"""memory 视图/受管块/opencode 条目的落盘编排。**prepare/validate all → commit writes**：
先只读预检并渲染全部目标 (path, text)（确定性错误 ViewScopeError/BlockError 在此抛、零副作用），
再逐个原子写。opencode 的 refuse 归 warnings、不抛不阻断。提交期 I/O 故障才可能部分完成、重跑收敛。
**一次扫 shared、内存里切三份工具子集**——三种产物绝不各扫各的。
"""
import os
from pathlib import Path
from hub.memview import (load_shared_memories, validate_scopes, entries_for_tool,
                         render_view_file, render_codex_block, shared_hash)
from hub.textblock import upsert_block
from hub.opencode_cfg import plan_instruction, commit_instruction
from hub.hubconfig import backups_dir
from hub.writer import Writer

_TOOLS = ("claude", "codex", "opencode")

def hub_views_home() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub")) / "views"

def _view_path(tool: str) -> Path:
    return hub_views_home() / tool / "MEMORY.md"

def _codex_agents_target(dev) -> Path:
    """Codex 受管块目标：活动的非空 AGENTS.override.md 优先，否则 AGENTS.md。"""
    home = Path(dev.paths["CODEX_HOME"])
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8").strip():
        return override
    return home / "AGENTS.md"

def prepare_memory_views(vault_root: Path, dev):
    """只读预检 + 渲染全部目标。返回 (writes, warnings, opencode_plan)。
    ViewScopeError/BlockError 在此抛、零副作用；opencode refuse 归 warnings。"""
    mems = load_shared_memories(vault_root)                 # 只扫一次
    parsed = validate_scopes(mems)                           # scope 非法→ViewScopeError
    sh = shared_hash(mems)
    per_tool = {t: entries_for_tool(mems, parsed, vault_root, dev, t) for t in _TOOLS}
    writes: list[tuple[Path, str]] = []
    warnings: list[str] = []
    for t in _TOOLS:
        writes.append((_view_path(t), render_view_file(per_tool[t], t, sh)))
    if dev.paths.get("CLAUDE_HOME"):
        claude_md = Path(dev.paths["CLAUDE_HOME"]) / "CLAUDE.md"
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        body = f"# hub 共享记忆（自动生成，勿手改）\n@{_view_path('claude').as_posix()}"
        writes.append((claude_md, upsert_block(existing, body)))   # 坏块→BlockError（预检期）
    if dev.paths.get("CODEX_HOME"):
        target = _codex_agents_target(dev)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        writes.append((target, upsert_block(existing, render_codex_block(per_tool["codex"]))))
    plan = None
    if dev.paths.get("OPENCODE_CONFIG") or (Path.home() / ".config" / "opencode" / "opencode.json").exists():
        plan = plan_instruction(dev, _view_path("opencode"))
        if plan.action == "refuse":
            warnings.append(f"opencode: {plan.reason}")
    return writes, warnings, plan

def commit_memory_views(writes, plan, w: Writer) -> None:
    for path, text in writes:
        w.write_text_atomic(path, text)
    if plan is not None:
        commit_instruction(plan, w, backups_dir())

def wire_memory_views(vault_root: Path, dev, w: Writer) -> dict:
    writes, warnings, plan = prepare_memory_views(vault_root, dev)   # 全量预检；确定性错误→零写
    commit_memory_views(writes, plan, w)
    return {"written": len(writes), "warnings": warnings}
