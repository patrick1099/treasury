"""copilot-vscode 解析器的重放测试。

copilot-vscode 是增量日志：kind:0 全量快照、kind:1 设值、kind:2 截断+追加（splice）、
kind:3 删键。一条 assistant 消息可能由快照加多个不连续 delta 拼成（spec §8.3），
所以这里专门压重放语义：

- 重放后 requests 数量与顺序正确；
- 被截断重写的元素取**最终版本**（fixture 里 response[1] 被 line 8 重写）；
- last_raw_line / replay_upto_line 正确（最后一次影响它的行）；
- replay_upto_line 单调不减；
- 坏行不丢（进 meta，不参与重放）。

fixture 是编的，形状照真机，内容自己造。
"""
import pytest

from hub.chats.parse import copilot_vscode

# line 1: kind:0 快照（空 requests）
# line 2: kind:1 设 inputState.inputText（非会话内容，不产 event）
# line 3: kind:2 追加 request r1（自带 response=[thinking]）
# line 4: kind:2 追加 response 元素 markdownContent
# line 5: kind:2 追加 response 元素 toolInvocationSerialized
# line 6: 坏行（不参与重放，进 meta）
# line 7: kind:1 设 completionTokens（非会话内容）
# line 8: kind:2 截断到 1 再追加 text("回答v2") → response = [thinking, text]
# line 9: kind:2 追加 request r2
VSCODE_JSONL = (
    '{"kind":0,"v":{"version":3,"creationDate":1000,"sessionId":"vs-1",'
    '"requests":[],"pendingRequests":[]}}\n'
    '{"kind":1,"k":["inputState","inputText"],"v":"typing..."}\n'
    '{"kind":2,"k":["requests"],"v":[{"requestId":"r1","timestamp":1100,'
    '"message":{"text":"你好"},"response":[{"kind":"thinking","value":"想"}],'
    '"responseId":"res1","responseTimestamp":1150}]}\n'
    '{"kind":2,"k":["requests",0,"response"],"v":[{"kind":"markdownContent",'
    '"content":"回答"}]}\n'
    '{"kind":2,"k":["requests",0,"response"],"v":[{"kind":"toolInvocationSerialized",'
    '"invocationMessage":{"value":"读取文件"}}]}\n'
    "this line is not json\n"
    '{"kind":1,"k":["requests",0,"completionTokens"],"v":42}\n'
    '{"kind":2,"k":["requests",0,"response"],"i":1,"v":[{"kind":"text",'
    '"text":"回答v2"}]}\n'
    '{"kind":2,"k":["requests"],"v":[{"requestId":"r2","timestamp":1200,'
    '"message":{"text":"第二个问题"},"response":[{"kind":"markdownContent",'
    '"content":"二答"}],"responseId":"res2"}]}\n'
)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_vscode_requests_count_and_order(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    session, events = copilot_vscode.parse(p)
    assert session.session_id == "vs-1"
    users = [e for e in events if e.role == "user"]
    assert [e.native_id for e in users] == ["r1", "r2"]
    assert users[0].source_key == "requests[0]"
    assert users[1].source_key == "requests[1]"


def test_vscode_truncate_replace_takes_final_version(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    _, events = copilot_vscode.parse(p)
    resp = [e for e in events if e.role == "assistant"]
    assert len(resp) == 3
    assert resp[0].source_key == "requests[0].response[0]"
    assert resp[0].kind == "thinking" and resp[0].text == "想"
    # response[1] 被 line 8 截断重写成 text("回答v2")，不是 line 4 的 markdownContent
    assert resp[1].source_key == "requests[0].response[1]"
    assert resp[1].kind == "text" and resp[1].text == "回答v2"
    assert resp[2].source_key == "requests[1].response[0]"
    assert resp[2].text == "二答"


def test_vscode_last_raw_line_and_replay_upto_line(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    _, events = copilot_vscode.parse(p)
    r1_user = next(e for e in events if e.source_key == "requests[0]")
    r1_resp1 = next(e for e in events if e.source_key == "requests[0].response[1]")
    assert r1_user.last_raw_line == 3
    assert r1_user.replay_upto_line == 3
    assert r1_resp1.last_raw_line == 8
    assert r1_resp1.replay_upto_line == 8


def test_vscode_replay_upto_line_monotone(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    _, events = copilot_vscode.parse(p)
    # 重放出来的事件都有水位；坏行（kind=meta）没有对应可重放的逻辑节点，
    # replay_upto_line 本来就是 None，进不了单调性序列——过滤掉再断言单调。
    ups = [e.replay_upto_line for e in events if e.replay_upto_line is not None]
    assert ups == sorted(ups)
    bad = [e for e in events if e.kind == "meta" and e.last_raw_line == 6]
    assert len(bad) == 1 and bad[0].replay_upto_line is None


def test_vscode_bad_line_not_dropped(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    _, events = copilot_vscode.parse(p)
    bad = [e for e in events if e.kind == "meta" and e.last_raw_line == 6]
    assert len(bad) == 1
    assert bad[0].text == "this line is not json"
    # 坏行不参与重放：后续 line 7/8/9 仍然生效，r1 的 response 还是两个元素
    r1_resp = [e for e in events if e.source_key.startswith("requests[0].response")]
    assert len(r1_resp) == 2


def test_vscode_seqs_are_1_based_and_unique(tmp_path):
    p = _write(tmp_path / "vs-1.jsonl", VSCODE_JSONL)
    _, events = copilot_vscode.parse(p)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert seqs[0] == 1
