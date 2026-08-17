"""claude 源解析器：一行一条 JSON，user/assistant 行的 message.content[] 逐元素展开。

spec §8.2：role 从 type（user/assistant）来，message.role 兜底；kind 从
message.content[].type 来（text / thinking→reasoning / tool_use→tool_call /
tool_result）。同一行展开的多个 event 共享同一个 last_raw_line，用
source_key = f"{uuid}#c{i}" 区分——没有原生 id 时定位就靠它。

注意 message.content 真机上**既有 list 也有裸字符串**（单文本的 user 行就是
字符串），两种都要接住。tool_result 元素只带 tool_use_id 不带工具名，跨行维护
一个 tool_use_id → name 的映射把名补上。

映射不出 role/kind 的行（ai-title / mode / permission-mode / last-prompt /
attachment / queue-operation / file-history-* / system 等）一律进 meta，text 存
该行紧凑 JSON——宁可当 meta 进索引，也不要丢一行。ai-title 行同时补 session.title。
"""
import json

from ..parse._common import bad_line_event, compact_json, iso_to_ms, meta_event, number
from ..parse.model import ParsedEvent, ParsedSession

NAME = "claude"


def _result_text(content):
    """tool_result 的 content 可能是字符串、也可能是 [{"type":..,"text":..}]，都接住。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [e.get("text") for e in content
                 if isinstance(e, dict) and isinstance(e.get("text"), str)]
        if parts:
            return "\n".join(parts)
    return compact_json(content)


def _emit_message(obj, type_, lineno, session, events, tool_names):
    ts = iso_to_ms(obj.get("timestamp"))
    uuid = obj.get("uuid") or ""
    if session.started_at is None:
        session.started_at = ts
    if ts is not None:
        session.ended_at = ts
    if not session.cwd and isinstance(obj.get("cwd"), str):
        session.cwd = obj["cwd"]
    if not session.branch and isinstance(obj.get("gitBranch"), str):
        session.branch = obj["gitBranch"]
    msg = obj.get("message")
    if not isinstance(msg, dict):
        events.append(meta_event(0, lineno, obj, ts, uuid))
        return
    role = type_ if type_ in ("user", "assistant") else msg.get("role") or ""
    if type_ == "assistant" and not session.model and isinstance(msg.get("model"), str):
        session.model = msg["model"]
    content = msg.get("content")
    if isinstance(content, str):
        events.append(ParsedEvent(seq=0, native_id=uuid, source_key=f"{uuid}#c0",
                                  ts=ts, role=role, kind="text", text=content,
                                  last_raw_line=lineno))
        return
    if not isinstance(content, list):
        events.append(meta_event(0, lineno, obj, ts, uuid))
        return
    for i, el in enumerate(content):
        key = f"{uuid}#c{i}" if uuid else ""
        if not isinstance(el, dict):
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="meta", text=compact_json(el),
                                      last_raw_line=lineno))
            continue
        et = el.get("type")
        if et == "text":
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="text", text=el.get("text") or "",
                                      last_raw_line=lineno))
        elif et == "thinking":
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="reasoning",
                                      text=el.get("thinking") or "", last_raw_line=lineno))
        elif et == "tool_use":
            name = el.get("name") or ""
            cid = el.get("id")
            if cid:
                tool_names[cid] = name
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="tool_call", tool=name,
                                      text=compact_json(el), last_raw_line=lineno))
        elif et == "tool_result":
            name = tool_names.get(el.get("tool_use_id"), "")
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="tool_result", tool=name,
                                      text=_result_text(el.get("content")),
                                      last_raw_line=lineno))
        else:
            events.append(ParsedEvent(seq=0, native_id=uuid, source_key=key, ts=ts,
                                      role=role, kind="meta", text=compact_json(el),
                                      last_raw_line=lineno))


def parse(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    session = ParsedSession(session_id=path.stem)
    events = []
    tool_names = {}
    for lineno, raw in enumerate(lines, 1):
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            events.append(bad_line_event(0, lineno, raw))
            continue
        if not isinstance(obj, dict):
            events.append(meta_event(0, lineno, obj))
            continue
        sid = obj.get("sessionId")
        if isinstance(sid, str) and sid:
            session.session_id = sid
        type_ = obj.get("type")
        if type_ in ("user", "assistant"):
            _emit_message(obj, type_, lineno, session, events, tool_names)
        elif type_ == "ai-title":
            title = obj.get("aiTitle")
            if isinstance(title, str) and title:
                session.title = title
            events.append(meta_event(0, lineno, obj, iso_to_ms(obj.get("timestamp")),
                                     obj.get("uuid") or ""))
        else:
            events.append(meta_event(0, lineno, obj, iso_to_ms(obj.get("timestamp")),
                                     obj.get("uuid") or ""))
    return session, number(events)
