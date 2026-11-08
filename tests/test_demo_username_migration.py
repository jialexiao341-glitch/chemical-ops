"""使用隔离的 MySQL 临时表验证真实不区分大小写排序规则。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.modules.system.audit import AuditLog
from app.modules.system.model import User
from scripts.seed_demo_accounts import LEGACY_USERNAMES
from scripts.update_demo_user_identities import migrate_usernames


@pytest.fixture
def migration_db(db_engine):
    with db_engine.connect() as connection:
        connection.exec_driver_sql("""CREATE TEMPORARY TABLE sys_users (
            id INT PRIMARY KEY AUTO_INCREMENT, username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL, display_name VARCHAR(100) NOT NULL,
            department_id INT NULL, email VARCHAR(255), phone VARCHAR(32), status VARCHAR(20) NOT NULL,
            token_version INT NOT NULL DEFAULT 0, avatar MEDIUMBLOB, last_login_at DATETIME(3),
            created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
            updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci""")
        connection.exec_driver_sql("""CREATE TEMPORARY TABLE sys_audit_logs (
            id INT PRIMARY KEY AUTO_INCREMENT, actor_id INT, action_type VARCHAR(64) NOT NULL,
            resource_type VARCHAR(64) NOT NULL, resource_id INT, request_summary TEXT,
            result_status VARCHAR(20) NOT NULL, ip_address VARCHAR(45), user_agent VARCHAR(500),
            created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3))""")
        connection.exec_driver_sql("CREATE TEMPORARY TABLE migration_test_links (user_id INT NOT NULL, kind VARCHAR(30) NOT NULL)")
        connection.commit()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.rollback()
            session.close()
            connection.exec_driver_sql("DROP TEMPORARY TABLE migration_test_links")
            connection.exec_driver_sql("DROP TEMPORARY TABLE sys_audit_logs")
            connection.exec_driver_sql("DROP TEMPORARY TABLE sys_users")
            connection.commit()


def add_user(db, username):
    user = User(username=username, password_hash="unchanged-hash", display_name="示例", department_id=42, status="ACTIVE")
    db.add(user)
    db.flush()
    return user


def config(**overrides):
    return SimpleNamespace(**{"app_env": "development", "admin_username": "SystemAdmin", **overrides})


def test_complete_mapping_is_idempotent_and_keeps_identity_and_links(migration_db):
    db = migration_db
    users = {new: add_user(db, aliases[0]) for new, aliases in LEGACY_USERNAMES.items()}
    for user in users.values():
        for kind in ("role", "warehouse", "supplier"):
            db.execute(text("INSERT INTO migration_test_links (user_id, kind) VALUES (:id, :kind)"), {"id": user.id, "kind": kind})
    extras = [add_user(db, name) for name in ("Antiboys", "Zhangsan", "Supplierportal")]
    ids = {name: user.id for name, user in users.items()}
    links_before = list(db.execute(text("SELECT user_id, kind FROM migration_test_links ORDER BY user_id, kind")))
    assert migrate_usernames(db, config()) == 12
    db.flush()
    for name, user in users.items():
        assert (user.id, user.username, user.password_hash, user.department_id) == (ids[name], name, "unchanged-hash", 42)
    assert [user.username for user in extras] == ["Antiboys", "Zhangsan", "Supplierportal"]
    assert list(db.execute(text("SELECT user_id, kind FROM migration_test_links ORDER BY user_id, kind"))) == links_before
    assert len(db.scalars(select(AuditLog)).all()) == 12
    assert migrate_usernames(db, config()) == 0
    assert len(db.scalars(select(AuditLog)).all()) == 12


def test_case_only_rename_respects_mysql_ci_collation(migration_db):
    db = migration_db
    user = add_user(db, "financeclerk")
    assert db.scalar(select(User.id).where(User.username == "FinanceClerk")) == user.id
    assert migrate_usernames(db, config(), mapping={"FinanceClerk": ("financeclerk",)}) == 1
    db.flush()
    assert user.username == "FinanceClerk"


@pytest.mark.parametrize("supplier_names", [("supplier_portal", "SupplierUser"),
    ("supplier_portal_demo", "supplier_portal"), ("supplier_portal_demo", "supplier_portal", "SupplierUser")])
def test_conflicts_stop_before_any_change(migration_db, supplier_names):
    db = migration_db
    admin = add_user(db, "system_admin")
    for name in supplier_names:
        add_user(db, name)
    with pytest.raises(RuntimeError, match="冲突"):
        migrate_usernames(db, config())
    assert admin.username == "system_admin"
    assert db.scalars(select(AuditLog)).all() == []


def test_supplier_demo_alias_is_migrated(migration_db):
    user = add_user(migration_db, "supplier_portal_demo")
    assert migrate_usernames(migration_db, config()) == 1
    assert user.username == "SupplierUser"


@pytest.mark.parametrize(("legacy", "target"), [("quality", "QualityInspector"), ("warehouse", "WarehouseUser")])
def test_additional_legacy_name_is_migrated(migration_db, legacy, target):
    user = add_user(migration_db, legacy)
    assert migrate_usernames(migration_db, config()) == 1
    assert user.username == target


@pytest.mark.parametrize("aliases", [("quality_inspector", "quality"), ("warehouse_receiver", "warehouse")])
def test_multiple_legacy_names_for_one_target_stop_all_migration(migration_db, aliases):
    admin = add_user(migration_db, "system_admin")
    for name in aliases:
        add_user(migration_db, name)
    with pytest.raises(RuntimeError, match="冲突"):
        migrate_usernames(migration_db, config())
    assert admin.username == "system_admin"
    assert migration_db.scalars(select(AuditLog)).all() == []


@pytest.mark.parametrize("settings", [config(app_env="production"), config(admin_username="system_admin")])
def test_environment_and_admin_preflight_block_any_changes(migration_db, settings):
    user = add_user(migration_db, "buyer")
    with pytest.raises(RuntimeError):
        migrate_usernames(migration_db, settings)
    assert user.username == "buyer"
    assert migration_db.scalars(select(AuditLog)).all() == []
