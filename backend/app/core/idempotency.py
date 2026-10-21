"""HTTP 层统一 Idempotency-Key 中间件。"""

from datetime import datetime, timedelta
from hashlib import sha256
import json
import logging

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from app.core.observability import metrics

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token_claims
from app.modules.system.idempotency_model import IdempotencyRecord
from app.modules.system.model import User


LOGGER = logging.getLogger("chemicalops.idempotency")
MAX_CACHED_RESPONSE_BYTES = 1024 * 1024
MAX_IDEMPOTENCY_REQUEST_BYTES = 1024 * 1024
IDEMPOTENCY_EXEMPT_SUFFIXES = ("/auth/login", "/ai/chat/stream")
REPLAYABLE_HEADERS = {
    "cache-control",
    "content-disposition",
    "content-language",
    "content-type",
    "etag",
    "expires",
    "last-modified",
    "location",
    "retry-after",
    "vary",
}


def _error_response(status_code: int, detail: str, *, headers: dict[str, str] | None = None) -> JSONResponse:
    message = {
        409: "数据已存在",
        422: "请求参数校验失败",
        428: "请求条件不满足",
    }.get(status_code, "请求处理失败")
    return JSONResponse(
        status_code=status_code,
        content={"code": status_code, "message": message, "detail": detail},
        headers=headers,
    )


def _replayable_headers(headers) -> dict[str, str]:
    return {
        name.lower(): value
        for name, value in headers.items()
        if name.lower() in REPLAYABLE_HEADERS
    }


def _buffered_response(response, body: bytes) -> Response:
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        background=getattr(response, "background", None),
    )


def _resume_stream(response, body_iterator, buffered_body: bytes) -> StreamingResponse:
    async def content():
        if buffered_body:
            yield buffered_body
        async for chunk in body_iterator:
            yield chunk

    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("transfer-encoding", None)
    return StreamingResponse(
        content(),
        status_code=response.status_code,
        headers=headers,
        background=getattr(response, "background", None),
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """对带 Idempotency-Key 的小型 JSON 写响应保存并回放。"""

    @staticmethod
    def _replay_existing(record: IdempotencyRecord, request: Request, request_hash: str):
        """验证请求指纹，并只回放已完成且可安全重放的 JSON 响应。"""

        request_path = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
        if (
            record.expires_at <= datetime.now()
            or record.method != request.method
            or record.path != request_path
            or record.request_hash != request_hash
        ):
            return _error_response(409, "Idempotency-Key 已用于其他请求")
        if record.status == "IN_PROGRESS":
            return _error_response(
                409,
                "相同请求正在处理中，请稍后重试",
                headers={"Retry-After": "2"},
            )
        if record.status != "COMPLETED":
            return _error_response(
                409,
                "首次请求结果无法安全回放，请核对业务状态后再决定是否重试",
            )
        return JSONResponse(
            status_code=record.response_status or 200,
            content=record.response_body,
            headers=record.response_headers or {},
        )

    @staticmethod
    def _set_record_state(
        record_id: int | None,
        state: str,
        *,
        response_status: int | None = None,
        response_body=None,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        if record_id is None:
            return
        db = SessionLocal()
        try:
            record = db.get(IdempotencyRecord, record_id)
            if record is not None and record.status == "IN_PROGRESS":
                record.status = state
                record.response_status = response_status
                record.response_body = response_body
                record.response_headers = response_headers
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def _best_effort_record_state(cls, record_id: int | None, state: str, **values) -> None:
        try:
            cls._set_record_state(record_id, state, **values)
        except Exception:
            LOGGER.exception("Could not persist idempotency request state=%s", state)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")
        # Login responses contain bearer tokens; SSE must remain incremental.
        if path.endswith(IDEMPOTENCY_EXEMPT_SUFFIXES):
            return await call_next(request)
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)

        # multipart 交给 UploadFile 的限额读取，不在此层复制整个上传体。
        if request.headers.get("content-type", "").lower().startswith("multipart/"):
            return await call_next(request)
        settings = get_settings()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            if settings.idempotency_required:
                return _error_response(428, "写请求必须携带 Idempotency-Key")
            return await call_next(request)
        if len(key) > 128:
            return _error_response(422, "Idempotency-Key 长度不能超过 128 个字符")

        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            return _error_response(422, "Content-Length 不合法")
        if declared > MAX_IDEMPOTENCY_REQUEST_BYTES:
            return _error_response(413, "幂等请求体不能超过 1 MB，文件请使用上传接口")
        chunks = bytearray()
        async for chunk in request.stream():
            if len(chunks) + len(chunk) > MAX_IDEMPOTENCY_REQUEST_BYTES:
                return _error_response(413, "幂等请求体不能超过 1 MB")
            chunks.extend(chunk)
        body = bytes(chunks)
        request._body = body  # Starlette 将已受限的请求体回放给下游。

        request_hash = sha256(body).hexdigest()
        authorization = request.headers.get("Authorization", "")
        actor_identifier = authorization or "anonymous"
        if authorization.lower().startswith("bearer "):
            try:
                user_id, token_version = decode_access_token_claims(authorization[7:].strip())
                auth_db = SessionLocal()
                try:
                    user = auth_db.get(User, user_id)
                    if (
                        user is None
                        or user.status != "ACTIVE"
                        or user.token_version != token_version
                    ):
                        # Let the authentication dependency return 401, not a cached success.
                        return await call_next(request)
                finally:
                    auth_db.close()
                actor_identifier = f"user:{user_id}"
            except jwt.InvalidTokenError:
                # Authentication dependency returns 401; keep invalid tokens isolated.
                actor_identifier = f"token:{authorization}"
        actor_key = sha256(actor_identifier.encode("utf-8")).hexdigest()
        request_path = str(request.url.path) + (f"?{request.url.query}" if request.url.query else "")
        db = SessionLocal()
        record = None
        try:
            record = (
                db.query(IdempotencyRecord)
                .filter(
                    IdempotencyRecord.actor_key == actor_key,
                    IdempotencyRecord.idempotency_key == key,
                )
                .first()
            )
            if record is not None and record.expires_at <= datetime.now():
                db.delete(record)
                db.commit()
                record = None
            if record is not None:
                return self._replay_existing(record, request, request_hash)

            record = IdempotencyRecord(
                idempotency_key=key,
                actor_key=actor_key,
                method=request.method,
                path=request_path,
                request_hash=request_hash,
                status="IN_PROGRESS",
                expires_at=datetime.now() + timedelta(hours=24),
            )
            db.add(record)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                record = (
                    db.query(IdempotencyRecord)
                    .filter(
                        IdempotencyRecord.actor_key == actor_key,
                        IdempotencyRecord.idempotency_key == key,
                    )
                    .first()
                )
                if record is None:
                    return _error_response(
                        409,
                        "相同请求正在建立，请稍后重试",
                        headers={"Retry-After": "2"},
                    )
                return self._replay_existing(record, request, request_hash)
        except Exception:
            db.rollback()
            raise
        finally:
            record_id = record.id if record is not None else None
            db.close()

        try:
            response = await call_next(request)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            is_json = content_type == "application/json" or content_type.endswith("+json")
            if not is_json:
                self._best_effort_record_state(record_id, "NON_REPLAYABLE", response_status=response.status_code)
                return response

            content_length = response.headers.get("content-length")
            try:
                declared_length = int(content_length) if content_length else None
            except ValueError:
                declared_length = None
            if declared_length is not None and declared_length > MAX_CACHED_RESPONSE_BYTES:
                self._best_effort_record_state(record_id, "NON_REPLAYABLE", response_status=response.status_code)
                return response

            body_iterator = getattr(response, "body_iterator", None)
            if body_iterator is None:
                response_body = bytes(getattr(response, "body", b""))
            else:
                chunks = bytearray()
                async for chunk in body_iterator:
                    chunks.extend(chunk)
                    if len(chunks) > MAX_CACHED_RESPONSE_BYTES:
                        self._best_effort_record_state(
                            record_id,
                            "NON_REPLAYABLE",
                            response_status=response.status_code,
                        )
                        return _resume_stream(response, body_iterator, bytes(chunks))
                response_body = bytes(chunks)

            if not response_body:
                self._best_effort_record_state(record_id, "NON_REPLAYABLE", response_status=response.status_code)
                return _buffered_response(response, response_body)

            try:
                response_content = json.loads(response_body.decode("utf-8")) if response_body else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._best_effort_record_state(record_id, "NON_REPLAYABLE", response_status=response.status_code)
                return _buffered_response(response, response_body)

            response_headers = _replayable_headers(response.headers)
            state = "COMPLETED" if response.status_code < 500 else "UNCERTAIN"
            if state == "COMPLETED":
                self._best_effort_record_state(
                    record_id,
                    state,
                    response_status=response.status_code,
                    response_body=response_content,
                    response_headers=response_headers,
                )
            else:
                self._best_effort_record_state(record_id, state, response_status=response.status_code)
            return _buffered_response(response, response_body)
        except Exception:
            self._best_effort_record_state(record_id, "UNCERTAIN")
            raise


def cleanup_expired_records() -> int:
    """按小时调用，单事务删除过期缓存并暴露成功/失败指标。"""
    try:
        with SessionLocal() as db:
            result = db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= datetime.now()))
            db.commit()
            count = result.rowcount
        metrics.increment("idempotency_cleanup", labels={"result": "success"})
        metrics.increment("idempotency_expired_deleted", value=count)
        return count
    except Exception:
        metrics.increment("idempotency_cleanup", labels={"result": "failed"})
        raise
