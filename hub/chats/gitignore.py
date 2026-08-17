"""原始对话库不进 git 的第一道保险：金库根 .gitignore 的幂等写入。

为什么有这道 .gitignore 还要在 backend.py 加一道 ChatsTracked 代码闸：
.gitignore 只是"建议"。它哪天被改坏、或某个文件早被 git add -f 强行加进索引，
失败方向就是 800 MB 明文对话静默推上 GitHub —— 而 git 的每个历史版本永久留存，
事后删文件不等于删历史。所以这道规则写得下、写得好，只是"拦住"的第一层；
backend.py 那道闸是"拦不住时"的第二层、最后一层。
"""
from pathlib import Path

from hub.writer import Writer

_BLOCK = (
    "# 原始对话库：明文，本轮不进 git，且没有任何离机备份。\n"
    "# 解禁条件=静态加密+回溯脱敏；届时同步实现另议，不是\"删掉这行\"就完事。\n"
    "*/*/chats/\n"
)


def ensure_chats_ignored(vault_root: Path, w: Writer) -> bool:
    """幂等追加原始对话库的 gitignore 块；返回是否真的写入了。

    vault_root 是金库根。已有这段就一个字节不动（幂等，连跑两次只写一次）；
    金库根已有别的 .gitignore 内容时只追加、不覆盖人家的。走 Writer 唯一写入口，
    dry-run 下零写入。
    """
    gitignore = Path(vault_root) / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if _BLOCK in existing:
        return False
    text = existing
    if text and not text.endswith("\n"):
        text += "\n"
    if text:
        text += "\n"
    w.write_text(gitignore, text + _BLOCK)
    return True