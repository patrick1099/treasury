"""解析层共享的小工具：时间解析、紧凑 JSON、坏行兜底。

三个源（claude / codex / copilot-cli）的时间戳是 ISO8601 字符串，opencode 与
copilot-vscode 直接是 epoch 毫秒整数，统一在这里转成毫秒。

`compact_json` 给 meta / tool 类事件兜底文本：源码里有超大附件 base64、工具输出、
系统提示词，直接整段塞进 FTS 会撑爆索引，所以超长一律截断并加标记。原始层那行字节
不受影响——索引只是派生层，截断的是"可检索副本"，不是证据本身。
"""
import datetime
import json

from .model import ParsedEvent

MAX_TEXT = 20000
TRUNC_MARK = "\u2026<截断>"


def iso_to_ms(s):
    """ISO8601 字符串 → epoch 毫秒；解析不了返回 None（行号照记，不抛）。"""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return None


def compact_json(obj, max_len=MAX_TEXT):
    """obj → 紧凑 JSON，超长截断。逗号/冒号无空格分隔，跟 opencode 导出同款风格。"""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if len(text) > max_len:
        return text[:max_len] + TRUNC_MARK
    return text


def join_text(items, max_len=MAX_TEXT):
    """[{"type":..,"text":..},...] 这类元素列表拼成一段文本；不是这种形状返回空串。"""
    parts = []
    if isinstance(items, list):
        for el in items:
            if isinstance(el, dict) and isinstance(el.get("text"), str):
                parts.append(el["text"])
    text = "\n".join(parts)
    if len(text) > max_len:
        return text[:max_len] + TRUNC_MARK
    return text


def bad_line_event(seq, lineno, raw):
    """JSON 解析失败的坏行 → 一条 meta，text 存原始行前 500 字符（spec §8.2）。"""
    return ParsedEvent(seq=seq, kind="meta", text=raw[:500], last_raw_line=lineno)


def meta_event(seq, lineno, obj, ts=None, native_id="", source_key=""):
    """映射不出 role/kind 的行 → 一条 meta，text 存该行紧凑 JSON，行号照记。"""
    return ParsedEvent(seq=seq, native_id=native_id, source_key=source_key,
                       ts=ts, kind="meta", text=compact_json(obj),
                       last_raw_line=lineno)


def number(events):
    """给事件排会话内序号（1 起）。seq 只用于排序与显示，不是定位符。"""
    for i, e in enumerate(events, 1):
        e.seq = i
    return events
