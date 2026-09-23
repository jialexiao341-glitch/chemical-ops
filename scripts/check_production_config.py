"""生产启动前的 fail-closed 配置检查。"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.production import production_config_errors


def main() -> int:
    settings = get_settings()
    if settings.app_env.lower() not in {"production", "prod"}:
        print(f"production_config_check=skipped app_env={settings.app_env}")
        return 0
    errors = production_config_errors(settings)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("production_config_check=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
