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

def test_cutover_reinstall_claude_desired_drops_redundant_enable(tmp_path):
    # 同身份换源(cjt)且期望启用：install 自动启用,不得再补 cutover-enable
    dev,_=_setup(tmp_path, name="cjt", platforms=("claude",), enabled_tools=("claude",))
    installed=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"C:/old"}]
    markets=[{"name":"cjt","path":"C:/old"}]        # 旧路径 → 触发换源重装
    plan=prepare_cutover(tmp_path,dev,runner=_runner(claude_mkts=markets,claude_inst=installed))
    ids=_ids(plan)
    assert "cjt:claude:cutover-uninstall" in ids
    assert "cjt:claude:cutover-install" in ids
    assert "cjt:claude:cutover-enable" not in ids
    state=next(a for a in plan.actions if a.id=="cjt:claude:cutover-state")
    assert "cjt:claude:cutover-install" in state.depends_on

def test_rerun_from_partial_converges_claude_retire_only(tmp_path):
    # 模拟 §4 部分完成后重跑:新身份已装且启用、市场已切 shared、Codex 已收敛干净、
    # Claude 仍残留旧 @xu-local + 未删 xu-local 市场。重跑只应收敛 Claude 残留,不碰 Codex。
    dev,root=_setup(tmp_path, name="keil2clangd",
                    platforms=("claude","codex"), enabled_tools=("claude","codex"))
    src=str(root.resolve())
    claude_mkts=[{"name":"keil2clangd","path":src},{"name":"xu-local","path":"C:/old/plugins-dev"}]
    claude_inst=[
        {"id":"keil2clangd@keil2clangd","version":"0.2.0","enabled":True,"installPath":src},
        {"id":"keil2clangd@xu-local","version":"0.2.0","enabled":True,"installPath":"C:/old"},
    ]
    codex_mkts=[{"name":"keil2clangd","root":src}]  # codex 已切 shared、xu-local 已删
    codex_inst=[{"pluginId":"keil2clangd@keil2clangd","version":"0.2.0","enabled":True,
                 "marketplaceName":"keil2clangd","source":{"path":src}}]
    plan=prepare_cutover(tmp_path,dev,runner=_runner(
        codex_mkts=codex_mkts,codex_inst=codex_inst,claude_mkts=claude_mkts,claude_inst=claude_inst))
    ids=_ids(plan)
    # 新身份已就绪 → 不再 install/enable(两平台)
    assert not any(i in ("keil2clangd:claude:install","keil2clangd:claude:enable",
                         "keil2clangd:codex:add") for i in ids)
    # Claude 只收敛:退役旧身份 + 删 xu-local 市场
    assert "keil2clangd:claude:retire-old" in ids
    assert "claude:retire-market:xu-local" in ids
    retire=next(a for a in plan.actions if a.id=="keil2clangd:claude:retire-old")
    assert retire.depends_on==()                    # 预检已 ready → 无虚假依赖,退役无条件可跑
    # Codex 已完成 → 零动作,不被破坏
    assert not any(i.startswith("keil2clangd:codex") or i.startswith("codex:") for i in ids)

def test_cutover_requires_manifest(tmp_path):
    (tmp_path/"box").mkdir(parents=True)
    (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n',encoding="utf-8")
    from hub.vault import load_device
    with pytest.raises(MigrationInputError):
        prepare_cutover(tmp_path,load_device(tmp_path,"box"),runner=_runner())
