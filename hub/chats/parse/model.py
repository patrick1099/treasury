"""统一事件模型：五个源解析出来的共同形状（spec §8 派生层）。

定位符优先级 native_id → source_key → s<seq>（spec §8.1）：seq 是派生序号，源一
重写、重放规则一变、插入一条 meta 就漂移，不能单独当定位符，所以 native_id 必须
尽量填。replay_upto_line 只有增量日志源（copilot-vscode）用——普通源直接 None。
"""
from dataclasses import dataclass


@dataclass
class ParsedSession:
    session_id: str
    started_at: int | None = None
    ended_at: int | None = None
    cwd: str = ""
    repo: str = ""
    branch: str = ""
    model: str = ""
    title: str = ""


@dataclass
class ParsedEvent:
    seq: int
    native_id: str = ""
    source_key: str = ""
    ts: int | None = None
    role: str = ""
    kind: str = ""
    tool: str = ""
    text: str = ""
    last_raw_line: int = 0
    replay_upto_line: int | None = None
