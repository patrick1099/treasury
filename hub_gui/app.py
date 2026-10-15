"""hub-gui launcher.

Starts uvicorn on 127.0.0.1:<random port> then opens the local page in a
pywebview window.  Development mode: ``python -m uvicorn api.server:app --reload``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def find_free_port() -> int:
    """Return a free TCP port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, timeout: float = 25.0, per_attempt: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=per_attempt)
            return
        except Exception:
            time.sleep(0.3)
    raise TimeoutError(f"uvicorn did not become ready at {url}")


def _server_root() -> Path:
    """Directory containing the importable ``hub_gui`` package.

    In development the app is ``<root>/hub_gui/app.py``.  When packaged the
    source tree still lives in the user's my-repos checkout; ``HUB_GUI_ROOT``
    can override it.
    """
    env_root = os.environ.get("HUB_GUI_ROOT")
    if env_root:
        return Path(env_root)
    here = Path(__file__).resolve()
    if not getattr(sys, "frozen", False):
        if here.parent.name == "hub_gui":
            return here.parents[1]
    home = Path.home()
    for candidate in (
        home / "Desktop" / "MyProjects" / "my-repos",
        home / "treasury",
    ):
        if (candidate / "hub_gui" / "api" / "server.py").exists():
            return candidate
    return Path.cwd()


def _start_uvicorn_process(port: int, root: Path):
    import uvicorn  # noqa: F401  (dependency check; the child needs it too)

    if getattr(sys, "frozen", False):
        cmd = ["py", "-3", "-m", "uvicorn", "hub_gui.api.server:app",
               "--host", "127.0.0.1", "--port", str(port)]
    else:
        cmd = [sys.executable, "-m", "uvicorn", "hub_gui.api.server:app",
               "--host", "127.0.0.1", "--port", str(port)]
    env = os.environ.copy()
    root_str = str(root)
    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = root_str + (os.pathsep + old_pythonpath if old_pythonpath else "")
    log_path = os.environ.get("HUB_GUI_UVICORN_LOG") or str(Path.home() / ".hub-gui-uvicorn.log")
    log_file = open(log_path, "a", encoding="utf-8")
    startupinfo = None
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        startupinfo = si
    return subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        startupinfo=startupinfo,
    )


def main() -> None:
    try:
        import uvicorn  # noqa: F401
    except ImportError as exc:
        raise SystemExit("缺少依赖：请先 `pip install -r requirements.txt`（至少 uvicorn）") from exc

    root = _server_root()
    if not (root / "hub_gui" / "api" / "server.py").exists():
        raise SystemExit(
            f"找不到 hub_gui 源码目录，请设置 HUB_GUI_ROOT。当前尝试: {root}"
        )

    port = find_free_port()
    url = f"http://127.0.0.1:{port}"

    proc = _start_uvicorn_process(port, root)

    try:
        wait_for_server(url)
    except TimeoutError:
        # Still try to show something useful.
        webbrowser.open(url)
        proc.terminate()
        raise

    print(f"hub-gui listening at {url}")

    try:
        import webview
    except ImportError as exc:
        raise SystemExit("缺少依赖：请先 `pip install -r requirements.txt`（至少 pywebview）") from exc

    try:
        webview.create_window(
            "hub-gui",
            url,
            width=1280,
            height=860,
            min_size=(820, 600),
        )
        webview.start()
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
