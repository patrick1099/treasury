"""记忆流水线:镜像同步。

本机源里有的 → 写进 <host>/claude/memory/
本机源里没了的 → 从金库删掉(先列出来给人确认)

只镜像**本机自己那一块**。shared/ 与别的设备的文件夹碰都不碰——
本机的 collect 凭什么删别人写的东西。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.frontmatter import load_memory, dump_memory, FrontmatterError
from hub.guard import check_source
from hub.writer import Writer

@dataclass
class MemoryResult:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped_sensitive: list[str] = field(default_factory=list)

def _home(vault_root: Path, host: str) -> Path:
    return Path(vault_root) / host / "claude" / "memory"

def _scan(source_dirs: list[Path]) -> tuple[list, list[str]]:
    """读源目录里的全部记忆。解析失败 → 抛错,**绝不静默跳过**。"""
    mems, sensitive = [], []
    for d in source_dirs:
        d = Path(d)
        check_source(d)                     # 硬闸
        if not d.is_dir():
            continue                        # 工具没装 = 正常
        for p in sorted(d.glob("*.md")):
            if p.name in ("MEMORY.md", "memory-index.md"):
                continue                    # 派生索引，不是记忆
            try:
                m = load_memory(p)
            except FrontmatterError as e:
                raise FrontmatterError(f"{p}: {e}") from e
            if m.sensitive:
                sensitive.append(m.name)    # 硬闸 3：sensitive 不入库
                continue
            mems.append(m)
    return mems, sensitive

def plan_memory(source_dirs: list[Path], vault_root: Path, host: str) -> MemoryResult:
    """只算不写:告诉你这次会写哪些、会删哪些。"""
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    have = {p.stem for p in home.glob("*.md")} if home.is_dir() else set()
    names = {m.name for m in mems}
    return MemoryResult(
        written=sorted(names),
        deleted=sorted(have - names),
        skipped_sensitive=sorted(sensitive),
    )

def collect_memory(source_dirs: list[Path], vault_root: Path, host: str,
                   w: Writer) -> MemoryResult:
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    have = {p.stem for p in home.glob("*.md")} if home.is_dir() else set()
    names = {m.name for m in mems}
    for m in mems:
        w.write_text(home / f"{m.name}.md", dump_memory(m))
    for gone in sorted(have - names):
        w.unlink(home / f"{gone}.md")
    return MemoryResult(written=sorted(names), deleted=sorted(have - names),
                        skipped_sensitive=sorted(sensitive))
