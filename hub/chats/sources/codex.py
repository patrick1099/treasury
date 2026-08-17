"""Codex 的会话发现:扫 ~/.codex/sessions/**/rollout-*.jsonl 与 archived_sessions/。

只负责**发现** artifact,不落盘。

`sessions/` 自带 YYYY/MM/DD 日期分层,真机 747 个文件,平铺进一个目录不可接受,
所以 `rel` 保留相对 `sessions/` 的原路径,不拍平。`archived_sessions/` 是扁平的,
统一落进 `sessions/archived/<name>`。

`session_id` 从文件名 `rollout-<ISO>-<uuid>.jsonl` 里取那个 uuid。Iso 时间戳在
Windows 上不能含 `:`,只能全用 `-` 分隔,和 uuid 自己带的分隔符叠在一起,靠字符串
切不可靠 —— 用正则直接定位 8-4-4-4-12 的十六进制组才稳。取不出来就退回 stem,
那是定位用的兜底,不是错误,不许抛。
"""
import re
from pathlib import Path

from ..model import Artifact, COPY, TRANSCRIPT
from ...guard import check_source
from ...collect.errors import require_source

NAME = "codex"

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _session_id(name: str) -> str:
    m = _UUID_RE.search(name)
    return m.group(0) if m else Path(name).stem


def discover(root: Path) -> list[Artifact]:
    check_source(root)
    root = require_source(root, NAME, kind="dir")
    arts = []
    sessions_dir = root / "sessions"
    for f in sorted(sessions_dir.glob("**/rollout-*.jsonl")):
        rel = "sessions/" + f.relative_to(sessions_dir).as_posix()
        arts.append(Artifact(
            rel=rel,
            session_id=_session_id(f.name),
            kind=COPY,
            role=TRANSCRIPT,
            src=f,
        ))
    for f in sorted((root / "archived_sessions").glob("rollout-*.jsonl")):
        arts.append(Artifact(
            rel=f"sessions/archived/{f.name}",
            session_id=_session_id(f.name),
            kind=COPY,
            role=TRANSCRIPT,
            src=f,
        ))
    return arts