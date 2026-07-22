import json, subprocess
from pathlib import Path
import pytest
from hub.plugin_cli import CliResult
from hub.plugin_migrate import prepare_cutover, MigrationInputError

def _git(c,*a): subprocess.run(["git","-C",str(c),*a],check=True,capture_output=True)

def _setup(tmp, name="cjt", platforms=("codex",), enabled_tools=("codex",)):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    root=tmp/"shared/plugins"/name; cp=root/".claude-plugin"; cp.mkdir(parents=True)
    (cp/"marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
    (cp/"plugin.json").write_text(json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    subprocess.run(["git","init","-q",str(root)],check=True)
    _git(root,"config","user.email","t@t"); _git(root,"config","user.name","t")
    _git(root,"add","-A"); _git(root,"commit","-qm","initial")
    (tmp/"shared/plugins/manifest.toml").write_text(
        f'[{name}]\nplatforms={json.dumps(list(platforms))}\n',encoding="utf-8")
    (tmp/"box").mkdir()
    dp="".join(f'[plugins.{t}]\nenabled=["{name}"]\n' for t in enabled_tools)
    (tmp/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dp,encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box"), root

def _runner(codex_mkts=None, codex_inst=None, claude_mkts=None, claude_inst=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="codex plugin marketplace list --json":
            return CliResult(0,json.dumps({"marketplaces":codex_mkts or []}),"")
        if s=="codex plugin list --json":
            return CliResult(0,json.dumps({"installed":codex_inst or [],"available":[]}),"")
        if s=="claude plugin marketplace list --json": return CliResult(0,json.dumps(claude_mkts or []),"")
        if s=="claude plugin list --json": return CliResult(0,json.dumps(claude_inst or []),"")
        return CliResult(0,"ok","")
    return r

def _ids(plan): return [a.id for a in plan.actions]

def test_old_identity_retired_only_after_new_identity_ready(tmp_path):
    dev,_=_setup(tmp_path)
    runner=_runner(
        codex_mkts=[{"name":"xu-local","root":"C:/old"}],
        codex_inst=[{"pluginId":"cjt@xu-local","version":"0.1.0","enabled":True,
                    "marketplaceName":"xu-local","source":{"path":"x"}}])
    plan=prepare_cutover(tmp_path,dev,runner=runner)
    ids=_ids(plan)
    assert "cjt:codex:add" in ids
    assert "cjt:codex:retire-old" in ids
    old=next(a for a in plan.actions if a.id=="cjt:codex:retire-old")
    assert "cjt:codex:add" in old.depends_on
    market=next(a for a in plan.actions if a.id=="codex:retire-market:xu-local")
    assert old.id in market.depends_on

def test_same_identity_source_move_forces_codex_reinstall(tmp_path):
    dev,_=_setup(tmp_path)
    installed=[{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,
                "marketplaceName":"cjt","source":{"path":"C:/old"}}]
    markets=[{"name":"cjt","root":"C:/old"}]
    plan=prepare_cutover(tmp_path,dev,runner=_runner(codex_mkts=markets,codex_inst=installed))
    reinstall=next(a for a in plan.actions if a.id=="cjt:codex:cutover-reinstall")
    assert reinstall.depends_on==("cjt:codex:mktadd",)
    assert reinstall.cli.argv==["plugin","add","cjt@cjt"]

def test_unknown_old_market_identity_blocks(tmp_path):
    dev,_=_setup(tmp_path)
    installed=[{"pluginId":"mystery@xu-local","version":"1","enabled":True,
                "marketplaceName":"xu-local","source":{"path":"x"}}]
    with pytest.raises(MigrationInputError):
        prepare_cutover(tmp_path,dev,runner=_runner(
            codex_mkts=[{"name":"xu-local","root":"C:/old"}],codex_inst=installed))

def test_cutover_requires_manifest(tmp_path):
    (tmp_path/"box").mkdir(parents=True)
    (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n',encoding="utf-8")
    from hub.vault import load_device
    with pytest.raises(MigrationInputError):
        prepare_cutover(tmp_path,load_device(tmp_path,"box"),runner=_runner())
