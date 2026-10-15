"""Tests for hub_gui.core.inventory_client.

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

from hub_gui.core.inventory_client import InventoryError, load_inventory


class FakeCompleted:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _ok_payload() -> dict:
    return {
        "ok": True,
        "data": {
            "vault": "C:/vault",
            "host": "dev-host",
            "generated_at": "2026-08-27T12:00:00",
            "assets": [
                {
                    "type": "plugin",
                    "id": "plugin:demo",
                    "name": "demo",
                    "harnesses": {
                        "claude": {
                            "harness": "claude",
                            "desired": True,
                            "actual": True,
                            "health": "ok",
                            "control": "direct",
                            "detail": "ok",
                        }
                    },
                }
            ],
            "matrix": [
                {
                    "asset_type": "plugin",
                    "asset_id": "plugin:demo",
                    "asset_name": "demo",
                    "harness": "claude",
                    "desired": True,
                    "actual": True,
                    "health": "ok",
                    "control": "direct",
                    "detail": "ok",
                }
            ],
        },
        "error": None,
        "meta": {"warnings": []},
    }


def test_load_inventory_success_parses_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeCompleted(stdout=json.dumps(_ok_payload(), ensure_ascii=False), returncode=0)

    monkeypatch.setattr("hub_gui.core.inventory_client.subprocess.run", fake_run)

    result = load_inventory(vault="C:/vault", host="dev-host", hub_root="C:/hub")

    assert result["assets"][0]["id"] == "plugin:demo"
    assert result["matrix"][0]["asset_id"] == "plugin:demo"
    # Process boundary translation passes CLI flags through.
    assert captured["command"][:5] == [sys.executable, "-m", "hub.cli", "inventory", "--json"]
    assert "--vault" in captured["command"]
    assert "C:/vault" in captured["command"]
    assert "--host" in captured["command"]
    assert Path(captured["kwargs"]["cwd"]) == Path("C:/hub")
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"


def test_load_inventory_failure_envelope_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    error = {
        "ok": False,
        "data": None,
        "error": {"code": "E_NOT_FOUND", "message": "找不到金库", "retryable": False},
        "meta": {},
    }

    def fake_run(command, **kwargs):
        return FakeCompleted(stdout=json.dumps(error, ensure_ascii=False), returncode=1)

    monkeypatch.setattr("hub_gui.core.inventory_client.subprocess.run", fake_run)

    with pytest.raises(InventoryError, match="找不到金库"):
        load_inventory(hub_root="C:/hub")


def test_load_inventory_cli_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command, **kwargs):
        raise FileNotFoundError("no python")

    monkeypatch.setattr("hub_gui.core.inventory_client.subprocess.run", fake_run)

    with pytest.raises(InventoryError, match="找不到 hub CLI"):
        load_inventory(hub_root="C:/hub")
