"""阶段 B 3.1 数据面:group / archived / index 三个生命周期字段升成 Memory 一等字段。

frontmatter 强校验 + dump 缺省零输出 + memview 原样带过。见
docs/plans/2026-08-31-hub-memory-layering.md §3.1。
"""
import pytest
from pathlib import Path

from hub.frontmatter import load_memory, dump_memory, FrontmatterError, _require_group
from hub.memview import entries_for_tool
from hub.model import Memory, DeviceProfile
from hub.scope import parse_scope


_LIFECYCLE = """---
name: x
description: 摘要
metadata:
  type: project
  scope: [global]
  group: 固件约束（改协议/参数/编译前查）
  archived: 2026-08-31
  index: expanded
---
正文
"""


def _write(tmp_path, text):
    p = tmp_path / "x.md"
    p.write_text(text, encoding="utf-8")
    return p


# ---- 三个键的 round-trip ------------------------------------------------

def test_lifecycle_fields_roundtrip(tmp_path):
    p = _write(tmp_path, _LIFECYCLE)
    m = load_memory(p)
    assert m.group == "固件约束（改协议/参数/编译前查）"
    assert m.archived == "2026-08-31"
    assert m.index == "expanded"
    m2 = load_memory(_write(tmp_path, dump_memory(m)))
    assert m2.group == m.group
    assert m2.archived == m.archived
    assert m2.index == m.index


# ---- 缺省零输出:没写这三个键的记忆,dump 结果逐字节不变 -------------------

_LEGACY = """---
name: x
description: 摘要
metadata:
  type: project
  scope: [global]
  portable: true
  sensitive: false
---
正文
"""


def test_dump_omits_absent_lifecycle_keys(tmp_path):
    p = _write(tmp_path, _LEGACY)
    m = load_memory(p)
    assert m.group is None and m.archived is None and m.index is None
    out = dump_memory(m)
    assert "group" not in out
    assert "archived" not in out
    assert "index" not in out
    assert out == _LEGACY


# ---- 六个非法输入,逐个断言炸 FrontmatterError ----------------------------

def _with_meta(extra_meta_line: str) -> str:
    return ("---\nname: x\ndescription: d\nmetadata:\n  type: project\n"
            "  scope: [global]\n" + extra_meta_line + "\n---\n正文\n")


@pytest.mark.parametrize("line", [
    '  group: ""',
    '  archived: 2026/08/31',
    '  archived: true',
    '  archived: 20260831',
    '  index: true',
    '  index: compact',
])
def test_invalid_lifecycle_values_raise(tmp_path, line):
    p = _write(tmp_path, _with_meta(line))
    with pytest.raises(FrontmatterError) as e:
        load_memory(p)
    assert str(p) in str(e.value)


def test_group_with_newline_raises():
    """真实换行进不了单行解析器的值,这条防线是给未来解析器变动兜底的——直接打校验函数。"""
    with pytest.raises(FrontmatterError):
        _require_group({"group": "a\nb"}, "group", Path("x.md"))


# ---- 三个键不落 extra_metadata ------------------------------------------

def test_lifecycle_keys_not_in_extra_metadata(tmp_path):
    p = _write(tmp_path, _LIFECYCLE)
    m = load_memory(p)
    assert "group" not in m.extra_metadata
    assert "archived" not in m.extra_metadata
    assert "index" not in m.extra_metadata
    assert m.extra_metadata == {}


# ---- memview 原样带过 ---------------------------------------------------

def test_entries_for_tool_carries_lifecycle_fields():
    m = Memory(name="x", description="d", type="reference", scope=["global"],
               portable=True, sensitive=False, body="\n",
               group="固件约束", archived="2026-08-31", index="expanded")
    dev = DeviceProfile(host="box1", classes=["work"], projects=[], paths={})
    parsed = {"x": parse_scope(["global"])}
    entries = entries_for_tool([m], parsed, Path("C:/vault"), dev, "claude")
    assert len(entries) == 1
    e = entries[0]
    assert e.group == "固件约束"
    assert e.archived == "2026-08-31"
    assert e.index == "expanded"
