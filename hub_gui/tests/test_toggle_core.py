"""Tests for hub_gui.core.toggle_client.

These tests use a fake subprocess.run and never invoke the real hub CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hub_gui.core.toggle_client import ToggleClientError, run_toggle


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _ok_payload() -> dict:
    return {
        "ok": True,
        "data": {
            "asset_type": "plugin",
            "name": "cjt",
            "plugin": None,
            "harness": "claude",
            "action": "on",
            "dry_run": True,
            "results": [
                {
                    "harness": "claude",
                    "status": "applied",
                    "actions": [],
                }
            ],
            "changed": ["C:/vault/device.toml"],
            "actions": [],
        },
        "error": None,
        "meta": {"warnings": []},
    }


def test_run_toggle_success_parses_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeCompleted(stdout=json.dumps(_ok_payload(), ensure_ascii=False), returncode=0)

    monkeypatch.setattr("hub_gui.core.toggle_client.subprocess.run", fake_run)

    result = run_toggle(
        "plugin",
        "cjt",
        "claude",
        "on",
        dry_run=True,
        vault="C:/vault",
        host="dev-host",
        hub_root="C:/hub",
    )

    assert result["asset_type"] == "plugin"
    assert result["name"] == "cjt"
    assert result["dry_run"] is True
    assert result["results"][0]["status"] == "applied"

    # Verify the CLI invocation shape.
    assert captured["command"][:8] == [
        sys.executable, "-m", "hub.cli", "toggle",
        "plugin", "cjt", "claude", "on",
    ]
    assert "--json" in captured["command"]
    assert "--dry-run" in captured["command"]
    assert "--vault" in captured["command"]
    assert "C:/vault" in captured["command"]
    assert "--host" in captured["command"]
    assert "dev-host" in captured["command"]
    assert Path(captured["kwargs"]["cwd"]) == Path("C:/hub")
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"


def test_run_toggle_passes_plugin_disambiguator(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeCompleted(stdout=json.dumps(_ok_payload(), ensure_ascii=False), returncode=0)

    monkeypatch.setattr("hub_gui.core.toggle_client.subprocess.run", fake_run)

    run_toggle(
        "skill",
        "cjt",
        "opencode",
        "off",
        plugin="cjt",
        hub_root="C:/hub",
    )

    assert "--plugin" in captured["command"]
    assert captured["command"][captured["command"].index("--plugin") + 1] == "cjt"


def test_run_toggle_failure_envelope_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    error = {
        "ok": False,
        "data": None,
        "error": {
            "code": "E_VALIDATION",
            "message": "memory 首版只读",
            "retryable": False,
        },
        "meta": {},
    }

    def fake_run(command, **kwargs):
        return FakeCompleted(stdout=json.dumps(error, ensure_ascii=False), returncode=1)

    monkeypatch.setattr("hub_gui.core.toggle_client.subprocess.run", fake_run)

    with pytest.raises(ToggleClientError, match="memory 首版只读"):
        run_toggle("memory", "project_projx", "claude", "off", hub_root="C:/hub")


def test_run_toggle_non_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):
        return FakeCompleted(stdout="not json", stderr="boom", returncode=1)

    monkeypatch.setattr("hub_gui.core.toggle_client.subprocess.run", fake_run)

    with pytest.raises(ToggleClientError, match="未返回 JSON 信封"):
        run_toggle("plugin", "cjt", "claude", "on", hub_root="C:/hub")


def test_run_toggle_cli_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):
        raise FileNotFoundError("no python")

    monkeypatch.setattr("hub_gui.core.toggle_client.subprocess.run", fake_run)

    with pytest.raises(ToggleClientError, match="找不到 hub CLI"):
        run_toggle("plugin", "cjt", "claude", "on", hub_root="C:/hub")
