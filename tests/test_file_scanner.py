"""文件上传病毒扫描适配器测试。"""

from subprocess import CompletedProcess

from app.core.config import Settings
from app.modules.files import scanner


def test_scanner_is_skipped_by_default(monkeypatch) -> None:
    """开发环境默认不调用外部扫描进程。"""

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("未启用扫描时不应启动外部进程")

    monkeypatch.setattr(scanner.subprocess, "run", fail_if_called)
    result = scanner.scan_content(b"safe", settings=Settings(file_scan_enabled=False))
    assert result.status == "SKIPPED"


def test_scanner_accepts_clean_content(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, stdout=b"OK", stderr=b"")

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)
    result = scanner.scan_content(b"safe", settings=Settings(file_scan_enabled=True, file_scan_command="clamdscan"))
    assert result.status == "CLEAN"
    assert calls[0][0] == ["clamdscan", "--stream"]
    assert calls[0][1]["input"] == b"safe"
    assert calls[0][1]["shell"] is False


def test_scanner_rejects_infected_content(monkeypatch) -> None:
    monkeypatch.setattr(
        scanner.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess(["clamdscan"], 1, stdout=b"FOUND", stderr=b""),
    )
    result = scanner.scan_content(b"bad", settings=Settings(file_scan_enabled=True))
    assert result.status == "INFECTED"
