"""安全迁移开发环境演示账号登录名，不修改账号身份与授权。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.system_management.audit import add_audit_log
from app.modules.system_management.model import User
from scripts.seed_demo_accounts import LEGACY_USERNAMES


def _exact_username(name: str):
    """绕开账号字段不区分大小写的排序规则。"""
    return User.username.collate("utf8mb4_bin") == name


def migrate_usernames(db, settings, *, mapping=None) -> int:
    """先锁定并检查所有候选，确认无冲突后才修改和审计。"""
    if settings.app_env.strip().lower() not in {"development", "dev"}:
        raise RuntimeError("仅允许在 development/dev 环境迁移演示账号")
    if settings.admin_username.strip().lower() == "system_admin":
        raise RuntimeError("ADMIN_USERNAME 仍为 system_admin，请先在 .env 改为 SystemAdmin")
    mapping = LEGACY_USERNAMES if mapping is None else mapping
    plan = []
    conflicts = []
    for target, aliases in mapping.items():
        sources = [db.scalar(select(User).where(_exact_username(name)).with_for_update()) for name in aliases]
        sources = [user for user in sources if user is not None]
        exact_target = db.scalar(select(User).where(_exact_username(target)).with_for_update())
        # 使用数据库当前排序规则查询目标，识别大小写或重音等价的实际占用者。
        equivalent = list(db.scalars(select(User).where(User.username == target).with_for_update()).all())
        if len(sources) > 1:
            conflicts.append(f"{target}: 存在多个历史账号 ({', '.join(aliases)})")
        elif sources:
            source = sources[0]
            if (exact_target is not None and exact_target.id != source.id) or any(user.id != source.id for user in equivalent):
                conflicts.append(f"{source.username} → {target}: 新账号已被其他用户占用")
            elif source.username != target:
                plan.append((source, source.username, target))
        elif exact_target is None and equivalent:
            conflicts.append(f"{target}: 存在排序规则等价的其他账号")
    if conflicts:
        raise RuntimeError("演示账号迁移冲突：" + "；".join(conflicts))
    for user, old, target in plan:
        user.username = target
        add_audit_log(db, actor_id=None, action_type="RENAME_DEMO_USER", resource_type="system.users",
                      resource_id=user.id, request_summary=f"演示账号登录名迁移：{old} → {target}",
                      result_status="SUCCESS")
    db.flush()
    return len(plan)


def main():
    with SessionLocal() as db:
        count = migrate_usernames(db, get_settings())
        db.commit()
    print(f"renamed_users={count}")


if __name__ == "__main__":
    main()
