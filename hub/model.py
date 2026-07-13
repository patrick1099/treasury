from dataclasses import dataclass, field
from pathlib import Path

SHARED = "shared"           # 共享区，与各设备文件夹同级

@dataclass
class Memory:
    name: str
    description: str
    type: str
    scope: list[str]
    portable: bool
    sensitive: bool
    body: str
    path: Path | None = None
    # 归属 = 金库顶层文件夹名：SHARED 或某台设备的 host
    origin: str | None = None

@dataclass
class ToolSources:
    """一台设备上、某个工具的源路径。缺的项就是本机没有,不是错误。"""
    memory: list[str] = field(default_factory=list)
    skills: str | None = None
    plugin_repos: str | None = None     # 自己写的插件仓所在目录（Claude 的 plugins-dev）
    settings: str | None = None         # claude: settings.json ; codex: config.toml
    agents: str | None = None           # claude: CLAUDE.md ; codex: AGENTS.md

@dataclass
class DeviceProfile:
    host: str
    classes: list[str]
    projects: list[str]
    paths: dict[str, str]
    sources: dict[str, ToolSources] = field(default_factory=dict)   # "claude" / "codex"

@dataclass(frozen=True)
class Target:
    device_classes: frozenset[str]
    project: str | None
    tool: str

@dataclass
class VaultConfig:
    version: int

@dataclass
class Vault:
    root: Path
    config: VaultConfig
    memories: list[Memory]
