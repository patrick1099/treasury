"""C 的状态检查（只读）。Plan 1 只报 skill 链接健康。

只检查 shared/skills/ 里的**期望项**——没 manifest 就无法安全判定某额外目录
以前归不归 hub 管，故本机自带的本地 skill 一律不报，免得把用户的东西冤成残留。
"""
import os
from pathlib import Path
from hub.model import SHARED, DeviceProfile
from hub.register import skill_targets

def _points_at(link: Path, src: Path) -> bool:
    try:
        return link.resolve() == src.resolve()
    except (OSError, RuntimeError):                       # 解析异常 → 落成 conflict，不外冒
        return False

def link_status(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, str]]:
    vault_root = Path(vault_root)
    shared = vault_root / SHARED / "skills"
    shared_skills = sorted((d for d in shared.iterdir() if d.is_dir()),
                           key=lambda p: p.name) if shared.is_dir() else []
    rows: list[tuple[str, str]] = []
    for target_dir in skill_targets(dev):
        for src in shared_skills:
            link = target_dir / src.name
            label = str(link)
            if not os.path.lexists(link):
                rows.append(("missing", label))
            elif _points_at(link, src):
                rows.append(("ok", label))
            else:
                rows.append(("conflict", label))     # 指别处 / 用户真目录 / 解析失败
    return rows
