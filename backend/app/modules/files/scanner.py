"""文件上传前的可选病毒扫描适配器。"""

from dataclasses import dataclass
import shlex
import subprocess
from time import perf_counter

from app.core.config import Settings, get_settings
from app.core.observability import metrics


@dataclass(frozen=True)
class FileScanResult:
    """扫描结果；SKIPPED 仅表示当前环境没有启用扫描。"""

    status: str
    detail: str | None = None


def scan_content(content: bytes, *, settings: Settings | None = None) -> FileScanResult:
    """通过 clamdscan 标准输入扫描内容，不把文件名或文件内容写入日志。"""

    runtime = settings or get_settings()
    started = perf_counter()
    if not runtime.file_scan_enabled:
        metrics.increment("file_scan", labels={"status": "skipped"})
        return FileScanResult(status="SKIPPED")
    command = shlex.split(runtime.file_scan_command)
    if not command:
        metrics.increment("file_scan", labels={"status": "unavailable"})
        return FileScanResult(status="UNAVAILABLE", detail="文件扫描命令为空")
    try:
        result = subprocess.run(
            [*command, "--stream"],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=runtime.file_scan_timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        metrics.increment("file_scan", labels={"status": "unavailable"})
        return FileScanResult(status="UNAVAILABLE", detail="文件扫描命令不存在")
    except subprocess.TimeoutExpired:
        metrics.increment("file_scan", labels={"status": "timeout"})
        return FileScanResult(status="TIMEOUT", detail="文件扫描超时")
    except OSError:
        metrics.increment("file_scan", labels={"status": "error"})
        return FileScanResult(status="ERROR", detail="文件扫描进程启动失败")
    if result.returncode == 0:
        metrics.increment("file_scan", labels={"status": "clean"})
        metrics.observe("file_scan_duration_seconds", perf_counter() - started, labels={"status": "clean"})
        return FileScanResult(status="CLEAN")
    if result.returncode == 1:
        metrics.increment("file_scan", labels={"status": "infected"})
        metrics.observe("file_scan_duration_seconds", perf_counter() - started, labels={"status": "infected"})
        return FileScanResult(status="INFECTED", detail="扫描引擎报告文件存在风险")
    metrics.increment("file_scan", labels={"status": "error"})
    metrics.observe("file_scan_duration_seconds", perf_counter() - started, labels={"status": "error"})
    return FileScanResult(status="ERROR", detail="文件扫描引擎返回异常状态")
