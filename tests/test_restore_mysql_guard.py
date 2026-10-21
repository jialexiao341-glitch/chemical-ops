from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_restore_rejects_multiline_database_ddl_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('DROP\nDATABASE another_db;\nSELECT 1;', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_restore_rejects_comment_separated_database_ddl_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('DROP/**/DATABASE another_db;\nSELECT 1;', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_restore_rejects_database_ddl_in_executable_comment_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('DROP /*!50000 DATABASE another_db */;\nSELECT 1;', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr
