"""保存带原文依据的不可变化学品百科版本。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, Text, UniqueConstraint, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base
from app.modules.jobs_scheduler.wiki_release import validate_pair


class WikiVersion(Base):
    __tablename__ = 'chemical_wiki_versions'
    __table_args__ = (UniqueConstraint('entry_id', 'version', name='uq_chemical_wiki_entry_version'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default='')
    actor_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


def history(db: Session, entry_id: int) -> list[WikiVersion]:
    return list(db.scalars(select(WikiVersion).where(WikiVersion.entry_id == entry_id)
                           .order_by(WikiVersion.version.desc())).all())


def create_version(db: Session, entry_id: int, expected_version: int, content: dict,
                   note: str, *, actor_id: int, baseline: dict | None = None) -> WikiVersion:
    validate_pair(content, entry_id)
    if baseline is not None:
        validate_pair(baseline, entry_id)
    current = db.scalar(select(func.max(WikiVersion.version)).where(WikiVersion.entry_id == entry_id)) or 0
    if current != expected_version:
        raise ValueError('版本已变化，请刷新后重试')
    original = db.scalar(select(WikiVersion.id).where(WikiVersion.entry_id == entry_id, WikiVersion.version == 0))
    if original is None:
        db.add(WikiVersion(entry_id=entry_id, version=0, content=baseline or content, note='', actor_id=actor_id))
    version = WikiVersion(entry_id=entry_id, version=current + 1, content=content,
                          note=note, actor_id=actor_id)
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError('版本已变化，请刷新后重试') from exc
    return version
