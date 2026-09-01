"""render_view_file / render_codex_block 的产物格式契约 + classify_entries 的分层判据。

阶段 B(plan §3.2/§3.4)把平铺一条一行改成分层折叠:展开段逐条 name+description,
折叠段/归档段只列名、同组中点连成一行。判据是唯一出口 classify_entries,这里是钉死
格式与判据的测试——不是让实现怎么改,而是下次改规则时先红在这里。
"""
from pathlib import Path

from hub.memview import (MemoryViewEntry, render_view_file, render_codex_block,
                         EMPTY_VIEW_NOTE, shared_hash, classify_entries)
from hub.model import Memory


def _entry(name="a_memory", desc="一句话说明", scope=("global",), type="",
           group=None, archived=None, index=None):
    return MemoryViewEntry(name=name, description=desc, type=type, scope=list(scope),
                           group=group, archived=archived, index=index,
                           source=Path("C:/some vault/shared/memory") / f"{name}.md")


def _mem(name="x", type="reference", description="d", body="b", scope=("global",),
         group=None, archived=None, index=None):
    return Memory(name=name, description=description, type=type, scope=list(scope),
                  portable=True, sensitive=False, body=body,
                  group=group, archived=archived, index=index)


# ---- 展开段:逐条一行,定界可被下游稳定解析 --------------------------------

def test_expanded_entry_one_line_per_entry():
    out = render_view_file([_entry("x", "说明 X", type="feedback"),
                            _entry("y", "说明 Y", type="feedback")], "claude", "h")
    rows = [l for l in out.splitlines() if l.startswith("- ")]
    assert rows == ["- x — 说明 X", "- y — 说明 Y"]


def test_no_absolute_path_leaks():
    """路径没有消费者（memread 走内存里的 source），却占近四成体积。"""
    out = render_view_file([_entry()], "claude", "h")
    assert "](<" not in out
    assert "some vault" not in out


def test_no_scope_line():
    """视图本身就是 scope 过滤后的结果，再印一遍是同义反复。"""
    out = render_view_file([_entry(scope=("class:work", "tool:claude"))], "claude", "h")
    assert "scope:" not in out
    assert "class:work" not in out


def test_expanded_name_is_parseable_by_delimiter():
    """下游按 `- ` 到首个 ` — ` 取名字；description 里再出现破折号也不能干扰。"""
    out = render_view_file([_entry("n1", "前段 — 后段", type="feedback")], "claude", "h")
    row = [l for l in out.splitlines() if l.startswith("- ")][0]
    assert row[2:].split(" — ", 1)[0] == "n1"


def test_header_keeps_shared_hash_and_tool():
    out = render_view_file([_entry()], "codex", "deadbeef00")
    assert "shared_hash: deadbeef00" in out
    assert "# 共享记忆索引 — codex" in out


def test_empty_keeps_placeholder():
    out = render_view_file([], "dsh", "h")
    assert EMPTY_VIEW_NOTE in out


# ---- 分层判据:四类条目各自落到哪一段 --------------------------------------

def test_four_categories_land_in_right_sections():
    fb = _entry("fb_1", "约束A", type="feedback")
    idx = _entry("idx_1", "项目约束", type="project", index="expanded")
    grp = _entry("grp_1", "说明", type="reference", group="固件")
    arc = _entry("arc_1", "旧东西", type="project", archived="2026-08-01")
    out = render_view_file([fb, idx, grp, arc], "claude", "h")
    assert "## 工作约束（2）" in out              # feedback + 显式 index
    assert "- fb_1 — 约束A" in out
    assert "- idx_1 — 项目约束" in out
    assert "## 其余（1）" in out
    assert "- 固件(1): grp_1" in out             # 折叠段只列名
    assert "## 已归档（1）" in out
    assert "- arc_1" in out                      # 归档段只列名


def test_archived_beats_index_and_type():
    """archived 优先级最高：同时有 index=expanded、type=feedback 也进归档段。"""
    arc = _entry("arc", "x", type="feedback", index="expanded", archived="2026-01-01")
    cls = classify_entries([arc])
    assert cls.archived == [arc]
    assert cls.expanded == [] and cls.folded == {}
    out = render_view_file([arc], "claude", "h")
    assert "## 工作约束" not in out
    assert "## 已归档（1）" in out


def test_index_override_beats_type():
    """index == expanded 优先于 type：project 也能被显式提到展开层。"""
    cls = classify_entries([_entry("p", "d", type="project", index="expanded")])
    assert [e.name for e in cls.expanded] == ["p"]
    assert cls.folded == {} and cls.archived == []


def test_empty_section_omitted():
    """空段整段不输出（连标题一起省掉），不留空标题。"""
    out = render_view_file([_entry("a", "d", type="reference", group="组X")], "claude", "h")
    assert "## 工作约束" not in out
    assert "## 已归档" not in out
    assert "## 其余（1）" in out


def test_default_group_last():
    """缺省组「未分组」排在所有具名组之后；具名组按组名升序。"""
    entries = [
        _entry("z", "z", type="reference", group="B组"),
        _entry("a", "a", type="reference"),
        _entry("m", "m", type="reference", group="A组"),
    ]
    out = render_view_file(entries, "claude", "h")
    lines = [l for l in out.splitlines() if l.startswith("- ")]
    assert lines[0].startswith("- A组")
    assert lines[1].startswith("- B组")
    assert lines[2].startswith("- 未分组")
    assert "## 其余（3）" in out


# ---- codex 受管块:同一分层结构 + 嵌 shared_hash ----------------------------

def test_codex_block_same_layout_and_embeds_hash():
    out = render_codex_block([_entry("fb1", "约束1", type="feedback"),
                              _entry("r1", "说明", type="reference")], "v3:abc")
    assert "shared_hash: v3:abc" in out
    assert "## 工作约束（1）" in out
    assert "- fb1 — 约束1" in out
    assert "## 其余（1）" in out
    assert "- 未分组(1): r1" in out
    assert "正文请用" in out
    assert "scope:" not in out                     # 与阶段 A 瘦身对齐
    assert "`fb1`" not in out                      # 不再反引号包名


# ---- shared_hash:v3 前缀 + 所有渲染字段进哈希 ------------------------------

def test_hash_has_version_prefix():
    assert shared_hash([_mem()]).startswith("v3:")


def test_hash_changes_when_group_changes():
    assert shared_hash([_mem(group=None)]) != shared_hash([_mem(group="固件")])


def test_hash_changes_when_archived_changes():
    assert shared_hash([_mem(archived=None)]) != shared_hash([_mem(archived="2026-08-31")])


def test_hash_changes_when_index_changes():
    assert shared_hash([_mem(index=None)]) != shared_hash([_mem(index="expanded")])


def test_hash_changes_when_type_changes():
    assert shared_hash([_mem(type="reference")]) != shared_hash([_mem(type="feedback")])


def test_hash_changes_on_content_and_scope():
    assert shared_hash([_mem(description="a")]) != shared_hash([_mem(description="b")])
    assert shared_hash([_mem(body="a")]) != shared_hash([_mem(body="b")])
    assert shared_hash([_mem(scope=["global"])]) != shared_hash([_mem(scope=["class:work"])])
