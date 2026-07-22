import json, subprocess
from pathlib import Path
import pytest
from hub.plugin_migrate import prepare_migration, MigrationInputError

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _repo(src_dir, name, market=True):
    d=src_dir/name; d.mkdir(parents=True)
    if market:
        (d/".claude-plugin").mkdir()
        (d/".claude-plugin/marketplace.json").write_text(json.dumps(
            {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
        (d/".claude-plugin/plugin.json").write_text(
            json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    (d/"code.txt").write_text("v\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")

def test_prepare_is_pure(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt"); _repo(src,"tn", market=False)
    (tmp_path/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude","codex"]\nenabled=["claude","codex"]\n'
        '[tn]\nplatforms=["claude"]\nenabled=[]\n', encoding="utf-8")
    plan=prepare_migration(src, tmp_path, inp)
    kinds=[(a.kind,a.id) for a in plan.actions]
    assert ("move","cjt:move") in kinds and ("induct","cjt:induct") in kinds
    assert any(a.kind=="write" and "manifest" in a.id for a in plan.actions)
    assert "tn" in plan.needs_author                       # 缺 market-of-one → 标注
    # 纯：源仍在、目标未建
    assert (src/"cjt/.git").exists() and not (tmp_path/"shared/plugins/cjt").exists()
    # induct 依赖 move
    ind=[a for a in plan.actions if a.id=="cjt:induct"][0]
    assert "cjt:move" in ind.depends_on

def test_missing_platforms_raises(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nenabled=[]\n', encoding="utf-8")
    with pytest.raises(MigrationInputError):
        prepare_migration(src, tmp_path, inp)

def test_enabled_must_be_subset_of_platforms(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude"]\nenabled=["codex"]\n',encoding="utf-8")
    with pytest.raises(MigrationInputError):
        prepare_migration(src,tmp_path,inp)

def test_prepare_rerun_accepts_repo_already_moved(tmp_path):
    src=tmp_path/"plugins-dev"; src.mkdir()
    subprocess.run(["git","init","-q",str(tmp_path)],check=True)
    _repo(tmp_path/"shared/plugins","cjt")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    plan=prepare_migration(src,tmp_path,inp)
    assert not any(a.id=="cjt:move" for a in plan.actions)
    assert any(a.id=="cjt:induct" for a in plan.actions)  # move 已完成但父仓未 add → 重跑从 induct 收敛
    assert any(a.id=="write:manifest" for a in plan.actions)
