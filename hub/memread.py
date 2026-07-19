"""memory-read 核心：只在本机该 tool 的视图里查名（拒读越 scope），读 canonical 正文，
在内存里用 device.toml 的 [paths] 展开符号根，返回正文。不写第二份、不改 shared。"""
from pathlib import Path
from hub.vault import load_device
from hub.memview import collect_view_entries
from hub.frontmatter import load_memory
from hub.links import resolve_symbols

class MemoryNotInView(RuntimeError):
    pass

def read_memory(vault_root: Path, host: str, tool: str, name: str) -> str:
    dev = load_device(vault_root, host)
    entries = {e.name: e for e in collect_view_entries(vault_root, dev, tool)}
    if name not in entries:
        raise MemoryNotInView(f"记忆 {name!r} 不在本机 {tool} 视图里（不存在或越 scope），拒读。")
    m = load_memory(entries[name].source)
    body, _missing = resolve_symbols(m.body, dev.paths)
    return body
