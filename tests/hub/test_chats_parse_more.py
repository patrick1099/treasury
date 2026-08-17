"""opencode / copilot-cli 两个源解析器的测试。

opencode 读 T5 导出的那份 jsonl（_row 分派）：role 从父 message 来、kind 从 part 的
data.type 来；tool 按 state.status 拆 call/result；step-start 这类 UI 脚手架进 meta。
copilot-cli：role 取 type 前缀、kind 取后缀（不归一化）；session.start 补会话元信息。
内容自己编，形状照真机。
"""
import pytest

from hub.chats.parse import copilot_cli, opencode


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------- opencode ----------------

OPENCODE_JSONL = """\
{"_row":"session","id":"oc-1","directory":"/proj","title":"会话","model":"model-x","time_created":1000,"time_updated":2000}
{"_row":"message","id":"m1","session_id":"oc-1","time_created":1100,"data":{"role":"user"}}
{"_row":"part","id":"p1","message_id":"m1","session_id":"oc-1","time_created":1110,"data":{"type":"text","text":"你好"}}
{"_row":"message","id":"m2","session_id":"oc-1","time_created":1200,"data":{"role":"assistant"}}
{"_row":"part","id":"p2","message_id":"m2","session_id":"oc-1","time_created":1210,"data":{"type":"reasoning","text":"想"}}
{"_row":"part","id":"p3","message_id":"m2","session_id":"oc-1","time_created":1220,"data":{"type":"tool","tool":"read","callID":"call_1","state":{"status":"completed","input":{},"output":"内容"}}}
{"_row":"part","id":"p4","message_id":"m2","session_id":"oc-1","time_created":1230,"data":{"type":"step-start","snapshot":"x"}}
{"_row":"message","id":"m3","session_id":"oc-1","time_created":1300,"data":{"role":"user"}}
{"_row":"part","id":"p5","message_id":"m3","session_id":"oc-1","time_created":1310,"data":{"type":"tool","tool":"write","callID":"call_2","state":{"status":"running","input":{"path":"/x"}}}}
{"_row":"message","id":"m4","session_id":"oc-1","time_created":1400,"data":{"role":"assistant"}}
this line is not json
"""


def test_opencode_session_fields(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    session, _ = opencode.parse(p)
    assert session.session_id == "oc-1"
    assert session.cwd == "/proj"
    assert session.title == "会话"
    assert session.model == "model-x"
    assert session.started_at == 1000 and session.ended_at == 2000


def test_opencode_role_from_parent_message(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    _, events = opencode.parse(p)
    text = next(e for e in events if e.native_id == "p1")
    assert text.role == "user" and text.kind == "text" and text.text == "你好"
    reasoning = next(e for e in events if e.native_id == "p2")
    assert reasoning.role == "assistant" and reasoning.kind == "reasoning"


def test_opencode_tool_split_by_state(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    _, events = opencode.parse(p)
    p3 = next(e for e in events if e.native_id == "p3")
    assert p3.kind == "tool_result" and p3.tool == "read"
    p5 = next(e for e in events if e.native_id == "p5")
    assert p5.kind == "tool_call" and p5.tool == "write"


def test_opencode_ui_scaffold_goes_meta(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    _, events = opencode.parse(p)
    p4 = next(e for e in events if e.native_id == "p4")
    assert p4.kind == "meta"


def test_opencode_message_without_parts_not_lost(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    _, events = opencode.parse(p)
    m4 = next(e for e in events if e.native_id == "m4")
    assert m4.role == "assistant" and m4.kind == "text"


def test_opencode_bad_line(tmp_path):
    p = _write(tmp_path / "oc-1.jsonl", OPENCODE_JSONL)
    _, events = opencode.parse(p)
    bad = [e for e in events if e.last_raw_line == 11]
    assert len(bad) == 1 and bad[0].kind == "meta"
    assert bad[0].text == "this line is not json"


# ---------------- copilot-cli ----------------

CLI_JSONL = """\
{"type":"session.start","id":"e1","timestamp":"2026-08-01T01:00:00.000Z","data":{"sessionId":"cp-1","context":{"cwd":"/proj","gitRoot":"/proj","branch":"main"}}}
{"type":"user.message","id":"e2","timestamp":"2026-08-01T01:00:01.000Z","data":{"content":"你好"}}
{"type":"assistant.message","id":"e3","timestamp":"2026-08-01T01:00:02.000Z","data":{"content":"回答"}}
{"type":"assistant.turn_start","id":"e4","timestamp":"2026-08-01T01:00:03.000Z","data":{"turnId":"0"}}
{"type":"session.model_change","id":"e5","timestamp":"2026-08-01T01:00:04.000Z","data":{"newModel":"gpt-x"}}
this line is not json
"""


def test_cli_session_fields(tmp_path):
    p = _write(tmp_path / "cp-1" / "events.jsonl", CLI_JSONL)
    session, _ = copilot_cli.parse(p)
    assert session.session_id == "cp-1"
    assert session.cwd == "/proj"
    assert session.repo == "/proj"
    assert session.branch == "main"
    assert session.model == "gpt-x"


def test_cli_prefix_role_suffix_kind(tmp_path):
    p = _write(tmp_path / "cp-1" / "events.jsonl", CLI_JSONL)
    _, events = copilot_cli.parse(p)
    by = {(e.role, e.kind): e for e in events}
    assert by[("user", "message")].text == "你好"
    assert by[("user", "message")].native_id == "e2"
    assert by[("assistant", "message")].text == "回答"
    assert by[("assistant", "turn_start")].kind == "turn_start"   # 后缀原样，不归一化


def test_cli_lifecycle_lines_meta(tmp_path):
    p = _write(tmp_path / "cp-1" / "events.jsonl", CLI_JSONL)
    _, events = copilot_cli.parse(p)
    metas = [e for e in events if e.kind == "meta"]
    assert any("session.start" in e.text for e in metas)
    assert any("model_change" in e.text for e in metas)
    bad = [e for e in events if e.last_raw_line == 6]
    assert len(bad) == 1 and bad[0].kind == "meta"
