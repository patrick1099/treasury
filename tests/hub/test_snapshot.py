import subprocess
import pytest
from pathlib import Path
from hub.guard import SecretPathError
from hub.snapshot import snapshot_repo, repo_meta, is_git_repo
from hub.writer import Writer

def _git(repo: Path, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myplugin"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    (repo / ".gitignore").write_text("node_modules/\nbuild/\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "huge.js").write_text("x" * 1000, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", "https://github.com/x/myplugin.git")
    return repo

def test_snapshot_repo_hard_gate_blocks_denied_path(tmp_path):
    """snapshot_repo 自身必须是硬闸——不靠调用方记得挡。

    直接调用 snapshot_repo,绕开 decl.py/skills.py 两条流水线里的 check_source
    call-site 闸,证明原语本身对密钥路径也会拒绝(防第五次同类事故:未来某个
    新调用方忘了在调用前挡)。repo 路径本身命中 DENIED_NAMES(secrets)。
    """
    repo = tmp_path / "secrets"
    repo.mkdir()
    (repo / "token.md").write_text("sekret", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    dest = tmp_path / "vault" / "secrets"
    with pytest.raises(SecretPathError):
        snapshot_repo(repo, dest, Writer())
    assert not dest.exists()               # 硬闸挡在写之前——没有任何字节落地

def test_snapshot_excludes_git_and_ignored(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer())
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"
    assert not (dest / ".git").exists()              # 不产生嵌套仓（否则是 gitlink 空壳）
    assert not (dest / "node_modules").exists()      # gitignored 出不去

def test_snapshot_is_full_rewrite(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("上一轮的残留", encoding="utf-8")
    snapshot_repo(repo, dest, Writer())
    assert not (dest / "stale.txt").exists()

def test_repo_meta_reports_remote_sha_clean(tmp_path):
    repo = _mk_repo(tmp_path)
    m = repo_meta(repo)
    assert m.name == "myplugin"
    assert m.remote == "https://github.com/x/myplugin.git"
    assert len(m.sha) == 40
    assert m.dirty is False

def test_dirty_worktree_is_flagged(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "src" / "a.py").write_text("print(2)\n", encoding="utf-8")   # 改了没提交
    assert repo_meta(repo).dirty is True

def test_snapshot_only_contains_committed_content(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "src" / "a.py").write_text("print(2)\n", encoding="utf-8")   # 改了没提交
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer())
    # git archive HEAD 只打包已提交的东西 —— 这正是要 dirty 警告的原因
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"

def test_dry_run_snapshots_nothing(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer(dry_run=True))
    assert not dest.exists()

def test_snapshot_records_dest_in_written(tmp_path):
    """真实(非 dry-run)快照必须让 dest 出现在 w.written —— 下游报告/清单靠它才知道备份了什么。"""
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    w = Writer()
    snapshot_repo(repo, dest, w)
    assert dest in w.written

def test_is_git_repo(tmp_path):
    repo = _mk_repo(tmp_path)
    assert is_git_repo(repo)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not is_git_repo(plain)

def test_repo_without_remote(tmp_path):
    repo = tmp_path / "local_only"
    repo.mkdir()
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    assert repo_meta(repo).remote is None      # 没 remote 不是错误
