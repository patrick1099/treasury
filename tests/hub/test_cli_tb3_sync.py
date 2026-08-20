# tests/hub/test_cli_tb3_sync.py —— CLI-AI 规范 T-B3：sync 簇 --json 契约
import io
import json
import subprocess
from pathlib import Path
import pytest
from hub import cli
from hub import cliout
from hub.cli import main
from hub.backend import GitBackend, RemoteUnavailable
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


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _mem(name: str, sensitive: str = "false", body: str = "正文\n") -> str:
    return (f"---\nname: {name}\ndescription: d\nmetadata:\n  type: project\n"
            f"  scope: [global]\n  portable: true\n  sensitive: {sensitive}\n---\n{body}")


def _mk_vault(root: Path, host: str):
    (root / "shared" / "memory").mkdir(parents=True)
    (root / host / "claude" / "memory").mkdir(parents=True)
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / host / "claude" / "memory" / "m1.md").write_text(_mem("m1"), encoding="utf-8")
    (root / host / "device.toml").write_text(
        f'class = ["work"]\nprojects = ["projx"]\n\n[paths]\nVAULT = "{root.as_posix()}"\n',
        encoding="utf-8")


def _mk_git_vault(tmp_path, host="h1") -> Path:
    v = tmp_path / "vault"
    _mk_vault(v, host)
    _init_git(v)
    _git(v, "add", "-A"); _git(v, "commit", "-qm", "seed")
    return v


# ---- 成功信封 ----

def test_sync_json_success(tmp_path, machine_out, machine_err):
    v = _mk_git_vault(tmp_path)
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue())
    assert env["ok"] is True
    data = env["data"]
    assert data["message"] == "chore(hub): sync"
    assert data["committed"] is True
    assert data["refreshed"] is False
    assert data["git_clean"] is True
    assert GitBackend(v).status().strip() == ""


def test_sync_json_no_changes_committed_false(tmp_path, machine_out, machine_err):
    v = _mk_git_vault(tmp_path)
    assert main(["sync", "--vault", str(v), "--host", "h1"]) == 0
    machine_out.seek(0); machine_out.truncate(); machine_err.seek(0); machine_err.truncate()
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["committed"] is False
    assert data["git_clean"] is True
    assert machine_err.getvalue() == b""


# ---- acquire 失败：E_NETWORK ----

def test_sync_json_acquire_network_error(tmp_path, machine_out, machine_err, monkeypatch):
    class _B:
        def __init__(self, *a): pass
        def acquire(self): raise RemoteUnavailable("git pull 失败:\n网络断了")
        def status(self): return ""
        def publish(self, *a): pass
    monkeypatch.setattr(cli, "GitBackend", _B)
    rc = main(["sync", "--vault", str(tmp_path), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_NETWORK"
    assert err["error"]["retryable"] is True
    assert "网络" in err["error"]["suggestion"]


def test_sync_human_acquire_network_returns_1(tmp_path, monkeypatch, capsys):
    class _B:
        def __init__(self, *a): pass
        def acquire(self): raise RemoteUnavailable("git pull 失败:\n网络断了")
        def status(self): return ""
        def publish(self, *a): pass
    monkeypatch.setattr(cli, "GitBackend", _B)
    rc = main(["sync", "--vault", str(tmp_path), "--host", "h1"])
    assert rc == 1
    assert "够不着远端" in capsys.readouterr().out


# ---- acquire 失败：E_VALIDATION(冲突) ----

def test_sync_json_conflict(tmp_path, machine_out, machine_err):
    remote = tmp_path / "remote"; _mk_vault(remote, "h1"); _init_git(remote)
    _git(remote, "add", "-A"); _git(remote, "commit", "-qm", "seed")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    (remote / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _git(remote, "commit", "-qam", "remote change")
    (clone / "vault.toml").write_text("version = 3\n", encoding="utf-8")
    _git(clone, "commit", "-qam", "local change")
    rc = main(["sync", "--vault", str(clone), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert err["error"]["details"]["conflicted"] == ["vault.toml"]
    assert "手工解决冲突" in err["error"]["suggestion"]


# ---- lint 失败：E_VALIDATION ----

def test_sync_json_lint_failure(tmp_path, machine_out, machine_err):
    v = _mk_git_vault(tmp_path)
    (v / "h1" / "claude" / "memory" / "sec.md").write_text(
        _mem("sec", sensitive="true", body="密"), encoding="utf-8")
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert any("sec" in x for x in err["error"]["details"]["errors"])
    assert not (v / "MEMORY.md").exists()


# ---- publish 失败：GitlinkTracked → E_VALIDATION ----

def test_sync_json_gitlink_blocked(tmp_path, machine_out, machine_err):
    v = _mk_git_vault(tmp_path)
    nested = v / "shared" / "plugins" / "foo"
    nested.mkdir(parents=True)
    _init_git(nested)
    (nested / "SKILL.md").write_text("# foo\n", encoding="utf-8")
    _git(nested, "add", "-A"); _git(nested, "commit", "-qm", "seed")
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert err["error"]["details"]["paths"] == ["shared/plugins/foo"]
    assert "induct" in err["error"]["suggestion"]


# ---- publish 失败：ChatsTracked → E_VALIDATION ----

def test_sync_json_chats_blocked(tmp_path, machine_out, machine_err):
    v = _mk_git_vault(tmp_path)
    chats = v / "h1" / "claude" / "chats" / "sessions" / "s1.jsonl"
    chats.parent.mkdir(parents=True)
    chats.write_text("secret cleartext\n", encoding="utf-8")
    _git(v, "add", "-f", "h1/claude/chats/sessions/s1.jsonl")
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert err["error"]["details"]["paths"] == ["h1/claude/chats/sessions/s1.jsonl"]
    assert "git rm --cached" in err["error"]["suggestion"]


# ---- publish 失败：RemoteUnavailable(push) → E_PARTIAL_FAILURE ----

def test_sync_json_push_failure_partial(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_git_vault(tmp_path)
    real_publish = cli.GitBackend.publish

    def fake_publish(self, message):
        real_publish(self, message)
        raise RemoteUnavailable("git push 失败:\n认证失败")
    monkeypatch.setattr(cli.GitBackend, "publish", fake_publish)
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_PARTIAL_FAILURE"
    assert err["error"]["retryable"] is True
    assert err["error"]["details"]["state_preserved"] is True
    assert GitBackend(v).status().strip() == ""


# ---- --refresh json 模式：stdout 只能有一个信封 ----

def test_sync_json_refresh_single_envelope(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_git_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_memory_views",
                        lambda *a, **k: (["v.md"], ["warn1"], None))
    monkeypatch.setattr(cli, "prepare_plugin_refresh",
                        lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "commit_memory_views", lambda *a, **k: None)
    monkeypatch.setattr(cli, "execute_plugin_plan",
                        lambda plan, w: PluginRunReport())
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json", "--refresh"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue())
    assert env["ok"] is True
    data = env["data"]
    assert data["refreshed"] is True
    assert data["written"] == 1
    assert data["warnings"] == ["warn1"]
    assert data["plugin"] == {"succeeded": 0, "skipped": 0, "failed": 0}
    assert data["committed"] is True
    assert data["git_clean"] is True


def test_sync_json_refresh_failure_emits_failure(tmp_path, machine_out, machine_err,
                                                 monkeypatch):
    v = _mk_git_vault(tmp_path)

    def boom(*a, **k):
        raise FileNotFoundError("device.toml 丢失")
    monkeypatch.setattr(cli, "prepare_memory_views", boom)
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json", "--refresh"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_NOT_FOUND"


def test_sync_json_refresh_partial_failure(tmp_path, machine_out, machine_err, monkeypatch):
    v = _mk_git_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_memory_views",
                        lambda *a, **k: (["v.md"], [], None))
    monkeypatch.setattr(cli, "prepare_plugin_refresh",
                        lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "commit_memory_views", lambda *a, **k: None)
    monkeypatch.setattr(cli, "execute_plugin_plan",
                        lambda plan, w: PluginRunReport(failed=[("plug", "boom")]))
    rc = main(["sync", "--vault", str(v), "--host", "h1", "--json", "--refresh"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_PARTIAL_FAILURE"
    assert err["error"]["retryable"] is True
