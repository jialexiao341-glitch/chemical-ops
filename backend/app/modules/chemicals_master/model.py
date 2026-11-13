"""md_chemicals 化学品表的数据库模型。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Chemical(Base):
    """可被多个采购产品复用的化学品身份信息。"""

    __tablename__ = "md_chemicals"

    id: Mapped[int] = mapped_column(primary_key=True)
    chemical_name: Mapped[str] = mapped_column(String(255), nullable=False)
    english_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alias_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cas_no: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    chemical_formula: Mapped[str | None] = mapped_column(String(128), nullable=True)
    molecular_weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    hazard_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )
