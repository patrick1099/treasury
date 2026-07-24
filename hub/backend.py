import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

class ConflictError(RuntimeError):
    pass

class RemoteUnavailable(ConflictError):
    """够不着远端(网络/超时/认证)——**不是**内容冲突。

    分出来是因为报错文案会把人带偏:pull 超时被笼统说成"git 冲突,请手工解决",
    人就去找根本不存在的冲突。手工解冲突治不了网络,重试才行。
    仍继承 ConflictError,老的 except 分支不受影响。
    """

class GitlinkTracked(RuntimeError):
    """索引里出现 gitlink(mode 160000)。

    金库只存**文件**。把带 `.git` 的目录直接 `git add` 进来,父仓记下的是一个
    它自己都没有的 commit sha:本机看着好好的,别的设备 clone 下来那个目录是**空的**。
    带 .git 的产物必须走 induction(临时移开 .git → add 成 blob → 移回)。
    """
    def __init__(self, paths):
        self.paths = list(paths)
        super().__init__(
            "金库索引里出现 gitlink(空壳,别的设备 clone 拿不到内容):\n"
            + "".join(f"  - {p}\n" for p in self.paths)
            + "带 .git 的目录不能直接 add;跑 `hub induct --vault <金库> <路径>` 正规纳入后重试。")

def tracked_gitlinks(repo) -> list[str]:
    """索引里所有 gitlink 条目的路径(金库的硬不变量是:一个都不该有)。"""
    r = subprocess.run(["git", "ls-files", "-s"], cwd=str(repo), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return []
    return [l.split("\t", 1)[1] for l in r.stdout.splitlines()
            if l.startswith("160000") and "\t" in l]

class Backend(ABC):
    @abstractmethod
    def acquire(self) -> None: ...
    @abstractmethod
    def publish(self, message: str) -> None: ...
    @abstractmethod
    def status(self) -> str: ...

class GitBackend(Backend):
    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.repo, check=check,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def _has_remote(self) -> bool:
        return self._run("remote", check=False).stdout.strip() != ""

    def _conflicted_files(self) -> list[str]:
        out = self._run("diff", "--name-only", "--diff-filter=U", check=False).stdout
        return [l for l in out.splitlines() if l.strip()]

    def acquire(self) -> None:
        if not self._has_remote():
            return
        r = self._run("pull", "--no-rebase", "--no-edit", check=False)
        if r.returncode != 0:
            conflicted = self._conflicted_files()
            if conflicted:
                raise ConflictError("git merge 冲突，需手工解决:\n" + "\n".join(conflicted))
            raise RemoteUnavailable(f"git pull 失败:\n{r.stderr or r.stdout}")

    def publish(self, message: str) -> None:
        """提交,有 remote 就推。

        (曾经有个 push=False 开关,给已经删掉的 `hub process`(只本地提交、不推)用。
        现在唯一的调用方是 `hub sync`,它的语义就是"推上去";没有 remote 时 _has_remote()
        自己会跳过 push,离线照样能用。没有第二种调用方式了,开关跟着走。)
        """
        self._run("add", "-A")
        # `add -A` 是 gitlink 的生产机器:shared/ 下但凡出现一个带 .git 的目录,
        # 它就无声无息记成 gitlink。所以闸设在这里——提交之前,不是提交之后。
        links = tracked_gitlinks(self.repo)
        if links:
            raise GitlinkTracked(links)
        if self._run("status", "--porcelain").stdout.strip():
            self._run("commit", "-m", message)
        if self._has_remote():
            r = self._run("push", check=False)
            if r.returncode != 0:
                raise RemoteUnavailable(f"git push 失败:\n{r.stderr or r.stdout}")

    def status(self) -> str:
        return self._run("status", "--porcelain").stdout
