from pathlib import Path
from hub.frontmatter import load_memory, dump_memory, FrontmatterError

_DERIVED = {"MEMORY.md", "memory-index.md"}

def collect_memories(source_dirs: list[Path], vault_memory_dir: Path) -> list[str]:
    vault_memory_dir.mkdir(parents=True, exist_ok=True)
    collected: list[str] = []
    for d in source_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.name in _DERIVED:
                continue
            try:
                m = load_memory(p)
            except FrontmatterError:
                continue
            if m.sensitive:
                continue
            (vault_memory_dir / f"{m.name}.md").write_text(
                dump_memory(m), encoding="utf-8")
            collected.append(m.name)
    return collected
