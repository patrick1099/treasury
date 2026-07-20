import os, pytest
from pathlib import Path
from hub.vaultpaths import shared_skills_dir, within_shared_skills, SharedSkillsEscape
from hub.fslink import make_dir_link

def test_container_absent_is_ok(tmp_path):
    # shared/skills 还没建：不报错，返回路径
    assert shared_skills_dir(tmp_path) == tmp_path / "shared" / "skills"

def test_real_container_is_ok(tmp_path):
    (tmp_path / "shared" / "skills").mkdir(parents=True)
    assert shared_skills_dir(tmp_path).name == "skills"

def test_container_junction_escape_raises(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (tmp_path / "shared").mkdir()
    make_dir_link(outside, tmp_path / "shared" / "skills")   # 容器指向金库外
    with pytest.raises(SharedSkillsEscape):
        shared_skills_dir(tmp_path)

def test_container_parent_link_escape_raises(tmp_path):
    # shared 本身是指向金库外的 junction，skills 尚不存在：旧的 lexists 守卫会放行，
    # 无条件比对才挡得住这种父目录逃逸。
    outside = tmp_path / "outside"; outside.mkdir()
    make_dir_link(outside, tmp_path / "shared")   # 容器的父目录（shared）指向金库外
    with pytest.raises(SharedSkillsEscape):
        shared_skills_dir(tmp_path)

def test_within_rejects_escaping_name(tmp_path):
    (tmp_path / "shared" / "skills").mkdir(parents=True)
    outside = tmp_path / "outside" / "alpha"; outside.mkdir(parents=True)
    make_dir_link(outside, tmp_path / "shared" / "skills" / "alpha")  # 单名逃逸
    assert within_shared_skills(tmp_path / "shared" / "skills" / "alpha", tmp_path) is False

def test_within_accepts_real_child(tmp_path):
    (tmp_path / "shared" / "skills" / "alpha").mkdir(parents=True)
    assert within_shared_skills(tmp_path / "shared" / "skills" / "alpha", tmp_path) is True
