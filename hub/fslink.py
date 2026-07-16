"""跨平台目录链接 + realpath 归属判断（底层 os 操作，不含 dry-run）。

link-only：建链失败就抛错，绝不静默拷贝。
Windows 用目录 junction（mklink /J，不需管理员），POSIX 用 symlink。
删除只删链接点、绝不跟随进目标删内容。
"""
import os
import subprocess
from pathlib import Path

class LinkError(RuntimeError):
    pass

def make_dir_link(target: Path, link: Path) -> None:
    target, link = Path(target), Path(link)
    if not target.is_dir():
        raise NotADirectoryError(f"链接目标不是目录或不存在: {target}")
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # junction：不需要管理员/开发者模式（symlink 才需要）
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise LinkError(f"mklink /J 失败 ({link} → {target}): "
                            f"{r.stderr.strip() or r.stdout.strip()}")
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as e:
            raise LinkError(f"symlink 失败 ({link} → {target}): {e}") from e

def remove_dir_link(link: Path) -> None:
    """只删链接点本身。Windows junction 用 os.rmdir（删 reparse 点、不碰目标）；
    POSIX symlink 用 os.unlink。若 link 是真实非空目录，os.rmdir 会抛——刻意的防线，
    绝不误删真目录内容。"""
    link = Path(link)
    if not os.path.lexists(link):
        return
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)

def is_under(path: Path, ancestor: Path) -> bool:
    p = Path(path).resolve()
    a = Path(ancestor).resolve()
    return p == a or a in p.parents

def resolves_to(link: Path, src: Path) -> bool:
    """link 跟随解析后是否精确指向 src；解析失败（坏链/环等）→ False（当作不是我们的），
    异常一律吞成 False、不外冒。"""
    try:
        return link.resolve() == src.resolve()
    except (OSError, RuntimeError):
        return False
