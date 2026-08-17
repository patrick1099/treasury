"""Copilot CLI 的会话发现:扫 ~/.copilot/session-state/<uuid>/。

只负责**发现** artifact,不落盘。落盘归 collect.py。

`session-state/` 下每个会话一个以 uuid 命名的目录。真机上**有的会话目录根本没有
`events.jsonl`**(实测两个会话里就有一个是这样)——没有正文,就没法建会话,跳过。

跳过信息怎么表达(契约是 `discover(root) -> list[Artifact]`,返回值塞不下):
- `discover(root)` 仍返回纯 artifact 列表,保持对 collect.py 的契约;
- 另导出一个 `skipped(root) -> list[tuple[str, str]]`,每个元素是 (uuid, 原因);
- 两者共用同一个内部扫描器,扫一遍够用,不会读两遍盘。
collect.py(或谁要报告跳过)调 `skipped` 即可;manifest / 落盘只认 discover 的返回值。

同目录的 `inuse.*.lock` / `session.db` / `checkpoints/` / `files/` / `research/` /
`rewind-file-snapshots/` 一概不收——它们不是对话正文,是运行态副产物,收了只会让
manifest 记一堆没用的身份。

`workspace.yaml` 是辅助证据(会话里的工程上下文),role=AUXILIARY:同样 append-only
收进来,但索引层不建 session、不产 event,只在补 session 工程信息时读它。它只在
`events.jsonl` 存在时才收——没有正文的会话目录整个跳过,连它的辅助文件也不收。
"""
from pathlib import Path

from ..model import Artifact, COPY, TRANSCRIPT, AUXILIARY
from ...guard import check_source
from ...collect.errors import require_source

NAME = "copilot-cli"


def _scan(root: Path):
    arts = []
    skipped = []
    state = root / "session-state"
    if state.is_dir():
        for d in sorted(state.iterdir()):
            if not d.is_dir():
                continue
            ev = d / "events.jsonl"
            if not ev.is_file():
                skipped.append((d.name, "会话目录没有 events.jsonl"))
                continue
            arts.append(Artifact(
                rel=f"sessions/{d.name}/events.jsonl",
                session_id=d.name,
                kind=COPY,
                role=TRANSCRIPT,
                src=ev,
            ))
            wy = d / "workspace.yaml"
            if wy.is_file():
                arts.append(Artifact(
                    rel=f"sessions/{d.name}/workspace.yaml",
                    session_id=d.name,
                    kind=COPY,
                    role=AUXILIARY,
                    src=wy,
                ))
    return arts, skipped


def discover(root: Path) -> list[Artifact]:
    check_source(root)
    root = require_source(root, NAME, kind="dir")
    arts, _ = _scan(root)
    return arts


def skipped(root: Path) -> list[tuple[str, str]]:
    """哪些会话目录被跳过了、为什么。见模块 docstring 的"跳过信息怎么表达"。"""
    check_source(root)
    root = require_source(root, NAME, kind="dir")
    _, skips = _scan(root)
    return skips