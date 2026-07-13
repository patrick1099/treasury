from pathlib import Path
from hub.model import Memory

def render_memory_index(memories: list[Memory], vault_root: Path) -> str:
    """金库总览索引。链接是相对金库根的真实路径,一眼看得出哪条是共享的、哪条是哪台设备的。

    这是**派生物**,每次重算。C 阶段的 skill 靠它决定读哪几条正文,
    不必把全文塞进上下文(47 条全文 85 KB,索引 7.3 KB)。
    """
    header = "<!-- 自动生成，勿手改：由 hub 从各 memory/*.md 的 frontmatter 派生 -->\n"
    rows = []
    for m in sorted(memories, key=lambda x: (x.origin or "", x.name)):
        rel = Path(m.path).relative_to(vault_root).as_posix() if m.path else f"{m.name}.md"
        rows.append(f"- [{m.name}]({rel}) — {m.description}")
    return header + "\n".join(rows) + "\n"
