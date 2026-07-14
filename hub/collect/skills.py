"""散装 skill 流水线:整目录快照,全量重写。

~/.claude/skills/ 和 ~/.codex/skills/ 下的 skill 很多没有 git 仓,是**唯一副本**。
带仓的走 git archive(避免嵌套仓变空壳),不带仓的直接拷。
"""
from pathlib import Path
from hub.collect.errors import require_source
from hub.guard import check_source
from hub.snapshot import is_git_repo, snapshot_repo
from hub.writer import Writer

def collect_skills(src: Path | None, dest: Path, w: Writer) -> list[str]:
    """src is None = device.toml 里没配 skills = 工具没装 = 正常,什么都不做。

    配了、但目录不在 → 抛错(见 errors.py)。今天这条路径还不至于删掉金库里的 skill
    (`is_dir()` 的早退发生在 `rmtree` **之前**),但它跟记忆那条毁灭路径是同一个形状:
    把"配置坏了"读成"本机什么都没有"。这里让它响,免得金库里的 skill 备份悄悄变成
    一份永不更新的化石,而用户以为每次 collect 都在备份。
    """
    if src is None:
        return []
    src, dest = Path(src), Path(dest)
    check_source(src)
    require_source(src, "[sources.<工具>] skills")
    w.rmtree(dest)                      # 全量重写:本机删掉的 skill，金库也不该留
    names = []
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        check_source(d)                 # 硬闸:每个 skill 目录
        if is_git_repo(d):
            snapshot_repo(d, dest / d.name, w)
        else:
            w.copy_tree(d, dest / d.name)
        names.append(d.name)
    if not names:
        # 源里一把 skill 都没有:上面那记 rmtree 把 dest 整个铲了,再也没建回来——
        # 连 scaffold 铺的 .gitkeep 一起没了,于是 git 把这个目录整个丢掉,金库骨架
        # 破一个洞。补回来(走 Writer,dry-run 下照样一个字节不落盘)。
        w.write_text(dest / ".gitkeep", "")
    return names
