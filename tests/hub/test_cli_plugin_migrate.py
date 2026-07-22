from hub import cli
from hub.plugin_migrate import MigrationPlan, MigrationReport
from hub.plugin_ops import PluginPlan, PluginRunReport

def test_migrate_plugins_dryrun_uses_writer_gate(tmp_path, monkeypatch):
    captured={}
    monkeypatch.setattr(cli,"prepare_migration",lambda *a,**k:MigrationPlan([],[],[]))
    def execute(plan,vault,w):
        captured["dry"]=w.dry_run
        return MigrationReport()
    monkeypatch.setattr(cli,"execute_migration",execute)
    rc=cli.main(["migrate-plugins","--vault",str(tmp_path),"--src",str(tmp_path/"old"),
                 "--input",str(tmp_path/"m.toml"),"--dry-run"])
    assert rc==0 and captured=={"dry":True}

def test_migrate_plugins_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(cli,"recover_pending",lambda *a,**k:[])
    monkeypatch.setattr(cli,"prepare_migration",lambda *a,**k:MigrationPlan([],[],[]))
    monkeypatch.setattr(cli,"execute_migration",
        lambda *a,**k:MigrationReport(failed=[("move","boom")]))
    rc=cli.main(["migrate-plugins","--vault",str(tmp_path),"--src",str(tmp_path/"old"),
                 "--input",str(tmp_path/"m.toml")])
    assert rc==1

def test_cutover_dryrun_uses_plugin_executor(tmp_path, monkeypatch):
    (tmp_path/"box").mkdir(); (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n',encoding="utf-8")
    monkeypatch.setattr(cli,"prepare_cutover",lambda *a,**k:PluginPlan([],[]))
    seen={}
    def execute(plan,w):
        seen["dry"]=w.dry_run
        return PluginRunReport()
    monkeypatch.setattr(cli,"execute_plugin_plan",execute)
    rc=cli.main(["cutover-plugins","--vault",str(tmp_path),"--host","box","--dry-run"])
    assert rc==0 and seen=={"dry":True}
