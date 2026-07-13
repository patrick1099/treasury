"""硬闸:提取器永不读取的路径。

用户的全局约定是"私密文件统一放 ~/.claude/secrets/"。这条约定本身就是最好的
硬闸——只要提取器永不碰那个目录,而记忆/skill 里只留指针,密钥就物理上出不去。

secrets/ 连加密了也不进金库:它是**全部密钥的单一集合**,整包搬到 NAS 等于把所有
鸡蛋装进一个篮子,主密钥一泄就是一次性全崩。它换机时另有通道(ai-cli-migrate 点对点搬)。
"""
from pathlib import Path


class SecretPathError(RuntimeError):
    pass


DENIED_NAMES = frozenset({"secrets", "auth.json", ".env"})


def is_denied(path: Path) -> bool:
    """路径自身或它的任一祖先命中黑名单。"""
    p = Path(path)
    return any(part.lower() in DENIED_NAMES for part in p.parts)


def check_source(path: Path) -> None:
    if is_denied(path):
        raise SecretPathError(
            f"硬闸:拒绝读取 {path} —— 命中密钥黑名单 {sorted(DENIED_NAMES)}。"
            f"私密内容留在 ~/.claude/secrets/,记忆/skill 里只写指针。")
