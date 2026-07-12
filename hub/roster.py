"""跨设备数据的人工闸门。

金库顶层按归属分文件夹(见 hub.vault)。`shared/` 里的东西所有设备无条件拿;
某台设备文件夹里的东西是它的**私产**——别的设备**不会自动拿到**,要先过目再拍板:

- accept  只给本机(记进 `<host>/merged.txt`)
- promote 提进 `shared/`,从此所有设备都拿(一次决定,免得每台机各审一遍)
- reject  不要,记进 `<host>/rejected.txt`,以后不再打扰

名单是纯文本,一行一个 `<来源>/<名字>`。MVP 只管 memory;skills/plugins/chats 同理扩展。
"""
from pathlib import Path
from hub.model import Memory, SHARED

def _list_path(vault_root: Path, host: str, kind: str) -> Path:
    return vault_root / host / f"{kind}.txt"

def _read_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return out

_HEADERS = {
    "merged": "# 本机已接受的外来数据(来自别的设备)。一行一个 <来源>/<名字>。\n"
              "# 这些会随 pull 落地到本机工具;删掉某行即撤销接受。\n\n",
    "rejected": "# 本机已拒绝的外来数据。列在这里的不再进待审、不再打扰。\n"
                "# `hub review --all` 会忽略本名单,把它们重新过一遍。\n\n",
}

def _save(vault_root: Path, host: str, kind: str, entries: set[str]) -> None:
    p = _list_path(vault_root, host, kind)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = _HEADERS[kind] + "\n".join(sorted(entries)) + ("\n" if entries else "")
    p.write_text(body, encoding="utf-8", newline="\n")

def entry_of(m: Memory) -> str:
    """名单里的唯一标识:<来源>/<名字>。"""
    return f"{m.origin}/{m.name}"

def split_entry(entry: str) -> tuple[str, str]:
    origin, _, name = entry.partition("/")
    return origin, name

def load_merged(vault_root: Path, host: str) -> set[str]:
    return _read_list(_list_path(vault_root, host, "merged"))

def load_rejected(vault_root: Path, host: str) -> set[str]:
    return _read_list(_list_path(vault_root, host, "rejected"))

def is_native(m: Memory, host: str) -> bool:
    """本机天然拥有:公共池的,或本机自产的。这类不过闸门。"""
    return m.origin in (SHARED, host)

def visible(memories: list[Memory], host: str, merged: set[str]) -> list[Memory]:
    """本机该落地的 = 天然拥有的 + 已接受的外来数据。"""
    return [m for m in memories if is_native(m, host) or entry_of(m) in merged]

def pending(memories: list[Memory], host: str, merged: set[str],
            rejected: set[str], include_rejected: bool = False) -> list[Memory]:
    """待审 = 外来的,且既没接受也没拒绝。include_rejected 时把拒绝过的也重新过一遍。"""
    out = []
    for m in memories:
        if is_native(m, host):
            continue
        e = entry_of(m)
        if e in merged:
            continue
        if e in rejected and not include_rejected:
            continue
        out.append(m)
    return out

def accept(vault_root: Path, host: str, entries: list[str]) -> None:
    """接受:只落地到本机。同时从拒绝名单撤出——改主意是允许的。"""
    _save(vault_root, host, "merged", load_merged(vault_root, host) | set(entries))
    _save(vault_root, host, "rejected", load_rejected(vault_root, host) - set(entries))

def reject(vault_root: Path, host: str, entries: list[str]) -> None:
    _save(vault_root, host, "rejected", load_rejected(vault_root, host) | set(entries))
    _save(vault_root, host, "merged", load_merged(vault_root, host) - set(entries))

def promote(vault_root: Path, entries: list[str]) -> list[str]:
    """提进公共池:把文件从 <来源>/memory/ 移进 shared/memory/。

    公共池已有同名 → 跳过不覆盖。同名可能是两台机器各写各的,该由人先看过,
    不能默默顶掉一份。
    """
    shared_mem = vault_root / SHARED / "memory"
    shared_mem.mkdir(parents=True, exist_ok=True)
    moved = []
    for e in entries:
        origin, name = split_entry(e)
        src = vault_root / origin / "memory" / f"{name}.md"
        dst = shared_mem / f"{name}.md"
        if not src.exists() or dst.exists():
            continue
        src.replace(dst)
        moved.append(e)
    return moved
