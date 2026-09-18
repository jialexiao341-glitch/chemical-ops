"""MinerU 官方异步接口契约测试，不访问真实网络。"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from app.core.config import Settings
from app.modules.files import mineru


class FakeResponse:
    def __init__(self, payload: dict | None = None, content: bytes = b"", status_code: int = 200) -> None:
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise mineru.httpx.HTTPStatusError("fake failure", request=None, response=None)

    def json(self) -> dict:
        assert self._payload is not None
        return self._payload


class FakeClient:
    requests: list[dict] = []
    poll_count = 0
    archive = b""

    def __init__(self, **_: object) -> None:
        self.__class__.requests = []
        self.__class__.poll_count = 0

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict) -> FakeResponse:
        self.requests.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return FakeResponse({"code": 0, "data": {"batch_id": "batch-1", "file_urls": ["https://upload.example/signed"]}})

    def put(self, url: str, *, content: bytes) -> FakeResponse:
        self.requests.append({"method": "PUT", "url": url, "content": content})
        return FakeResponse({"code": 0})

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        if url.endswith("/batch-1"):
            type(self).poll_count += 1
            if type(self).poll_count == 1:
                return FakeResponse({"code": 0, "data": {"extract_result": [{"state": "running"}]}})
            return FakeResponse({"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": "https://download.example/result.zip"}]}})
        return FakeResponse(content=self.archive)


def _archive(text: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as bundle:
        bundle.writestr("full.md", text)
    return buffer.getvalue()


def test_mineru_v4_upload_poll_and_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.archive = _archive("# 到货计划\n\n乙醇：12 千克")
    monkeypatch.setattr(mineru.httpx, "Client", FakeClient)
    settings = Settings(
        mineru_api_key="test-token",
        mineru_base_url="https://mineru.example/api/v4",
        mineru_poll_interval_seconds=0,
    )

    result = mineru.parse_bytes("到货计划.pdf", b"%PDF-test", settings)

    assert result.status == "SUCCEEDED"
    assert "乙醇：12 千克" in result.text
    assert result.parser == "mineru-v4-vlm"
    assert result.references[0]["locator"] == "full.md"
    post_request = FakeClient.requests[0]
    assert post_request["url"] == "https://mineru.example/api/v4/file-urls/batch"
    assert post_request["headers"] == {"Authorization": "Bearer test-token"}
    assert "test-token" not in str(post_request["json"])
    assert FakeClient.requests[1]["content"] == b"%PDF-test"
    assert FakeClient.poll_count == 2


def test_mineru_failed_task_does_not_fabricate_content(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedClient(FakeClient):
        def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
            if url.endswith("/batch-1"):
                return FakeResponse({"code": 0, "data": {"extract_result": [{"state": "failed", "err_msg": "invalid"}]}})
            return super().get(url, headers=headers)

    monkeypatch.setattr(mineru.httpx, "Client", FailedClient)

    with pytest.raises(mineru.MinerUParseError, match="解析失败"):
        mineru.parse_bytes("坏文件.docx", b"not-a-docx", Settings(mineru_api_key="test-token", mineru_poll_interval_seconds=0))


def test_mineru_retries_transient_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FlakyClient(FakeClient):
        post_attempts = 0

        def post(self, url: str, *, headers: dict[str, str], json: dict) -> FakeResponse:
            type(self).post_attempts += 1
            if type(self).post_attempts == 1:
                raise mineru.httpx.RequestError("temporary network failure", request=None)
            return super().post(url, headers=headers, json=json)

    FlakyClient.archive = _archive("重试成功")
    monkeypatch.setattr(mineru.httpx, "Client", FlakyClient)
    monkeypatch.setattr(mineru.time, "sleep", lambda _seconds: None)

    result = mineru.parse_bytes(
        "重试.pdf",
        b"%PDF-test",
        Settings(mineru_api_key="test-token", mineru_poll_interval_seconds=0, mineru_max_retries=1),
    )

    assert result.status == "SUCCEEDED"
    assert result.text == "重试成功"
    assert FlakyClient.post_attempts == 2
