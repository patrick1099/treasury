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

def parse_frontmatter(text: str) -> tuple[dict, str]:
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
    meta: dict = {}
    cur: dict = meta
    cur_key = None
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if ":" not in ln:
            raise FrontmatterError(f"无法解析行(子集外): {ln!r}")
        key, _, val = ln.strip().partition(":")
        key = key.strip()
        if indent == 0:
            if val.strip() == "":
                meta[key] = {}
                cur = meta[key]
                cur_key = key
            else:
                meta[key] = _coerce(val)
                cur = meta
        elif indent >= 2 and cur is not meta:
            # 一层嵌套；值不得再是空(=二层嵌套)
            if val.strip() == "":
                raise FrontmatterError(f"超出一层嵌套子集: {ln!r}")
            cur[key] = _coerce(val)
        else:
            raise FrontmatterError(f"缩进/结构越界: {ln!r}")
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
