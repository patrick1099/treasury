"""把备份区选定内容提升进共享区 shared/。

规矩（SCHEMA §6/§7）：**复制不是移动**（源在备份区不动，下次 collect 照样镜像）；
同名不同内容**立即停下问**，绝不静默覆盖。源由 host/tool/name 推导，三者都必须是
单路径组件、解析后严格落在备份区内 —— 不接受任意绝对路径，挡穿越/逃逸/密钥/自引用。
"""
import os
from pathlib import Path
from hub.writer import Writer
from hub.guard import check_source, is_denied
from hub.vaultpaths import shared_skills_dir
from hub.model import SHARED
from hub.frontmatter import load_memory
from hub.scope import parse_scope

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

def _is_link_at(path: Path) -> bool:
    """True 当且仅当 path 自身的最后一段是符号链接/Windows junction——
    不管父目录是不是链接、也不管链接目标存不存在（坏链也算）。
    用 realpath(path) 与 realpath(父目录)/basename 比较，把"链接性"锁在叶子上，
    避免 vault 挂在被链接父目录下面的真实子目录被误判。"""
    p = os.path.abspath(path)
    parent_real = os.path.realpath(os.path.dirname(p))
    expected = os.path.join(parent_real, os.path.basename(p))
    return os.path.realpath(p) != expected

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

    dest = shared_skills_dir(vault_root) / name        # 断言容器不逃逸
    if os.path.lexists(dest):
        if _is_link_at(dest):
            raise PromoteConflict(
                f"shared/skills/{name} 是意外出现的链接（symlink/junction）——"
                f"不管指向哪、指向是否存在，都停下来让你处理，绝不当真目录用。")
        if not dest.is_dir():
            raise PromoteConflict(
                f"shared/skills/{name} 已被非目录（文件/坏链）占用——停下来让你处理。")
        if _same_tree(src, dest):
            return dest                                  # 严格幂等：内容相同，一个字节都不写
        raise PromoteConflict(
            f"shared/skills/{name} 已存在且内容不同——停下来让你决定，"
            f"绝不静默覆盖。要么改名，要么先手工核对合并。")
    w.copy_tree(src, dest)
    return dest

class PromoteMemoryConflict(RuntimeError):
    pass

def _shared_memory_dir(vault_root: Path) -> Path:
    d = (vault_root / SHARED / "memory")
    # **不加 lexists 守卫**：shared/memory 尚不存在但父目录 shared 是外链时，
    # realpath(d) 会解析到金库外——只有无条件比对才挡得住这种父目录逃逸。
    expected = os.path.join(os.path.realpath(vault_root), SHARED, "memory")
    if os.path.realpath(d) != expected:
        raise ValueError(f"shared/memory 经链接逃出金库: {d} → {os.path.realpath(d)}")
    return d

def _classify_memory(vault_root: Path, host: str, name: str) -> tuple[Path, Path, str]:
    """返回 (src, dest, 动作)；动作 ∈ {copy, noop}；冲突/非法直接抛。"""
    _single_component("host", host)
    _single_component("name", name)
    src = vault_root / host / "claude" / "memory" / f"{name}.md"
    check_source(src)                                  # 读闸先于 access
    # 源 containment：源文件（或其所在 memory 目录）经链接逃出本机备份区 → 拒绝
    backup_root = os.path.realpath(vault_root / host)
    rsrc = os.path.realpath(src)
    if rsrc != backup_root and not rsrc.startswith(backup_root + os.sep):
        raise ValueError(f"记忆源经链接逃出备份区: {src} → {rsrc}")
    if not src.is_file():
        raise FileNotFoundError(f"备份区没有这条记忆: {src}")
    parse_scope(load_memory(src).scope)                # frontmatter/scope 非法即停（抛 ScopeError←ValueError）
    dest = _shared_memory_dir(vault_root) / f"{name}.md"
    if os.path.lexists(dest):
        if os.path.islink(dest) or os.path.isdir(dest) or _is_link_at(dest):
            raise PromoteMemoryConflict(f"shared/memory/{name}.md 被目录/链接占用，停下来让你处理。")
        if not dest.is_file():
            raise PromoteMemoryConflict(f"shared/memory/{name}.md 被非普通文件占用，停下来让你处理。")
        if dest.read_bytes() == src.read_bytes():
            return src, dest, "noop"
        raise PromoteMemoryConflict(
            f"shared/memory/{name}.md 已存在且内容不同——停下来让你决定，绝不静默覆盖。")
    return src, dest, "copy"

def promote_memory(vault_root: Path, host: str, name: str, w: Writer) -> Path:
    vault_root = Path(vault_root)
    src, dest, action = _classify_memory(vault_root, host, name)
    if action == "copy":
        w.copy_file(src, dest)
    return dest

def promote_memory_all(vault_root: Path, host: str, w: Writer) -> list[Path]:
    """把本机备份区所有记忆批量提升。全量预检：任一冲突/非法→零写入、报全清单。非 mirror。"""
    vault_root = Path(vault_root)
    mem_dir = vault_root / host / "claude" / "memory"
    names = sorted(p.stem for p in mem_dir.glob("*.md")) if mem_dir.is_dir() else []
    plans: list[tuple[Path, Path, str]] = []
    errors: list[str] = []
    for n in names:
        try:
            plans.append(_classify_memory(vault_root, host, n))
        except (PromoteMemoryConflict, ValueError, FileNotFoundError) as e:
            errors.append(f"{n}: {e}")
    if errors:
        raise PromoteMemoryConflict(
            "批量提升预检失败，一个字节都没写。请逐条处理后重试：\n  " + "\n  ".join(errors))
    done: list[Path] = []
    for src, dest, action in plans:
        if action == "copy":
            w.copy_file(src, dest)
        done.append(dest)
    return done
