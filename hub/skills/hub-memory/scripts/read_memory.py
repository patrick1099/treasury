#!/usr/bin/env python3
"""hub-memory skill 的稳定启动包装：只负责找到 hub 并转调 `hub memory-read`。
核心逻辑（查视图、读正文、展开符号根）唯一落在 hub 模块/CLI，这里不重复实现。"""
import os, subprocess, sys, tomllib
from pathlib import Path

def _hub_root() -> str | None:
    cfg = Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub")) / "config.toml"
    if cfg.exists():
        return tomllib.loads(cfg.read_text(encoding="utf-8")).get("hub_root")
    return None

def main(argv: list[str]) -> int:
    root = _hub_root()
    env = dict(os.environ)
    if root:
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    # 转调 hub CLI 的 memory-read；--vault/--host 由 CLI 从 ~/.hub/config.toml 补全
    return subprocess.run([sys.executable, "-m", "hub.cli", "memory-read", *argv], env=env).returncode

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
