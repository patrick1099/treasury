"""Claude Code 的会话发现:扫 ~/.claude/projects/<编码工程路径>/ 下的 *.jsonl。

只负责**发现** artifact,不落盘。落盘归 collect.py。

`rel` 必须带上工程目录名(`sessions/<project_dir>/<sessionId>.jsonl`),不能平铺进
`sessions/` —— 两个工程目录下完全可能撞同名 session(真机 33 个工程目录、97 个会话),
平铺会被 append-only 状态机当成同一个 artifact 互相覆盖。

`projects/<工程>/` 下面除了 `*.jsonl`,还有一些以会话 uuid 命名的**子目录**
(tool-results 之类),它们不是会话。`projects/*/*.jsonl` 这个 glob 天然只匹配工程
目录下的直接文件,不跨进子目录。

`meta["x_project_dir"]` 是那个编码过的工程目录名,是回溯真实工程路径的唯一线索
(会话里 `cwd` 虽是明文路径,但编码名才是稳定的链接锚点)。
"""
from pathlib import Path

from ..model import Artifact, COPY, TRANSCRIPT
from ...guard import check_source
from ...collect.errors import require_source

NAME = "claude"


def discover(root: Path) -> list[Artifact]:
    check_source(root)
    root = require_source(root, NAME, kind="dir")
    arts = []
    for p in sorted(root.glob("projects/*/*.jsonl")):
        project_dir = p.parent.name
        arts.append(Artifact(
            rel=f"sessions/{project_dir}/{p.stem}.jsonl",
            session_id=p.stem,
            kind=COPY,
            role=TRANSCRIPT,
            src=p,
            meta={"x_project_dir": project_dir},
        ))
    return arts