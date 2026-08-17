"""原始对话库的路径边界。

与 vaultpaths.shared_skills_dir 同一个形状、同一个理由:容器本身要是经链接逃出了
金库,提取器就会往金库外写几百 MB 对话正文,而且状态还报正常。这里一次锁死。
"""
import os
from pathlib import Path

CHATS = "chats"


class ChatsPathEscape(RuntimeError):
    pass


def _seg(name: str, what: str) -> str:
    """host / tool 必须是**单个路径段**——挡住 host=".." 这类穿越。"""
    p = Path(name)
    if not name or len(p.parts) != 1 or name in (".", "..") or os.path.isabs(name):
        raise ChatsPathEscape(f"{what} 必须是单个路径段,收到 {name!r}")
    return name


def chats_dir(vault_root: Path, host: str, tool: str) -> Path:
    """返回 <vault>/<host>/<tool>/chats;经链接解析后逃出金库则抛。

    无条件比对(不加 lexists 守卫):chats 尚不存在但父目录是外链时,realpath 会解析
    到金库外——只有无条件比对才挡得住父目录逃逸。这条是 Plan 2 最终评审用一个跨任务
    不一致换来的教训,别加"目录还不存在就跳过检查"的豁免。
    """
    vault_root = Path(vault_root)
    host, tool = _seg(host, "host"), _seg(tool, "tool")
    container = vault_root / host / tool / CHATS
    expected = os.path.join(os.path.realpath(vault_root), host, tool, CHATS)
    if os.path.realpath(container) != expected:
        raise ChatsPathEscape(
            f"{host}/{tool}/chats 经链接逃出金库:{container} → {os.path.realpath(container)};"
            f"应在 {expected}。停下来让你处理,绝不往金库外写对话正文。")
    return container


def all_chats_dirs(vault_root: Path, host: str) -> list[Path]:
    """本机已存在的全部 chats 目录。给 scan_tree 的排除清单和 status 用。"""
    home = Path(vault_root) / host
    if not home.is_dir():
        return []
    return sorted(p for p in home.glob(f"*/{CHATS}") if p.is_dir())
