import pytest
from pathlib import Path
from hub.promote import promote_skill, PromoteConflict
from hub.writer import Writer

def _skill(root: Path, name: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d

def test_promote_copies_into_shared(tmp_path):
    vault = tmp_path / "vault"
    src = _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    dest = promote_skill(vault, "box1", "claude", "alpha", Writer())
    assert dest == vault / "shared" / "skills" / "alpha"
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# a\n"
    # 复制不是移动：源还在
    assert (src / "SKILL.md").exists()

def test_promote_same_content_is_strictly_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    promote_skill(vault, "box1", "claude", "alpha", Writer())
    w = Writer()
    dest = promote_skill(vault, "box1", "claude", "alpha", w)    # 内容相同：不该再写
    assert dest == vault / "shared" / "skills" / "alpha"
    assert w.written == []                                       # 严格无写入
    assert (vault / "shared" / "skills" / "alpha" / "SKILL.md").exists()

def test_promote_rejects_traversal_in_host(tmp_path):
    vault = tmp_path / "vault"
    with pytest.raises(ValueError):
        promote_skill(vault, "..", "claude", "alpha", Writer())

def test_promote_rejects_src_link_escaping_backup(tmp_path):
    """备份区里的 skill 目录本身是指向备份区外的链接——必须拒（防链接逃逸）。"""
    from hub.fslink import make_dir_link
    vault = tmp_path / "vault"
    outside = tmp_path / "outside_secret"; outside.mkdir()
    (outside / "SKILL.md").write_text("# 外部\n", encoding="utf-8")
    (vault / "box1" / "claude" / "skills").mkdir(parents=True)
    make_dir_link(outside, vault / "box1" / "claude" / "skills" / "alpha")
    with pytest.raises(ValueError, match="逃出备份区"):
        promote_skill(vault, "box1", "claude", "alpha", Writer())

def test_promote_conflict_when_dest_is_file(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    (vault / "shared" / "skills").mkdir(parents=True)
    (vault / "shared" / "skills" / "alpha").write_text("我是文件不是目录", encoding="utf-8")
    with pytest.raises(PromoteConflict):
        promote_skill(vault, "box1", "claude", "alpha", Writer())

def test_promote_conflict_stops_and_does_not_overwrite(tmp_path):
    vault = tmp_path / "vault"
    existing = _skill(vault / "shared" / "skills", "alpha", "# 共享区已有的版本\n")
    before = (existing / "SKILL.md").read_bytes()
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# 备份区不同的版本\n")
    with pytest.raises(PromoteConflict, match="alpha"):
        promote_skill(vault, "box1", "claude", "alpha", Writer())
    assert (existing / "SKILL.md").read_bytes() == before      # 一个字节都没动

def test_promote_missing_source_raises(tmp_path):
    vault = tmp_path / "vault"
    (vault / "box1" / "claude" / "skills").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        promote_skill(vault, "box1", "claude", "nope", Writer())

def test_promote_rejects_path_traversal_in_name(tmp_path):
    vault = tmp_path / "vault"
    with pytest.raises(ValueError):
        promote_skill(vault, "box1", "claude", "../../secrets", Writer())

def test_promote_dry_run_writes_nothing(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    promote_skill(vault, "box1", "claude", "alpha", Writer(dry_run=True))
    assert not (vault / "shared" / "skills" / "alpha").exists()
