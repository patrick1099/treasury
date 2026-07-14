"""软提醒:扫疑似密钥。**只报告,不阻断。**

误报率高到不能当闸——实测扫 plugins-dev 的 10 条命中全是误报(`sk-` 撞上
`task-fix3-report`)。阻断只会逼人无脑加白名单,闸就废了。

它的用途是**提醒你打 sensitive 标 / 把密钥挪进 ~/.claude/secrets/**。
真正的硬闸在 hub/guard.py。
"""
import re
from dataclasses import dataclass
from pathlib import Path

# 已知前缀 —— 边界靠 (?<![\w-]) 挡掉 "task-fix3" 这类误撞
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai", re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{20,}")),
    ("github", re.compile(r"(?<![\w-])ghp_[A-Za-z0-9]{28,}")),
    ("aws",    re.compile(r"(?<![\w-])AKIA[0-9A-Z]{16}")),
    ("aliyun", re.compile(r"(?<![\w-])LTAI[A-Za-z0-9]{12,}")),
    ("jwt",    re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")),
]


@dataclass
class Hit:
    path: Path
    line: int
    kind: str
    sample: str


def _redact(s: str) -> str:
    return s[:8] + "…"          # 只给前缀，不把明文抄进 transcript


def scan_text(text: str, path: Path) -> list[Hit]:
    hits = []
    for i, ln in enumerate(text.splitlines(), start=1):
        for kind, pat in _PATTERNS:
            m = pat.search(ln)
            if m:
                hits.append(Hit(path=Path(path), line=i, kind=kind,
                                sample=_redact(m.group(0))))
    return hits


def scan_tree(root: Path) -> list[Hit]:
    hits = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue            # 读不了 → 跳过
        if b"\x00" in data:
            continue            # 含 NUL 字节 → 判定为二进制,跳过
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue            # 非法编码 → 跳过
        hits.extend(scan_text(text, p))
    return hits
