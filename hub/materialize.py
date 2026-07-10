from hub.managed_block import replace_block
from hub.model import Memory, Target
from hub.scope import scope_matches
from hub.links import resolve_symbols

def render_agents_md(existing: str, rules: list[tuple[str, str]],
                     project_memory_inner: str = "") -> str:
    parts = []
    for _name, content in rules:
        parts.append(content.rstrip("\n"))
    if project_memory_inner.strip():
        parts.append(project_memory_inner.rstrip("\n"))
    inner = "\n\n".join(parts)
    return replace_block(existing, inner)

def render_claude_md(existing: str, memory_index_import: str) -> str:
    inner = f"@AGENTS.md\n@{memory_index_import}"
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
