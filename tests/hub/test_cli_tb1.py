# tests/hub/test_cli_tb1.py —— CLI-AI 规范 T-B1：普通查询簇 --json 契约 + _error_code + emitter 兜底
import io
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
import pytest
from hub import cli
from hub.cli import main
from hub.backend import RemoteUnavailable
from hub.register import RegisterConflict
from hub.promote import PromoteConflict, PromoteMemoryConflict
from hub.hubconfig import ConfigConflict
from hub.memview import ViewScopeError, SharedMemoryError
from hub.memread import MemoryNotInView
from hub.vaultpaths import SharedSkillsEscape
from hub.textblock import BlockError
from hub.plugin_manifest import PluginManifestError, PluginIdentityError
from hub.plugin_ops import PluginContainmentError, PluginRepoUnavailable
from hub.vault import UnsupportedVaultVersion
from hub.plugin_cli import CliUnavailable


@pytest.fixture
def machine_out(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cli, "_MACHINE_OUT", buf)
    return buf


@pytest.fixture
def machine_err(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cli, "_MACHINE_ERR", buf)
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


def _mk_base_vault(tmp_path, host="box1") -> Path:
    v = tmp_path / "vault"
    (v / host).mkdir(parents=True)
    (v / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    return v


def _shared_skill(vault: Path, name: str) -> None:
    d = vault / "shared" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


# ---- _error_code 映射：顺序敏感 + 领域显式 + __cause__/__context__ 链 ----

def test_error_code_oserror_ordering():
    assert cli._error_code(PermissionError("p")) == "E_PERMISSION"
    assert cli._error_code(FileNotFoundError("f")) == "E_NOT_FOUND"
    assert cli._error_code(OSError("o")) == "E_IO"


def test_error_code_domain_errors():
    assert cli._error_code(MemoryNotInView("x")) == "E_NOT_FOUND"
    assert cli._error_code(ViewScopeError("x")) == "E_NOT_FOUND"
    assert cli._error_code(SharedMemoryError("x")) == "E_NOT_FOUND"
    assert cli._error_code(PromoteConflict("x")) == "E_VALIDATION"
    assert cli._error_code(PromoteMemoryConflict("x")) == "E_VALIDATION"
    assert cli._error_code(RegisterConflict("x")) == "E_VALIDATION"
    assert cli._error_code(ConfigConflict("x")) == "E_VALIDATION"
    assert cli._error_code(SharedSkillsEscape("x")) == "E_VALIDATION"
    assert cli._error_code(BlockError("x")) == "E_VALIDATION"
    assert cli._error_code(PluginManifestError("x")) == "E_VALIDATION"
    assert cli._error_code(PluginIdentityError("x")) == "E_VALIDATION"
    assert cli._error_code(PluginContainmentError("x")) == "E_VALIDATION"
    assert cli._error_code(RemoteUnavailable("x")) == "E_NETWORK"
    assert cli._error_code(CliUnavailable("x")) == "E_EXTERNAL_TOOL"
    assert cli._error_code(ValueError("x")) == "E_VALIDATION"
    assert cli._error_code(PluginRepoUnavailable("x")) == "E_NETWORK"
    assert cli._error_code(UnsupportedVaultVersion("x")) == "E_PLATFORM"
    assert cli._error_code(RuntimeError("x")) == "E_INTERNAL"


def test_error_code_tb2_domain_errors():
    from hub.collect.errors import MissingSourceError
    from hub.frontmatter import FrontmatterError
    from hub.migrate import SchemaMigrationError
    from hub.plugin_migrate import MigrationInputError
    from hub.induction import InductionError
    assert cli._error_code(MissingSourceError("x")) == "E_NOT_FOUND"
    assert cli._error_code(FrontmatterError("x")) == "E_VALIDATION"
    assert cli._error_code(SchemaMigrationError("x")) == "E_VALIDATION"
    assert cli._error_code(MigrationInputError("x")) == "E_VALIDATION"
    assert cli._error_code(InductionError("x")) == "E_VALIDATION"
    assert cli._error_code(subprocess.CalledProcessError(1, ["x"])) == "E_EXTERNAL_TOOL"


def test_error_code_cause_chain_finds_domain():
    outer = RuntimeError("外层")
    outer.__cause__ = RegisterConflict("内层冲突")
    assert cli._error_code(outer) == "E_VALIDATION"


def test_error_code_deep_cause_chain():
    inner = FileNotFoundError("底层找不到")
    mid = RuntimeError("中层")
    mid.__cause__ = inner
    outer = RuntimeError("顶层")
    outer.__cause__ = mid
    assert cli._error_code(outer) == "E_NOT_FOUND"


def test_error_code_context_chain():
    outer = RuntimeError("外层")
    outer.__context__ = PermissionError("权限不足")
    assert cli._error_code(outer) == "E_PERMISSION"


def test_error_code_domain_wins_over_cause():
    outer = PromoteConflict("显式领域错误")
    outer.__cause__ = FileNotFoundError("底层找不到")
    assert cli._error_code(outer) == "E_VALIDATION"


def test_error_code_internal_cause_falls_to_internal():
    outer = RuntimeError("外层")
    outer.__cause__ = RuntimeError("内层")
    assert cli._error_code(outer) == "E_INTERNAL"


# ---- emitter：json 序列化归一化 + 失败兜底 ----

def test_json_default_path_bytes_datetime():
    assert cli._json_default(Path("x")) == "x"
    assert cli._json_default(b"abc") == "abc"
    assert cli._json_default(b"\xff\xfe") == repr(b"\xff\xfe")
    assert cli._json_default(datetime(2026, 8, 19, 10, 30)) == "2026-08-19T10:30:00"
    assert cli._json_default(date(2026, 8, 19)) == "2026-08-19"
    with pytest.raises(TypeError):
        cli._json_default(object())


def test_emit_result_unserializable_fallback(machine_out, machine_err):
    class Bad:
        pass
    ok = cli._emit_result({"bad": Bad()})
    assert ok is False
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["data"] is None
    assert err["error"]["code"] == "E_INTERNAL"


def test_emit_error_unserializable_details_fallback(machine_out, machine_err):
    class Bad:
        pass
    ok = cli._emit_error("E_INTERNAL", "x", details={"bad": Bad()})
    assert ok is False
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_INTERNAL"


def test_emit_result_path_in_data_serialized(machine_out):
    ok = cli._emit_result({"dest": Path("a/b")})
    assert ok is True
    data = json.loads(machine_out.getvalue())["data"]
    assert isinstance(data["dest"], str)


# ---- status --json ----

def test_status_json_no_device(tmp_path, machine_out, machine_err):
    v = _mk_base_vault(tmp_path)
    _init_git(v)
    rc = main(["status", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert isinstance(data["git"], str)
    assert data["skill_links"] == []
    assert data["opencode_links"] == []
    assert data["gitlinks"] == []
    assert "check" not in data
    assert "health" not in data


def test_status_json_with_device(tmp_path, machine_out, machine_err):
    v = _mk_base_vault(tmp_path)
    _init_git(v)
    (v / "box1" / "device.toml").write_text(
        _dev_toml(v, CLAUDE_HOME=(tmp_path / ".claude").as_posix()), encoding="utf-8")
    _shared_skill(v, "alpha")
    rc = main(["status", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["skill_links"]
    states = {row[0] for row in data["skill_links"]}
    assert "missing" in states
    assert any("alpha" in row[1] for row in data["skill_links"])
    assert data["opencode_links"] == []
    assert data["gitlinks"] == []


def test_status_json_check_unhealthy(tmp_path, machine_out, machine_err):
    v = _mk_base_vault(tmp_path)
    _init_git(v)
    (v / "box1" / "device.toml").write_text(
        _dev_toml(v, CLAUDE_HOME=(tmp_path / ".claude").as_posix()), encoding="utf-8")
    _shared_skill(v, "alpha")
    rc = main(["status", "--vault", str(v), "--host", "box1", "--check", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"
    assert "不健康" in err["error"]["message"]
    assert err["error"]["suggestion"]
    assert err["error"]["details"]


def test_status_json_check_no_device(tmp_path, machine_out, machine_err):
    v = _mk_base_vault(tmp_path)
    _init_git(v)
    rc = main(["status", "--vault", str(v), "--host", "box1", "--check", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_NOT_FOUND"
    assert err["error"]["suggestion"]


def test_status_json_shared_escape(tmp_path, machine_out, machine_err):
    from hub.fslink import make_dir_link
    v = _mk_base_vault(tmp_path)
    _init_git(v)
    (v / "box1" / "device.toml").write_text(
        _dev_toml(v, CLAUDE_HOME=(tmp_path / ".claude").as_posix()), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (v / "shared").mkdir()
    make_dir_link(outside, v / "shared" / "skills")
    rc = main(["status", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


# ---- register --json ----

def _mk_register_vault(tmp_path) -> Path:
    v = _mk_base_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(
        _dev_toml(v, CLAUDE_HOME=(tmp_path / "cl").as_posix(),
                  AGENTS_HOME=(tmp_path / "ag").as_posix()), encoding="utf-8")
    _shared_skill(v, "alpha")
    return v


def test_register_json_success(tmp_path, machine_out, machine_err):
    v = _mk_register_vault(tmp_path)
    rc = main(["register", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue())
    assert env["ok"] is True
    data = env["data"]
    assert data["dry_run"] is False
    assert data["skills_linked"] >= 1
    assert data["opencode_links"] == 0
    assert data["plugin"] == {"succeeded": 0, "skipped": 0, "failed": 0}
    assert env["meta"]["warnings"] == []


def test_register_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_register_vault(tmp_path)
    rc = main(["register", "--vault", str(v), "--host", "box1", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert not (tmp_path / "cl" / "skills" / "alpha").exists()
    assert machine_err.getvalue() == b""


def test_register_json_conflict(tmp_path, machine_out, machine_err):
    v = _mk_register_vault(tmp_path)
    user_dir = tmp_path / "cl" / "skills" / "alpha"
    user_dir.mkdir(parents=True)
    (user_dir / "own.txt").write_text("用户自己的东西\n", encoding="utf-8")
    rc = main(["register", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"
    assert "alpha" in err["error"]["message"]


# ---- refresh --json ----

def _mk_refresh_vault(tmp_path) -> Path:
    v = _mk_base_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(_dev_toml(v), encoding="utf-8")
    (v / "shared" / "memory").mkdir(parents=True)
    return v


def test_refresh_json_success(tmp_path, machine_out, machine_err):
    v = _mk_refresh_vault(tmp_path)
    rc = main(["refresh", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["written"] >= 3
    assert data["warnings"] == []
    assert data["plugin"] == {"succeeded": 0, "skipped": 0, "failed": 0}


def test_refresh_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_refresh_vault(tmp_path)
    rc = main(["refresh", "--vault", str(v), "--host", "box1", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert machine_err.getvalue() == b""


def test_refresh_json_no_device(tmp_path, machine_out, machine_err):
    v = _mk_base_vault(tmp_path)
    rc = main(["refresh", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


# ---- promote --json ----

def _mk_promote_vault(tmp_path) -> Path:
    v = _mk_base_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(_dev_toml(v), encoding="utf-8")
    d = v / "box1" / "claude" / "skills" / "alpha"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# a\n", encoding="utf-8")
    return v


def test_promote_json_success(tmp_path, machine_out, machine_err):
    v = _mk_promote_vault(tmp_path)
    rc = main(["promote", "--vault", str(v), "--host", "box1",
               "--tool", "claude", "--name", "alpha", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["dest"].replace("\\", "/").endswith("shared/skills/alpha")


def test_promote_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_promote_vault(tmp_path)
    rc = main(["promote", "--vault", str(v), "--host", "box1",
               "--tool", "claude", "--name", "alpha", "--json", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert not (v / "shared" / "skills" / "alpha").exists()
    assert machine_err.getvalue() == b""


def test_promote_json_missing(tmp_path, machine_out, machine_err):
    v = _mk_promote_vault(tmp_path)
    rc = main(["promote", "--vault", str(v), "--host", "box1",
               "--tool", "claude", "--name", "nope", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


def test_promote_json_conflict(tmp_path, machine_out, machine_err):
    v = _mk_promote_vault(tmp_path)
    d = v / "shared" / "skills" / "alpha"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# 不同版本\n", encoding="utf-8")
    rc = main(["promote", "--vault", str(v), "--host", "box1",
               "--tool", "claude", "--name", "alpha", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


# ---- promote-memory --json + rc2 收敛 ----

def _mk_promote_mem_vault(tmp_path) -> Path:
    v = _mk_base_vault(tmp_path)
    (v / "box1" / "device.toml").write_text(_dev_toml(v), encoding="utf-8")
    d = v / "box1" / "claude" / "memory"
    d.mkdir(parents=True)
    for n in ("a", "b"):
        (d / f"{n}.md").write_text(
            f"---\nname: {n}\ndescription: x\nmetadata:\n  type: reference\n"
            f"  scope: [global]\n---\n\nbody\n",
            encoding="utf-8", newline="\n")
    return v


def test_promote_memory_json_usage_error_rc2(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1", "--json"])
    assert rc == 2
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"
    assert "二选一" in err["error"]["message"]
    assert err["error"]["suggestion"]


def test_promote_memory_json_usage_error_both_rc2(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1",
               "--json", "--name", "a", "--all"])
    assert rc == 2
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


def test_promote_memory_json_success_single(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1",
               "--json", "--name", "a"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["name"] == "a"
    assert data["all"] is False
    assert data["count"] == 1
    assert data["dest"].replace("\\", "/").endswith("shared/memory/a.md")
    assert (v / "shared" / "memory" / "a.md").exists()


def test_promote_memory_json_success_all(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1",
               "--json", "--all"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is False
    assert data["name"] is None
    assert data["all"] is True
    assert data["count"] == 2
    assert "dest" not in data


def test_promote_memory_json_dry_run(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1",
               "--json", "--name", "a", "--dry-run"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert data["dry_run"] is True
    assert not (v / "shared" / "memory" / "a.md").exists()
    assert machine_err.getvalue() == b""


def test_promote_memory_json_missing(tmp_path, machine_out, machine_err):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1",
               "--json", "--name", "nope"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


def test_promote_memory_human_usage_error_rc2(tmp_path, capsys):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1"])
    assert rc == 2
    assert "--name 与 --all 必须二选一" in capsys.readouterr().out


def test_promote_memory_human_success_unchanged(tmp_path, capsys):
    v = _mk_promote_mem_vault(tmp_path)
    rc = main(["promote-memory", "--vault", str(v), "--host", "box1", "--name", "a"])
    assert rc == 0
    assert "已提升 → " in capsys.readouterr().out
