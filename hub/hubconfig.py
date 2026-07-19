"""本机 hub 指针：~/.hub/config.toml（vault / host / hub_root）+ ~/.hub/backups。

register 写它，memory-read 缺 --vault 时读它，skill 包装脚本靠 hub_root 找到 hub。
已存在且指向不同 vault/host → 冲突停下，不覆盖（一台机被绑到另一个金库时要人来决定）。
不进金库、collect 不收。
"""
import os, tomllib
from pathlib import Path
from hub.writer import Writer

class ConfigConflict(RuntimeError):
    pass

def _hub_home() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub"))

def hub_config_path() -> Path:
    return _hub_home() / "config.toml"

def backups_dir() -> Path:
    return _hub_home() / "backups"

def read_config() -> dict:
    p = hub_config_path()
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def _canon(p) -> str:
    """canonical 绝对 posix 路径——config 存它，保证 skill 从任意 cwd 启动都能定位。"""
    return Path(p).resolve().as_posix()

def check_config(vault_root: Path, host: str) -> None:
    """只读冲突检查（供 register 先检后写）：已绑定到不同 vault/host → 抛 ConfigConflict，不写。"""
    cur = read_config()
    if cur and (cur.get("host") != host or cur.get("vault") != _canon(vault_root)):
        raise ConfigConflict(
            f"~/.hub/config.toml 已绑定 vault={cur.get('vault')} host={cur.get('host')}，"
            f"与本次 vault={_canon(vault_root)} host={host} 不符。停下来让你决定，不覆盖。")

def write_config(vault_root: Path, host: str, hub_root: Path, w: Writer) -> None:
    check_config(vault_root, host)
    body = (f'vault = "{_canon(vault_root)}"\n'
            f'host = "{host}"\n'
            f'hub_root = "{_canon(hub_root)}"\n')
    w.write_text_atomic(hub_config_path(), body)
