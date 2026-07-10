from hub.materialize import render_agents_md, render_claude_md
from hub.managed_block import extract_block

def test_agents_md_embeds_rules_and_preserves_outside():
    out = render_agents_md("# 我的手写抬头\n", [("a", "规则A\n"), ("b", "规则B\n")])
    assert "# 我的手写抬头" in out
    inner = extract_block(out)
    assert "规则A" in inner and "规则B" in inner

def test_agents_md_appends_project_memory_block():
    out = render_agents_md("", [("a", "规则A\n")], project_memory_inner="## 项目记忆\n- 坑X\n")
    inner = extract_block(out)
    assert "规则A" in inner and "项目记忆" in inner and "坑X" in inner

def test_agents_md_idempotent():
    once = render_agents_md("抬头\n", [("a", "规则A\n")])
    twice = render_agents_md(once, [("a", "规则A改\n")])
    assert twice.count("hub:begin") == 1
    assert "规则A改" in extract_block(twice)
    assert "抬头" in twice

def test_claude_md_imports():
    out = render_claude_md("手写\n", "hub/memory-index.md")
    inner = extract_block(out)
    assert "@AGENTS.md" in inner
    assert "@hub/memory-index.md" in inner
    assert "手写" in out
