"""提取器:把本机各工具的家当收进金库的备份区。

铁律:只写 <本机>/,不碰 shared/,不碰别的设备,不写任何工具的地盘。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.collect.decl import DeclResult, collect_claude_decl, collect_codex_decl
from hub.collect.errors import MissingSourceError, require_source
from hub.collect.memory import MemoryResult, collect_memory, plan_memory
from hub.collect.skills import collect_skills
from hub.guard import check_source
from hub.model import DeviceProfile
from hub.secrets_scan import Hit, scan_tree
from hub.writer import Writer

@dataclass
class CollectReport:
    memory: MemoryResult = field(default_factory=MemoryResult)
    skills: dict[str, list[str]] = field(default_factory=dict)
    decl: dict[str, DeclResult] = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)

_FILE_SOURCES = ("settings", "agents")      # 这两个是文件,其余是目录

def preflight(dev: DeviceProfile) -> None:
    """写任何东西之前,把 device.toml 里**配了的**源全部验一遍:密钥硬闸 + 必须存在。

    为什么要单独走一遍(每条流水线里已经各自查过了):流水线是**边验边写**的。
    等 collect_memory 写完 49 条记忆、collect_skills 才发现 skills 路径不存在,
    金库就停在一个"写了一半"的状态上——而 run_all 是整个提取器唯一的写入序列,
    它不该有中途暴毙的姿势。先验后写:要么全做,要么什么都没做。
    """
    for tool, src in dev.sources.items():
        for d in src.memory:
            check_source(Path(d))
            require_source(d, f"[sources.{tool}] memory 里的一项")
        for key in ("skills", "plugin_repos"):
            v = getattr(src, key)
            if v:
                check_source(Path(v))
                require_source(v, f"[sources.{tool}] {key}")
        for key in _FILE_SOURCES:
            v = getattr(src, key)
            if v:
                check_source(Path(v))
                require_source(v, f"[sources.{tool}] {key}", kind="file")

def plan_deletions(vault_root: Path, dev: DeviceProfile) -> list[str]:
    """这次 collect 会从金库删掉哪些记忆。给 CLI 拿去问人。"""
    src = dev.sources.get("claude")
    dirs = [Path(s) for s in (src.memory if src else [])]
    return plan_memory(dirs, vault_root, dev.host).deleted

def run_all(vault_root: Path, dev: DeviceProfile, w: Writer) -> CollectReport:
    vault_root = Path(vault_root)
    home = vault_root / dev.host
    rep = CollectReport()

    cl = dev.sources.get("claude")
    if cl:
        rep.memory = collect_memory([Path(s) for s in cl.memory], vault_root, dev.host, w)
        rep.skills["claude"] = collect_skills(
            Path(cl.skills) if cl.skills else None, home / "claude" / "skills", w)
        rep.decl["claude"] = collect_claude_decl(
            Path(cl.plugin_repos) if cl.plugin_repos else None,
            Path(cl.settings) if cl.settings else None,
            home / "claude", w)
        if cl.agents:
            p = Path(cl.agents)
            check_source(p)                 # 硬闸:agents(CLAUDE.md)源文件
            require_source(p, "[sources.claude] agents", kind="file")
            w.copy_file(p, home / "claude" / p.name)    # copy_file 自己也过一遍闸

    cx = dev.sources.get("codex")
    if cx:
        rep.skills["codex"] = collect_skills(
            Path(cx.skills) if cx.skills else None, home / "codex" / "skills", w)
        rep.decl["codex"] = collect_codex_decl(
            Path(cx.settings) if cx.settings else None, home / "codex", w)
        if cx.agents:
            p = Path(cx.agents)
            check_source(p)                 # 硬闸:agents(AGENTS.md)源文件
            require_source(p, "[sources.codex] agents", kind="file")
            w.copy_file(p, home / "codex" / p.name)     # copy_file 自己也过一遍闸

    if not w.dry_run and home.is_dir():
        rep.hits = scan_tree(home)      # 软提醒：扫刚落进金库的东西
    return rep
