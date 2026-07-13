"""提取器:把本机各工具的家当收进金库的备份区。

铁律:只写 <本机>/,不碰 shared/,不碰别的设备,不写任何工具的地盘。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.collect.decl import DeclResult, collect_claude_decl, collect_codex_decl
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
            if p.is_file():
                w.write_text(home / "claude" / p.name, p.read_text(encoding="utf-8"))

    cx = dev.sources.get("codex")
    if cx:
        rep.skills["codex"] = collect_skills(
            Path(cx.skills) if cx.skills else None, home / "codex" / "skills", w)
        rep.decl["codex"] = collect_codex_decl(
            Path(cx.settings) if cx.settings else None, home / "codex", w)
        if cx.agents:
            p = Path(cx.agents)
            check_source(p)                 # 硬闸:agents(AGENTS.md)源文件
            if p.is_file():
                w.write_text(home / "codex" / p.name, p.read_text(encoding="utf-8"))

    if not w.dry_run and home.is_dir():
        rep.hits = scan_tree(home)      # 软提醒：扫刚落进金库的东西
    return rep
