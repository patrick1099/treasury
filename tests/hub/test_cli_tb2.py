# tests/hub/test_cli_tb2.py —— CLI-AI 规范 T-B2：文件变更簇 --json 契约
import io
import json
import subprocess
from pathlib import Path
import pytest
from hub import cli
from hub import cliout
from hub.cli import main
from hub.plugin_migrate import (MigrationPlan, MigrationReport, RetirePlan, RetireReport,
                                RetireAction, MigrationInputError)
from hub.plugin_ops import PluginPlan, PluginRunReport


@pytest.fixture
def machine_out(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_OUT", buf)
    return buf


@pytest.fixture
def machine_err(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_ERR", buf)
    return buf


def _init_git(repo):
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _dev_toml(vault: Path, **paths) -> str:
    body = 'class=[]\nprojects=[]\n[paths]\n'
    body += f'VAULT="{vault.as_posix()}"\n'
    for k, v in paths.items():
        body += f'{k}="{v}"\n'
    return body


def _mk_backup_vault(tmp_path, host="box1") -> Path:
    v = tmp_path / "vault"
    (v / host).mkdir(parents=True)
    (v / "shared" / "memory").mkdir(parents=True)
    (v / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    return v


def _mem(name: str, body: str = "正文\n") -> str:
    return (f"---\nname: {name}\ndescription: d\nmetadata:\n  type: reference\n"
            f"  scope: [global]\n---\n{body}")


# ---- collect --json ----

def _mk_collect_vault(tmp_path) -> Path:
    v = _mk_backup_vault(tmp_path)
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "a.md").write_text(_mem("a"), encoding="utf-8", newline="\n")
    (v / "box1" / "device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "cl").as_posix()}"\n\n'
        f'[sources.claude]\nmemory = ["{src.as_posix()}"]\n',
        encoding="utf-8")
    return v


def test_collect_json_success(tmp_path, machine_out, machine_err):
    v = _mk_collect_vault(tmp_path)
    rc = main(["collect", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue())
    assert env["ok"] is True
    data = env["data"]
    assert data["dry_run"] is False
    assert data["memory_written"] == 1
    assert data["memory_deleted"] == 0
    assert data["skipped_sensitive"] == 0
    assert data["skills"] == {"claude": []}
    assert data["decl"] == {"claude": {"repos": 0, "enabled": 0, "dirty": 0}}
    assert data["hits"] == []


def test_collect_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_collect_vault(tmp_path)
    rc = main(["collect", "--vault", str(v), "--host", "box1", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert not (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert machine_err.getvalue() == b""


def test_collect_json_no_yes_with_delete_blocks_interaction(tmp_path, machine_out,
                                                            machine_err, monkeypatch):
    v = _mk_collect_vault(tmp_path)
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(_mem("gone"), encoding="utf-8", newline="\n")

    def no_input(*a):
        raise AssertionError("json 模式禁止交互 input()")
    monkeypatch.setattr("builtins.input", no_input)

    rc = main(["collect", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"
    assert "删掉" in err["error"]["message"]
    assert err["error"]["details"]["doomed"] == ["gone"]
    assert "yes" in err["error"]["suggestion"]
    assert stale.exists()


def test_collect_json_missing_source(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    missing = tmp_path / "gone" / "memory"
    (v / "box1" / "device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "cl").as_posix()}"\n\n'
        f'[sources.claude]\nmemory = ["{missing.as_posix()}"]\n',
        encoding="utf-8")
    rc = main(["collect", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


def test_collect_json_broken_memory(tmp_path, machine_out, machine_err):
    v = _mk_collect_vault(tmp_path)
    (v / "shared" / "memory" / "bad.md").write_text("没有 frontmatter\n", encoding="utf-8")
    rc = main(["collect", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


# ---- bootstrap --json ----

def _mk_bootstrap_vault(tmp_path) -> Path:
    v = _mk_backup_vault(tmp_path)
    loader = v / "shared" / "skills" / "hub-loader"
    loader.mkdir(parents=True)
    (loader / "SKILL.md").write_text("# loader\n", encoding="utf-8")
    (v / "box1" / "device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "cl").as_posix()}"\n',
        encoding="utf-8")
    return v


def test_bootstrap_json_success(tmp_path, machine_out, machine_err):
    v = _mk_bootstrap_vault(tmp_path)
    rc = main(["bootstrap", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["installed"] == ["claude:hub-loader"]
    assert (tmp_path / "cl" / "skills" / "hub-loader" / "SKILL.md").exists()


def test_bootstrap_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_bootstrap_vault(tmp_path)
    rc = main(["bootstrap", "--vault", str(v), "--host", "box1", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert data["installed"] == ["claude:hub-loader"]
    assert not (tmp_path / "cl" / "skills" / "hub-loader").exists()


def test_bootstrap_json_no_skills(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "cl").as_posix()}"\n',
        encoding="utf-8")
    rc = main(["bootstrap", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


# ---- migrate-schema --json ----

def test_migrate_schema_json_success(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    (v / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    rc = main(["migrate-schema", "--vault", str(v), "--host", "box1", "--to", "2", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["to"] == 2
    assert "version = 2" in (v / "vault.toml").read_text(encoding="utf-8")


def test_migrate_schema_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    (v / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    rc = main(["migrate-schema", "--vault", str(v), "--host", "box1",
               "--to", "2", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")


def test_migrate_schema_json_error(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    rc = main(["migrate-schema", "--vault", str(v), "--host", "box1", "--to", "2", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


# ---- migrate-plugins --json ----

def test_migrate_plugins_json_success(tmp_path, machine_out, machine_err, monkeypatch):
    monkeypatch.setattr(cli, "recover_pending", lambda *a, **k: [])
    monkeypatch.setattr(cli, "prepare_migration", lambda *a, **k: MigrationPlan([], ["w1"], []))
    monkeypatch.setattr(cli, "execute_migration",
                        lambda *a, **k: MigrationReport(done=["move:1"]))
    rc = main(["migrate-plugins", "--vault", str(tmp_path), "--src", str(tmp_path / "old"),
               "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["warnings"] == ["w1"]
    assert data["failed"] == []
    assert data["succeeded"] == ["move:1"]


def test_migrate_plugins_json_partial_failure(tmp_path, machine_out, machine_err, monkeypatch):
    monkeypatch.setattr(cli, "recover_pending", lambda *a, **k: [])
    monkeypatch.setattr(cli, "prepare_migration", lambda *a, **k: MigrationPlan([], [], []))
    monkeypatch.setattr(cli, "execute_migration",
                        lambda *a, **k: MigrationReport(failed=[("move", "boom")]))
    rc = main(["migrate-plugins", "--vault", str(tmp_path), "--src", str(tmp_path / "old"),
               "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_PARTIAL_FAILURE"
    assert err["error"]["details"]["failed"] == [["move", "boom"]]
    assert err["error"]["retryable"] is True
    assert err["error"]["suggestion"]


def test_migrate_plugins_json_input_error(tmp_path, machine_out, machine_err, monkeypatch):
    def boom(*a, **k):
        raise MigrationInputError("缺 platforms")
    monkeypatch.setattr(cli, "recover_pending", lambda *a, **k: [])
    monkeypatch.setattr(cli, "prepare_migration", boom)
    rc = main(["migrate-plugins", "--vault", str(tmp_path), "--src", str(tmp_path / "old"),
               "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


# ---- cutover-plugins --json ----

def _mk_cutover_vault(tmp_path) -> Path:
    v = _mk_backup_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(_dev_toml(v), encoding="utf-8")
    return v


def test_cutover_json_success(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_cutover", lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "execute_plugin_plan", lambda plan, w: PluginRunReport())
    rc = main(["cutover-plugins", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["plugin"] == {"succeeded": 0, "skipped": 0, "failed": 0}


def test_cutover_json_dry_run(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_cutover", lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "execute_plugin_plan", lambda plan, w: PluginRunReport())
    rc = main(["cutover-plugins", "--vault", str(v), "--host", "box1", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True


def test_cutover_json_partial_failure(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_cutover", lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "execute_plugin_plan",
                        lambda plan, w: PluginRunReport(failed=[("x:claude:install", "boom")]))
    rc = main(["cutover-plugins", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_PARTIAL_FAILURE"
    assert err["error"]["details"]["failed"] == [["x:claude:install", "boom"]]


# ---- retire-plugin-sources --json ----

def test_retire_json_success(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_retire",
                        lambda *a, **k: RetirePlan([RetireAction("x:retire-src", "del", "/t/x")], []))
    monkeypatch.setattr(cli, "execute_retire",
                        lambda plan, w: RetireReport(done=["x:retire-src"]))
    rc = main(["retire-plugin-sources", "--vault", str(v), "--host", "box1",
               "--src", str(tmp_path / "old"), "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["actions"] == ["/t/x"]


def test_retire_json_no_actions(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_retire", lambda *a, **k: RetirePlan([], []))
    monkeypatch.setattr(cli, "execute_retire", lambda plan, w: RetireReport())
    rc = main(["retire-plugin-sources", "--vault", str(v), "--host", "box1",
               "--src", str(tmp_path / "old"), "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["actions"] == []


def test_retire_json_blocked(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_cutover_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_retire",
                        lambda *a, **k: RetirePlan([], ["codex: 旧市场仍在"]))
    monkeypatch.setattr(cli, "execute_retire", lambda plan, w: RetireReport(blocked=list(plan.blocks)))
    rc = main(["retire-plugin-sources", "--vault", str(v), "--host", "box1",
               "--src", str(tmp_path / "old"), "--input", str(tmp_path / "m.toml"), "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"
    assert err["error"]["details"]["blocked"] == ["codex: 旧市场仍在"]
    assert err["error"]["suggestion"]


# ---- induct --json + rc2 收敛 ----

def _mk_induct_vault(tmp_path) -> Path:
    v = _mk_backup_vault(tmp_path)
    _init_git(v)
    d = v / "shared" / "plugins" / "foo"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# foo\n", encoding="utf-8")
    return v


def test_induct_json_success(tmp_path, machine_out, machine_err):
    v = _mk_induct_vault(tmp_path)
    rc = main(["induct", "--vault", str(v), "--host", "box1", "--json", "shared/plugins/foo"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["paths"] == ["shared/plugins/foo"]
    out = subprocess.run(["git", "-C", str(v), "ls-files"],
                         capture_output=True, text=True).stdout
    assert "shared/plugins/foo/SKILL.md" in out


def test_induct_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_induct_vault(tmp_path)
    rc = main(["induct", "--vault", str(v), "--host", "box1",
               "--json", "--dry-run", "shared/plugins/foo"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert data["paths"] == ["shared/plugins/foo"]
    assert machine_err.getvalue() == b""


def test_induct_json_bad_path_rc2(tmp_path, machine_out, machine_err):
    v = _mk_backup_vault(tmp_path)
    _init_git(v)
    rc = main(["induct", "--vault", str(v), "--host", "box1", "--json", "nope"])
    assert rc == 2
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert "不是金库里的目录" in err["error"]["message"]
    assert err["error"]["suggestion"]


def test_induct_human_bad_path_rc2(tmp_path, capsys):
    v = _mk_backup_vault(tmp_path)
    _init_git(v)
    rc = main(["induct", "--vault", str(v), "--host", "box1", "nope"])
    assert rc == 2
    assert "induct 停止:nope 不是金库里的目录" in capsys.readouterr().out
