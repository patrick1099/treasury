"""原始层 → 统一事件模型：五个源的原始行解析成 ParsedSession / ParsedEvent。

设计见 spec §8。每个源一个模块，统一导出 `parse(path) -> (ParsedSession,
list[ParsedEvent])`，由本包按源名字分派；dataclass 在 `model.py`，各源模块只认它，
不碰彼此的格式。

copilot-vscode 是增量日志（kind:0 全量快照、kind:1/2/3 增量），必须先重放才能拼出
requests[]，见 copilot_vscode.py 的 docstring 和 spec §8.3——它的 last_raw_line /
replay_upto_line 语义和其它源不一样，其它源这两个字段分别取行号和 None。
"""
from hub.chats.parse import claude, codex, copilot_cli, copilot_vscode, opencode
from hub.chats.parse.model import ParsedEvent, ParsedSession

PARSERS = {
    m.NAME: m for m in (claude, codex, opencode, copilot_cli, copilot_vscode)
}


class UnknownSource(KeyError):
    pass


def parse(source: str, path):
    """按源名字解析一份原始层文件。名字不认识就抛，别静默返回空结果。"""
    try:
        mod = PARSERS[source]
    except KeyError:
        raise UnknownSource(
            f"不认识的对话源 {source!r};已知的是 {sorted(PARSERS)}") from None
    return mod.parse(path)
