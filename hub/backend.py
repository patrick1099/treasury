import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

class ConflictError(RuntimeError):
    pass

class Backend(ABC):
    @abstractmethod
    def acquire(self) -> None: ...
    @abstractmethod
    def publish(self, message: str, push: bool = True) -> None: ...
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
            raise ConflictError(f"git pull 失败:\n{r.stderr or r.stdout}")

    def publish(self, message: str, push: bool = True) -> None:
        self._run("add", "-A")
        if self._run("status", "--porcelain").stdout.strip():
            self._run("commit", "-m", message)
        if push and self._has_remote():
            r = self._run("push", check=False)
            if r.returncode != 0:
                raise ConflictError(f"git push 失败:\n{r.stderr or r.stdout}")

    def status(self) -> str:
        return self._run("status", "--porcelain").stdout
