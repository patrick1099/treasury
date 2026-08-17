"""claude / codex 两个源提取器的发现测试。

全是纯发现,不落盘:用 tmp_path 造 fixture,目录里放假的 jsonl 文件,断言
Artifact 的 rel / session_id / meta / role / kind。

缺源规则(spec §6.3)单独压两道:
- 目录在但里面没有会话 → 返回 [] (合法);
- root 不存在 → 必须抛,不许返回 [] (否则 append-only 状态机会把整个源判成 source_gone)。
"""
import pytest

from hub.chats.sources import claude, codex
from hub.chats.model import COPY, TRANSCRIPT
from hub.collect.errors import MissingSourceError
from hub.guard import SecretPathError


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---- claude ----

def test_claude_rel_session_meta_role_kind(tmp_path):
    root = tmp_path / "claude"
    _write(root / "projects" / "C--Users--Me--proj" / "abc-123.jsonl")
    arts = claude.discover(root)
    assert len(arts) == 1
    a = arts[0]
    assert a.rel == "sessions/C--Users--Me--proj/abc-123.jsonl"
    assert a.session_id == "abc-123"
    assert a.meta == {"x_project_dir": "C--Users--Me--proj"}
    assert a.role == TRANSCRIPT
    assert a.kind == COPY
    assert a.src == (root / "projects" / "C--Users--Me--proj" / "abc-123.jsonl")


def test_claude_same_session_across_two_projects_not_colliding(tmp_path):
    root = tmp_path / "claude"
    _write(root / "projects" / "projA" / "sess1.jsonl")
    _write(root / "projects" / "projB" / "sess1.jsonl")
    arts = claude.discover(root)
    rels = sorted(a.rel for a in arts)
    assert rels == [
        "sessions/projA/sess1.jsonl",
        "sessions/projB/sess1.jsonl",
    ]
    assert {a.meta["x_project_dir"] for a in arts} == {"projA", "projB"}


def test_claude_session_uuid_subdir_not_treated_as_session(tmp_path):
    root = tmp_path / "claude"
    _write(root / "projects" / "proj" / "sess1.jsonl")
    _write(root / "projects" / "proj" / "sess1" / "tool-results" / "blob.jsonl")
    arts = claude.discover(root)
    assert [a.rel for a in arts] == ["sessions/proj/sess1.jsonl"]


def test_claude_empty_dir_returns_empty(tmp_path):
    root = tmp_path / "claude"
    (root / "projects").mkdir(parents=True)
    assert claude.discover(root) == []


def test_claude_root_missing_raises(tmp_path):
    with pytest.raises(MissingSourceError):
        claude.discover(tmp_path / "nope")


def test_claude_check_source_denied(tmp_path):
    with pytest.raises(SecretPathError):
        claude.discover(tmp_path / "secrets" / "claude")


# ---- codex ----

def test_codex_date_hierarchy_preserved(tmp_path):
    root = tmp_path / "codex"
    uuid = "11111111-2222-3333-4444-555555555555"
    f = _write(
        root / "sessions" / "2025" / "05" / "01" / f"rollout-20250501T030405-{uuid}.jsonl"
    )
    arts = codex.discover(root)
    assert len(arts) == 1
    a = arts[0]
    assert a.rel == f"sessions/2025/05/01/rollout-20250501T030405-{uuid}.jsonl"
    assert a.session_id == uuid
    assert a.role == TRANSCRIPT
    assert a.kind == COPY
    assert a.src == f


def test_codex_archived_lands_in_sessions_archived(tmp_path):
    root = tmp_path / "codex"
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    name = f"rollout-20240101T000000-{uuid}.jsonl"
    _write(root / "archived_sessions" / name)
    arts = codex.discover(root)
    assert arts[0].rel == f"sessions/archived/{name}"
    assert arts[0].session_id == uuid


def test_codex_uuid_not_extractable_falls_back_to_stem(tmp_path):
    root = tmp_path / "codex"
    _write(root / "sessions" / "2025" / "01" / "02" / "rollout-20250102T000000-no-uuid-here.jsonl")
    arts = codex.discover(root)
    assert arts[0].session_id == "rollout-20250102T000000-no-uuid-here"


def test_codex_sessions_and_archived_both(tmp_path):
    root = tmp_path / "codex"
    _write(root / "sessions" / "2025" / "06" / "07" / "rollout-20250607T000000-11111111-2222-3333-4444-555555555555.jsonl")
    _write(root / "archived_sessions" / "rollout-20250608T000000-66666666-7777-8888-9999-000000000000.jsonl")
    arts = codex.discover(root)
    rels = sorted(a.rel for a in arts)
    assert len(rels) == 2
    assert rels[0] == "sessions/2025/06/07/rollout-20250607T000000-11111111-2222-3333-4444-555555555555.jsonl"
    assert rels[1] == "sessions/archived/rollout-20250608T000000-66666666-7777-8888-9999-000000000000.jsonl"


def test_codex_empty_dir_returns_empty(tmp_path):
    root = tmp_path / "codex"
    (root / "sessions").mkdir(parents=True)
    assert codex.discover(root) == []


def test_codex_root_missing_raises(tmp_path):
    with pytest.raises(MissingSourceError):
        codex.discover(tmp_path / "nope")


def test_codex_check_source_denied(tmp_path):
    with pytest.raises(SecretPathError):
        codex.discover(tmp_path / "secrets" / "codex")