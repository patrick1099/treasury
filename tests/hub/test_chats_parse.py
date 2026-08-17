"""claude / codex 两个源解析器的测试。

每源一个小 fixture，形状照真机来但内容自己编——**不许从真机拷真实对话进测试**。
断言 role / kind / tool / native_id / source_key / 行号；坏行不丢（进 meta）。
"""
import pytest

from hub.chats.parse import UnknownSource, parse
from hub.chats.parse import claude, codex


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------- claude ----------------

CLAUDE_JSONL = """\
{"type":"ai-title","aiTitle":"测试会话","sessionId":"sess-1"}
{"type":"user","uuid":"u1","timestamp":"2026-08-01T01:00:00.000Z","sessionId":"sess-1","cwd":"/proj","gitBranch":"main","message":{"role":"user","content":"裸字符串内容"}}
{"type":"assistant","uuid":"a1","timestamp":"2026-08-01T01:00:01.000Z","sessionId":"sess-1","cwd":"/proj","gitBranch":"main","message":{"role":"assistant","model":"claude-x","content":[{"type":"thinking","thinking":"想一下"},{"type":"text","text":"回答"},{"type":"tool_use","id":"toolu_1","name":"Read","input":{"path":"/a"}}]}}
{"type":"user","uuid":"u2","timestamp":"2026-08-01T01:00:02.000Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_1","content":"文件内容"}]}}
this line is not json
{"type":"mode","uuid":"m1","timestamp":"2026-08-01T01:00:03.000Z","sessionId":"sess-1","mode":"plan"}
"""


def test_claude_session_fields(tmp_path):
    p = _write(tmp_path / "sess-1.jsonl", CLAUDE_JSONL)
    session, _ = claude.parse(p)
    assert session.session_id == "sess-1"
    assert session.title == "测试会话"
    assert session.cwd == "/proj"
    assert session.branch == "main"
    assert session.model == "claude-x"
    assert session.started_at is not None and session.ended_at is not None
    assert session.started_at <= session.ended_at


def test_claude_content_expansion_kinds_and_source_key(tmp_path):
    p = _write(tmp_path / "sess-1.jsonl", CLAUDE_JSONL)
    _, events = claude.parse(p)
    by = {(e.role, e.kind): e for e in events}
    assert by[("user", "text")].text == "裸字符串内容"
    assert by[("user", "text")].source_key == "u1#c0"
    assert by[("assistant", "reasoning")].text == "想一下"
    assert by[("assistant", "reasoning")].source_key == "a1#c0"
    assert by[("assistant", "text")].text == "回答"
    assert by[("assistant", "text")].source_key == "a1#c1"
    assert by[("assistant", "tool_call")].tool == "Read"
    assert by[("user", "tool_result")].tool == "Read"   # 跨行反查到工具名
    assert by[("user", "tool_result")].source_key == "u2#c0"


def test_claude_shared_last_raw_line(tmp_path):
    p = _write(tmp_path / "sess-1.jsonl", CLAUDE_JSONL)
    _, events = claude.parse(p)
    thinking = next(e for e in events if e.kind == "reasoning")
    text = next(e for e in events if e.kind == "text" and e.text == "回答")
    assert thinking.last_raw_line == 3
    assert text.last_raw_line == 3          # 同一行展开的多个 event 共享行号


def test_claude_native_id_is_uuid(tmp_path):
    p = _write(tmp_path / "sess-1.jsonl", CLAUDE_JSONL)
    _, events = claude.parse(p)
    tool_call = next(e for e in events if e.kind == "tool_call")
    assert tool_call.native_id == "a1"
    assert tool_call.seq >= 1


def test_claude_bad_line_and_meta_not_dropped(tmp_path):
    p = _write(tmp_path / "sess-1.jsonl", CLAUDE_JSONL)
    _, events = claude.parse(p)
    bad = [e for e in events if e.kind == "meta" and e.last_raw_line == 5]
    assert len(bad) == 1
    assert bad[0].text == "this line is not json"
    assert any(e.kind == "meta" and "plan" in e.text for e in events)  # mode 行进 meta


# ---------------- codex ----------------

CODEX_JSONL = """\
{"timestamp":"2026-08-01T01:00:00.000Z","type":"session_meta","payload":{"session_id":"cx-1","id":"cx-1","cwd":"/proj","git":{"branch":"dev","repository_url":"https://x/repo.git"}}}
{"timestamp":"2026-08-01T01:00:01.000Z","type":"response_item","payload":{"type":"message","id":"msg_1","role":"user","content":[{"type":"input_text","text":"帮我改"}]}}
{"timestamp":"2026-08-01T01:00:02.000Z","type":"response_item","payload":{"type":"reasoning","id":"rs_1","summary":[{"type":"text","text":"考虑"}]}}
{"timestamp":"2026-08-01T01:00:03.000Z","type":"response_item","payload":{"type":"function_call","id":"fc_1","name":"bash","call_id":"call_1","arguments":"{}"}}
{"timestamp":"2026-08-01T01:00:04.000Z","type":"response_item","payload":{"type":"function_call_output","id":"fco_1","call_id":"call_1","output":[{"type":"input_text","text":"输出"}]}}
{"timestamp":"2026-08-01T01:00:05.000Z","type":"response_item","payload":{"type":"custom_tool_call","id":"ctc_1","name":"exec","call_id":"call_2","input":"run it"}}
{"timestamp":"2026-08-01T01:00:06.000Z","type":"response_item","payload":{"type":"custom_tool_call_output","id":"ctco_1","call_id":"call_2","output":[{"type":"input_text","text":"完成"}]}}
{"timestamp":"2026-08-01T01:00:07.000Z","type":"event_msg","payload":{"type":"task_started","turn_id":"t1"}}
this line is not json
"""


def test_codex_session_fields(tmp_path):
    p = _write(tmp_path / "rollout-20260801T000000-abc-1.jsonl", CODEX_JSONL)
    session, _ = codex.parse(p)
    assert session.session_id == "cx-1"
    assert session.cwd == "/proj"
    assert session.branch == "dev"
    assert session.repo == "https://x/repo.git"


def test_codex_payload_type_dispatch(tmp_path):
    p = _write(tmp_path / "rollout-20260801T000000-abc-1.jsonl", CODEX_JSONL)
    _, events = codex.parse(p)
    # 同 (role, kind) 会有多个事件（fc_1/ctc_1 都是 tool_call），不能拿 (role,kind)
    # 当键——按 native_id 找具体那条
    by_id = {e.native_id: e for e in events}
    assert by_id["msg_1"].role == "user" and by_id["msg_1"].kind == "text"
    assert by_id["msg_1"].text == "帮我改"
    assert by_id["rs_1"].role == "assistant" and by_id["rs_1"].kind == "reasoning"
    assert by_id["rs_1"].text == "考虑"
    assert by_id["fc_1"].kind == "tool_call" and by_id["fc_1"].tool == "bash"
    assert by_id["fco_1"].kind == "tool_result" and by_id["fco_1"].tool == "bash"


def test_codex_custom_tool_mapped_to_tool_call_result(tmp_path):
    p = _write(tmp_path / "rollout-20260801T000000-abc-1.jsonl", CODEX_JSONL)
    _, events = codex.parse(p)
    calls = [e for e in events if e.kind == "tool_call" and e.native_id == "ctc_1"]
    results = [e for e in events if e.kind == "tool_result" and e.native_id == "ctco_1"]
    assert len(calls) == 1 and calls[0].tool == "exec"
    assert len(results) == 1 and results[0].tool == "exec"


def test_codex_meta_and_bad_line(tmp_path):
    p = _write(tmp_path / "rollout-20260801T000000-abc-1.jsonl", CODEX_JSONL)
    _, events = codex.parse(p)
    assert any(e.kind == "meta" and "task_started" in e.text for e in events)
    bad = [e for e in events if e.last_raw_line == 9]
    assert len(bad) == 1 and bad[0].kind == "meta"


def test_codex_session_meta_not_dropped(tmp_path):
    p = _write(tmp_path / "rollout-20260801T000000-abc-1.jsonl", CODEX_JSONL)
    _, events = codex.parse(p)
    assert any(e.kind == "meta" and "cx-1" in e.text for e in events)


# ---------------- 总入口 ----------------

def test_dispatcher_routes_by_source(tmp_path):
    p = _write(tmp_path / "sess.jsonl", CLAUDE_JSONL)
    session, events = parse("claude", p)
    assert session.session_id == "sess-1"
    assert any(e.kind == "tool_call" for e in events)


def test_dispatcher_unknown_source_raises(tmp_path):
    p = _write(tmp_path / "sess.jsonl", CLAUDE_JSONL)
    with pytest.raises(UnknownSource):
        parse("nope", p)
