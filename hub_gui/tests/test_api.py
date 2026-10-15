"""API tests for hub_gui.api.server.

FastAPI and httpx (needed by TestClient) are optional for this project.
If either is missing, this module is skipped and only core tests run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")

try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - depends on environment
    pytest.skip(f"FastAPI TestClient unavailable (requires httpx): {exc}", allow_module_level=True)

from hub_gui.api.server import app
from hub_gui.core.inventory_client import InventoryError
from hub_gui.core.toggle_client import ToggleClientError


def _fake_inventory(vault=None, host=None):
    return {
        "vault": vault or "C:/vault",
        "host": host or "dev-host",
        "assets": [
            {
                "type": "skill",
                "id": "skill:demo:demo",
                "name": "demo",
                "plugin": "demo",
                "skill_origin": "plugin-internal",
                "harnesses": {
                    "claude": {
                        "harness": "claude",
                        "desired": True,
                        "actual": True,
                        "health": "ok",
                        "control": "plugin",
                        "detail": "由插件整体控制",
                    }
                },
            }
        ],
        "matrix": [],
    }


def _fake_toggle(asset_type="skill", name="demo", harness="opencode", state="on",
                 plugin="demo", dry_run=False, vault=None, host=None):
    return {
        "asset_type": asset_type,
        "name": name,
        "plugin": plugin,
        "harness": harness,
        "action": state,
        "dry_run": dry_run,
        "results": [
            {
                "harness": harness,
                "status": "applied",
                "actions": [],
            }
        ],
        "changed": [],
        "actions": [],
    }


def test_inventory_endpoint_returns_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hub_gui.api.server.load_inventory", _fake_inventory)
    client = TestClient(app)
    response = client.get("/api/inventory", params={"vault": "C:/vault", "host": "dev-host"})
    assert response.status_code == 200
    body = response.json()
    assert "assets" in body
    assert body["assets"][0]["id"] == "skill:demo:demo"


def test_inventory_endpoint_propagates_core_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args, **kwargs):
        raise InventoryError("hub CLI 不可用")

    monkeypatch.setattr("hub_gui.api.server.load_inventory", raise_error)
    client = TestClient(app)
    response = client.get("/api/inventory")
    assert response.status_code == 502
    assert "hub CLI 不可用" in response.json()["detail"]


def test_toggle_endpoint_returns_data(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_toggle(asset_type, name, harness, state, plugin=None,
                    dry_run=False, vault=None, host=None):
        captured.update(
            asset_type=asset_type,
            name=name,
            harness=harness,
            state=state,
            plugin=plugin,
            dry_run=dry_run,
            vault=vault,
            host=host,
        )
        return _fake_toggle(
            asset_type=asset_type, name=name, harness=harness, state=state,
            plugin=plugin, dry_run=dry_run, vault=vault, host=host,
        )

    monkeypatch.setattr("hub_gui.api.server.run_toggle", fake_toggle)
    client = TestClient(app)
    response = client.post(
        "/api/toggle",
        json={
            "asset_type": "skill",
            "name": "demo",
            "harness": "opencode",
            "state": "on",
            "plugin": "demo",
            "dry_run": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["asset_type"] == "skill"
    assert body["data"]["action"] == "on"
    assert captured["asset_type"] == "skill"
    assert captured["name"] == "demo"
    assert captured["harness"] == "opencode"
    assert captured["state"] == "on"
    assert captured["plugin"] == "demo"
    assert captured["dry_run"] is False


def test_toggle_endpoint_propagates_core_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args, **kwargs):
        raise ToggleClientError("memory 首版只读")

    monkeypatch.setattr("hub_gui.api.server.run_toggle", raise_error)
    client = TestClient(app)
    response = client.post(
        "/api/toggle",
        json={"asset_type": "memory", "name": "project_projx",
              "harness": "claude", "state": "off", "plugin": None,
              "dry_run": False},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "memory 首版只读"
