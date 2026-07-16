import os
import pytest
from pathlib import Path
from hub.fslink import make_dir_link, remove_dir_link, is_under, LinkError

def test_make_dir_link_creates_followable_link(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "marker.txt").write_text("hi", encoding="utf-8")
    link = tmp_path / "sub" / "linked"          # 父目录 sub 不存在，应自动建
    make_dir_link(target, link)
    assert (link / "marker.txt").read_text(encoding="utf-8") == "hi"   # 经链接读到真内容

def test_make_dir_link_rejects_missing_target(tmp_path):
    with pytest.raises(NotADirectoryError):
        make_dir_link(tmp_path / "nope", tmp_path / "link")

def test_remove_dir_link_deletes_link_not_target(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "linked"
    make_dir_link(target, link)
    remove_dir_link(link)
    assert not os.path.lexists(link)                     # 链接没了
    assert (target / "keep.txt").exists()                # 目标内容完好无损

def test_remove_dir_link_absent_is_noop(tmp_path):
    remove_dir_link(tmp_path / "nothing")                # 不抛

def test_remove_dir_link_refuses_real_nonempty_dir(tmp_path):
    """安全防线：link 传进来一个真实的非空目录（不是链接）时，remove_dir_link
    绝不能把它当链接删掉——必须报错，目录和里面的内容都得原样留着。"""
    real = tmp_path / "real"
    real.mkdir()
    (real / "keep.txt").write_text("data", encoding="utf-8")
    with pytest.raises(OSError):
        remove_dir_link(real)
    assert real.exists()
    assert (real / "keep.txt").exists()

def test_make_dir_link_raises_link_error_on_create_failure(tmp_path):
    """target 合法但 link 路径已被一个普通文件占用——建链接这步本身失败，
    必须抛 LinkError（不是 NotADirectoryError 那种目标校验失败）。"""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.write_text("occupied", encoding="utf-8")        # link 路径已被普通文件占用
    with pytest.raises(LinkError):
        make_dir_link(target, link)

def test_is_under_true_through_link(tmp_path):
    shared = tmp_path / "vault" / "shared" / "skills"
    (shared / "foo").mkdir(parents=True)
    link = tmp_path / "home" / "skills" / "foo"
    make_dir_link(shared / "foo", link)
    assert is_under(link, tmp_path / "vault" / "shared") is True

def test_is_under_false_for_unrelated_dir(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert is_under(tmp_path / "a", tmp_path / "b") is False

def test_is_under_true_when_equal(tmp_path):
    (tmp_path / "a").mkdir()
    assert is_under(tmp_path / "a", tmp_path / "a") is True
