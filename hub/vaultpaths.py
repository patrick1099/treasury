"""金库路径边界断言：shared/skills 容器不得经链接逃出金库。

Plan 1 只查了叶子 shared/skills/<name> 是不是链接，没查容器本身。若
vault/shared/skills 是指向金库外的 junction，promote 会往金库外落盘、register
会枚举金库外目录建链、status 还报 ok。这里把容器边界一次锁死，三处共用。
"""
import os
from pathlib import Path
from hub.model import SHARED

class SharedSkillsEscape(RuntimeError):
    pass

def shared_skills_dir(vault_root: Path) -> Path:
    """返回 <vault>/shared/skills；经链接解析后逃出金库则抛 SharedSkillsEscape。

    允许 vault_root 整体经链接访问（整个金库挂在被链接的 home 下也行），所以比的是
    realpath(shared/skills) 是否等于 realpath(vault_root)/shared/skills，不是拿
    realpath(vault_root) 去比 vault_root。容器不存在时不报错（首次注册前它可能还没建）。
    """
    vault_root = Path(vault_root)
    container = vault_root / SHARED / "skills"
    # 无条件比对（不加 lexists 守卫）：shared/skills 尚不存在但父目录 shared 是外链时，
    # realpath 会解析到金库外——只有无条件比对才挡得住这种父目录逃逸。与
    # promote._shared_memory_dir / memview._shared_memory_dir 保持一致。
    expected = os.path.join(os.path.realpath(vault_root), SHARED, "skills")
    if os.path.realpath(container) != expected:
        raise SharedSkillsEscape(
            f"shared/skills 经链接逃出金库：{container} → {os.path.realpath(container)}；"
            f"应在 {expected} 内。停下来让你处理，绝不往金库外读写。")
    return container

def within_shared_skills(child: Path, vault_root: Path) -> bool:
    """child 解析后是否仍落在（已验证不逃逸的）shared/skills 内。异常一律 False。"""
    container = shared_skills_dir(vault_root)          # 先保证容器本身不逃逸
    try:
        c = os.path.realpath(Path(child))
        base = os.path.realpath(container)
    except (OSError, ValueError):
        return False
    return c == base or c.startswith(base + os.sep)
