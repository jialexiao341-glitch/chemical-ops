from pathlib import Path

from scripts import backup_mysql


def test_find_mysqldump_prefers_explicit_configuration(monkeypatch, tmp_path: Path):
    configured_dump = tmp_path / "custom" / "mysqldump.exe"
    configured_dump.parent.mkdir()
    configured_dump.touch()
    monkeypatch.setenv("MYSQLDUMP_PATH", str(configured_dump))
    monkeypatch.setattr(backup_mysql.shutil, "which", lambda _: "path-mysqldump")

    assert backup_mysql._find_mysqldump(windows=True) == str(configured_dump)


def test_find_mysqldump_uses_path_before_windows_install_locations(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MYSQLDUMP_PATH", raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setattr(backup_mysql.shutil, "which", lambda _: "path-mysqldump")

    assert backup_mysql._find_mysqldump(windows=True) == "path-mysqldump"


def test_find_mysqldump_discovers_standard_windows_install(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MYSQLDUMP_PATH", raising=False)
    monkeypatch.delenv("MYSQL_HOME", raising=False)
    monkeypatch.setattr(backup_mysql.shutil, "which", lambda _: None)
    program_files = tmp_path / "Program Files"
    executable = program_files / "MySQL" / "MySQL Server 8.0" / "bin" / "mysqldump.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    assert backup_mysql._find_mysqldump(windows=True) == str(executable)


def test_find_mysqldump_uses_mysql_home(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MYSQLDUMP_PATH", raising=False)
    monkeypatch.setattr(backup_mysql.shutil, "which", lambda _: None)
    executable = tmp_path / "mysql" / "bin" / "mysqldump.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("MYSQL_HOME", str(executable.parent.parent))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    assert backup_mysql._find_mysqldump(windows=True) == str(executable)
