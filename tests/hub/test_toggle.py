import json
import pytest
from pathlib import Path

from hub.toggle_ops import toggle_asset
from hub.vault import load_device
from hub.plugin_cli import CliResult
from hub.dsh_ops import patch_path
from hub.opencode_skills import opencode_skill_dir


def _mk_vault(tmp_path, host="box1", *, plugin_platforms=("opencode",),
              plugin_skills=("beta",), standalone_skills=("alpha",),
              enabled_plugins=(), enabled_skills=None, dsh_enabled=False):
    vault = tmp_path / "vault"
    (vault / host).mkdir(parents=True)
    (vault / "vault.toml").write_text("""version = 3
""", encoding="utf-8")

    if plugin_platforms or plugin_skills:
        (vault / "shared" / "plugins" / "p1" / ".claude-plugin").mkdir(parents=True)
        (vault / "shared" / "plugins" / "p1" / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "p1", "version": "0.1.0"}), encoding="utf-8")
        (vault / "shared" / "plugins" / "p1" / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "p1", "plugins": [{"name": "p1", "source": ".", "description": "d"}]}),
            encoding="utf-8")
        for sk in plugin_skills:
            d = vault / "shared" / "plugins" / "p1" / "skills" / sk
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"""# {sk}
""", encoding="utf-8")
        man = ""
        if plugin_platforms:
            man += f"""[p1]
platforms = {json.dumps(list(plugin_platforms))}

"""
        (vault / "shared" / "plugins" / "manifest.toml").write_text(man, encoding="utf-8")

    for sk in standalone_skills:
        d = vault / "shared" / "skills" / sk
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"""# {sk}
""", encoding="utf-8")

    homes = tmp_path / "home"
    dev_text = """class=["work"]
projects=[]
[paths]
CLAUDE_HOME="%s/.claude"
AGENTS_HOME="%s/.agents"
OPENCODE_CONFIG="%s/.config/opencode/opencode.json"
DSH_HOME="%s/.dsh"
DSH_PROFILE="headless"
""" % (homes.as_posix(), homes.as_posix(), homes.as_posix(), homes.as_posix())
    if enabled_plugins:
        dev_text += """
[plugins.opencode]
enabled=""" + json.dumps(list(enabled_plugins)) + """
"""
    if dsh_enabled:
        dev_text += """
[plugins.dsh]
enabled=["p1"]
"""
    if enabled_skills is not None:
        dev_text += """
[skills.opencode]
enabled=""" + json.dumps(list(enabled_skills)) + """
"""
    (vault / host / "device.toml").write_text(dev_text, encoding="utf-8")
    return vault


def _hub_root(tmp_path):
    hub = tmp_path / "hub"
    src = hub / "dsh-claude-plugin-loader" / "dsh-claude-plugin-loader.mjs"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("""export const name = 'dsh-claude-plugin-loader'
""", encoding="utf-8")
    hm = hub / "hub" / "skills" / "hub-memory"
    hm.mkdir(parents=True, exist_ok=True)
    (hm / "SKILL.md").write_text("""# hub-memory
""", encoding="utf-8")
    return hub


def test_plugin_opencode_on_off(tmp_path):
    vault = _mk_vault(tmp_path, enabled_plugins=())
    res_on = toggle_asset(vault, "box1", "plugin", "p1", "opencode", True,
                          hub_root=_hub_root(tmp_path))
    assert res_on["errors"] == []
    assert res_on["results"][0]["status"] == "applied"
    dev = load_device(vault, "box1")
    assert dev.plugins["opencode"] == ["p1"]
    assert (opencode_skill_dir(dev) / "beta" / "SKILL.md").exists()

    res_off = toggle_asset(vault, "box1", "plugin", "p1", "opencode", False,
                           hub_root=_hub_root(tmp_path))
    assert res_off["errors"] == []
    dev = load_device(vault, "box1")
    assert dev.plugins.get("opencode") is None or "p1" not in dev.plugins["opencode"]
    assert not (opencode_skill_dir(dev) / "beta").exists()


def test_skill_opencode_on_off(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=(), plugin_skills=(),
                      standalone_skills=("alpha",), enabled_skills=None)
    res_on = toggle_asset(vault, "box1", "skill", "alpha", "opencode", True,
                          hub_root=_hub_root(tmp_path))
    assert res_on["errors"] == []
    dev = load_device(vault, "box1")
    assert dev.skills["opencode"] == ["alpha"]
    assert (opencode_skill_dir(dev) / "alpha" / "SKILL.md").exists()

    res_off = toggle_asset(vault, "box1", "skill", "alpha", "opencode", False,
                           hub_root=_hub_root(tmp_path))
    assert res_off["errors"] == []
    dev = load_device(vault, "box1")
    assert dev.skills.get("opencode") is None or "alpha" not in dev.skills["opencode"]
    assert not (opencode_skill_dir(dev) / "alpha").exists()


def test_skill_dsh_plugin_internal_on_off(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=("dsh",), plugin_skills=("beta",),
                      standalone_skills=(), enabled_plugins=(), dsh_enabled=True)
    hub = _hub_root(tmp_path)
    res_on = toggle_asset(vault, "box1", "skill", "beta", "dsh", True,
                          plugin="p1", hub_root=hub)
    assert res_on["errors"] == []
    dev = load_device(vault, "box1")
    assert dev.skills["dsh"] == ["beta"]
    patch = patch_path(dev)
    assert patch is not None and patch.exists()
    assert "p1:beta" in patch.read_text(encoding="utf-8")

    res_off = toggle_asset(vault, "box1", "skill", "beta", "dsh", False,
                           plugin="p1", hub_root=hub)
    assert res_off["errors"] == []
    dev = load_device(vault, "box1")
    assert dev.skills.get("dsh") is None or "beta" not in dev.skills["dsh"]
    assert "p1:beta" not in patch_path(dev).read_text(encoding="utf-8")


def test_claude_plugin_internal_skill_is_degraded(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=("claude",), plugin_skills=("beta",),
                      standalone_skills=())
    res = toggle_asset(vault, "box1", "skill", "beta", "claude", False,
                       plugin="p1", hub_root=_hub_root(tmp_path))
    assert res["errors"] == []
    assert res["results"][0]["status"] == "degraded"
    assert res["results"][0]["controlled_by"] == "plugin"
    dev = load_device(vault, "box1")
    assert "claude" not in dev.skills


def test_standalone_skill_claude_on_off(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=(), plugin_skills=(),
                      standalone_skills=("alpha",), enabled_skills=None)
    hub = _hub_root(tmp_path)
    res_on = toggle_asset(vault, "box1", "skill", "alpha", "claude", True, hub_root=hub)
    assert res_on["errors"] == []
    dev = load_device(vault, "box1")
    link = Path(dev.paths["CLAUDE_HOME"]) / "skills" / "alpha"
    assert link.exists()

    res_off = toggle_asset(vault, "box1", "skill", "alpha", "claude", False, hub_root=hub)
    assert res_off["errors"] == []
    assert not link.exists()


def test_memory_is_readonly(tmp_path):
    vault = _mk_vault(tmp_path)
    with pytest.raises(ValueError, match="只读"):
        toggle_asset(vault, "box1", "memory", "m1", "claude", False)


def test_ambiguous_skill_requires_plugin(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=("opencode",), plugin_skills=("alpha",),
                      standalone_skills=("alpha",), enabled_plugins=("p1",))
    with pytest.raises(ValueError, match="歧义|多个来源|--plugin"):
        toggle_asset(vault, "box1", "skill", "alpha", "opencode", True)



def _fake_claude_runner(mkts=None, inst=None):
    def runner(argv):
        line = " ".join(argv)
        if line.endswith("--help"):
            return CliResult(0, "install uninstall enable disable marketplace", "")
        if line == "claude plugin marketplace list --json":
            return CliResult(0, json.dumps(mkts or []), "")
        if line == "claude plugin list --json":
            return CliResult(0, json.dumps(inst or []), "")
        return CliResult(0, "ok", "")
    return runner


def test_plugin_claude_on_off_with_fake_runner(tmp_path):
    vault = _mk_vault(tmp_path, plugin_platforms=("claude",), plugin_skills=("beta",),
                      standalone_skills=())
    on_runner = _fake_claude_runner(mkts=[], inst=[])
    res_on = toggle_asset(vault, "box1", "plugin", "p1", "claude", True,
                          hub_root=_hub_root(tmp_path), runner=on_runner)
    assert res_on["errors"] == []
    on_actions = " ".join(res_on["actions"])
    assert "安装" in on_actions or "市场" in on_actions
    assert load_device(vault, "box1").plugins["claude"] == ["p1"]

    src = str((vault / "shared" / "plugins" / "p1").resolve())
    off_runner = _fake_claude_runner(
        mkts=[{"name": "p1", "path": src}],
        inst=[{"id": "p1@p1", "version": "0.1.0", "enabled": True, "installPath": "x"}])
    res_off = toggle_asset(vault, "box1", "plugin", "p1", "claude", False,
                           hub_root=_hub_root(tmp_path), runner=off_runner)
    assert res_off["errors"] == []
    off_actions = " ".join(res_off["actions"])
    assert "禁用" in off_actions or "移除" in off_actions
    dev = load_device(vault, "box1")
    assert dev.plugins.get("claude") is None or "p1" not in dev.plugins["claude"]

def test_dry_run_plugin_opencode_no_disk_change(tmp_path):
    vault = _mk_vault(tmp_path, enabled_plugins=())
    hub = _hub_root(tmp_path)
    before = (vault / "box1" / "device.toml").read_text(encoding="utf-8")
    res = toggle_asset(vault, "box1", "plugin", "p1", "opencode", True,
                       hub_root=hub, dry_run=True)
    assert res["dry_run"] is True
    assert res["actions"]
    assert (vault / "box1" / "device.toml").read_text(encoding="utf-8") == before
    dev = load_device(vault, "box1")
    assert not (opencode_skill_dir(dev) / "beta").exists()
