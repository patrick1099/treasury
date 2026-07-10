import re

# 盘符绝对路径 C:\ 或 C:/ ；UNC \\host\ ；POSIX 绝对 /a/b（排除行内 http:// 之类由前置空白/行首约束）
_ABS = re.compile(r"(?<![\w$:/])(?:[A-Za-z]:[\\/]|\\\\[^\s]|/[A-Za-z0-9_.]+/)[^\s)>\]]*")
_SYM = re.compile(r"\$([A-Z][A-Z0-9_]*)(/[^\s)>\]]*)?")

def lint_raw_paths(body: str) -> list[str]:
    hits = []
    for m in _ABS.finditer(body):
        frag = m.group(0)
        if frag.startswith("$"):
            continue
        hits.append(frag)
    return hits

def resolve_symbols(body: str, paths: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    def sub(m: re.Match) -> str:
        root = m.group(1)
        rest = m.group(2) or ""
        if root not in paths:
            if root not in missing:
                missing.append(root)
            return m.group(0)
        base = paths[root].rstrip("/")
        return base + rest
    out = _SYM.sub(sub, body)
    return out, missing
