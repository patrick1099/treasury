"""codex 源解析器：行 {timestamp,type,payload}，按 payload.type 分派。

spec §8.2：role 从 payload.role 来，kind 从 payload.type 来（message→text /
reasoning→reasoning / function_call→tool_call / function_call_output→tool_result）。
真机上还有大量 custom_tool_call / custom_tool_call_output（exec 这类自研工具，
结构跟 function_call 一模一样：call_id + name + input/output）——按 spec 的意图
它们是 tool call/result，不是"映射不出的行"，这里一并映射；否则最常见的工具活动
（本机 8794+8792 条）会全沉进 meta。两种输出型事件靠 call_id 反查工具名。

session_meta 行不产 event（它描述会话本身，不是一条消息），只用来填 ParsedSession
的 session_id / cwd / branch / repo，但也照"不丢行"规矩进一条 meta。其余映射不出
的行类型（event_msg / world_state / turn_context / compacted / agent_message /
web_search_call / tool_search_* / image_generation_call / ...）一律进 meta。
"""
import json
import re

from ..parse._common import (bad_line_event, compact_json, iso_to_ms, join_text,
                             meta_event, number)
from ..parse.model import ParsedEvent, ParsedSession

NAME = "codex"

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_CALL_TYPES = {"function_call", "custom_tool_call"}
_OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}


def _fallback_id(stem):
    """文件名 rollout-<ISO>-<uuid>.jsonl 里取 uuid；取不出就用 stem（跟 T4 同一规则）。"""
    m = _UUID_RE.search(stem)
    return m.group(0) if m else stem


def _emit(payload, ts, call_names, events):
    """response_item 的 payload → 事件。返回 True 表示映射出了 role/kind。"""
    ptype = payload.get("type")
    pid = payload.get("id") or ""
    if ptype == "message":
        events.append(ParsedEvent(seq=0, native_id=pid, ts=ts,
                                  role=payload.get("role") or "", kind="text",
                                  text=join_text(payload.get("content")) or compact_json(payload),
                                  last_raw_line=0))
        return True
    if ptype == "reasoning":
        events.append(ParsedEvent(seq=0, native_id=pid, ts=ts,
                                  role="assistant", kind="reasoning",
                                  text=join_text(payload.get("summary")),
                                  last_raw_line=0))
        return True
    if ptype in _CALL_TYPES:
        name = payload.get("name") or ""
        cid = payload.get("call_id")
        if cid:
            call_names[cid] = name
        events.append(ParsedEvent(seq=0, native_id=pid, ts=ts,
                                  role="assistant", kind="tool_call", tool=name,
                                  text=compact_json(payload), last_raw_line=0))
        return True
    if ptype in _OUTPUT_TYPES:
        cid = payload.get("call_id")
        events.append(ParsedEvent(seq=0, native_id=pid, ts=ts,
                                  role="tool", kind="tool_result",
                                  tool=call_names.get(cid, ""),
                                  text=join_text(payload.get("output")) or compact_json(payload),
                                  last_raw_line=0))
        return True
    return False


def parse(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    session = ParsedSession(session_id=_fallback_id(path.stem))
    events = []
    call_names = {}
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
        ts = iso_to_ms(obj.get("timestamp"))
        if ts is not None:
            if session.started_at is None:
                session.started_at = ts
            last_ts = ts
        ltype = obj.get("type")
        if ltype == "session_meta":
            pl = obj.get("payload")
            if isinstance(pl, dict):
                sid = pl.get("session_id") or pl.get("id")
                if isinstance(sid, str) and sid:
                    session.session_id = sid
                if not session.cwd and isinstance(pl.get("cwd"), str):
                    session.cwd = pl["cwd"]
                git = pl.get("git")
                if isinstance(git, dict):
                    if not session.branch and isinstance(git.get("branch"), str):
                        session.branch = git["branch"]
                    if not session.repo and isinstance(git.get("repository_url"), str):
                        session.repo = git["repository_url"]
            events.append(meta_event(0, lineno, obj, ts,
                                     pl.get("id") if isinstance(pl, dict) else ""))
            continue
        if ltype == "response_item":
            pl = obj.get("payload")
            if isinstance(pl, dict) and _emit(pl, ts, call_names, events):
                events[-1].last_raw_line = lineno
                continue
            events.append(meta_event(0, lineno, obj, ts,
                                     pl.get("id") if isinstance(pl, dict) else ""))
            continue
        events.append(meta_event(0, lineno, obj, ts))
    session.ended_at = last_ts
    return session, number(events)
