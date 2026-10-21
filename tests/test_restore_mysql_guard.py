from pathlib import Path
import subprocess
import sys

import pytest


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


def test_restore_rejects_schema_synonym_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('DROP SCHEMA another_db;\nSELECT 1;', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_restore_rejects_ansi_quotes_database_redirect_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text("SET SESSION sql_mode='ANSI_QUOTES';\nUSE \"another_db\";\n", encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


@pytest.mark.parametrize(
    'statement',
    [
        'DROP TABLE another_db.important;',
        'RENAME TABLE chemicalops.items TO another_db.items;',
        'DROP TABLE another_db.表;',
        'DROP TABLE 123db.important;',
    ],
)
def test_restore_rejects_schema_qualified_object_references_before_mysql(tmp_path, statement):
    backup = tmp_path / 'backup.sql'
    backup.write_text(statement, encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_restore_rejects_ansi_quotes_schema_qualified_reference_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text('SET SESSION sql_mode=\'ANSI_QUOTES\';\nDROP TABLE "another_db".important;\n', encoding='utf-8')
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr


def test_restore_rejects_executable_comment_qualified_reference_before_mysql(tmp_path):
    backup = tmp_path / 'backup.sql'
    backup.write_text(
        "SET SESSION sql_mode='ANSI_QUOTES';\nDROP TABLE \"another_db\" /*!50000 . */ important;\n",
        encoding='utf-8',
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/restore_mysql.py'), str(backup), '--confirm', '--database', 'chemicalops_restore_test'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert 'error:' in result.stderr
