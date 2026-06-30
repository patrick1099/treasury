#!/usr/bin/env python3
"""Export and import a local Codex profile migration package."""

from __future__ import annotations

import fnmatch
import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


MANIFEST_NAME = "manifest.json"
PROFILE_PREFIX = "profile"
MANIFEST_VERSION = 2

INCLUDE_DIRS = (
    "plugins",
    "skills",
    "memories",
    "sessions",
    "attachments",
)

INCLUDE_FILES = (
    "config.toml",
    "session_index.jsonl",
    "models_cache.json",
)

# SQLite 库:只匹配主库文件(不含 -wal/-shm)。导出时用 backup API 做一致性快照,
# 自动把 WAL 合并进主库,因此不需要、也不会单独拷 -wal/-shm。
DB_PATTERNS = (
    "memories_*.sqlite",
    "state_*.sqlite",
    "goals_*.sqlite",
)

# 运行日志库,默认不迁(可达数百 MB,且是 telemetry 日志而非聊天记录)。
# 仅当 --include-logs 时才打包。
DB_PATTERNS_LOGS = (
    "logs_*.sqlite",
)

EXCLUDE_NAMES = {
    "auth.json": "login credentials are not migrated",
    ".sandbox-secrets": "sandbox secrets are machine-specific credentials",
    ".sandbox": "sandbox runtime state is machine-specific",
    ".sandbox-bin": "sandbox runtime binaries are machine-specific",
    ".tmp": "temporary data is not migrated",
    "tmp": "temporary data is not migrated",
    "cache": "cache data is rebuildable",
    "cap_sid": "session capability state is machine-specific",
    "installation_id": "installation identity is machine-specific",
}


class MigrationError(Exception):
    """Raised when a migration operation cannot continue safely."""


def export_package(profile_path, package_path, force=False, include_logs=False):
    """Export selected Codex profile content into an unencrypted zip package.

    SQLite databases are captured with the backup API so the snapshot is
    internally consistent even if Codex is running. Raw -wal/-shm files are
    never copied. Log databases are excluded unless include_logs is set.
    """
    profile = Path(profile_path)
    package = Path(package_path)
    if not profile.is_dir():
        raise MigrationError(f"source profile does not exist: {profile}")
    if package.exists() and not force:
        raise MigrationError(f"output package already exists: {package}")

    plain_files, db_files = _collect_included_files(profile, include_logs)
    excluded = _collect_excluded_paths(profile)

    snapshots = {}  # db 源文件 Path -> 临时快照 Path
    try:
        for db_path in db_files:
            snapshots[db_path] = _snapshot_sqlite(db_path)

        manifest = _build_manifest(profile, plain_files, snapshots, excluded, include_logs)

        package.parent.mkdir(parents=True, exist_ok=True)
        # strict_timestamps=False: 容忍插件缓存里 1970 时间戳的文件(钳到 1980),
        # 否则 Python 3.14 的 zipfile 会对 pre-1980 时间戳直接抛 ValueError。
        with zipfile.ZipFile(
            package, "w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False
        ) as zip_file:
            zip_file.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            )
            for file_path in plain_files:
                relative_path = file_path.relative_to(profile).as_posix()
                zip_file.write(file_path, f"{PROFILE_PREFIX}/{relative_path}")
            for db_path, snapshot in snapshots.items():
                relative_path = db_path.relative_to(profile).as_posix()
                zip_file.write(snapshot, f"{PROFILE_PREFIX}/{relative_path}")

        total_bytes = sum(p.stat().st_size for p in plain_files)
        total_bytes += sum(s.stat().st_size for s in snapshots.values())
        return {
            "package": str(package),
            "file_count": len(plain_files) + len(snapshots),
            "total_bytes": total_bytes,
            "include_logs": include_logs,
            "manifest": manifest,
        }
    finally:
        for snapshot in snapshots.values():
            snapshot.unlink(missing_ok=True)


def inspect_package(package_path):
    """Read and return a migration package manifest."""
    package = Path(package_path)
    if not package.is_file():
        raise MigrationError(f"package does not exist: {package}")

    try:
        with zipfile.ZipFile(package) as zip_file:
            if MANIFEST_NAME not in zip_file.namelist():
                raise MigrationError(f"missing {MANIFEST_NAME}")
            return json.loads(zip_file.read(MANIFEST_NAME).decode("utf-8"))
    except zipfile.BadZipFile as exc:
        raise MigrationError(f"not a valid zip package: {package}") from exc


def default_profile_path():
    """Return the current user's default Codex profile path."""
    return Path.home() / ".codex"


def import_package(package_path, profile_path, remap_user=None):
    """Restore a migration package into a Codex profile directory.

    remap_user=(old, new) rewrites the old username to the new one in restored
    session text files and in the SQLite path columns (cwd/rollout_path/...),
    so threads still resolve on a machine with a different username.
    """
    package = Path(package_path)
    target_profile = Path(profile_path)
    backup_path = None

    manifest = inspect_package(package)

    try:
        with zipfile.ZipFile(package) as zip_file:
            members = _validated_profile_members(zip_file)
            if target_profile.exists():
                backup_path = _backup_existing_profile(target_profile)
            target_profile.mkdir(parents=True, exist_ok=False)
            for member in members:
                relative_name = member.filename[len(f"{PROFILE_PREFIX}/") :]
                destination = target_profile / Path(relative_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zip_file.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
    except zipfile.BadZipFile as exc:
        raise MigrationError(f"not a valid zip package: {package}") from exc

    remap = None
    if remap_user is not None:
        old, new = remap_user
        text_files, db_updates = remap_user_in_profile(target_profile, old, new)
        remap = {"old": old, "new": new, "text_files": text_files, "db_updates": db_updates}

    return {
        "profile": str(target_profile),
        "backup_path": str(backup_path) if backup_path is not None else None,
        "restored_file_count": len(members),
        "remap": remap,
        "manifest": manifest,
    }


# 改写用户名时,只动 `Users<分隔符><用户名><分隔符>` 形态,避免误伤正文里别的同名词。
_TEXT_REMAP_DIRS = ("sessions", "memories")
_TEXT_REMAP_FILES = ("session_index.jsonl", "config.toml")


def remap_user_in_profile(profile, old, new):
    """把已恢复的 profile 里旧用户名改写成新用户名。

    文本文件(sessions/memories/jsonl/toml)按字节安全替换;SQLite 库走
    SQL UPDATE ... REPLACE(),由 SQLite 重写记录,变长字符串也不会损坏。
    返回 (改写的文本文件数, 受影响的 SQLite 行数估计)。
    """
    profile = Path(profile)
    text_files = 0

    targets = []
    for sub in _TEXT_REMAP_DIRS:
        directory = profile / sub
        if directory.is_dir():
            targets.extend(p for p in directory.rglob("*") if p.is_file())
    for name in _TEXT_REMAP_FILES:
        path = profile / name
        if path.is_file():
            targets.append(path)

    for path in targets:
        if _remap_text_file(path, old, new):
            text_files += 1

    db_updates = 0
    for db_path in profile.glob("*.sqlite"):
        db_updates += _remap_sqlite_paths(db_path, old, new)

    return text_files, db_updates


def _remap_text_file(path, old, new):
    bs = b"\\"
    ob, nb = old.encode("utf-8"), new.encode("utf-8")
    pairs = [
        (b"Users" + bs + ob + bs, b"Users" + bs + nb + bs),                      # Users\dell\
        (b"Users/" + ob + b"/", b"Users/" + nb + b"/"),                          # Users/dell/
        (b"Users" + bs + bs + ob + bs + bs, b"Users" + bs + bs + nb + bs + bs),  # JSON Users\\dell\\
    ]
    data = path.read_bytes()
    updated = data
    for find, repl in pairs:
        if find in updated:
            updated = updated.replace(find, repl)
    if updated != data:
        path.write_bytes(updated)
        return True
    return False


def _remap_sqlite_paths(db_path, old, new):
    """对一个 SQLite 库里所有文本列做 Users<sep>old<sep> -> Users<sep>new<sep> 的 SQL 替换。"""
    variants = [
        (f"Users\\{old}\\", f"Users\\{new}\\"),
        (f"Users/{old}/", f"Users/{new}/"),
    ]
    conn = sqlite3.connect(str(db_path))
    affected = 0
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name <> '_sqlx_migrations'"
            )
        ]
        for table in tables:
            text_cols = [
                row[1]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
                if _is_text_column(row[2])
            ]
            for col in text_cols:
                for find, repl in variants:
                    cursor = conn.execute(
                        f'UPDATE "{table}" SET "{col}" = REPLACE("{col}", ?, ?) '
                        f'WHERE "{col}" LIKE ?',
                        (find, repl, f"%{find}%"),
                    )
                    if cursor.rowcount and cursor.rowcount > 0:
                        affected += cursor.rowcount
        conn.commit()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise MigrationError(f"failed to remap sqlite database {db_path.name}: {exc}") from exc
    finally:
        conn.close()
    return affected


def _is_text_column(declared_type):
    declared = (declared_type or "").upper()
    if declared == "":
        return True  # SQLite 无类型亲和,按文本对待
    return any(token in declared for token in ("TEXT", "CHAR", "CLOB"))


def main(argv=None):
    """Run the command line interface."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "export":
            out = args.out
            if out is None:
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                out = Path(__file__).resolve().parent / f"codex-backup-{ts}.zip"
            summary = export_package(
                args.profile, out, force=args.force, include_logs=args.include_logs
            )
            print(
                "Exported "
                f"{summary['file_count']} files "
                f"({summary['total_bytes']} bytes) to {summary['package']}"
            )
            print(f"Log databases included: {summary['include_logs']}")
            print("WARNING: package is not encrypted.")
            return 0
        if args.command == "inspect":
            manifest = inspect_package(args.from_path)
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 0
        if args.command == "import":
            summary = import_package(
                args.from_path, args.profile, remap_user=args.remap_user
            )
            print(
                "Imported "
                f"{summary['restored_file_count']} files "
                f"to {summary['profile']}"
            )
            if summary["backup_path"]:
                print(f"Backup: {summary['backup_path']}")
            if summary["remap"]:
                r = summary["remap"]
                print(
                    f"Remap {r['old']} -> {r['new']}: "
                    f"{r['text_files']} text files, {r['db_updates']} sqlite rows"
                )
            print("Reminder: log in to Codex again on this machine.")
            return 0
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.error("missing command")
    return 2


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="codex-migrate",
        description="Export or import a local Codex profile migration package.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export a Codex profile")
    export_parser.add_argument(
        "--out",
        type=Path,
        help="output zip path (default: <tool dir>/codex-backup-<timestamp>.zip)",
    )
    export_parser.add_argument(
        "--profile",
        type=Path,
        default=default_profile_path(),
        help="source Codex profile path",
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing output zip",
    )
    export_parser.add_argument(
        "--include-logs",
        action="store_true",
        help="also pack logs_*.sqlite (large telemetry logs; off by default)",
    )

    import_parser = subparsers.add_parser("import", help="import a Codex profile")
    import_parser.add_argument(
        "--from",
        dest="from_path",
        required=True,
        type=Path,
        help="input migration zip path",
    )
    import_parser.add_argument(
        "--profile",
        type=Path,
        default=default_profile_path(),
        help="target Codex profile path",
    )
    import_parser.add_argument(
        "--force",
        action="store_true",
        help="accepted for future compatibility; existing profiles are backed up",
    )
    import_parser.add_argument(
        "--remap-user",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="rewrite OLD username to NEW in session files and sqlite path columns",
    )

    inspect_parser = subparsers.add_parser("inspect", help="print package manifest")
    inspect_parser.add_argument(
        "--from",
        dest="from_path",
        required=True,
        type=Path,
        help="input migration zip path",
    )

    return parser


def _collect_included_files(profile, include_logs):
    """Return (plain_files, db_files). Plain files are copied as-is; db files
    are snapshotted via the SQLite backup API at export time."""
    plain = []
    for directory_name in INCLUDE_DIRS:
        directory = profile / directory_name
        if directory.is_dir():
            plain.extend(path for path in directory.rglob("*") if path.is_file())
    for file_name in INCLUDE_FILES:
        file_path = profile / file_name
        if file_path.is_file():
            plain.append(file_path)
    plain = sorted(set(plain), key=lambda path: path.relative_to(profile).as_posix())

    patterns = list(DB_PATTERNS)
    if include_logs:
        patterns += list(DB_PATTERNS_LOGS)
    dbs = [
        child
        for child in profile.iterdir()
        if child.is_file() and _matches_any(child.name, patterns)
    ]
    dbs = sorted(set(dbs), key=lambda path: path.name)
    return plain, dbs


def _collect_excluded_paths(profile):
    excluded = []
    for name, reason in sorted(EXCLUDE_NAMES.items()):
        path = profile / name
        if path.exists():
            excluded.append({"path": name, "reason": reason})
    return excluded


def _matches_any(name, patterns):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _snapshot_sqlite(source):
    """用 SQLite backup API 生成一致性单文件快照(自动合并 WAL),返回临时文件 Path。"""
    handle, temp_name = tempfile.mkstemp(prefix="codexmig-", suffix=".sqlite")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        source_conn = sqlite3.connect(str(source))
        try:
            dest_conn = sqlite3.connect(str(temp_path))
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
    except sqlite3.DatabaseError as exc:
        temp_path.unlink(missing_ok=True)
        raise MigrationError(
            f"failed to snapshot sqlite database {source.name}: {exc}"
        ) from exc
    return temp_path


def _build_manifest(profile, plain_files, snapshots, excluded, include_logs):
    included_entries = []
    for file_path in plain_files:
        included_entries.append(
            {
                "path": file_path.relative_to(profile).as_posix(),
                "size": file_path.stat().st_size,
            }
        )
    for db_path, snapshot in snapshots.items():
        included_entries.append(
            {
                "path": db_path.relative_to(profile).as_posix(),
                "size": snapshot.stat().st_size,
                "sqlite_snapshot": True,
            }
        )
    included_entries.sort(key=lambda entry: entry["path"])

    return {
        "tool": "codex-migrate",
        "manifest_version": MANIFEST_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_os": platform.platform(),
        "source_profile": str(profile),
        "profile_root_name": profile.name,
        "unencrypted": True,
        "includes_logs": include_logs,
        "sqlite_consistent_snapshot": True,
        "warning": (
            "This package is not encrypted and may contain private chat history, "
            "memories, attachments, paths, and project details."
        ),
        "included": included_entries,
        "excluded": excluded,
    }


def _validated_profile_members(zip_file):
    names = zip_file.namelist()
    if MANIFEST_NAME not in names:
        raise MigrationError(f"missing {MANIFEST_NAME}")

    members = []
    for member in zip_file.infolist():
        name = member.filename
        if member.is_dir() or name == MANIFEST_NAME:
            continue
        if not name.startswith(f"{PROFILE_PREFIX}/"):
            raise MigrationError(f"unexpected package entry: {name}")
        relative_name = name[len(f"{PROFILE_PREFIX}/") :]
        if not relative_name or _is_unsafe_relative_path(relative_name):
            raise MigrationError(f"unsafe package entry: {name}")
        members.append(member)

    if not members:
        raise MigrationError("package contains no profile files")
    return members


def _is_unsafe_relative_path(path_text):
    path = Path(path_text)
    return path.is_absolute() or ".." in path.parts


def _backup_existing_profile(target_profile):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target_profile.with_name(f"{target_profile.name}.backup-{timestamp}")
    if backup_path.exists():
        raise MigrationError(f"backup path already exists: {backup_path}")
    shutil.move(str(target_profile), str(backup_path))
    return backup_path


if __name__ == "__main__":
    sys.exit(main())
