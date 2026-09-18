"""产品分类树的最小模型，供产品表建立自关联外键。"""

from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductCategory(Base):
    """产品分类树节点。"""

    __tablename__ = "md_product_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("md_product_categories.id"), nullable=True)
    category_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
