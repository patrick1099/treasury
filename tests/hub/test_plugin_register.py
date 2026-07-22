import json
import pytest
from pathlib import Path
from hub.plugin_cli import CliResult
from hub.plugin_ops import prepare_plugin_register, PluginContainmentError
from hub.plugin_manifest import PluginIdentityError

def _setup(tmp, entries, plugins, ver="0.1.0", identity_ok=True):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    body = ""
    for name, plats in entries.items():
        body += f'[{name}]\nplatforms = {json.dumps(plats)}\n'
        cp = tmp/"shared/plugins"/name/".claude-plugin"; cp.mkdir(parents=True)
        pn = "WRONG" if (not identity_ok and name == "cjt") else name
        (cp/"marketplace.json").write_text(json.dumps(
            {"name": name, "plugins":[{"name": pn, "source":".","description":"d"}]}), encoding="utf-8")
        (cp/"plugin.json").write_text(json.dumps({"name": pn, "version": ver}), encoding="utf-8")
    (tmp/"shared/plugins/manifest.toml").write_text(body, encoding="utf-8")
    (tmp/"box").mkdir()
    dev_plugins = "".join(f'[plugins.{t}]\nenabled={json.dumps(v)}\n' for t, v in plugins.items())
    (tmp/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dev_plugins, encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp, "box")

HELP = "install uninstall enable disable add remove marketplace list"
def make_runner(mkts_claude=None, mkts_codex=None, inst_claude=None, inst_codex=None):
    def runner(argv):
        s = " ".join(argv)
        if s.endswith("--help"): return CliResult(0, HELP, "")
        if s == "claude plugin marketplace list --json": return CliResult(0, json.dumps(mkts_claude or []), "")
        if s == "codex plugin marketplace list --json": return CliResult(0, json.dumps({"marketplaces": mkts_codex or []}), "")
        if s == "claude plugin list --json": return CliResult(0, json.dumps(inst_claude or []), "")
        if s == "codex plugin list --json": return CliResult(0, json.dumps({"installed": inst_codex or [], "available": []}), "")
        return CliResult(0, "ok", "")
    return runner
def _ids(plan): return [a.id for a in plan.actions]

def test_no_manifest_empty_plan(tmp_path):
    (tmp_path/"vault.toml").write_text("version = 2\n", encoding="utf-8")  # 无 manifest：不要求 v3
    (tmp_path/"box").mkdir(); (tmp_path/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    from hub.vault import load_device
    plan = prepare_plugin_register(tmp_path, load_device(tmp_path,"box"), runner=make_runner())
    assert plan.actions == []

def test_allowlist_inside_not_installed_installs(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]})
    plan = prepare_plugin_register(tmp_path, dev, runner=make_runner())
    ids = _ids(plan)
    assert "cjt:claude:mktadd" in ids
    assert "cjt:claude:install" in ids
    # claude plugin install 安装即在 user scope 自动启用 —— 不得再生成冗余 enable
    assert "cjt:claude:enable" not in ids
    install = next(a for a in plan.actions if a.id == "cjt:claude:install")
    assert install.depends_on == ("cjt:claude:mktadd",)
    assert install.cli.argv == ["plugin", "install", "cjt@cjt", "--scope", "user"]

def test_allowlist_inside_installed_disabled_enables_only(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]})
    src = str((tmp_path/"shared/plugins/cjt").resolve())
    runner = make_runner(mkts_claude=[{"name":"cjt","path":src}],
        inst_claude=[{"id":"cjt@cjt","version":"0.1.0","enabled":False,"installPath":"x"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    ids = _ids(plan)
    # 已装但禁用：只补 enable，不重装
    assert "cjt:claude:enable" in ids and "cjt:claude:install" not in ids
    enable = next(a for a in plan.actions if a.id == "cjt:claude:enable")
    assert enable.cli.argv == ["plugin", "enable", "cjt@cjt", "--scope", "user"]
    # 幂等兜底标记：并发/重跑时凭真实状态确认 enabled 才按成功处理
    assert enable.confirm_enabled == "cjt@cjt"

def test_allowlist_inside_installed_enabled_noop(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]})
    src = str((tmp_path/"shared/plugins/cjt").resolve())
    runner = make_runner(mkts_claude=[{"name":"cjt","path":src}],
        inst_claude=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"x"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    ids = _ids(plan)
    # 已装且启用：readiness 已满足，不安排任何 install/enable
    assert not any(i in ("cjt:claude:install", "cjt:claude:enable") for i in ids)

def test_allowlist_outside_installed_disables_not_uninstalls(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":[]})
    src = str((tmp_path/"shared/plugins/cjt").resolve())
    runner = make_runner(mkts_claude=[{"name":"cjt","path":src}],
        inst_claude=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"x"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    ids = _ids(plan)
    assert "cjt:claude:disable" in ids and not any("install" in i for i in ids)
    disable = next(a for a in plan.actions if a.id == "cjt:claude:disable")
    assert disable.cli.argv[-2:] == ["--scope", "user"]

def test_codex_source_moved_remove_then_add(tmp_path):
    dev = _setup(tmp_path, {"cjt":["codex"]}, {"codex":["cjt"]})
    runner = make_runner(mkts_codex=[{"name":"cjt","root":"C:/old/path"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner); ids = _ids(plan)
    assert ids.index("cjt:codex:mktrm") < ids.index("cjt:codex:mktadd")
    add = [a for a in plan.actions if a.id == "cjt:codex:mktadd"][0]
    assert "cjt:codex:mktrm" in add.depends_on

def test_identity_mismatch_raises(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]}, identity_ok=False)
    with pytest.raises(PluginIdentityError):
        prepare_plugin_register(tmp_path, dev, runner=make_runner())

def test_shared_plugins_container_escape_refused(tmp_path):
    import os
    outside=tmp_path/"outside"; cp=outside/"cjt/.claude-plugin"; cp.mkdir(parents=True)
    (cp/"marketplace.json").write_text(json.dumps(
        {"name":"cjt","plugins":[{"name":"cjt","source":".","description":"d"}]}),encoding="utf-8")
    (cp/"plugin.json").write_text(json.dumps({"name":"cjt","version":"0.1.0"}),encoding="utf-8")
    (outside/"manifest.toml").write_text('[cjt]\nplatforms=["claude"]\n',encoding="utf-8")
    (tmp_path/"shared").mkdir(); (tmp_path/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    try: os.symlink(outside,tmp_path/"shared/plugins",target_is_directory=True)
    except OSError: pytest.skip("本机无 symlink 权限")
    (tmp_path/"box").mkdir(); (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n[plugins.claude]\nenabled=["cjt"]\n',encoding="utf-8")
    from hub.vault import load_device
    with pytest.raises(PluginContainmentError):
        prepare_plugin_register(tmp_path,load_device(tmp_path,"box"),runner=make_runner())
