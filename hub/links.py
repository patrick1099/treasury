import re
from pathlib import Path

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

def load_lint_exempt(vault_root: Path) -> set[str]:
    """读取金库根的 lint-exempt.txt：一行一个记忆 name，被列出的记忆跳过裸路径检查。

    这些记忆正文里的绝对路径是信息性备注（“装在哪 / 笔记在哪”），非跨设备链接，
    无符号根可映射；豁免只放行裸路径这一项，scope 非法与 sensitive 泄漏仍硬拦。
    # 开头为注释，空行忽略。文件缺失时返回空集（无豁免）。
    """
    p = vault_root / "lint-exempt.txt"
    if not p.exists():
        return set()
    names: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        names.add(s)
    return names

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
