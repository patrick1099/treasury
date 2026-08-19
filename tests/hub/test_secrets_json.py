# tests/hub/test_secrets_json.py —— secrets exec/run 的 --json 契约（T-C 阶段）
import io
import json
import sys
from pathlib import Path
import pytest

from hub import cli, secrets_cli
from hub.cli import main
from hub.secrets_store import SecretsError


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


class _Cap:
    """替身 stdout：isatty 值可设，接得住 write/flush。"""

    def __init__(self, tty):
        self._tty = tty
        self.buf = []

    def isatty(self):
        return self._tty

    def write(self, s):
        self.buf.append(s)
        return len(s)

    def flush(self):
        pass


def _strlist(items):
    return "[" + ", ".join('"' + str(x).replace("\\", "/") + '"' for x in items) + "]"


def _profile_toml(name, argv, env=None, subs=("go",)):
    if env:
        env_body = "env = {" + ", ".join(f'"{k}" = "{v}"' for k, v in env.items()) + "}"
    else:
        env_body = "env = {}"
    return ("[profiles.%s]\nargv = %s\n%s\nallow_subcommands = %s\n"
            % (name, _strlist(argv), env_body, _strlist(list(subs))))


def _setup_profile(tmp_path, monkeypatch, entry_body, env=None, subs=("go",), name="prof"):
    """profile 声明 + 真实入口脚本 + HUB_HOME/HUB_SECRETS_ROOT 隔离。"""
    entry = tmp_path / "entry.py"
    entry.write_text(entry_body, encoding="utf-8")
    hub = tmp_path / "hub"
    hub.mkdir(exist_ok=True)
    (hub / "secrets-profiles.toml").write_text(
        _profile_toml(name, [sys.executable, entry], env=env, subs=subs),
        encoding="utf-8")
    monkeypatch.setenv("HUB_HOME", str(hub))
    sroot = tmp_path / "secrets"
    sroot.mkdir(exist_ok=True)
    monkeypatch.setenv("HUB_SECRETS_ROOT", str(sroot))
    return sroot, entry


_ECHO_ARGV = "import sys, json\nsys.stdout.write(json.dumps(sys.argv[1:]))\n"


# ---- exec json 成功信封 ----

def test_exec_json_success(machine_out, machine_err, tmp_path, monkeypatch):
    _setup_profile(tmp_path, monkeypatch, _ECHO_ARGV)
    rc = main(["secrets", "exec", "prof", "go", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue())
    assert env["ok"] is True
    data = env["data"]
    assert data["exit_code"] == 0
    assert json.loads(data["stdout"]) == ["go"]


def test_exec_json_stdout_redacted_stderr_not_in_data(machine_out, machine_err,
                                                      tmp_path, monkeypatch):
    """exec 输出已遮罩，可进 data；但成功信封只放 stdout，不放 stderr。"""
    _setup_profile(tmp_path, monkeypatch,
                   "import os,sys\nsys.stdout.write(os.environ.get('TOK','plain'))\n")
    rc = main(["secrets", "exec", "prof", "go", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue())["data"]
    assert set(data) == {"exit_code", "stdout"}
    assert "stderr" not in data


# ---- exec json 子进程非零 → E_EXTERNAL_TOOL ----

def test_exec_json_nonzero_external_tool(machine_out, machine_err, tmp_path, monkeypatch):
    _setup_profile(tmp_path, monkeypatch,
                   "import sys\nsys.stderr.write('boom-123')\nsys.exit(3)\n")
    rc = main(["secrets", "exec", "prof", "go", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""          # 失败信封走 stderr，stdout 零字节
    err = json.loads(machine_err.getvalue())
    assert err["ok"] is False
    assert err["error"]["code"] == "E_EXTERNAL_TOOL"
    assert err["error"]["retryable"] is True
    assert err["error"]["details"]["tool"] == "prof"
    assert err["error"]["details"]["exit_code"] == 3
    assert "boom-123" in err["error"]["details"]["stderr_tail"]


# ---- exec json 模式：json 标记不泄漏给子进程 ----

def test_exec_json_strips_json_markers(machine_out, machine_err, tmp_path, monkeypatch):
    _setup_profile(tmp_path, monkeypatch, _ECHO_ARGV)
    rc = main(["secrets", "exec", "prof", "go", "--json", "--force"])
    assert rc == 0
    argv = json.loads(json.loads(machine_out.getvalue())["data"]["stdout"])
    assert argv == ["go", "--force"]
    assert "--json" not in argv
    assert "--force" in argv


def test_exec_json_strips_format_variants(machine_out, machine_err, tmp_path, monkeypatch):
    _setup_profile(tmp_path, monkeypatch, _ECHO_ARGV)
    for extra in (["--format", "json"], ["--format=json"]):
        machine_out.seek(0); machine_out.truncate()
        rc = main(["secrets", "exec", "prof", "go", *extra])
        assert rc == 0
        argv = json.loads(json.loads(machine_out.getvalue())["data"]["stdout"])
        assert argv == ["go"]


def test_exec_json_marker_after_double_dash_is_childs(tmp_path, monkeypatch):
    """`--` 之后不剔：那个 `--json` 是子进程的，hub 走人类模式透传。"""
    cap = _Cap(False)
    monkeypatch.setattr(sys, "stdout", cap)
    _setup_profile(tmp_path, monkeypatch, _ECHO_ARGV)
    rc = main(["secrets", "exec", "prof", "go", "--", "--json"])
    assert rc == 0
    assert '"--json"' in "".join(cap.buf)          # 子进程真的收到了


# ---- exec json 缺 profile → E_NOT_FOUND rc1 ----

def test_exec_json_missing_profile(machine_out, machine_err, tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(exist_ok=True)
    (hub / "secrets-profiles.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("HUB_HOME", str(hub))
    monkeypatch.setenv("HUB_SECRETS_ROOT", str(tmp_path / "secrets"))
    rc = main(["secrets", "exec", "nope", "go", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"


# ---- run json：human_only 闸 + 泄密边界 ----

def test_run_json_non_tty_rejected(machine_out, machine_err, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Cap(False))
    sroot, entry = _setup_profile(tmp_path, monkeypatch, "pass")
    rc = main(["secrets", "run", "--profile", "prof", "--json", "--",
               sys.executable, str(entry)])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"
    assert "exec" in err["error"]["message"]        # 拒绝必须给出路（spec §6.2）


def test_run_json_tty_success(machine_out, machine_err, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", _Cap(True))
    sroot, entry = _setup_profile(tmp_path, monkeypatch, "pass")
    rc = main(["secrets", "run", "--profile", "prof", "--json", "--",
               sys.executable, str(entry)])
    assert rc == 0
    assert machine_err.getvalue() == b""
    data = json.loads(machine_out.getvalue())["data"]
    assert set(data) == {"exit_code"} and data["exit_code"] == 0


def test_run_json_failure_envelope_has_no_raw_output(machine_out, machine_err,
                                                     tmp_path, monkeypatch):
    """run 不遮罩——原始输出可能含密钥，信封/详情必须不含它（泄密审查）。"""
    monkeypatch.setattr(sys, "stdout", _Cap(True))
    secret = "SUPERSECRET-xyz-123"
    sroot, entry = _setup_profile(
        tmp_path, monkeypatch,
        "import os,sys\nsys.stdout.write(os.environ['TOK'])\nsys.exit(5)\n",
        env={"TOK": "hub://secrets/demo/k"})
    (sroot / "demo.md").write_text(
        f"---\nname: demo\n---\n\n## fields\n\nk = {secret}\n", encoding="utf-8")
    rc = main(["secrets", "run", "--profile", "prof", "--json", "--",
               sys.executable, str(entry)])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_EXTERNAL_TOOL"
    assert err["error"]["details"]["exit_code"] == 5
    assert secret.encode() not in machine_err.getvalue()


def test_run_json_no_command_rc2(machine_out, machine_err, tmp_path, monkeypatch):
    """`--` 后空 = 缺操作数，用法错误 rc2（与 promote-memory/induct 先例一致）。"""
    monkeypatch.setattr(sys, "stdout", _Cap(True))
    _setup_profile(tmp_path, monkeypatch, "pass")
    rc = main(["secrets", "run", "--profile", "prof", "--json", "--"])
    assert rc == 2
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue())
    assert err["error"]["code"] == "E_VALIDATION"


# ---- _fail 退出码收敛 + SecretsError 映射 ----

def test_fail_rc_convergence(capsys):
    assert secrets_cli._fail(SecretsError("没有名为 'x' 的 profile。")) == 1
    assert "没有名为" in capsys.readouterr().err
    assert secrets_cli._fail(
        SecretsError("secrets run 要在 `--` 后面给一条命令")) == 2
    assert secrets_cli._fail(SecretsError("这条命令只给人在终端里用。")) == 1
    assert secrets_cli._fail(SecretsError("demo 里没有字段 'k'")) == 1


def test_fail_json_mode_writes_envelope(machine_out, machine_err):
    rc = secrets_cli._fail(SecretsError("没有名为 'x' 的 profile。"), json_mode=True)
    assert rc == 1
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_NOT_FOUND"
    machine_err.seek(0); machine_err.truncate()
    rc2 = secrets_cli._fail(
        SecretsError("secrets run 要在 `--` 后面给一条命令"), json_mode=True)
    assert rc2 == 2
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"


def test_secrets_error_code_classification():
    f = secrets_cli._secrets_error_code
    assert f(SecretsError("没有名为 'x' 的 profile。")) == "E_NOT_FOUND"
    assert f(SecretsError("demo 里没有字段 'k'")) == "E_NOT_FOUND"
    assert f(SecretsError("C:/x/secrets/demo.md 不是普通文件")) == "E_NOT_FOUND"
    assert f(SecretsError("没有 profile 声明")) == "E_NOT_FOUND"
    assert f(SecretsError("启动链第 0 段不存在：C:/x")) == "E_NOT_FOUND"
    assert f(SecretsError("secrets run 要在 `--` 后面给一条命令")) == "E_VALIDATION"
    assert f(SecretsError("这条命令只给人在终端里用。")) == "E_VALIDATION"
    assert f(SecretsError("参数不合语法：'-e'")) == "E_VALIDATION"


def test_error_code_secrets_mapping():
    assert cli._error_code(SecretsError("没有名为 'x' 的 profile。")) == "E_NOT_FOUND"
    assert cli._error_code(SecretsError("demo 里没有字段 'k'")) == "E_NOT_FOUND"
    assert cli._error_code(
        SecretsError("secrets run 要在 `--` 后面给一条命令")) == "E_VALIDATION"
    assert cli._error_code(SecretsError("参数不合语法")) == "E_VALIDATION"


# ---- REMAINDER 剔除逻辑单测 ----

def test_strip_json_markers():
    f = secrets_cli._strip_json_markers
    assert f([]) == []
    assert f(["--json"]) == []
    assert f(["--format", "json"]) == []
    assert f(["--format=json"]) == []
    assert f(["go", "--json", "--force"]) == ["go", "--force"]
    assert f(["go", "--format", "json"]) == ["go"]
    assert f(["go", "--format=json"]) == ["go"]
    assert f(["go", "--", "--json"]) == ["go", "--", "--json"]   # `--` 之后不剔
    assert f(["--format", "yaml"]) == ["--format", "yaml"]       # 非 json 值不动
    assert f(["--format"]) == ["--format"]                        # 悬空 --format 不动


# ---- render/unlock 收到 --json 走 _JsonFriendlyParser → E_VALIDATION 信封 rc2 ----

@pytest.mark.parametrize("cmd", [
    ["secrets", "render", "--profile", "x", "--json"],
    ["secrets", "unlock", "--json"],
])
def test_human_only_subcommand_json_is_validation(cmd, machine_out, machine_err):
    """它们没有 --json；收到就走 argparse 错误 → E_VALIDATION 信封 rc2 = '这不是给 AI 的'。"""
    with pytest.raises(SystemExit) as ei:
        main(cmd)
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""
    assert json.loads(machine_err.getvalue())["error"]["code"] == "E_VALIDATION"
