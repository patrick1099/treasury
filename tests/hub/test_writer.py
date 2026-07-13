import io
import subprocess
import tarfile
from pathlib import Path
import pytest
from hub.writer import Writer

def _make_tar_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        data = b"print(1)\n"
        info = tarfile.TarInfo(name="src/a.py")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()

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

def test_unlink_removes_file(tmp_path):
    """unlink() really deletes the file from disk (non-dry-run)."""
    p = tmp_path / "file.txt"
    p.write_text("content", encoding="utf-8")
    assert p.exists()
    Writer().unlink(p)
    assert not p.exists()

def test_dry_run_unlink_preserves_file(tmp_path):
    """dry-run unlink() leaves the file untouched."""
    p = tmp_path / "file.txt"
    p.write_text("content", encoding="utf-8")
    w = Writer(dry_run=True)
    w.unlink(p)
    assert p.exists()                          # 一个字节都不删
    assert p.read_text(encoding="utf-8") == "content"
    assert w.removed == [p]                    # 但报告说它"会"删

def test_dry_run_copy_tree_changes_nothing(tmp_path):
    """dry-run copy_tree() leaves destination completely unchanged."""
    src, dest = tmp_path / "s", tmp_path / "d"
    # Setup source
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "new.txt").write_text("new", encoding="utf-8")
    # Setup destination with stale content
    dest.mkdir()
    (dest / "stale.txt").write_text("stale", encoding="utf-8")

    # Dry-run copy
    w = Writer(dry_run=True)
    w.copy_tree(src, dest)

    # Verify destination is completely unchanged
    assert (dest / "stale.txt").exists()
    assert (dest / "stale.txt").read_text(encoding="utf-8") == "stale"
    assert not (dest / "sub").exists()         # 源的内容一个字节都没过来
    assert not (dest / "sub" / "new.txt").exists()
    assert w.written == [dest]                 # 但报告说它"会"写

def test_copy_tree_skips_nested_secrets_dir(tmp_path):
    """secrets/ 嵌套在被拷贝的树里必须被剔除，但同级文件正常拷过去。"""
    src, dest = tmp_path / "s", tmp_path / "d"
    (src / "secrets").mkdir(parents=True)
    (src / "secrets" / "token.md").write_text("top-secret", encoding="utf-8")
    (src / "sibling.txt").write_text("normal", encoding="utf-8")
    Writer().copy_tree(src, dest)
    assert not (dest / "secrets").exists()                     # 密钥目录整个消失
    assert (dest / "sibling.txt").read_text(encoding="utf-8") == "normal"  # 同级文件照常拷贝

def test_copy_tree_skips_nested_env_file(tmp_path):
    """.env 文件嵌套在被拷贝的树里必须被剔除，但同级文件正常拷过去。"""
    src, dest = tmp_path / "s", tmp_path / "d"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / ".env").write_text("SECRET=1", encoding="utf-8")
    (src / "sub" / "normal.txt").write_text("normal", encoding="utf-8")
    Writer().copy_tree(src, dest)
    assert not (dest / "sub" / ".env").exists()
    assert (dest / "sub" / "normal.txt").read_text(encoding="utf-8") == "normal"

def test_copy_tree_does_not_match_substring(tmp_path):
    """守门是按路径组件精确匹配，不是子串匹配——secretsanta.md 不该被误伤。"""
    src, dest = tmp_path / "s", tmp_path / "d"
    src.mkdir()
    (src / "secretsanta.md").write_text("holiday plan", encoding="utf-8")
    Writer().copy_tree(src, dest)
    assert (dest / "secretsanta.md").read_text(encoding="utf-8") == "holiday plan"

def test_copy_tree_does_not_leak_through_symlink_to_secrets(tmp_path):
    """树里的符号链接/junction 指向 secrets/ 目录时,真实字节不能流进 dest。"""
    src, dest = tmp_path / "s", tmp_path / "d"
    real_secrets = tmp_path / "secrets"
    real_secrets.mkdir()
    (real_secrets / "token.md").write_text("top-secret", encoding="utf-8")
    src.mkdir()
    (src / "sibling.txt").write_text("normal", encoding="utf-8")
    link = src / "creds"

    try:
        os_symlink_ok = True
        import os
        os.symlink(real_secrets, link, target_is_directory=True)
    except OSError:
        os_symlink_ok = False

    if not os_symlink_ok:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(real_secrets)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not link.exists():
            pytest.skip(
                f"无法创建符号链接或 NTFS junction (symlink 需要管理员/开发者模式，"
                f"mklink /J 失败: {result.stderr.strip() or result.stdout.strip()})"
            )

    Writer().copy_tree(src, dest)
    assert (dest / "sibling.txt").read_text(encoding="utf-8") == "normal"
    leaked = dest / "creds" / "token.md"
    assert not leaked.exists()

def test_extract_tar_writes_real_files(tmp_path):
    """真实运行:extract_tar() 把 tar 里的内容真的解到 dest,并记进 written。"""
    dest = tmp_path / "d"
    w = Writer()
    w.extract_tar(dest, _make_tar_bytes())
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"
    assert w.written == [dest]

def test_dry_run_extract_tar_changes_nothing(tmp_path):
    """dry-run extract_tar() 留 dest 原样不动(预置残留内容,防空判断)。"""
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "stale.txt").write_text("stale", encoding="utf-8")   # 上一轮的残留

    w = Writer(dry_run=True)
    w.extract_tar(dest, _make_tar_bytes())

    assert (dest / "stale.txt").exists()
    assert (dest / "stale.txt").read_text(encoding="utf-8") == "stale"
    assert not (dest / "src").exists()          # tar 的内容一个字节都没落盘
    assert w.written == [dest]                  # 但报告说它"会"写
