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
