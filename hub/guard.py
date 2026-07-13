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


def has_denied_component(path) -> bool:
    """路径的字面 parts 里有没有任一组件命中黑名单——只字符串匹配,不 resolve()。

    单独拆出来是因为它对**归档内部的相对路径**才是唯一正确的检查方式:tar 成员名
    (如 ``secrets/token.md``)不是文件系统路径,归档里也没有对应的真实 inode 可解析。
    对它调用 ``Path.resolve()``:
    - 没有意义——它会按**当前工作目录**把这个相对名拼成一个文件系统路径再解析,
      但那个路径和归档成员实际会解到 dest 下的哪里毫无关系;
    - 而且依附 cwd——如果进程恰好在名为 ``secrets`` 的目录里运行,every 归档
      成员名都会被 resolve() 出一个带 ``secrets`` 分量的绝对路径,导致整份快照
      被硬闸清空,而清空是静默的(tar 里没内容看着也正常),不会报错提醒。

    ``is_denied()`` 面对的是真实文件系统路径,resolve() 半部分挡符号链接绕闸
    是必要的;这个函数只服务于"字面路径就是全部信息"的场景(如 tar 成员名)。
    """
    p = Path(path)
    return any(part.lower() in DENIED_NAMES for part in p.parts)


def is_denied(path: Path) -> bool:
    """路径自身或它的任一祖先命中黑名单。

    同时按**字面路径**与**解析后的真实路径**匹配组件(两者任一命中即拒绝)——
    单纯 resolve() 并不严格更强,所以两边都要查:

    - 字面 parts(见 has_denied_component):挡得住 ``..`` 穿越等仍把 ``secrets``
      写在字符串里的路径。
    - resolve(strict=False) 后的 parts:挡得住符号链接指向 secrets/ 之类目标、
      以及 cwd 已经在 secrets/ 内时传入裸相对文件名(字面串里根本没有 secrets)
      这两种字面匹配看不出来的情况。``shutil.copytree`` 默认解引用符号链接,
      所以这里必须解析,否则符号链接能让真实字节绕过硬闸落进金库。
    - resolve() 因符号链接环等原因抛 OSError 时,闭门造车地当作拒绝——判断不了
      一个路径真实指向哪里,正确答案是拒绝读取,不是放行。
    """
    p = Path(path)
    if has_denied_component(p):
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
