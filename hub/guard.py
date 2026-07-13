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
    """路径自身或它的任一祖先命中黑名单。

    同时按**字面路径**与**解析后的真实路径**匹配组件(两者任一命中即拒绝)——
    单纯 resolve() 并不严格更强,所以两边都要查:

    - 字面 parts:挡得住 ``..`` 穿越等仍把 ``secrets`` 写在字符串里的路径。
    - resolve(strict=False) 后的 parts:挡得住符号链接指向 secrets/ 之类目标、
      以及 cwd 已经在 secrets/ 内时传入裸相对文件名(字面串里根本没有 secrets)
      这两种字面匹配看不出来的情况。``shutil.copytree`` 默认解引用符号链接,
      所以这里必须解析,否则符号链接能让真实字节绕过硬闸落进金库。
    - resolve() 因符号链接环等原因抛 OSError 时,闭门造车地当作拒绝——判断不了
      一个路径真实指向哪里,正确答案是拒绝读取,不是放行。
    """
    p = Path(path)
    if any(part.lower() in DENIED_NAMES for part in p.parts):
        return True
    try:
        resolved = p.resolve(strict=False)
    except OSError:
        return True
    return any(part.lower() in DENIED_NAMES for part in resolved.parts)


def check_source(path: Path) -> None:
    if is_denied(path):
        raise SecretPathError(
            f"硬闸:拒绝读取 {path} —— 命中密钥黑名单 {sorted(DENIED_NAMES)}。"
            f"私密内容留在 ~/.claude/secrets/,记忆/skill 里只写指针。")
