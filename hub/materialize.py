from pathlib import Path
from hub.managed_block import replace_block
from hub.model import Memory, Target
from hub.scope import scope_matches
from hub.links import resolve_symbols
from hub.frontmatter import dump_memory

def render_agents_md(existing: str, rules: list[tuple[str, str]],
                     project_memory_inner: str = "") -> str:
    parts = []
    for _name, content in rules:
        parts.append(content.rstrip("\n"))
    if project_memory_inner.strip():
        parts.append(project_memory_inner.rstrip("\n"))
    inner = "\n\n".join(parts)
    return replace_block(existing, inner)

def render_claude_md(existing: str, memory_index_import: str | None = None) -> str:
    inner = "@AGENTS.md"
    if memory_index_import:
        inner += f"\n@{memory_index_import}"
    return replace_block(existing, inner)

def select_for_target(memories: list[Memory], target: Target) -> list[Memory]:
    out = []
    for m in memories:
        if m.sensitive:
            continue
        if scope_matches(m.scope, target):
            out.append(m)
    return out

def render_memory_bundle(memories: list[Memory], paths: dict[str, str]) -> str:
    chunks = []
    for m in memories:
        resolved, missing = resolve_symbols(m.body, paths)
        if missing:
            chunks.append(f"<!-- skipped {m.name}: 未定义符号根 {missing} -->")
            continue
        chunks.append(f"### {m.name}\n{resolved.rstrip(chr(10))}")
    return "\n\n".join(chunks) + ("\n" if chunks else "")

def codex_project_inner(memories: list[Memory], paths: dict[str, str]) -> str:
    body = render_memory_bundle(memories, paths)
    return "## 项目记忆(hub)\n" + body

def select_user_level(memories: list[Memory], device_classes: list[str],
                      tool: str) -> list[Memory]:
    """某工具的**用户级**记忆:命中本机 scope、且不是工程专属的。

    工程专属记忆有自己的落点(Claude 的工程 memory 目录 / 工程根的 AGENTS.md),
    塞进用户级会跨工程泄漏。
    """
    target = Target(frozenset(device_classes), None, tool)
    return [m for m in select_for_target(memories, target)
            if not any(s.startswith("project:") for s in m.scope)]

def resolved_body(m: Memory, paths: dict[str, str]) -> str | None:
    """记忆正文,符号根按本设备展开。有解析不出的符号根 → 返回 None(跳过,不写断链的文件)。"""
    body, missing = resolve_symbols(m.body, paths)
    return None if missing else body

def render_index(memories: list[Memory], body_dir: str) -> str:
    """索引:一行一条(名字 + 一句话摘要)。正文目录在头部说一次。

    **只放索引,不放全文**——照抄 Claude 原生记忆的做法:上下文里常驻的是索引,
    正文躺在文件里、用到了才读。47 条全文拼起来 85KB,每个会话吃一遍,不可接受。
    """
    head = (f"hub 维护,勿手改。下面只有摘要;需要细节时读 `{body_dir}/<名字>.md`。\n\n")
    rows = [f"- **{m.name}** — {m.description}"
            for m in sorted(memories, key=lambda x: x.name)]
    return head + "\n".join(rows) + "\n"

def render_codex_global_agents(existing: str, index: str) -> str:
    """Codex 的**用户级**知识落地口 = ~/.codex/AGENTS.md 的 managed block。

    不是 ~/.codex/memories/ ——那是个未经验证的假设:Codex 并不读那里的散装 md,
    它的 memories_*.sqlite 是自己从对话沉淀的内部流水线,不是给外部写文件的地方。
    AGENTS.md 才是 Codex 有文档、确知会读的指令文件。

    块里只放索引;正文在磁盘上,Codex 需要时自己去读。
    """
    return replace_block(existing, "## 记忆索引(hub)\n" + index)

def ensure_user_claude_import(existing: str, import_target: str) -> str:
    return replace_block(existing, f"@{import_target}")

from claude_migrate import encode_project_path

def claude_project_memory_dir(project_root: str, claude_home: Path) -> Path:
    return Path(claude_home) / "projects" / encode_project_path(str(project_root)) / "memory"

def select_claude_project(memories: list[Memory], project: str,
                          device_classes: list[str]) -> list[Memory]:
    """落进 Claude 工程记忆目录的那批:该工程专属的(全局的另有 bundle,不重复塞)。"""
    target = Target(frozenset(device_classes), project, "claude")
    return [m for m in select_for_target(memories, target)
            if f"project:{project}" in m.scope]
