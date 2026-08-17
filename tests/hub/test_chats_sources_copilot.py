"""copilot-cli / copilot-vscode 两个源提取器的发现测试。

全是纯发现,不落盘:用 tmp_path 造 fixture,断言 rel / session_id / role / kind / src。

copilot-cli 的跳过信息表达:discover 契约是 `list[Artifact]`,跳过信息塞不进去,
走同模块的 `skipped(root) -> list[(uuid, reason)]`,与 discover 共用同一个扫描器
(见 copilot_cli.py 的 docstring)。测试里两个入口都压。
"""
import tomllib

import pytest

from hub.chats.sources import copilot_cli, copilot_vscode
from hub.chats.model import COPY, GENERATED, TRANSCRIPT, AUXILIARY
from hub.collect.errors import MissingSourceError
from hub.guard import SecretPathError


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---- copilot-cli ----

def test_cli_events_collected_transcript(tmp_path):
    root = tmp_path / "copilot"
    uuid = "11111111-2222-3333-4444-555555555555"
    ev = _write(root / "session-state" / uuid / "events.jsonl", "line1\n")
    arts = copilot_cli.discover(root)
    assert len(arts) == 1
    a = arts[0]
    assert a.rel == f"sessions/{uuid}/events.jsonl"
    assert a.session_id == uuid
    assert a.kind == COPY
    assert a.role == TRANSCRIPT
    assert a.src == ev


def test_cli_workspace_yaml_auxiliary(tmp_path):
    root = tmp_path / "copilot"
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    _write(root / "session-state" / uuid / "events.jsonl")
    _write(root / "session-state" / uuid / "workspace.yaml", "root: /x\nbranch: main\n")
    arts = copilot_cli.discover(root)
    by_rel = {a.rel: a for a in arts}
    assert set(by_rel) == {
        f"sessions/{uuid}/events.jsonl",
        f"sessions/{uuid}/workspace.yaml",
    }
    assert by_rel[f"sessions/{uuid}/events.jsonl"].role == TRANSCRIPT
    assert by_rel[f"sessions/{uuid}/workspace.yaml"].kind == COPY
    assert by_rel[f"sessions/{uuid}/workspace.yaml"].role == AUXILIARY


def test_cli_session_without_events_skipped_and_reason_findable(tmp_path):
    root = tmp_path / "copilot"
    uuid_ok = "11111111-2222-3333-4444-555555555555"
    uuid_missing = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    _write(root / "session-state" / uuid_ok / "events.jsonl")
    _write(root / "session-state" / uuid_missing / "workspace.yaml")
    arts = copilot_cli.discover(root)
    assert [a.rel for a in arts] == [f"sessions/{uuid_ok}/events.jsonl"]
    skips = copilot_cli.skipped(root)
    assert (uuid_missing, "会话目录没有 events.jsonl") in skips
    assert uuid_ok not in [s[0] for s in skips]


def test_cli_lock_db_subdirs_not_collected(tmp_path):
    root = tmp_path / "copilot"
    uuid = "11111111-2222-3333-4444-555555555555"
    s = root / "session-state" / uuid
    _write(s / "events.jsonl")
    _write(s / "inuse.foo.lock")
    _write(s / "session.db")
    _write(s / "checkpoints" / "x.bin")
    _write(s / "files" / "y.txt")
    _write(s / "research" / "z.md")
    _write(s / "rewind-file-snapshots" / "w.md")
    arts = copilot_cli.discover(root)
    assert [a.rel for a in arts] == [f"sessions/{uuid}/events.jsonl"]


def test_cli_empty_state_dir_returns_empty(tmp_path):
    root = tmp_path / "copilot"
    (root / "session-state").mkdir(parents=True)
    assert copilot_cli.discover(root) == []
    assert copilot_cli.skipped(root) == []


def test_cli_root_missing_raises(tmp_path):
    with pytest.raises(MissingSourceError):
        copilot_cli.discover(tmp_path / "nope")


def test_cli_check_source_denied(tmp_path):
    with pytest.raises(SecretPathError):
        copilot_cli.discover(tmp_path / "secrets" / "copilot")


# ---- copilot-vscode ----

def _vscode(root, hashname, sessions, workspace_json=None):
    base = root / "workspaceStorage" / hashname
    for name in sessions:
        _write(base / "chatSessions" / name)
    if workspace_json is not None:
        _write(base / "workspace.json", workspace_json)
    return base


def test_vscode_chatsessions_rel_role_kind(tmp_path):
    root = tmp_path / "user"
    h = "abcdef1234567890"
    _vscode(root, h, ["sess1.jsonl", "sess2.jsonl"])
    arts = copilot_vscode.discover(root)
    chats = [a for a in arts if a.role == TRANSCRIPT]
    assert len(chats) == 2
    rels = sorted(a.rel for a in chats)
    assert rels == [f"sessions/{h}/sess1.jsonl", f"sessions/{h}/sess2.jsonl"]
    for a in chats:
        assert a.kind == COPY
        assert a.role == TRANSCRIPT
        assert a.src.name == a.rel.split("/")[-1]


def test_vscode_folder_key(tmp_path):
    root = tmp_path / "user"
    h = "hashAAA"
    _vscode(root, h, ["s.jsonl"], '{"folder": "file:///c%3A/Users/me/proj"}')
    toml = _workspaces_toml(root)
    data = tomllib.loads(toml.payload.decode("utf-8"))
    assert data["workspaces"][h] == "file:///c%3A/Users/me/proj"


def test_vscode_workspace_key(tmp_path):
    root = tmp_path / "user"
    h = "hashBBB"
    _vscode(root, h, ["s.jsonl"], '{"workspace": "file:///c%3A/Users/me/multi"}')
    toml = _workspaces_toml(root)
    data = tomllib.loads(toml.payload.decode("utf-8"))
    assert data["workspaces"][h] == "file:///c%3A/Users/me/multi"


def test_vscode_folder_takes_precedence_when_both(tmp_path):
    root = tmp_path / "user"
    h = "hashAB"
    _vscode(root, h, ["s.jsonl"],
            '{"workspace": "w", "folder": "f"}')
    toml = _workspaces_toml(root)
    data = tomllib.loads(toml.payload.decode("utf-8"))
    assert data["workspaces"][h] == "f"


def test_vscode_neither_key_blank_not_raise(tmp_path):
    root = tmp_path / "user"
    h = "hashCCC"
    _vscode(root, h, ["s.jsonl"], '{"monitor": 1}')
    toml = _workspaces_toml(root)
    data = tomllib.loads(toml.payload.decode("utf-8"))
    assert data["workspaces"][h] == ""


def test_vscode_workspaces_toml_deterministic_and_auxiliary(tmp_path):
    root = tmp_path / "user"
    _vscode(root, "hashAZ", ["s.jsonl"], '{"folder": "z"}')
    _vscode(root, "hashAA", ["t.jsonl"], '{"workspace": "a"}')
    first = copilot_vscode.discover(root)
    second = copilot_vscode.discover(root)
    t1 = next(a for a in first if a.rel == "workspaces.toml")
    t2 = next(a for a in second if a.rel == "workspaces.toml")
    assert t1.payload == t2.payload
    assert t1.kind == GENERATED
    assert t1.role == AUXILIARY
    data = tomllib.loads(t1.payload.decode("utf-8"))
    assert data["workspaces"] == {"hashAZ": "z", "hashAA": "a"}


def test_vscode_only_chatsessions_workspaces_in_table(tmp_path):
    root = tmp_path / "user"
    _vscode(root, "hashWithChat", ["s.jsonl"], '{"folder": "x"}')
    _vscode(root, "hashNoChat", [], '{"folder": "y"}')
    arts = copilot_vscode.discover(root)
    toml = _workspaces_toml(root)
    data = tomllib.loads(toml.payload.decode("utf-8"))
    assert list(data["workspaces"]) == ["hashWithChat"]
    chats = [a for a in arts if a.role == TRANSCRIPT]
    assert [a.rel for a in chats] == ["sessions/hashWithChat/s.jsonl"]


def test_vscode_root_missing_raises(tmp_path):
    with pytest.raises(MissingSourceError):
        copilot_vscode.discover(tmp_path / "nope")


def test_vscode_check_source_denied(tmp_path):
    with pytest.raises(SecretPathError):
        copilot_vscode.discover(tmp_path / "secrets" / "user")


def _workspaces_toml(root):
    arts = copilot_vscode.discover(root)
    return next(a for a in arts if a.rel == "workspaces.toml")