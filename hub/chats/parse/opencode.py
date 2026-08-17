"""opencode 源解析器：读 T5 导出的那份 jsonl（_row 分派），不是直接读库。

导出行形状见 spec §4.3：session / message / part 三表混排，data 已内联
（坏 JSON 的 data 保留字符串并带 _data_unparsed: true）。

映射（spec §8.2）：role 从 message.data.role 来，kind 从 part.data.type 来——
一个 event = 父 message 的 role + part 的 kind，part 通过 message_id 挂回 message
拿 role；没有 part 的 message 单独出一条 text 事件兜底，不然它整行就沉没了。
tool 类型按 state.status 拆（spec "tool→按 data.state 拆 call/result"）：终态
（completed/error/...）是结果，非终态（running/pending）是调用。
step-start / step-finish / compaction 这些 UI 脚手架不映射 → meta。

session 行只填 ParsedSession，不产 event（跟 codex session_meta 同理）。
"""
import collections
import json

from ..parse._common import (bad_line_event, compact_json, meta_event, number)
from ..parse.model import ParsedEvent, ParsedSession

NAME = "opencode"

_TERMINAL = {"completed", "error", "aborted", "cancelled", "failed"}


def parse(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows = []
    part_counts = collections.Counter()
    for lineno, raw in enumerate(lines, 1):
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            rows.append((lineno, None))
            continue
        rows.append((lineno, obj))
        if not isinstance(obj, dict):
            continue
        if obj.get("_row") == "message":
            part_counts.setdefault(obj.get("id"), 0)
        elif obj.get("_row") == "part":
            part_counts[obj.get("message_id")] += 1

    session = ParsedSession(session_id="")
    msg_roles = {}
    for _, obj in rows:
        if not isinstance(obj, dict):
            continue
        if obj.get("_row") == "session":
            sid = obj.get("id")
            if isinstance(sid, str) and sid:
                session.session_id = sid
            if isinstance(obj.get("directory"), str):
                session.cwd = obj["directory"]
            if isinstance(obj.get("title"), str):
                session.title = obj["title"]
            if isinstance(obj.get("model"), str):
                session.model = obj["model"]
            if session.started_at is None and isinstance(obj.get("time_created"), int):
                session.started_at = obj["time_created"]
            if isinstance(obj.get("time_updated"), int):
                session.ended_at = obj["time_updated"]
        elif obj.get("_row") == "message":
            data = obj.get("data")
            if isinstance(data, dict) and isinstance(data.get("role"), str):
                msg_roles[obj.get("id")] = data["role"]

    events = []
    for lineno, obj in rows:
        if obj is None:
            events.append(bad_line_event(0, lineno, lines[lineno - 1]))
            continue
        if not isinstance(obj, dict):
            events.append(meta_event(0, lineno, obj))
            continue
        row = obj.get("_row")
        if row == "session":
            continue
        if row == "message":
            if part_counts.get(obj.get("id"), 0) == 0:
                data = obj.get("data")
                role = data.get("role") if isinstance(data, dict) else ""
                events.append(ParsedEvent(seq=0, native_id=obj.get("id") or "",
                                          ts=obj.get("time_created"), role=role,
                                          kind="text", text=compact_json(obj),
                                          last_raw_line=lineno))
            continue
        if row == "part":
            data = obj.get("data")
            mid = obj.get("message_id")
            role = msg_roles.get(mid, "")
            ts = obj.get("time_created")
            nid = obj.get("id") or ""
            if not isinstance(data, dict):
                events.append(meta_event(0, lineno, obj, ts, nid))
                continue
            ptype = data.get("type")
            if ptype == "text":
                events.append(ParsedEvent(seq=0, native_id=nid, ts=ts, role=role,
                                          kind="text", text=data.get("text") or "",
                                          last_raw_line=lineno))
            elif ptype == "reasoning":
                events.append(ParsedEvent(seq=0, native_id=nid, ts=ts, role=role,
                                          kind="reasoning", text=data.get("text") or "",
                                          last_raw_line=lineno))
            elif ptype == "tool":
                st = data.get("state")
                status = st.get("status") if isinstance(st, dict) else None
                kind = "tool_result" if status in _TERMINAL else "tool_call"
                events.append(ParsedEvent(seq=0, native_id=nid, ts=ts, role=role,
                                          kind=kind, tool=data.get("tool") or "",
                                          text=compact_json(data), last_raw_line=lineno))
            elif ptype in ("patch", "file"):
                events.append(ParsedEvent(seq=0, native_id=nid, ts=ts, role=role,
                                          kind=ptype, text=compact_json(data),
                                          last_raw_line=lineno))
            else:
                events.append(meta_event(0, lineno, obj, ts, nid))
            continue
        events.append(meta_event(0, lineno, obj))
    return session, number(events)
