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
