import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

_RETRY_DELAYS = (3, 8)          # 退避秒数;长度=重试次数(测试里 monkeypatch 掉)

# 挂死的连接要尽快认输,否则一次卡死 300s、重试就成了纯粹的受罪。
# 门槛压得很低(整整 60 秒连 1000 B/s 都跑不到才算死),正常的慢不会被误伤。
_NET = ("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=60")

def _first_line(e: Exception) -> str:
    return next((l for l in str(e).splitlines() if l.strip()), "")

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

    def _retry(self, what: str, once):
        """瞬时的够不着远端 → 退避重试;内容冲突 → 立刻抛,一次都不重试。

        实测(2026-07-24,本机走代理):金库是**私有**仓,每次 git 操作要多吃一轮
        401 挑战 + 带凭据重来,在抖动的代理节点上单次失败率约 1/6;重试两次压到 ~1/200。
        公开仓匿名一次过,所以以前只有金库在超时——不是路由规则的问题,别去改 Clash。
        """
        for delay in (*_RETRY_DELAYS, None):
            try:
                return once()
            except RemoteUnavailable as e:
                if delay is None:
                    raise
                print(f"  {what}:够不着远端,{delay}s 后重试 —— {_first_line(e)}")
                time.sleep(delay)

    def acquire(self) -> None:
        if not self._has_remote():
            return
        self._retry("git pull", self._pull_once)

    def _pull_once(self) -> None:
        r = self._run(*_NET, "pull", "--no-rebase", "--no-edit", check=False)
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
            # 重试 push 是安全的:上一次要么没到远端,要么到了——到了的话这次就是
            # "Everything up-to-date" 退 0。提交已经在本地,重推不会产生第二份东西。
            self._retry("git push", self._push_once)

    def _push_once(self) -> None:
        r = self._run(*_NET, "push", check=False)
        if r.returncode != 0:
            raise RemoteUnavailable(f"git push 失败:\n{r.stderr or r.stdout}")

    def status(self) -> str:
        return self._run("status", "--porcelain").stdout
