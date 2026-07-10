from hub.model import Memory

def render_memory_index(memories: list[Memory]) -> str:
    header = "<!-- 自动生成，勿手改：由 hub 从各 memory/*.md frontmatter 派生 -->\n"
    rows = [f"- [{m.name}]({m.name}.md) — {m.description}"
            for m in sorted(memories, key=lambda x: x.name)]
    return header + "\n".join(rows) + "\n"
