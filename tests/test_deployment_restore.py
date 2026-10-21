from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_baseline_safety_stock_migration_is_repeatable():
    from sqlalchemy import create_engine
    from scripts.migrate_database import _apply_migration, _migration_files
    engine = create_engine('sqlite://')
    with engine.connect() as connection:
        connection.exec_driver_sql('CREATE TABLE md_products (status TEXT, safety_stock_quantity DECIMAL(18,6))')
        connection.exec_driver_sql('CREATE INDEX idx_product_safety_stock ON md_products (status, safety_stock_quantity)')
        migration = next(item for item in _migration_files() if item.version == '024')
        _apply_migration(connection, migration)


def test_restore_requires_explicit_isolated_target(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('SELECT 1;', encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm'], capture_output=True, text=True)
    assert result.returncode == 2
    assert '--database' in result.stderr


def test_full_stack_has_tls_and_independent_workers():
    path = ROOT / 'deploy/compose.full.yaml'
    assert path.exists(), '完整运行栈尚未提供'
    import yaml
    services = yaml.safe_load(path.read_text(encoding='utf-8'))['services']
    assert {'api', 'frontend', 'worker-agent', 'worker-documents', 'mysql', 'redis', 'qdrant', 'minio', 'proxy', 'migrate'} <= services.keys()
    assert all('ports' not in service for name, service in services.items() if name != 'proxy')
    assert '127.0.0.1:' in services['proxy']['ports'][0]
    assert any('/app/backups/mysql' in volume and 'BACKUP_DIR' in volume for volume in services['migrate']['volumes'])
    assert (ROOT / 'deploy/nginx/frontend.conf').exists()


def test_restore_rejects_database_redirect_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('/*!50000 USE `chemicalops` */;\nSELECT 1;', encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'], capture_output=True, text=True)
    assert result.returncode == 2
    assert '数据库切换' in result.stderr
