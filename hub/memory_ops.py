"""memory-explain / memory-audit 两条只读命令的核心（plan §4 / §3.5）。

memory-explain：解释每条记忆在某个工具的视图里落在哪一段——展开 / 折叠 / 已归档 /
被 scope 筛掉——命中哪条规则（type / group / archived / index），以及它在视图里的
实际字节数。判定**全走** classify_entries，本文件不重写判据；scope 过滤是
entries_for_tool 的活，而 explain 必须从 load_shared_memories 的全量出发，把「被
scope 筛掉」也当成一种判定结果说出来——否则永远回答不了「这条为什么没出现」，而
这个命令存在就是为了回答它（plan §4 硬要求 1）。

memory-audit：列三类归档候选——疑似完成 / 久未更新 / 归档已久——**只列不改**。归档是
用户的人工闸门（plan §3.5：判定权在人，不在代码），代码只负责把候选指出来，审阅那一步
不许省。两个阈值是拍出来的（plan §9），必须做成命令行参数，不许写死在代码里。

两条命令都不写一个字节：所有计算在内存里完成，直接交给 CLI 输出。
"""
import subprocess
from datetime import date, datetime
from pathlib import Path

from hub.memview import (load_shared_memories, validate_scopes, classify_entries,
                         _view_entry, expanded_entry_text)
from hub.model import DeviceProfile
from hub.scope import scope_matches
from hub.platforms import all_names, enabled_names, check_enabled

# memory-explain 省略 --tool 时解释「本机启用的全部平台」，不是猜当前工具（plan §4 硬要求 3）。
# --tool 的可选值是注册表全集；点名一个本机停用的平台会明确报错（见 explain_memories）。
EXPLAIN_TOOLS = all_names()

# 完成态词（plan §3.5）：project 的 description 命中任一个即算「疑似完成」候选。
_DONE_WORDS = ("shipped", "已完成", "已落地", "全部", "已闭环")


def _scope_miss_reason(dims: dict, dev: DeviceProfile, tool: str) -> str:
    """对照 device.toml 的 classes/projects 和目标 tool，说清哪一条谓词把这条筛掉了。

    分解必须和 scope_matches 的判定同源：设备维度（class/project）OR 后跟本机标签集求交，
    tool 维度看目标在不在集合里。两处算法一旦分叉，explain 说出的理由就和实际视图对不上——
    这条命令的全部价值就是「说得对」。
    """
    subs = dims.get("class", set()) | {f"@proj:{p}" for p in dims.get("project", set())}
    device_tags = set(dev.classes) | {f"@proj:{p}" for p in dev.projects}
    parts = []
    if subs and not (subs & device_tags):
        preds = ([f"class:{c}" for c in sorted(dims.get("class", set()))]
                 + [f"project:{p}" for p in sorted(dims.get("project", set()))])
        parts.append("设备订阅不匹配：需要 " + " / ".join(preds)
                     + f"，本机 class={sorted(dev.classes)!r} projects={sorted(dev.projects)!r}")
    tools = dims.get("tool", set())
    if tools and tool not in tools:
        parts.append(f"tool 不匹配：只对 {sorted(tools)!r}，目标是 {tool!r}")
    return "；".join(parts) or "scope 谓词不匹配"


def _decision_row(e, decision: str, rule: str, group):
    """构造一条 explain 记录。bytes 必须对**实际渲染字符串**算——展开段就是渲染器里那条
    `- name — description`（与 expanded_entry_text 共用，绝不另写估算公式，plan §4 硬要求
    2）；折叠/归档段里条目自己的实际文本就是它的 name。被 scope 筛掉 = 视图里 0 字节。"""
    text = expanded_entry_text(e) if decision == "expanded" else e.name
    return {"name": e.name, "decision": decision, "rule": rule, "group": group,
            "bytes": len(text.encode("utf-8")), "text": text}


def _explain_tool(mems, parsed, vault_root: Path, dev: DeviceProfile, tool: str) -> dict:
    """解释单个工具。从全量出发：scope 匹配的走 classify_entries 定段，不匹配的单独记
    scope_miss。classify_entries 只吃匹配后的条目——所以 scope miss 必须在这里补记，否则
    全量里被筛掉的那几条就从 explain 里蒸发了（那正是本命令要回答的问题）。"""
    entries, misses = [], []
    for m in mems:
        e = _view_entry(m, vault_root)
        if scope_matches(parsed[m.name], dev.classes, dev.projects, tool):
            entries.append(e)
        else:
            misses.append((e, _scope_miss_reason(parsed[m.name], dev, tool)))
    cls = classify_entries(entries)
    decided = {}
    for e in cls.expanded:
        rule = "index=expanded" if e.index == "expanded" else "type=feedback"
        decided[e.name] = ("expanded", rule, e.group)
    for group, members in cls.folded.items():
        for e in members:
            decided[e.name] = ("folded", f"group={group}", group)
    for e in cls.archived:
        decided[e.name] = ("archived", f"archived={e.archived}", e.group)
    rows = []
    counts = {"total": len(mems), "expanded": 0, "folded": 0, "archived": 0, "scope_miss": 0}
    byte_sums = {"expanded": 0, "folded": 0, "archived": 0}
    for e in entries:
        decision, rule, group = decided[e.name]
        row = _decision_row(e, decision, rule, group)
        counts[decision] += 1
        byte_sums[decision] += row["bytes"]
        rows.append(row)
    for e, reason in misses:
        counts["scope_miss"] += 1
        rows.append({"name": e.name, "decision": "scope_miss", "rule": reason,
                     "group": None, "bytes": 0, "text": ""})
    rows.sort(key=lambda r: r["name"])
    return {
        "tool": tool,
        "summary": {"total": counts["total"], "expanded": counts["expanded"],
                    "folded": counts["folded"], "archived": counts["archived"],
                    "scope_miss": counts["scope_miss"],
                    "bytes": {"expanded": byte_sums["expanded"], "folded": byte_sums["folded"],
                              "archived": byte_sums["archived"],
                              "total": sum(byte_sums.values())}},
        "entries": rows,
    }


def explain_memories(vault_root: Path, dev: DeviceProfile, tool: str | None) -> dict:
    """--tool 给了就解释那一个（必须是本机启用的）；没给就解释本机启用的全部平台（plan §4 硬要求 3）。"""
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)
    if tool:
        check_enabled(dev, tool)                # 点名停用的平台 → 明确报错
    tools = (tool,) if tool else enabled_names(dev)
    return {"host": dev.host, "vault": str(vault_root), "tool": tool,
            "tools": [_explain_tool(mems, parsed, vault_root, dev, t) for t in tools]}


# ---- memory-audit ---------------------------------------------------------

def _git_available(vault_root: Path) -> bool:
    r = subprocess.run(["git", "-C", str(vault_root), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0 and r.stdout.strip() == "true"


def _git_status(vault_root: Path) -> str:
    r = subprocess.run(["git", "-C", str(vault_root), "status", "--porcelain"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def _last_commit_date(vault_root: Path, name: str):
    """金库是 git 仓时，取该记忆文件最后被提交的时间（提交者日期 %cI）。文件从未提交 /
    金库不是仓 / 日期解析失败都返回 None（无法判断，不硬猜）。"""
    r = subprocess.run(["git", "-C", str(vault_root), "log", "-1", "--format=%cI",
                        "--", f"shared/memory/{name}.md"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    s = r.stdout.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def audit_memories(vault_root: Path, stale_days: int = 90, archived_days: int = 180) -> dict:
    """列三类归档候选，只列不改。归档池（第三条）走 classify_entries 的归档段——和视图
    用的是同一个判据，代码不另设一套「什么算归档」。前两条扫 project 且未归档的条目。"""
    mems = load_shared_memories(vault_root)
    validate_scopes(mems)
    entries = [_view_entry(m, vault_root) for m in mems]
    cls = classify_entries(entries)
    today = date.today()
    possibly_done, stale = [], []
    for e in entries:
        if e.type != "project" or e.archived is not None:
            continue
        hit = [w for w in _DONE_WORDS if w in e.description]
        if hit:
            possibly_done.append({"name": e.name, "description": e.description, "words": hit})
    git_ok = _git_available(vault_root)
    if git_ok:
        for e in entries:
            if e.type != "project" or e.archived is not None:
                continue
            last = _last_commit_date(vault_root, e.name)
            if last is not None:
                days = (today - last).days
                if days > stale_days:
                    stale.append({"name": e.name, "days": days, "last_commit": last.isoformat()})
    archived_long = []
    for e in cls.archived:
        try:
            d = date.fromisoformat(e.archived)
        except (TypeError, ValueError):
            continue
        days = (today - d).days
        if days > archived_days:
            archived_long.append({"name": e.name, "archived": e.archived, "days": days})
    return {
        "vault": str(vault_root),
        "stale_days": stale_days,
        "archived_days": archived_days,
        "git_available": git_ok,
        "git_clean": _git_status(vault_root).strip() == "",
        "candidates": {"possibly_done": possibly_done, "stale": stale,
                       "archived_long": archived_long},
    }


# ---- 人类可读渲染（JSON 走 CLI 的 _emit_result，这里只管给人看的文本）--------

def render_explain_human(result: dict) -> str:
    multi = len(result["tools"]) > 1
    out = ["# memory-explain" + ("" if multi else f" — {result['tool']}")]
    if multi:
        out.append("（--tool 未给：解释全部四个工具）")
    out.append(f"金库: {result['vault']} · 本机: {result['host']}")
    for per in result["tools"]:
        if multi:
            out.append("")
            out.append(f"## {per['tool']}")
        s = per["summary"]
        out.append(f"共 {s['total']} 条：展开 {s['expanded']} · 折叠 {s['folded']} · "
                   f"已归档 {s['archived']} · 被 scope 筛掉 {s['scope_miss']}")
        out.append(f"## 展开（{s['expanded']} 条 · {s['bytes']['expanded']} B）")
        for r in per["entries"]:
            if r["decision"] == "expanded":
                out.append(f"{r['text']}  [{r['rule']} · {r['bytes']} B]")
        out.append(f"## 折叠（{s['folded']} 条 · 名字合计 {s['bytes']['folded']} B）")
        by_group = {}
        for r in per["entries"]:
            if r["decision"] == "folded":
                by_group.setdefault(r["group"], []).append(r)
        for g, rows in by_group.items():
            names = " · ".join(f"{r['name']}({r['bytes']} B)" for r in rows)
            out.append(f"- {g}({len(rows)} · {sum(r['bytes'] for r in rows)} B): {names}")
        out.append(f"## 已归档（{s['archived']} 条 · 名字合计 {s['bytes']['archived']} B）")
        for r in per["entries"]:
            if r["decision"] == "archived":
                out.append(f"- {r['name']}  [{r['rule']} · {r['bytes']} B]")
        out.append(f"## 被 scope 筛掉（{s['scope_miss']} 条 · 0 B）")
        for r in per["entries"]:
            if r["decision"] == "scope_miss":
                out.append(f"- {r['name']}  [{r['rule']}]")
    return "\n".join(out) + "\n"


def render_audit_human(result: dict) -> str:
    c = result["candidates"]
    out = ["# memory-audit", f"金库: {result['vault']}",
           f"阈值: 久未更新 > {result['stale_days']} 天 · 归档已久 > {result['archived_days']} 天"]
    if c["possibly_done"]:
        out.append(f"## 疑似完成（{len(c['possibly_done'])} 条 · project 命中完成态词,未归档）")
        for r in c["possibly_done"]:
            out.append(f"- {r['name']} — {r['description']}  [命中: {'/'.join(r['words'])}]")
    if c["stale"]:
        out.append(f"## 久未更新（{len(c['stale'])} 条 · 超过 {result['stale_days']} 天未在 git 改动）")
        for r in sorted(c["stale"], key=lambda x: -x["days"]):
            out.append(f"- {r['name']} —— {r['days']} 天前（{r['last_commit']} 最后提交）")
    if c["archived_long"]:
        out.append(f"## 归档已久（{len(c['archived_long'])} 条 · 归档超过 {result['archived_days']} 天）")
        for r in sorted(c["archived_long"], key=lambda x: -x["days"]):
            out.append(f"- {r['name']} —— 归档于 {r['archived']}（{r['days']} 天前）")
    if not any(c.values()):
        out.append("没有候选（三类都为空）")
    if not result["git_available"]:
        out.append("⚠ 金库不是 git 仓：久未更新检查跳过")
    out.append("git 状态: " + ("干净" if result["git_clean"] else "有未提交改动（只读命令不会动它们）"))
    return "\n".join(out) + "\n"
