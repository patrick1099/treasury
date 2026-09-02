"""memory 下行视图核心：从 shared/memory **只扫一次**，全量 scope 预检，再在内存里按
(设备, 工具) 切出各工具子集，喂给渲染器。绝不各扫各的、也绝不经 load_vault 顺带解析
各设备未 promote 的记忆（那会被无关坏记忆炸到，且违反"只取 shared/memory 已闸门项"）。
"""
import hashlib
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
    type: str = ""          # 内容类别(feedback 默认展开)
    # 阶段 B 生命周期字段:从 Memory 原样带过来。
    # type 是内容类别(feedback 默认展开);index 是显式 override(expanded 强制展开);
    # group 是折叠段分组名;archived 有值即归档。四个都进 shared_hash——渲染规则读它们,
    # 哈希不含这些字段,改了 group 而 status --check 仍判新鲜,视图不会重算(plan §3.3)。
    group: str | None = None
    archived: str | None = None
    index: str | None = None

_DEFAULT_GROUP = "未分组"

@dataclass
class ClassifiedEntries:
    """分层渲染的结构化结果:展开段(逐条 name+description)、折叠段(按 group 归组、
    只列名)、归档段(只列名)。这是**唯一**的判据出口——磁盘视图、Codex 受管块、将来的
    memory-explain / inventory 全从它取判定,绝不把 feedback/group/archived/index 的
    判定复制第二遍,那是下次改规则时四处不同步的种子(plan §3.4)。"""
    expanded: list[MemoryViewEntry]
    folded: dict[str, list[MemoryViewEntry]]     # 有序:具名组按组名升序,「未分组」垫底
    archived: list[MemoryViewEntry]

def classify_entries(entries: list[MemoryViewEntry]) -> ClassifiedEntries:
    """按 plan §3.2 的优先级自上而下判每条落哪段,命中即止:
      1. archived 有值 → 归档段(不论 type / index);
      2. index == expanded → 展开段(显式 override 优先于 type);
      3. type == feedback → 展开段(默认判据:开始行动前就必须约束行为);
      4. 其余 → 折叠段,按 group 归组;group 为 None 落缺省组「未分组」,
         排在所有具名组之后;具名组按组名升序,组内按 name 升序。

    为什么抽出来而不是写进 render:渲染只是消费方之一,规则将来要被 memory-explain /
    inventory 复用。规则只活在这一处,改规则就改这里——散在四处就是下次不同步的种子。"""
    expanded: list[MemoryViewEntry] = []
    folded: dict[str, list[MemoryViewEntry]] = {}
    archived: list[MemoryViewEntry] = []
    for e in entries:
        if e.archived is not None:
            archived.append(e)
        elif e.index == "expanded":
            expanded.append(e)
        elif e.type == "feedback":
            expanded.append(e)
        else:
            folded.setdefault(e.group if e.group is not None else _DEFAULT_GROUP, []).append(e)
    expanded.sort(key=lambda e: e.name)
    archived.sort(key=lambda e: e.name)
    named = {g: folded[g] for g in sorted(g for g in folded if g != _DEFAULT_GROUP)}
    if _DEFAULT_GROUP in folded:
        named[_DEFAULT_GROUP] = folded[_DEFAULT_GROUP]
    for members in named.values():
        members.sort(key=lambda e: e.name)
    return ClassifiedEntries(expanded=expanded, folded=named, archived=archived)

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

def _view_entry(m: Memory, vault_root: Path) -> MemoryViewEntry:
    """从 Memory 构造视图条目。entries_for_tool 与 memory-explain 共用这一处——构造逻辑
    散在两边，下一次加字段就会有一边漏带（和 plan §3.4 抽 classify_entries 是同一个理由）。"""
    return MemoryViewEntry(
        name=m.name, description=m.description, type=m.type, scope=m.scope,
        group=m.group, archived=m.archived, index=m.index,
        source=(Path(vault_root) / SHARED / "memory" / f"{m.name}.md").resolve())

def entries_for_tool(memories: list[Memory], parsed: dict[str, dict],
                     vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """在内存里按 (设备 class/projects, 目标 tool) 过滤已扫好的一批——不重新扫盘。"""
    out = [_view_entry(m, vault_root) for m in memories
           if scope_matches(parsed[m.name], dev.classes, dev.projects, tool)]
    out.sort(key=lambda e: e.name)
    return out
def collect_view_entries(vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """单工具便捷入口（memory-read 用）。批量落盘走 load_shared_memories→validate_scopes→
    entries_for_tool 三步，只扫一次。"""
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)
    return entries_for_tool(mems, parsed, vault_root, dev, tool)

EMPTY_VIEW_NOTE = "（当前设备/该工具无匹配共享记忆）"

_HASH_VERSION = "v3"

def shared_hash(memories: list[Memory]) -> str:
    """全部 shared 记忆内容的短哈希——status --check 用它判视图是否陈旧。
    输入含**所有**影响渲染的字段:格式版本 + name + type + description + body +
    scope + group + archived + index。缺一个就是静默失效:改了 group 而 status --check
    仍判新鲜,视图不会重算(plan §3.3)。版本前缀 v3 的用途是「正确失效 + 可诊断」:
    分层规则变了,旧视图在新规则下本来就不该被信任,先判 stale、refresh 后才 fresh。"""
    h = hashlib.sha256()
    for m in sorted(memories, key=lambda x: x.name):
        for part in (m.name, m.type, m.description, m.body, " ".join(m.scope),
                     m.group or "", m.archived or "", m.index or ""):
            h.update(part.encode("utf-8")); h.update(b"\0")
    return f"{_HASH_VERSION}:{h.hexdigest()[:16]}"

def expanded_entry_text(e: MemoryViewEntry) -> str:
    """展开段里一条记忆的实际渲染文本（不含行尾换行）。渲染器与 memory-explain 共用——
    explain 的字节数必须对这段真实文本算 len(text.encode("utf-8"))，另写估算公式必然和
    渲染分叉（plan §4 硬要求 2）。折叠/归档段里条目自己的实际文本就是它的 name。"""
    return f"- {e.name} — {e.description}"

def _render_layered_body(cls: ClassifiedEntries) -> str:
    """分层正文:展开/折叠/归档三段,空段整段不输出(连标题一起省掉)。view 文件与
    Codex 受管块共用,判定全在 classify_entries,这里只做排版。"""
    blocks: list[str] = []
    if cls.expanded:
        blocks.append("## 工作约束（%d）\n" % len(cls.expanded)
                      + "\n".join(expanded_entry_text(e) for e in cls.expanded))
    if cls.folded:
        total = sum(len(v) for v in cls.folded.values())
        lines = [f"## 其余（{total}）"]
        for group, members in cls.folded.items():
            lines.append(f"- {group}({len(members)}): " + " · ".join(e.name for e in members))
        blocks.append("\n".join(lines))
    if cls.archived:
        lines = [f"## 已归档（{len(cls.archived)}）",
                 "- " + " · ".join(e.name for e in cls.archived)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

def render_view_file(entries: list[MemoryViewEntry], tool: str, shared_hash: str = "") -> str:
    """~/.hub/views/<tool>/MEMORY.md：分层索引。展开段逐条 `- name — description`;
    折叠段 / 归档段只列名,同组名字用中点连成一行,判据见 classify_entries。
    **不输出绝对路径**——memread 是按名查到条目后从内存里的 MemoryViewEntry.source 取路径,
    渲染文本里的路径没有任何消费者,却占了视图近四成体积(render_codex_block 一直如此)。
    **不输出 scope**——视图本身就是 scope 过滤后的结果,再印一遍是同义反复。
    头部嵌 shared_hash 供新鲜度比对。"""
    head = (f"<!-- 自动生成，勿手改：hub memory 视图（{tool}）。正文用 $hub-memory skill 按名读 -->\n"
            f"<!-- shared_hash: {shared_hash} -->\n"
            f"# 共享记忆索引 — {tool}\n\n")
    if not entries:
        return head + EMPTY_VIEW_NOTE + "\n"
    return head + _render_layered_body(classify_entries(entries)) + "\n"

def render_codex_block(entries: list[MemoryViewEntry], shared_hash: str = "") -> str:
    """Codex AGENTS.md 内联索引:与 render_view_file 同一分层结构、同一判定函数。
    同样嵌 shared_hash——status --check 才能发现「视图写好了但 AGENTS.md 块没跟上」
    的半截状态(plan §3.3 补的洞)。无绝对路径、无 scope、无反引号包名。"""
    head = ("## 共享记忆索引（自动生成，勿手改）\n\n"
            f"<!-- shared_hash: {shared_hash} -->\n")
    if not entries:
        return head + EMPTY_VIEW_NOTE + "\n"
    tail = "\n\n正文请用 `$hub-memory` skill 按名读取；不要一次性加载全部正文。\n"
    return head + _render_layered_body(classify_entries(entries)) + tail
