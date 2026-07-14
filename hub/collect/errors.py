"""提取器的配置错误。

`MissingSourceError` 存在的理由是**分开两个语义相反的状态**,它们过去共用一条代码路径:

- **没配那个源**(`device.toml` 里根本没有那个键)= 工具没装 = 正常。什么都不做。
- **配了、但那个路径不在** = **配置坏了**。绝不是"用户把本机的记忆/skill 全删了"。

collect 对记忆做的是**镜像**(源里没有的 → 从金库删掉)。把第二种状态当成"源是空的",
镜像就会把金库里**每一条**记忆都算成"源里已经没了"并删掉——而金库是它们的唯一备份。
2026-07-13 的评审复现过:`scaffold --force` 把 `<占位>` 模板写回 `device.toml`,下一次
`collect --yes` 就把整个备份清空,还返回 0。

所以配置坏了就**炸**,点名那个路径,让人去修 device.toml。宁可响,不可错。
"""


class MissingSourceError(RuntimeError):
    pass


def require_source(path, what: str, kind: str = "dir"):
    """配了就必须在,而且必须是对的类型。返回 path 本身,方便链式使用。

    类型也要查:一个本该是目录的源如果是个文件,`glob("*.md")` 只会安静地返回空——
    又回到"源里零条记忆"那条毁灭路径上,而且这次连报错都没有。
    """
    from pathlib import Path
    p = Path(path)
    ok = p.is_dir() if kind == "dir" else p.is_file()
    if not ok:
        noun = "目录" if kind == "dir" else "文件"
        why = "这个路径不存在" if not p.exists() else f"这个路径存在,但它不是一个{noun}"
        raise MissingSourceError(
            f"device.toml 配了 {what} = {p},但{why}。\n"
            f"这是**配置错误**,不是「本机没有这些东西」——提取器不敢照着一个读不到的源\n"
            f"去镜像(那等于把金库里对应的备份当成「用户已经删了」清掉)。\n"
            f"要么把路径改对,要么把这一项从 device.toml 里**删掉**(缺项 = 本机没那个源,是合法的)。")
    return p
