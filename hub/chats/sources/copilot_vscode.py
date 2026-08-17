"""Copilot VS Code 的会话发现:扫 workspaceStorage/<hash>/chatSessions/*.jsonl。

只负责**发现** artifact,不落盘。落盘归 collect.py。

`root` **由调用方传绝对路径**(本机是 %APPDATA%/Code/User)——模块内绝不读环境
变量,否则测试没法把 root 指到 tmp_path。调用方负责把 root 解析成已配置的绝对路径。

这些会话文件后缀真机上是 `.jsonl`(不是 `.json`),且是**增量日志**:`kind:0` 全量
快照、`kind:1/2` 是增量。这里只负责把文件列出来,不解析——重放归 parse 层。

`rel` 带 workspace 的 hash(`sessions/<hash>/<name>`):hash 是 workspaceStorage 下
的目录名,不同 workspace 的会话撞名全靠它区分,平铺会互相覆盖。

额外产出一个 GENERATED + role=AUXILIARY 的 `workspaces.toml`:把每个**有
chatSessions 目录**的 <hash> 映射到 `workspaceStorage/<hash>/workspace.json` 的
`folder` 或 `workspace` 值。这两个键真机上都有——单文件夹工作区用 `folder`,
多根/命名工作区用 `workspace`;两个都没有就记空串,**不抛**。没有这张表,那串
hash 就是废字符串——索引层想补 session 的工程路径时无从下手,所以这条不是可选项。

用 `hub/tomlout.py` 的 `dump_toml` 生成内容,按 hash 排序保证两次生成字节相同
(否则 append-only 的幂等当场失效)。
"""
import json
from pathlib import Path

from ..model import Artifact, COPY, GENERATED, TRANSCRIPT, AUXILIARY
from ...guard import check_source
from ...collect.errors import require_source
from ...tomlout import dump_toml

NAME = "copilot-vscode"


def _workspace_label(ws_dir: Path) -> str:
    """workspace.json 里取 folder / workspace 值。两个键都可能,都没有记空串,不抛。

    workspace.json 缺失或解析失败也算"没有值"——宁可记空串,也不能让一个坏工作区
    把整次 discover 炸掉,那会连累其它完好的会话一个都收不上来。
    """
    wj = ws_dir / "workspace.json"
    if not wj.is_file():
        return ""
    try:
        data = json.loads(wj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        for key in ("folder", "workspace"):
            v = data.get(key)
            if isinstance(v, str):
                return v
    return ""


def discover(root: Path) -> list[Artifact]:
    check_source(root)
    root = require_source(root, NAME, kind="dir")
    arts = []
    mapping = {}
    storage = root / "workspaceStorage"
    if storage.is_dir():
        for ws in sorted(storage.iterdir()):
            if not ws.is_dir():
                continue
            chat = ws / "chatSessions"
            if not chat.is_dir():
                continue
            h = ws.name
            for f in sorted(chat.glob("*.jsonl")):
                arts.append(Artifact(
                    rel=f"sessions/{h}/{f.name}",
                    session_id=f.stem,
                    kind=COPY,
                    role=TRANSCRIPT,
                    src=f,
                ))
            mapping[h] = _workspace_label(ws)
    toml = dump_toml([("workspaces", dict(sorted(mapping.items())))])
    arts.append(Artifact(
        rel="workspaces.toml",
        kind=GENERATED,
        role=AUXILIARY,
        payload=toml.encode("utf-8"),
        lines=toml.count("\n"),
    ))
    return arts