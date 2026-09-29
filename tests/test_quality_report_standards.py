"""质量报告标准核对的确定性边界。"""

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import BusinessValidationError
from app.modules.quality_acceptances.report_review import _check_standard, _choose_target, _product_status
from app.modules.quality_acceptances.schema import QualityCriterion, QualityReviewTarget, QualityStandardCreate
from app.modules.quality_acceptances import standards
from app.modules.quality_acceptances.model import QualityAcceptance, QualityReportReviewRecord
from app.modules.quality_acceptances.schema import QualityReportReview
from app.modules.deliveries.model import DeliveryItem
from app.modules.system.file_model import SysFile, SysFileAttachment
from app.modules.products.model import Product
from app.modules.system.model import User
from .conftest import login


def test_numeric_standard_requires_exact_unit_and_respects_bounds() -> None:
    """验证数值标准对单位和上下限的精确判定。"""
    criterion = QualityCriterion(name="纯度", kind="NUMERIC", unit="%", minimum="99.5", maximum="100")
    assert _check_standard("99.50%", criterion) == "WITHIN_STANDARD"
    assert _check_standard("99.49%", criterion) == "OUTSIDE_STANDARD"
    assert _check_standard("99.50g/L", criterion) == "UNVERIFIED"
    assert _check_standard("约99.50%", criterion) == "UNVERIFIED"


def test_standard_rejects_ambiguous_or_invalid_criteria() -> None:
    """验证无效限值和重名项目会在录入时被拒绝。"""
    with pytest.raises(ValidationError):
        QualityCriterion(name="水分", kind="NUMERIC", unit="%", minimum="1", maximum="0.5")
    with pytest.raises(ValidationError):
        QualityStandardCreate(source_reference="已审核协议", criteria=[
            QualityCriterion(name="纯度", aliases=["含量"], kind="NUMERIC", unit="%", minimum="99"),
            QualityCriterion(name="含量", kind="TEXT", expected_text="合格"),
        ])


def test_multiple_delivery_items_require_explicit_selection() -> None:
    """验证多条到货明细时必须明确选择核对目标。"""
    targets = [
        QualityReviewTarget(delivery_item_id=1, product_id=10, product_name="无水乙醇", batch_no="B1", line_no=1),
        QualityReviewTarget(delivery_item_id=2, product_id=11, product_name="丙酮", batch_no="B2", line_no=2),
    ]
    with pytest.raises(BusinessValidationError):
        _choose_target(targets, None)
    with pytest.raises(BusinessValidationError):
        _choose_target(targets, 999)
    assert _choose_target(targets, 2).product_name == "丙酮"


def test_product_identity_blocks_standard_comparison_when_unverified() -> None:
    """验证产品身份未确认时不能直接视为标准匹配。"""
    assert _product_status("无水乙醇", "无水乙醇", "分析纯（AR）", "AR") == "MATCH"
    assert _product_status("无水乙醇", "无水乙醇", None, "AR") == "UNVERIFIED"
    assert _product_status("无水乙醇", "无水乙醇", "工业级", "AR") == "MISMATCH"
    assert _product_status("乙醇", "无水乙醇", "分析纯（AR）", "AR") == "MISMATCH"
    assert _product_status("丙酮", "无水乙醇（分析纯）") == "MISMATCH"
    assert _product_status(None, "无水乙醇（分析纯）") == "UNVERIFIED"


@pytest.mark.integration
def test_standard_versions_are_immutable(db_session) -> None:
    """验证新增标准会递增版本且保留旧版内容。"""
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").order_by(Product.id))
    user = db_session.scalar(select(User).where(User.status == "ACTIVE").order_by(User.id))
    if product is None or user is None:
        pytest.skip("测试数据库缺少启用的产品或用户")
    original = standards.latest_standard(db_session, product.id)
    data = QualityStandardCreate(
        source_reference="测试用经审核协议 V1",
        criteria=[QualityCriterion(name="纯度", kind="NUMERIC", unit="%", minimum="99.5")],
    )
    first = standards.create_standard(db_session, user, product.id, data)
    second = standards.create_standard(db_session, user, product.id, QualityStandardCreate(
        source_reference="测试用经审核协议 V2",
        criteria=[QualityCriterion(name="纯度", kind="NUMERIC", unit="%", minimum="99.7")],
    ))
    assert first.version_no == (original.version_no if original else 0) + 1
    assert second.version_no == first.version_no + 1
    assert first.criteria[0]["minimum"] == "99.5"
    assert second.criteria[0]["minimum"] == "99.7"


@pytest.mark.integration
def test_standard_api_follows_permissions(client, db_session, demo_password) -> None:
    """验证检测标准接口按产品读写权限开放。"""
    product = db_session.scalar(select(Product).where(Product.status == "ACTIVE").order_by(Product.id))
    if product is None:
        pytest.skip("测试数据库缺少启用的产品")
    admin = login(client, "system_admin", demo_password)
    quality = login(client, "quality_inspector", demo_password)
    payload = {
        "source_reference": "测试用经审核协议 V1",
        "criteria": [{"name": "纯度", "aliases": ["含量"], "kind": "NUMERIC", "unit": "%", "minimum": "99.5"}],
    }
    created = client.post(f"/api/v1/products/{product.id}/quality-standards", headers=admin, json=payload)
    assert created.status_code == 201, created.text
    listed = client.get(f"/api/v1/products/{product.id}/quality-standards", headers=admin)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == created.json()["id"]
    denied = client.post(f"/api/v1/products/{product.id}/quality-standards", headers=quality, json=payload)
    assert denied.status_code == 403


@pytest.mark.integration
def test_review_decision_is_saved_without_changing_acceptance(client, db_session, demo_password) -> None:
    """验证人工复核意见单独保存，不改变验收结论。"""
    acceptance = db_session.scalar(select(QualityAcceptance).order_by(QualityAcceptance.id))
    if acceptance is None:
        pytest.skip("测试数据库缺少验收单")
    item = db_session.scalar(select(DeliveryItem).where(DeliveryItem.delivery_id == acceptance.delivery_id))
    attachment = db_session.scalar(select(SysFileAttachment).where(
        SysFileAttachment.resource_type == "QUALITY_ACCEPTANCE",
        SysFileAttachment.resource_id == acceptance.id,
    ))
    if item is None or attachment is None:
        pytest.skip("测试数据库缺少验收明细或报告附件")
    file = db_session.get(SysFile, attachment.file_id)
    admin_user = db_session.scalar(select(User).where(User.username == "system_admin"))
    assert file is not None and admin_user is not None
    snapshot = QualityReportReview(
        acceptance_id=acceptance.id, delivery_item_id=item.id, file_id=file.id,
        file_name=file.file_name, expected_batch_nos=[item.batch_no] if item.batch_no else [],
        batch_status="UNVERIFIED", checks=[], warnings=[], reviewed_at=acceptance.created_at,
    )
    record = QualityReportReviewRecord(
        acceptance_id=acceptance.id, delivery_item_id=item.id, file_id=file.id,
        result_json=snapshot.model_dump(mode="json"), created_by=admin_user.id,
    )
    db_session.add(record)
    db_session.flush()
    before = acceptance.result
    admin = login(client, "system_admin", demo_password)
    response = client.post(
        f"/api/v1/quality-acceptances/{acceptance.id}/report-reviews/{record.id}/decision",
        headers=admin, json={"status": "CONFIRMED", "reviewer_note": "已核对报告来源"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONFIRMED"
    assert db_session.get(QualityAcceptance, acceptance.id).result == before
    repeated = client.post(
        f"/api/v1/quality-acceptances/{acceptance.id}/report-reviews/{record.id}/decision",
        headers=admin, json={"status": "CONFIRMED", "reviewer_note": "重复确认"},
    )
    assert repeated.status_code == 400
