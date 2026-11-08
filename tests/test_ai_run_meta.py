"""Agent 运行元数据的兼容性和脱敏回归。"""

from app.modules.ai import agent_runtime as runtime
from app.modules.ai.schema import AIChatMessage, AIChatResponse, TaskRead
from types import SimpleNamespace


def test_task_read_defaults_to_empty_metadata():
    task = TaskRead(id="old", status="SUCCEEDED", revision=1, reply="", error_code=None, messages=[], trace=[])
    assert task.run_meta == {}


def test_response_metadata_records_only_actual_safe_fields():
    state = runtime.RunState("task", 0, [], [], 0)
    response = AIChatResponse(message=AIChatMessage(role="assistant", content="secret"),
        conversation_id=0, model="actual", provider="provider", usage={"total_tokens": 12},
        call_meta={"requested_model": "original", "attempts": 2, "fallback_used": True})
    runtime._record_model_response(state, response)
    assert state.run_meta["model"] == {"provider": "provider", "name": "actual", "usage": {"total_tokens": 12},
        "requested_model": "original", "fallback_used": True}
    assert state.run_meta["retries"]["llm"] == 1
    assert "secret" not in str(state.run_meta)


def test_failed_call_does_not_invent_attempts():
    state = runtime.RunState("task", 0, [], [], 0)
    runtime._record_model_response(state, None)
    assert state.run_meta["retries"]["llm"] is None


def test_queue_failure_exposes_terminal_error_without_changing_payload():
    task = SimpleNamespace(status="FAILED", error_code="TASK_EXECUTION_ERROR",
        payload={"run_meta": {"prompt_versions": {}}})
    error = runtime._public_run_meta(task)["error"]
    assert error["code"] == "TASK_EXECUTION_ERROR"
    assert error["class"] == "UNKNOWN" and error["recovery"] == "CONTACT_SUPPORT"
    assert "error" not in task.payload["run_meta"]
    task.payload = {}
    assert runtime._public_run_meta(task) == {}


def test_existing_error_classification_is_preserved():
    task = SimpleNamespace(status="FAILED", error_code="UPDATED",
        payload={"run_meta": {"error": {"code": "OLD", "class": "BUDGET", "recovery": "NARROW_SCOPE"}}})
    assert runtime._public_run_meta(task)["error"] == {
        "code": "UPDATED", "class": "BUDGET", "recovery": "NARROW_SCOPE"}
