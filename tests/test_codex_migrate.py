import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest


TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

import codex_migrate  # noqa: E402


def write_file(path, content="data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_wal_sqlite(path, rows):
    """Create a real WAL-mode SQLite db with leftover -wal/-shm side files,
    mirroring a live Codex database."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO items(v) VALUES (?)", [(f"row-{i}",) for i in range(rows)])
    conn.commit()
    # 故意不 checkpoint,留下 -wal/-shm,模拟实时库
    conn.close()


def build_fake_profile(profile):
    write_file(profile / "plugins" / "demo" / ".codex-plugin" / "plugin.json", "{}")
    write_file(profile / "skills" / "demo" / "SKILL.md", "# Demo\n")
    write_file(profile / "memories" / "note.md", "remember this")
    write_file(profile / "sessions" / "2026" / "session.jsonl", "{}\n")
    write_file(profile / "attachments" / "image.txt", "attachment")
    write_file(profile / "config.toml", "model = \"test\"\n")
    write_file(profile / "session_index.jsonl", "{\"id\":\"s1\"}\n")
    write_file(profile / "models_cache.json", "{}")
    write_wal_sqlite(profile / "state_5.sqlite", rows=50)
    write_wal_sqlite(profile / "memories_1.sqlite", rows=5)
    write_wal_sqlite(profile / "goals_1.sqlite", rows=1)
    write_wal_sqlite(profile / "logs_2.sqlite", rows=200)
    write_file(profile / "auth.json", "{\"token\":\"secret\"}")
    write_file(profile / ".sandbox-secrets" / "secret.txt", "secret")
    write_file(profile / "cache" / "cache.bin", "cache")
    write_file(profile / ".tmp" / "temp.txt", "temp")
    write_file(profile / "cap_sid", "sid")
    write_file(profile / "installation_id", "install")


def zip_names(package_path):
    with zipfile.ZipFile(package_path) as package:
        return set(package.namelist())


def test_export_includes_chat_history_state_and_manifest(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)

    summary = codex_migrate.export_package(profile, package_path)

    assert summary["file_count"] > 0
    names = zip_names(package_path)
    assert "manifest.json" in names
    assert "profile/sessions/2026/session.jsonl" in names
    assert "profile/attachments/image.txt" in names
    assert "profile/session_index.jsonl" in names
    assert "profile/state_5.sqlite" in names
    assert "profile/memories_1.sqlite" in names
    assert "profile/goals_1.sqlite" in names


def test_export_excludes_logs_by_default_but_includes_with_flag(tmp_path):
    profile = tmp_path / ".codex"
    build_fake_profile(profile)

    default_pkg = tmp_path / "default.zip"
    codex_migrate.export_package(profile, default_pkg)
    assert "profile/logs_2.sqlite" not in zip_names(default_pkg)

    logs_pkg = tmp_path / "with-logs.zip"
    codex_migrate.export_package(profile, logs_pkg, include_logs=True)
    assert "profile/logs_2.sqlite" in zip_names(logs_pkg)


def test_export_never_copies_raw_wal_or_shm(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)

    codex_migrate.export_package(profile, package_path, include_logs=True)

    names = zip_names(package_path)
    assert not any(n.endswith("-wal") or n.endswith("-shm") for n in names)


def test_exported_sqlite_snapshot_is_valid_and_consistent(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)
    codex_migrate.export_package(profile, package_path)

    restored = tmp_path / "restored.sqlite"
    with zipfile.ZipFile(package_path) as package:
        restored.write_bytes(package.read("profile/state_5.sqlite"))

    conn = sqlite3.connect(str(restored))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 50
    finally:
        conn.close()


def test_export_excludes_credentials_secrets_and_caches(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)

    codex_migrate.export_package(profile, package_path)

    names = zip_names(package_path)
    assert "profile/auth.json" not in names
    assert "profile/.sandbox-secrets/secret.txt" not in names
    assert "profile/cache/cache.bin" not in names
    assert "profile/.tmp/temp.txt" not in names
    assert "profile/cap_sid" not in names
    assert "profile/installation_id" not in names


def test_inspect_package_reads_manifest(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)
    codex_migrate.export_package(profile, package_path)

    manifest = codex_migrate.inspect_package(package_path)

    assert manifest["tool"] == "codex-migrate"
    assert manifest["manifest_version"] == 2
    assert manifest["unencrypted"] is True
    assert manifest["sqlite_consistent_snapshot"] is True
    assert manifest["includes_logs"] is False
    included_paths = {entry["path"] for entry in manifest["included"]}
    excluded_paths = {entry["path"] for entry in manifest["excluded"]}
    assert "sessions/2026/session.jsonl" in included_paths
    assert "auth.json" in excluded_paths


def test_manifest_in_zip_is_json(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)

    codex_migrate.export_package(profile, package_path)

    with zipfile.ZipFile(package_path) as package:
        manifest = json.loads(package.read("manifest.json").decode("utf-8"))
    assert manifest["profile_root_name"] == ".codex"


def test_import_restores_profile_and_backs_up_existing_target(tmp_path):
    source_profile = tmp_path / "source" / ".codex"
    target_profile = tmp_path / "target" / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(source_profile)
    write_file(target_profile / "sessions" / "old.jsonl", "old")
    write_file(target_profile / "auth.json", "{\"token\":\"old-secret\"}")
    codex_migrate.export_package(source_profile, package_path)

    summary = codex_migrate.import_package(package_path, target_profile)

    assert summary["restored_file_count"] > 0
    backup_path = Path(summary["backup_path"])
    assert backup_path.is_dir()
    assert (backup_path / "sessions" / "old.jsonl").read_text(encoding="utf-8") == "old"
    assert (backup_path / "auth.json").is_file()
    assert (target_profile / "sessions" / "2026" / "session.jsonl").is_file()
    assert (target_profile / "attachments" / "image.txt").is_file()
    assert (target_profile / "state_5.sqlite").is_file()
    assert not (target_profile / "auth.json").exists()


def test_import_restores_into_new_target_without_backup(tmp_path):
    source_profile = tmp_path / "source" / ".codex"
    target_profile = tmp_path / "target" / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(source_profile)
    codex_migrate.export_package(source_profile, package_path)

    summary = codex_migrate.import_package(package_path, target_profile)

    assert summary["backup_path"] is None
    assert (target_profile / "config.toml").read_text(encoding="utf-8") == "model = \"test\"\n"
    assert (target_profile / "sessions" / "2026" / "session.jsonl").is_file()


def test_import_remaps_username_in_sessions_and_sqlite(tmp_path):
    source_profile = tmp_path / "source" / ".codex"
    target_profile = tmp_path / "target" / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(source_profile)

    # 会话 jsonl 里塞两种形态的绝对路径
    write_file(
        source_profile / "sessions" / "2026" / "s.jsonl",
        json.dumps({"cwd": "C:\\Users\\dell\\proj", "p": "/Users/dell/x"}) + "\n",
    )
    # state 库的 threads 表带真实路径列
    conn = sqlite3.connect(str(source_profile / "state_5.sqlite"))
    conn.execute("CREATE TABLE threads(id TEXT, rollout_path TEXT, cwd TEXT)")
    conn.execute(
        "INSERT INTO threads VALUES(?,?,?)",
        ("t1", "C:\\Users\\dell\\.codex\\sessions\\s.jsonl", "C:\\Users\\dell\\proj"),
    )
    conn.commit()
    conn.close()

    codex_migrate.export_package(source_profile, package_path)
    summary = codex_migrate.import_package(package_path, target_profile, remap_user=("dell", "alice"))

    assert summary["remap"]["text_files"] >= 1
    assert summary["remap"]["db_updates"] >= 1

    text = (target_profile / "sessions" / "2026" / "s.jsonl").read_text(encoding="utf-8")
    assert "dell" not in text
    assert "Users\\\\alice\\\\proj" in text or "Users\\alice\\proj" in text
    assert "/Users/alice/x" in text

    conn = sqlite3.connect(str(target_profile / "state_5.sqlite"))
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rollout, cwd = conn.execute("SELECT rollout_path, cwd FROM threads").fetchone()
        assert rollout == "C:\\Users\\alice\\.codex\\sessions\\s.jsonl"
        assert cwd == "C:\\Users\\alice\\proj"
    finally:
        conn.close()


def test_import_rejects_invalid_package(tmp_path):
    package_path = tmp_path / "not-a-package.zip"
    package_path.write_text("not zip", encoding="utf-8")

    with pytest.raises(codex_migrate.MigrationError, match="valid zip"):
        codex_migrate.import_package(package_path, tmp_path / ".codex")


def test_export_rejects_existing_package_without_force(tmp_path):
    profile = tmp_path / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(profile)
    package_path.write_text("existing", encoding="utf-8")

    with pytest.raises(codex_migrate.MigrationError, match="already exists"):
        codex_migrate.export_package(profile, package_path)


def test_inspect_rejects_zip_without_manifest(tmp_path):
    package_path = tmp_path / "missing-manifest.zip"
    with zipfile.ZipFile(package_path, "w") as package:
        package.writestr("profile/config.toml", "model = \"test\"\n")

    with pytest.raises(codex_migrate.MigrationError, match="manifest"):
        codex_migrate.inspect_package(package_path)


def test_main_dispatches_export_inspect_and_import(tmp_path, capsys):
    source_profile = tmp_path / "source" / ".codex"
    target_profile = tmp_path / "target" / ".codex"
    package_path = tmp_path / "codex-profile.zip"
    build_fake_profile(source_profile)

    export_status = codex_migrate.main(
        ["export", "--profile", str(source_profile), "--out", str(package_path)]
    )
    inspect_status = codex_migrate.main(["inspect", "--from", str(package_path)])
    import_status = codex_migrate.main(
        ["import", "--profile", str(target_profile), "--from", str(package_path)]
    )

    output = capsys.readouterr().out
    assert export_status == 0
    assert inspect_status == 0
    assert import_status == 0
    assert "Exported" in output
    assert "codex-migrate" in output
    assert "Imported" in output
    assert (target_profile / "sessions" / "2026" / "session.jsonl").is_file()


def test_main_returns_nonzero_for_migration_error(tmp_path, capsys):
    package_path = tmp_path / "missing.zip"

    status = codex_migrate.main(["inspect", "--from", str(package_path)])

    output = capsys.readouterr().err
    assert status == 1
    assert "ERROR:" in output
