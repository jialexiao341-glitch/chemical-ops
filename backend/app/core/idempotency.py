"""HTTP 层统一 Idempotency-Key 中间件。"""

from datetime import datetime, timedelta
from hashlib import sha256
import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.system.idempotency_model import IdempotencyRecord


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """对带 Idempotency-Key 的写请求保存并回放首次响应。"""

    @staticmethod
    def _replay_existing(record: IdempotencyRecord, request: Request, request_hash: str, key: str):
        """检查已有记录是否属于当前请求，并返回回放或冲突响应。"""
        if record.expires_at <= datetime.now() or record.method != request.method or record.path != request.url.path or record.request_hash != request_hash:
            return JSONResponse(status_code=409, content={"code": 409, "message": "数据已存在", "detail": "Idempotency-Key 已用于其他请求"})
        if record.status == "IN_PROGRESS":
            return JSONResponse(status_code=409, content={"code": 409, "message": "数据已存在", "detail": "相同请求正在处理中，请稍后重试"})
        return JSONResponse(status_code=record.response_status or 200, content=record.response_body)

    @staticmethod
    def _remove_record(record_id: int) -> None:
        """删除执行异常或不可回放响应留下的幂等占位记录。"""
        db = SessionLocal()
        try:
            record = db.get(IdempotencyRecord, record_id)
            if record is not None and record.status == "IN_PROGRESS":
                db.delete(record)
                db.commit()
        finally:
            db.close()

    async def dispatch(self, request: Request, call_next):
        key = request.headers.get("Idempotency-Key")
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        if not key:
            if get_settings().idempotency_required:
                return JSONResponse(status_code=428, content={"code": 428, "message": "请求条件不满足", "detail": "写请求必须携带 Idempotency-Key"})
            return await call_next(request)
        if len(key) > 128:
            return JSONResponse(status_code=422, content={"code": 422, "message": "请求参数校验失败", "detail": "Idempotency-Key 长度不能超过 128 个字符"})
        body = await request.body()
        request_hash = sha256(body).hexdigest()
        actor_key = sha256(request.headers.get("Authorization", "anonymous").encode("utf-8")).hexdigest()
        db = SessionLocal()
        record = None
        try:
            record = db.query(IdempotencyRecord).filter(IdempotencyRecord.actor_key == actor_key, IdempotencyRecord.idempotency_key == key).first()
            if record is not None:
                return self._replay_existing(record, request, request_hash, key)
            record = IdempotencyRecord(idempotency_key=key, actor_key=actor_key, method=request.method, path=request.url.path, request_hash=request_hash, status="IN_PROGRESS", expires_at=datetime.now() + timedelta(hours=24))
            db.add(record)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                record = db.query(IdempotencyRecord).filter(IdempotencyRecord.actor_key == actor_key, IdempotencyRecord.idempotency_key == key).first()
                if record is None:
                    return JSONResponse(status_code=409, content={"code": 409, "message": "数据已存在", "detail": "幂等请求正在建立，请稍后重试"})
                return self._replay_existing(record, request, request_hash, key)
        except Exception:
            db.rollback()
            raise
        finally:
            record_id = record.id if record is not None else None
            db.close()

        try:
            response = await call_next(request)
            response_body = b"".join([chunk async for chunk in response.body_iterator])
        except Exception:
            if record_id is not None:
                self._remove_record(record_id)
            raise
        try:
            content = json.loads(response_body.decode("utf-8")) if response_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            content = None
        db = SessionLocal()
        try:
            saved = db.get(IdempotencyRecord, record_id) if record_id is not None else None
            if saved is not None:
                if response.status_code < 500 and content is not None:
                    saved.status = "COMPLETED"
                    saved.response_status = response.status_code
                    saved.response_body = content
                else:
                    db.delete(saved)
                db.commit()
        finally:
            db.close()
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=response_body, status_code=response.status_code, headers=headers, media_type=response.media_type)
