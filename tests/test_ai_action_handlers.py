from types import SimpleNamespace

import pytest

from app.modules.purchase_requests import service
from app.modules.purchase_requests.schema import PurchaseRequestUpdate
from app.modules.rfqs import service as rfq_service
from app.modules.rfqs.schema import RFQCreate, RFQItemCreate


class _DB:
    def __init__(self):
        self.commits = 0
        self.flushes = 0

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1


def test_create_draft_catalog_validation_uses_product_code_with_valid_limit(monkeypatch):
    from app.modules.ai import action_handlers, agent_tools
    from app.modules.products.model import Product

    product = SimpleNamespace(id=9, product_code="PRD-ETHANOL-AR", status="ACTIVE")
    db = _DB()
    db.get = lambda model, _id: product if model is Product else None
    calls = []
    monkeypatch.setattr(agent_tools, "list_tools", lambda *_args: [{"name": "catalog.search_products"}])

    def execute_tool(_db, _user, call):
        calls.append(call)
        assert 1 <= call.arguments["limit"] <= 20
        return SimpleNamespace(rows=[SimpleNamespace(product_id=9)])

    monkeypatch.setattr(agent_tools, "execute_tool", execute_tool)
    action_handlers._validate_catalog_product_candidates(
        db, SimpleNamespace(id=5), [SimpleNamespace(product_id=9)])
    assert calls[0].arguments == {"keyword": "PRD-ETHANOL-AR", "limit": 10}


def test_update_request_flushes_without_committing_when_used_by_action_transaction(monkeypatch):
    request = SimpleNamespace(id=8, status="DRAFT", purpose="旧用途", items=[])
    db = _DB()
    monkeypatch.setattr(service, "get_request_for_write", lambda *_args, **_kwargs: request)
    monkeypatch.setattr(service, "_audit", lambda *_args: None)
    result = service.update_request(db, SimpleNamespace(id=5), 8, PurchaseRequestUpdate(purpose="新用途"), commit=False)
    assert result.purpose == "新用途"
    assert db.flushes == 1
    assert db.commits == 0


def test_submit_request_flushes_without_committing_when_used_by_action_transaction(monkeypatch):
    request = SimpleNamespace(id=8, status="DRAFT", items=[object()], approvals=[], submitted_at=None,
                              rejected_at=None, cancelled_at=None, cancel_reason=None)
    db = _DB()
    monkeypatch.setattr(service, "get_request_for_write", lambda *_args, **_kwargs: request)
    monkeypatch.setattr(service.crud, "delete_approvals", lambda *_args: None)
    monkeypatch.setattr(service, "_validate_items", lambda *_args: None)
    monkeypatch.setattr(service, "_audit", lambda *_args: None)
    result = service.submit_request(db, SimpleNamespace(id=5), 8, commit=False)
    assert result.status == "APPROVING"
    assert len(result.approvals) == 1
    assert db.flushes == 1
    assert db.commits == 0


def test_create_rfq_flushes_without_committing_when_used_by_action_transaction(monkeypatch):
    from app.modules.purchase_requests import service as request_service
    monkeypatch.setattr(request_service, "_validate_department_scope", lambda *_args: None)
    class RFQDB(_DB):
        def add(self, row):
            self.row = row

        def flush(self):
            self.flushes += 1
            self.row.id = 91

    db = RFQDB()
    monkeypatch.setattr(rfq_service, "get_scoped_purchase_request", lambda *_args: None)
    monkeypatch.setattr(rfq_service, "_validate_item_refs", lambda *_args: None)
    monkeypatch.setattr(rfq_service, "_validate_suppliers", lambda *_args: None)
    monkeypatch.setattr(rfq_service, "add_audit_log", lambda *_args, **_kwargs: None)
    data = RFQCreate(items=[RFQItemCreate(requested_name="乙醇", quantity=1, unit_id=3)], supplier_ids=[7])
    created = rfq_service.create_rfq(db, SimpleNamespace(id=5, department_id=None), data, commit=False)
    assert isinstance(created, rfq_service.RFQ)
    assert created.rfq_no.startswith("RFQ")
    assert db.flushes == 1
    assert db.commits == 0


def _source_request(status="APPROVED"):
    source_item = SimpleNamespace(id=12, line_no=1, product_id=31, requested_name="乙醇", technical_requirements=None,
                                  quantity=5, unit_id=4, budget_price=None, expected_date=None)
    return SimpleNamespace(id=9, request_no="PR-009", updated_at=None, status=status, department_id=2,
                           applicant_id=5, purpose="实验", priority="NORMAL", budget_amount=None,
                           currency_code="CNY", expected_date=None, items=[source_item])


def test_rfq_handler_requires_visible_approved_source_and_creates_only_a_preview(monkeypatch):
    from app.core.errors import BusinessValidationError
    from app.modules.ai import action_handlers
    from app.modules.purchase_requests import service as request_service
    from app.modules.rfqs import service as rfq_service
    from app.modules.system import crud as system_crud
    from app.modules.rfqs.schema import RFQCreate

    monkeypatch.setattr(request_service, "get_request", lambda *_args: _source_request("DRAFT"))
    monkeypatch.setattr(system_crud, "get_user_permission_codes", lambda *_args: ["master.suppliers.read"])
    monkeypatch.setattr(system_crud, "get_user_role_codes", lambda *_args: [])
    monkeypatch.setattr(rfq_service, "_validate_item_refs", lambda *_args: None)
    monkeypatch.setattr(rfq_service, "_validate_suppliers", lambda *_args: None)
    handler = action_handlers.RFQCreateDraftHandler()
    data = RFQCreate(source_request_id=9, items=[{"source_request_item_id": 12, "product_id": 31,
        "requested_name": "乙醇", "quantity": 2, "unit_id": 4}], supplier_ids=[7])
    with pytest.raises(BusinessValidationError, match="已审批"):
        handler.prepare(SimpleNamespace(), SimpleNamespace(id=5), data.model_dump(mode="json"))


def test_rfq_handler_requires_supplier_directory_permission(monkeypatch):
    from app.core.errors import BusinessValidationError
    from app.modules.ai import action_handlers
    from app.modules.system import crud as system_crud
    from app.modules.rfqs.schema import RFQCreate

    monkeypatch.setattr(system_crud, "get_user_permission_codes", lambda *_args: [])
    monkeypatch.setattr(system_crud, "get_user_role_codes", lambda *_args: [])
    data = RFQCreate(source_request_id=9, items=[{"source_request_item_id": 12, "product_id": 31,
        "requested_name": "乙醇", "quantity": 2, "unit_id": 4}], supplier_ids=[7])
    with pytest.raises(BusinessValidationError, match="供应商目录"):
        action_handlers.RFQCreateDraftHandler().prepare(SimpleNamespace(), SimpleNamespace(id=5), data.model_dump(mode="json"))
