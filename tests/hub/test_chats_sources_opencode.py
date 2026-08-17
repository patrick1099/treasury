"""opencode 源的导出测试。

跟 claude/codex 的纯发现不同,opencode 没有文件可拷,discover 要真的去读一个
SQLite。所以测试用 tmp_path 造一个同构小库:三张表(加一张 event 表),几行数据,
其中一行 data 是坏 JSON。然后对着导出的字节/行断言。

不许碰真机库——spec 和计划都钉死:源数据一律 tmp_path 自造,不许拷真实对话。
"""
import json
import sqlite3

import pytest

from hub.chats.sources import opencode
from hub.chats.model import GENERATED, TRANSCRIPT
from hub.collect.errors import MissingSourceError
from hub.guard import SecretPathError


SCHEMA = """
CREATE TABLE session(
  id TEXT PRIMARY KEY, project_id TEXT, workspace_id TEXT, parent_id TEXT,
  slug TEXT, directory TEXT, path TEXT, title TEXT, version TEXT, share_url TEXT,
  agent TEXT, model TEXT, time_created INTEGER, time_updated INTEGER,
  time_compacting INTEGER, time_archived INTEGER);
CREATE TABLE message(
  id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
  time_updated INTEGER, data TEXT);
CREATE TABLE part(
  id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER,
  time_updated INTEGER, data TEXT);
CREATE TABLE event(
  id TEXT PRIMARY KEY, session_id TEXT, data TEXT);
"""


def _build_db(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO session (id,title,model,directory,time_created) VALUES (?,?,?,?,?)",
        ("sess_A", "alpha", "model-x", "/proj/a", 1000))
    cur.execute(
        "INSERT INTO session (id,title,model,directory,time_created) VALUES (?,?,?,?,?)",
        ("sess_B", "beta", "model-y", "/proj/b", 2000))
    cur.execute(
        "INSERT INTO message (id,session_id,time_created,time_updated,data) VALUES (?,?,?,?,?)",
        ("m1", "sess_A", 1050, 1070, '{"role":"user","content":"hi"}'))
    cur.execute(
        "INSERT INTO message (id,session_id,time_created,time_updated,data) VALUES (?,?,?,?,?)",
        ("m2", "sess_A", 1100, 1150, '{"role":"assistant","content":"broken'))
    cur.execute(
        "INSERT INTO part (id,message_id,session_id,time_created,time_updated,data) VALUES (?,?,?,?,?,?)",
        ("p1", "m1", "sess_A", 1060, 1061, '{"type":"text","text":"hello"}'))
    cur.execute(
        "INSERT INTO message (id,session_id,time_created,time_updated,data) VALUES (?,?,?,?,?)",
        ("m9", "sess_B", 2100, 2150, '{"role":"user","content":"sessB"}'))
    cur.execute(
        "INSERT INTO event (id,session_id,data) VALUES (?,?,?)",
        ("e1", "sess_A", '{"type":"secret-should-not-appear"}'))
    con.commit()
    con.close()
    return path


def _payload_lines(art):
    return art.payload.decode("utf-8").splitlines()


def _art_for(arts, sid):
    return next(a for a in arts if a.session_id == sid)


def _rows(art):
    return [json.loads(l) for l in _payload_lines(art)]


def test_one_artifact_per_session_tmpdb(tmp_path):
    db = _build_db(tmp_path / "opencode.db")
    arts = opencode.discover(tmp_path)
    assert len(arts) == 2
    rels = sorted(a.rel for a in arts)
    assert rels == ["sessions/sess_A.jsonl", "sessions/sess_B.jsonl"]
    for a in arts:
        assert a.kind == GENERATED
        assert a.role == TRANSCRIPT
        assert a.payload is not None
    assert db.exists()


def test_two_exports_byte_identical(tmp_path):
    _build_db(tmp_path / "opencode.db")
    first = opencode.discover(tmp_path)
    second = opencode.discover(tmp_path)
    assert [a.payload for a in first] == [a.payload for a in second]


def test_row_annotation_and_session_first(tmp_path):
    _build_db(tmp_path / "opencode.db")
    arts = opencode.discover(tmp_path)
    a = _art_for(arts, "sess_A")
    rows = _rows(a)
    assert rows[0]["_row"] == "session"
    assert rows[0]["id"] == "sess_A"
    assert rows[0]["title"] == "alpha"
    assert [r["_row"] for r in rows[1:]] == ["message", "part", "message"]
    assert [r["id"] for r in rows[1:]] == ["m1", "p1", "m2"]


def test_data_inlined_not_nested_string(tmp_path):
    _build_db(tmp_path / "opencode.db")
    a = _art_for(opencode.discover(tmp_path), "sess_A")
    m1 = next(r for r in _rows(a) if r.get("id") == "m1")
    assert isinstance(m1["data"], dict)
    assert m1["data"] == {"role": "user", "content": "hi"}


def test_bad_json_kept_with_flag(tmp_path):
    _build_db(tmp_path / "opencode.db")
    a = _art_for(opencode.discover(tmp_path), "sess_A")
    m2 = next(r for r in _rows(a) if r.get("id") == "m2")
    assert m2["_data_unparsed"] is True
    assert m2["data"] == '{"role":"assistant","content":"broken'


def test_event_rows_not_exported(tmp_path):
    _build_db(tmp_path / "opencode.db")
    arts = opencode.discover(tmp_path)
    all_rows = [r for a in arts for r in _rows(a)]
    assert all(r["_row"] != "event" for r in all_rows)
    assert all("secret-should-not-appear" not in json.dumps(r) for r in all_rows)


def test_lines_count_matches_rows(tmp_path):
    _build_db(tmp_path / "opencode.db")
    a = _art_for(opencode.discover(tmp_path), "sess_A")
    assert a.lines == len(_payload_lines(a))
    assert a.lines == 4


def test_db_missing_raises(tmp_path):
    with pytest.raises(MissingSourceError):
        opencode.discover(tmp_path)


def test_check_source_denied(tmp_path):
    with pytest.raises(SecretPathError):
        opencode.discover(tmp_path / "secrets" / "opencode")