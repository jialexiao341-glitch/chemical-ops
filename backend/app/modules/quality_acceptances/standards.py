"""人工维护的产品检测标准；每次修改创建新版本。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessValidationError, ResourceNotFoundError
from app.modules.products.model import Product
from app.modules.quality_acceptances.model import QualityInspectionStandard
from app.modules.quality_acceptances.schema import QualityStandardCreate
from app.modules.system.model import User
from app.modules.system.audit import add_audit_log


def list_standards(db: Session, product_id: int) -> list[QualityInspectionStandard]:
    """确认产品存在后，按版本号从新到旧返回全部检测标准。"""
    if db.get(Product, product_id) is None:
        raise ResourceNotFoundError("产品不存在")
    return list(db.scalars(
        select(QualityInspectionStandard)
        .where(QualityInspectionStandard.product_id == product_id)
        .order_by(QualityInspectionStandard.version_no.desc())
    ).all())


def latest_standard(db: Session, product_id: int) -> QualityInspectionStandard | None:
    """读取产品当前最高版本的检测标准；未配置时返回 None。"""
    return db.scalar(
        select(QualityInspectionStandard)
        .where(QualityInspectionStandard.product_id == product_id)
        .order_by(QualityInspectionStandard.version_no.desc())
        .limit(1)
    )


def create_standard(db: Session, user: User, product_id: int, data: QualityStandardCreate) -> QualityInspectionStandard:
    """校验产品与标准来源，新增不可覆盖的版本并记录操作审计。"""
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None:
        raise ResourceNotFoundError("产品不存在")
    if product.status != "ACTIVE":
        raise BusinessValidationError("仅可为启用的产品配置检测标准")
    source = data.source_reference.strip()
    if not source:
        raise BusinessValidationError("请填写经审核的标准来源")
    version = (db.scalar(select(func.max(QualityInspectionStandard.version_no)).where(QualityInspectionStandard.product_id == product_id)) or 0) + 1
    standard = QualityInspectionStandard(
        product_id=product_id,
        version_no=version,
        source_reference=source,
        criteria=[item.model_dump(mode="json") for item in data.criteria],
        created_by=user.id,
    )
    db.add(standard)
    db.flush()
    add_audit_log(db, actor_id=user.id, action_type="CREATE_STANDARD", resource_type="PRODUCT", resource_id=product_id, request_summary=f"创建检测标准第 {version} 版", result_status="SUCCESS")
    db.commit()
    db.refresh(standard)
    return standard
