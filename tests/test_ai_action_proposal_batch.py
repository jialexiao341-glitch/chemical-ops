"""批量动作提案：单项失败隔离与输入上限回归。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.errors import BusinessValidationError
from app.modules.ai_agent.action_management import action_proposals
from app.modules.ai_agent.schema import (
    AIActionProposalBatchCreate,
    AIActionProposalCreate,
    AIActionProposalPreview,
)


def _preview(order_id: int) -> AIActionProposalPreview:
    return AIActionProposalPreview(
        confirmation_id=f"{order_id:032x}", action_type="deliveries.followup_draft",
        resource_id=str(order_id), preview_version=1, risk_level="LOW",
        status="PENDING", expires_at=datetime.now())


def test_batch_keeps_successes_and_reports_single_failure(monkeypatch):
    rollbacks = []
    calls = []

    def fake_propose(_db, _user, action_type, payload, *, idempotency_key):
        calls.append((action_type, payload, idempotency_key))
        if payload["order_id"] == 2:
            raise BusinessValidationError("订单状态不允许生成催办草稿")
        return _preview(payload["order_id"])

    monkeypatch.setattr(action_proposals, "propose_action", fake_propose)
    db = SimpleNamespace(rollback=lambda: rollbacks.append(True))
    items = [
        AIActionProposalCreate(action_type="deliveries.followup_draft",
                               payload={"order_id": 1}, idempotency_key="k1"),
        AIActionProposalCreate(action_type="deliveries.followup_draft",
                               payload={"order_id": 2}, idempotency_key="k2"),
        AIActionProposalCreate(action_type="deliveries.followup_draft",
                               payload={"order_id": 3}, idempotency_key="k3"),
    ]

    result = action_proposals.propose_action_batch(db, SimpleNamespace(id=1), items)

    assert [call[1]["order_id"] for call in calls] == [1, 2, 3]
    assert [item.resource_id for item in result.created] == ["1", "3"]
    assert len(result.failed) == 1
    assert result.failed[0].index == 1
    assert result.failed[0].resource_id == "2"
    assert "状态" in result.failed[0].error
    assert rollbacks == [True]


def test_batch_schema_limits_items_and_forbids_extra_fields():
    from app.modules.ai_agent.schema import AIActionProposalBatchResult

    with pytest.raises(ValidationError):
        AIActionProposalBatchCreate(items=[])
    with pytest.raises(ValidationError):
        AIActionProposalBatchCreate(items=[
            AIActionProposalCreate(action_type="deliveries.followup_draft",
                                   payload={"order_id": index}, idempotency_key=f"k{index}")
            for index in range(21)
        ])
    with pytest.raises(ValidationError):
        AIActionProposalBatchCreate(items=[], execute=True)
    assert AIActionProposalBatchResult().created == []