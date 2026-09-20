"""MinerU v4 精确解析客户端。

官方接口采用异步流程：申请签名上传地址、PUT 原始文件、轮询任务并下载结果压缩包。
本模块负责 MinerU 协议、结果转换以及 PDF/图片的 OCR 解析；调用方通过 MinerU 开关决定是否启用远程服务。
"""

from __future__ import annotations

import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx

from app.core.config import Settings
from app.core.observability import metrics
from app.modules.files.parser import MAX_TEXT_CHARS, ParsedFile


class MinerUParseError(RuntimeError):
    """MinerU 请求、任务或结果格式异常。"""


SUPPORTED_REMOTE_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg"}


def _endpoint(base_url: str, path: str) -> str:
    """拼接 API 地址，允许本地测试使用自定义服务地址。"""

    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _request_with_retry(request: Callable[[], httpx.Response], max_retries: int, *, operation: str = "request") -> httpx.Response:
    """仅对网络层瞬时失败做有限退避，不重复提交业务失败请求。"""

    attempts = max(0, max_retries) + 1
    for attempt in range(attempts):
        try:
            return request()
        except httpx.RequestError:
            if attempt == attempts - 1:
                raise
            metrics.increment("mineru_retries", labels={"operation": operation})
            time.sleep(min(2.0, 0.5 * (2**attempt)))
    raise MinerUParseError("MinerU 请求未执行")


def _json(response: httpx.Response, action: str) -> dict[str, Any]:
    """校验 HTTP 和 MinerU 业务响应，只保留安全的错误摘要。"""

    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MinerUParseError(f"MinerU {action}请求失败") from exc
    if not isinstance(payload, dict):
        raise MinerUParseError(f"MinerU {action}返回格式异常")
    if payload.get("code") not in (0, "0", None):
        raise MinerUParseError(f"MinerU {action}失败")
    return payload


def _extract_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """兼容官方返回的列表形式，并拒绝无法核对的结果。"""

    data = payload.get("data")
    if not isinstance(data, dict):
        raise MinerUParseError("MinerU 轮询结果缺少 data")
    items = data.get("extract_result")
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise MinerUParseError("MinerU 轮询结果缺少 extract_result")
    return items


def _find_markdown(archive: bytes) -> str:
    """从官方结果压缩包中读取 full.md，限制读取到模型的文本长度。"""

    try:
        with zipfile.ZipFile(BytesIO(archive)) as bundle:
            names = bundle.namelist()
            markdown_name = next((name for name in names if Path(name).name.lower() == "full.md"), None)
            if markdown_name is None:
                raise MinerUParseError("MinerU 结果压缩包缺少 full.md")
            text = bundle.read(markdown_name).decode("utf-8", errors="replace").strip()
    except (zipfile.BadZipFile, KeyError, UnicodeError) as exc:
        raise MinerUParseError("MinerU 结果压缩包无法读取") from exc
    return text[:MAX_TEXT_CHARS]


def parse_bytes(file_name: str, content: bytes, settings: Settings) -> ParsedFile:
    """通过 MinerU v4 解析本地文件并返回统一的附件解析结果。"""

    metrics.increment("mineru_requests", labels={"status": "started"})
    if not settings.mineru_api_key.strip():
        metrics.increment("mineru_requests", labels={"status": "failed"})
        raise MinerUParseError("MinerU API key 未配置")
    extension = Path(file_name).suffix.lower()
    is_image = extension in {".png", ".jpg", ".jpeg"}
    if extension not in SUPPORTED_REMOTE_EXTENSIONS:
        raise MinerUParseError(f"MinerU 暂不处理 {extension or '未知'} 文件")

    headers = {"Authorization": f"Bearer {settings.mineru_api_key}"}
    data_id = uuid.uuid4().hex
    request_body = {
        "files": [{"name": Path(file_name).name, "data_id": data_id}],
        "model_version": settings.mineru_model_version,
        "language": settings.mineru_language,
        "enable_table": True,
        "enable_formula": True,
    }
    timeout = httpx.Timeout(settings.mineru_timeout_seconds)
    deadline = time.monotonic() + settings.mineru_timeout_seconds

    try:
        with httpx.Client(timeout=timeout) as client:
            submit = _json(
                _request_with_retry(
                    lambda: client.post(_endpoint(settings.mineru_base_url, "file-urls/batch"), headers=headers, json=request_body),
                    settings.mineru_max_retries,
                    operation="submit",
                ),
                "签名上传地址申请",
            )
            data = submit.get("data")
            if not isinstance(data, dict) or not data.get("batch_id") or not isinstance(data.get("file_urls"), list) or not data["file_urls"]:
                raise MinerUParseError("MinerU 签名上传响应缺少 batch_id 或 file_urls")
            upload_url = data["file_urls"][0]
            if not isinstance(upload_url, str) or not upload_url:
                raise MinerUParseError("MinerU 签名上传地址无效")

            upload_response = _request_with_retry(lambda: client.put(upload_url, content=content), settings.mineru_max_retries, operation="upload")
            try:
                upload_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise MinerUParseError("MinerU 文件上传失败") from exc

            result_url = _endpoint(settings.mineru_base_url, f"extract-results/batch/{data['batch_id']}")
            while True:
                result_payload = _json(
                    _request_with_retry(lambda: client.get(result_url, headers=headers), settings.mineru_max_retries, operation="poll"),
                    "解析任务查询",
                )
                items = _extract_result_items(result_payload)
                item = next((candidate for candidate in items if candidate.get("data_id") == data_id), items[0])
                state = str(item.get("state") or "").lower()
                if state == "done":
                    full_zip_url = item.get("full_zip_url")
                    if not isinstance(full_zip_url, str) or not full_zip_url:
                        raise MinerUParseError("MinerU 已完成但缺少 full_zip_url")
                    archive_response = _request_with_retry(lambda: client.get(full_zip_url), settings.mineru_max_retries, operation="download")
                    try:
                        archive_response.raise_for_status()
                    except httpx.HTTPError as exc:
                        raise MinerUParseError("MinerU 结果下载失败") from exc
                    text = _find_markdown(archive_response.content)
                    status = "SUCCEEDED" if text else "EMPTY"
                    metrics.increment("mineru_requests", labels={"status": "success"})
                    return ParsedFile(
                        status=status,
                        text=text,
                        parser=f"mineru-v4-{settings.mineru_model_version}",
                        references=[{"type": "mineru", "locator": "full.md", "batch_id": data["batch_id"], "ocr": is_image}],
                    )
                if state == "failed":
                    raise MinerUParseError("MinerU 文档解析失败")
                if time.monotonic() >= deadline:
                    raise MinerUParseError("MinerU 文档解析超时")
                time.sleep(max(0.0, settings.mineru_poll_interval_seconds))
    except MinerUParseError:
        metrics.increment("mineru_requests", labels={"status": "failed"})
        raise
    except httpx.TimeoutException as exc:
        metrics.increment("mineru_requests", labels={"status": "failed"})
        raise MinerUParseError("MinerU 请求超时") from exc
    except httpx.RequestError as exc:
        metrics.increment("mineru_requests", labels={"status": "failed"})
        raise MinerUParseError("MinerU 网络请求失败") from exc
