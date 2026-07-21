import json, os, subprocess
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.induction import (prepare_induction, execute_induction, recover_pending, InductionError)

def _git(cwd, *a): subprocess.run(["git","-C",str(cwd),*a], check=True, capture_output=True)
def _parent(tmp):
    p = tmp/"parent"; (p/"shared/plugins").mkdir(parents=True)
    subprocess.run(["git","init","-q",str(p)], check=True)
    _git(p,"config","user.email","t@t"); _git(p,"config","user.name","t"); return p
def _nested(parent, name, ver="0.1.0"):
    d = parent/"shared/plugins"/name; d.mkdir(parents=True)
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","n@n"); _git(d,"config","user.name","n")
    (d/"code.txt").write_text("v1\n", encoding="utf-8")
    (d/"plugin.json").write_text(json.dumps({"version":ver}), encoding="utf-8")
    _git(d,"add","-A"); _git(d,"commit","-qm","nested"); return d
def _idx(p, rel): return subprocess.run(["git","-C",str(p),"ls-files","-s",rel],
                                        capture_output=True,text=True).stdout
def _gitdir(p): return subprocess.run(["git","-C",str(p),"rev-parse","--git-dir"],
                                      capture_output=True,text=True).stdout.strip()

def test_induct_tracks_files_not_gitlink(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer())
    ls = _idx(p,"shared/plugins/foo")
    assert "160000" not in ls and "code.txt" in ls
    assert (p/"shared/plugins/foo/.git").exists()
    # 日志已清（admin dir 下无残留 journal）
    assert not (Path(p/_gitdir(p))/"hub-induction"/"journal.json").exists()

def test_nested_repo_still_alive(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer())
    r = subprocess.run(["git","-C",str(p/"shared/plugins/foo"),"log","--oneline"],
                       capture_output=True,text=True)
    assert r.returncode == 0 and "nested" in r.stdout

def test_dry_run_moves_nothing(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer(dry_run=True))
    assert (p/"shared/plugins/foo/.git").is_dir()          # 没被移动
    assert "160000" not in _idx(p,"shared/plugins/foo") and _idx(p,"shared/plugins/foo") == ""  # 没 add

def test_recover_pending(tmp_path):
    p = _parent(tmp_path); d = _nested(p,"foo")
    admin = Path(p/_gitdir(p))/"hub-induction"; (admin/"stash").mkdir(parents=True)
    os.replace(str(d/".git"), str(admin/"stash"/".git"))
    (admin/"journal.json").write_text(json.dumps(
        {"rel_target":"shared/plugins/foo","stash_git":str(admin/"stash"/".git")}), encoding="utf-8")
    done = recover_pending(p, Writer())
    assert "shared/plugins/foo" in done and (d/".git").exists()
    assert not (admin/"journal.json").exists()

def test_containment_escape_refused(tmp_path):
    p = _parent(tmp_path)
    with pytest.raises(InductionError):
        prepare_induction(p, "../outside")
