"""金库的读取。

金库顶层按**归属**切,不按数据类型切:

    vault/
    ├─ vault.toml
    ├─ shared/          公共池:rules/ memory/ (skills/ plugins/ 预留)
    ├─ <host>/          一台设备的全部家当:device.toml memory/ merged.txt …
    └─ <他机>/

两台设备各写各的文件夹,永远碰不到同一个文件 → git 合并零冲突。
"""
import socket
import tomllib
from pathlib import Path
from hub.model import Vault, VaultConfig, DeviceProfile, ProjectTarget, SHARED
from hub.frontmatter import load_memory

def current_host() -> str:
    return socket.gethostname().lower()

def _read_rules(d: Path) -> list[tuple[str, str]]:
    if not d.is_dir():
        return []
    return [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.md"))]

def _owner_dirs(root: Path):
    """金库顶层的归属文件夹(shared 与各设备),跳过 .git 之类。"""
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            yield d

def load_vault(root: Path) -> Vault:
    cfg_raw = tomllib.loads((root / "vault.toml").read_text(encoding="utf-8"))
    config = VaultConfig(version=int(cfg_raw.get("version", 1)))
    rules = _read_rules(root / SHARED / "rules")
    memories = []
    for owner in _owner_dirs(root):
        for p in sorted((owner / "memory").glob("*.md")) if (owner / "memory").is_dir() else []:
            m = load_memory(p)
            m.origin = owner.name
            memories.append(m)
    return Vault(root=root, config=config, memories=memories, rules=rules)

def load_device_rules(root: Path, host: str) -> list[tuple[str, str]]:
    """某台设备私有的规则(可选)。公共规则在 shared/rules/。"""
    return _read_rules(root / host / "rules")

def load_device(root: Path, host: str) -> DeviceProfile:
    raw = tomllib.loads((root / host / "device.toml").read_text(encoding="utf-8"))
    targets = [ProjectTarget(project=t["project"], root=t["root"])
               for t in raw.get("targets", [])]
    return DeviceProfile(
        host=host,
        classes=list(raw.get("class", [])),
        projects=list(raw.get("projects", [])),
        paths=dict(raw.get("paths", {})),
        targets=targets,
        collect_sources=list(raw.get("collect_sources", [])),
    )
