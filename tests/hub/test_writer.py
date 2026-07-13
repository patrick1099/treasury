from pathlib import Path
from hub.writer import Writer

def test_write_text_creates_parents(tmp_path):
    w = Writer()
    w.write_text(tmp_path / "a" / "b.md", "hi\n")
    assert (tmp_path / "a" / "b.md").read_text(encoding="utf-8") == "hi\n"
    assert w.written == [tmp_path / "a" / "b.md"]

def test_dry_run_writes_nothing(tmp_path):
    w = Writer(dry_run=True)
    w.write_text(tmp_path / "a" / "b.md", "hi\n")
    assert not (tmp_path / "a").exists()          # 一个字节都不落盘
    assert w.written == [tmp_path / "a" / "b.md"] # 但报告说它"会"写

def test_dry_run_rmtree_removes_nothing(tmp_path):
    d = tmp_path / "d"
    (d / "x").mkdir(parents=True)
    w = Writer(dry_run=True)
    w.rmtree(d)
    assert (d / "x").exists()
    assert w.removed == [d]

def test_copy_tree_is_full_rewrite(tmp_path):
    src, dest = tmp_path / "s", tmp_path / "d"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "new.txt").write_text("new", encoding="utf-8")
    dest.mkdir()
    (dest / "stale.txt").write_text("stale", encoding="utf-8")   # 上一轮的残留
    Writer().copy_tree(src, dest)
    assert (dest / "sub" / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (dest / "stale.txt").exists()      # 全量重写：残留必须消失

def test_write_text_preserves_existing_newline_style(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes(b"old\r\nline\r\n")
    Writer().write_text(p, "new\nline\n")
    assert p.read_bytes() == b"new\r\nline\r\n"    # 沿用原有 CRLF，不制造整文件重写

def test_new_file_uses_lf(tmp_path):
    p = tmp_path / "a.md"
    Writer().write_text(p, "new\nline\n")
    assert p.read_bytes() == b"new\nline\n"
