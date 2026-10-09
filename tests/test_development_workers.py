"""Development launcher starts workers once and cleans up when API startup fails."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import main as launcher
from app.core import config
from app.modules.task_queue import processes


@pytest.mark.parametrize("modes,expected", [
    (("database", "database"), ["documents", "agent"]),
    (("in_process", "database"), ["agent"]),
    (("in_process", "in_process"), []),
])
def test_development_starts_configured_workers_and_cleans_up_on_api_failure(monkeypatch, modes, expected):
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(
        technical_document_execution_mode=modes[0], agent_execution_mode=modes[1]))
    children, jobs = [], []
    def spawn(arguments, **options):
        child = MagicMock(pid=100 + len(children))
        child.poll.return_value = None
        children.append((arguments, child))
        return child
    def job(pid):
        handle = MagicMock()
        jobs.append(handle)
        return handle
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(processes, "WindowsJob", job)
    monkeypatch.setattr(launcher.os, "killpg", lambda *_args: None, raising=False)
    def fail_api(*_args, **_options):
        assert len(children) == len(expected)
        raise RuntimeError("substitute API failure")
    monkeypatch.setattr(launcher.uvicorn, "run", fail_api)
    with pytest.raises(RuntimeError, match="substitute API failure"):
        launcher.run_server("dev")
    assert [arguments[arguments.index("--queue") + 1] for arguments, _ in children] == expected
    for _, child in children:
        child.wait.assert_called_once_with(timeout=10)
    for handle in jobs:
        handle.close.assert_called_once()


def test_production_leaves_workers_to_process_manager(monkeypatch):
    spawn = MagicMock()
    run = MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher.uvicorn, "run", run)
    launcher.run_server("prod")
    spawn.assert_not_called()
    assert run.call_args.kwargs["reload"] is False
