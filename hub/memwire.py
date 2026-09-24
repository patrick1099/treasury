"""memory 视图/受管块/各平台入口接线的落盘编排。**prepare/validate all → commit writes**：
先只读预检并渲染全部目标 (path, text)（确定性错误 ViewScopeError/BlockError 在此抛、零副作用），
再逐个原子写。opencode 的 refuse 归 warnings、不抛不阻断。提交期 I/O 故障才可能部分完成、重跑收敛。
**一次扫 shared、内存里按平台切子集**——视图和各平台接线绝不各扫各的。

只处理本机启用的平台（hub.platforms）；启用的平台里有一个加载不了，整次预检失败、零写入。
每个平台的视图文件形状相同，由这里统一渲染；把视图接进平台自己的入口文件（CLAUDE.md 受管块、
Codex AGENTS.md 受管块、opencode.json instructions）归各平台适配器。
"""
import os
from pathlib import Path
from hub.memview import (load_shared_memories, validate_scopes, entries_for_tool,
                         render_view_file, shared_hash)
from hub.writer import Writer
from hub import platforms
from hub.platforms.base import WiringCtx


def hub_views_home() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub")) / "views"


def view_path(tool: str) -> Path:
    return hub_views_home() / tool / "MEMORY.md"


_view_path = view_path      # 旧名，保留给既有调用方


def prepare_memory_views(vault_root: Path, dev):
    """只读预检 + 渲染全部目标。返回 (writes, warnings, plans)。
    plans 是各平台需要自己提交的额外计划（如 opencode.json），没有就是空表。
    ViewScopeError/BlockError/PlatformUnavailable 在此抛、零副作用；opencode refuse 归 warnings。"""
    loaded = platforms.enabled(dev)
    msg = platforms.unavailable_message(loaded)
    if msg:
        raise platforms.PlatformUnavailable(msg)
    names = [x.name for x in loaded]
    mems = load_shared_memories(vault_root)                 # 只扫一次
    parsed = validate_scopes(mems)                           # scope 非法→ViewScopeError
    sh = shared_hash(mems)
    per_tool = {t: entries_for_tool(mems, parsed, vault_root, dev, t) for t in names}
    writes: list[tuple[Path, str]] = []
    warnings: list[str] = []
    if not mems:
        # shared 空但本机备份区有记忆 → 视图只会是占位。空 shared 是合法的新机状态，
        # 备份区也空时不吭声；只有"有记忆却忘了 promote"才提示。只 warn，不改写入/退出码。
        backup = Path(vault_root) / dev.host / "claude" / "memory"
        n = len(list(backup.glob("*.md"))) if backup.is_dir() else 0
        if n:
            warnings.append(
                f"本机备份区有 {n} 条记忆，但 shared/memory 为空；本次生成的记忆视图将只有占位内容。"
                f"请先用 `promote-memory --name <名称>` 审阅提升，或确认全部适合共享后使用 `promote-memory --all`。")
    for t in names:
        writes.append((view_path(t), render_view_file(per_tool[t], t, sh)))
    ctx = WiringCtx(vault_root=Path(vault_root), dev=dev, per_tool=per_tool,
                    shared_hash=sh, view_path=view_path)
    plans = []
    for x in loaded:
        wiring = x.adapter.prepare_wiring(ctx)               # 坏受管块→BlockError（预检期）
        writes += wiring.writes
        warnings += wiring.warnings
        if wiring.plan is not None:
            plans.append(wiring.plan)
    return writes, warnings, plans


def commit_memory_views(writes, plans, w: Writer) -> None:
    for path, text in writes:
        w.write_text_atomic(path, text)
    for plan in plans or ():
        plan.commit(w)


def wire_memory_views(vault_root: Path, dev, w: Writer) -> dict:
    writes, warnings, plans = prepare_memory_views(vault_root, dev)   # 全量预检；确定性错误→零写
    commit_memory_views(writes, plans, w)
    return {"written": len(writes), "warnings": warnings}
