import subprocess
from pathlib import Path
import pytest
from hub.collect.errors import MissingSourceError
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

def test_no_source_configured_is_not_an_error(tmp_path):
    """device.toml 里没配 skills(src is None)= 工具没装 = 正常。"""
    assert collect_skills(None, tmp_path / "vault" / "skills", Writer()) == []

def test_configured_but_missing_source_refuses_and_keeps_the_backup(tmp_path):
    """配了、但目录不在 → 配置错误,抛错点名路径;金库里已有的 skill 备份纹丝不动。

    (今天这条路径还删不掉东西——早退发生在 rmtree 之前——但它和记忆那条毁灭路径
    是同一个形状:把"配置坏了"读成"本机什么都没有"。让它响。)
    """
    dest = tmp_path / "vault" / "skills"
    _skill(dest, "backed_up_last_week")
    before = (dest / "backed_up_last_week" / "SKILL.md").read_bytes()

    with pytest.raises(MissingSourceError, match="nope"):
        collect_skills(tmp_path / "nope", dest, Writer())

    assert (dest / "backed_up_last_week" / "SKILL.md").read_bytes() == before

def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha", body="# new from src\n")
    dest = tmp_path / "vault" / "skills"
    stale_path = _skill(dest, "beta", body="# stale existing content\n") / "SKILL.md"
    stale_bytes_before = stale_path.read_bytes()               # 预置真实残留，防空判断
    got = collect_skills(src, dest, Writer(dry_run=True))
    assert got == ["alpha"]                                    # 报告说"会"收
    # dest 里已有的内容必须逐字节原样保留
    assert stale_path.read_bytes() == stale_bytes_before
    # src 的内容一个字节都不该落进 dest
    assert not (dest / "alpha").exists()

def test_empty_source_keeps_the_scaffolded_gitkeep(tmp_path):
    """最终评审 finding 9:源里一把 skill 都没有时,rmtree 把 dest 整个铲掉就再也不建回来
    —— 连 scaffold 铺的 .gitkeep 一起没了,于是 git 把这个目录整个丢掉,金库骨架破了一个洞。
    """
    src = tmp_path / "skills"
    src.mkdir()                                   # 本机一把 skill 都没有(或全删了)
    dest = tmp_path / "vault" / "skills"
    dest.mkdir(parents=True)
    (dest / ".gitkeep").write_text("", encoding="utf-8")     # scaffold 铺的

    assert collect_skills(src, dest, Writer()) == []

    assert dest.is_dir()
    assert (dest / ".gitkeep").exists()           # 骨架活下来

def test_empty_source_gitkeep_goes_through_the_writer(tmp_path):
    """补 .gitkeep 也必须走 Writer —— dry-run 下一个字节都不许落盘。"""
    src = tmp_path / "skills"
    src.mkdir()
    dest = tmp_path / "vault" / "skills"
    w = Writer(dry_run=True)
    collect_skills(src, dest, w)
    assert not dest.exists()                      # dry-run:什么都没建
    assert (dest / ".gitkeep") in w.written       # 但报告说它"会"写

def test_loose_files_at_skills_root_are_ignored(tmp_path):
    src = tmp_path / "skills"
    src.mkdir()
    (src / "README.md").write_text("说明", encoding="utf-8")
    _skill(src, "alpha")
    assert collect_skills(src, tmp_path / "v", Writer()) == ["alpha"]   # 只收目录
