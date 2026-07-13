"""仓库快照:git archive HEAD → 一棵干净的普通目录树。

**不能用 cp -r**:
1. 把带 .git 的目录拷进另一个 git 仓,外层会把它记成 gitlink 空壳,
   新机 clone 下来是空目录——你以为备份了,其实没有。
2. cp -r 会把 node_modules / 构建产物 / .env 一起拖进来(实测 1MB → 22MB)。

git archive 只打包 git 跟踪的文件,两个问题一起解决。
"""
import io
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

@dataclass
class RepoMeta:
    name: str
    remote: str | None
    sha: str
    dirty: bool          # 工作区有未提交改动 → 快照里没有它们

def _git(repo: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}))

def is_git_repo(path: Path) -> bool:
    return (Path(path) / ".git").exists()

def repo_meta(repo: Path) -> RepoMeta:
    repo = Path(repo)
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    dirty = bool(_git(repo, "status", "--porcelain").stdout.strip())
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8")
    remote = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    return RepoMeta(name=repo.name, remote=remote, sha=sha, dirty=dirty)

def snapshot_repo(repo: Path, dest: Path, w: Writer) -> RepoMeta:
    """把 repo 的 HEAD 快照全量重写到 dest。返回仓库元数据。"""
    repo, dest = Path(repo), Path(dest)
    meta = repo_meta(repo)
    w.rmtree(dest)
    if w.dry_run:
        print(f"  [dry-run] 快照 {repo} → {dest}  (sha {meta.sha[:8]}"
              f"{', 有未提交改动' if meta.dirty else ''})")
        return meta
    dest.mkdir(parents=True, exist_ok=True)
    tar = _git(repo, "archive", "--format=tar", "HEAD", binary=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        tf.extractall(dest, filter="data")
    return meta
