"""Fail-closed validation for production runtime configuration."""

from __future__ import annotations

import shlex
import shutil
from urllib.parse import urlsplit

from app.core.config import Settings


PRODUCTION_ENVIRONMENTS = {"production", "prod"}


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"password", "secret", "changeme", "change-me"} or normalized.startswith(
        ("change_me", "your_", "replace_me")
    )


def _is_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme == "https" and bool(parsed.netloc) and parsed.hostname is not None
    except ValueError:
        return False


def _scanner_executable_exists(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    executable = parts[0]
    return shutil.which(executable) is not None


def production_config_errors(settings: Settings) -> list[str]:
    """Return safe-to-display configuration errors for production only."""

    if settings.app_env.strip().lower() not in PRODUCTION_ENVIRONMENTS:
        return []

    errors: list[str] = []
    if settings.debug:
        errors.append("DEBUG 必须为 false")
    if len(settings.jwt_secret_key.strip()) < 32 or _is_placeholder(settings.jwt_secret_key):
        errors.append("JWT_SECRET_KEY 必须是至少 32 位的非占位密钥")
    if _is_placeholder(settings.mysql_password):
        errors.append("MYSQL_PASSWORD 必须配置为非占位密码")
    if not settings.mysql_host.strip() or not settings.mysql_database.strip() or not settings.mysql_user.strip():
        errors.append("MYSQL_HOST、MYSQL_DATABASE 和 MYSQL_USER 必须配置")

    storage_backend = settings.file_storage_backend.strip().lower()
    if storage_backend not in {"local", "minio", "s3"}:
        errors.append("FILE_STORAGE_BACKEND 只支持 local、minio 或 s3")
    if storage_backend in {"minio", "s3"}:
        if _is_placeholder(settings.minio_access_key) or _is_placeholder(settings.minio_secret_key):
            errors.append("MinIO/S3 必须配置非占位访问密钥")
        if not settings.minio_endpoint.strip():
            errors.append("MINIO_ENDPOINT 必须配置")
        if (
            not (settings.minio_document_bucket or settings.minio_bucket).strip()
            or not settings.minio_result_bucket.strip()
        ):
            errors.append("必须配置原始文件桶和解析结果桶")

    if not settings.redis_enabled or not settings.redis_rate_limit_enabled:
        errors.append("生产环境必须启用 REDIS_ENABLED 和 REDIS_RATE_LIMIT_ENABLED")
    if storage_backend in {"minio", "s3"} and not settings.minio_secure:
        errors.append("生产对象存储必须设置 MINIO_SECURE=true")
    if len(settings.metrics_access_token.strip()) < 32 or _is_placeholder(settings.metrics_access_token):
        errors.append("METRICS_ACCESS_TOKEN 必须是至少 32 位的非占位凭据")

    if not settings.file_scan_enabled:
        errors.append("生产环境必须启用文件病毒扫描")
    elif not _scanner_executable_exists(settings.file_scan_command):
        errors.append("FILE_SCAN_COMMAND 指定的扫描程序不存在或不可执行")

    if not settings.idempotency_required:
        errors.append("生产环境必须设置 IDEMPOTENCY_REQUIRED=true")
    if settings.agent_allow_write_tools:
        errors.append("生产环境禁止启用 AI 直接写工具")
    if settings.agent_enabled and (
        _is_placeholder(settings.openai_api_key)
        or not _is_https_url(settings.openai_base_url)
    ):
        errors.append("启用 AI 时必须配置 OPENAI_API_KEY 和 HTTPS OPENAI_BASE_URL；如不使用 AI，请设置 AGENT_ENABLED=false")
    if settings.mineru_enabled and (
        _is_placeholder(settings.mineru_api_key)
        or not _is_https_url(settings.mineru_base_url)
    ):
        errors.append("启用 MinerU 时必须配置 MINERU_API_KEY 和 HTTPS MINERU_BASE_URL")

    if settings.demo_default_password.strip():
        errors.append("生产环境不得配置 DEMO_DEFAULT_PASSWORD")
    if settings.admin_password.strip() and (
        len(settings.admin_password) < 16 or _is_placeholder(settings.admin_password)
    ):
        errors.append("ADMIN_PASSWORD 如已配置，必须至少 16 位且不能是占位值")

    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not origins:
        errors.append("CORS_ORIGINS 必须包含明确的生产前端来源")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            valid_origin = (
                origin != "*"
                and parsed.scheme == "https"
                and bool(hostname)
                and hostname.lower() not in {"localhost", "127.0.0.1", "::1"}
                and parsed.path == ""
                and not parsed.query
                and not parsed.fragment
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            valid_origin = False
        if not valid_origin:
            errors.append("CORS_ORIGINS 只能包含明确的 HTTPS 生产来源，不能使用通配符或本地地址")
            break

    return errors
