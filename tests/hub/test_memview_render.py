from pathlib import Path
from hub.memview import MemoryViewEntry, render_view_file, render_codex_block

def _e(name, scope):
    return MemoryViewEntry(name=name, description=f"{name} desc", scope=scope,
                           source=Path("C:/hub-vault/shared/memory") / f"{name}.md")

def test_view_file_has_absolute_angle_bracket_links(tmp_path):
    out = render_view_file([_e("a", ["global"])], "claude")
    assert "- [a](<C:/hub-vault/shared/memory/a.md>)" in out
    assert "自动生成" in out

def test_view_file_uses_forward_slashes(tmp_path):
    out = render_view_file([_e("a", ["global"])], "codex")
    assert "\\" not in out.split("](<")[1].split(">)")[0]   # 链接段无反斜杠

def test_view_file_empty_has_placeholder():
    out = render_view_file([], "opencode")
    assert "无匹配共享记忆" in out

def test_codex_block_is_compact_no_paths():
    out = render_codex_block([_e("a", ["project:xinao"])])
    assert "`a`" in out and "a desc" in out and "project:xinao" in out
    assert "shared/memory" not in out                    # 不含绝对/相对源路径
    assert "$hub-memory" in out                            # 指到 skill 读正文

def test_codex_block_empty_has_placeholder():
    assert "无匹配共享记忆" in render_codex_block([])

def test_view_file_embeds_shared_hash():
    from hub.memview import render_view_file
    out = render_view_file([_e("a", ["global"])], "claude", shared_hash="deadbeef")
    assert "<!-- shared_hash: deadbeef -->" in out

def _mem(name, description="d", body="body", scope=("global",)):
    from hub.model import Memory
    return Memory(name=name, description=description, type="reference",
                  scope=list(scope), portable=True, sensitive=False, body=body)

def test_shared_hash_reflects_description():
    # named-risk：description 进视图索引，只改它也必须翻转哈希（否则 status --check 误判 fresh）
    from hub.memview import shared_hash
    assert shared_hash([_mem("x", description="alpha")]) != \
           shared_hash([_mem("x", description="beta")])

def test_shared_hash_is_order_independent():
    # 内部按 name 排序 → 与输入列表顺序无关，跨机/跨扫描顺序稳定
    from hub.memview import shared_hash
    a, b = _mem("a"), _mem("b")
    assert shared_hash([a, b]) == shared_hash([b, a])
