import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hub.memread import read_memory

TREASURY = Path(__file__).resolve().parents[2]
WRAPPER = TREASURY / "hub" / "skills" / "hub-memory" / "scripts" / "read_memory.py"
HOST = "h1"


def _build_vault(vault):
    (vault / HOST).mkdir(parents=True, exist_ok=True)
    (vault / "vault.toml").write_bytes(b"version = 2\n")
    (vault / HOST / "device.toml").write_bytes(
        ("class = []\nprojects = []\n[paths]\nVAULT = \"" + vault.as_posix() + "\"\n").encode("utf-8"))
    d = vault / "shared" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / "probe.md").write_bytes(
        ("---\nname: probe\ndescription: contract-test probe\nmetadata:\n"
         "  type: reference\n  scope: [global]\n---\n\ncontract probe body\n").encode("utf-8"))


def _run_wrapper(tmp_path, argv):
    home = tmp_path / "hubhome"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(TREASURY)
    env["HUB_HOME"] = str(home)
    return subprocess.run([sys.executable, str(WRAPPER)] + argv,
                          capture_output=True, env=env)


def _read_args(vault):
    return ["--vault", str(vault), "--host", HOST, "--tool", "claude", "--name", "probe"]


def _assert_json_success(proc, vault, body):
    assert proc.returncode == 0
    assert proc.stderr == b""
    envelope = json.loads(proc.stdout.decode("utf-8"))
    assert envelope["ok"] is True
    assert envelope["error"] is None
    data = envelope["data"]
    assert data["body"] == body
    assert data["name"] == "probe"
    assert data["tool"] == "claude"
    assert data["host"] == HOST
    assert Path(data["vault"]) == vault


def test_plain_success_passthrough_bytes(tmp_path):
    vault = tmp_path / "vault"
    _build_vault(vault)
    body = read_memory(vault, HOST, "claude", "probe")
    proc = _run_wrapper(tmp_path, _read_args(vault))
    assert proc.returncode == 0
    assert proc.stderr == b""
    assert proc.stdout == body.replace("\n", os.linesep).encode("utf-8")


def test_json_success_envelope(tmp_path):
    vault = tmp_path / "vault"
    _build_vault(vault)
    body = read_memory(vault, HOST, "claude", "probe")
    proc = _run_wrapper(tmp_path, _read_args(vault) + ["--json"])
    _assert_json_success(proc, vault, body)


def test_format_json_equiv(tmp_path):
    vault = tmp_path / "vault"
    _build_vault(vault)
    body = read_memory(vault, HOST, "claude", "probe")
    proc = _run_wrapper(tmp_path, _read_args(vault) + ["--format", "json"])
    _assert_json_success(proc, vault, body)


def test_json_missing_envelope(tmp_path):
    vault = tmp_path / "vault"
    _build_vault(vault)
    proc = _run_wrapper(
        tmp_path,
        ["--vault", str(vault), "--host", HOST, "--tool", "claude",
         "--name", "no-such-name", "--json"])
    assert proc.returncode == 1
    assert proc.stdout == b""
    envelope = json.loads(proc.stderr.decode("utf-8"))
    assert envelope["ok"] is False
    assert envelope["data"] is None
    err = envelope["error"]
    assert err["code"] == "E_NOT_FOUND"
    assert "message" in err
    assert "suggestion" in err
    assert err["retryable"] is False


def test_plain_missing_human_error(tmp_path):
    vault = tmp_path / "vault"
    _build_vault(vault)
    proc = _run_wrapper(
        tmp_path,
        ["--vault", str(vault), "--host", HOST, "--tool", "claude",
         "--name", "no-such-name"])
    assert proc.returncode == 1
    assert proc.stderr == b""
    assert proc.stdout != b""
    text = proc.stdout.decode("utf-8")
    with pytest.raises(ValueError):
        json.loads(text)
    assert "'no-such-name'" in text
