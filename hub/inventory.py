"""hub inventory --json 的读侧资产矩阵。

只做只读整理：把金库里的 plugin / skill / memory 三类资产与四类 harness
组合成统一 JSON 矩阵，并复用既有状态模块（plugin_health、opencode_skill_status、
dsh_loader_status、memview 等）取 desired/actual/health/control。

CLI 不可用、opencode/dsh 未安装等局部不可判定场景不中断整个 inventory，
对应单元格标 health="unknown"，消息进入返回 dict 的 warnings。
"""
import os
import re
from datetime import datetime
from pathlib import Path

from hub.vault import load_device, current_host
from hub.model import SHARED, DeviceProfile
from hub.plugin_manifest import load_plugin_manifest
from hub.plugin_ops import plugin_health
from hub.plugin_cli import installed_plugins
from hub.opencode_skills import opencode_skill_dir, opencode_skill_status
from hub.dsh_ops import (dsh_profile_dir, dsh_loader_status, patch_path)
from hub.memview import load_shared_memories, validate_scopes, entries_for_tool, shared_hash
from hub.memwire import hub_views_home
from hub.fslink import resolves_to
from hub.vaultpaths import shared_skills_dir

HARNESSES = ("claude", "codex", "opencode", "dsh")


# ---------------------------------------------------------------- helpers

def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _path_str(p) -> str:
    return Path(p).resolve().as_posix()


def _skill_desired(dev: DeviceProfile, tool: str, name: str) -> bool:
    """[skills.<tool>].enabled 缺省=全部开启；存在 key 时是权威列表。"""
    enabled = dev.skills.get(tool)
    if enabled is None:
        return True
    return name in enabled


def _view_path(tool: str) -> Path:
    return hub_views_home() / tool / "MEMORY.md"


def _patch_has(patch_text: str | None, section: str, item: str) -> bool:
    """极简 YAML 列表解析：在当前 D0 生成的 patch 里读 enabledPlugins/enabledSkills。"""
    if not patch_text:
        return False
    pattern = re.compile(rf"^{re.escape(section)}\s*:", re.M)
    m = pattern.search(patch_text)
    if not m:
        return False
    after = patch_text[m.end():]
    found = False
    for line in after.splitlines():
        if re.match(r"^\s*-", line):
            if re.search(rf"['\"]?{re.escape(item)}['\"]?", line):
                found = True
        elif line.strip() and not line.startswith(("#", " ")):
            break
    return found


# 视图行的两个定界符,与 hub/memview.py 的 _render_layered_body 一一对应。
# 改渲染定界必须同时改这里 —— 不同步的后果是健康度静默全线误报。
EM_DASH = " \u2014 "
MIDDOT = " \u00b7 "


def _view_names(tool: str) -> set[str]:
    """视图里出现的全部记忆名。

    分层改造(2026-08-31)之后视图有三种行形:
      展开段  - name 破折号 description
      折叠段  - 组名(k): name 中点 name 中点 name
      归档段  - name 中点 name
    老实现是拿方括号包名和反引号包名去 text 里捞子串 —— 这两种定界符在新格式里一个都不
    出现,于是**每一条都判成"视图里没有",健康度全线误报**。顺带治掉子串误命中:这里回的
    是精确的名字集合,不是子串匹配,名字互为前缀时也不会串。"""
    v = _view_path(tool)
    if not v.exists():
        return set()
    try:
        text = v.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        row = line[2:]
        if EM_DASH in row:                          # 展开段:name 在首个破折号之前
            names.add(row.split(EM_DASH, 1)[0].strip())
            continue
        head, sep, rest = row.partition(": ")       # 折叠段:剥掉组名与计数前缀
        if sep and head.endswith(")"):
            row = rest
        names.update(x.strip() for x in row.split(MIDDOT) if x.strip())
    return names


def _view_has_memory(tool: str, name: str) -> bool:
    return name in _view_names(tool)


def _view_hash_state(tool: str, cur_hash: str) -> str:
    v = _view_path(tool)
    if not v.exists():
        return "missing"
    try:
        text = v.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "missing"
    for line in text.splitlines():
        if "shared_hash:" in line:
            embedded = line.split("shared_hash:", 1)[1].split("-->", 1)[0].strip()
            return "ok" if embedded == cur_hash else "stale"
    # 视图存在却找不到 shared_hash 行 = 版本不可验证。以前这里回 "ok",等于把
    # "查不出来"当"没问题"报,和视图根本没刷新是同样的后果,只是账面全绿。
    return "stale"


def _standalone_sources(vault_root: Path, hub_root: Path | None) -> list[tuple[str, Path]]:
    """shared/skills/* + hub 包内 hub-memory（存在时才加）。"""
    out: list[tuple[str, Path]] = []
    shared = shared_skills_dir(vault_root)      # 容器逃逸时抛 SharedSkillsEscape（E_VALIDATION）
    if shared.is_dir():
        out.extend((d.name, d) for d in sorted(shared.iterdir(), key=lambda p: p.name)
                   if d.is_dir())
    if hub_root is not None:
        src = Path(hub_root) / "hub" / "skills" / "hub-memory"
        if src.is_dir() and not any(n == "hub-memory" for n, _ in out):
            out.append(("hub-memory", src))
    return out


def _plugin_internal_skills(vault_root: Path, plugin: str) -> list[tuple[str, Path]]:
    d = Path(vault_root) / "shared" / "plugins" / plugin / "skills"
    if not d.is_dir():
        return []
    return [(x.name, x) for x in sorted(d.iterdir(), key=lambda p: p.name)
            if x.is_dir() and (x / "SKILL.md").is_file()]


def _plugin_cli_cell(vault_root, dev, entry, tool, health_by_name, installed_snap):
    name = entry.name
    desired = name in dev.plugins.get(tool, [])
    pid = f"{name}@{name}"
    inst = installed_snap.get(tool)
    if inst is not None:
        present = pid in inst
        active = present and (inst[pid].enabled if tool == "claude" else True)
        actual = bool(active)
    else:
        actual = None
    health = health_by_name.get((name, tool), "unknown")
    if health == "enable-drift" and inst is not None:
        actual = bool(pid in inst and (inst[pid].enabled if tool == "claude" else True))
    if health == "unknown":
        detail = f"{tool}: CLI 状态不可用，无法判定安装/启用"
    else:
        detail = f"{tool}: {health}"
    return {
        "harness": tool,
        "desired": desired,
        "actual": actual,
        "health": health,
        "control": "direct",
        "detail": detail,
    }


def _plugin_opencode_cell(vault_root, dev, entry, oc_dir, oc_rows):
    name = entry.name
    desired = name in dev.plugins.get("opencode", [])
    skills = _plugin_internal_skills(vault_root, name)
    skill_names = {n for n, _ in skills}
    if oc_dir is None:
        if desired:
            return {"harness": "opencode", "desired": True, "actual": False,
                    "health": "missing", "control": "direct",
                    "detail": "opencode 未配置（无 OPENCODE_HOME/OPENCODE_CONFIG）"}
        return {"harness": "opencode", "desired": False, "actual": False,
                "health": "ok", "control": "direct",
                "detail": "插件未启用，opencode 也未配置"}
    statuses = []
    for sname, src in skills:
        link = oc_dir / sname
        if not os.path.lexists(link):
            statuses.append(("missing", str(link)))
        elif resolves_to(link, src):
            statuses.append(("ok", str(link)))
        else:
            statuses.append(("conflict", str(link)))
    if desired and not skills:
        actual, health = True, "ok"
        detail = f"opencode: 插件 {name} 无内部 skill，空转 ok"
    elif desired:
        actual = all(s == "ok" for s, _ in statuses)
        if any(s == "conflict" for s, _ in statuses):
            health = "conflict"
        elif any(s == "missing" for s, _ in statuses):
            health = "missing"
        else:
            health = "ok"
        detail = "opencode: " + "; ".join(f"{s}={l}" for s, l in statuses) or "ok"
    else:
        orphan = next((l for s, l in oc_rows if s == "orphan"
                       and Path(l).name in skill_names), None)
        if orphan:
            actual, health = True, "orphan"
            detail = f"opencode: 插件 {name} 已关闭，仍存在遗留链 {orphan}"
        else:
            actual, health = False, "ok"
            detail = "opencode: 插件未启用"
    return {"harness": "opencode", "desired": desired, "actual": actual,
            "health": health, "control": "direct", "detail": detail}


def _plugin_dsh_cell(dev, entry, dsh_rows):
    name = entry.name
    desired = name in dev.plugins.get("dsh", [])
    patch = patch_path(dev)
    enabled = False
    if patch is not None and patch.exists():
        try:
            enabled = _patch_has(patch.read_text(encoding="utf-8", errors="replace"),
                                 "enabledPlugins", name)
        except OSError:
            pass
    if dsh_profile_dir(dev) is None:
        return {"harness": "dsh", "desired": desired, "actual": False,
                "health": "missing", "control": "direct",
                "detail": "dsh 未安装（无 DSH_HOME 或 .dsh）"}
    if any(s == "conflict" for s, _ in dsh_rows):
        return {"harness": "dsh", "desired": desired, "actual": bool(enabled),
                "health": "conflict", "control": "direct",
                "detail": "dsh loader patch 冲突"}
    if desired and enabled:
        return {"harness": "dsh", "desired": True, "actual": True,
                "health": "ok", "control": "direct",
                "detail": f"dsh enabledPlugins 已含 {name}"}
    if desired and not enabled:
        return {"harness": "dsh", "desired": True, "actual": False,
                "health": "missing", "control": "direct",
                "detail": f"dsh enabledPlugins 未含 {name}"}
    if not desired and enabled:
        return {"harness": "dsh", "desired": False, "actual": True,
                "health": "conflict", "control": "direct",
                "detail": f"dsh 已关闭但在 patch 中仍启用 {name}"}
    return {"harness": "dsh", "desired": False, "actual": False,
            "health": "ok", "control": "direct", "detail": "dsh 未启用"}


def _standalone_claude_codex_cell(dev, tool, name, src):
    if tool == "claude":
        home = dev.paths.get("CLAUDE_HOME")
        target = (Path(home) / "skills") if home else None
        label = "CLAUDE_HOME" if home is None else "claude 技能目录"
    else:
        agents = dev.paths.get("AGENTS_HOME")
        target = (Path(agents) / "skills") if agents else (Path.home() / ".agents" / "skills")
        label = "AGENTS_HOME" if agents is None else "codex/AGENTS 技能目录"
    desired = _skill_desired(dev, tool, name)
    if target is None:
        actual, health, detail = False, "missing", f"{tool}: 未配置 {label}，无法判定实际状态"
    else:
        link = target / name
        if not os.path.lexists(link):
            actual, health, detail = False, "missing", str(link)
        elif resolves_to(link, src):
            actual, health, detail = True, "ok", f"{tool}: {link} -> {src}"
        else:
            actual, health, detail = False, "conflict", f"{tool}: {link} 指向别处"
    return {"harness": tool, "desired": desired, "actual": actual,
            "health": health, "control": "direct", "detail": detail}


def _opencode_direct_cell(dev, name, src, oc_dir, oc_rows):
    desired = _skill_desired(dev, "opencode", name)
    if oc_dir is None:
        return {"harness": "opencode", "desired": desired, "actual": False,
                "health": "missing" if desired else "ok", "control": "direct",
                "detail": "opencode 未配置"}
    link = oc_dir / name
    if not os.path.lexists(link):
        actual, health, detail = False, "missing", f"opencode: {link}"
    elif resolves_to(link, src):
        if desired:
            actual, health, detail = True, "ok", f"opencode: {link} -> {src}"
        else:
            actual, health, detail = True, "orphan", f"opencode: {link} 已关闭但仍存在"
    else:
        actual, health, detail = False, "conflict", f"opencode: {link} 指向别处"
    return {"harness": "opencode", "desired": desired, "actual": actual,
            "health": health, "control": "direct", "detail": detail}


def _dsh_direct_cell(dev, name, src, plugin_name):
    desired = _skill_desired(dev, "dsh", name)
    key = f"{plugin_name}:{name}" if plugin_name else name
    patch = patch_path(dev)
    enabled = False
    if patch is not None and patch.exists():
        try:
            enabled = _patch_has(patch.read_text(encoding="utf-8", errors="replace"),
                                 "enabledSkills", key)
        except OSError:
            pass
    if dsh_profile_dir(dev) is None:
        return {"harness": "dsh", "desired": desired, "actual": False,
                "health": "missing", "control": "direct",
                "detail": "dsh 未安装，无法判定 enabledSkills"}
    if desired and enabled:
        return {"harness": "dsh", "desired": True, "actual": True,
                "health": "ok", "control": "direct",
                "detail": f"dsh enabledSkills 已含 {key}"}
    if desired and not enabled:
        return {"harness": "dsh", "desired": True, "actual": False,
                "health": "missing", "control": "direct",
                "detail": f"dsh enabledSkills 未含 {key}"}
    if not desired and enabled:
        return {"harness": "dsh", "desired": False, "actual": True,
                "health": "conflict", "control": "direct",
                "detail": f"dsh 已关闭但 enabledSkills 仍含 {key}"}
    return {"harness": "dsh", "desired": False, "actual": False,
            "health": "ok", "control": "direct", "detail": "dsh 未启用"}


def _dsh_unmanaged_cell(dev, name):
    desired = _skill_desired(dev, "dsh", name)
    return {"harness": "dsh", "desired": desired, "actual": None,
            "health": "unknown", "control": "unmanaged",
            "detail": "dsh 独立 skill 本期只读展示，未纳入单切"}


# ---------------------------------------------------------------- builders

def _build_plugin_assets(vault_root, dev, entries, health_by_name, installed_snap,
                         oc_dir, oc_rows, dsh_rows, warnings):
    assets = []
    plugin_cells: dict[str, dict] = {}
    for entry in entries:
        cells = {}
        for tool in HARNESSES:
            if tool not in entry.platforms:
                continue
            if tool in ("claude", "codex"):
                cells[tool] = _plugin_cli_cell(vault_root, dev, entry, tool,
                                               health_by_name, installed_snap)
            elif tool == "opencode":
                cells[tool] = _plugin_opencode_cell(vault_root, dev, entry, oc_dir, oc_rows)
            else:
                cells[tool] = _plugin_dsh_cell(dev, entry, dsh_rows)
        if not cells:
            continue
        plugin_cells[entry.name] = cells
        assets.append({
            "type": "plugin",
            "id": f"plugin:{entry.name}",
            "name": entry.name,
            "path": _path_str(Path(vault_root) / "shared" / "plugins" / entry.name),
            "plugin": None,
            "skill_origin": None,
            "platforms": [t for t in HARNESSES if t in entry.platforms],
            "harnesses": cells,
        })
    return assets, plugin_cells


def _build_plugin_skill_assets(vault_root, dev, entries, plugin_cells,
                               oc_dir, oc_rows, warnings):
    assets = []
    for entry in entries:
        for name, src in _plugin_internal_skills(vault_root, entry.name):
            cells = {}
            platforms = []
            for tool in HARNESSES:
                if tool not in entry.platforms:
                    continue
                if tool in ("claude", "codex"):
                    pcell = plugin_cells.get(entry.name, {}).get(tool)
                    if pcell is None:
                        continue
                    cells[tool] = {
                        "harness": tool,
                        "desired": pcell["desired"],
                        "actual": pcell["actual"],
                        "health": pcell["health"],
                        "control": "plugin",
                        "detail": f"{tool} 不支持插件内单 skill，由插件 {entry.name} 整体控制",
                    }
                    platforms.append(tool)
                elif tool == "opencode":
                    cells[tool] = _opencode_direct_cell(dev, name, src, oc_dir, oc_rows)
                    platforms.append(tool)
                else:
                    cells[tool] = _dsh_direct_cell(dev, name, src, entry.name)
                    platforms.append(tool)
            if not cells:
                continue
            assets.append({
                "type": "skill",
                "id": f"skill:{entry.name}:{name}",
                "name": name,
                "path": _path_str(src),
                "plugin": entry.name,
                "skill_origin": "plugin-internal",
                "platforms": platforms,
                "harnesses": cells,
            })
    return assets


def _build_standalone_skill_assets(vault_root, dev, standalone_pairs,
                                   oc_dir, oc_rows, warnings):
    assets = []
    for name, src in standalone_pairs:
        cells = {}
        platforms = []
        for tool in HARNESSES:
            if tool in ("claude", "codex"):
                cells[tool] = _standalone_claude_codex_cell(dev, tool, name, src)
                platforms.append(tool)
            elif tool == "opencode":
                cells[tool] = _opencode_direct_cell(dev, name, src, oc_dir, oc_rows)
                platforms.append(tool)
            else:
                cells[tool] = _dsh_unmanaged_cell(dev, name)
                platforms.append(tool)
        assets.append({
            "type": "skill",
            "id": f"skill:standalone:{name}",
            "name": name,
            "path": _path_str(src),
            "plugin": None,
            "skill_origin": "standalone",
            "platforms": platforms,
            "harnesses": cells,
        })
    return assets


def _build_memory_assets(vault_root, dev, hub_root, warnings):
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)          # scope 非法 → ViewScopeError（E_NOT_FOUND）
    per_tool = {t: entries_for_tool(mems, parsed, vault_root, dev, t) for t in HARNESSES}
    cur_hash = shared_hash(mems)
    assets = []
    for m in mems:
        cells = {}
        for t in HARNESSES:
            desired = any(e.name == m.name for e in per_tool[t])
            actual = _view_has_memory(t, m.name)
            view_state = _view_hash_state(t, cur_hash)
            if desired and actual:
                health = "stale" if view_state == "stale" else "ok"
            elif desired and not actual:
                health = "missing"
            elif not desired and actual:
                health = "conflict" if view_state != "stale" else "stale"
            else:
                health = "stale" if view_state == "stale" else "ok"
            detail = (f"{t}: {'scope 命中' if desired else 'scope 不匹配'}; "
                      f"视图中{'有' if actual else '无'}条目; view={view_state}")
            cells[t] = {"harness": t, "desired": desired, "actual": actual,
                        "health": health, "control": "readonly", "detail": detail}
        assets.append({
            "type": "memory",
            "id": f"memory:{m.name}",
            "name": m.name,
            "path": _path_str(Path(vault_root) / SHARED / "memory" / f"{m.name}.md"),
            "plugin": None,
            "skill_origin": None,
            "scope": list(m.scope),
            "platforms": list(HARNESSES),
            "harnesses": cells,
        })
    return assets


# ---------------------------------------------------------------- public

def build_inventory(vault_root, host=None, hub_root=None) -> dict:
    vault_root = Path(vault_root)
    host = host or current_host()
    warnings: list[str] = []
    dev = load_device(vault_root, host)
    entries = load_plugin_manifest(vault_root)

    # claude/codex：CLI 不可用时整块降级为 unknown，不中断 inventory。
    try:
        health_rows = plugin_health(vault_root, dev)
        health_by_name = {(h.name, h.tool): h.state for h in health_rows}
    except Exception as e:
        health_by_name = {}
        warnings.append(f"claude/codex 插件健康检查不可用：{type(e).__name__}: {e}")

    installed_snap = {}
    for tool in ("claude", "codex"):
        try:
            installed_snap[tool] = installed_plugins(tool)
        except Exception as e:
            warnings.append(f"{tool} plugin list 不可用：{type(e).__name__}: {e}")

    if hub_root is not None:
        hub_root = Path(hub_root)

    oc_dir = opencode_skill_dir(dev)
    try:
        oc_rows = opencode_skill_status(vault_root, dev, hub_root)
    except Exception as e:
        oc_rows = []
        warnings.append(f"opencode skill 状态不可用：{type(e).__name__}: {e}")

    try:
        dsh_env_root = hub_root if hub_root is not None else Path(__file__).resolve().parents[1]
        dsh_rows = dsh_loader_status(vault_root, dev, dsh_env_root)
    except Exception as e:
        dsh_rows = []
        warnings.append(f"dsh loader 状态不可用：{type(e).__name__}: {e}")

    plugin_assets, plugin_cells = _build_plugin_assets(
        vault_root, dev, entries, health_by_name, installed_snap,
        oc_dir, oc_rows, dsh_rows, warnings)
    plugin_skill_assets = _build_plugin_skill_assets(
        vault_root, dev, entries, plugin_cells, oc_dir, oc_rows, warnings)

    standalone_pairs = _standalone_sources(vault_root, hub_root)
    standalone_assets = _build_standalone_skill_assets(
        vault_root, dev, standalone_pairs, oc_dir, oc_rows, warnings)

    memory_assets = _build_memory_assets(vault_root, dev, hub_root, warnings)

    assets = plugin_assets + plugin_skill_assets + standalone_assets + memory_assets
    matrix = []
    for asset in assets:
        for tool, cell in asset.get("harnesses", {}).items():
            row = {
                "asset_type": asset["type"],
                "asset_id": asset["id"],
                "asset_name": asset["name"],
                "harness": tool,
                "desired": cell["desired"],
                "actual": cell["actual"],
                "health": cell["health"],
                "control": cell["control"],
                "detail": cell["detail"],
            }
            matrix.append(row)

    seen = set()
    unique_warnings = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            unique_warnings.append(w)

    return {
        "vault": _path_str(vault_root.resolve() if vault_root.exists() else vault_root),
        "host": host,
        "generated_at": _iso_now(),
        "assets": assets,
        "matrix": matrix,
        "warnings": unique_warnings,
    }
