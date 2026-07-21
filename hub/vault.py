"""金库的读取。

两个区,语义不同:

    vault/
    ├─ vault.toml  SCHEMA.md  MEMORY.md  lint-exempt.txt
    ├─ <host>/          备份区:这台机的原始数据,按工具分
    │   ├─ device.toml
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    └─ shared/          共享区:跨设备/跨工具的精选,按类型分
        └─ memory/ skills/ plugins/ hooks/ chats/

备份区 = "别丢"(换机照它还原);共享区 = "到处都要有"(skill 照它装)。
两台设备各写各的文件夹,永远碰不到同一个文件 → git 合并零冲突。
"""
import socket
import tomllib
from pathlib import Path
from hub.model import Vault, VaultConfig, DeviceProfile, ToolSources, SHARED
from hub.frontmatter import load_memory

def current_host() -> str:
    return socket.gethostname().lower()

def _owner_dirs(root: Path):
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            yield d

def memory_dirs(root: Path) -> list[tuple[str, Path]]:
    """金库里所有存放记忆的目录:[(归属, 目录), …]。

    共享区在 shared/memory/;备份区在 <host>/claude/memory/
    (记忆是 Claude 的著作物;Codex 的原生 memories 是生成态,不收——见 spec §3)。
    """
    out: list[tuple[str, Path]] = []
    shared = root / SHARED / "memory"
    if shared.is_dir():
        out.append((SHARED, shared))
    for owner in _owner_dirs(root):
        if owner.name == SHARED:
            continue
        d = owner / "claude" / "memory"
        if d.is_dir():
            out.append((owner.name, d))
    return out

def load_vault(root: Path) -> Vault:
    cfg_raw = tomllib.loads((root / "vault.toml").read_text(encoding="utf-8"))
    config = VaultConfig(version=int(cfg_raw.get("version", 1)))
    memories = []
    for origin, d in memory_dirs(root):
        for p in sorted(d.glob("*.md")):
            m = load_memory(p)
            m.origin = origin
            memories.append(m)
    return Vault(root=root, config=config, memories=memories)

def _tool_sources(raw: dict) -> ToolSources:
    return ToolSources(
        memory=list(raw.get("memory", [])),
        skills=raw.get("skills"),
        plugin_repos=raw.get("plugin_repos"),
        settings=raw.get("settings"),
        agents=raw.get("agents"),
    )

def load_device(root: Path, host: str) -> DeviceProfile:
    raw = tomllib.loads((root / host / "device.toml").read_text(encoding="utf-8"))
    return DeviceProfile(
        host=host,
        classes=list(raw.get("class", [])),
        projects=list(raw.get("projects", [])),
        paths=dict(raw.get("paths", {})),
        sources={k: _tool_sources(v) for k, v in raw.get("sources", {}).items()},
    )

class UnsupportedVaultVersion(RuntimeError):
    pass

def _read_version(root) -> int:
    return int(tomllib.loads((Path(root)/"vault.toml").read_text(encoding="utf-8")).get("version", 1))

def require_supported_version(root, max_known: int = 3) -> int:
    v = _read_version(root)
    if v > max_known:
        raise UnsupportedVaultVersion(
            f"金库版本 {v} 高于本 hub 所知（最高 {max_known}）——请先升级 hub，绝不按旧模型运行。")
    return v

def require_version_exactly(root, want: int) -> None:
    v = _read_version(root)
    if v != want:
        raise UnsupportedVaultVersion(f"本命令要求金库 version=={want}，当前是 {v}——先 `hub migrate-schema --to {want}`。")
