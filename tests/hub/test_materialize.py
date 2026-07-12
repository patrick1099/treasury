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

def test_claude_md_agents_only_when_no_import():
    # 工程级 CLAUDE.md 不应产出悬空的 @hub/memory-index.md 导入（该文件只在 CLAUDE_HOME 落地）
    out = render_claude_md("手写\n")
    inner = extract_block(out)
    assert "@AGENTS.md" in inner
    assert "@hub/memory-index.md" not in out
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
from hub.materialize import (render_codex_global_agents, render_index,
                             resolved_body, select_user_level)

def test_index_carries_summary_not_full_body():
    # 关键约束：上下文里只放索引，正文按需读。全文拼进去 = 每个会话吃 85KB。
    m = _mem("g", ["global"], body="很长很长的正文" * 100)
    m.description = "一句话摘要"
    out = render_index([m], "C:/x/hub/memory")
    assert "一句话摘要" in out
    assert "C:/x/hub/memory" in out               # 指出正文在哪个目录（说一次，不每行重复）
    assert "很长很长的正文" not in out             # 正文绝不进索引

def test_user_level_selection_matches_scope_and_skips_project():
    mems = [_mem("g", ["global"]), _mem("w", ["device:work"]),
            _mem("p", ["project:xinao"])]
    got = {m.name for m in select_user_level(mems, ["work"], "claude")}
    assert got == {"g", "w"}                      # 工程专属不进用户级(会跨工程泄漏)
    assert {m.name for m in select_user_level(mems, ["home"], "claude")} == {"g"}

def test_resolved_body_expands_or_skips():
    assert "Z:/v/a" in resolved_body(_mem("g", ["global"], body="看 $VAULT/a\n"),
                                     {"VAULT": "Z:/v"})
    # 本机没定义该符号根 -> 返回 None，跳过，不写出断链的文件
    assert resolved_body(_mem("g", ["global"], body="看 $NOPE/a\n"), {}) is None

def test_codex_global_agents_wraps_index_in_block():
    out = render_codex_global_agents("我手写的 Codex 全局指令\n", "- **g** — 摘要\n")
    assert "我手写的 Codex 全局指令" in out          # 块外用户内容不动
    assert "- **g** — 摘要" in out
    twice = render_codex_global_agents(out, "- **g** — 摘要\n")
    assert twice.count("<!-- hub:begin -->") == 1   # 幂等，不叠块

def test_ensure_user_claude_import_idempotent():
    from hub.materialize import ensure_user_claude_import
    once = ensure_user_claude_import("我的手写\n", "hub/memory-index.md")
    twice = ensure_user_claude_import(once, "hub/memory-index.md")
    assert twice.count("@hub/memory-index.md") == 1
    assert "我的手写" in twice

def test_claude_project_dir_and_selection(tmp_path):
    from hub.materialize import claude_project_memory_dir, select_claude_project
    from claude_migrate import encode_project_path
    home = tmp_path / "claude"
    root = "C:/proj/x"
    mems = [_mem("pj", ["project:xinao"], body="坑\n"),
            _mem("g", ["global"], body="全局\n")]
    mem_dir = claude_project_memory_dir(root, home)
    assert mem_dir.parent.name == encode_project_path(root)   # 目录名编码一致
    picked = {m.name for m in select_claude_project(mems, "xinao", ["work"])}
    assert picked == {"pj"}                   # 只有工程专属的进工程目录，全局的走 bundle
