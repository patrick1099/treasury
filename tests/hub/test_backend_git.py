import subprocess
from pathlib import Path
import pytest
from hub.backend import GitBackend, ConflictError

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)

def _init_repo(path: Path):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A"); _git(path, "commit", "-qm", "seed")

def test_status_and_publish(tmp_path):
    repo = tmp_path / "clone"; _init_repo(repo)
    b = GitBackend(repo)
    (repo / "new.md").write_text("hi\n", encoding="utf-8")
    assert b.status().strip() != ""       # 有未提交改动
    b.publish("add new")
    assert b.status().strip() == ""       # 提交后干净

def test_acquire_conflict_raises(tmp_path):
    # 远端与本地在同一文件分叉 -> 非 ff -> ConflictError
    remote = tmp_path / "remote"; _init_repo(remote)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    # 远端前进一步
    (remote / "seed.txt").write_text("remote\n", encoding="utf-8")
    _git(remote, "commit", "-qam", "remote change")
    # 本地也改同文件并提交 -> 分叉
    (clone / "seed.txt").write_text("local\n", encoding="utf-8")
    _git(clone, "commit", "-qam", "local change")
    with pytest.raises(ConflictError):
        GitBackend(clone).acquire()

def test_acquire_merges_nonconflicting_changes(tmp_path):
    # 对等场景：远端与本地各自新增【不同文件】-> 应自动 merge，不抛
    remote = tmp_path / "remote"; _init_repo(remote)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    (remote / "a.md").write_text("A\n", encoding="utf-8")
    _git(remote, "add", "-A"); _git(remote, "commit", "-qm", "remote a")
    (clone / "b.md").write_text("B\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-qm", "local b")
    GitBackend(clone).acquire()             # 不应抛
    assert (clone / "a.md").exists() and (clone / "b.md").exists()
