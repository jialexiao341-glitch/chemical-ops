"""AI 文档知识库数据库模型。"""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AiDocument(Base):
    """一份解析后的化学品文档（MSDS / TDS / 物性页）。"""

    __tablename__ = "ai_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    cas_no: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_zh: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_bucket: Mapped[str] = mapped_column(String(64), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_count: Mapped[int] = mapped_column(nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(nullable=False, default=0)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, server_default=func.current_timestamp(3), onupdate=func.current_timestamp(3)
    )

    __table_args__ = ({"mysql_charset": "utf8mb4"},)


class AiDocumentSection(Base):
    """文档章节：SDS 按 SECTION 切、物性页按 h2/h3 切、TDS PDF 按页切。"""

    __tablename__ = "ai_document_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("ai_documents.id"), nullable=False)
    cas_no: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    section_no: Mapped[int | None] = mapped_column(nullable=True)
    section_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    char_count: Mapped[int] = mapped_column(nullable=False, default=0)

    __table_args__ = ({"mysql_charset": "utf8mb4"},)
