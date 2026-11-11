"""回归用例草稿、权限范围、去重和审阅状态流转。"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.errors import AuthorizationError, BusinessValidationError, ResourceNotFoundError
from app.modules.ai import regression_cases
from app.modules.ai.model import AIAgentTask, AIFeedback, AIRegressionCase
from app.modules.ai.schema import RegressionCaseCreate
from app.modules.system.model import User


@pytest.fixture
def regression_db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ai_agent_tasks (
                id VARCHAR(32) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                status VARCHAR(24) NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                payload JSON NOT NULL,
                reply TEXT NOT NULL,
                error_code VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ai_feedback (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                task_id VARCHAR(32) NOT NULL,
                rating VARCHAR(8) NOT NULL,
                reason_code VARCHAR(32),
                comment VARCHAR(1000),
                correction TEXT,
                prompt_version VARCHAR(100),
                prompt_versions JSON,
                model_name VARCHAR(100),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE ai_regression_cases (
                id INTEGER PRIMARY KEY,
                case_key VARCHAR(64) NOT NULL UNIQUE,
                source_task_id VARCHAR(32),
                source_task_hash VARCHAR(64),
                source_prompt_version VARCHAR(100),
                question TEXT NOT NULL,
                expected_execution_mode VARCHAR(16) NOT NULL,
                expected_tasks JSON NOT NULL,
                forbidden_tasks JSON NOT NULL,
                note VARCHAR(500),
                status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
                created_by INTEGER NOT NULL,
                reviewed_by INTEGER,
                reviewed_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
    session = Session(engine, autoflush=False, expire_on_commit=False)
    roles: dict[int, list[str]] = {}
    monkeypatch.setattr(regression_cases, "get_user_role_codes",
                        lambda _db, user_id: roles.get(user_id, []))
    session.roles = roles
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(user_id):
    return User(id=user_id, username=f"user{user_id}", status="ACTIVE", password_hash="x")


def _task(db, task_id, *, user_id=1, question="查合成乙醇库存",
          tools=("catalog.search_products", "inventory.query_available"),
          status="SUCCEEDED", error_code=None, minutes_ago=0):
    now = datetime.now() - timedelta(minutes=minutes_ago)
    db.add(AIAgentTask(
        id=task_id, user_id=user_id, status=status, revision=0,
        payload={"messages": [question],
                 "run_meta": {"prompt_versions": {"routing": "routing@1-bbb", "planner": "planner@1-aaa"}},
                 "trace": [{"action": "call_tool", "tool": tool} for tool in tools]},
        reply="", error_code=error_code, created_at=now, updated_at=now))
    db.commit()


def _feedback(db, task_id, rating, reason_code=None, *, user_id=1, minutes_ago=0):
    now = datetime.now() - timedelta(minutes=minutes_ago)
    db.add(AIFeedback(id=None, user_id=user_id, task_id=task_id, rating=rating,
                      reason_code=reason_code, comment=None, correction=None,
                      prompt_version=None, prompt_versions=None, model_name=None,
                      created_at=now, updated_at=now))
    db.commit()


def test_draft_from_own_task_derives_contract_but_keeps_text_for_review(regression_db):
    _task(regression_db, "task-a")
    user = _user(1)

    draft = regression_cases.draft_from_task(regression_db, user, "task-a")

    assert draft.source_task_id == "task-a"
    assert draft.source_task_hash == regression_cases._task_hash("task-a")
    assert draft.source_prompt_version == "planner@1-aaa"
    assert draft.question == "查合成乙醇库存"
    assert draft.expected_execution_mode == "agent"
    assert draft.expected_tasks == ["inventory"]

    with pytest.raises(ResourceNotFoundError):
        regression_cases.draft_from_task(regression_db, _user(2), "task-a")


def test_create_requires_redaction_confirmation_and_owned_source(regression_db):
    _task(regression_db, "task-a")
    _task(regression_db, "task-b", user_id=2)
    user = _user(1)
    data = dict(source_task_id="task-a", question="查合成乙醇库存，核对可用量",
                expected_execution_mode="agent", expected_tasks=["inventory"])

    with pytest.raises(BusinessValidationError, match="脱敏"):
        regression_cases.create_case(regression_db, user, RegressionCaseCreate(**data))

    created = regression_cases.create_case(regression_db, user, RegressionCaseCreate(
        **data, redacted_confirmed=True))
    assert created.status == "DRAFT"
    assert created.expected_tasks == ["inventory"]
    assert created.source_task_hash == regression_cases._task_hash("task-a")

    duplicate = regression_cases.create_case(regression_db, user, RegressionCaseCreate(
        **data, redacted_confirmed=True))
    assert duplicate.id == created.id

    with pytest.raises(ResourceNotFoundError):
        regression_cases.create_case(regression_db, user, RegressionCaseCreate(
            **{**data, "source_task_id": "task-b"}, redacted_confirmed=True))


def test_task_lists_are_owner_scoped_and_admin_can_review(regression_db):
    _task(regression_db, "task-a")
    _task(regression_db, "task-b", user_id=2)
    user1, user2 = _user(1), _user(2)
    case1 = regression_cases.create_case(regression_db, user1, RegressionCaseCreate(
        source_task_id="task-a", question="查合成乙醇库存，核对可用量",
        expected_execution_mode="agent", expected_tasks=["inventory"],
        redacted_confirmed=True))
    case2 = regression_cases.create_case(regression_db, user2, RegressionCaseCreate(
        source_task_id="task-b", question="查测试甲醇库存，核对可用量",
        expected_execution_mode="agent", expected_tasks=["inventory"],
        redacted_confirmed=True))

    page1 = regression_cases.list_cases(regression_db, user1)
    assert page1.total == 1 and page1.items[0].id == case1.id

    regression_db.roles[2] = ["SYS_ADMIN"]
    admin_page = regression_cases.list_cases(regression_db, user2)
    assert admin_page.total == 2
    assert {case1.id, case2.id} == {row.id for row in admin_page.items}

    with pytest.raises(AuthorizationError):
        regression_cases.review_case(regression_db, user1, case1.id, "APPROVE")

    approved = regression_cases.review_case(regression_db, user2, case1.id, "APPROVE")
    assert approved.status == "APPROVED" and approved.reviewed_by == 2
    with pytest.raises(BusinessValidationError):
        regression_cases.review_case(regression_db, user2, case1.id, "APPROVE")
    archived = regression_cases.review_case(regression_db, user2, case1.id, "ARCHIVE")
    assert archived.status == "ARCHIVED"


def test_create_rejects_unknown_or_conflicting_tasks(regression_db):
    _task(regression_db, "task-a")
    user = _user(1)

    with pytest.raises(BusinessValidationError, match="未登记"):
        regression_cases.create_case(regression_db, user, RegressionCaseCreate(
            source_task_id="task-a", question="查合成乙醇库存，核对可用量",
            expected_execution_mode="agent", expected_tasks=["unknown"],
            redacted_confirmed=True))

    with pytest.raises(BusinessValidationError, match="不能同时"):
        regression_cases.create_case(regression_db, user, RegressionCaseCreate(
            source_task_id="task-a", question="查合成乙醇库存，核对可用量",
            expected_execution_mode="agent", expected_tasks=["inventory"],
            forbidden_tasks=["inventory"], redacted_confirmed=True))

    assert regression_db.scalar(select(AIRegressionCase)) is None


def test_candidates_come_from_feedback_or_failure_owner_scoped_and_deduped(regression_db):
    _task(regression_db, "task-a", status="FAILED", error_code="INTENT_SCHEMA_ERROR")
    _task(regression_db, "task-a2", status="SUCCEEDED", minutes_ago=5)
    _task(regression_db, "task-b", user_id=2, question="查测试甲醇库存")
    _task(regression_db, "task-c", status="FAILED", error_code="TOOL_TIMEOUT",
          question="查合成甲醇库存", minutes_ago=10)
    _feedback(regression_db, "task-a", "DOWN", "WRONG_ANSWER")
    _feedback(regression_db, "task-a2", "DOWN", "WRONG_NUMBER", minutes_ago=1)
    _feedback(regression_db, "task-b", "DOWN", "WRONG_ANSWER", user_id=2)

    page = regression_cases.candidate_drafts(regression_db, _user(1), days=7, limit=10)

    assert page.total == 2
    item = page.items[0]
    assert item.source_task_id == "task-a" and item.question == "查合成乙醇库存"
    assert item.source == "feedback"
    assert item.task_status == "FAILED" and item.error_code == "INTENT_SCHEMA_ERROR"
    assert item.failure_stage == "routing" and item.feedback_reason_code == "WRONG_ANSWER"
    assert item.existing_case_id is None
    assert item.case_key.startswith("PR-")
    assert page.items[1].source == "failure" and page.items[1].failure_stage == "tool"
    assert page.items[1].feedback_reason_code is None

    regression_db.roles[2] = ["SYS_ADMIN"]
    admin_page = regression_cases.candidate_drafts(regression_db, _user(2), days=7, limit=10)
    assert admin_page.total == 3


def test_candidate_links_existing_case_and_limits_are_validated(regression_db):
    _task(regression_db, "task-a", status="FAILED", error_code="TOOL_ERRORS")
    _feedback(regression_db, "task-a", "DOWN", "TOOL_ERROR")
    page = regression_cases.candidate_drafts(regression_db, _user(1), days=7, limit=10)
    draft = page.items[0]

    case = regression_cases.create_case(regression_db, _user(1), RegressionCaseCreate(
        source_task_id=draft.source_task_id, question="查【已脱敏产品】库存",
        expected_execution_mode=draft.expected_execution_mode,
        expected_tasks=draft.expected_tasks, redacted_confirmed=True))
    regression_db.roles[1] = ["SYS_ADMIN"]
    regression_cases.review_case(regression_db, _user(1), case.id, "APPROVE")
    regression_db.roles.pop(1)

    again = regression_cases.candidate_drafts(regression_db, _user(1), days=7, limit=10)
    assert again.items[0].existing_case_id == case.id
    assert again.items[0].case_key != case.case_key  # 脱敏改写后仍按来源任务关联

    with pytest.raises(BusinessValidationError):
        regression_cases.candidate_drafts(regression_db, _user(1), days=0, limit=10)
    with pytest.raises(BusinessValidationError):
        regression_cases.candidate_drafts(regression_db, _user(1), days=7, limit=99)


def test_approved_case_exports_without_task_or_user_identity(regression_db):
    from scripts.export_regression_cases import case_payload

    _task(regression_db, "task-a", status="FAILED", error_code="INTENT_SCHEMA_ERROR")
    _feedback(regression_db, "task-a", "DOWN", "WRONG_ANSWER")
    regression_db.roles[1] = ["SYS_ADMIN"]
    case = regression_cases.create_case(regression_db, _user(1), RegressionCaseCreate(
        source_task_id="task-a", question="查合成乙醇库存，核对可用量",
        expected_execution_mode="agent", expected_tasks=["inventory"],
        note="差评任务转用例", redacted_confirmed=True))
    approved = regression_cases.review_case(regression_db, _user(1), case.id, "APPROVE")

    assert approved.status == "APPROVED"
    payload = case_payload(regression_db.get(AIRegressionCase, case.id))
    assert payload["id"] == case.case_key
    assert payload["question"] == "查合成乙醇库存，核对可用量"
    assert "source_task_id" not in payload and "created_by" not in payload
    assert payload["source_task_hash"] == regression_cases._task_hash("task-a")
