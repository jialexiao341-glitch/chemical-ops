"""文件解析中断后的状态回收测试。"""

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.modules.files.service import recover_stale_parses
from app.modules.system.file_model import SysFile
from app.modules.system.model import User


def test_recover_stale_processing_files(db_session) -> None:
    user = db_session.scalar(select(User).where(User.username == "system_admin"))
    assert user is not None
    stale = SysFile(
        file_name="stale.pdf",
        object_key=f"files/{uuid4().hex}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        sha256_hash="a" * 64,
        file_category="TEST",
        access_level="PRIVATE",
        uploader_id=user.id,
        parse_status="PROCESSING",
        updated_at=datetime.now() - timedelta(hours=1),
    )
    fresh = SysFile(
        file_name="fresh.pdf",
        object_key=f"files/{uuid4().hex}.pdf",
        mime_type="application/pdf",
        file_size_bytes=10,
        sha256_hash="b" * 64,
        file_category="TEST",
        access_level="PRIVATE",
        uploader_id=user.id,
        parse_status="PROCESSING",
        updated_at=datetime.now(),
    )
    db_session.add_all([stale, fresh])
    db_session.flush()

    recovered = recover_stale_parses(db_session, stale_after_seconds=60)

    assert recovered == 1
    assert stale.parse_status == "FAILED"
    assert "重新提交" in (stale.parse_error or "")
    assert fresh.parse_status == "PROCESSING"
    assert recover_stale_parses(db_session, stale_after_seconds=60) == 0
