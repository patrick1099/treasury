import socket
import tomllib
from pathlib import Path
from hub.model import Vault, VaultConfig, DeviceProfile, ProjectTarget
from hub.frontmatter import load_memory

def current_host() -> str:
    return socket.gethostname().lower()

def load_vault(root: Path) -> Vault:
    cfg_raw = tomllib.loads((root / "vault.toml").read_text(encoding="utf-8"))
    config = VaultConfig(version=int(cfg_raw.get("version", 1)))
    rules = []
    rules_dir = root / "rules"
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*.md")):
            rules.append((p.stem, p.read_text(encoding="utf-8")))
    memories = []
    mem_dir = root / "memory"
    if mem_dir.is_dir():
        for p in sorted(mem_dir.glob("*.md")):
            memories.append(load_memory(p))
    return Vault(root=root, config=config, memories=memories, rules=rules)

def load_device(root: Path, host: str) -> DeviceProfile:
    raw = tomllib.loads((root / "devices" / f"{host}.toml").read_text(encoding="utf-8"))
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
