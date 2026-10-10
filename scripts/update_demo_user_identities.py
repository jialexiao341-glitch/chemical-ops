"""更新开发演示账号示例姓名，并停用非门户角色的历史供应商绑定。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.system import crud
from app.modules.system.model import User
from app.modules.system.audit import add_audit_log
from app.modules.supplier_portal.model import SupplierPortalAccount
from seed_demo_accounts import USERS


def main():
    if get_settings().app_env.lower() not in {"development", "dev"}:
        raise RuntimeError("仅允许更新开发环境演示账号")
    names_changed = bindings_disabled = 0
    with SessionLocal() as db:
        legacy = db.scalar(select(User).where(User.username == "supplier_portal_demo").with_for_update())
        if legacy is not None:
            if db.scalar(select(User.id).where(User.username == "supplier_portal")) is not None:
                raise RuntimeError("supplier_portal 已存在，不能自动合并账号")
            legacy.username = "supplier_portal"
            add_audit_log(db, actor_id=None, action_type="RENAME_DEMO_USER", resource_type="system.users",
                          resource_id=legacy.id, request_summary="供应商门户登录名去除 demo 后缀", result_status="SUCCESS")
            db.flush()
        for username, name, *_ in USERS:
            user = db.scalar(select(User).where(User.username == username).with_for_update())
            if user is not None and user.display_name != name:
                user.display_name = name
                names_changed += 1
                add_audit_log(db, actor_id=None, action_type="UPDATE_DEMO_NAME", resource_type="system.users",
                              resource_id=user.id, request_summary="演示账号改用独立示例姓名", result_status="SUCCESS")
        for account in db.scalars(select(SupplierPortalAccount).where(SupplierPortalAccount.status == "ACTIVE").with_for_update()):
            if set(crud.get_user_role_codes(db, account.user_id)) != {"SUPPLIER_PORTAL"}:
                account.status = "INACTIVE"
                bindings_disabled += 1
                add_audit_log(db, actor_id=None, action_type="DISABLE_SUPPLIER_BINDING", resource_type="system.users",
                              resource_id=account.user_id, request_summary="非供应商门户角色，停用历史绑定", result_status="SUCCESS")
        db.commit()
    print(f"names_changed={names_changed}; invalid_bindings_disabled={bindings_disabled}")


if __name__ == "__main__":
    main()
