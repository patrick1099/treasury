"""各平台的源提取器:只负责**发现** artifact,不负责落盘(落盘归 collect.py)。

每个源模块导出 `NAME` 和 `discover(root) -> list[Artifact]`。

**缺源规则(spec §6.3)**:`discover` 拿到的 `root` 是**已配置**的路径,不存在就**抛**
(各源模块内部用 `hub.collect.errors.require_source`),不许返回 `[]`——返回空会被
append-only 状态机解释成"这个源的全部会话都消失了",把整个源标成 `source_gone`。
"未配置"这个合法情况由调用方**根本不调用**来表达,不由 `discover` 的返回值表达。

`copilot-cli` 与 `copilot-vscode` 是**两个源**,不是一个:两套独立存储、两套格式、
两个产品形态,合并只会制造一个不存在的东西。
"""
from hub.chats.sources import claude, codex, copilot_cli, copilot_vscode, opencode

SOURCES = {
    m.NAME: m for m in (claude, codex, opencode, copilot_cli, copilot_vscode)
}


class UnknownSource(KeyError):
    pass


def discover(name: str, root):
    """按名字调对应源的 discover。名字不认识就抛,别静默返回空。

    静默返回空在这一层格外危险:它会被状态机读成"这个源一个会话都没有",
    进而把金库里该源已有的证据全标成 source_gone。
    """
    try:
        mod = SOURCES[name]
    except KeyError:
        raise UnknownSource(
            f"不认识的对话源 {name!r};已知的是 {sorted(SOURCES)}") from None
    return mod.discover(root)
