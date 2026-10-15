"""hub toggle --json process boundary.

This module is intentionally thin: it only invokes the CLI, parses the
standard ``{ok,data,error,meta}`` envelope and returns the ``data`` payload.
It never contains display logic or business rules.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class ToggleClientError(RuntimeError):
    """Raised when hub toggle cannot be called or returns a failure envelope."""


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


def _build_toggle_command(asset_type: str, name: str, harness: str, state: str,
                          plugin: str | None = None, dry_run: bool = False,
                          vault: str | None = None, host: str | None = None) -> list[str]:
    command = [sys.executable, "-m", "hub.cli", "toggle", asset_type, name, harness, state, "--json"]
    if plugin:
        command += ["--plugin", str(plugin)]
    if dry_run:
        command += ["--dry-run"]
    if vault:
        command += ["--vault", str(vault)]
    if host:
        command += ["--host", str(host)]
    return command


def run_toggle(asset_type: str, name: str, harness: str, state: str,
               plugin: str | None = None, dry_run: bool = False,
               vault: str | None = None, host: str | None = None,
               hub_root: str | Path | None = None) -> dict:
    """Call ``hub toggle ... --json`` and return the ``data`` payload dict.

    Parameters
    ----------
    asset_type:
        One of ``plugin``, ``skill`` or ``memory``.
    name:
        Asset name passed to the CLI.
    harness:
        One of ``claude``, ``codex``, ``opencode`` or ``dsh``.
    state:
        ``on`` or ``off``.
    plugin:
        Optional plugin name disambiguator for plugin-internal skills.
    dry_run:
        When true, pass ``--dry-run`` so the CLI only reports what would change.
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
        The ``data`` field of the success envelope (``results``, ``changed``,
        ``actions`` etc.).
    """
    hub_root_path = Path(hub_root) if hub_root else _default_hub_root()
    command = _build_toggle_command(
        asset_type=asset_type,
        name=name,
        harness=harness,
        state=state,
        plugin=plugin,
        dry_run=dry_run,
        vault=vault,
        host=host,
    )
    if getattr(sys, "frozen", False):
        # In a PyInstaller exe ``sys.executable`` is the GUI exe, not a Python
        # interpreter; use the installed ``py -3`` launcher to call hub CLI.
        command = ["py", "-3", "-m", "hub.cli"] + command[3:]

    try:
        popen_kwargs = {}
        if os.name == "nt":
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
        raise ToggleClientError(
            "找不到 hub CLI，请确认 hub_root 下存在 `hub/cli.py`。"
            f"当前目录: {hub_root_path}"
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
            raise ToggleClientError(
                "hub toggle 未返回 JSON 信封 "
                f"(exit={proc.returncode}): stdout={stdout[:300]!r} stderr={stderr[:300]!r}"
            ) from None

    if not isinstance(payload, dict):
        raise ToggleClientError("hub toggle 返回了非对象 JSON")

    if not payload.get("ok", False):
        err = payload.get("error") or {}
        message = err.get("message") if isinstance(err, dict) else str(err)
        if not message:
            message = stderr.strip() or stdout.strip() or "hub toggle 返回失败信封"
        raise ToggleClientError(message)

    data = payload.get("data")
    if data is None:
        raise ToggleClientError("hub toggle 成功信封缺少 data")
    if not isinstance(data, dict):
        raise ToggleClientError("hub toggle 的 data 字段不是对象")

    return data
