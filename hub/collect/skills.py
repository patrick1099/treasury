"""散装 skill 流水线:整目录快照,全量重写。

~/.claude/skills/ 和 ~/.codex/skills/ 下的 skill 很多没有 git 仓,是**唯一副本**。
带仓的走 git archive(避免嵌套仓变空壳),不带仓的直接拷。
"""
from pathlib import Path
from hub.guard import check_source
from hub.snapshot import is_git_repo, snapshot_repo
from hub.writer import Writer

def collect_skills(src: Path | None, dest: Path, w: Writer) -> list[str]:
    if src is None:
        return []
    src, dest = Path(src), Path(dest)
    check_source(src)
    if not src.is_dir():
        return []                       # 工具没装 = 正常
    w.rmtree(dest)                      # 全量重写:本机删掉的 skill，金库也不该留
    names = []
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        check_source(d)                 # 硬闸:每个 skill 目录
        if is_git_repo(d):
            snapshot_repo(d, dest / d.name, w)
        else:
            w.copy_tree(d, dest / d.name)
        names.append(d.name)
    return names
