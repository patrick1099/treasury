import pytest
from pathlib import Path
from hub.status_report import link_status
from hub.fslink import make_dir_link
from hub.model import DeviceProfile
from hub.vaultpaths import SharedSkillsEscape

def _dev(tmp_path):
    return DeviceProfile(host="box1", classes=[], projects=[],
                         paths={"CLAUDE_HOME": str(tmp_path / ".claude"),
                                "AGENTS_HOME": str(tmp_path / ".agents")}, sources={})

def test_reports_ok_when_linked(tmp_path):
    vault = tmp_path / "vault"
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    dev = _dev(tmp_path)
    make_dir_link(s, tmp_path / ".claude" / "skills" / "alpha")
    make_dir_link(s, tmp_path / ".agents" / "skills" / "alpha")
    rows = link_status(vault, dev)
    assert ("ok", str(tmp_path / ".claude" / "skills" / "alpha")) in rows
    assert all(st == "ok" for st, _ in rows)

def test_reports_missing_when_not_linked(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills" / "alpha").mkdir(parents=True)
    rows = link_status(vault, _dev(tmp_path))
    assert ("missing", str(tmp_path / ".claude" / "skills" / "alpha")) in rows

def test_reports_conflict_when_points_elsewhere(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills" / "alpha").mkdir(parents=True)
    other = tmp_path / "other"; other.mkdir()
    make_dir_link(other, tmp_path / ".claude" / "skills" / "alpha")   # 同名但指别处
    rows = link_status(vault, _dev(tmp_path))
    assert ("conflict", str(tmp_path / ".claude" / "skills" / "alpha")) in rows

def test_status_raises_when_shared_skills_container_escapes(tmp_path):
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"; outside.mkdir()
    (vault / "shared").mkdir(parents=True)
    make_dir_link(outside, vault / "shared" / "skills")
    with pytest.raises(SharedSkillsEscape):
        link_status(vault, _dev(tmp_path))

def test_status_flags_linked_tool_container(tmp_path):
    (tmp_path / "shared" / "skills" / "alpha").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    (tmp_path / ".agents").mkdir()
    make_dir_link(elsewhere, tmp_path / ".agents" / "skills")     # 容器整个是 junction
    rows = link_status(tmp_path, _dev(tmp_path))
    assert any(state == "conflict" and ".agents" in label for state, label in rows)
    assert not any(state == "ok" and str(tmp_path / ".agents" / "skills") in label
                   for state, label in rows)

def test_local_only_skill_is_not_reported(tmp_path):
    """用户自己的本地 skill（shared 里没有）——绝不能进结果（既非 conflict 也非任何状态）。"""
    vault = tmp_path / "vault"
    (vault / "shared" / "skills").mkdir(parents=True)                 # shared 空
    mine = tmp_path / ".claude" / "skills" / "my_local"; mine.mkdir(parents=True)
    rows = link_status(vault, _dev(tmp_path))
    assert all("my_local" not in label for _, label in rows)         # 压根不出现
