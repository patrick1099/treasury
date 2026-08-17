import tomllib
import pytest
from hub.tomlout import dump_toml, quote_key

def test_roundtrips_through_tomllib():
    out = dump_toml([
        ("claude.repos.cjt", {"remote": "https://github.com/x/cjt.git",
                              "sha": "abc123", "dirty": False}),
        ("claude.enabled", {"superpowers@claude-plugins-official": True,
                            "compact-plus@xu-local": False}),
    ])
    back = tomllib.loads(out)
    assert back["claude"]["repos"]["cjt"]["dirty"] is False
    assert back["claude"]["enabled"]["superpowers@claude-plugins-official"] is True
    assert back["claude"]["enabled"]["compact-plus@xu-local"] is False

def test_keys_needing_quotes_are_quoted():
    out = dump_toml([("t", {"a@b": True})])
    assert '"a@b" = true' in out
    assert tomllib.loads(out)["t"]["a@b"] is True

def test_windows_paths_are_escaped():
    out = dump_toml([("t", {"path": "C:\\Users\\x\\.claude"})])
    assert tomllib.loads(out)["t"]["path"] == "C:\\Users\\x\\.claude"

def test_empty_table_still_emits_header():
    assert "[t]" in dump_toml([("t", {})])

def test_control_characters_roundtrip_through_real_parser():
    """字符串值里带换行/回车/制表符时,_val() 必须转义它们——否则原样吐进 TOML
    basic string,tomllib.loads() 会拒绝整份文件,不只是这一个字段。断言必须
    走真实解析器,而不是检查发出的文本本身。"""
    tricky = 'line1\nline2\r\nwith\ttab and "quote" and \\backslash'
    out = dump_toml([("t", {"note": tricky})])
    back = tomllib.loads(out)
    assert back["t"]["note"] == tricky

def test_unsupported_type_raises_naming_the_type():
    """_val() 遇到不认识的形状(如嵌套 dict/list)必须响亮地报错,而不是拿
    str()/repr() 糊成语法正确、语义错误的 TOML。错误要点名是哪个类型。"""
    with pytest.raises(ValueError, match="dict"):
        dump_toml([("hooks", {"PreToolUse": {"matcher": "*", "hooks": []}})])

def test_quote_key_reuses_private_logic():
    """quote_key 是 _key 的公开薄封装:裸键原样返回,含 / . 空格 中文的键
    加引号并转义。manifest 靠它做 artifact 表名,所以走真实解析器验证
    `artifact.<key>` 能原样读回,而不只是检查发出的文本。"""
    assert quote_key("plain") == "plain"
    quirky = 'sessions/工程 d.会话/a"b\\c.jsonl'
    out = dump_toml([("artifact." + quote_key(quirky), {"k": 1})])
    back = tomllib.loads(out)
    assert back["artifact"][quirky] == {"k": 1}