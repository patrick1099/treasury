import pathlib

from hub.chats.manifest import dump, load
from hub.chats.model import Entry


def _entry(rel, **kw):
    base = dict(source_path="C:/Users/x/.claude/projects/p/abc.jsonl",
                role="transcript", kind="copy", bytes=1234567,
                sha256="01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
                lines=184, source_size=1234567, source_mtime_ns=1786123456789,
                source_ino=0, imported_at="2026-08-14T12:00:00Z",
                session_id="abc123", source_gone=False,
                superseded_by="", supersedes="")
    base.update(kw)
    return Entry(rel=rel, **base)


def _write(tmp_path, entries):
    p = pathlib.Path(tmp_path) / "manifest.toml"
    p.write_text(dump(entries), encoding="utf-8")
    return p


def test_roundtrip_dump_then_load(tmp_path):
    e = _entry("sessions/6a96cdd6.jsonl", meta={"project_dir": "C--Users--x"})
    _write(tmp_path, {"sessions/6a96cdd6.jsonl": e})
    back = load(tmp_path)
    assert back == {"sessions/6a96cdd6.jsonl": e}


def test_rel_with_slashes_dots_spaces_chinese_parses(tmp_path):
    rel = "sessions/工程 d.会话/6a96cdd6.jsonl"
    _write(tmp_path, {rel: _entry(rel)})
    text = dump({rel: _entry(rel)})
    assert f'artifact."{rel}"' in text
    back = load(tmp_path)
    assert rel in back
    assert back[rel].rel == rel


def test_empty_manifest(tmp_path):
    _write(tmp_path, {})
    assert load(tmp_path) == {}


def test_meta_flattened_and_restored(tmp_path):
    e = _entry("sessions/a.jsonl", meta={"project_dir": "C--", "flag": True, "n": 7})
    text = dump({"sessions/a.jsonl": e})
    assert 'x_project_dir = "C--"' in text
    assert "x_flag = true" in text
    assert "x_n = 7" in text
    _write(tmp_path, {"sessions/a.jsonl": e})
    back = load(tmp_path)["sessions/a.jsonl"]
    assert back.meta == {"project_dir": "C--", "flag": True, "n": 7}


def test_two_dumps_byte_identical():
    entries = {
        "sessions/b.jsonl": _entry("sessions/b.jsonl"),
        "sessions/a.jsonl": _entry("sessions/a.jsonl", meta={"z": 1}),
    }
    assert dump(entries) == dump(entries)


def test_bool_and_int_fields_roundtrip(tmp_path):
    e = _entry("sessions/a.jsonl", source_gone=True, bytes=99, lines=3,
               source_size=88, source_mtime_ns=123, source_ino=5)
    _write(tmp_path, {"sessions/a.jsonl": e})
    back = load(tmp_path)["sessions/a.jsonl"]
    assert back.source_gone is True
    assert back.bytes == 99
    assert back.lines == 3
    assert back.source_size == 88
    assert back.source_mtime_ns == 123
    assert back.source_ino == 5