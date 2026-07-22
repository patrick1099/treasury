import json, subprocess
from pathlib import Path
from hub.writer import Writer
from hub.plugin_migrate import prepare_migration, execute_migration

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _repo(src, name):
    d=src/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(
        json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    (d/"code.txt").write_text("v\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")
def _idx(p, rel): return subprocess.run(["git","-C",str(p),"ls-files","-s",rel], capture_output=True, text=True).stdout

def _vault(tmp_path):
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)], check=True)
    _git(v,"config","user.email","t@t"); _git(v,"config","user.name","t")
    return v

def test_execute_copies_keeps_source_and_inducts(tmp_path):
    # 三段式 phase1:只复制+induct,绝不删源。旧源保留,Codex 的旧市场根不悬空。
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=_vault(tmp_path)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    rep=execute_migration(prepare_migration(src, v, inp), v, Writer())
    assert not rep.failed
    assert (src/"cjt/.git").exists()                         # 源**保留**(不再删)
    assert (v/"shared/plugins/cjt/.git").exists()            # 嵌套仓在
    assert "160000" not in _idx(v,"shared/plugins/cjt")      # 父仓跟踪文件非 gitlink
    assert (v/"shared/plugins/manifest.toml").read_text(encoding="utf-8").strip().startswith("[cjt]")

def test_phase1_rerun_is_idempotent(tmp_path):
    # src+dest 共存(phase1 不删源后的常态):内容+身份一致→幂等,不报错、不重删。
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=_vault(tmp_path)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    execute_migration(prepare_migration(src, v, inp), v, Writer())
    rep2=execute_migration(prepare_migration(src, v, inp), v, Writer())   # 重跑
    assert not rep2.failed
    assert (src/"cjt/.git").exists() and (v/"shared/plugins/cjt/.git").exists()
    assert "160000" not in _idx(v,"shared/plugins/cjt")

def test_phase1_content_drift_refuses_zero_delete(tmp_path):
    # src 与 dest 内容/身份漂移→冲突失败、零删除。
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=_vault(tmp_path)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    execute_migration(prepare_migration(src, v, inp), v, Writer())
    # 让 dest 漂移:加一个提交,HEAD 与 src 不再一致
    d=v/"shared/plugins/cjt"; (d/"drift.txt").write_text("x\n", encoding="utf-8")
    _git(d,"add","-A"); _git(d,"commit","-qm","drift")
    import pytest
    from hub.plugin_migrate import MigrationInputError
    with pytest.raises(MigrationInputError):
        prepare_migration(src, v, inp)
    assert (src/"cjt/.git").exists() and (d/".git").exists()   # 两份都在,零删除

def test_codex_old_market_root_readable_after_phase1(tmp_path):
    # phase1 后旧源仍是合法 market-of-one 根 → cutover 前 Codex 始终能读它,不悬空。
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=_vault(tmp_path)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["codex"]\nenabled=["codex"]\n', encoding="utf-8")
    execute_migration(prepare_migration(src, v, inp), v, Writer())
    from hub.plugin_migrate import _market_ready
    assert (src/"cjt/.claude-plugin/marketplace.json").exists()
    assert _market_ready(src/"cjt", "cjt")                    # 旧市场根仍有效

def test_dry_run_moves_nothing(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)], check=True)
    _git(v,"config","user.email","t@t"); _git(v,"config","user.name","t")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    execute_migration(prepare_migration(src,v,inp), v, Writer(dry_run=True))
    assert (src/"cjt").exists() and not (v/"shared/plugins/cjt").exists()

def test_needs_author_blocks_before_move(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    (src/"cjt/.claude-plugin/marketplace.json").write_text("{}",encoding="utf-8")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)],check=True)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    rep=execute_migration(prepare_migration(src,v,inp),v,Writer())
    assert rep.failed and rep.failed[0][0]=="preflight:needs-author"
    assert (src/"cjt").exists() and not (v/"shared/plugins/cjt").exists()

def test_unmet_dependency_stops_before_action(tmp_path):
    from hub.plugin_migrate import MigrationAction, MigrationPlan
    v=tmp_path/"vault"; v.mkdir(); subprocess.run(["git","init","-q",str(v)],check=True)
    plan=MigrationPlan([MigrationAction("x:induct","induct","bad",dest="shared/plugins/x",
                                       depends_on=("x:move",))],[],[])
    rep=execute_migration(plan,v,Writer())
    assert rep.failed==[("x:induct","未满足依赖: x:move")]

def test_copy_verification_failure_keeps_source(tmp_path, monkeypatch):
    import hub.plugin_migrate as pm
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)],check=True)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    real=pm._tree_manifest; calls={"n":0}
    def mismatch(path):
        calls["n"]+=1
        return real(path) if calls["n"]==1 else [("CORRUPT","file","0")]
    monkeypatch.setattr(pm,"_tree_manifest",mismatch)
    rep=execute_migration(prepare_migration(src,v,inp),v,Writer())
    assert rep.failed and (src/"cjt").exists()
    assert not (v/"shared/plugins/cjt").exists()
