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

def write_claude_index(memories: list[Memory], paths: dict[str, str],
                       claude_home: Path, device_classes: list[str]) -> Path:
    target = Target(frozenset(device_classes), None, "claude")
    selected = select_for_target(memories, target)
    out = Path(claude_home) / "hub" / "memory-index.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_memory_bundle(selected, paths),
                   encoding="utf-8", newline="\n")
    return out

def write_codex_user_memories(memories: list[Memory], paths: dict[str, str],
                              codex_mem_dir: Path, device_classes: list[str]) -> list[str]:
    target = Target(frozenset(device_classes), None, "codex")
    d = Path(codex_mem_dir)
    d.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for m in select_for_target(memories, target):
        if any(s.startswith("project:") for s in m.scope):
            continue
        (d / f"{m.name}.md").write_text(dump_memory(m), encoding="utf-8", newline="\n")
        written.append(m.name)
    return written

def ensure_user_claude_import(existing: str, import_target: str) -> str:
    return replace_block(existing, f"@{import_target}")
