"""采购 Agent 的只读工具：定位业务对象、读取库存和比较报价。"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.inventory.model import InventoryBalance, InventoryBatch, Warehouse
from app.modules.inventory.service import accessible_warehouse_ids
from app.modules.products.model import Product
from app.modules.purchase_requests.model import Unit
from app.modules.rfqs.model import RFQ, RFQItem, SupplierQuote, SupplierQuoteItem
from app.modules.suppliers.model import Supplier
from app.modules.system.crud import get_user_permission_codes, get_user_role_codes
from app.modules.system.model import User


PositiveID = Annotated[int, Field(strict=True, gt=0)]


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryInput(ToolSchema):
    product_id: PositiveID
    warehouse_id: PositiveID | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class QuoteInput(ToolSchema):
    product_id: PositiveID
    rfq_item_id: PositiveID
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class ToolCall(ToolSchema):
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, object]


class ProductSearchInput(ToolSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keyword: str = Field(min_length=1, max_length=100)
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10


class RFQSearchInput(ToolSchema):
    product_id: PositiveID
    rfq_no: str | None = Field(default=None, min_length=1, max_length=32)
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10


class ProductCandidate(ToolSchema):
    product_id: int
    product_code: str
    product_name: str
    model: str | None
    packaging_spec: str | None
    unit_id: int
    unit_name: str


class ProductSearchResult(ToolSchema):
    tool: Literal["catalog.search_products"] = "catalog.search_products"
    keyword: str
    total_rows: int
    truncated: bool
    rows: list[ProductCandidate]
    sources: list["Source"]


class RFQCandidate(ToolSchema):
    rfq_item_id: int
    rfq_id: int
    rfq_no: str
    product_id: int
    specification: str | None
    technical_requirements: str | None


class RFQSearchResult(ToolSchema):
    tool: Literal["supplier_quotes.find_rfq_items"] = "supplier_quotes.find_rfq_items"
    product_id: int
    total_rows: int
    truncated: bool
    rows: list[RFQCandidate]
    sources: list["Source"]


class Source(ToolSchema):
    resource: str
    record_id: int
    parent_id: int | None = None


def search_products(db: Session, user: User, arguments: ProductSearchInput) -> ProductSearchResult:
    """按名称或编码查启用产品，返回规格候选；多个命中由 Runtime 追问选择。

    统一执行入口要求产品读取权限；关键词使用绑定参数并转义 LIKE 通配符。
    不做名称到 CAS 的猜测，不把首个模糊命中直接当用户指定的产品。
    """
    base = select(
        Product.id.label("product_id"), Product.product_code, Product.product_name,
        Product.model, Product.packaging_spec, Product.unit_id, Unit.unit_name,
    ).join(Unit, Unit.id == Product.unit_id).where(
        Product.status == "ACTIVE", Unit.status == "ACTIVE",
        Product.product_name.contains(arguments.keyword, autoescape=True) |
        Product.product_code.contains(arguments.keyword, autoescape=True),
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Product.id).limit(arguments.limit)).mappings().all()
    return ProductSearchResult(keyword=arguments.keyword, total_rows=total,
        truncated=total > arguments.limit, rows=[ProductCandidate(**row) for row in rows],
        sources=[Source(resource="md_products", record_id=row["product_id"]) for row in rows])


def find_rfq_items(db: Session, user: User, arguments: RFQSearchInput) -> RFQSearchResult:
    """定位产品的当前可见询价明细；不把其他用户询价或历史关闭单作为候选。"""
    _product(db, arguments.product_id)
    base = select(RFQItem.id.label("rfq_item_id"), RFQ.id.label("rfq_id"), RFQ.rfq_no,
        RFQItem.product_id, RFQItem.specification, RFQItem.technical_requirements,
    ).join(RFQ, RFQ.id == RFQItem.rfq_id).where(
        RFQItem.product_id == arguments.product_id, RFQ.status.in_(("SENT", "RESPONDING")))
    if not set(get_user_role_codes(db, user.id)) & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        base = base.where(RFQ.requester_id == user.id)
    if arguments.rfq_no is not None:
        base = base.where(RFQ.rfq_no == arguments.rfq_no)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(RFQ.id.desc(), RFQItem.id).limit(arguments.limit)).mappings().all()
    return RFQSearchResult(product_id=arguments.product_id, total_rows=total,
        truncated=total > arguments.limit, rows=[RFQCandidate(**row) for row in rows],
        sources=[Source(resource="rfq_items", record_id=row["rfq_item_id"], parent_id=row["rfq_id"]) for row in rows])


class InventoryRow(ToolSchema):
    balance_id: int
    warehouse_id: int
    warehouse_name: str
    batch_id: int
    batch_no: str
    expiry_date: date | None
    unit_id: int
    unit_name: str
    status: str
    quantity: Decimal
    locked_quantity: Decimal
    available_quantity: Decimal


class InventoryTotal(ToolSchema):
    unit_id: int
    unit_name: str
    available_quantity: Decimal


class InventoryResult(ToolSchema):
    tool: Literal["inventory.query_available"] = "inventory.query_available"
    observed_at: datetime
    product_id: int
    product_name: str
    warehouse_id: int | None
    scope: str = "当前用户可访问仓库；未指定仓库时不是企业全量库存"
    total_rows: int
    truncated: bool
    totals: list[InventoryTotal]
    scope_warehouse_ids: list[int] = Field(default_factory=list)
    rows: list[InventoryRow]
    sources: list[Source]
    warnings: list[str]


class QuoteRow(ToolSchema):
    quote_id: int
    quote_item_id: int
    supplier_id: int
    supplier_name: str
    quote_no: str
    quote_version: int
    quote_date: date
    valid_until: date | None
    currency_code: str
    unit_id: int
    unit_name: str
    supplier_model: str | None
    tax_rate: Decimal | None
    unit_price: Decimal
    quoted_quantity: Decimal
    moq_quantity: Decimal | None
    moq_unit_id: int | None
    lead_days: int | None
    rank: int | None = None


class QuoteResult(ToolSchema):
    tool: Literal["supplier_quotes.compare"] = "supplier_quotes.compare"
    observed_at: datetime
    as_of: date
    product_id: int
    rfq_id: int
    rfq_no: str
    rfq_item_id: int
    specification: str | None
    technical_requirements: str | None
    scope: str = "同一询价明细；普通用户仅本人询价，采购经理/管理员全部询价"
    comparison_basis: str = "未税单价；仅在币种、单位、税率、供应商型号相同且明确时排序"
    total_rows: int
    truncated: bool
    rows: list[QuoteRow]
    sources: list[Source]
    warnings: list[str]


def _product(db: Session, product_id: int):
    """读取启用产品的最小识别信息；不匹配名称，不替调用者推断产品规格。"""
    value = db.execute(select(Product.id, Product.product_name).where(
        Product.id == product_id, Product.status == "ACTIVE"
    )).first()
    if value is None:
        raise ResourceNotFoundError("产品不存在或已停用")
    return value


def query_inventory(db: Session, user: User, arguments: InventoryInput) -> InventoryResult:
    """查询授权仓库的账面库存，返回分单位全量合计和有上限的来源明细。

    由 execute_tool 先校验工具权限，本函数沿用库存服务的仓库范围。
    冻结余额可用量为零；有效期仅展示，不据此自动决定领用资格。
    查询不创建/更新余额、不锁定库存，也不提交事务。
    """
    product = _product(db, arguments.product_id)
    warehouses = accessible_warehouse_ids(db, user)
    if arguments.warehouse_id is not None:
        if warehouses is not None and arguments.warehouse_id not in warehouses:
            raise ResourceNotFoundError("仓库不存在或不可访问")
        if db.scalar(select(Warehouse.id).where(
            Warehouse.id == arguments.warehouse_id, Warehouse.status == "ACTIVE"
        )) is None:
            raise ResourceNotFoundError("仓库不存在或不可访问")
    conditions = [InventoryBalance.product_id == arguments.product_id, Warehouse.status == "ACTIVE"]
    if warehouses is not None:
        conditions.append(InventoryBalance.warehouse_id.in_(warehouses))
    if arguments.warehouse_id is not None:
        conditions.append(InventoryBalance.warehouse_id == arguments.warehouse_id)
    # 与已有库存查询口径一致：冻结余额不计可用，不按有效期自动推断放行。
    available = case((InventoryBalance.status == "AVAILABLE",
                      InventoryBalance.quantity - InventoryBalance.locked_quantity), else_=0)
    base = select(
        InventoryBalance.id.label("balance_id"), InventoryBalance.warehouse_id,
        Warehouse.warehouse_name, InventoryBalance.batch_id, InventoryBatch.batch_no,
        InventoryBatch.expiry_date, InventoryBalance.unit_id, Unit.unit_name,
        InventoryBalance.status, InventoryBalance.quantity, InventoryBalance.locked_quantity,
        available.label("available_quantity"),
    ).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id).join(
        InventoryBatch, InventoryBatch.id == InventoryBalance.batch_id
    ).join(Unit, Unit.id == InventoryBalance.unit_id).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    totals = db.execute(select(
        InventoryBalance.unit_id, Unit.unit_name, func.sum(available).label("available_quantity")
    ).select_from(InventoryBalance).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id).join(
        Unit, Unit.id == InventoryBalance.unit_id
    ).where(*conditions).group_by(InventoryBalance.unit_id, Unit.unit_name)).mappings().all()
    rows = db.execute(base.order_by(InventoryBalance.id).limit(arguments.limit)).mappings().all()
    scope_warehouse_ids = list(db.scalars(select(InventoryBalance.warehouse_id).join(
        Warehouse, Warehouse.id == InventoryBalance.warehouse_id).where(*conditions).distinct()))
    warnings = ["可用量沿用余额状态口径；过期批次、停用单位等仍需原业务流程核查，不代表可直接领用。"]
    if total == 0:
        warnings.append("当前授权范围无库存记录，不能据此推断企业没有库存。")
    if total > arguments.limit:
        warnings.append("明细已截断；分单位合计仍按全部可见余额计算。")
    return InventoryResult(
        observed_at=datetime.now(timezone.utc), product_id=product.id,
        product_name=product.product_name, warehouse_id=arguments.warehouse_id,
        total_rows=total, truncated=total > arguments.limit,
        totals=[InventoryTotal(**row) for row in totals],
        scope_warehouse_ids=scope_warehouse_ids,
        rows=[InventoryRow(**row) for row in rows],
        sources=[Source(resource="inventory_balances", record_id=row["balance_id"]) for row in rows],
        warnings=warnings,
    )


def compare_quotes(db: Session, user: User, arguments: QuoteInput) -> QuoteResult:
    """读取指定询价明细的最新可见报价，按明确的可比条件计算展示排名。

    由 execute_tool 先检查询价读取权限；这里按发起人/管理角色限制资源范围。
    先排除旧版本，再过滤有效期、状态和停用对象。异币种、单位、税率或
    型号不得混排；条件未知和结果截断时不排序，不保存比价或变更定标。
    """
    _product(db, arguments.product_id)
    roles = set(get_user_role_codes(db, user.id))
    statement = select(
        RFQ.id.label("rfq_id"), RFQ.rfq_no, RFQ.status,
        RFQItem.specification, RFQItem.technical_requirements,
    ).join(RFQItem, RFQItem.rfq_id == RFQ.id).where(
        RFQItem.id == arguments.rfq_item_id, RFQItem.product_id == arguments.product_id
    )
    if not roles & {"SYS_ADMIN", "PROCUREMENT_MANAGER"}:
        statement = statement.where(RFQ.requester_id == user.id)
    context = db.execute(statement).first()
    if context is None:
        raise ResourceNotFoundError("询价明细不存在、产品不匹配或不可访问")
    if context.status not in {"SENT", "RESPONDING"}:
        raise BusinessValidationError("只比较已发送或报价中的询价；已关闭询价不作为当前采购候选")
    # 当前业务采用中国标准时间；固定 UTC+08 避免 Windows 依赖额外 tzdata。
    today = datetime.now(timezone(timedelta(hours=8))).date()
    newer = aliased(SupplierQuote)
    # 最新版本先于状态和有效期过滤，不能把撤回/失效新版的旧价重新当成有效候选。
    has_newer = exists(select(newer.id).where(
        newer.rfq_id == SupplierQuote.rfq_id, newer.supplier_id == SupplierQuote.supplier_id,
        (newer.quote_version > SupplierQuote.quote_version) |
        ((newer.quote_version == SupplierQuote.quote_version) & (newer.id > SupplierQuote.id)),
    ))
    base = select(
        SupplierQuote.id.label("quote_id"), SupplierQuoteItem.id.label("quote_item_id"),
        SupplierQuote.supplier_id, Supplier.supplier_name, SupplierQuote.quote_no,
        SupplierQuote.quote_version, SupplierQuote.quote_date, SupplierQuote.valid_until,
        SupplierQuote.currency_code, SupplierQuoteItem.unit_id, Unit.unit_name,
        SupplierQuoteItem.supplier_model, SupplierQuoteItem.tax_rate,
        SupplierQuoteItem.unit_price, SupplierQuoteItem.quoted_quantity,
        SupplierQuoteItem.moq_quantity, SupplierQuoteItem.moq_unit_id, SupplierQuoteItem.lead_days,
    ).select_from(SupplierQuote).join(SupplierQuoteItem, SupplierQuoteItem.quote_id == SupplierQuote.id).join(
        Supplier, Supplier.id == SupplierQuote.supplier_id
    ).join(Unit, Unit.id == SupplierQuoteItem.unit_id).where(
        SupplierQuote.rfq_id == context.rfq_id, SupplierQuoteItem.rfq_item_id == arguments.rfq_item_id,
        SupplierQuote.status == "SUBMITTED", SupplierQuote.quote_date <= today,
        (SupplierQuote.valid_until.is_(None)) | (SupplierQuote.valid_until >= today),
        Supplier.status == "ACTIVE", Unit.status == "ACTIVE", ~has_newer,
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = [QuoteRow(**row) for row in db.execute(
        base.order_by(SupplierQuote.id, SupplierQuoteItem.id).limit(arguments.limit)
    ).mappings().all()]
    truncated = total > arguments.limit
    warnings = ["报价数量、起订量和交期仅展示原值；不推断目标数量可成交，不自动选定供应商。"]
    groups: dict[tuple, list[QuoteRow]] = {}
    for row in rows:
        if truncated or row.valid_until is None or row.tax_rate is None or not row.supplier_model:
            continue
        key = (row.currency_code, row.unit_id, row.tax_rate, row.supplier_model)
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        if len(group) > 1:
            prices = sorted({row.unit_price for row in group})
            for row in group:
                row.rank = prices.index(row.unit_price) + 1
    if not rows:
        warnings.append("可见询价明细没有符合条件的最新报价；不代表没有供应商或历史报价。")
    if any(row.valid_until is None or row.tax_rate is None or not row.supplier_model for row in rows):
        warnings.append("有效期、税率或型号未明确的报价仅展示，不参与排序。")
    if truncated:
        warnings.append("报价已截断，全部候选不排序；请缩小范围或在原询价页面核对。")
    return QuoteResult(
        observed_at=datetime.now(timezone.utc), as_of=today, product_id=arguments.product_id,
        rfq_id=context.rfq_id, rfq_no=context.rfq_no, rfq_item_id=arguments.rfq_item_id,
        specification=context.specification, technical_requirements=context.technical_requirements,
        total_rows=total, truncated=truncated, rows=rows,
        sources=[Source(resource="supplier_quote_items", record_id=row.quote_item_id,
                        parent_id=context.rfq_id) for row in rows], warnings=warnings,
    )


@dataclass(frozen=True)
class ToolSpec:
    """静态工具契约：Schema 与处理函数由代码登记，禁止按模型文本动态查找函数。"""
    name: str
    description: str
    permission: str
    input_schema: type[ToolSchema]
    output_schema: type[ToolSchema]
    handler: Callable


TOOLS = {
    spec.name: spec for spec in (
        ToolSpec("catalog.search_products", "按名称/编码找产品规格；多候选必须让用户选择，不猜 ID",
                 "master.products.read", ProductSearchInput, ProductSearchResult, search_products),
        ToolSpec("supplier_quotes.find_rfq_items", "定位产品的可见询价明细；多候选必须让用户选择",
                 "procurement.rfqs.read", RFQSearchInput, RFQSearchResult, find_rfq_items),
        ToolSpec("inventory.query_available", "按产品查询可见仓库余额，分单位合计，保留明细来源",
                 "warehouse.inventory.read", InventoryInput, InventoryResult, query_inventory),
        ToolSpec("supplier_quotes.compare", "同一可见询价明细的最新有效提交报价，分可比组排序",
                 "procurement.rfqs.read", QuoteInput, QuoteResult, compare_quotes),
    )
}


def _permissions(db: Session, user: User) -> tuple[bool, set[str]]:
    """检查总开关并读取当前 RBAC；管理员豁免权限码，资源范围另由工具校验。"""
    if not get_settings().agent_enabled:
        raise BusinessValidationError("Agent 能力已关闭")
    return "SYS_ADMIN" in get_user_role_codes(db, user.id), set(get_user_permission_codes(db, user.id))


def list_tools(db: Session, user: User) -> list[dict[str, object]]:
    """仅向用户公开当前有权执行的只读工具及输入/输出 Schema；不调用模型。"""
    admin, permissions = _permissions(db, user)
    return [{"name": spec.name, "description": spec.description, "version": "1.0",
             "risk": "READ_ONLY", "permission": spec.permission,
             "input_schema": spec.input_schema.model_json_schema(),
             "output_schema": spec.output_schema.model_json_schema()}
            for spec in TOOLS.values() if admin or spec.permission in permissions]


def execute_tool(db: Session, user: User, call: ToolCall) -> InventoryResult | QuoteResult | ProductSearchResult | RFQSearchResult:
    """统一执行入口：白名单、当前权限、参数 Schema、资源范围、输出 Schema。

    用户身份只取自认证上下文；拒绝模型夹带的身份、SQL 和其他未登记参数。
    禁用调用期间的 ORM 自动刷新，避免待写对象因查询被隐式写入。
    当前注册表只有只读函数；写开关不能使未知或写操作工具变成可执行工具。
    """
    admin, permissions = _permissions(db, user)
    spec = TOOLS.get(call.tool)
    if spec is None:
        raise BusinessValidationError("未注册的只读工具")
    if not admin and spec.permission not in permissions:
        raise AuthorizationError("没有执行该工具的权限")
    try:
        arguments = spec.input_schema.model_validate(call.arguments)
    except ValidationError as exc:
        raise BusinessValidationError("工具参数缺失或无效；仅接受登记字段，禁止传入身份、SQL 或写入指令") from exc
    with db.no_autoflush:
        return spec.output_schema.model_validate(spec.handler(db, user, arguments))
