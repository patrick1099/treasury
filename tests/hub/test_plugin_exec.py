from hub.writer import Writer
from hub.plugin_cli import CliCommand, CliResult
from hub.plugin_ops import PluginAction, PluginPlan, execute_plugin_plan
from hub.plugin_state import read_state

ok = lambda argv: CliResult(0,"ok","")
def fail_add(argv): return CliResult(1,"","boom") if argv[1:3]==["plugin","add"] else CliResult(0,"ok","")

def _chain():
    return PluginPlan([
        PluginAction("add","codex plugin add cjt@cjt", cli=CliCommand("codex",["plugin","add","cjt@cjt"])),
        PluginAction("state","ledger cjt/codex", depends_on=("add",), state=("cjt","codex","sha","0.1.0")),
    ], [])

def test_dryrun_zero_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    execute_plugin_plan(_chain(), Writer(dry_run=True), runner=ok)
    assert "cjt@cjt" in capsys.readouterr().out and read_state()=={}

def test_dep_blocks_state_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    rep = execute_plugin_plan(_chain(), Writer(), runner=fail_add)
    assert ("add" in [f[0] for f in rep.failed]) and "state" in rep.skipped
    assert read_state()=={}                          # 前置失败→不写台账

def test_success_writes_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    execute_plugin_plan(_chain(), Writer(), runner=ok)
    assert read_state()["cjt"]["codex"].version=="0.1.0"

def test_state_write_failure_reported_not_raised(tmp_path, monkeypatch):
    import hub.plugin_ops as ops
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    monkeypatch.setattr(ops,"record",lambda *a,**k: (_ for _ in ()).throw(OSError("disk full")))
    rep=execute_plugin_plan(_chain(),Writer(),runner=ok)
    assert "add" in rep.succeeded
    assert rep.failed==[("state","disk full")]

def test_unknown_or_not_yet_satisfied_dependency_skips():
    plan=PluginPlan([PluginAction("danger","must not run",depends_on=("missing",),
                                  cli=CliCommand("codex",["plugin","remove","x@x"]))],[])
    rep=execute_plugin_plan(plan,Writer(),runner=ok)
    assert rep.skipped==["danger"] and not rep.succeeded
