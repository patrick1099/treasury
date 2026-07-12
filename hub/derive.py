from hub.model import Memory

def _rel(m: Memory) -> str:
    return f"{m.origin}/memory/{m.name}.md" if m.origin else f"{m.name}.md"

def render_memory_index(memories: list[Memory]) -> str:
    """金库总览索引。链接带上归属文件夹，一眼看得出哪条是公共的、哪条是哪台设备产的。"""
    header = "<!-- 自动生成，勿手改：由 hub 从各 <归属>/memory/*.md frontmatter 派生 -->\n"
    rows = [f"- [{m.name}]({_rel(m)}) — {m.description}"
            for m in sorted(memories, key=lambda x: (x.origin or "", x.name))]
    return header + "\n".join(rows) + "\n"
