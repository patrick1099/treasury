import json
from hub.writer import Writer
from hub.plugin_cli import CliCommand, CliResult
from hub.plugin_ops import PluginAction, PluginPlan, execute_plugin_plan
from hub.plugin_state import read_state

ok = lambda argv: CliResult(0,"ok","")
def fail_add(argv): return CliResult(1,"","boom") if argv[1:3]==["plugin","add"] else CliResult(0,"ok","")

def _enable_plan(confirm):
    # 一个 enable 动作 + 依赖它的退役动作；enable 声明 confirm_enabled 幂等兜底
    return PluginPlan([
        PluginAction("en","claude 启用 cjt@cjt", confirm_enabled=confirm,
            cli=CliCommand("claude",["plugin","enable","cjt@cjt","--scope","user"])),
        PluginAction("retire","claude 退役旧身份", depends_on=("en",),
            cli=CliCommand("claude",["plugin","uninstall","cjt@xu-local","--scope","user"])),
    ], [])

def _enable_runner(actually_enabled):
    # enable 命令返回非零(模拟 already-enabled)；plugin list 反映平台真实 enabled 状态
    def r(argv):
        if argv[1:3]==["plugin","enable"]:
            return CliResult(1,"",'Plugin "cjt@cjt" is already enabled at user scope')
        if " ".join(argv)=="claude plugin list --json":
            return CliResult(0, json.dumps(
                [{"id":"cjt@cjt","version":"0.1.0","enabled":actually_enabled,"installPath":"x"}]), "")
        return CliResult(0,"ok","")
    return r

def test_enable_already_enabled_confirmed_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    rep = execute_plugin_plan(_enable_plan("cjt@cjt"), Writer(), runner=_enable_runner(actually_enabled=True))
    # enable 非零但平台确认已 enabled → 按成功处理，下游退役继续
    assert "en" in rep.succeeded and "retire" in rep.succeeded

def test_enable_real_failure_still_blocks_dependents(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    rep = execute_plugin_plan(_enable_plan("cjt@cjt"), Writer(), runner=_enable_runner(actually_enabled=False))
    # enable 非零且平台确认仍未 enabled → 真失败，退役被阻断
    assert "en" in [f[0] for f in rep.failed] and "retire" in rep.skipped

def test_nonzero_without_confirm_marker_is_failure(tmp_path, monkeypatch):
    # 没有 confirm_enabled 的动作：非零一律失败，绝不无条件吞掉
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    plan = PluginPlan([PluginAction("en","claude 启用 cjt@cjt",
        cli=CliCommand("claude",["plugin","enable","cjt@cjt","--scope","user"]))], [])
    rep = execute_plugin_plan(plan, Writer(), runner=_enable_runner(actually_enabled=True))
    assert "en" in [f[0] for f in rep.failed]

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
