import subprocess
from pathlib import Path
from hub.collect.skills import collect_skills
from hub.writer import Writer

def _skill(root: Path, name: str, body: str = "# skill\n"):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d

def test_copies_each_skill_dir(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    _skill(src, "beta")
    dest = tmp_path / "vault" / "skills"
    got = collect_skills(src, dest, Writer())
    assert sorted(got) == ["alpha", "beta"]
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "# skill\n"

def test_full_rewrite_drops_removed_skills(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    dest = tmp_path / "vault" / "skills"
    _skill(dest, "deleted_last_week")          # 上一轮收的，本机已经删了
    collect_skills(src, dest, Writer())
    assert (dest / "alpha").exists()
    assert not (dest / "deleted_last_week").exists()

def test_skill_with_own_git_repo_is_snapshotted_not_copied(tmp_path):
    src = tmp_path / "skills"
    d = _skill(src, "gamma")
    (d / "junk").mkdir()
    (d / "junk" / "big.bin").write_text("x" * 500, encoding="utf-8")
    (d / ".gitignore").write_text("junk/\n", encoding="utf-8")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "i"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    dest = tmp_path / "vault" / "skills"
    collect_skills(src, dest, Writer())
    assert (dest / "gamma" / "SKILL.md").exists()
    assert not (dest / "gamma" / ".git").exists()    # 不留嵌套仓
    assert not (dest / "gamma" / "junk").exists()    # gitignored 出不去

def test_missing_source_is_not_an_error(tmp_path):
    assert collect_skills(None, tmp_path / "vault" / "skills", Writer()) == []
    assert collect_skills(tmp_path / "nope", tmp_path / "vault" / "skills", Writer()) == []

def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    dest = tmp_path / "vault" / "skills"
    got = collect_skills(src, dest, Writer(dry_run=True))
    assert got == ["alpha"]
    assert not dest.exists()

def test_loose_files_at_skills_root_are_ignored(tmp_path):
    src = tmp_path / "skills"
    src.mkdir()
    (src / "README.md").write_text("说明", encoding="utf-8")
    _skill(src, "alpha")
    assert collect_skills(src, tmp_path / "v", Writer()) == ["alpha"]   # 只收目录
