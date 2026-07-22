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

def test_execute_moves_inducts(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)], check=True)
    _git(v,"config","user.email","t@t"); _git(v,"config","user.name","t")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    plan=prepare_migration(src, v, inp)
    rep=execute_migration(plan, v, Writer())
    assert not rep.failed
    assert not (src/"cjt").exists()                          # 源已删
    assert (v/"shared/plugins/cjt/.git").exists()            # 嵌套仓在
    assert "160000" not in _idx(v,"shared/plugins/cjt")      # 父仓跟踪文件非 gitlink
    assert (v/"shared/plugins/manifest.toml").read_text(encoding="utf-8").strip().startswith("[cjt]")

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
