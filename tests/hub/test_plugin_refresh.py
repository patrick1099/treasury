import json, os, subprocess
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.plugin_cli import CliResult
from hub.plugin_ops import (prepare_plugin_refresh, PluginBumpNeeded, PluginRepoDirty,
                            PluginRepoUnavailable)
from hub.plugin_state import record

def _git(cwd,*a): subprocess.run(["git","-C",str(cwd),*a], check=True, capture_output=True)
def _setup(tmp, name, ver, platforms):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    d = tmp/"shared/plugins"/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}), encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":name,"version":ver}), encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t")
    _git(d,"add","-A"); _git(d,"commit","-qm","c")
    (tmp/"shared/plugins/manifest.toml").write_text(f'[{name}]\nplatforms={json.dumps(platforms)}\n', encoding="utf-8")
    (tmp/"box").mkdir(); (tmp/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box"), d
def _head(d): return subprocess.run(["git","-C",str(d),"rev-parse","HEAD"], capture_output=True, text=True).stdout.strip()
def _bump(d, ver):
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":d.name,"version":ver}), encoding="utf-8")
    _git(d,"add","-A"); _git(d,"commit","-qm","bump")
def _runner(codex=None, claude=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="codex plugin list --json": return CliResult(0, json.dumps({"installed":codex or [],"available":[]}),"")
        if s=="claude plugin list --json": return CliResult(0, json.dumps(claude or []),"")
        if "codex" in s and s.endswith("marketplace list --json"): return CliResult(0, json.dumps({"marketplaces":[]}),"")
        if s.endswith("marketplace list --json"): return CliResult(0, "[]","")
        return CliResult(0,"ok","")
    return r
def _ids(p): return [a.id for a in p.actions]
_CI = [{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,"marketplaceName":"cjt","source":{"path":"x"}}]

def test_not_installed_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,_ = _setup(tmp_path,"cjt","0.2.0",["codex"])
    assert prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=[])).actions == []

def test_no_baseline_rereads_then_records(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,_ = _setup(tmp_path,"cjt","0.1.0",["codex"])
    plan = prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))
    assert _ids(plan) == ["cjt:codex:reinstall", "cjt:codex:state"]
    state = plan.actions[-1]
    assert state.depends_on == ("cjt:codex:reinstall",)

def test_nongit_source_refused(tmp_path, monkeypatch):
    import shutil, stat
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    def _onexc(func, p, exc):          # git 在 Windows 上把 .git/objects 下的文件设为只读
        os.chmod(p, stat.S_IWRITE); func(p)
    shutil.rmtree(d/".git", onexc=_onexc)
    with pytest.raises(PluginRepoUnavailable):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_bump_needed(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer())
    (d/"x.txt").write_text("c\n",encoding="utf-8"); _git(d,"add","-A"); _git(d,"commit","-qm","c2")  # sha 变 version 没变
    with pytest.raises(PluginBumpNeeded):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_dirty_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer())
    (d/"x.txt").write_text("dirty\n",encoding="utf-8")
    with pytest.raises(PluginRepoDirty):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_codex_reinstall_on_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer()); _bump(d,"0.2.0")
    ids=_ids(prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI)))
    assert "cjt:codex:reinstall" in ids and "cjt:codex:state" in ids

def test_claude_disabled_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["claude"])
    record("cjt","claude",_head(d),"0.1.0", Writer()); _bump(d,"0.2.0")
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":False,"installPath":"x"}]
    ids=_ids(prepare_plugin_refresh(tmp_path, dev, runner=_runner(claude=ci)))
    assert ids[:3]==["cjt:claude:uninstall","cjt:claude:install","cjt:claude:redisable"]
    assert "cjt:claude:state" in ids
