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

from pathlib import Path
from hub.materialize import write_claude_index, write_codex_user_memories

def test_write_claude_index_bundle(tmp_path):
    home = tmp_path / "claude"
    mems = [_mem("g", ["global"], body="看 $VAULT/a\n")]
    out = write_claude_index(mems, {"VAULT": "Z:/v"}, home, ["work"])
    assert out == home / "hub" / "memory-index.md"
    assert "Z:/v/a" in out.read_text(encoding="utf-8")

def test_write_claude_index_matches_device_scope(tmp_path):
    # device:work 记忆：本机 class 含 work 才应命中（回归 Target 丢 classes 的 bug）
    home = tmp_path / "claude"
    mems = [_mem("w", ["device:work"], body="仅公司机\n")]
    got = write_claude_index(mems, {}, home, ["work"]).read_text(encoding="utf-8")
    assert "仅公司机" in got
    home2 = tmp_path / "claude2"
    got2 = write_claude_index(mems, {}, home2, ["home"]).read_text(encoding="utf-8")
    assert "仅公司机" not in got2

def test_write_codex_user_skips_project_scoped(tmp_path):
    d = tmp_path / "codexmem"
    mems = [_mem("g", ["global"]), _mem("p", ["project:xinao"])]
    written = write_codex_user_memories(mems, {}, d, ["work"])
    assert written == ["g"]                 # project 级不进用户目录
    assert (d / "g.md").exists()
    assert not (d / "p.md").exists()

def test_ensure_user_claude_import_idempotent():
    from hub.materialize import ensure_user_claude_import
    once = ensure_user_claude_import("我的手写\n", "hub/memory-index.md")
    twice = ensure_user_claude_import(once, "hub/memory-index.md")
    assert twice.count("@hub/memory-index.md") == 1
    assert "我的手写" in twice
