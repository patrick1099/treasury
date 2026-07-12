from dataclasses import dataclass, field
from pathlib import Path

SHARED = "shared"           # 公共池，与各设备文件夹同级；所有设备无条件落地

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
    # 来源 = 金库顶层的归属文件夹名：SHARED 或某台设备的 host。
    origin: str | None = None

@dataclass
class ProjectTarget:
    project: str
    root: str

@dataclass
class DeviceProfile:
    host: str
    classes: list[str]
    projects: list[str]
    paths: dict[str, str]
    targets: list[ProjectTarget] = field(default_factory=list)
    collect_sources: list[str] = field(default_factory=list)

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
    root: "Path"
    config: VaultConfig
    memories: list[Memory]
    rules: list[tuple[str, str]]
