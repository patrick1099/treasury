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

    # 模型不认识的 frontmatter 键。**原样带着走,dump 时原样吐回去。**
    #
    # 备份区的立身之本是"别丢"。真实数据里 49/49 条记忆的 metadata 都带
    # originSessionId(curating-memory skill 靠它把记忆追回出生的那次会话)和
    # node_type —— 而 Memory 只认 7 个字段,dump_memory 只写这 7 个,于是进金库
    # 就**全没了**。从金库还原之后,那条线索对每一条记忆都断了。
    #
    # 模型该认的字段就那 7 个(hub 只对它们做判断);认不出来的**不代表不重要**,
    # 只代表**不归 hub 管**。不归它管的东西,它更没有资格丢。
    extra: dict = field(default_factory=dict)             # 未识别的**顶层**键
    extra_metadata: dict = field(default_factory=dict)    # 未识别的 **metadata:** 子键

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

@dataclass
class VaultConfig:
    version: int

@dataclass
class Vault:
    root: Path
    config: VaultConfig
    memories: list[Memory]
