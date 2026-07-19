"""memory 下行视图核心：从 shared/memory **只扫一次**，全量 scope 预检，再在内存里按
(设备, 工具) 切出各工具子集，喂给渲染器。绝不各扫各的、也绝不经 load_vault 顺带解析
各设备未 promote 的记忆（那会被无关坏记忆炸到，且违反"只取 shared/memory 已闸门项"）。
"""
import os
from dataclasses import dataclass
from pathlib import Path
from hub.model import SHARED, DeviceProfile, Memory
from hub.frontmatter import load_memory
from hub.scope import parse_scope, scope_matches, ScopeError

class ViewScopeError(RuntimeError):
    pass

class SharedMemoryError(RuntimeError):
    pass

@dataclass
class MemoryViewEntry:
    name: str
    description: str
    scope: list[str]
    source: Path            # 绝对路径 <vault>/shared/memory/<name>.md

def _shared_memory_dir(vault_root: Path) -> Path:
    """<vault>/shared/memory；经链接逃出金库→抛（含 shared/memory 尚不存在但父目录是外链，
    故**无条件**比 realpath，不加 lexists 守卫）。"""
    d = Path(vault_root) / SHARED / "memory"
    expected = os.path.join(os.path.realpath(vault_root), SHARED, "memory")
    if os.path.realpath(d) != expected:
        raise SharedMemoryError(f"shared/memory 经链接逃出金库: {d} → {os.path.realpath(d)}")
    return d

def load_shared_memories(vault_root: Path) -> list[Memory]:
    """**只扫 shared/memory/**——不碰各设备备份区、不经 load_vault。落三条不变量（否则会索引
    错文件、覆盖 parsed[name]、甚至让视图指向不存在的路径）：容器不逃逸、文件 stem == frontmatter
    `name`、`name` 不重复。"""
    d = _shared_memory_dir(vault_root)
    out: list[Memory] = []
    seen: set[str] = set()
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            m = load_memory(p); m.origin = SHARED
            if m.name != p.stem:
                raise SharedMemoryError(
                    f"{p.name}: frontmatter name={m.name!r} 与文件名 stem={p.stem!r} 不一致")
            if m.name in seen:
                raise SharedMemoryError(f"shared/memory 有重名记忆: {m.name!r}")
            seen.add(m.name)
            out.append(m)
    return out

def validate_scopes(memories: list[Memory]) -> dict[str, dict]:
    """全量预检：任一 scope 非法 → 抛 ViewScopeError、点名全部坏文件。返回 {name: dims}。"""
    parsed, errors = {}, []
    for m in memories:
        try:
            parsed[m.name] = parse_scope(m.scope)
        except ScopeError as e:
            errors.append(f"{m.name}.md: scope={m.scope} — {e}")
    if errors:
        raise ViewScopeError(
            "shared/memory 有 scope 非法的记忆，视图生成中止、旧产物不动：\n  " + "\n  ".join(errors))
    return parsed

def entries_for_tool(memories: list[Memory], parsed: dict[str, dict],
                     vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """在内存里按 (设备 class/projects, 目标 tool) 过滤已扫好的一批——不重新扫盘。"""
    vault_root = Path(vault_root)
    out = [MemoryViewEntry(
               name=m.name, description=m.description, scope=m.scope,
               source=(vault_root / SHARED / "memory" / f"{m.name}.md").resolve())
           for m in memories
           if scope_matches(parsed[m.name], dev.classes, dev.projects, tool)]
    out.sort(key=lambda e: e.name)
    return out

def collect_view_entries(vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """单工具便捷入口（memory-read 用）。批量落盘走 load_shared_memories→validate_scopes→
    entries_for_tool 三步，只扫一次。"""
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)
    return entries_for_tool(mems, parsed, vault_root, dev, tool)
