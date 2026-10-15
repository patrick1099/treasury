"""hub inventory --json process boundary.

This module is intentionally thin: it only invokes the CLI, parses the
standard ``{ok,data,error,meta}`` envelope and returns the ``data`` payload.
No display logic, no toggle calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class InventoryError(RuntimeError):
    """Raised when hub inventory cannot be called or returns a failure envelope."""


def _default_hub_root() -> Path:
    """Best-effort location of the hub package.

    The hub CLI is a Python package normally checked out next to ``hub_gui``,
    e.g. ``C:/Users/<user>/treasury``.  When packaged/relocated, the env var
    ``HUB_ROOT`` is honoured first, then the standard user home layout
    ``~/treasury`` is used.
    """
    env_root = os.environ.get("HUB_ROOT")
    if env_root:
        return Path(env_root)
    here = Path(__file__).resolve()
    candidate = here.parents[2]  # .../treasury/
    if (candidate / "hub" / "cli.py").exists():
        return candidate
    user_treasury = Path.home() / "treasury"
    if (user_treasury / "hub" / "cli.py").exists():
        return user_treasury
    return Path.cwd()


def load_inventory(vault: str | None = None, host: str | None = None,
                   hub_root: str | Path | None = None) -> dict:
    """Call ``hub inventory --json`` and return the ``data`` payload dict.

    Parameters
    ----------
    vault:
        Optional vault directory passed through to the CLI (``--vault``).
    host:
        Optional device host passed through to the CLI (``--host``).
    hub_root:
        Directory containing the ``hub`` Python package.  Defaults to the
        repository root sibling of ``hub_gui`` or ``$HUB_ROOT``.

    Returns
    -------
    dict
        The ``data`` field of the success envelope: includes ``assets``,
        ``matrix``, ``vault``, ``host`` and ``generated_at``.
    """
    hub_root_path = Path(hub_root) if hub_root else _default_hub_root()

    if getattr(sys, "frozen", False):
        command = ["py", "-3", "-m", "hub.cli", "inventory", "--json"]
    else:
        command = [sys.executable, "-m", "hub.cli", "inventory", "--json"]
    if vault:
        command += ["--vault", str(vault)]
    if host:
        command += ["--host", str(host)]

    try:
        popen_kwargs = {}
        if os.name == "nt":
            # Prevent the child py.exe / python.exe from flashing a console
            # window when hub-gui itself is a windowed (no-console) exe.
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            command,
            cwd=str(hub_root_path),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise InventoryError(
            "找不到 hub CLI；请确认 hub_root 下存在 `hub/cli.py`，"
            f"或设置 HUB_ROOT。当前尝试: {hub_root_path}"
        ) from exc

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    payload = None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # On error the CLI may emit the envelope on stderr instead.
        try:
            payload = json.loads(stderr)
        except json.JSONDecodeError:
            raise InventoryError(
                "hub inventory 返回非 JSON 输出 "
                f"(exit={proc.returncode}): stdout={stdout[:300]!r} stderr={stderr[:300]!r}"
            ) from None

    if not isinstance(payload, dict):
        raise InventoryError("hub inventory 返回了非对象 JSON")

    if not payload.get("ok", False):
        err = payload.get("error") or {}
        message = err.get("message") if isinstance(err, dict) else str(err)
        if not message:
            message = stderr.strip() or stdout.strip() or "hub inventory 返回失败信封"
        raise InventoryError(message)

    data = payload.get("data")
    if data is None:
        raise InventoryError("hub inventory 成功信封缺少 data")
    if not isinstance(data, dict):
        raise InventoryError("hub inventory 的 data 字段不是对象")

    return data
