from hub.managed_block import replace_block

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
