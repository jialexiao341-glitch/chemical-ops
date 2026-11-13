"""工具结果受控续读的权限、分页与快照语义。"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai_agent.evidence_store import make_ref, read_evidence
from app.modules.ai_agent.model import AIAgentTask
from app.modules.ai_agent.schema import EvidenceReadInput


def _task(trace, *, user_id=7, task_id="a" * 32):
    now = datetime(2026, 11, 10, 12, 0, 0)
    return AIAgentTask(id=task_id, user_id=user_id, status="SUCCEEDED", revision=1,
                       payload={"trace": trace}, reply="", created_at=now, updated_at=now)


def _trace(rows, *, tool="suppliers.profile", step=3):
    return [{"step": step, "action": "call_tool", "tool": tool, "status": "SUCCEEDED",
             "captured_at": "2026-11-10T12:00:00", "result": {"rows": rows, "total_rows": len(rows)}}]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    AIAgentTask.__table__.create(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _skip_permission_recheck(monkeypatch):
    from app.modules.ai_agent import agent_runtime
    monkeypatch.setattr(agent_runtime, "_check_trace_access", lambda *args, **kwargs: [])


def test_pages_are_bounded_and_report_next_offset(db):
    rows = [{"po_no": f"PO{i}", "amount": i} for i in range(1, 8)]
    db.add(_task(_trace(rows)))
    db.commit()
    user = SimpleNamespace(id=7, status="ACTIVE")

    page = read_evidence(db, user, EvidenceReadInput(ref=make_ref("a" * 32, 3), offset=0, limit=3))
    assert page.returned == 3
    assert page.total_rows == 7
    assert page.next_offset == 3
    assert page.snapshot_only is True
    assert page.volatile is False
    assert "历史快照" in page.note

    last = read_evidence(db, user, EvidenceReadInput(ref=make_ref("a" * 32, 3), offset=6, limit=3))
    assert last.returned == 1
    assert last.next_offset is None


def test_volatile_tools_are_marked_as_snapshot_only(db):
    db.add(_task(_trace([{"product_id": 1, "available": "10"}], tool="inventory.query_available")))
    db.commit()
    user = SimpleNamespace(id=7, status="ACTIVE")
    page = read_evidence(db, user, EvidenceReadInput(ref=make_ref("a" * 32, 3)))
    assert page.volatile is True
    assert "不代表当前库存" in page.note


def test_other_users_and_invalid_steps_are_rejected(db):
    db.add(_task(_trace([{"x": 1}])))
    db.commit()
    stranger = SimpleNamespace(id=8, status="ACTIVE")
    with pytest.raises(ResourceNotFoundError):
        read_evidence(db, stranger, EvidenceReadInput(ref=make_ref("a" * 32, 3)))
    with pytest.raises(BusinessValidationError):
        read_evidence(db, SimpleNamespace(id=7, status="ACTIVE"),
                      EvidenceReadInput(ref=make_ref("a" * 32, 4)))


def test_ref_format_is_strict():
    with pytest.raises(BusinessValidationError):
        read_evidence(None, None, EvidenceReadInput.model_construct(ref="task:short/step:1"))
    with pytest.raises(ValueError):
        EvidenceReadInput(ref="task:not-a-task/step:1")


def test_inactive_user_is_denied(db):
    db.add(_task(_trace([{"x": 1}])))
    db.commit()
    with pytest.raises(AuthorizationError):
        read_evidence(db, SimpleNamespace(id=7, status="INACTIVE"),
                      EvidenceReadInput(ref=make_ref("a" * 32, 3)))


def test_planner_view_exposes_spill_ref_for_truncated_results():
    from app.modules.ai_agent.agent_runtime import _planner_view

    entry = {"step": 2, "action": "call_tool", "tool": "suppliers.profile", "status": "SUCCEEDED",
             "result": {"rows": [{"i": i} for i in range(20)], "total_rows": 20}}
    view = _planner_view(entry, "a" * 32)
    assert view["result"]["planner_truncated"] is True
    assert view["result"]["spill_ref"] == make_ref("a" * 32, 2)
    assert "spill_hint" in view["result"]


def test_planner_view_marks_tool_level_truncation():
    from app.modules.ai_agent.agent_runtime import _planner_view

    entry = {"step": 4, "action": "call_tool", "tool": "quality_acceptances.get_by_no",
             "status": "SUCCEEDED", "result": {"rows": [{"i": 1}], "truncated": True}}
    view = _planner_view(entry, "b" * 32)
    assert view["result"]["planner_truncated"] is True
    assert view["result"]["spill_ref"] == make_ref("b" * 32, 4)