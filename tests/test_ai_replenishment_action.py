"""补货申请提案：槽位解析、唯一产品、快照和事务边界。"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errors import BusinessValidationError
from app.modules.ai import action_handlers, schema
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.replenishments import service as replenishment_service
from app.modules.suppliers.model import Supplier


class _DB:
    def __init__(self):
        self.gets = {}
        self.scalars = []

    def get(self, model, object_id):
        return self.gets.get((model, object_id))

    def scalar(self, _query):
        return self.scalars.pop(0)


def _entities():
    supplier = SimpleNamespace(id=3, supplier_code="SUP-26001", supplier_name="华东精细化工", status="ACTIVE")
    product = SimpleNamespace(id=318, product_code="PRD-ETHANOL-AR", product_name="无水乙醇",
                              status="ACTIVE", version_no=2, unit_id=2)
    unit = SimpleNamespace(id=2, unit_name="升", dimension="VOLUME", status="ACTIVE")
    return supplier, product, unit


def _patch_tools(monkeypatch):
    from app.modules.ai import agent_tools

    monkeypatch.setattr(agent_tools, "list_tools", lambda *_args: [{"name": "catalog.search_products"}])

    def execute_tool(_db, _user, call):
        if call.tool == "catalog.search_products":
            return SimpleNamespace(rows=[SimpleNamespace(product_id=318)], total_rows=1, truncated=False)
        return SimpleNamespace(model_dump=lambda **_kwargs: {
            "scope": "当前用户可访问仓库", "observed_at": "2026-10-25T03:00:00+00:00",
            "totals": [{"unit_name": "升", "available_quantity": "1954"}], "sources": [],
        })

    monkeypatch.setattr(agent_tools, "execute_tool", execute_tool)


def _patch_entities(monkeypatch, db):
    supplier, product, unit = _entities()
    db.gets[(Product, 318)] = product
    db.gets[(Unit, 2)] = unit
    monkeypatch.setattr(action_handlers, "get_supplier_by_code", lambda *_args: supplier)
    _patch_tools(monkeypatch)
    return supplier, product, unit


def test_prepare_builds_draft_payload_and_evidence(monkeypatch):
    db = _DB()
    supplier, product, unit = _patch_entities(monkeypatch, db)
    handler = action_handlers.ReplenishmentCreateHandler()
    prepared = handler.prepare(db, SimpleNamespace(id=5, status="ACTIVE"), {
        "supplier_code": "SUP-26001",
        "product_keyword": "PRD-ETHANOL-AR",
        "quantity": "200",
        "reason": "低于安全库存",
        "expected_date": "2026-10-31",
    })

    assert prepared["payload"] == {
        "supplier_id": 3, "reason": "低于安全库存",
        "items": [{"product_id": 318, "unit_id": 2, "requested_quantity": "200",
                   "expected_date": "2026-10-31", "note": None}],
    }
    assert prepared["snapshot"]["supplier"]["supplier_code"] == "SUP-26001"
    assert prepared["snapshot"]["product"]["version_no"] == 2
    assert [entry["type"] for entry in prepared["evidence"]] == ["supplier", "product", "inventory"]
    assert prepared["risk_level"] == "MEDIUM"
    assert prepared["resource_id"] is None


def test_prepare_requires_unique_product_and_positive_quantity(monkeypatch):
    db = _DB()
    _patch_entities(monkeypatch, db)
    from app.modules.ai import agent_tools
    monkeypatch.setattr(agent_tools, "execute_tool",
                        lambda *_args, **_kwargs: SimpleNamespace(rows=[SimpleNamespace(product_id=318)],
                                                                  total_rows=2, truncated=False))
    handler = action_handlers.ReplenishmentCreateHandler()
    user = SimpleNamespace(id=5, status="ACTIVE")
    with pytest.raises(BusinessValidationError, match="唯一的产品"):
        handler.prepare(db, user, {"supplier_code": "SUP-26001", "product_keyword": "乙醇",
                                   "quantity": "10", "reason": "低库存"})

    _patch_tools(monkeypatch)
    with pytest.raises(BusinessValidationError, match="正数"):
        handler.prepare(db, user, {"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR",
                                   "quantity": "0", "reason": "低库存"})
    with pytest.raises(BusinessValidationError, match="不允许的字段"):
        handler.prepare(db, user, {"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR",
                                   "quantity": "10", "reason": "低库存", "product_id": 318})


def test_validate_current_rejects_changed_product(monkeypatch):
    db = _DB()
    supplier, product, unit = _patch_entities(monkeypatch, db)
    handler = action_handlers.ReplenishmentCreateHandler()
    user = SimpleNamespace(id=5, status="ACTIVE")
    prepared = handler.prepare(db, user, {"supplier_code": "SUP-26001",
                                          "product_keyword": "PRD-ETHANOL-AR",
                                          "quantity": "200", "reason": "低于安全库存"})
    proposal = SimpleNamespace(payload=prepared["payload"],
                               expected_resource_snapshot=prepared["snapshot"])

    db.scalars = [supplier, product, unit]
    handler.validate_current(db, user, proposal, for_update=False)
    product.version_no = 3
    db.scalars = [supplier, product, unit]
    with pytest.raises(BusinessValidationError, match="已变化"):
        handler.validate_current(db, user, proposal, for_update=False)


def test_execute_uses_domain_service_with_caller_transaction(monkeypatch):
    db = _DB()
    _patch_entities(monkeypatch, db)
    value = SimpleNamespace(
        id=77, replenishment_no="RP20261025000077", supplier_id=3, source_po_id=None,
        source_delivery_id=None, applicant_id=5, reason="低于安全库存", status="DRAFT",
        fulfillment_po_id=None, approved_by=None, approved_at=None, rejected_at=None,
        reject_reason=None, cancelled_at=None, completed_at=None,
        created_at=datetime(2026, 10, 25), updated_at=datetime(2026, 10, 25), items=[],
    )
    calls = []
    monkeypatch.setattr(replenishment_service, "create_replenishment",
                        lambda _db, _user, data, *, commit=True:
                        calls.append((data, commit)) or value)
    proposal = SimpleNamespace(payload={
        "supplier_id": 3, "reason": "低于安全库存",
        "items": [{"product_id": 318, "unit_id": 2, "requested_quantity": "200",
                   "expected_date": None, "note": None}],
    })
    result = action_handlers.ReplenishmentCreateHandler().execute(
        db, SimpleNamespace(id=5, status="ACTIVE"), proposal, commit=False)

    assert calls[0][1] is False
    assert calls[0][0].items[0].requested_quantity == Decimal("200")
    assert result["replenishment_no"] == "RP20261025000077"
    assert result["status"] == "DRAFT"


def test_replenishment_understanding_requires_slots_and_safe_fields():
    with pytest.raises(ValueError):
        schema.Understanding(purpose="replenishment_draft",
                             slots={"product_keyword": "PRD-ETHANOL-AR"},
                             action_fields={"quantity": 10, "reason": "低库存"})
    with pytest.raises(ValueError):
        schema.Understanding(purpose="replenishment_draft",
                             slots={"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR"},
                             action_fields={"quantity": 10})
    with pytest.raises(ValueError):
        schema.Understanding(purpose="replenishment_draft",
                             slots={"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR"},
                             action_fields={"quantity": 10, "reason": "低库存", "supplier_id": 3})
    with pytest.raises(ValueError):
        schema.Understanding(purpose="replenishment_draft",
                             slots={"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR"},
                             action_fields={"quantity": 0, "reason": "低库存"})

    valid = schema.Understanding(purpose="replenishment_draft",
                                 slots={"supplier_code": "SUP-26001", "product_keyword": "PRD-ETHANOL-AR"},
                                 action_fields={"quantity": 200, "reason": "低于安全库存",
                                                "expected_date": "2026-10-31"})
    assert valid.route == "replenishment_draft"
    assert valid.action_fields == {"quantity": Decimal("200"), "reason": "低于安全库存",
                                   "expected_date": "2026-10-31"}
