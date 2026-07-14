"""记忆流水线:镜像同步。

本机源里有的 → 写进 <host>/claude/memory/
本机源里没了的 → 从金库删掉(先列出来给人确认)

只镜像**本机自己那一块**。shared/ 与别的设备的文件夹碰都不碰——
本机的 collect 凭什么删别人写的东西。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.collect.errors import require_source
from hub.frontmatter import load_memory, dump_memory
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
    """读源目录里的全部记忆。解析失败 → 抛错,**绝不静默跳过**。

    源目录**配了就必须在**(见 errors.py)。过去这里把"配了但不在"当成"工具没装"
    跳过,于是源侧零条记忆 → _diff() 判定金库里每一条都该删 → 金库(唯一备份)被清空。
    "没配"这个合法情况由 source_dirs 为空表达,不由"目录不存在"表达。
    """
    mems, sensitive = [], []
    for d in source_dirs:
        d = Path(d)
        check_source(d)                     # 硬闸:目录本身(密钥路径)
        require_source(d, "[sources.claude] memory 里的一项")
        for p in sorted(d.glob("*.md")):
            if p.name in ("MEMORY.md", "memory-index.md"):
                continue                    # 派生索引，不是记忆
            check_source(p)                 # 硬闸:每个文件——挡住目录干净但
                                             # 文件本身(如符号链接/junction)解析
                                             # 后落进 secrets/ 的情况
            m = load_memory(p)              # 解析失败直接向上抛，路径已在
                                             # load_memory 的错误信息里带过一次
            if m.sensitive:
                sensitive.append(m.name)    # 硬闸 3：sensitive 不入库
                continue
            mems.append(m)
    return mems, sensitive

def _diff(mems: list, home: Path) -> tuple[set[str], set[str]]:
    """算一次:本次要写的名字集合、要删的名字集合。

    plan_memory 和 collect_memory **都必须**调这一个函数——不能各自重算,
    否则预览(--dry-run)和实际发生的事就有各自漂移的可能。
    """
    have = {p.stem for p in home.glob("*.md")} if home.is_dir() else set()
    names = {m.name for m in mems}
    return names, have - names

def plan_memory(source_dirs: list[Path], vault_root: Path, host: str) -> MemoryResult:
    """只算不写:告诉你这次会写哪些、会删哪些。"""
    if not source_dirs:
        return MemoryResult()               # 没配记忆源 → 不镜像。见 _no_source_no_mirror
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    names, gone = _diff(mems, home)
    return MemoryResult(
        written=sorted(names),
        deleted=sorted(gone),
        skipped_sensitive=sorted(sensitive),
    )

def collect_memory(source_dirs: list[Path], vault_root: Path, host: str,
                   w: Writer) -> MemoryResult:
    """镜像本机的记忆源 → <host>/claude/memory/。

    **没配记忆源(source_dirs 为空)= 不镜像**,不是"源里一条都没有"。
    镜像删除只有在**真的读过源**之后才有意义:
    - `[]`           → 没这个源 → 什么都不做(工具没装)。
    - `["<不存在>"]`  → 配坏了   → 抛错(_scan 里的 require_source)。
    - `["<空目录>"]`  → 读过了,源里确实空了 → **照常镜像删除**,那是用户的真实意图。
    """
    if not source_dirs:
        return MemoryResult()
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    names, gone = _diff(mems, home)
    for m in mems:
        w.write_text(home / f"{m.name}.md", dump_memory(m))
    for name in sorted(gone):
        w.unlink(home / f"{name}.md")
    return MemoryResult(written=sorted(names), deleted=sorted(gone),
                        skipped_sensitive=sorted(sensitive))
