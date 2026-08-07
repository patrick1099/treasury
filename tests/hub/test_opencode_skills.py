import json
import os
import pytest
from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.fslink import make_dir_link
from hub.register import RegisterConflict
from hub.opencode_skills import (opencode_skill_dir, collect_opencode_sources,
                                 plan_link_opencode_skills, commit_link_opencode_skills,
                                 opencode_skill_status, stale_skills_paths_hint)

def _dev(tmp_path, *, enabled=("p1",), opencode=True) -> DeviceProfile:
    paths = {"CLAUDE_HOME": str(tmp_path / "home" / ".claude"),
             "AGENTS_HOME": str(tmp_path / "home" / ".agents")}
    if opencode:
        paths["OPENCODE_CONFIG"] = str(tmp_path / "home" / ".config" / "opencode" / "opencode.json")
    return DeviceProfile(host="box1", classes=["work"], projects=[], paths=paths,
                         sources={}, plugins={"opencode": list(enabled)})

def _oc_skill_dir(tmp_path) -> Path:
    return tmp_path / "home" / ".config" / "opencode" / "skill"

def _shared_skill(vault: Path, name: str) -> Path:
    d = vault / "shared" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return d

def _plugin_skill(vault: Path, plugin: str, name: str, *, with_md=True) -> Path:
    d = vault / "shared" / "plugins" / plugin / "skills" / name
    d.mkdir(parents=True)
    if with_md:
        (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return d

def _manifest(vault: Path, body: dict[str, list[str]]) -> None:
    p = vault / "shared" / "plugins" / "manifest.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"[{n}]\nplatforms = {json.dumps(pl)}\n\n" for n, pl in body.items())
    p.write_text(text, encoding="utf-8")

def _do(vault, dev, w=None):
    w = w or Writer()
    to_link, ensured = plan_link_opencode_skills(vault, dev)
    commit_link_opencode_skills(to_link, w)
    return ensured, w

# ── 落点 ───────────────────────────────────────────────────────────────
def test_skill_dir_derived_from_opencode_config_parent(tmp_path):
    assert opencode_skill_dir(_dev(tmp_path)) == _oc_skill_dir(tmp_path)

def test_opencode_home_wins_over_config(tmp_path):
    dev = _dev(tmp_path)
    dev.paths["OPENCODE_HOME"] = str(tmp_path / "elsewhere")
    assert opencode_skill_dir(dev) == tmp_path / "elsewhere" / "skill"

def test_device_without_opencode_is_a_noop(tmp_path):
    """既没 OPENCODE_HOME 也没 OPENCODE_CONFIG：本机没装 opencode，不是错误，也绝不
    因为默认路径恰好存在就往里写。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path, opencode=False)
    assert opencode_skill_dir(dev) is None
    ensured, w = _do(vault, dev)
    assert ensured == [] and w.written == []
    assert not _oc_skill_dir(tmp_path).exists()

# ── 建链 ───────────────────────────────────────────────────────────────
def test_links_standalone_and_plugin_skills(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    _plugin_skill(vault, "p1", "beta")
    _manifest(vault, {"p1": ["claude", "codex", "opencode"]})
    ensured, _ = _do(vault, _dev(tmp_path))
    root = _oc_skill_dir(tmp_path)
    assert (root / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "# alpha\n"
    assert (root / "beta" / "SKILL.md").read_text(encoding="utf-8") == "# beta\n"
    assert len(ensured) == 2

def test_edit_through_link_is_live(tmp_path):
    """零拷贝的立身之本：改金库那一份，链接这边立刻是新的。"""
    vault = tmp_path / "vault"
    src = _shared_skill(vault, "alpha")
    _do(vault, _dev(tmp_path))
    (src / "SKILL.md").write_text("# 改过了\n", encoding="utf-8")
    assert (_oc_skill_dir(tmp_path) / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "# 改过了\n"

def test_plugin_not_declaring_opencode_is_skipped(tmp_path):
    vault = tmp_path / "vault"
    _plugin_skill(vault, "p1", "beta")
    _manifest(vault, {"p1": ["claude", "codex"]})          # 清单没声明 opencode
    ensured, w = _do(vault, _dev(tmp_path))
    assert ensured == [] and w.written == []

def test_plugin_not_enabled_on_this_device_is_skipped(tmp_path):
    vault = tmp_path / "vault"
    _plugin_skill(vault, "p1", "beta")
    _manifest(vault, {"p1": ["opencode"]})
    ensured, w = _do(vault, _dev(tmp_path, enabled=()))     # 本机没 enable
    assert ensured == [] and w.written == []

def test_skill_dir_without_skill_md_is_skipped(tmp_path):
    """opencode 自己也不认没有 SKILL.md 的目录，别链过去添乱。"""
    vault = tmp_path / "vault"
    _plugin_skill(vault, "p1", "beta", with_md=False)
    _plugin_skill(vault, "p1", "gamma")
    _manifest(vault, {"p1": ["opencode"]})
    ensured, _ = _do(vault, _dev(tmp_path))
    assert [Path(e).name for e in ensured] == ["gamma"]

def test_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    first, _ = _do(vault, dev)
    second, w2 = _do(vault, dev)
    assert len(first) == len(second) == 1
    assert w2.written == []                                 # 第二遍零写入

def test_creates_absent_container_as_real_dir(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    _do(vault, _dev(tmp_path))
    root = _oc_skill_dir(tmp_path)
    assert (root / "alpha").exists()
    assert not root.is_symlink()

# ── 冲突：一律零写入，绝不覆盖 ─────────────────────────────────────────
def test_conflict_user_dir_is_untouched_and_nothing_written(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    _shared_skill(vault, "zeta")                            # 本可建的另一个
    mine = _oc_skill_dir(tmp_path) / "alpha"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("# 我自己的\n", encoding="utf-8")
    w = Writer()
    with pytest.raises(RegisterConflict, match="alpha"):
        _do(vault, _dev(tmp_path), w)
    assert w.written == []
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "# 我自己的\n"
    assert not os.path.lexists(_oc_skill_dir(tmp_path) / "zeta")   # 另一个也没建

def test_conflict_link_pointing_elsewhere(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    other = tmp_path / "somewhere_else"; other.mkdir()
    make_dir_link(other, _oc_skill_dir(tmp_path) / "alpha")
    with pytest.raises(RegisterConflict, match="alpha"):
        _do(vault, _dev(tmp_path))

def test_conflict_when_container_is_a_link(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    root = _oc_skill_dir(tmp_path)
    root.parent.mkdir(parents=True)
    make_dir_link(elsewhere, root)                          # 整个 skill/ 是链接
    w = Writer()
    with pytest.raises(RegisterConflict, match="真目录"):
        _do(vault, _dev(tmp_path), w)
    assert w.written == []
    assert not os.path.lexists(elsewhere / "alpha")          # 没往别人地盘里写

def test_duplicate_skill_name_across_sources_refuses(tmp_path):
    """opencode 的 skill 名全局扁平，重名它只 WARN 一条再丢掉一个——在这里就停。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    _plugin_skill(vault, "p1", "alpha")
    _manifest(vault, {"p1": ["opencode"]})
    w = Writer()
    with pytest.raises(RegisterConflict, match="alpha"):
        _do(vault, _dev(tmp_path), w)
    assert w.written == []

def test_duplicate_across_two_plugins_refuses(tmp_path):
    vault = tmp_path / "vault"
    _plugin_skill(vault, "p1", "beta")
    _plugin_skill(vault, "p2", "beta")
    _manifest(vault, {"p1": ["opencode"], "p2": ["opencode"]})
    with pytest.raises(RegisterConflict, match="beta"):
        _do(vault, _dev(tmp_path, enabled=("p1", "p2")))

def test_same_source_seen_twice_is_not_a_duplicate(tmp_path):
    """同一个真身被两条路径指到不算撞名（realpath 相同）。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    pairs = collect_opencode_sources(vault, _dev(tmp_path, enabled=()))
    assert [n for n, _ in pairs] == ["alpha"]

# ── hub-memory（源在 hub 包里，不在金库）───────────────────────────────
def _hub_pkg(tmp_path) -> Path:
    d = tmp_path / "hubpkg" / "hub" / "skills" / "hub-memory"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# hub-memory\n", encoding="utf-8")
    return tmp_path / "hubpkg"

def test_hub_memory_is_linked_when_hub_root_given(tmp_path):
    """关掉兼容扫描后 opencode 就只认自己家；hub-memory 的源不在金库，必须单独带上，
    否则它会无声消失。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    to_link, ensured = plan_link_opencode_skills(vault, dev, _hub_pkg(tmp_path))
    commit_link_opencode_skills(to_link, Writer())
    assert (_oc_skill_dir(tmp_path) / "hub-memory" / "SKILL.md").exists()
    assert sorted(Path(e).name for e in ensured) == ["alpha", "hub-memory"]

def test_hub_memory_omitted_when_hub_root_absent(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    _, ensured = plan_link_opencode_skills(vault, _dev(tmp_path))
    assert [Path(e).name for e in ensured] == ["alpha"]

def test_vault_skill_named_hub_memory_collides(tmp_path):
    """金库里若也有一把叫 hub-memory 的普通 skill，两个源指向同一个落点——停下来。
    （register.check_link_collisions 防的是同一个坑，这里是 opencode 侧的对应防线。）"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "hub-memory")
    with pytest.raises(RegisterConflict, match="hub-memory"):
        plan_link_opencode_skills(vault, _dev(tmp_path), _hub_pkg(tmp_path))

# ── 状态 ───────────────────────────────────────────────────────────────
def test_status_reports_missing_then_ok(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    assert [s for s, _ in opencode_skill_status(vault, dev)] == ["missing"]
    _do(vault, dev)
    assert [s for s, _ in opencode_skill_status(vault, dev)] == ["ok"]

def test_status_reports_conflict_for_foreign_entry(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    mine = _oc_skill_dir(tmp_path) / "alpha"
    mine.mkdir(parents=True)
    assert [s for s, _ in opencode_skill_status(vault, _dev(tmp_path))] == ["conflict"]

def test_status_empty_when_device_has_no_opencode(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    assert opencode_skill_status(vault, _dev(tmp_path, opencode=False)) == []

def test_status_reports_orphan_after_source_removed(tmp_path):
    """源侧删了 skill——链接留在原地（本模块从不删）。它不再是期望项，但必须报出来，
    否则永远没人知道那条断链还躺着。"""
    vault = tmp_path / "vault"
    src = _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    _do(vault, dev)
    (src / "SKILL.md").unlink(); src.rmdir()
    assert opencode_skill_status(vault, dev) == [("orphan", str(_oc_skill_dir(tmp_path) / "alpha"))]
    assert os.path.lexists(_oc_skill_dir(tmp_path) / "alpha")   # 没被删，等人工清

def test_status_reports_orphan_after_plugin_disabled(tmp_path):
    """把插件从 device.toml 的 enabled 里去掉——它带来的 skill 链接全变孤儿。"""
    vault = tmp_path / "vault"
    _plugin_skill(vault, "p1", "beta")
    _manifest(vault, {"p1": ["opencode"]})
    _do(vault, _dev(tmp_path))
    rows = opencode_skill_status(vault, _dev(tmp_path, enabled=()))
    assert rows == [("orphan", str(_oc_skill_dir(tmp_path) / "beta"))]

def test_status_ignores_user_own_skill_dir(tmp_path):
    """用户自己在 opencode 的 skill 目录里放的真目录——不是链接、不指金库，一概不报，
    绝不把别人的东西冤成 hub 残留。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    _do(vault, dev)
    mine = _oc_skill_dir(tmp_path) / "my-own"
    mine.mkdir()
    (mine / "SKILL.md").write_text("# 我自己的\n", encoding="utf-8")
    assert [s for s, _ in opencode_skill_status(vault, dev)] == ["ok"]

def test_status_ignores_link_pointing_outside_vault(tmp_path):
    """指向金库外的链接也不报——归属判据是"目标指回金库/hub 包"，不满足就不是我们的。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    _do(vault, dev)
    outside = tmp_path / "outside"; outside.mkdir()
    make_dir_link(outside, _oc_skill_dir(tmp_path) / "foreign")
    assert [s for s, _ in opencode_skill_status(vault, dev)] == ["ok"]

def test_orphan_ownership_also_covers_hub_package(tmp_path):
    """hub-memory 的源在 hub 包里而非金库——归属判据必须**同时**认 hub_root，
    否则 hub 包那侧留下的残留永远报不出来。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    hub = _hub_pkg(tmp_path)
    _do(vault, dev)
    make_dir_link(hub / "hub" / "skills" / "hub-memory",         # 一条指进 hub 包的陈年链接
                  _oc_skill_dir(tmp_path) / "stale-thing")
    rows = opencode_skill_status(vault, dev, hub)
    assert ("orphan", str(_oc_skill_dir(tmp_path) / "stale-thing")) in rows

# ── skills.paths 提示 ──────────────────────────────────────────────────
def _write_cfg(tmp_path, data) -> None:
    p = Path(_dev(tmp_path).paths["OPENCODE_CONFIG"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")

def test_hint_fires_when_skills_paths_points_into_vault(tmp_path):
    vault = tmp_path / "vault"; (vault / "shared").mkdir(parents=True)
    _write_cfg(tmp_path, {"skills": {"paths": [str(vault / "shared" / "plugins")]}})
    assert "skills.paths" in stale_skills_paths_hint(_dev(tmp_path), vault)

def test_hint_silent_for_unrelated_paths(tmp_path):
    vault = tmp_path / "vault"; (vault / "shared").mkdir(parents=True)
    _write_cfg(tmp_path, {"skills": {"paths": [str(tmp_path / "unrelated")]}})
    assert stale_skills_paths_hint(_dev(tmp_path), vault) is None

def test_hint_silent_when_config_unparsable(tmp_path):
    """带密钥那份文件坏了也只是不吭声——hub 对它的态度是能不碰就不碰。"""
    vault = tmp_path / "vault"; (vault / "shared").mkdir(parents=True)
    p = Path(_dev(tmp_path).paths["OPENCODE_CONFIG"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ 尾逗号, }", encoding="utf-8")
    assert stale_skills_paths_hint(_dev(tmp_path), vault) is None

def test_hint_silent_when_no_config_file(tmp_path):
    vault = tmp_path / "vault"; (vault / "shared").mkdir(parents=True)
    assert stale_skills_paths_hint(_dev(tmp_path), vault) is None
