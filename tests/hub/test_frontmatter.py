import pytest
from pathlib import Path
from hub.frontmatter import parse_frontmatter, load_memory, dump_memory, FrontmatterError
from hub.model import Memory

SAMPLE = """---
name: project_encoding_workflow
description: CP936 源文件处理
metadata:
  type: project
  scope: [global, tool:claude]
  portable: false
  sensitive: false
---
正文第一行
第二行
"""

def test_parse_nested_and_inline_list():
    meta, body = parse_frontmatter(SAMPLE)
    assert meta["name"] == "project_encoding_workflow"
    assert meta["metadata"]["scope"] == ["global", "tool:claude"]
    assert meta["metadata"]["portable"] is False
    assert body.startswith("正文第一行")

def test_load_memory_roundtrip(tmp_path):
    p = tmp_path / "m.md"
    p.write_text(SAMPLE, encoding="utf-8")
    m = load_memory(p)
    assert isinstance(m, Memory)
    assert m.scope == ["global", "tool:claude"]
    assert m.sensitive is False
    assert m.path == p
    # dump 后再 parse 应稳定
    meta2, _ = parse_frontmatter(dump_memory(m))
    assert meta2["metadata"]["scope"] == ["global", "tool:claude"]

def test_reject_out_of_subset():
    bad = "---\nname: x\ntags:\n  - a:\n      b: 1\n---\nbody\n"  # 二层嵌套列表，越界
    with pytest.raises(FrontmatterError):
        parse_frontmatter(bad)


_BLOCK = """---
name: x
description: 摘要
metadata:
  type: project
  scope:
    - global
  sensitive: false
---
正文
"""

def test_block_list_is_parsed(tmp_path):
    meta, body = parse_frontmatter(_BLOCK)
    assert meta["metadata"]["scope"] == ["global"]
    assert body.strip() == "正文"

def test_block_list_with_multiple_items():
    text = _BLOCK.replace("    - global\n", "    - tool:claude\n    - device:work\n")
    meta, _ = parse_frontmatter(text)
    assert meta["metadata"]["scope"] == ["tool:claude", "device:work"]

def test_top_level_block_list():
    text = "---\nname: x\ndescription: d\ntags:\n  - a\n  - b\n---\n正文\n"
    meta, _ = parse_frontmatter(text)
    assert meta["tags"] == ["a", "b"]

def test_load_memory_roundtrips_block_list(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(_BLOCK, encoding="utf-8")
    m = load_memory(p)
    assert m.scope == ["global"] and m.type == "project"

def test_genuinely_broken_frontmatter_still_raises():
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nname x\n---\n正文\n")     # 没有冒号
    with pytest.raises(FrontmatterError):
        parse_frontmatter("没有 frontmatter\n")

def test_load_memory_broken_frontmatter_includes_path(tmp_path):
    """Malformed frontmatter must include the file path in the error message."""
    p = tmp_path / "broken.md"
    p.write_text("---\nname x\n---\nbody\n", encoding="utf-8")  # missing colon after 'name'
    with pytest.raises(FrontmatterError) as exc_info:
        load_memory(p)
    # The error message must contain the file path
    assert str(p) in str(exc_info.value)

def test_load_memory_non_utf8_includes_path(tmp_path):
    """Non-UTF-8 file bytes must raise FrontmatterError (not bare UnicodeDecodeError) with path in message."""
    p = tmp_path / "non_utf8.md"
    # Write invalid UTF-8 bytes directly
    p.write_bytes(b"\xff\xfe---\nname: x\n---\nbody\n")
    with pytest.raises(FrontmatterError) as exc_info:
        load_memory(p)
    # The error message must contain the file path
    assert str(p) in str(exc_info.value)


# ---- 布尔位必须是真布尔:宁可响,不可错 ------------------------------------

def _mem(sensitive: str = "false", portable: str = "true") -> str:
    return ("---\nname: x\ndescription: d\nmetadata:\n  type: project\n"
            f"  scope: [global]\n  portable: {portable}\n  sensitive: {sensitive}\n---\n正文\n")

def test_sensitive_with_trailing_comment_raises_not_inverts(tmp_path):
    """`sensitive: false  # 不入库` 现在解析成字符串,bool() 判 True——本意 false 的
    记忆被当 sensitive 静默丢弃。必须炸,并点名文件/字段/值。"""
    p = tmp_path / "x.md"
    p.write_text(_mem(sensitive="false  # 不入库"), encoding="utf-8")
    with pytest.raises(FrontmatterError) as e:
        load_memory(p)
    msg = str(e.value)
    assert str(p) in msg
    assert "sensitive" in msg
    assert "不入库" in msg          # 点名那个冒犯的值

def test_portable_non_bool_raises(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(_mem(portable="yes"), encoding="utf-8")
    with pytest.raises(FrontmatterError) as e:
        load_memory(p)
    assert "portable" in str(e.value) and "yes" in str(e.value)

def test_quoted_bool_raises(tmp_path):
    """引号剥掉之后是字符串 'false',不是布尔。标准 YAML 也这么读。照样炸。"""
    p = tmp_path / "x.md"
    p.write_text(_mem(sensitive='"false"'), encoding="utf-8")
    with pytest.raises(FrontmatterError):
        load_memory(p)

def test_real_bools_still_load(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(_mem(sensitive="false", portable="true"), encoding="utf-8")
    m = load_memory(p)
    assert m.sensitive is False and m.portable is True

def test_absent_bools_fall_back_to_defaults(tmp_path):
    """键缺失 = 用默认值(portable=True / sensitive=False),不是错误。"""
    p = tmp_path / "x.md"
    p.write_text("---\nname: x\ndescription: d\nmetadata:\n  type: project\n"
                 "  scope: [global]\n---\n正文\n", encoding="utf-8")
    m = load_memory(p)
    assert m.portable is True and m.sensitive is False


# ---- 引号:剥一层配对的外层引号 -------------------------------------------

def test_quoted_description_is_unquoted():
    text = ('---\nname: x\ndescription: "带引号的摘要"\nmetadata:\n  type: project\n'
            "  scope: [global]\n---\n正文\n")
    meta, _ = parse_frontmatter(text)
    assert meta["description"] == "带引号的摘要"

def test_inner_quotes_survive_intact():
    """真实记忆里就有这一条:外层双引号,内层单引号。内层必须原样活下来。"""
    text = ('---\nname: x\ndescription: "别把设计重心压在\'我认为重要的风险\'上"\n'
            "metadata:\n  type: project\n  scope: [global]\n---\n正文\n")
    meta, _ = parse_frontmatter(text)
    assert meta["description"] == "别把设计重心压在'我认为重要的风险'上"

def test_unmatched_quote_is_left_alone():
    text = ("---\nname: x\ndescription: 他说'这样'不行\nmetadata:\n  type: project\n"
            "  scope: [global]\n---\n正文\n")
    meta, _ = parse_frontmatter(text)
    assert meta["description"] == "他说'这样'不行"

def test_quoted_inline_list_items_are_unquoted():
    text = ('---\nname: x\ndescription: d\nmetadata:\n  type: project\n'
            '  scope: ["global"]\n---\n正文\n')
    meta, _ = parse_frontmatter(text)
    assert meta["metadata"]["scope"] == ["global"]

def test_quoted_block_list_items_are_unquoted():
    text = ('---\nname: x\ndescription: d\nmetadata:\n  type: project\n'
            '  scope:\n    - "tool:claude"\n    - \'device:work\'\n---\n正文\n')
    meta, _ = parse_frontmatter(text)
    assert meta["metadata"]["scope"] == ["tool:claude", "device:work"]

def test_quoted_name_yields_a_legal_filename(tmp_path):
    """name: "my-note" 过去会得到带引号的 name,拿去当文件名在 NTFS 上非法。"""
    p = tmp_path / "q.md"
    p.write_text('---\nname: "my-note"\ndescription: "d"\nmetadata:\n  type: project\n'
                 "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
                 encoding="utf-8")
    m = load_memory(p)
    assert m.name == "my-note" and m.description == "d"
