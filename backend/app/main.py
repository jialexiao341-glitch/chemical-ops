"""ChemicalOps FastAPI 应用入口。"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.idempotency import IdempotencyMiddleware
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
from app.modules.supplier_portal.controller import router as supplier_portal_router
from app.modules.files.controller import router as files_router
from app.modules.inventory_cost.controller import router as inventory_cost_router
from app.modules.jobs.controller import router as jobs_router
from app.modules.dashboard.controller import router as dashboard_router
from app.modules.ai.controller import router as ai_router
from app.modules.system.controller import auth_router, router as system_router


settings = get_settings()
LOGGER = logging.getLogger("chemicalops.api")
app = FastAPI(
    title=settings.app_name,
    description="化工采购与供应商管理系统后端 API",
    version="0.1.0",
    responses=API_ERROR_RESPONSES,
)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(IdempotencyMiddleware)


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

    LOGGER.exception("未处理 API 异常 path=%s method=%s", request.url.path, request.method)
    return _error_response(500, "服务器暂时无法处理该请求")


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict[str, str]:
    """返回服务状态及数据环境，帮助前端区分实时聚合和演示数据。"""

    environment = settings.app_env.lower()
    data_mode = "demo" if environment in {"development", "test"} else "production"
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": environment,
        "data_source": "database",
        "data_mode": data_mode,
    }


app.include_router(chemicals_router, prefix=settings.api_prefix)
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
app.include_router(files_router, prefix=settings.api_prefix)
app.include_router(inventory_cost_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(ai_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(system_router, prefix=settings.api_prefix)
