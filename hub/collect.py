from pathlib import Path
from hub.frontmatter import load_memory, dump_memory, FrontmatterError

_DERIVED = {"MEMORY.md", "memory-index.md"}

def _existing(vault_root: Path) -> dict[str, Path]:
    """金库里现有记忆:name -> 它所在的 <归属>/memory 目录。"""
    out: dict[str, Path] = {}
    for owner in vault_root.iterdir():
        if not owner.is_dir() or owner.name.startswith("."):
            continue
        mem = owner / "memory"
        if mem.is_dir():
            for p in mem.glob("*.md"):
                if p.name not in _DERIVED:
                    out[p.stem] = mem
    return out

def collect_memories(source_dirs: list[Path], vault_root: Path, host: str) -> list[str]:
    """把本机工具目录里的记忆收进金库。

    落点:金库里已有同名记忆 → **写回它原来的归属文件夹**(这是对那条记忆的更新,
    它可能来自公共池或别的设备,不能复制成一份本机自产的孪生体——否则 pull 落地到
    工具目录、collect 再收回来,就成了回环)。否则写进本机 <host>/memory/。
    """
    home = vault_root / host / "memory"
    home.mkdir(parents=True, exist_ok=True)
    existing = _existing(vault_root)
    collected: list[str] = []
    for d in source_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.name in _DERIVED:
                continue
            try:
                m = load_memory(p)
            except (FrontmatterError, UnicodeDecodeError, OSError):
                continue
            if m.sensitive:
                continue
            dest = existing.get(m.name, home)
            (dest / f"{m.name}.md").write_text(
                dump_memory(m), encoding="utf-8", newline="\n")
            existing.setdefault(m.name, dest)
            collected.append(m.name)
    return collected
