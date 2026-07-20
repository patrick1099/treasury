from pathlib import Path
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.register import install_hub_memory_skill

def test_installs_hub_memory_by_link(tmp_path):
    repo = tmp_path / "repo"; (repo / "hub" / "skills" / "hub-memory").mkdir(parents=True)
    (repo / "hub" / "skills" / "hub-memory" / "SKILL.md").write_text("---\nname: hub-memory\n---\n", encoding="utf-8")
    dev = DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "AGENTS_HOME": (tmp_path / ".agents").as_posix()}, sources={})
    install_hub_memory_skill(repo, dev, Writer())
    assert (tmp_path / ".claude" / "skills" / "hub-memory").exists()
    assert (tmp_path / ".agents" / "skills" / "hub-memory").exists()

def test_hub_memory_name_collision_zero_write(tmp_path):
    # 金库里若也有一把名为 hub-memory 的普通 shared skill → 与随包 hub-memory 撞同一链接路径，
    # 跨来源冲突预检必须在提交前拦下（零写）
    import pytest
    from hub.register import (plan_register_skills, plan_hub_memory_skill,
                              check_link_collisions, RegisterConflict)
    (tmp_path / "shared" / "skills" / "hub-memory").mkdir(parents=True)
    (tmp_path / "shared" / "skills" / "hub-memory" / "SKILL.md").write_text("# vault\n", encoding="utf-8")
    repo = tmp_path / "repo"; (repo / "hub" / "skills" / "hub-memory").mkdir(parents=True)
    (repo / "hub" / "skills" / "hub-memory" / "SKILL.md").write_text("# bundled\n", encoding="utf-8")
    dev = DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "AGENTS_HOME": (tmp_path / ".agents").as_posix()}, sources={})
    to_link, _ = plan_register_skills(tmp_path, dev)
    hm = plan_hub_memory_skill(repo, dev)
    with pytest.raises(RegisterConflict):
        check_link_collisions(to_link, hm)          # 提交前拦下，什么都没建
    assert not (tmp_path / ".claude" / "skills").exists()
