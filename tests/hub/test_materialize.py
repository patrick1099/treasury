from hub.materialize import render_agents_md, render_claude_md, select_for_target, render_memory_bundle, codex_project_inner
from hub.managed_block import extract_block
from hub.model import Memory, Target

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


def _mem(name, scope, body="正文", sensitive=False):
    return Memory(name=name, description=name, type="project",
                  scope=scope, portable=True, sensitive=sensitive, body=body)

def test_select_filters_scope_and_sensitive():
    mems = [_mem("g", ["global"]),
            _mem("claude_only", ["tool:claude"]),
            _mem("secret", ["global"], sensitive=True)]
    for_codex = select_for_target(mems, Target(frozenset(), None, "codex"))
    names = {m.name for m in for_codex}
    assert names == {"g"}  # claude_only 被 AND 排除；secret 被敏感排除

def test_bundle_resolves_symbols_and_marks_missing():
    mems = [_mem("ok", ["global"], body="看 $VAULT/a\n"),
            _mem("bad", ["global"], body="看 $NOPE/b\n")]
    out = render_memory_bundle(mems, {"VAULT": "Z:/v"})
    assert "Z:/v/a" in out
    assert "skipped" in out and "bad" in out  # 未定义根 -> 跳过并标注

def test_codex_project_inner_wraps():
    inner = codex_project_inner([_mem("p", ["project:xinao"], body="坑\n")], {})
    assert "坑" in inner
