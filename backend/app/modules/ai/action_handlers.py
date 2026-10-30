"""服务端明确注册的 Agent 写动作处理器。"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai.formatting import format_decimal
from app.modules.products.model import Product
from app.modules.purchase_requests import service as purchase_request_service
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.purchase_requests.model import Unit
from app.modules.purchase_requests.schema import PurchaseRequestCreate, PurchaseRequestUpdate, PurchaseRequestRead
from app.modules.operation_exceptions import service as exception_service
from app.modules.operation_exceptions.schema import OperationTaskCreate, OperationTaskRead
from app.modules.purchase_orders import service as purchase_order_service
from app.modules.purchase_orders.model import PurchaseOrder
from app.modules.purchase_orders.schema import PurchaseOrderCreate, PurchaseOrderRead
from app.modules.replenishments import service as replenishment_service
from app.modules.replenishments.schema import ReplenishmentCreate, ReplenishmentItemCreate, ReplenishmentRead
from app.modules.system.model import User
from app.modules.suppliers.model import Supplier
from app.modules.suppliers.service import get_supplier_by_code
from sqlalchemy import select


class ActionHandler(Protocol):
    permission_code: str
    resource_type: str | None

    def prepare(self, db, user, payload: dict[str, Any]) -> dict[str, Any]: ...

    def validate_current(self, db, user, proposal, *, for_update: bool = True) -> None: ...

    def execute(self, db, user, proposal, *, commit: bool = False) -> dict[str, Any]: ...


_HANDLERS: dict[str, ActionHandler] = {}


def register_handler(action_type: str, handler: ActionHandler) -> None:
    if not action_type or action_type in _HANDLERS:
        raise ValueError(f"动作处理器已注册或类型无效：{action_type}")
    _HANDLERS[action_type] = handler


def clear_handlers() -> None:
    """测试和应用装配使用；不暴露给客户端。"""
    _HANDLERS.clear()


def get_handler(action_type: str) -> ActionHandler:
    try:
        return _HANDLERS[action_type]
    except KeyError:
        raise BusinessValidationError("不支持该 Agent 动作类型") from None


def registered_action_types() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


def required_permissions(action_type: str) -> set[str]:
    """能力声明与提案执行共用的动作权限集合。"""
    required = {get_handler(action_type).permission_code}
    if action_type == "rfq.create_draft":
        required.add("master.suppliers.read")
    if action_type == "purchase_order.create_draft":
        required.add("procurement.rfqs.read")
    if action_type == "deliveries.followup_draft":
        required.add("procurement.orders.read")
    return required


def _request_snapshot(request: PurchaseRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
        "status": request.status,
        "department_id": request.department_id,
        "applicant_id": request.applicant_id,
        "purpose": request.purpose,
        "priority": request.priority,
        "budget_amount": str(request.budget_amount) if request.budget_amount is not None else None,
        "currency_code": request.currency_code,
        "expected_date": request.expected_date.isoformat() if request.expected_date else None,
        "items": [
            {"id": item.id, "line_no": item.line_no, "product_id": item.product_id,
             "requested_name": item.requested_name, "technical_requirements": item.technical_requirements,
             "quantity": str(item.quantity), "unit_id": item.unit_id,
             "budget_price": str(item.budget_price) if item.budget_price is not None else None,
             "expected_date": item.expected_date.isoformat() if item.expected_date else None}
            for item in request.items
        ],
    }


def _item_reference_snapshot(db, items, *, for_update: bool = False) -> dict[str, dict]:
    products: dict[str, dict] = {}
    units: dict[str, dict] = {}
    for item in items:
        if item.product_id is not None:
            query = select(Product).where(Product.id == item.product_id)
            product = db.scalar(query.with_for_update() if for_update else query)
            if product is None or product.status != "ACTIVE":
                raise BusinessValidationError(f"产品 {item.product_id} 不存在或已停用")
            products[str(product.id)] = {"status": product.status, "version_no": product.version_no}
        query = select(Unit).where(Unit.id == item.unit_id)
        unit = db.scalar(query.with_for_update() if for_update else query)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError(f"计量单位 {item.unit_id} 不存在或已停用")
        units[str(unit.id)] = {"status": unit.status, "unit_name": unit.unit_name, "dimension": unit.dimension}
    return {"products": products, "units": units}


def _validate_catalog_product_candidates(db, user, items, existing_product_ids: set[int] | None = None) -> None:
    existing_product_ids = existing_product_ids or set()
    for item in items:
        if item.product_id is None or item.product_id in existing_product_ids:
            continue
        from app.modules.ai import agent_tools
        from app.modules.ai.schema import ToolCall

        available = {entry["name"] for entry in agent_tools.list_tools(db, user)}
        if "catalog.search_products" not in available:
            raise BusinessValidationError("当前账号不能将产品目录记录关联到采购申请")
        product = db.get(Product, item.product_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError("关联产品不存在或已停用")
        candidates = agent_tools.execute_tool(db, user, ToolCall(
            tool="catalog.search_products", arguments={"keyword": product.product_code, "limit": 10}))
        if item.product_id not in {row.product_id for row in candidates.rows}:
            raise BusinessValidationError("关联产品必须来自当前用户可访问的产品目录候选")


def _resolve_purchase_request(db, user, payload, allowed_keys: set[str]) -> PurchaseRequest:
    keys = set(payload)
    if keys != allowed_keys | {"request_id"} and keys != allowed_keys | {"request_no"}:
        raise BusinessValidationError("采购申请提案必须提供准确的申请编号及动作字段")
    if "request_id" in payload:
        request_id = payload["request_id"]
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id <= 0:
            raise BusinessValidationError("采购申请编号无效")
        return purchase_request_service.get_request(db, user, request_id)
    request_no = payload["request_no"]
    if not isinstance(request_no, str) or not request_no.strip() or len(request_no) > 32:
        raise BusinessValidationError("请提供准确的采购申请编号")
    request = purchase_request_service.get_request_by_no(db, user, request_no.strip())
    if request is None:
        raise ResourceNotFoundError("采购申请不存在或不属于当前用户的数据范围")
    return request


class PurchaseRequestCreateHandler:
    permission_code = "procurement.requests.write"
    resource_type = "PURCHASE_REQUEST"

    def prepare(self, db, user, payload):
        data = PurchaseRequestCreate.model_validate(payload)
        if data.department_id is not None and data.department_id != user.department_id:
            roles = set(__import__("app.modules.system.crud", fromlist=["get_user_role_codes"]).get_user_role_codes(db, user.id))
            if not roles.intersection({"SYS_ADMIN", "PROCUREMENT_MANAGER"}):
                raise BusinessValidationError("采购申请部门必须属于当前用户的数据范围")
        normalized = data.model_dump(mode="json")
        normalized["department_id"] = data.department_id or user.department_id
        refs = _item_reference_snapshot(db, data.items)
        _validate_catalog_product_candidates(db, user, data.items)
        for item in data.items:
            if item.product_id is not None:
                product = db.scalar(select(Product).where(Product.id == item.product_id))
                if product.unit_id != item.unit_id:
                    raise BusinessValidationError("采购申请计量单位必须与产品目录单位一致")
        preview_diff = [{"field": field, "before": None, "after": normalized.get(field)}
                        for field in ("purpose", "priority", "budget_amount", "currency_code", "expected_date")]
        preview_diff.append({"field": "items", "before": None, "after": [
            {"requested_name": item["requested_name"], "quantity": item["quantity"], "unit_id": item["unit_id"]}
            for item in normalized["items"]]})
        return {"payload": normalized, "snapshot": {"department_id": user.department_id, **refs},
                "resource_id": None, "diff": preview_diff,
                "evidence": [], "warnings": [], "blockers": [], "risk_level": "LOW"}

    def validate_current(self, db, user, proposal, *, for_update=True):
        if proposal.expected_resource_snapshot.get("department_id") != user.department_id:
            raise BusinessValidationError("当前用户部门已变化，请重新生成预览")
        for product_id, expected in proposal.expected_resource_snapshot.get("products", {}).items():
            query = select(Product).where(Product.id == int(product_id))
            product = db.scalar(query.with_for_update() if for_update else query)
            if product is None or product.status != "ACTIVE" or product.status != expected["status"] or product.version_no != expected["version_no"]:
                raise BusinessValidationError("关联产品状态或版本已变化，请重新生成预览")
        for unit_id, expected in proposal.expected_resource_snapshot.get("units", {}).items():
            query = select(Unit).where(Unit.id == int(unit_id))
            unit = db.scalar(query.with_for_update() if for_update else query)
            if unit is None or unit.status != "ACTIVE" or unit.unit_name != expected["unit_name"] or unit.dimension != expected["dimension"]:
                raise BusinessValidationError("关联计量单位状态或信息已变化，请重新生成预览")

    def execute(self, db, user, proposal, *, commit=False):
        request = purchase_request_service.create_request(db, user, PurchaseRequestCreate.model_validate(proposal.payload), commit=commit)
        return PurchaseRequestRead.model_validate(request).model_dump(mode="json")


class PurchaseRequestUpdateHandler:
    permission_code = "procurement.requests.write"
    resource_type = "PURCHASE_REQUEST"

    def prepare(self, db, user, payload):
        if not isinstance(payload, dict) or (set(payload) not in ({"request_id", "changes"}, {"request_no", "changes"})):
            raise BusinessValidationError("修改申请提案必须包含申请编号和字段变更")
        request = _resolve_purchase_request(db, user, payload, {"changes"})
        request = purchase_request_service.get_request_for_write(db, user, request.id)
        request_id = request.id
        if request.status not in {"DRAFT", "REJECTED"}:
            raise BusinessValidationError("只有草稿或已驳回的采购申请可以修改")
        allowed = set(PurchaseRequestUpdate.model_fields)
        if not isinstance(payload["changes"], dict) or set(payload["changes"]) - allowed:
            raise BusinessValidationError("采购申请修改包含不允许的字段")
        changes = PurchaseRequestUpdate.model_validate(payload["changes"])
        values = changes.model_dump(exclude_unset=True, mode="json")
        if not values:
            raise BusinessValidationError("请提供至少一个需要修改的字段")
        current = _request_snapshot(request)
        updated_items = changes.items if changes.items is not None else request.items
        purchase_request_service._validate_items(db, updated_items)
        original_product_ids = {item.product_id for item in request.items if item.product_id is not None}
        _validate_catalog_product_candidates(db, user, updated_items, original_product_ids)
        refs = _item_reference_snapshot(db, updated_items)
        return {"payload": {"request_id": request_id, "changes": values}, "snapshot": {"request": current, "refs": refs},
                "resource_id": request_id,
                "diff": [{"field": field, "before": current.get(field), "after": value} for field, value in values.items()],
                "evidence": [{"type": "purchase_request", "id": request_id, "request_no": request.request_no}],
                "warnings": [], "blockers": [], "risk_level": "LOW"}

    def validate_current(self, db, user, proposal, *, for_update=True):
        request = purchase_request_service.get_request_for_write(db, user, int(proposal.resource_id), for_update=for_update)
        if request.status not in {"DRAFT", "REJECTED"} or _request_snapshot(request) != proposal.expected_resource_snapshot["request"]:
            raise BusinessValidationError("采购申请状态或内容已变化，请重新生成预览")
        updated = PurchaseRequestUpdate.model_validate(proposal.payload["changes"])
        item_values = updated.items if updated.items is not None else request.items
        purchase_request_service._validate_items(db, item_values)
        if _item_reference_snapshot(db, item_values, for_update=for_update) != proposal.expected_resource_snapshot["refs"]:
            raise BusinessValidationError("采购申请关联的产品或单位已变化，请重新生成预览")

    def execute(self, db, user, proposal, *, commit=False):
        request = purchase_request_service.update_request(
            db, user, int(proposal.resource_id), PurchaseRequestUpdate.model_validate(proposal.payload["changes"]), commit=commit)
        return PurchaseRequestRead.model_validate(request).model_dump(mode="json")


class PurchaseRequestSubmitHandler:
    permission_code = "procurement.requests.write"
    resource_type = "PURCHASE_REQUEST"

    def prepare(self, db, user, payload):
        if not isinstance(payload, dict) or set(payload) not in ({"request_id"}, {"request_no"}):
            raise BusinessValidationError("提交申请提案必须包含准确的申请编号")
        request = _resolve_purchase_request(db, user, payload, set())
        request = purchase_request_service.get_request_for_write(db, user, request.id)
        request_id = request.id
        if request.status not in {"DRAFT", "REJECTED"}:
            raise BusinessValidationError("只有草稿或已驳回的采购申请可以提交")
        if not request.items:
            raise BusinessValidationError("采购申请至少需要一条明细")
        purchase_request_service._validate_items(db, request.items)
        snapshot = _request_snapshot(request)
        return {"payload": {"request_id": request_id}, "snapshot": snapshot, "resource_id": request_id,
                "diff": [{"field": "status", "before": request.status, "after": "APPROVING"}],
                "evidence": [{"type": "purchase_request", "id": request_id, "request_no": request.request_no}],
                "warnings": [], "blockers": [], "risk_level": "MEDIUM"}

    def validate_current(self, db, user, proposal, *, for_update=True):
        request = purchase_request_service.get_request_for_write(db, user, int(proposal.resource_id), for_update=for_update)
        if request.status not in {"DRAFT", "REJECTED"} or _request_snapshot(request) != proposal.expected_resource_snapshot:
            raise BusinessValidationError("采购申请状态或内容已变化，请重新检查")
        if not request.items:
            raise BusinessValidationError("采购申请至少需要一条明细")
        purchase_request_service._validate_items(db, request.items)

    def execute(self, db, user, proposal, *, commit=False):
        request = purchase_request_service.submit_request(db, user, int(proposal.resource_id), commit=commit)
        return PurchaseRequestRead.model_validate(request).model_dump(mode="json")


register_handler("purchase_request.create_draft", PurchaseRequestCreateHandler())
register_handler("purchase_request.update_draft", PurchaseRequestUpdateHandler())
register_handler("purchase_request.submit", PurchaseRequestSubmitHandler())


class RFQCreateDraftHandler:
    permission_code = "procurement.rfqs.write"
    resource_type = "RFQ"

    def prepare(self, db, user, payload):
        from app.modules.purchase_requests import service as request_service
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import RFQCreate, RFQItemCreate
        from app.modules.system.crud import get_user_permission_codes, get_user_role_codes

        selected_supplier_codes: list[str] = []
        if isinstance(payload, dict) and "source_request_no" in payload:
            allowed = {"source_request_no", "supplier_codes", "quote_deadline", "requested_delivery_date", "delivery_requirements"}
            if set(payload) - allowed:
                raise BusinessValidationError("询价提案包含不允许的字段")
            source_no = payload.get("source_request_no")
            if not isinstance(source_no, str) or not source_no.strip() or len(source_no) > 32:
                raise BusinessValidationError("请提供准确的来源采购申请编号")
            source_for_lines = request_service.get_request_by_no(db, user, source_no.strip())
            if source_for_lines is None:
                raise ResourceNotFoundError("来源采购申请不存在或不属于当前用户的数据范围")
            codes = payload.get("supplier_codes")
            if not isinstance(codes, list) or not codes or any(not isinstance(code, str) or not code.strip() for code in codes):
                raise BusinessValidationError("请提供用户明确指定的供应商编码")
            selected_supplier_codes = [code.strip() for code in codes]
            if len(set(selected_supplier_codes)) != len(selected_supplier_codes):
                raise BusinessValidationError("供应商编码不能重复")
            from app.modules.ai import agent_tools
            from app.modules.ai.schema import ToolCall
            supplier_ids = []
            for supplier_code in selected_supplier_codes:
                supplier_result = agent_tools.execute_tool(db, user, ToolCall(
                    tool="suppliers.get_by_code", arguments={"supplier_code": supplier_code}))
                if supplier_result.total_rows != 1 or len(supplier_result.sources) != 1:
                    raise ResourceNotFoundError(f"供应商编码 {supplier_code} 不存在或当前用户不可见")
                supplier_ids.append(supplier_result.sources[0].record_id)
            payload = {
                "source_request_id": source_for_lines.id,
                "quote_deadline": payload.get("quote_deadline"),
                "requested_delivery_date": payload.get("requested_delivery_date"),
                "delivery_requirements": payload.get("delivery_requirements"),
                "items": [{
                    "source_request_item_id": item.id,
                    "product_id": item.product_id,
                    "requested_name": item.requested_name,
                    "quantity": item.quantity,
                    "unit_id": item.unit_id,
                    "required_delivery_date": item.expected_date,
                    "technical_requirements": item.technical_requirements,
                } for item in source_for_lines.items],
                "supplier_ids": supplier_ids,
            }
        data = RFQCreate.model_validate(payload)
        if data.source_request_id is None:
            raise BusinessValidationError("询价草稿必须关联一张已审批采购申请")
        supplier_permissions = set(get_user_permission_codes(db, user.id))
        supplier_roles = set(get_user_role_codes(db, user.id))
        if "SYS_ADMIN" not in supplier_roles and "master.suppliers.read" not in supplier_permissions:
            raise BusinessValidationError("当前账号不能读取可邀请供应商目录")
        source = request_service.get_request(db, user, data.source_request_id)
        if source.status != "APPROVED":
            raise BusinessValidationError("只有当前用户可见且已审批的采购申请才能创建询价草稿")
        source_items = {item.id: item for item in source.items}
        for item in data.items:
            if item.source_request_item_id is None or item.source_request_item_id not in source_items:
                raise BusinessValidationError("询价明细必须引用来源采购申请中的明细")
            source_item = source_items[item.source_request_item_id]
            if item.product_id != source_item.product_id or item.unit_id != source_item.unit_id:
                raise BusinessValidationError("询价产品和单位必须与来源申请明细一致")
            if item.quantity > source_item.quantity:
                raise BusinessValidationError("询价数量不能超过来源申请数量")
        rfq_service._validate_item_refs(db, data.items, data.source_request_id)
        rfq_service._validate_suppliers(db, data.supplier_ids)
        supplier_snapshot = {}
        for supplier_id in data.supplier_ids:
            supplier = db.scalar(select(Supplier).where(Supplier.id == supplier_id))
            supplier_snapshot[str(supplier_id)] = {"status": supplier.status}
        product_snapshot = {}
        unit_snapshot = {}
        for item in data.items:
            if item.product_id is not None:
                product = db.scalar(select(Product).where(Product.id == item.product_id))
                product_snapshot[str(product.id)] = {"status": product.status, "version_no": product.version_no}
            unit = db.scalar(select(Unit).where(Unit.id == item.unit_id))
            unit_snapshot[str(unit.id)] = {"status": unit.status, "unit_name": unit.unit_name, "dimension": unit.dimension}
        normalized = data.model_dump(mode="json")
        supplier_evidence = []
        for supplier_id in data.supplier_ids:
            supplier = db.scalar(select(Supplier).where(Supplier.id == supplier_id))
            supplier_evidence.append({"supplier_id": supplier_id, "supplier_code": supplier.supplier_code,
                                      "supplier_name": supplier.supplier_name})
        return {"payload": normalized,
                "snapshot": {"source_request": _request_snapshot(source), "suppliers": supplier_snapshot,
                             "products": product_snapshot, "units": unit_snapshot},
                "resource_id": None,
                "diff": [
                    {"field": "source_request", "before": None, "after": source.request_no},
                    {"field": "items", "before": None, "after": [
                        {"requested_name": item.requested_name, "quantity": str(item.quantity), "unit_id": item.unit_id}
                        for item in data.items]},
                    {"field": "suppliers", "before": None, "after": [item["supplier_name"] for item in supplier_evidence]},
                ],
                "evidence": [{"type": "purchase_request", "id": source.id, "request_no": source.request_no,
                              "status": source.status}, {"type": "suppliers", "items": supplier_evidence,
                                                           "selected_by_user": bool(selected_supplier_codes)}],
                "warnings": [], "blockers": [], "risk_level": "MEDIUM"}

    def validate_current(self, db, user, proposal, *, for_update=True):
        from app.modules.purchase_requests import service as request_service
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import RFQCreate

        data = RFQCreate.model_validate(proposal.payload)
        source = request_service.get_request(db, user, data.source_request_id, for_update=for_update)
        if source.status != "APPROVED" or _request_snapshot(source) != proposal.expected_resource_snapshot["source_request"]:
            raise BusinessValidationError("来源采购申请或明细已变化，请重新生成询价预览")
        source_items = {item.id: item for item in source.items}
        for item in data.items:
            source_item = source_items.get(item.source_request_item_id)
            if source_item is None or item.product_id != source_item.product_id or item.unit_id != source_item.unit_id or item.quantity > source_item.quantity:
                raise BusinessValidationError("询价行与来源申请明细已不一致，请重新生成预览")
        rfq_service._validate_item_refs(db, data.items, data.source_request_id)
        rfq_service._validate_suppliers(db, data.supplier_ids)
        for supplier_id, expected in proposal.expected_resource_snapshot["suppliers"].items():
            query = select(Supplier).where(Supplier.id == int(supplier_id))
            supplier = db.scalar(query.with_for_update() if for_update else query)
            if supplier is None or supplier.status != "ACTIVE" or supplier.status != expected["status"]:
                raise BusinessValidationError("受邀供应商状态已变化，请重新生成询价预览")
        for product_id, expected in proposal.expected_resource_snapshot["products"].items():
            query = select(Product).where(Product.id == int(product_id))
            product = db.scalar(query.with_for_update() if for_update else query)
            if product is None or product.status != "ACTIVE" or product.version_no != expected["version_no"]:
                raise BusinessValidationError("询价产品状态或版本已变化，请重新生成预览")
        for unit_id, expected in proposal.expected_resource_snapshot["units"].items():
            query = select(Unit).where(Unit.id == int(unit_id))
            unit = db.scalar(query.with_for_update() if for_update else query)
            if unit is None or unit.status != "ACTIVE" or unit.unit_name != expected["unit_name"] or unit.dimension != expected["dimension"]:
                raise BusinessValidationError("询价单位状态或信息已变化，请重新生成预览")

    def execute(self, db, user, proposal, *, commit=False):
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import RFQCreate, RFQRead

        rfq = rfq_service.create_rfq(db, user, RFQCreate.model_validate(proposal.payload), commit=commit)
        return RFQRead.model_validate(rfq).model_dump(mode="json")


register_handler("rfq.create_draft", RFQCreateDraftHandler())


def _rfq_send_snapshot(rfq) -> dict[str, Any]:
    return {
        "id": rfq.id,
        "rfq_no": rfq.rfq_no,
        "requester_id": rfq.requester_id,
        "status": rfq.status,
        "quote_deadline": rfq.quote_deadline.isoformat() if rfq.quote_deadline else None,
        "requested_delivery_date": rfq.requested_delivery_date.isoformat() if rfq.requested_delivery_date else None,
        "delivery_requirements": rfq.delivery_requirements,
        "items": [
            {"id": item.id, "requested_name": item.requested_name, "quantity": str(item.quantity),
             "unit_id": item.unit_id, "required_delivery_date": item.required_delivery_date.isoformat()
             if item.required_delivery_date else None, "technical_requirements": item.technical_requirements}
            for item in rfq.items
        ],
        "supplier_ids": sorted(supplier.supplier_id for supplier in rfq.suppliers),
    }


class RFQSendHandler:
    permission_code = "procurement.rfqs.write"
    resource_type = "RFQ"

    def prepare(self, db, user, payload):
        from app.modules.rfqs import service as rfq_service

        if not isinstance(payload, dict) or set(payload) != {"rfq_id"}:
            raise BusinessValidationError("发送询价提案只接受询价单编号")
        try:
            rfq_id = int(payload["rfq_id"])
        except (TypeError, ValueError):
            raise BusinessValidationError("询价单编号无效") from None
        rfq = rfq_service.get_rfq(db, user, rfq_id)
        if rfq.status != "DRAFT":
            raise BusinessValidationError("只有草稿状态的询价单可以发送")
        if not rfq.items or not rfq.suppliers:
            raise BusinessValidationError("询价单必须包含明细和邀请供应商")
        snapshot = _rfq_send_snapshot(rfq)
        return {
            "payload": {"rfq_id": rfq.id}, "snapshot": snapshot, "resource_id": rfq.id,
            "diff": [{"field": "status", "before": "DRAFT", "after": "SENT"}],
            "evidence": [{"type": "rfq", "id": rfq.id, "rfq_no": rfq.rfq_no,
                          "status": rfq.status, "item_count": len(rfq.items),
                          "supplier_count": len(rfq.suppliers),
                          "quote_deadline": snapshot["quote_deadline"]}],
            "warnings": [], "blockers": [], "risk_level": "MEDIUM",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        from app.modules.rfqs import service as rfq_service

        rfq_id = int(proposal.resource_id or proposal.payload["rfq_id"])
        rfq = rfq_service.get_rfq(db, user, rfq_id, for_update=for_update)
        if rfq.status != "DRAFT" or not rfq.items or not rfq.suppliers:
            raise BusinessValidationError("询价单状态或内容已变化，请重新生成提案")
        if _rfq_send_snapshot(rfq) != proposal.expected_resource_snapshot:
            raise BusinessValidationError("询价单内容已变化，请重新生成提案")

    def execute(self, db, user, proposal, *, commit=False):
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import RFQRead

        rfq = rfq_service.send_rfq(db, user, int(proposal.payload["rfq_id"]), commit=commit)
        return RFQRead.model_validate(rfq).model_dump(mode="json")


register_handler("rfq.send", RFQSendHandler())


def _quote_comparison_snapshot(comparison) -> dict[str, Any]:
    return {
        "id": comparison.id,
        "comparison_no": comparison.comparison_no,
        "status": comparison.status,
        "selected_quote_id": comparison.selected_quote_id,
        "conclusion": comparison.conclusion,
        "items": [
            {"id": item.id, "quote_id": item.quote_id, "rfq_item_id": item.rfq_item_id,
             "supplier_id": item.supplier_id, "quoted_unit_price": str(item.quoted_unit_price),
             "total_amount": str(item.total_amount) if item.total_amount is not None else None,
             "moq_quantity": str(item.moq_quantity) if item.moq_quantity is not None else None,
             "lead_days": item.lead_days, "payment_terms": item.payment_terms,
             "rank_no": item.rank_no, "selection_flag": item.selection_flag}
            for item in comparison.items
        ],
    }


def _supplier_quote_snapshot(quote) -> dict[str, Any]:
    return {
        "id": quote.id,
        "rfq_id": quote.rfq_id,
        "quote_no": quote.quote_no,
        "supplier_id": quote.supplier_id,
        "quote_version": quote.quote_version,
        "status": quote.status,
        "currency_code": quote.currency_code,
        "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
        "items": [
            {"id": item.id, "rfq_item_id": item.rfq_item_id, "unit_id": item.unit_id,
             "quoted_quantity": str(item.quoted_quantity), "unit_price": str(item.unit_price),
             "tax_rate": str(item.tax_rate) if item.tax_rate is not None else None,
             "moq_quantity": str(item.moq_quantity) if item.moq_quantity is not None else None,
             "moq_unit_id": item.moq_unit_id, "lead_days": item.lead_days,
             "payment_terms": item.payment_terms}
            for item in quote.items
        ],
    }


class RFQSelectQuoteHandler:
    permission_code = "procurement.rfqs.award"
    resource_type = "RFQ"

    def prepare(self, db, user, payload):
        from app.modules.rfqs import crud as rfq_crud
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import QuoteSelection

        if not isinstance(payload, dict) or set(payload) != {"rfq_id", "comparison_id", "quote_id", "selection_reason"}:
            raise BusinessValidationError("中选提案字段无效")
        try:
            rfq_id = int(payload["rfq_id"])
        except (TypeError, ValueError):
            raise BusinessValidationError("询价单编号无效") from None
        selection = QuoteSelection.model_validate({key: payload[key] for key in
            ("comparison_id", "quote_id", "selection_reason")})
        rfq = rfq_service.get_rfq(db, user, rfq_id)
        if rfq.status != "RESPONDING":
            raise BusinessValidationError("只有等待报价的询价单可以确认中选")
        comparison = rfq_crud.get_comparison(db, rfq.id, selection.comparison_id)
        if comparison is None:
            raise ResourceNotFoundError("比价结果不存在")
        if comparison.status != "DRAFT":
            raise BusinessValidationError("比价结果已变化，请重新生成提案")
        quote = rfq_crud.get_quote(db, selection.quote_id)
        if quote is None or quote.rfq_id != rfq.id:
            raise BusinessValidationError("中选报价不属于当前询价单")
        if quote.status != "SUBMITTED":
            raise BusinessValidationError("只有已提交的报价可以中选")
        if quote.id not in {item.quote_id for item in comparison.items}:
            raise BusinessValidationError("中选报价不在该比价结果快照中")
        snapshot = {"rfq": _rfq_send_snapshot(rfq),
                    "comparison": _quote_comparison_snapshot(comparison),
                    "quote": _supplier_quote_snapshot(quote)}
        return {
            "payload": {"rfq_id": rfq.id, **selection.model_dump(mode="json")},
            "snapshot": snapshot,
            "resource_id": rfq.id,
            "diff": [
                {"field": "status", "before": rfq.status, "after": "CLOSED"},
                {"field": "selected_quote", "before": None, "after": quote.quote_no},
                {"field": "selection_reason", "before": None, "after": selection.selection_reason},
            ],
            "evidence": [
                {"type": "quote_comparison", "id": comparison.id, "comparison_no": comparison.comparison_no,
                 "status": comparison.status, "conclusion": comparison.conclusion,
                 "items": snapshot["comparison"]["items"]},
                {"type": "supplier_quote", "id": quote.id, "quote_no": quote.quote_no,
                 "supplier_id": quote.supplier_id, "status": quote.status,
                 "currency_code": quote.currency_code, "valid_until": snapshot["quote"]["valid_until"],
                 "items": snapshot["quote"]["items"]},
            ],
            "warnings": ["确认后询价单将关闭，其他已提交报价将被拒绝。"],
            "blockers": [],
            "risk_level": "HIGH",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        from app.modules.rfqs import crud as rfq_crud
        from app.modules.rfqs import service as rfq_service

        payload = proposal.payload
        rfq = rfq_service.get_rfq(db, user, int(proposal.resource_id or payload["rfq_id"]), for_update=for_update)
        comparison = rfq_crud.get_comparison(db, rfq.id, int(payload["comparison_id"]), for_update=for_update)
        quote = rfq_crud.get_quote(db, int(payload["quote_id"]), for_update=for_update)
        if comparison is None or quote is None or quote.rfq_id != rfq.id:
            raise BusinessValidationError("比价结果或报价已不可用，请重新生成提案")
        current = {"rfq": _rfq_send_snapshot(rfq),
                   "comparison": _quote_comparison_snapshot(comparison),
                   "quote": _supplier_quote_snapshot(quote)}
        if current != proposal.expected_resource_snapshot:
            raise BusinessValidationError("询价单、比价结果或报价已变化，请重新核对")
        if rfq.status != "RESPONDING" or comparison.status != "DRAFT" or quote.status != "SUBMITTED":
            raise BusinessValidationError("询价单、比价结果或报价状态已变化，请重新核对")
        if quote.id not in {item.quote_id for item in comparison.items}:
            raise BusinessValidationError("中选报价已不在比价结果中")

    def execute(self, db, user, proposal, *, commit=False):
        from app.modules.rfqs import service as rfq_service
        from app.modules.rfqs.schema import QuoteSelection, RFQRead

        selection = QuoteSelection.model_validate({key: proposal.payload[key] for key in
            ("comparison_id", "quote_id", "selection_reason")})
        rfq = rfq_service.select_quote(db, user, int(proposal.payload["rfq_id"]), selection, commit=commit)
        return RFQRead.model_validate(rfq).model_dump(mode="json")


register_handler("rfq.select_quote", RFQSelectQuoteHandler())


def _purchase_request_source_snapshot(request) -> dict[str, Any]:
    return {
        "id": request.id,
        "updated_at": request.updated_at.isoformat() if request.updated_at else None,
        "status": request.status,
        "department_id": request.department_id,
        "expected_date": request.expected_date.isoformat() if request.expected_date else None,
        "items": [
            {"id": item.id, "quantity": str(item.quantity),
             "fulfilled_quantity": str(item.fulfilled_quantity)}
            for item in sorted(request.items, key=lambda value: value.id)
        ],
    }


class PurchaseOrderCreateDraftHandler:
    permission_code = "procurement.orders.write"
    resource_type = "RFQ"
    editable_fields = frozenset({"delivery_address", "expected_arrival_date", "note"})

    def prepare(self, db, user, payload):
        return self._prepare(db, user, payload, for_update=False)

    def _prepare(self, db, user, payload, *, for_update: bool):
        from pydantic import ValidationError
        from app.modules.rfqs import service as rfq_service

        if not isinstance(payload, dict) or set(payload) - ({"comparison_id", "quote_id"} | self.editable_fields):
            raise BusinessValidationError("订单草稿提案包含不允许的字段")
        if not {"comparison_id", "quote_id"} <= set(payload):
            raise BusinessValidationError("订单草稿提案必须提供比价结果和中选报价编号")
        for key in ("comparison_id", "quote_id"):
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise BusinessValidationError("比价结果或报价编号无效")
        try:
            data = PurchaseOrderCreate.model_validate(payload)
        except ValidationError as exc:
            raise BusinessValidationError("订单草稿提案参数无效") from exc

        comparison, quote, request, rfq_items, quote_items = purchase_order_service._validate_source(
            db, user, data, for_update=for_update,
        )
        if comparison.status != "CONFIRMED" or comparison.selected_quote_id != quote.id or quote.status != "SELECTED":
            raise BusinessValidationError("比价结果或中选报价状态已变化，请重新生成提案")
        if request.status != "APPROVED":
            raise BusinessValidationError("来源采购申请未审批通过，不能生成采购订单")
        rfq = rfq_service.get_rfq(db, user, quote.rfq_id, for_update=for_update)
        if rfq.id != comparison.rfq_id or rfq.id != quote.rfq_id:
            raise BusinessValidationError("比价结果、报价与询价单来源不一致")
        existing_order = db.scalar(
            select(PurchaseOrder.id).where(PurchaseOrder.source_comparison_id == comparison.id)
            .with_for_update() if for_update else
            select(PurchaseOrder.id).where(PurchaseOrder.source_comparison_id == comparison.id)
        )
        if existing_order is not None:
            raise BusinessValidationError("该比价结果已经生成采购订单")

        normalized = data.model_dump(mode="json")
        request_snapshot = _purchase_request_source_snapshot(request)
        source_lines = []
        line_details = []
        request_items = {item.id: item for item in request.items}
        for rfq_item_id in sorted(quote_items, key=lambda value: rfq_items[value].line_no):
            rfq_item = rfq_items[rfq_item_id]
            quote_item = quote_items[rfq_item_id]
            unit = db.get(Unit, quote_item.unit_id)
            request_item = request_items.get(rfq_item.source_request_item_id)
            remaining = request_item.quantity - request_item.fulfilled_quantity if request_item else None
            source_lines.append({
                "rfq_item_id": rfq_item.id,
                "line_no": rfq_item.line_no,
                "product_id": rfq_item.product_id,
                "requested_name": rfq_item.requested_name,
                "required_delivery_date": rfq_item.required_delivery_date.isoformat()
                if rfq_item.required_delivery_date else None,
                "source_request_item_id": rfq_item.source_request_item_id,
                "request_quantity": str(request_item.quantity) if request_item else None,
                "request_fulfilled_quantity": str(request_item.fulfilled_quantity) if request_item else None,
                "quote_item_id": quote_item.id,
                "supplier_product_id": quote_item.supplier_product_id,
                "supplier_model": quote_item.supplier_model,
                "quoted_quantity": str(quote_item.quoted_quantity),
                "unit_id": quote_item.unit_id,
                "unit_name": unit.unit_name if unit else None,
                "unit_price": str(quote_item.unit_price),
                "tax_rate": str(quote_item.tax_rate) if quote_item.tax_rate is not None else None,
                "lead_days": quote_item.lead_days,
                "payment_terms": quote_item.payment_terms,
                "available_request_quantity": str(remaining) if remaining is not None else None,
                "quantity_check": "within_remaining" if remaining is not None and quote_item.quoted_quantity <= remaining else "not_applicable",
            })
            line_details.append({
                "line_no": rfq_item.line_no,
                "product": rfq_item.requested_name,
                "product_id": rfq_item.product_id,
                "quantity": str(quote_item.quoted_quantity),
                "unit_id": quote_item.unit_id,
                "unit_name": unit.unit_name if unit else None,
                "unit_price": str(quote_item.unit_price),
                "tax_rate": str(quote_item.tax_rate) if quote_item.tax_rate is not None else None,
                "currency_code": quote.currency_code,
                "lead_days": quote_item.lead_days,
                "payment_terms": quote_item.payment_terms,
                "required_delivery_date": rfq_item.required_delivery_date.isoformat()
                if rfq_item.required_delivery_date else request.expected_date.isoformat() if request.expected_date else None,
                "available_request_quantity": str(remaining) if remaining is not None else None,
                "quantity_check": "within_remaining" if remaining is not None and quote_item.quoted_quantity <= remaining else "not_applicable",
            })
        snapshot = {
            "rfq": {**_rfq_send_snapshot(rfq), "source_request_id": rfq.source_request_id},
            "comparison": _quote_comparison_snapshot(comparison),
            "quote": _supplier_quote_snapshot(quote),
            "request": request_snapshot,
            "lines": source_lines,
        }
        warnings = []
        if not data.delivery_address:
            warnings.append("尚未填写收货地址，生成草稿后需人工核对。")
        if data.expected_arrival_date is None:
            warnings.append("尚未填写预计到货日期，无法与询价要求日期核对。")
        elif (rfq.requested_delivery_date or request.expected_date) and data.expected_arrival_date > (
            rfq.requested_delivery_date or request.expected_date
        ):
            warnings.append("预计到货日期晚于询价要求日期，请人工确认。")
        if any(not item["payment_terms"] for item in line_details):
            warnings.append("部分报价明细未提供付款条件，订单快照将保留为空。")
        if any(item["lead_days"] is None for item in line_details):
            warnings.append("部分报价明细未提供交期，无法核对该行交付周期。")
        diff = [
            {"field": "supplier", "before": None, "after": quote.supplier_id},
            {"field": "currency_code", "before": None, "after": quote.currency_code},
            {"field": "delivery_address", "before": None, "after": data.delivery_address},
            {"field": "expected_arrival_date", "before": rfq.requested_delivery_date.isoformat()
             if rfq.requested_delivery_date else request.expected_date.isoformat() if request.expected_date else None,
             "after": data.expected_arrival_date.isoformat() if data.expected_arrival_date else None},
            {"field": "items", "before": None, "after": line_details},
        ]
        evidence = [{"type": "purchase_order_terms_check", "rfq_no": rfq.rfq_no,
                    "comparison_no": comparison.comparison_no, "quote_no": quote.quote_no,
                    "supplier_id": quote.supplier_id,
                    "request_no": request.request_no, "items": line_details}]
        return {
            "payload": normalized,
            "snapshot": snapshot,
            "resource_type": "RFQ",
            "resource_id": rfq.id,
            "diff": diff,
            "evidence": evidence,
            "warnings": warnings,
            "blockers": [],
            "risk_level": "MEDIUM",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        prepared = self._prepare(db, user, proposal.payload, for_update=for_update)
        if prepared["snapshot"] != proposal.expected_resource_snapshot:
            raise BusinessValidationError("询价、比价、报价或申请数据已变化，请重新核对")

    def execute(self, db, user, proposal, *, commit=False):
        order = purchase_order_service.create_order(
            db, user, PurchaseOrderCreate.model_validate(proposal.payload), commit=commit,
        )
        return PurchaseOrderRead.model_validate(order).model_dump(mode="json")


register_handler("purchase_order.create_draft", PurchaseOrderCreateDraftHandler())


def _exception_snapshot(exception) -> dict[str, Any]:
    return {
        "id": exception.id,
        "exception_no": exception.exception_no,
        "exception_type": exception.exception_type,
        "status": exception.status,
        "owner_id": exception.owner_id,
        "updated_at": exception.updated_at.isoformat() if exception.updated_at else None,
        "source_type": exception.source_type,
        "source_id": exception.source_id,
    }


def _assignee_snapshot(db, assignee_id: int | None) -> dict[str, Any] | None:
    if assignee_id is None:
        return None
    assignee = db.get(User, assignee_id)
    if assignee is None:
        raise BusinessValidationError("任务负责人不存在或已停用")
    return {"id": assignee.id, "status": assignee.status, "department_id": assignee.department_id}


class ExceptionTaskCreateHandler:
    permission_code = "operations.exceptions.write"
    resource_type = "OPERATION_EXCEPTION"
    _TASK_FIELDS = ("title", "assignee_id", "priority", "due_at")

    @staticmethod
    def _task_values(payload: dict[str, Any]) -> dict[str, Any]:
        """日期型截止时间按当天结束处理；不接受模型自行换算时区。"""

        values = {key: payload[key] for key in ExceptionTaskCreateHandler._TASK_FIELDS if key in payload}
        due_at = values.get("due_at")
        if isinstance(due_at, str) and len(due_at) == 10 and due_at[4] == "-" and due_at[7] == "-":
            values["due_at"] = f"{due_at}T23:59:59"
        return values

    def _resolve_exception(self, db, user, payload: dict[str, Any]):
        if ("exception_id" in payload) == ("exception_no" in payload):
            raise BusinessValidationError("异常任务提案必须且只能提供准确异常编号")
        if "exception_id" in payload:
            exception_id = payload["exception_id"]
            if isinstance(exception_id, bool) or not isinstance(exception_id, int) or exception_id <= 0:
                raise BusinessValidationError("运营异常编号无效")
            return exception_service.get_exception_for_task_creation(db, user, exception_id)
        exception_no = payload["exception_no"]
        if not isinstance(exception_no, str) or not exception_no.strip() or len(exception_no.strip()) > 32:
            raise BusinessValidationError("请提供准确的运营异常编号")
        return exception_service.get_exception_by_no(db, user, exception_no.strip())

    def _prepare(self, db, user, payload, *, for_update: bool):
        if not isinstance(payload, dict):
            raise BusinessValidationError("异常任务提案格式无效")
        if set(payload) - {"exception_id", "exception_no", *self._TASK_FIELDS}:
            raise BusinessValidationError("异常任务提案包含不允许的字段")
        exception = self._resolve_exception(db, user, payload)
        if for_update:
            exception = exception_service.get_exception_for_task_creation(db, user, exception.id, for_update=True)
        if exception.status in {"CLOSED", "CANCELLED"}:
            raise BusinessValidationError("已关闭或已取消的异常不能新增处理任务")
        data = OperationTaskCreate.model_validate(self._task_values(payload))
        exception_service.validate_assignee(db, user, data.assignee_id)
        snapshot = {"exception": _exception_snapshot(exception),
                    "assignee": _assignee_snapshot(db, data.assignee_id)}
        return data, exception, snapshot

    def prepare(self, db, user, payload):
        data, exception, snapshot = self._prepare(db, user, payload, for_update=False)
        normalized = {"exception_id": exception.id, **data.model_dump(mode="json")}
        diff = [{"field": "title", "before": None, "after": data.title}]
        diff.append({"field": "priority", "before": None, "after": data.priority})
        if data.due_at is not None:
            diff.append({"field": "due_at", "before": None, "after": data.due_at.isoformat()})
        if data.assignee_id is not None:
            diff.append({"field": "assignee_id", "before": None, "after": data.assignee_id})
        return {
            "payload": normalized,
            "snapshot": snapshot,
            "resource_id": exception.id,
            "diff": diff,
            "evidence": [{"type": "operation_exception", "id": exception.id,
                          "exception_no": exception.exception_no, "status": exception.status,
                          "exception_type": exception.exception_type}],
            "warnings": [],
            "blockers": [],
            "risk_level": "LOW",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        expected = proposal.expected_resource_snapshot or {}
        _, exception, snapshot = self._prepare(db, user, proposal.payload, for_update=for_update)
        if snapshot != expected:
            raise BusinessValidationError("异常状态、负责人或内容已变化，请重新核对")

    def execute(self, db, user, proposal, *, commit=False):
        from app.modules.ai.model import AIOperationSuggestion

        data = OperationTaskCreate.model_validate(self._task_values(proposal.payload))
        task = exception_service.create_task(db, user, int(proposal.resource_id), data, commit=commit)
        open_suggestions = list(
            db.scalars(
                select(AIOperationSuggestion)
                .where(
                    AIOperationSuggestion.exception_id == int(proposal.resource_id),
                    AIOperationSuggestion.status == "OPEN",
                )
                .with_for_update()
            ).all()
        )
        now = datetime.now()
        for suggestion in open_suggestions:
            suggestion.task_id = task.id
            suggestion.status = "HANDED_OFF"
            suggestion.handled_by = user.id
            suggestion.handled_at = now
        if open_suggestions:
            db.flush()
            if commit:
                db.commit()
        return OperationTaskRead.model_validate(task).model_dump(mode="json")


register_handler("exceptions.create_task", ExceptionTaskCreateHandler())


def _parse_positive_quantity(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise BusinessValidationError("补货数量必须是正数")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise BusinessValidationError("补货数量必须是正数") from None
    if not quantity.is_finite() or quantity <= 0:
        raise BusinessValidationError("补货数量必须是正数")
    return quantity


def _parse_expected_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            raise BusinessValidationError("期望到货日期格式应为 YYYY-MM-DD") from None
    raise BusinessValidationError("期望到货日期格式应为 YYYY-MM-DD")


class ReplenishmentCreateHandler:
    permission_code = "procurement.replenishment.write"
    resource_type = "REPLENISHMENT_REQUEST"
    _FIELDS = ("supplier_code", "product_keyword", "quantity", "reason", "expected_date", "note")

    def _prepare(self, db, user, payload):
        if not isinstance(payload, dict):
            raise BusinessValidationError("补货申请提案格式无效")
        if set(payload) - set(self._FIELDS):
            raise BusinessValidationError("补货申请提案包含不允许的字段")
        supplier_code = payload.get("supplier_code")
        product_keyword = payload.get("product_keyword")
        if not isinstance(supplier_code, str) or not supplier_code.strip():
            raise BusinessValidationError("请提供准确的供应商编码")
        if not isinstance(product_keyword, str) or not product_keyword.strip():
            raise BusinessValidationError("请提供准确的产品编码或规格")
        supplier = get_supplier_by_code(db, supplier_code.strip())
        if supplier is None or supplier.status != "ACTIVE":
            raise BusinessValidationError("补货供应商不存在或已停用")

        from app.modules.ai import agent_tools
        from app.modules.ai.schema import ToolCall

        available = {entry["name"] for entry in agent_tools.list_tools(db, user)}
        if "catalog.search_products" not in available:
            raise BusinessValidationError("当前账号不能检索产品目录，无法创建补货申请")
        candidates = agent_tools.execute_tool(db, user, ToolCall(
            tool="catalog.search_products", arguments={"keyword": product_keyword.strip(), "limit": 10}))
        if candidates.total_rows != 1 or candidates.truncated:
            raise BusinessValidationError("请提供唯一的产品编码或规格后再创建补货申请")
        product = db.get(Product, candidates.rows[0].product_id)
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError("补货产品不存在或已停用")
        unit = db.get(Unit, product.unit_id)
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError("补货产品的计量单位不存在或已停用")

        quantity = _parse_positive_quantity(payload.get("quantity"))
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise BusinessValidationError("请说明补货原因")
        expected_date = _parse_expected_date(payload.get("expected_date"))
        note = payload.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 1000):
            raise BusinessValidationError("补货备注格式无效")

        data = ReplenishmentCreate(
            supplier_id=supplier.id,
            reason=reason.strip(),
            items=[ReplenishmentItemCreate(
                product_id=product.id, unit_id=unit.id, requested_quantity=quantity,
                expected_date=expected_date, note=note,
            )],
        )
        snapshot = {
            "supplier": {"id": supplier.id, "supplier_code": supplier.supplier_code, "status": supplier.status},
            "product": {"id": product.id, "product_code": product.product_code,
                        "status": product.status, "version_no": product.version_no},
            "unit": {"id": unit.id, "unit_name": unit.unit_name, "dimension": unit.dimension,
                     "status": unit.status},
        }
        evidence: list[dict] = [
            {"type": "supplier", "id": supplier.id, "supplier_code": supplier.supplier_code,
             "supplier_name": supplier.supplier_name, "status": supplier.status},
            {"type": "product", "id": product.id, "product_code": product.product_code,
             "product_name": product.product_name, "unit_name": unit.unit_name},
        ]
        warnings: list[str] = []
        try:
            inventory_call = ToolCall(tool="inventory.query_available", arguments={"product_id": product.id})
            inventory = agent_tools.execute_tool(db, user, inventory_call)
            dumped = inventory.model_dump(mode="json")
            evidence.append({"type": "inventory", "label": "当前可用库存",
                             "product_id": product.id, "scope": dumped.get("scope"),
                             "observed_at": dumped.get("observed_at"),
                             "totals": dumped.get("totals") or [],
                             "sources": dumped.get("sources") or []})
        except (AuthorizationError, BusinessValidationError, ResourceNotFoundError):
            warnings.append("当前账号无库存读取权限或库存事实暂不可用，未展示补货前的可用库存。")
        diff = [
            {"field": "supplier", "before": None, "after": supplier.supplier_code},
            {"field": "product", "before": None, "after": product.product_code},
            {"field": "quantity", "before": None, "after": format_decimal(quantity)},
            {"field": "reason", "before": None, "after": reason.strip()},
        ]
        if expected_date is not None:
            diff.append({"field": "expected_date", "before": None, "after": expected_date.isoformat()})
        normalized = {
            "supplier_id": supplier.id,
            "reason": reason.strip(),
            "items": [{
                "product_id": product.id, "unit_id": unit.id,
                "requested_quantity": format_decimal(quantity),
                "expected_date": expected_date.isoformat() if expected_date else None,
                "note": note,
            }],
        }
        return {"payload": normalized, "snapshot": snapshot, "resource_id": None,
                "diff": diff, "evidence": evidence, "warnings": warnings,
                "blockers": [], "risk_level": "MEDIUM"}

    def prepare(self, db, user, payload):
        return self._prepare(db, user, payload)

    def validate_current(self, db, user, proposal, *, for_update=True):
        expected = proposal.expected_resource_snapshot or {}
        supplier_id = int(proposal.payload.get("supplier_id"))
        supplier = db.scalar(select(Supplier).where(Supplier.id == supplier_id).with_for_update()
                             if for_update else select(Supplier).where(Supplier.id == supplier_id))
        if supplier is None or supplier.status != "ACTIVE":
            raise BusinessValidationError("补货供应商已停用或不存在，请重新生成预览")
        item = (proposal.payload.get("items") or [{}])[0]
        product = db.scalar(select(Product).where(Product.id == int(item.get("product_id"))).with_for_update()
                            if for_update else select(Product).where(Product.id == int(item.get("product_id"))))
        if product is None or product.status != "ACTIVE":
            raise BusinessValidationError("补货产品已停用或不存在，请重新生成预览")
        unit = db.scalar(select(Unit).where(Unit.id == int(item.get("unit_id"))).with_for_update()
                         if for_update else select(Unit).where(Unit.id == int(item.get("unit_id"))))
        if unit is None or unit.status != "ACTIVE":
            raise BusinessValidationError("补货计量单位已停用或不存在，请重新生成预览")
        current = {
            "supplier": {"id": supplier.id, "supplier_code": supplier.supplier_code, "status": supplier.status},
            "product": {"id": product.id, "product_code": product.product_code,
                        "status": product.status, "version_no": product.version_no},
            "unit": {"id": unit.id, "unit_name": unit.unit_name, "dimension": unit.dimension,
                     "status": unit.status},
        }
        if current != expected:
            raise BusinessValidationError("供应商、产品或计量单位已变化，请重新生成预览")

    def execute(self, db, user, proposal, *, commit=False):
        data = ReplenishmentCreate.model_validate(proposal.payload)
        value = replenishment_service.create_replenishment(db, user, data, commit=commit)
        return ReplenishmentRead.model_validate(value).model_dump(mode="json")


register_handler("inventory.create_replenishment", ReplenishmentCreateHandler())


def _order_snapshot(order: PurchaseOrder) -> dict[str, Any]:
    return {
        "id": order.id,
        "po_no": order.po_no,
        "status": order.status,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        "supplier_id": order.supplier_id,
        "buyer_id": order.buyer_id,
        "order_amount": str(order.order_amount),
        "currency_code": order.currency_code,
        "item_count": len(order.items),
    }


class PurchaseOrderSubmitHandler:
    permission_code = "procurement.orders.write"
    resource_type = "PURCHASE_ORDER"

    def _resolve(self, db, user, payload):
        if not isinstance(payload, dict) or set(payload) - {"order_id", "po_no"}:
            raise BusinessValidationError("订单提交提案包含不允许的字段")
        if ("order_id" in payload) == ("po_no" in payload):
            raise BusinessValidationError("订单提交提案必须且只能提供准确订单号")
        if "order_id" in payload:
            order_id = payload["order_id"]
            if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id <= 0:
                raise BusinessValidationError("采购订单编号无效")
            return purchase_order_service.get_order(db, user, order_id)
        po_no = payload["po_no"]
        if not isinstance(po_no, str) or not po_no.strip() or len(po_no.strip()) > 32:
            raise BusinessValidationError("请提供准确的采购订单号")
        return purchase_order_service.get_order_by_no(db, user, po_no.strip())

    def prepare(self, db, user, payload):
        order = self._resolve(db, user, payload)
        if order.status != "DRAFT":
            raise BusinessValidationError("只有草稿状态的采购订单可以提交审批")
        if not order.items:
            raise BusinessValidationError("采购订单必须包含明细")
        snapshot = _order_snapshot(order)
        return {
            "payload": {"order_id": order.id},
            "snapshot": snapshot,
            "resource_id": order.id,
            "diff": [
                {"field": "status", "before": "DRAFT", "after": "APPROVING"},
                {"field": "item_count", "before": len(order.items), "after": len(order.items)},
            ],
            "evidence": [{"type": "purchase_order", "id": order.id, "po_no": order.po_no,
                          "status": order.status, "amount": format_decimal(order.order_amount),
                          "currency": order.currency_code}],
            "warnings": [],
            "blockers": [],
            "risk_level": "HIGH",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        order = purchase_order_service.get_order(
            db, user, int(proposal.payload.get("order_id")), for_update=for_update)
        if order.status != "DRAFT":
            raise BusinessValidationError("采购订单已不是草稿状态，请重新核对")
        if not order.items:
            raise BusinessValidationError("采购订单没有明细，不能提交审批")
        if _order_snapshot(order) != (proposal.expected_resource_snapshot or {}):
            raise BusinessValidationError("采购订单内容或状态已变化，请重新核对")

    def execute(self, db, user, proposal, *, commit=False):
        order = purchase_order_service.submit_order(
            db, user, int(proposal.payload.get("order_id")), commit=commit)
        return PurchaseOrderRead.model_validate(order).model_dump(mode="json")


register_handler("purchase_order.submit", PurchaseOrderSubmitHandler())


class DeliveryFollowupDraftHandler:
    permission_code = "procurement.orders.write"
    resource_type = "PURCHASE_ORDER"

    def prepare(self, db, user, payload):
        from app.modules.purchase_orders.followup import build_followup, validate_input

        data = validate_input(payload)
        draft = build_followup(db, user, data.order_id, note=data.followup_note)
        return {
            "payload": data.model_dump(), "snapshot": draft["snapshot"], "resource_id": data.order_id,
            "diff": [{"field": "followup_message", "before": None, "after": draft["message"]}],
            "evidence": [{"type": "delivery_followup", **draft["snapshot"]}],
            "warnings": draft["warnings"], "blockers": [], "risk_level": "LOW",
        }

    def validate_current(self, db, user, proposal, *, for_update=True):
        from app.modules.purchase_orders.followup import build_followup, validate_input

        data = validate_input(proposal.payload)
        current = build_followup(db, user, data.order_id, note=data.followup_note, for_update=for_update)
        if current["snapshot"] != proposal.expected_resource_snapshot:
            raise BusinessValidationError("订单交期、收货数量或来源事实已变化，请重新生成预览")

    def execute(self, db, user, proposal, *, commit=False):
        from app.modules.purchase_orders.followup import build_followup, validate_input

        data = validate_input(proposal.payload)
        draft = build_followup(db, user, data.order_id, note=data.followup_note, for_update=True)
        if draft["snapshot"] != proposal.expected_resource_snapshot:
            raise BusinessValidationError("订单来源事实已变化，请重新生成预览")
        # 通用账本保存此结果；不调用通知或供应商发送服务，也不改订单状态。
        return {"order_id": data.order_id, "po_no": draft["snapshot"]["po_no"],
                "status": "DRAFT", "sent": False, "message": draft["message"]}


register_handler("deliveries.followup_draft", DeliveryFollowupDraftHandler())
