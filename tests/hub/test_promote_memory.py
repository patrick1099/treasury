import pytest
from pathlib import Path
from hub.writer import Writer
from hub.promote import promote_memory, promote_memory_all, PromoteMemoryConflict

def _backup_mem(vault, host, name, scope="[global]", body="body"):
    d = vault / host / "claude" / "memory"; d.mkdir(parents=True, exist_ok=True)
    # newline="\n"：真实备份区文件由 collect→copy_file→write_text 写成，新文件一律 LF。
    # 不加 newline，Path.write_text 会在 Windows 上把 \n 译成 CRLF，与 promote 落到 shared 的
    # LF 版本按字节不等，令 same-content noop 检测误判为冲突。写成 LF 才是生产真相。
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\n{body}\n", encoding="utf-8", newline="\n")

def test_promote_copies_new(tmp_path):
    _backup_mem(tmp_path, "box", "a")
    dest = promote_memory(tmp_path, "box", "a", Writer())
    assert dest == tmp_path / "shared" / "memory" / "a.md"
    assert dest.exists()

def test_same_content_is_noop(tmp_path):
    _backup_mem(tmp_path, "box", "a")
    promote_memory(tmp_path, "box", "a", Writer())
    w = Writer(); promote_memory(tmp_path, "box", "a", w)
    assert w.written == []                              # 内容相同零写

def test_diff_content_conflicts(tmp_path):
    _backup_mem(tmp_path, "box", "a", body="v1")
    promote_memory(tmp_path, "box", "a", Writer())
    _backup_mem(tmp_path, "box", "a", body="v2")       # 改了源
    with pytest.raises(PromoteMemoryConflict):
        promote_memory(tmp_path, "box", "a", Writer())

def test_illegal_scope_refused_before_write(tmp_path):
    _backup_mem(tmp_path, "box", "a", scope="[device:work]")  # 旧语法
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", Writer())
    assert not (tmp_path / "shared" / "memory" / "a.md").exists()

def test_missing_source_raises(tmp_path):
    (tmp_path / "box" / "claude" / "memory").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        promote_memory(tmp_path, "box", "nope", Writer())

def test_all_is_not_mirror_and_precheck_zero_write_on_conflict(tmp_path):
    _backup_mem(tmp_path, "box", "a", body="v1")
    _backup_mem(tmp_path, "box", "b", body="ok")
    promote_memory(tmp_path, "box", "a", Writer())     # a 先进 shared
    _backup_mem(tmp_path, "box", "a", body="v2")       # a 现在冲突
    w = Writer()
    with pytest.raises(PromoteMemoryConflict):
        promote_memory_all(tmp_path, "box", w)
    assert w.written == []                              # 任一冲突→全量零写
    assert not (tmp_path / "shared" / "memory" / "b.md").exists()

def test_source_dir_link_escape_refused(tmp_path):
    # 源 memory 目录整个是指向备份区外的链接 → 拒绝、零写
    from hub.fslink import make_dir_link
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "a.md").write_text(
        "---\nname: a\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nbody\n",
        encoding="utf-8")
    (tmp_path / "box" / "claude").mkdir(parents=True)
    make_dir_link(outside, tmp_path / "box" / "claude" / "memory")   # memory 目录逃逸
    w = Writer()
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", w)
    assert w.written == []

def test_shared_parent_link_escape_refused(tmp_path):
    # shared 父目录是外链、shared/memory 尚不存在 → 仍要挡住（父目录逃逸）
    from hub.fslink import make_dir_link
    _backup_mem(tmp_path, "box", "a")
    outside = tmp_path / "out"; outside.mkdir()
    make_dir_link(outside, tmp_path / "shared")
    w = Writer()
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", w)
    assert w.written == []
