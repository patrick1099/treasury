# tests/hub/test_contract_matrix.py —— CLI-AI 规范 T-A：输出内核契约矩阵
import io
import json
from pathlib import Path
import pytest
from hub import cli
from hub.cli import main
from hub.memread import read_memory


def _setup(vault, host, name, body):
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (vault / host).mkdir(parents=True, exist_ok=True)
    (vault / host / "device.toml").write_text(
        "class = []\nprojects = []\n[paths]\nVAULT = \"" + vault.as_posix() + "\"\n",
        encoding="utf-8")
    d = vault / "shared" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
        f"  scope: [global]\n---\n\n{body}",
        encoding="utf-8")


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


def _expected_success(data):
    envelope = {"ok": True, "data": data, "error": None, "meta": {}}
    return (json.dumps(envelope, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def test_json_success_envelope_bytes(machine_out, machine_err, tmp_path):
    body = "中文正文 👋\n第二行\n"
    _setup(tmp_path, "h1", "a", body)
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "a", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    canonical = read_memory(tmp_path, "h1", "claude", "a")
    assert canonical.startswith("\n") and canonical.endswith("\n")
    assert "👋" in canonical
    data = {"name": "a", "tool": "claude", "host": "h1", "vault": str(tmp_path), "body": canonical}
    assert machine_out.getvalue() == _expected_success(data)
    parsed = json.loads(machine_out.getvalue().decode("utf-8"))
    assert parsed["data"]["body"] == canonical
    assert parsed["data"]["body"] != canonical.strip()


def test_json_empty_body_preserved(machine_out, tmp_path):
    _setup(tmp_path, "h1", "empty", "")
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "empty", "--json"])
    assert rc == 0
    assert json.loads(machine_out.getvalue())["data"]["body"] == ""


def test_json_newlines_preserved(machine_out, tmp_path):
    body = "\n\n首尾带空行\n\n"
    _setup(tmp_path, "h1", "nl", body)
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "nl", "--json"])
    assert rc == 0
    canonical = read_memory(tmp_path, "h1", "claude", "nl")
    assert canonical.startswith("\n\n\n")          # 关闭 --- 后的空行 + 正文前导空行都保留
    assert "首尾带空行" in canonical
    assert json.loads(machine_out.getvalue())["data"]["body"] == canonical


def test_json_not_found_envelope(machine_out, machine_err, tmp_path):
    _setup(tmp_path, "h1", "a", "正文\n")
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "nope", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["ok"] is False and err["data"] is None
    assert err["error"]["code"] == "E_NOT_FOUND"
    assert err["error"]["retryable"] is False
    assert err["error"]["suggestion"]


def test_plain_default_is_plain_body(tmp_path, capsys):
    body = "纯文本正文\n"
    _setup(tmp_path, "h1", "a", body)
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "a"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out == read_memory(tmp_path, "h1", "claude", "a")
    assert "纯文本正文" in out


def test_plain_error_still_on_stdout(tmp_path, capsys):
    _setup(tmp_path, "h1", "a", "正文\n")
    rc = main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
               "--tool", "claude", "--name", "nope"])
    assert rc == 1
    assert "nope" in capsys.readouterr().out


def test_format_json_equiv(machine_out, tmp_path):
    _setup(tmp_path, "h1", "a", "正文\n")
    cases = (
        ["memory-read", "--vault", str(tmp_path), "--host", "h1",
         "--tool", "claude", "--name", "a", "--json"],
        ["memory-read", "--vault", str(tmp_path), "--host", "h1",
         "--tool", "claude", "--name", "a", "--format", "json"],
        ["memory-read", "--vault", str(tmp_path), "--host", "h1",
         "--tool", "claude", "--name", "a", "--format=json"],
    )
    outs = []
    for argv in cases:
        machine_out.truncate(0)
        machine_out.seek(0)
        assert main(argv) == 0
        outs.append(machine_out.getvalue())
    assert outs[0] == outs[1] == outs[2]


def test_json_requested_terminator_semantics():
    assert cli._json_requested(["--json"]) is True
    assert cli._json_requested(["--format", "json"]) is True
    assert cli._json_requested(["--format=json"]) is True
    assert cli._json_requested(["--", "--json"]) is False
    assert cli._json_requested(["--", "--format", "json"]) is False
    assert cli._json_requested(["memory-read", "--", "--json"]) is False


def test_json_argparse_error_envelope(machine_out, machine_err):
    with pytest.raises(SystemExit) as ei:
        main(["--json", "--definitely-invalid-flag"])
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"


def test_argparse_plain_error_not_enveloped(machine_out, machine_err):
    with pytest.raises(SystemExit) as ei:
        main(["--definitely-invalid-flag"])
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""
    assert machine_err.getvalue() == b""


def test_ai_help_content(machine_out):
    assert main(["--ai-help"]) == 0
    text = machine_out.getvalue().decode("utf-8")
    assert "name: hub" in text
    assert "description:" in text
    assert "ai_help_version: 0.1.0" in text
    for sec in ("## Quick Reference", "## When to Use", "## Command Reference",
                "## Input / Output", "## Side Effects & Safety", "## Exit Codes",
                "## Errors & Recovery"):
        assert sec in text
    assert text.find("## Quick Reference") < text.find("## Exit Codes")


def test_ai_help_eager(machine_out):
    assert main(["--garbage", "--ai-help"]) == 0
    assert b"name: hub" in machine_out.getvalue()


def test_ai_help_terminator(machine_out):
    with pytest.raises(SystemExit) as ei:
        main(["--", "--ai-help"])
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""


def test_help_line(tmp_path, capsys):
    with pytest.raises(SystemExit) as ei:
        main(["--help"])
    assert ei.value.code == 0
    assert "LLMs/agents: run 'hub --ai-help'" in capsys.readouterr().out


def test_machine_sink_injectable(tmp_path, monkeypatch):
    out = io.BytesIO()
    monkeypatch.setattr(cli, "_MACHINE_OUT", out)
    _setup(tmp_path, "h1", "a", "正文\n")
    assert main(["memory-read", "--vault", str(tmp_path), "--host", "h1",
                 "--tool", "claude", "--name", "a", "--json"]) == 0
    assert out.getvalue().startswith(b"{\n")
