"""copilot-vscode 源解析器：增量日志，必须先重放才能拼出 requests[]。

文件一行一个操作（spec §2）：kind:0 全量快照（v = 完整状态）；kind:1 把 k（键路径）
指向的值设为 v；kind:2 把路径上数组截断到 i（给了才截）再追加 v（模拟 splice）；
kind:3 删掉路径上的键。这套语义是从 VS Code 自己的 chat session 持久化（workbench
里对请求/响应做 splice-diff 序列化，写盘时把差异变成这几类操作）核出来的，不是猜的
——它直接决定一条 assistant 消息可能由快照加多个不连续 delta 拼成。

"重放"意味着同一格逻辑节点会被写很多次：agent 模式里一个 response 数组被反复追加、
截断重写，最后停在哪里由最后一次影响它的操作决定。所以（spec §8.3）：
- last_raw_line = 最后一次影响该节点的行，只用于"打开证据附近"；
- replay_upto_line = 重建该节点所需的日志水位（重放到这行就能取出它的最终版本）；
- source_key = requests[i].response[j] 这类稳定键路径，兼作无原生 id 时的定位符。
三者同源：对某个最终位置的节点，最后一次写它的行就是重建它所需的水位。

事件顺序 = 最终 requests[] 的展开顺序（每个 request 先 user 消息、再按位置展开
response 元素）——seq 只管"排序与显示"，重放水位单独记在 replay_upto_line。

response 元素的 kind 字段直接当 kind（markdownContent / thinking /
toolInvocationSerialized / ...），不归一化：源的差异不吞掉。user 消息 kind=text。
坏行照旧进 meta；坏行没法参与重放（后续操作可能引用到拼不出来的状态），跳过并
记 meta——原始层那行还在，索引是尽力而为。
"""
import json

from ..parse._common import (bad_line_event, compact_json, meta_event, number)
from ..parse.model import ParsedEvent, ParsedSession

NAME = "copilot-vscode"


def _mark_request(req_idx, req, lineno, lastwrite, req_created):
    """请求被创建/整体重写：它的创建行和它自带 response 的全部位置都算这一行写的。"""
    req_created[req_idx] = lineno
    resp = req.get("response") if isinstance(req, dict) else None
    if isinstance(resp, list):
        for j in range(len(resp)):
            lastwrite[(req_idx, j)] = lineno


def _mark_all(state, lineno, lastwrite, req_created):
    """快照整体落地：每个请求的创建行、每个 response 位置都算快照这一行写的。"""
    reqs = state.get("requests") if isinstance(state, dict) else None
    if isinstance(reqs, list):
        for i, r in enumerate(reqs):
            _mark_request(i, r, lineno, lastwrite, req_created)


def _mark_response(req_idx, resp, start, lineno, lastwrite):
    """response 数组在 start 起被写：start..start+len-1 都是这一行写的。"""
    if isinstance(resp, list):
        for j in range(len(resp)):
            lastwrite[(req_idx, start + j)] = lineno


def _apply_set(state, k, v):
    cur = state
    for part in k[:-1]:
        cur = cur[part]
    cur[k[-1]] = v


def _apply_push(state, k, v, i):
    cur = state
    for part in k[:-1]:
        cur = cur[part]
    last = k[-1]
    arr = cur.get(last) or []
    if i is not None:
        arr = arr[:i]
    if v:
        arr = arr + list(v)
    cur[last] = arr


def _note_write(state, k, v, i, lineno, lastwrite, req_created):
    """一行写操作落地后，记录它实际写了哪些逻辑节点（只记不删，过期位置靠最终状态忽略）。"""
    if k == ["requests"]:
        reqs = state.get("requests") or []
        start = i if i is not None else max(0, len(reqs) - len(v or []))
        for off, r in enumerate(v or []):
            _mark_request(start + off, r, lineno, lastwrite, req_created)
        return
    if len(k) == 2 and k[0] == "requests" and isinstance(k[1], int):
        _mark_request(k[1], state["requests"][k[1]], lineno, lastwrite, req_created)
        return
    if len(k) == 3 and k[0] == "requests" and isinstance(k[1], int) and k[2] == "response":
        if i is not None:
            start = i
        else:
            cur_resp = state["requests"][k[1]].get("response") or []
            start = max(0, len(cur_resp) - len(v or []))
        _mark_response(k[1], v, start, lineno, lastwrite)
        return


def _elem_text(el):
    """response 元素 → 可检索文本。拿不到就走紧凑 JSON 兜底。"""
    kind = el.get("kind")
    if kind == "text" and isinstance(el.get("text"), str):
        return el["text"]
    if kind == "markdownContent" and isinstance(el.get("content"), str):
        return el["content"]
    if kind == "thinking" and isinstance(el.get("value"), str):
        return el["value"]
    if kind == "toolInvocationSerialized":
        im = el.get("invocationMessage")
        if isinstance(im, dict) and isinstance(im.get("value"), str):
            return im["value"]
    if kind == "progressTaskSerialized" and isinstance(el.get("message"), str):
        return el["message"]
    return compact_json(el)


def parse(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    state = None
    lastwrite = {}
    req_created = {}
    bad_events = []
    for lineno, raw in enumerate(lines, 1):
        try:
            op = json.loads(raw)
        except (TypeError, ValueError):
            bad_events.append(bad_line_event(0, lineno, raw))
            continue
        if not isinstance(op, dict):
            bad_events.append(meta_event(0, lineno, op))
            continue
        kind = op.get("kind")
        try:
            if kind == 0:
                v = op.get("v")
                if not isinstance(v, dict):
                    bad_events.append(meta_event(0, lineno, op))
                    continue
                state = v
                _mark_all(state, lineno, lastwrite, req_created)
            elif kind == 1:
                if state is None:
                    bad_events.append(meta_event(0, lineno, op))
                    continue
                k = op.get("k") or []
                _apply_set(state, k, op.get("v"))
                _note_write(state, k, op.get("v"), None, lineno, lastwrite, req_created)
            elif kind == 2:
                if state is None:
                    bad_events.append(meta_event(0, lineno, op))
                    continue
                k = op.get("k") or []
                _apply_push(state, k, op.get("v"), op.get("i"))
                _note_write(state, k, op.get("v"), op.get("i"), lineno, lastwrite, req_created)
            elif kind == 3:
                if state is None:
                    bad_events.append(meta_event(0, lineno, op))
                    continue
                _apply_set(state, op.get("k") or [], None)
            else:
                bad_events.append(meta_event(0, lineno, op))
        except (KeyError, IndexError, TypeError):
            # 引用到拼不出来的状态（坏行/截断的副作用）——记 meta，不炸整场
            bad_events.append(meta_event(0, lineno, op))

    session = ParsedSession(session_id=path.stem)
    reqs = state.get("requests") if isinstance(state, dict) else []
    if isinstance(reqs, list):
        for i, r in enumerate(reqs):
            if not isinstance(r, dict):
                continue
            if isinstance(r.get("sessionId"), str) and r["sessionId"]:
                session.session_id = r["sessionId"]
            if not session.model and isinstance(r.get("modelId"), str) and r["modelId"]:
                session.model = r["modelId"]
            ts = r.get("timestamp")
            if isinstance(ts, int) and (session.started_at is None or ts < session.started_at):
                session.started_at = ts
            rts = r.get("responseTimestamp") or r.get("timestamp")
            if isinstance(rts, int) and (session.ended_at is None or rts > session.ended_at):
                session.ended_at = rts
        if state.get("sessionId"):
            session.session_id = state["sessionId"]
        if isinstance(state.get("creationDate"), int) and session.started_at is None:
            session.started_at = state["creationDate"]

    events = []
    for i, r in enumerate(reqs):
        if not isinstance(r, dict):
            continue
        created_line = req_created.get(i, 1)
        message = r.get("message")
        text = (message.get("text") if isinstance(message, dict)
                and isinstance(message.get("text"), str) else compact_json(message))
        events.append(ParsedEvent(seq=0, native_id=r.get("requestId") or "",
                                  source_key=f"requests[{i}]",
                                  ts=r.get("timestamp") if isinstance(r.get("timestamp"), int) else None,
                                  role="user", kind="text", text=text,
                                  last_raw_line=created_line, replay_upto_line=created_line))
        resp = r.get("response")
        if not isinstance(resp, list):
            continue
        for j, el in enumerate(resp):
            line = lastwrite.get((i, j), created_line)
            if not isinstance(el, dict):
                events.append(ParsedEvent(seq=0, native_id=r.get("responseId") or "",
                                          source_key=f"requests[{i}].response[{j}]",
                                          role="assistant", kind="meta",
                                          text=compact_json(el), last_raw_line=line,
                                          replay_upto_line=line))
                continue
            ts = r.get("responseTimestamp")
            if not isinstance(ts, int):
                ts = r.get("timestamp")
            events.append(ParsedEvent(seq=0, native_id=r.get("responseId") or "",
                                      source_key=f"requests[{i}].response[{j}]",
                                      ts=ts if isinstance(ts, int) else None,
                                      role="assistant", kind=el.get("kind") or "",
                                      text=_elem_text(el), last_raw_line=line,
                                      replay_upto_line=line))
    events.extend(bad_events)
    return session, number(events)
