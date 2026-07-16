"""散装 skill 流水线:整目录快照,全量重写。

~/.claude/skills/ 和 ~/.codex/skills/ 下的 skill 很多没有 git 仓,是**唯一副本**。
带仓的走 git archive(避免嵌套仓变空壳),不带仓的直接拷。
"""
from pathlib import Path
from hub.collect.errors import require_source
from hub.fslink import is_under
from hub.guard import check_source, SecretPathError
from hub.snapshot import is_git_repo, snapshot_repo
from hub.writer import Writer

class SkillScanError(RuntimeError):
    """skill 源扫描阶段的失败(链接环/坏链等),发生在动 dest 之前。"""

def collect_skills(src: Path | None, dest: Path, w: Writer,
                    skip_under: Path | None = None) -> list[str]:
    """src is None = device.toml 里没配 skills = 工具没装 = 正常,什么都不做。

    配了、但目录不在 → 抛错(见 errors.py)。今天这条路径还不至于删掉金库里的 skill
    (早退发生在 `rmtree` **之前**),但它跟记忆那条毁灭路径是同一个形状:
    把"配置坏了"读成"本机什么都没有"。这里让它响,免得金库里的 skill 备份悄悄变成
    一份永不更新的化石,而用户以为每次 collect 都在备份。

    skip_under:register 把 shared 的 skill 链进了本机 skills 目录后,realpath 落进
    skip_under 的条目会被跳过——不然 collect 又把它当"本机产物"再备份回金库,
    形成 shared → junction → collect → 设备区 的回环。
    """
    if src is None:
        return []
    src, dest = Path(src), Path(dest)
    check_source(src)
    require_source(src, "[sources.<工具>] skills")

    # ── 只读分类:枚举**全部**入口,逐个走统一预检(skip / resolve / is_dir /
    #    check_source)。坏链/链接环不再被 is_dir()==False 静默吞掉、悄悄漏备份——
    #    它是异常,转成 SkillScanError 停下来报;任何解析异常都在动 dest 之前抛。
    #    ("配坏读成本机为空 / 先删后验"是 A 阶段的毁灭形状,这里堵死。)──
    plan: list[tuple[str, Path, bool]] = []            # (name, dir, is_repo)
    for d in sorted(src.iterdir(), key=lambda p: p.name):
        try:
            if skip_under is not None and is_under(d, skip_under):
                continue                               # 活链进来的共享 skill,不重复备份
            d.resolve(strict=True)                     # 坏链/环 → OSError(下面转 SkillScanError)
            if not d.is_dir():
                continue                               # 解析成功但不是目录(普通文件)→ 跳过
            check_source(d)                            # 硬闸:每个 skill 目录
        except SecretPathError:
            raise                                      # 密钥闸原样抛(它就是要拒)
        except (OSError, RuntimeError) as e:
            raise SkillScanError(
                f"skill 源无法解析(疑似坏链/链接环): {d} —— {e}") from e
        plan.append((d.name, d, is_git_repo(d)))

    # 分类全过,才清空并重写。
    w.rmtree(dest)                                     # 全量重写:本机删掉的 skill,金库也不该留
    for name, d, repo in plan:
        if repo:
            snapshot_repo(d, dest / name, w)
        else:
            w.copy_tree(d, dest / name)
    if not plan:
        # 源里一把 skill 都没有:rmtree 把 dest 铲了,补回 .gitkeep 免得金库骨架破洞。
        w.write_text(dest / ".gitkeep", "")
    return [name for name, _, _ in plan]
