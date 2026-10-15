"""FastAPI thin adapter for hub-gui.

Responsibility: translate HTTP <-> core.  It does not build the matrix and
does not contain business rules.  Toggle requests are forwarded to
``hub_gui.core.toggle_client.run_toggle``.
"""

from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent.parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hub_gui.core.inventory_client import InventoryError, load_inventory
from hub_gui.core.toggle_client import ToggleClientError, run_toggle

if getattr(sys, "frozen", False):
    WEB_DIR = Path(getattr(sys, "_MEIPASS")) / "web"
else:
    WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="hub-gui", description="hub asset matrix GUI", version="0.2.0")


class ToggleRequest(BaseModel):
    asset_type: str
    name: str
    harness: str
    state: str
    plugin: str | None = None
    dry_run: bool = False
    vault: str | None = None
    host: str | None = None


@app.get("/api/inventory")
def get_inventory(
    vault: str | None = Query(default=None, description="Vault directory passed to hub inventory"),
    host: str | None = Query(default=None, description="Host name passed to hub inventory"),
) -> dict:
    """Return the normalized inventory data (assets + matrix)."""
    try:
        return load_inventory(vault=vault, host=host)
    except InventoryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/toggle")
def post_toggle(payload: ToggleRequest) -> dict:
    """Run ``hub toggle`` on behalf of the web UI.

    The UI passes asset type/name/harness plus the target state.  The core
    client invokes the real CLI and returns only the ``data`` envelope field.
    """
    try:
        data = run_toggle(
            asset_type=payload.asset_type,
            name=payload.name,
            harness=payload.harness,
            state=payload.state,
            plugin=payload.plugin,
            dry_run=payload.dry_run,
            vault=payload.vault,
            host=payload.host,
        )
        return {"ok": True, "data": data}
    except ToggleClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Serve the zero-build web/ directory in both development and pywebview delivery.
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
