"""copilot-cli 源解析器：事件 {id,parentId,timestamp,type,data}。

spec §8.2：role 从 type 前缀（user. / assistant. / system.）来，kind 取 type 后缀
——不归一化成 text/reasoning 那套词表，"message" 就是 "message"，源的差异不吞掉。
text 取 data.content（用户/助手正文），没有就存该行紧凑 JSON。

session.start 行同时填 ParsedSession 的 session_id / cwd / repo(gitRoot) /
branch，并照"不丢行"规矩进一条 meta（它映射不出 role/kind）。session.model_change
里非 auto 的 newModel 补 session.model。其余生命周期行（mode_changed / abort /
shutdown / auto_mode_resolved / ...）一律 meta。
"""
import json

from ..parse._common import (bad_line_event, compact_json, iso_to_ms, meta_event,
                             number)
from ..parse.model import ParsedEvent, ParsedSession

NAME = "copilot-cli"

_ROLE_PREFIXES = ("user.", "assistant.", "system.")


def parse(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    session = ParsedSession(session_id=path.stem)
    events = []
    last_ts = None
    for lineno, raw in enumerate(lines, 1):
        try:
            obj = json.loads(raw)
        except (TypeError, ValueError):
            events.append(bad_line_event(0, lineno, raw))
            continue
        if not isinstance(obj, dict):
            events.append(meta_event(0, lineno, obj))
            continue
        type_ = obj.get("type") or ""
        ts = iso_to_ms(obj.get("timestamp"))
        if ts is not None:
            if session.started_at is None:
                session.started_at = ts
            last_ts = ts
        nid = obj.get("id") or ""
        if type_ == "session.start":
            data = obj.get("data")
            if isinstance(data, dict):
                sid = data.get("sessionId")
                if isinstance(sid, str) and sid:
                    session.session_id = sid
                ctx = data.get("context")
                if isinstance(ctx, dict):
                    if not session.cwd and isinstance(ctx.get("cwd"), str):
                        session.cwd = ctx["cwd"]
                    if not session.repo and isinstance(ctx.get("gitRoot"), str):
                        session.repo = ctx["gitRoot"]
                    if not session.branch and isinstance(ctx.get("branch"), str):
                        session.branch = ctx["branch"]
            events.append(meta_event(0, lineno, obj, ts, nid))
            continue
        if type_ == "session.model_change":
            data = obj.get("data")
            nm = data.get("newModel") if isinstance(data, dict) else None
            if isinstance(nm, str) and nm and nm != "auto" and not session.model:
                session.model = nm
            events.append(meta_event(0, lineno, obj, ts, nid))
            continue
        if type_.startswith(_ROLE_PREFIXES):
            role, kind = type_.split(".", 1)
            data = obj.get("data")
            text = (data.get("content") if isinstance(data, dict)
                    and isinstance(data.get("content"), str) else compact_json(obj))
            events.append(ParsedEvent(seq=0, native_id=nid, ts=ts, role=role,
                                      kind=kind, text=text, last_raw_line=lineno))
            continue
        events.append(meta_event(0, lineno, obj, ts, nid))
    session.ended_at = last_ts
    return session, number(events)
