"""T7:源注册表 + device.toml 的 chats 字段。

注册表本身没什么逻辑,值得测的只有两件事:五个源一个不少地注册上了(漏一个的表现是
"那个平台的对话从此不收",而且悄无声息);以及不认识的名字必须**抛**——静默返回空在
这一层格外危险,它会被 append-only 状态机读成"这个源一个会话都没有",进而把金库里
该源已有的证据全标成 source_gone。
"""
import pytest

from hub.chats.sources import SOURCES, UnknownSource, discover
from hub.model import ToolSources
from hub.vault import _tool_sources


def test_all_five_sources_registered():
    assert sorted(SOURCES) == [
        "claude", "codex", "copilot-cli", "copilot-vscode", "opencode",
    ]


def test_each_module_exposes_the_contract():
    for name, mod in SOURCES.items():
        assert mod.NAME == name
        assert callable(mod.discover)


def test_unknown_source_raises_and_names_the_known_ones():
    with pytest.raises(UnknownSource) as e:
        discover("copilot", "somewhere")        # 差一点点的名字最容易犯
    assert "copilot-cli" in str(e.value)


def test_tool_sources_reads_chats_from_device_toml():
    src = _tool_sources({"chats": "C:/Users/x/.claude", "skills": "C:/Users/x/s"})
    assert src.chats == "C:/Users/x/.claude"
    assert src.skills == "C:/Users/x/s"


def test_chats_absent_is_none_not_error():
    """没配 chats 是合法的(本机没装那个工具),不是错误。"""
    assert _tool_sources({}).chats is None
    assert ToolSources().chats is None
