import os
import pytest
from pathlib import Path
from hub.register import register_skills, skill_targets, RegisterConflict
from hub.model import DeviceProfile
from hub.fslink import make_dir_link
from hub.writer import Writer

def _dev(tmp_path) -> DeviceProfile:
    return DeviceProfile(
        host="box1", classes=["work"], projects=[],
        paths={"CLAUDE_HOME": str(tmp_path / "home" / ".claude"),
               "AGENTS_HOME": str(tmp_path / "home" / ".agents")},
        sources={})

def _shared_skill(vault: Path, name: str) -> Path:
    d = vault / "shared" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return d

def test_register_links_each_skill_into_each_target(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    done = register_skills(vault, dev, Writer())
    claude = tmp_path / "home" / ".claude" / "skills" / "alpha"
    agents = tmp_path / "home" / ".agents" / "skills" / "alpha"
    assert (claude / "SKILL.md").read_text(encoding="utf-8") == "# alpha\n"   # 经链接可读
    assert (agents / "SKILL.md").read_text(encoding="utf-8") == "# alpha\n"
    assert len(done) == 2

def test_register_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    first = register_skills(vault, dev, Writer())
    second = register_skills(vault, dev, Writer())        # 重跑不炸、数目稳定
    assert len(first) == len(second) == 2
    assert (tmp_path / "home" / ".claude" / "skills" / "alpha" / "SKILL.md").exists()

def test_register_empty_shared_does_nothing(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills").mkdir(parents=True)
    assert register_skills(vault, _dev(tmp_path), Writer()) == []

def test_register_conflict_nonempty_user_dir_is_untouched(tmp_path):
    """用户自己的同名 skill（非空真目录）——register 报冲突，一个字节不动。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    mine = tmp_path / "home" / ".claude" / "skills" / "alpha"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("# 我自己的 alpha\n", encoding="utf-8")
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "# 我自己的 alpha\n"

def test_register_conflict_empty_user_dir_not_deleted(tmp_path):
    """用户自己的同名空目录——register 报冲突，**不能**把它删掉。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    mine = tmp_path / "home" / ".claude" / "skills" / "alpha"
    mine.mkdir(parents=True)                       # 空目录：os.rmdir 本会成功——绝不许删
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())
    assert mine.is_dir()                            # 还在

def test_register_conflict_link_pointing_elsewhere(tmp_path):
    """同名位置是指向别处的链接——冲突，不覆盖。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    other = tmp_path / "somewhere_else"; other.mkdir()
    make_dir_link(other, tmp_path / "home" / ".claude" / "skills" / "alpha")
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())

def test_skill_targets_skips_missing_home(tmp_path):
    dev = DeviceProfile(host="box1", classes=[], projects=[],
                        paths={"CLAUDE_HOME": str(tmp_path / "c")}, sources={})
    targets = skill_targets(dev)
    assert (tmp_path / "c" / "skills") in targets
