"""仓库快照:git archive HEAD → 一棵干净的普通目录树。

**不能用 cp -r**:
1. 把带 .git 的目录拷进另一个 git 仓,外层会把它记成 gitlink 空壳,
   新机 clone 下来是空目录——你以为备份了,其实没有。
2. cp -r 会把 node_modules / 构建产物 / .env 一起拖进来(实测 1MB → 22MB)。

git archive 只打包 git 跟踪的文件,两个问题一起解决。
"""
import subprocess
from dataclasses import dataclass
from pathlib import Path
from hub.guard import check_source
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
    """把 repo 的 HEAD 快照全量重写到 dest。返回仓库元数据。

    check_source(repo) 是原语自带的硬闸,不是调用方(decl.py/skills.py)那道
    call-site 闸的替代——那道闸留着不动,它拦得更早、报错更好(能说清楚是
    流水线里哪个条目被拒)。这里是纵深防御:万一未来某个新调用方忘了先挡
    (本项目已经因为"闸设在调用点而不是原语里"同类事故发生过四次),原语
    自己也会拒绝往下走,失败方向是"什么都不写",不是"照真的写"。
    """
    repo, dest = Path(repo), Path(dest)
    check_source(repo)
    meta = repo_meta(repo)
    tar = _git(repo, "archive", "--format=tar", "HEAD", binary=True).stdout
    w.extract_tar(dest, tar)
    return meta
