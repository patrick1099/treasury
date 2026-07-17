"""C 的注册器：把金库共享源活链进各工具地盘（link-only，非破坏）。

Plan 1 只做 skill。逐个 skill 建目录 junction，改一处三家实时生效。
写盘前完整只读预检：**发现任何冲突就零写入**（一个字节都不写），绝不删用户的东西。
预检通过后逐个建链——**这一步不是原子的**：若第 N 个建链遇系统错误，前 N-1 个已建、
不回滚。但 link-only 且幂等，重跑 register 会把剩下的补齐，不留脏拷贝。
建链走 Writer（dry-run 闸，见 fslink）。register 本身**从不删任何路径**。
"""
import os
from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.fslink import resolves_to
from hub.vaultpaths import shared_skills_dir, within_shared_skills, SharedSkillsEscape

class RegisterConflict(RuntimeError):
    pass

def _agents_home(dev: DeviceProfile) -> Path:
    v = dev.paths.get("AGENTS_HOME")
    return Path(v) if v else Path.home() / ".agents"

def skill_targets(dev: DeviceProfile) -> list[Path]:
    """本机要建 skill 链接的 skills 目录集合。缺失的 home 跳过。"""
    out: list[Path] = []
    ch = dev.paths.get("CLAUDE_HOME")
    if ch:
        out.append(Path(ch) / "skills")          # Claude 读这里
    out.append(_agents_home(dev) / "skills")     # Codex + opencode 读这里
    return out

def register_skills(vault_root: Path, dev: DeviceProfile, w: Writer) -> list[str]:
    vault_root = Path(vault_root)
    shared = shared_skills_dir(vault_root)             # 断言容器不逃逸
    skills = sorted((d for d in shared.iterdir() if d.is_dir()), key=lambda p: p.name) \
        if shared.is_dir() else []
    for d in skills:
        if not within_shared_skills(d, vault_root):    # 单名也不许逃逸
            raise SharedSkillsEscape(
                f"shared/skills/{d.name} 经链接逃出金库，register 拒绝、零写入。")

    # ── 只读预检：全过才写，任何冲突立即中止（一个字节不动）──
    to_link: list[tuple[Path, Path]] = []   # (src, link) 待建
    ensured: list[str] = []                 # 现在已就位（待建 + 已就位）
    conflicts: list[str] = []
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):
            # 容器必须是真目录：symlink/junction/文件/坏链一律拒（Codex issue #11314：
            # 整个 skills 目录是链接时不被识别）。realpath(容器)!=真身路径 → 是链接/坏链。
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                conflicts.append(f"{target_dir}（skills 容器必须是真目录，不能是链接/文件）")
                continue
        # 不存在：留给 make_dir_link 的 mkdir(parents=True) 建成真目录，放行。
        for src in skills:
            link = target_dir / src.name
            label = f"{target_dir}{os.sep}{src.name}"
            if not os.path.lexists(link):
                to_link.append((src, link)); ensured.append(label)
            elif resolves_to(link, src):
                ensured.append(label)                       # 已就位，no-op
            else:
                conflicts.append(label)                     # 用户的/指别处的，不碰
    if conflicts:
        raise RegisterConflict(
            "以下位置已被非 hub 管理的同名项占用，register 不覆盖、未写任何链接。"
            "请先移开或改名：\n  " + "\n  ".join(conflicts))

    for src, link in to_link:
        w.make_dir_link(src, link)
    return ensured
