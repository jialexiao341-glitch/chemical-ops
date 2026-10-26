"""采购催办的发送记录与供应商一次性正式回复。"""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now
from app.models.base import Base


class DeliveryFollowup(Base):
    __tablename__ = 'delivery_followups'
    __table_args__ = (
        UniqueConstraint('proposal_id', name='uq_delivery_followup_proposal'),
        Index('ix_delivery_followup_order', 'order_id', 'sent_at'),
        Index('ix_delivery_followup_supplier', 'supplier_id', 'sent_at'),
        CheckConstraint("status IN ('SENT','REPLIED')", name='ck_delivery_followup_status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey('purchase_orders.id'), nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey('suppliers.id'), nullable=False)
    proposal_id: Mapped[int] = mapped_column(ForeignKey('ai_agent_action_proposals.id'), nullable=False)
    sent_by: Mapped[int] = mapped_column(ForeignKey('sys_users.id'), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utc_now)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default='SENT')
    replied_by: Mapped[int | None] = mapped_column(ForeignKey('sys_users.id'))
    replied_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3))
    reply_message: Mapped[str | None] = mapped_column(String(1000))
    reply_expected_date: Mapped[date | None] = mapped_column(Date)
    reply_request_key: Mapped[str | None] = mapped_column(String(100))
    reply_payload_hash: Mapped[str | None] = mapped_column(String(64))
