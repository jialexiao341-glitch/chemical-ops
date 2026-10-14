"""ChemicalOps FastAPI 应用入口。"""

import asyncio
from contextlib import asynccontextmanager, suppress
import hashlib
import logging
from pathlib import Path
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.core.db import SessionLocal, engine, refresh_database_pool_metrics
from app.core.idempotency import IdempotencyMiddleware
from app.core.observability import JsonFormatter, RequestContextMiddleware, metrics
from app.core.task_metrics import refresh_task_queue_metrics
from app.core.telemetry import configure_tracing, shutdown_tracing
from app.core.production import production_config_errors
from app.core.errors import (
    API_ERROR_RESPONSES,
    STATUS_MESSAGES,
    AuthenticationError,
    AuthorizationError,
    BusinessValidationError,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from app.modules.chemicals.controller import router as chemicals_router
from app.modules.batch.controller import router as batch_router
from app.modules.products.controller import router as products_router
from app.modules.purchase_requests.controller import router as purchase_requests_router
from app.modules.purchase_orders.controller import router as purchase_orders_router
from app.modules.deliveries.controller import router as deliveries_router
from app.modules.rfqs.controller import router as rfqs_router
from app.modules.quality_acceptances.controller import router as quality_acceptances_router
from app.modules.inventory.controller import router as inventory_router
from app.modules.operation_exceptions.controller import router as operation_exceptions_router
from app.modules.notifications.controller import router as notifications_router
from app.modules.suppliers.controller import router as suppliers_router
from app.modules.finance.controller import router as finance_router
from app.modules.inventory_returns.controller import router as inventory_returns_router
from app.modules.replenishments.controller import router as replenishments_router
from app.modules.supplier_portal.controller import rfqs_router as supplier_portal_rfqs_router
from app.modules.supplier_portal.controller import router as supplier_portal_router
from app.modules.supplier_portal.controller import collaboration_router as supplier_portal_collaboration_router
from app.modules.files.controller import router as files_router
from app.modules.inventory_cost.controller import router as inventory_cost_router
from app.modules.jobs.controller import router as jobs_router
from app.modules.jobs.service import run_scheduled_alert_scan
from app.modules.dashboard.controller import router as dashboard_router
from app.modules.ai.controller import router as ai_router
from app.modules.insights.controller import router as insights_router
from app.modules.system.controller import auth_router, router as system_router


settings = get_settings()
LOGGER = logging.getLogger("chemicalops.api")


async def _business_alert_scheduler() -> None:
    """按配置间隔运行确定性业务提醒；首次扫描也等待完整间隔。"""

    interval = max(1, settings.overdue_scan_interval_seconds)
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(run_scheduled_alert_scan)
        except Exception:
            LOGGER.exception("定时业务提醒扫描失败")


def _configure_logging() -> None:
    """Apply the configured log level to application loggers."""

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger = logging.getLogger("chemicalops")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.propagate = False


def _check_database() -> bool:
    """Run a minimal database probe without logging credentials."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        LOGGER.exception(
            "中间件检查失败 name=MySQL 主机=%s 端口=%s 数据库=%s",
            settings.mysql_host,
            settings.mysql_port,
            settings.mysql_database,
        )
        return False

    LOGGER.info(
        "中间件检查通过 name=MySQL 主机=%s 端口=%s 数据库=%s",
        settings.mysql_host,
        settings.mysql_port,
        settings.mysql_database,
    )
    return True


def _check_schema_migrations() -> bool:
    """Reject a reachable database whose schema has not caught up to this release."""

    migrations_dir = Path(__file__).resolve().parents[2] / "database" / "migrations"
    migration_pattern = re.compile(r"^(\d{3})_.+\.sql$")
    try:
        migrations = {}
        for path in sorted(migrations_dir.glob("*.sql")):
            match = migration_pattern.fullmatch(path.name)
            if not match:
                raise RuntimeError(f"迁移文件命名无效：{path.name}")
            checksum = hashlib.sha256(
                path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            ).hexdigest()
            migrations[match.group(1)] = checksum
        if not migrations:
            raise RuntimeError(f"迁移目录为空：{migrations_dir}")

        with engine.connect() as connection:
            if not inspect(connection).has_table("schema_migrations"):
                raise RuntimeError("缺少 schema_migrations 迁移台账")
            applied = dict(
                connection.execute(text("SELECT version, checksum FROM schema_migrations")).all()
            )

        unknown = sorted(set(applied) - set(migrations))
        mismatched = sorted(
            version for version, checksum in applied.items()
            if version in migrations and checksum != migrations[version]
        )
        pending = sorted(set(migrations) - set(applied))
        if unknown or mismatched or pending:
            details = []
            if pending:
                details.append("待执行=" + ",".join(pending))
            if mismatched:
                details.append("校验和不匹配=" + ",".join(mismatched))
            if unknown:
                details.append("未知台账版本=" + ",".join(unknown))
            raise RuntimeError("数据库迁移未完成：" + "；".join(details))
    except Exception as exc:
        LOGGER.error("数据库结构检查失败：%s", exc)
        return False

    LOGGER.info("数据库结构检查通过 迁移版本数=%s", len(migrations))
    return True


def _check_minio() -> bool:
    """Check MinIO and the buckets required by the application."""

    backend = settings.file_storage_backend.strip().lower()
    if backend not in {"minio", "s3"}:
        LOGGER.info("中间件检查跳过 name=MinIO 原因=FILE_STORAGE_BACKEND=%s", backend)
        return True

    if not settings.minio_access_key or not settings.minio_secret_key:
        LOGGER.error("中间件检查失败 name=MinIO 原因=未配置访问密钥 endpoint=%s", settings.minio_endpoint)
        return False

    try:
        from minio import Minio

        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            region=settings.minio_region,
        )
        buckets = (
            settings.minio_document_bucket or settings.minio_bucket,
            settings.minio_result_bucket or settings.minio_bucket,
        )
        missing_buckets = [bucket for bucket in dict.fromkeys(buckets) if not client.bucket_exists(bucket)]
    except Exception:
        LOGGER.exception("中间件检查失败 name=MinIO endpoint=%s", settings.minio_endpoint)
        return False

    if missing_buckets:
        LOGGER.warning(
            "中间件检查部分通过 name=MinIO endpoint=%s 缺少桶=%s",
            settings.minio_endpoint,
            ",".join(missing_buckets),
        )
        return False

    LOGGER.info(
        "中间件检查通过 name=MinIO endpoint=%s 桶=%s",
        settings.minio_endpoint,
        ",".join(dict.fromkeys(buckets)),
    )
    return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Log startup progress and critical middleware availability."""

    _configure_logging()
    config_errors = production_config_errors(settings)
    if config_errors:
        for error in config_errors:
            LOGGER.critical("生产配置校验失败：%s", error)
        raise RuntimeError(f"生产配置校验失败，共 {len(config_errors)} 项；请查看启动日志")
    LOGGER.info(
        "ChemicalOps 启动中 环境=%s 存储后端=%s API前缀=%s",
        settings.app_env,
        settings.file_storage_backend,
        settings.api_prefix,
    )
    database_ready = _check_database()
    if database_ready and not _check_schema_migrations():
        raise RuntimeError("数据库结构尚未升级到当前代码版本；请先运行 scripts/migrate_database.py upgrade")
    minio_ready = _check_minio()
    if database_ready and minio_ready:
        LOGGER.info("ChemicalOps 启动检查完成 状态=就绪")
    else:
        LOGGER.warning(
            "ChemicalOps 启动检查完成 状态=降级 数据库就绪=%s MinIO就绪=%s",
            database_ready,
            minio_ready,
        )
    scheduler_task = (
        asyncio.create_task(_business_alert_scheduler())
        if database_ready and settings.business_alerts_scheduler_enabled
        else None
    )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        shutdown_tracing()
        LOGGER.info("ChemicalOps 正在关闭")


_configure_logging()
app = FastAPI(
    title=settings.app_name,
    description="化工采购与供应商管理系统后端 API",
    version="0.1.0",
    responses=API_ERROR_RESPONSES,
    lifespan=lifespan,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
# Keep CORS outside idempotency so replay responses receive the current request's CORS headers.
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)


def custom_openapi() -> dict:
    """为每个接口补充统一的中文错误状态码说明。"""

    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    error_schema = {"$ref": "#/components/schemas/ApiError"}
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            for code, response_config in API_ERROR_RESPONSES.items():
                response = operation["responses"].setdefault(str(code), {})
                response["description"] = response_config["description"]
                response["content"] = {"application/json": {"schema": error_schema}}
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


def _error_response(status_code: int, detail: object, message: str | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    """组装统一错误响应，保留具体业务提示。"""

    return JSONResponse(
        status_code=status_code,
        content={
            "code": status_code,
            "message": message or STATUS_MESSAGES.get(status_code, "请求处理失败"),
            "detail": detail,
        },
        headers=headers,
    )


@app.exception_handler(ResourceNotFoundError)
def handle_not_found(_: Request, exc: ResourceNotFoundError) -> JSONResponse:
    """将资源不存在业务异常转换为带中文提示的 404 响应。"""

    return _error_response(404, str(exc))


@app.exception_handler(DuplicateResourceError)
def handle_duplicate(_: Request, exc: DuplicateResourceError) -> JSONResponse:
    """将业务唯一性冲突转换为带中文提示的 409 响应。"""

    return _error_response(409, str(exc))


@app.exception_handler(BusinessValidationError)
def handle_business_validation(_: Request, exc: BusinessValidationError) -> JSONResponse:
    """将业务校验异常转换为带中文提示的 400 响应。"""

    return _error_response(400, str(exc))


@app.exception_handler(AuthenticationError)
def handle_authentication(_: Request, exc: AuthenticationError) -> JSONResponse:
    """将登录失败异常转换为带中文提示的 401 响应。"""

    return _error_response(401, str(exc))


@app.exception_handler(AuthorizationError)
def handle_authorization(_: Request, exc: AuthorizationError) -> JSONResponse:
    """将业务范围授权失败转换为统一的 403 响应。"""

    return _error_response(403, str(exc))


@app.exception_handler(StarletteHTTPException)
def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    """统一处理认证、权限、路由不存在等 HTTP 异常。"""

    detail = exc.detail
    generic_details = {"not found", "method not allowed", "unsupported media type", "unauthorized", "forbidden"}
    if isinstance(detail, str) and detail.strip().lower() in generic_details:
        detail = STATUS_MESSAGES.get(exc.status_code, "请求处理失败")
    return _error_response(exc.status_code, detail, headers=exc.headers)


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """将 FastAPI 参数校验错误转换为前端可解析的中文响应。"""

    details = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "参数格式不正确"),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    return _error_response(422, details)


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """将未处理异常转换为不泄露服务细节的 500 响应。"""

    LOGGER.error(
        "未处理 API 异常 path=%s method=%s",
        request.url.path,
        request.method,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_id": request.state.request_id, "trace_id": request.state.trace_id},
    )
    return _error_response(500, "服务器暂时无法处理该请求")


@app.get("/health/live", tags=["系统"], summary="存活检查")
@app.get("/health", tags=["系统"], summary="存活检查", include_in_schema=False)
def health() -> dict[str, str]:
    """轻量存活探针，不访问外部依赖，供负载均衡器使用。"""

    environment = settings.app_env.lower()
    data_mode = "demo" if environment in {"development", "test"} else "production"
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": environment,
        "data_source": "database",
        "data_mode": data_mode,
    }


@app.get("/health/ready", tags=["系统"], summary="就绪检查")
def readiness(response: Response) -> dict[str, object]:
    """检查数据库、对象存储和关键运行配置，供发布平台决定是否接流量。"""

    database_ready = _check_database()
    schema_ready = database_ready and _check_schema_migrations()
    storage_ready = _check_minio()
    ready = database_ready and schema_ready and storage_ready
    response.status_code = 200 if ready else 503
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": "ok" if database_ready else "failed",
            "schema_migrations": "ok" if schema_ready else "failed",
            "object_storage": "ok" if storage_ready else "failed",
        },
        "metrics": {"api_requests": "GET /metrics"},
    }


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint() -> PlainTextResponse:
    """输出 Prometheus 指标及来自持久化队列表的跨进程任务快照。"""

    refresh_database_pool_metrics()
    try:
        with SessionLocal() as db:
            refresh_task_queue_metrics(db, metrics)
    except Exception:
        metrics.increment("task_queue_metrics_collection", labels={"result": "database_error"})
        LOGGER.warning("task_queue_metrics_collection_failed")
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")


app.include_router(chemicals_router, prefix=settings.api_prefix)
app.include_router(batch_router, prefix=settings.api_prefix)
app.include_router(products_router, prefix=settings.api_prefix)
app.include_router(purchase_requests_router, prefix=settings.api_prefix)
app.include_router(purchase_orders_router, prefix=settings.api_prefix)
app.include_router(deliveries_router, prefix=settings.api_prefix)
app.include_router(rfqs_router, prefix=settings.api_prefix)
app.include_router(quality_acceptances_router, prefix=settings.api_prefix)
app.include_router(inventory_router, prefix=settings.api_prefix)
app.include_router(operation_exceptions_router, prefix=settings.api_prefix)
app.include_router(notifications_router, prefix=settings.api_prefix)
app.include_router(suppliers_router, prefix=settings.api_prefix)
app.include_router(finance_router, prefix=settings.api_prefix)
app.include_router(inventory_returns_router, prefix=settings.api_prefix)
app.include_router(replenishments_router, prefix=settings.api_prefix)
app.include_router(supplier_portal_router, prefix=settings.api_prefix)
app.include_router(supplier_portal_rfqs_router, prefix=settings.api_prefix)
app.include_router(supplier_portal_collaboration_router, prefix=settings.api_prefix)
app.include_router(files_router, prefix=settings.api_prefix)
app.include_router(inventory_cost_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(ai_router, prefix=settings.api_prefix)
app.include_router(insights_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(system_router, prefix=settings.api_prefix)

if settings.otel_enabled:
    configure_tracing(app=app, engine=engine, service_name=settings.otel_service_name)
