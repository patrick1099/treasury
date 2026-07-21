import json, subprocess
from pathlib import Path
from hub.writer import Writer
from hub.plugin_cli import CliResult
from hub.plugin_ops import plugin_health
from hub.plugin_state import record

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _base(tmp): (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8"); (tmp/"box").mkdir()
def _entry(tmp, name, git=False):
    d=tmp/"shared/plugins"/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}), encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":name,"version":"0.1.0"}), encoding="utf-8")
    if git:
        subprocess.run(["git","init","-q",str(d)], check=True)
        _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")
    return str(d.resolve())
def _write(tmp, manifest, dev_plugins):
    (tmp/"shared/plugins").mkdir(parents=True, exist_ok=True)
    (tmp/"shared/plugins/manifest.toml").write_text(manifest, encoding="utf-8")
    (tmp/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dev_plugins, encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box")
def _runner(mkts=None, inst=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="claude plugin marketplace list --json": return CliResult(0, json.dumps(mkts or []),"")
        if s=="claude plugin list --json": return CliResult(0, json.dumps(inst or []),"")
        if s=="codex plugin marketplace list --json": return CliResult(0, json.dumps({"marketplaces":[]}),"")
        if s=="codex plugin list --json": return CliResult(0, json.dumps({"installed":[],"available":[]}),"")
        return CliResult(0,"ok","")
    return r
def _one(hs,name,tool): return [h.state for h in hs if h.name==name and h.tool==tool][0]
MF='[cjt]\nplatforms=["claude"]\n'

def test_missing_source(tmp_path):
    _base(tmp_path)
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner()),"cjt","claude")=="missing-source"

def test_unregistered(tmp_path):
    _base(tmp_path); _entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[])),"cjt","claude")=="unregistered"

def test_enable_drift_desired_not_installed(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],inst=[])),"cjt","claude")=="enable-drift"

def test_outside_not_installed_ok(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=[]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],inst=[])),"cjt","claude")=="ok"

def _ci(enabled=True):
    return [{"id":"cjt@cjt","version":"0.1.0","enabled":enabled,"installPath":"x"}]

def test_source_moved_beats_enable_drift(tmp_path):
    _base(tmp_path); _entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":"C:/old"}],inst=[])),"cjt","claude")
    assert state=="source-moved"                 # 优先于"期望启用但未安装"

def test_dirty_beats_no_baseline(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt",git=True)
    Path(src,"dirty.txt").write_text("x\n", encoding="utf-8")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":src}],inst=_ci())),"cjt","claude")
    assert state=="dirty"

def test_no_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=_entry(tmp_path,"cjt",git=True)
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":src}],inst=_ci())),"cjt","claude")
    assert state=="no-baseline"

def test_stale_when_sha_changed_without_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=Path(_entry(tmp_path,"cjt",git=True))
    head=subprocess.run(["git","-C",str(src),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0",Writer())
    (src/"code.txt").write_text("changed\n",encoding="utf-8")
    _git(src,"add","-A"); _git(src,"commit","-qm","change-without-bump")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":str(src)}],inst=_ci())),"cjt","claude")
    assert state=="stale"

def test_remote_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=Path(_entry(tmp_path,"cjt",git=True))
    _git(src,"remote","add","origin","git@actual/repo.git")
    head=subprocess.run(["git","-C",str(src),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0",Writer())
    manifest='[cjt]\nplatforms=["claude"]\n[cjt.repository]\nremote="git@expected/repo.git"\n'
    dev=_write(tmp_path, manifest, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":str(src)}],inst=_ci())),"cjt","claude")
    assert state=="drift"

def test_drift_check_missing_source_when_not_installed_and_no_git(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=_entry(tmp_path,"cjt")   # git=False：无 .git，非嵌套 git 仓
    manifest='[cjt]\nplatforms=["claude"]\n[cjt.repository]\nremote="git@expected/repo.git"\nsha="deadbeef"\n'
    dev=_write(tmp_path, manifest, '[plugins.claude]\nenabled=[]\n')
    hs=plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],inst=[]))
    assert _one(hs,"cjt","claude")=="missing-source"

def test_ok_installed_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=_entry(tmp_path,"cjt", git=True)
    head=subprocess.run(["git","-C",src,"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0", Writer())
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    hs=plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],
        inst=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"x"}]))
    assert _one(hs,"cjt","claude")=="ok"
