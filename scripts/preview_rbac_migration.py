"""Read-only preview of built-in role grant changes against the configured database."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.db import SessionLocal
from app.modules.system.model import Permission, Role, RolePermission
from seed_demo_accounts import ROLE_SCOPES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, help="Optional path for a grant/revoke CSV report")
    parser.add_argument(
        "--snapshot-csv",
        type=Path,
        help="Optional path for a read-back matrix of expected and actual built-in role grants",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        present_roles = set(db.scalars(select(Role.role_code).where(Role.role_code.in_(ROLE_SCOPES))).all())
        if present_roles != set(ROLE_SCOPES):
            raise RuntimeError("开发库内置角色集合不完整：" + ", ".join(sorted(set(ROLE_SCOPES) - present_roles)))
        catalog_codes = set(db.scalars(select(Permission.permission_code)).all())
        actual_rows = db.execute(
            select(Role.role_code, Permission.permission_code)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(Role.role_code.in_(ROLE_SCOPES))
        ).all()
        actual: dict[str, set[str]] = {role: set() for role in ROLE_SCOPES}
        for role_code, permission_code in actual_rows:
            actual.setdefault(role_code, set()).add(permission_code)

        if actual["SYS_ADMIN"] != catalog_codes:
            raise RuntimeError("SYS_ADMIN 权限绑定与权限目录不一致")
        if any("dashboard.read" not in actual[role] for role in ROLE_SCOPES):
            raise RuntimeError("至少一个内置角色缺少 dashboard.read")
        if "ai.workspace.read" in actual["SUPPLIER_PORTAL"]:
            raise RuntimeError("SUPPLIER_PORTAL 被错误授予内部 AI 工作台权限")

        changes = []
        for role_code, desired in ROLE_SCOPES.items():
            for code in sorted(desired - actual.get(role_code, set())):
                changes.append((role_code, "GRANT", code))
            for code in sorted(actual.get(role_code, set()) - desired):
                changes.append((role_code, "REVOKE", code))

        if args.snapshot_csv:
            args.snapshot_csv.parent.mkdir(parents=True, exist_ok=True)
            with args.snapshot_csv.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("role_code", "permission_code", "expected", "actual", "matches"))
                for role_code, desired in ROLE_SCOPES.items():
                    granted = actual.get(role_code, set())
                    for code in sorted(catalog_codes | desired | granted):
                        expected_grant = code in desired
                        actual_grant = code in granted
                        writer.writerow((
                            role_code,
                            code,
                            "GRANT" if expected_grant else "DENY",
                            "GRANT" if actual_grant else "DENY",
                            "true" if expected_grant == actual_grant else "false",
                        ))

        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("role_code", "change", "permission_code"))
                writer.writerows(changes)

        print(f"roles={len(ROLE_SCOPES)} grant_count={sum(change == 'GRANT' for _, change, _ in changes)} revoke_count={sum(change == 'REVOKE' for _, change, _ in changes)}")
        for role_code, change, code in changes:
            print(f"{change} {role_code} {code}")
        print("verified invariants: SYS_ADMIN=all catalog permissions; all 12 roles=dashboard.read; SUPPLIER_PORTAL excludes ai.workspace.read")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
