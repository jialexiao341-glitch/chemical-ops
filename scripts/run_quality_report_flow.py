"""在本地开发库关联质量报告，并调用现有只读核对服务。"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.modules.deliveries.model import DeliveryItem  # noqa: E402
from app.modules.files import service as file_service  # noqa: E402
from app.modules.files.schema import FileAttachmentCreate  # noqa: E402
from app.modules.quality_acceptances.model import QualityAcceptance  # noqa: E402
from app.modules.quality_acceptances.report_review import list_report_files, review_report  # noqa: E402
from app.modules.system.model import User  # noqa: E402


CASES = (
    ("QA-26001", "B2609001", "QC-20260925-001_无水乙醇到货检验记录.txt"),
    ("QA-26002", "B2609002", "QC-20260925-002_丙酮到货检验记录.txt"),
    ("QA-26002", "B2609002", "QC-20260925-003_丙酮留样复核记录.txt"),
)


def main() -> None:
    """仅在本地开发环境运行报告上传、核对与复核流程的演示脚本。"""
    settings = get_settings()
    if settings.app_env.lower() not in {"development", "dev", "local"}:
        raise SystemExit("仅允许在本地开发环境运行")

    with SessionLocal() as db:
        for acceptance_no, expected_batch, file_name in CASES:
            acceptance = db.scalar(select(QualityAcceptance).where(QualityAcceptance.acceptance_no == acceptance_no))
            if acceptance is None:
                raise SystemExit(f"缺少验收单 {acceptance_no}")
            batches = set(db.scalars(select(DeliveryItem.batch_no).where(DeliveryItem.delivery_id == acceptance.delivery_id)).all())
            if expected_batch not in batches:
                raise SystemExit(f"验收单 {acceptance_no} 的批次与报告不符")
            user = db.get(User, acceptance.inspector_id)
            if user is None or user.status != "ACTIVE":
                raise SystemExit(f"验收单 {acceptance_no} 缺少可用检验员")

            linked = next((item for item in list_report_files(db, user, acceptance.id) if item.file_name == file_name), None)
            if linked is None:
                path = ROOT / "docs" / "quality-reports" / file_name
                value = file_service.upload_file(
                    db, user,
                    file_name=file_name,
                    mime_type="text/plain",
                    content=path.read_bytes(),
                    file_category="QUALITY_REPORT",
                    access_level="INTERNAL",
                )
                file_service.attach_file(
                    db, user, value.id,
                    FileAttachmentCreate(resource_type="QUALITY_ACCEPTANCE", resource_id=acceptance.id),
                )
                file_id = value.id
                action = "uploaded"
            else:
                file_id = linked.id
                action = "existing"

            review = asyncio.run(review_report(db, user, acceptance.id, file_id))
            counts = Counter(item.status for item in review.checks)
            print(f"{acceptance_no} | {file_name} | file_id={file_id} | {action} | product={review.product_status} | batch={review.batch_status} | standard={review.standard_version or 'none'} | checks={dict(counts)}")


if __name__ == "__main__":
    main()
