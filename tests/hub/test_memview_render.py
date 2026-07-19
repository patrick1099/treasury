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
