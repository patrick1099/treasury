import pytest
import subprocess
from pathlib import Path
from hub import cli
from hub.plugin_ops import PluginAction, PluginPlan, PluginRunReport, PluginRepoDirty
from hub.plugin_cli import CliCommand
from hub.plugin_manifest import PluginIdentityError

def _vault(tmp):
    # 最小 v3 金库：device + 一条 shared 记忆，令 memory/skill 预检可跑
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    d=tmp/"shared/memory"; d.mkdir(parents=True)
    (d/"a.md").write_text("---\nname: a\ndescription: d\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nb\n", encoding="utf-8")
    (tmp/"box").mkdir()
    (tmp/"box"/"device.toml").write_text(
        f'class=[]\nprojects=[]\n[paths]\nCLAUDE_HOME="{(tmp/".claude").as_posix()}"\n', encoding="utf-8")
    # 简报原文没有 git init：_cmd_status 顶部无条件跑 GitBackend(vault_root).status(),
    # 非 git 目录会让 `git status --porcelain` 以 exit 128 崩溃(和 test_cli.py 里
    # 其余 status 测试全都 _init_git/_mk_backup_vault 的做法一致)。只在测试侧补上，
    # 不改产品代码、不放宽任何零写断言。
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=tmp, check=True, capture_output=True)
    return tmp

def test_register_dryrun_prints_plugin_cli_and_zero_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    plan=PluginPlan([PluginAction("a:codex:add","codex 安装 a@a", cli=CliCommand("codex",["plugin","add","a@a"]))],[])
    monkeypatch.setattr(cli, "prepare_plugin_register", lambda *a, **k: plan)
    rc=cli.main(["register","--vault",str(v),"--host","box","--dry-run"])
    out=capsys.readouterr().out
    assert rc==0 and "codex plugin add a@a" in out
    from hub.memwire import hub_views_home
    assert not (hub_views_home()/"claude"/"MEMORY.md").exists()      # dry-run 零写

def test_register_plugin_preflight_failure_zero_write(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    def boom(*a, **k): raise PluginIdentityError("bad identity")
    monkeypatch.setattr(cli, "prepare_plugin_register", boom)
    rc=cli.main(["register","--vault",str(v),"--host","box"])
    from hub.memwire import hub_views_home
    assert rc==1
    assert not (hub_views_home()/"claude"/"MEMORY.md").exists()      # 插件预检失败→memory/skill 也没写

def test_register_cli_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_plugin_register", lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "execute_plugin_plan",
        lambda *a, **k: PluginRunReport(failed=[("cjt:codex:add","boom")]))
    assert cli.main(["register","--vault",str(v),"--host","box"])==1

def test_refresh_plugin_preflight_failure_preserves_old_view(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    from hub.memwire import hub_views_home
    old=hub_views_home()/"claude"/"MEMORY.md"
    old.parent.mkdir(parents=True); old.write_text("OLD\n",encoding="utf-8")
    monkeypatch.setattr(cli, "prepare_plugin_refresh",
        lambda *a, **k: (_ for _ in ()).throw(PluginRepoDirty("dirty")))
    rc=cli.main(["refresh","--vault",str(v),"--host","box"])
    assert rc==1 and old.read_text(encoding="utf-8")=="OLD\n"

def test_status_check_lists_plugin_health(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    from hub.plugin_ops import PluginHealth
    monkeypatch.setattr(cli, "plugin_health",
                        lambda *a, **k: [PluginHealth("a","codex","enable-drift")])
    rc=cli.main(["status","--vault",str(v),"--host","box","--check"])
    out=capsys.readouterr().out
    assert rc==1
    assert "[enable-drift] a@codex" in out
