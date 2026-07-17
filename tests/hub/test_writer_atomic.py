import os, pytest
from pathlib import Path
from hub.writer import Writer

def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "v" / "MEMORY.md"
    Writer().write_text_atomic(p, "hello\n")
    assert p.read_text(encoding="utf-8") == "hello\n"

def test_atomic_write_no_bom(tmp_path):
    p = tmp_path / "a.json"
    Writer().write_text_atomic(p, "{}\n")
    assert p.read_bytes()[:1] != b"\xef"                # 无 UTF-8 BOM

def test_atomic_write_preserves_crlf(tmp_path):
    p = tmp_path / "a.md"; p.write_bytes(b"old\r\n")
    Writer().write_text_atomic(p, "new\n")
    assert b"\r\n" in p.read_bytes()

def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "a.md"
    Writer(dry_run=True).write_text_atomic(p, "x\n")
    assert not p.exists()

def test_replace_failure_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "a.md"; p.write_text("original\n", encoding="utf-8")
    def boom(src, dst): raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        Writer().write_text_atomic(p, "new\n")
    assert p.read_text(encoding="utf-8") == "original\n"  # 原文完整
    assert not list(p.parent.glob("*.hub-tmp"))           # 失败不留临时垃圾

def test_non_oserror_also_cleans_temp(tmp_path, monkeypatch):
    # 编码/fsync 等非 OSError 异常也必须清 temp（不能只在 OSError 分支清）
    p = tmp_path / "a.md"
    def boom(fd): raise RuntimeError("boom")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(RuntimeError):
        Writer().write_text_atomic(p, "x\n")
    assert not list(p.parent.glob("*.hub-tmp"))
