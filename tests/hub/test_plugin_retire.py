import json, subprocess
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.plugin_cli import CliResult, CliUnavailable, installed_plugins
from hub.plugin_migrate import prepare_retire, execute_retire

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)

def _old_repo(src, name):
    d=src/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)],check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t")
    _git(d,"add","-A"); _git(d,"commit","-qm","c")

def _setup(tmp, names=("cjt","keil2clangd"), platforms=("claude","codex")):
    # 外层容器 src_dir(plugins-dev):含声明的旧子仓 + 一份**独有** docs(退役不该删它)
    src=tmp/"plugins-dev"; src.mkdir()
    for n in names: _old_repo(src, n)
    (src/"docs").mkdir(); (src/"docs/design.md").write_text("独有设计文档\n", encoding="utf-8")
    # 迁移输入
    inp=tmp/"m.toml"
    inp.write_text("".join(f'[{n}]\nplatforms={json.dumps(list(platforms))}\nenabled={json.dumps(list(platforms))}\n'
                          for n in names), encoding="utf-8")
    # device
    box=tmp/"box"; box.mkdir()
    dp="".join(f'[plugins.{t}]\nenabled={json.dumps(list(names))}\n' for t in platforms)
    (box/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dp, encoding="utf-8")
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    from hub.vault import load_device
    return src, inp, load_device(tmp,"box")

HELP="install uninstall enable disable add remove marketplace list"
def _runner(names=("cjt","keil2clangd"), platforms=("claude","codex"),
            old_market_present=False, stale_old_ids=(), market_paths=None,
            codex_dead=False, claude_inst_extra=None):
    """全切成功的干净态为默认;各参数注入一种"仍有旧引用"或平台不可读的情形。"""
    claude_inst=[{"id":f"{n}@{n}","version":"0.1.0","enabled":True,"installPath":"cache"} for n in names]
    claude_inst+=[{"id":pid,"version":"0.1.0","enabled":True,"installPath":"cache"} for pid in stale_old_ids if pid.split("@")[1]=="xu-local"]
    claude_inst+=list(claude_inst_extra or [])
    codex_inst=[{"pluginId":f"{n}@{n}","version":"0.1.0","enabled":True,
                 "marketplaceName":n,"source":{"path":f"shared/{n}"}} for n in names]
    codex_inst+=[{"pluginId":pid,"version":"0.1.0","enabled":True,"marketplaceName":"xu-local",
                  "source":{"path":"old"}} for pid in stale_old_ids]
    cl_mkts=[{"name":n,"path":(market_paths or {}).get(n,f"shared/{n}")} for n in names]
    cx_mkts=[{"name":n,"root":(market_paths or {}).get(n,f"shared/{n}")} for n in names]
    if old_market_present:
        cl_mkts.append({"name":"xu-local","path":"old"}); cx_mkts.append({"name":"xu-local","root":"old"})
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,HELP,"")
        if s=="claude plugin list --json": return CliResult(0,json.dumps(claude_inst),"")
        if s=="claude plugin marketplace list --json": return CliResult(0,json.dumps(cl_mkts),"")
        if argv[0]=="codex" and codex_dead:          # Codex 不容忍悬空:整体枚举硬失败
            return CliResult(1,"","failed to load marketplace snapshot(s): dangling")
        if s=="codex plugin list --json": return CliResult(0,json.dumps({"installed":codex_inst}),"")
        if s=="codex plugin marketplace list --json": return CliResult(0,json.dumps({"marketplaces":cx_mkts}),"")
        return CliResult(0,"ok","")
    return r

# ---- 全切成功:只删声明的子仓,不碰外层容器/docs ----------------------------
def test_all_switched_retires_only_declared_subrepos(tmp_path):
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner())
    assert plan.blocks==[]
    assert {a.target for a in plan.actions}=={str(src/"cjt"), str(src/"keil2clangd")}
    execute_retire(plan, Writer())
    assert not (src/"cjt").exists() and not (src/"keil2clangd").exists()   # 声明的子仓已删
    assert (src/"docs/design.md").exists()                                  # 外层容器独有文档保留
    assert src.exists()                                                     # 外层容器本身保留

# ---- 平台仍有旧引用:零删除 --------------------------------------------------
def test_stale_old_identity_blocks_retire_zero_delete(tmp_path):
    # 模拟 cutover 部分失败:旧 <name>@xu-local 仍安装
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner(stale_old_ids=("cjt@xu-local",)))
    assert plan.blocks and plan.actions==[]
    execute_retire(plan, Writer())
    assert (src/"cjt/.git").exists() and (src/"keil2clangd/.git").exists()  # 零删除

def test_old_market_still_registered_blocks_retire(tmp_path):
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner(old_market_present=True))
    assert plan.blocks and plan.actions==[]

def test_market_path_under_old_src_blocks_retire(tmp_path):
    # 某市场仍指向旧源目录(未换源)→零删除
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev,
                        runner=_runner(market_paths={"cjt":str(src/"cjt")}))
    assert plan.blocks and plan.actions==[]

def test_new_identity_not_enabled_blocks_retire(tmp_path):
    # 新身份未按 device 策略启用(claude 侧 disabled)→零删除
    src,inp,dev=_setup(tmp_path)
    bad=[{"id":"cjt@cjt","version":"0.1.0","enabled":False,"installPath":"cache"}]
    plan=prepare_retire(src, tmp_path, inp, dev,
                        runner=_runner(names=("keil2clangd",), claude_inst_extra=bad))
    assert plan.blocks and plan.actions==[]

# ---- Codex 不容忍悬空:读不到平台状态→零删除 --------------------------------
def test_codex_unreadable_blocks_retire(tmp_path):
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner(codex_dead=True))
    assert plan.blocks and plan.actions==[]

def test_claude_tolerates_dangling_codex_does_not(tmp_path):
    # 行为差异 fixture:同一"悬空"态下,claude plugin list 可读(带 errors),codex 硬失败。
    r=_runner(codex_dead=True)
    claude=installed_plugins("claude", runner=r)          # claude 容忍→读得到
    assert "cjt@cjt" in claude
    with pytest.raises(CliUnavailable):                    # codex 不容忍→抛
        installed_plugins("codex", runner=r)

# ---- dry-run 零写 + 重跑幂等 ------------------------------------------------
def test_retire_dry_run_zero_delete(tmp_path):
    src,inp,dev=_setup(tmp_path)
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner())
    w=Writer(dry_run=True); execute_retire(plan, w)
    assert (src/"cjt/.git").exists() and (src/"keil2clangd/.git").exists()  # 一个都没删
    assert plan.actions                                                     # 计划里有(只是没执行)

def test_retire_rerun_idempotent(tmp_path):
    src,inp,dev=_setup(tmp_path)
    execute_retire(prepare_retire(src, tmp_path, inp, dev, runner=_runner()), Writer())
    # 源已删,重跑:无待删动作,零阻断
    plan2=prepare_retire(src, tmp_path, inp, dev, runner=_runner())
    assert plan2.blocks==[] and plan2.actions==[]

# ---- containment：删除目标必须是 src_dir 下真实直属 git 子仓（缺陷短审阻断项）------
def _dev(tmp, box, claude=(), codex=()):
    b=tmp/box; b.mkdir()
    dp=(f'[plugins.claude]\nenabled={json.dumps(list(claude))}\n'
        f'[plugins.codex]\nenabled={json.dumps(list(codex))}\n')
    (b/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dp, encoding="utf-8")
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp, box)

def _runner2(claude_inst, codex_inst, cl_mkts, cx_mkts, codex_dead=False):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,HELP,"")
        if s=="claude plugin list --json": return CliResult(0,json.dumps(claude_inst),"")
        if s=="claude plugin marketplace list --json": return CliResult(0,json.dumps(cl_mkts),"")
        if argv[0]=="codex" and codex_dead: return CliResult(1,"","dangling")
        if s=="codex plugin list --json": return CliResult(0,json.dumps({"installed":codex_inst}),"")
        if s=="codex plugin marketplace list --json":
            return CliResult(0,json.dumps({"marketplaces":cx_mkts}),"")
        return CliResult(0,"ok","")
    return r

def test_escaping_table_name_blocks_zero_delete(tmp_path):
    # 迁移输入表名逃逸(../outside):必须零删除,绝不碰 src_dir 外的目录
    src=tmp_path/"plugins-dev"; src.mkdir()
    outside=tmp_path/"outside"; outside.mkdir(); (outside/"keep.txt").write_text("x",encoding="utf-8")
    inp=tmp_path/"m.toml"; inp.write_text('["../outside"]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    plan=prepare_retire(src, tmp_path, inp, _dev(tmp_path,"box"), runner=_runner2([],[],[],[]))
    assert plan.blocks and plan.actions==[]
    execute_retire(plan, Writer())
    assert outside.exists() and (outside/"keep.txt").exists()                # 逃逸目标毫发无损

def test_retire_target_junction_blocks_zero_delete(tmp_path):
    # 声明名合法,但磁盘上该名是指向 src 外真仓的 junction/symlink → 拒绝,外部目标完好
    from hub.fslink import make_dir_link
    src=tmp_path/"plugins-dev"; src.mkdir()
    _old_repo(tmp_path, "cjt"); external=tmp_path/"cjt"
    make_dir_link(external, src/"cjt")                                       # src/cjt 是链接
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n',encoding="utf-8")
    cl_mkts=[{"name":"cjt","path":"shared/cjt"}]
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"c"}]
    plan=prepare_retire(src, tmp_path, inp, _dev(tmp_path,"box",claude=("cjt",)),
                        runner=_runner2(ci,[],cl_mkts,[]))
    assert plan.blocks and plan.actions==[]
    execute_retire(plan, Writer())
    assert (external/".git").exists()                                       # 链接目标(外部真仓)完好

def test_retire_target_non_git_dir_blocks(tmp_path):
    # 声明名存在但只是普通非 git 目录 → 拒绝(不当作旧子仓删)
    src=tmp_path/"plugins-dev"; src.mkdir()
    (src/"cjt").mkdir(); (src/"cjt/file.txt").write_text("x",encoding="utf-8")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n',encoding="utf-8")
    cl_mkts=[{"name":"cjt","path":"shared/cjt"}]
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"c"}]
    plan=prepare_retire(src, tmp_path, inp, _dev(tmp_path,"box",claude=("cjt",)),
                        runner=_runner2(ci,[],cl_mkts,[]))
    assert plan.blocks and plan.actions==[]
    assert (src/"cjt/file.txt").exists()

# ---- Claude 列表外「已装但 disabled」是合法态,不该阻断退役(compact-plus 型)-------
def test_claude_offlist_disabled_allows_retire(tmp_path):
    src=tmp_path/"plugins-dev"; src.mkdir()
    for n in ("cjt","compact-plus"): _old_repo(src, n)
    inp=tmp_path/"m.toml"
    inp.write_text('[cjt]\nplatforms=["claude","codex"]\nenabled=["claude","codex"]\n'
                   '[compact-plus]\nplatforms=["claude"]\nenabled=[]\n', encoding="utf-8")
    dev=_dev(tmp_path,"box", claude=("cjt",), codex=("cjt",))               # compact-plus 列表外
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"c"},
        {"id":"compact-plus@compact-plus","version":"0.1.0","enabled":False,"installPath":"c"}]  # disabled
    xi=[{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,"marketplaceName":"cjt","source":{"path":"shared/cjt"}}]
    cl=[{"name":"cjt","path":"shared/cjt"},{"name":"compact-plus","path":"shared/compact-plus"}]
    cx=[{"name":"cjt","root":"shared/cjt"}]
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner2(ci,xi,cl,cx))
    assert plan.blocks==[]
    assert {a.target for a in plan.actions}=={str(src/"cjt"), str(src/"compact-plus")}

def test_claude_offlist_enabled_blocks_retire(tmp_path):
    src=tmp_path/"plugins-dev"; src.mkdir()
    for n in ("cjt","compact-plus"): _old_repo(src, n)
    inp=tmp_path/"m.toml"
    inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n'
                   '[compact-plus]\nplatforms=["claude"]\nenabled=[]\n', encoding="utf-8")
    dev=_dev(tmp_path,"box", claude=("cjt",))
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"c"},
        {"id":"compact-plus@compact-plus","version":"0.1.0","enabled":True,"installPath":"c"}]   # enabled!
    cl=[{"name":"cjt","path":"shared/cjt"},{"name":"compact-plus","path":"shared/compact-plus"}]
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner2(ci,[],cl,[]))
    assert plan.blocks and plan.actions==[]

def test_codex_offlist_present_blocks_retire(tmp_path):
    # Codex 无独立禁用模型:列表外仍 present → 阻断
    src=tmp_path/"plugins-dev"; src.mkdir()
    for n in ("cjt","compact-plus"): _old_repo(src, n)
    inp=tmp_path/"m.toml"
    inp.write_text('[cjt]\nplatforms=["codex"]\nenabled=["codex"]\n'
                   '[compact-plus]\nplatforms=["codex"]\nenabled=[]\n', encoding="utf-8")
    dev=_dev(tmp_path,"box", codex=("cjt",))
    xi=[{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,"marketplaceName":"cjt","source":{"path":"shared/cjt"}},
        {"pluginId":"compact-plus@compact-plus","version":"0.1.0","enabled":True,"marketplaceName":"compact-plus","source":{"path":"shared/compact-plus"}}]
    cx=[{"name":"cjt","root":"shared/cjt"},{"name":"compact-plus","root":"shared/compact-plus"}]
    plan=prepare_retire(src, tmp_path, inp, dev, runner=_runner2([],xi,[],cx))
    assert plan.blocks and plan.actions==[]
