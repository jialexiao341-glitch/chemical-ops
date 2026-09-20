"""生产启动前的 fail-closed 配置检查。"""

from __future__ import annotations

import sys

from app.core.config import get_settings


def main() -> int:
    settings = get_settings()
    if settings.app_env.lower() not in {"production", "prod"}:
        print(f"production_config_check=skipped app_env={settings.app_env}")
        return 0
    errors: list[str] = []
    if settings.debug:
        errors.append("DEBUG 必须为 false")
    if len(settings.jwt_secret_key) < 32 or settings.jwt_secret_key.startswith("CHANGE_ME"):
        errors.append("JWT_SECRET_KEY 必须是至少 32 位随机密钥")
    if not settings.mysql_password:
        errors.append("MYSQL_PASSWORD 不能为空")
    if settings.file_storage_backend.strip().lower() in {"minio", "s3"} and (not settings.minio_access_key or not settings.minio_secret_key):
        errors.append("MinIO/S3 必须配置访问密钥")
    if settings.file_storage_backend.strip().lower() in {"minio", "s3"} and not settings.file_scan_enabled:
        errors.append("生产对象存储模式必须启用 ClamAV 扫描")
    if settings.agent_allow_write_tools:
        errors.append("生产环境禁止 AI 直接写工具")
    if settings.admin_password.startswith("CHANGE_ME") or settings.demo_default_password.startswith("CHANGE_ME"):
        errors.append("管理员和演示账号密码不能使用示例值")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("production_config_check=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
