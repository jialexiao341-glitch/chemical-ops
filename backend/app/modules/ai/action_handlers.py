"""服务端明确注册的 Agent 写动作处理器。"""

from typing import Any, Protocol

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.products.model import Product
from app.modules.purchase_requests import service as purchase_request_service
from app.modules.purchase_requests.model import PurchaseRequest
from app.modules.purchase_requests.model import Unit
from app.modules.purchase_requests.schema import PurchaseRequestCreate, PurchaseRequestUpdate, PurchaseRequestRead
from app.modules.system.model import User
from app.modules.suppliers.model import Supplier
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
        candidates = agent_tools.execute_tool(db, user, ToolCall(
            tool="catalog.search_products", arguments={"keyword": item.requested_name, "limit": 100}))
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
        request = purchase_request_service.get_request(db, user, int(proposal.resource_id), for_update=for_update)
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
        request = purchase_request_service.get_request(db, user, int(proposal.resource_id), for_update=for_update)
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
