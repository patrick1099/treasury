from pathlib import Path
from hub.model import Memory

class FrontmatterError(ValueError):
    pass

def _coerce(v: str):
    s = v.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [x.strip() for x in inner.split(",")]
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    return s

def _indent_of(ln: str) -> int:
    return len(ln) - len(ln.lstrip(" "))

def _parse_block_list(lines: list[str], i: int, indent: int) -> tuple[list, int]:
    """从第 i 行开始收集缩进为 indent 的 '- item' 行,直到缩进变化或不再是列表项。"""
    n = len(lines)
    items: list = []
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if _indent_of(ln) != indent:
            break
        stripped = ln.strip()
        if not stripped.startswith("- "):
            break
        items.append(stripped[2:].strip())
        i += 1
    return items, i

def _parse_mapping(lines: list[str], i: int, indent: int) -> tuple[dict, int]:
    """从第 i 行开始解析缩进为 indent 的一层 'key: value' 映射。

    值为空时向下看一行:缩进 +2 且以 '- ' 开头 → 块状列表;
    缩进 +2 且是 'key: value' → 一层嵌套表(仅当 indent == 0 时允许,不然越界);
    否则视为空表(兼容旧行为)。
    """
    n = len(lines)
    result: dict = {}
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        cur_indent = _indent_of(ln)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise FrontmatterError(f"缩进/结构越界: {ln!r}")
        stripped = ln.strip()
        if stripped.startswith("- "):
            raise FrontmatterError(f"块状列表没有对应的键: {ln!r}")
        if ":" not in ln:
            raise FrontmatterError(f"无法解析行(子集外): {ln!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if val != "":
            result[key] = _coerce(val)
            i += 1
            continue

        # 值为空 —— 向下看一行判断是块状列表、嵌套表还是空表
        j = i + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n or _indent_of(lines[j]) <= indent:
            # 没有更深缩进的后续行 —— 空表(兼容旧行为),下一轮循环重新处理 j 行
            result[key] = {}
            i += 1
            continue

        child_indent = _indent_of(lines[j])
        if child_indent != indent + 2:
            raise FrontmatterError(f"缩进/结构越界: {lines[j]!r}")

        if lines[j].strip().startswith("- "):
            items, j = _parse_block_list(lines, j, child_indent)
            result[key] = items
            i = j
        else:
            if indent != 0:
                raise FrontmatterError(f"超出一层嵌套子集: {lines[j]!r}")
            sub, j = _parse_mapping(lines, j, child_indent)
            result[key] = sub
            i = j
    return result, i

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """YAML 的一个受控子集:标量、一层嵌套、行内列表 [a, b]、块状列表(- a)。

    块状列表必须支持——Claude 自己写记忆时用的就是这个形式。
    """
    if not text.startswith("---"):
        raise FrontmatterError("缺少 frontmatter 起始 ---")
    lines = text.splitlines()
    if lines[0].strip() != "---":
        raise FrontmatterError("首行必须是 ---")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise FrontmatterError("缺少 frontmatter 结束 ---")

    meta, _ = _parse_mapping(lines[1:end], 0, 0)

    body = "\n".join(lines[end + 1:])
    if body and not body.endswith("\n"):
        body += "\n"
    return meta, body

def load_memory(path: Path) -> Memory:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    md = meta.get("metadata", {})
    return Memory(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        type=md.get("type", "reference"),
        scope=md.get("scope", ["global"]),
        portable=bool(md.get("portable", True)),
        sensitive=bool(md.get("sensitive", False)),
        body=body,
        path=path,
    )

def _fmt_list(xs: list[str]) -> str:
    return "[" + ", ".join(xs) + "]"

def dump_memory(m: Memory, body: str | None = None) -> str:
    """序列化一条记忆。body 给了就用它替代 m.body(落地时用符号根展开后的正文)。"""
    lines = [
        "---",
        f"name: {m.name}",
        f"description: {m.description}",
        "metadata:",
        f"  type: {m.type}",
        f"  scope: {_fmt_list(m.scope)}",
        f"  portable: {str(m.portable).lower()}",
        f"  sensitive: {str(m.sensitive).lower()}",
        "---",
    ]
    b = m.body if body is None else body
    if not b.endswith("\n"):
        b += "\n"
    return "\n".join(lines) + "\n" + b
