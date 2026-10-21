"""问题清单第一批整改：真实数据库事务内验证数据与授权边界。"""
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.core.idempotency import IdempotencyMiddleware, MAX_IDEMPOTENCY_REQUEST_BYTES
from app.modules.inventory.model import InventoryBalance, InventoryBatch, InventoryTransaction, InventoryStocktakeRequest, InventoryStocktakeItem
from app.modules.inventory_cost.model import InventoryCostLayer
from app.modules.inventory_cost.service import allocate_outbound_cost, adjust_stocktake_cost
from app.modules.inventory import service as inventory_service
from app.modules.system import service as system_service
from app.modules.system.model import Role, User
from app.modules.system.audit import AuditLog
from app.modules.system.schema import UserUpdate, UserCreate
from app.modules.files import service as file_service


def stock_fixture(db):
    source = db.scalar(select(InventoryBalance).where(InventoryBalance.quantity > 0).limit(1))
    actor = db.scalar(select(User).where(User.username == "system_admin"))
    assert source is not None and actor is not None
    batch = InventoryBatch(product_id=source.product_id, batch_no=f"REMED-{uuid4().hex[:12]}")
    db.add(batch)
    db.flush()
    slot = dict(product_id=source.product_id, warehouse_id=source.warehouse_id,
                location_id=source.location_id, unit_id=source.unit_id, batch_id=batch.id)
    return actor, slot


def transaction(db, actor, slot, quantity="10"):
    tx = InventoryTransaction(**slot, transaction_no=f"RT-{uuid4().hex[:20]}",
                              transaction_type="ADJUSTMENT", quantity=Decimal(quantity), operator_id=actor.id)
    db.add(tx)
    db.flush()
    return tx


def layer(db, actor, slot, quantity="10", cost="8"):
    tx = transaction(db, actor, slot, quantity)
    value = InventoryCostLayer(**slot, source_transaction_id=tx.id, original_quantity=Decimal(quantity),
                               remaining_quantity=Decimal(quantity), unit_cost=Decimal(cost), currency_code="CNY")
    db.add(value)
    db.flush()
    return value


def test_outbound_never_consumes_another_batch(db_session):
    actor, slot = stock_fixture(db_session)
    own = layer(db_session, actor, slot, cost="9")
    other_batch = InventoryBatch(product_id=slot["product_id"], batch_no=f"OTHER-{uuid4().hex[:12]}")
    db_session.add(other_batch)
    db_session.flush()
    other = layer(db_session, actor, {**slot, "batch_id": other_batch.id}, cost="2")
    tx = transaction(db_session, actor, {**slot, "batch_id": other_batch.id}, "3")
    assert allocate_outbound_cost(db_session, tx, Decimal("3")) == Decimal("6")
    assert other.remaining_quantity == Decimal("7")
    assert own.remaining_quantity == Decimal("10")
    with pytest.raises(BusinessValidationError, match="成本层不足"):
        allocate_outbound_cost(db_session, tx, Decimal("8"))


@pytest.mark.parametrize("counted", ["7", "13"])
def test_stocktake_keeps_cost_quantity_equal_to_balance(db_session, counted):
    actor, slot = stock_fixture(db_session)
    balance = InventoryBalance(**slot, quantity=Decimal("10"), locked_quantity=0, status="AVAILABLE")
    db_session.add(balance)
    layer(db_session, actor, slot, quantity="4", cost="5")
    layer(db_session, actor, slot, quantity="6", cost="7")
    request = InventoryStocktakeRequest(stocktake_no=f"ST-R-{uuid4().hex[:12]}", applicant_id=actor.id,
        warehouse_id=slot["warehouse_id"], location_id=slot["location_id"], purpose="成本盘点回归", status="APPROVED")
    request.items.append(InventoryStocktakeItem(line_no=1, product_id=slot["product_id"],
        location_id=slot["location_id"], batch_id=slot["batch_id"], unit_id=slot["unit_id"],
        book_quantity=Decimal("10"), counted_quantity=Decimal(counted), difference_quantity=0, status="PENDING"))
    db_session.add(request)
    db_session.flush()
    inventory_service.execute_stocktake_request(db_session, actor, request.id)
    cost_quantity = db_session.scalar(select(func.sum(InventoryCostLayer.remaining_quantity)).where(InventoryCostLayer.batch_id == slot["batch_id"]))
    assert cost_quantity == balance.quantity == Decimal(counted)
    if counted == "13":
        gain = db_session.scalar(select(InventoryCostLayer).where(InventoryCostLayer.batch_id == slot["batch_id"]).order_by(InventoryCostLayer.id.desc()))
        assert gain.unit_cost == Decimal("6.2")


def test_stocktake_gain_requires_cost_basis(db_session):
    actor, slot = stock_fixture(db_session)
    tx = transaction(db_session, actor, slot)
    with pytest.raises(BusinessValidationError, match="历史成本依据"):
        adjust_stocktake_cost(db_session, tx, Decimal("1"))


def test_historical_return_cost_repair_is_audited_and_idempotent(db_session):
    from scripts.repair_return_cost_batches import repair
    from app.modules.inventory_cost.model import InventoryCostAllocation
    actor, source = stock_fixture(db_session)
    wrong = layer(db_session, actor, source, cost="8")
    other_batch = InventoryBatch(product_id=source["product_id"], batch_no=f"REPAIR-{uuid4().hex[:12]}")
    db_session.add(other_batch); db_session.flush()
    target = {**source, "batch_id": other_batch.id}
    correct = layer(db_session, actor, target, cost="3")
    db_session.add_all([InventoryBalance(**source, quantity=10, locked_quantity=0, status="AVAILABLE"),
                       InventoryBalance(**target, quantity=8, locked_quantity=0, status="AVAILABLE")])
    tx = transaction(db_session, actor, target, "2")
    tx.source_type = "INVENTORY_RETURN"
    wrong.remaining_quantity = Decimal("8")
    allocation = InventoryCostAllocation(transaction_id=tx.id, cost_layer_id=wrong.id, quantity=2, unit_cost=8, total_cost=16)
    db_session.add(allocation); db_session.flush()
    reports = repair(db_session, actor.id)
    own = next(row for row in reports if row["transaction_id"] == tx.id)
    assert Decimal(own["new_cost"]) == 6
    assert allocation.cost_layer_id == correct.id
    assert wrong.remaining_quantity == 10 and correct.remaining_quantity == 8
    assert repair(db_session, actor.id) == []
    assert db_session.scalar(select(AuditLog.id).where(AuditLog.action_type == "REPAIR_COST_ALLOCATION", AuditLog.resource_id == tx.id)) is not None


@pytest.mark.parametrize("target", ["buyer", "warehouse_receiver"])
def test_delegated_user_manager_cannot_grant_admin(db_session, target):
    actor = db_session.scalar(select(User).where(User.username == "buyer"))
    user = db_session.scalar(select(User).where(User.username == target))
    admin = db_session.scalar(select(Role).where(Role.role_code == "SYS_ADMIN"))
    with pytest.raises(AuthorizationError):
        system_service.update_user(db_session, user.id, UserUpdate(role_ids=[admin.id]), actor_id=actor.id)
    with pytest.raises(AuthorizationError):
        system_service.create_user(db_session, UserCreate(username=f"denied-{uuid4().hex[:8]}", password="test-only-password", display_name="拒绝提权", role_ids=[admin.id]), actor_id=actor.id)
    with pytest.raises(AuthorizationError):
        system_service.require_authorization_admin(db_session, actor.id)


def test_user_update_audits_without_password(db_session):
    actor = db_session.scalar(select(User).where(User.username == "system_admin"))
    user = db_session.scalar(select(User).where(User.username == "buyer"))
    system_service.update_user(db_session, user.id, UserUpdate(display_name="审计回归"), actor_id=actor.id)
    log = db_session.scalar(select(AuditLog).where(AuditLog.resource_type == "USER", AuditLog.resource_id == user.id).order_by(AuditLog.id.desc()))
    assert log.actor_id == actor.id and "display_name" in log.request_summary
    assert "password_hash=" not in log.request_summary


def test_registration_quota_precedes_password_hash(db_session):
    ip = f"test-{uuid4().hex}"
    for _ in range(3):
        system_service.check_registration_rate(db_session, ip)
    with pytest.raises(HTTPException) as error:
        system_service.check_registration_rate(db_session, ip)
    assert error.value.status_code == 429
    system_service.check_registration_rate(db_session, f"other-{uuid4().hex}")


def test_unlinked_internal_file_is_not_enumerable(monkeypatch):
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    monkeypatch.setattr(file_service, "_is_system_admin", lambda *_: False)
    value = SimpleNamespace(id=1, access_level="INTERNAL", uploader_id=2)
    with pytest.raises(ResourceNotFoundError):
        file_service._check_file_access(db, SimpleNamespace(id=3), value)
    file_service._check_file_access(db, SimpleNamespace(id=2), value)


def test_download_reads_bounded_chunks_and_closes_stream(monkeypatch):
    import asyncio
    from io import BytesIO
    from app.modules.files.controller import download_file
    class TrackedStream(BytesIO):
        sizes = []
        closes = 0
        releases = 0
        def read(self, size=-1):
            self.sizes.append(size)
            return super().read(size)
        def close(self):
            self.closes += 1
            super().close()
        def release_conn(self):
            self.releases += 1
    stream = TrackedStream(b"x" * 200_000)
    monkeypatch.setattr(file_service, "open_download", lambda *_: (SimpleNamespace(mime_type="application/pdf", file_name="test.pdf"), stream))
    response = download_file(1, object(), object())
    assert not stream.sizes, "创建响应时不能提前读取文件"
    async def consume():
        data = [chunk async for chunk in response.body_iterator]
        await response.background()
        return data
    data = asyncio.run(consume())
    assert sum(map(len, data)) == 200_000
    assert all(size == 64 * 1024 for size in stream.sizes)
    assert stream.closes == stream.releases == 1


def test_cleanup_expired_idempotency_records_preserves_live_record(db_session, monkeypatch):
    from datetime import datetime, timedelta
    from app.modules.system.idempotency_model import IdempotencyRecord
    from app.core import idempotency
    now = datetime.now()
    expired = IdempotencyRecord(actor_key=uuid4().hex, idempotency_key=uuid4().hex,
        method="POST", path="/test", request_hash="x", status="COMPLETED", expires_at=now - timedelta(hours=1))
    live = IdempotencyRecord(actor_key=uuid4().hex, idempotency_key=uuid4().hex,
        method="POST", path="/test", request_hash="x", status="COMPLETED", expires_at=now + timedelta(hours=1))
    db_session.add_all([expired, live]); db_session.flush()
    class SharedSession:
        def __enter__(self): return db_session
        def __exit__(self, *_): pass
    monkeypatch.setattr(idempotency, "SessionLocal", SharedSession)
    assert idempotency.cleanup_expired_records() >= 1
    assert db_session.scalar(select(IdempotencyRecord.id).where(IdempotencyRecord.id == expired.id)) is None
    assert db_session.scalar(select(IdempotencyRecord.id).where(IdempotencyRecord.id == live.id)) == live.id


def test_idempotency_multipart_is_never_read(monkeypatch):
    import asyncio
    from starlette.requests import Request
    from starlette.responses import Response
    async def receive():
        pytest.fail("幂等层不能读取 multipart 请求体")
    request = Request({"type": "http", "method": "POST", "path": "/files", "headers": [(b"content-type", b"multipart/form-data; boundary=x"), (b"idempotency-key", b"test")]}, receive)
    async def next_request(_):
        return Response(status_code=204)
    response = asyncio.run(IdempotencyMiddleware(lambda *_: None).dispatch(request, next_request))
    assert response.status_code == 204


@pytest.mark.parametrize("declared", [True, False])
def test_idempotency_rejects_oversize_body_before_db(declared):
    import asyncio
    from starlette.requests import Request
    headers = [(b"idempotency-key", b"test")]
    if declared:
        headers.append((b"content-length", str(MAX_IDEMPOTENCY_REQUEST_BYTES + 1).encode()))
    async def receive():
        assert not declared, "声明超限时不应读取 body"
        return {"type": "http.request", "body": b"x" * (MAX_IDEMPOTENCY_REQUEST_BYTES + 1), "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/write", "headers": headers}, receive)
    async def next_request(_):
        pytest.fail("超限请求不能到达业务端点")
    response = asyncio.run(IdempotencyMiddleware(lambda *_: None).dispatch(request, next_request))
    assert response.status_code == 413
