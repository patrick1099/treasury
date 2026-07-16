"""把备份区选定内容提升进共享区 shared/。

规矩（SCHEMA §6/§7）：**复制不是移动**（源在备份区不动，下次 collect 照样镜像）；
同名不同内容**立即停下问**，绝不静默覆盖。源由 host/tool/name 推导，三者都必须是
单路径组件、解析后严格落在备份区内 —— 不接受任意绝对路径，挡穿越/逃逸/密钥/自引用。
"""
import os
from pathlib import Path
from hub.model import SHARED
from hub.writer import Writer
from hub.guard import check_source, is_denied

class PromoteConflict(RuntimeError):
    pass

def _single_component(label: str, value: str) -> None:
    if "/" in value or "\\" in value or value in ("", ".", ".."):
        raise ValueError(f"非法 {label}（含路径分隔符或穿越）: {value!r}")

def _rel_files(root: Path) -> dict[str, bytes]:
    """目录树里所有文件的 {相对posix路径: 字节内容}。按内容比，不用 stat 浅比
    （filecmp.dircmp 默认按 os.stat 签名，同大小改内容会误判"相同"）。
    按 is_denied 排除密钥文件——与 copy_tree 实际拷贝的集合保持一致，
    否则 src 里若混进 .env，比对永远"不同"、还顺手读了密钥字节。"""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and not is_denied(p)}

def _same_tree(a: Path, b: Path) -> bool:
    return _rel_files(a) == _rel_files(b)

def promote_skill(vault_root: Path, host: str, tool: str, name: str, w: Writer) -> Path:
    _single_component("host", host)
    _single_component("tool", tool)
    _single_component("name", name)
    vault_root = Path(vault_root)
    backup_root = (vault_root / host).resolve()          # 本设备备份区根
    src = vault_root / host / tool / "skills" / name
    check_source(src)                                     # 读闸：先于任何 access（全局约束）
    rsrc = src.resolve()                                  # 跟随链接解析（strict=False）
    if rsrc != backup_root and backup_root not in rsrc.parents:
        raise ValueError(f"源逃出备份区（疑似链接逃逸）: {src} → {rsrc}")
    if not src.is_dir():
        raise FileNotFoundError(f"备份区没有这把 skill: {src}")

    dest = vault_root / SHARED / "skills" / name
    if os.path.lexists(dest):
        if not dest.is_dir():
            raise PromoteConflict(
                f"shared/skills/{name} 已被非目录（文件/坏链/异处链接）占用——停下来让你处理。")
        if _same_tree(src, dest):
            return dest                                  # 严格幂等：内容相同，一个字节都不写
        raise PromoteConflict(
            f"shared/skills/{name} 已存在且内容不同——停下来让你决定，"
            f"绝不静默覆盖。要么改名，要么先手工核对合并。")
    w.copy_tree(src, dest)
    return dest
