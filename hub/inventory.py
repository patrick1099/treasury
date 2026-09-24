"""hub inventory --json 的读侧资产矩阵。

只做只读整理：把金库里的 plugin / skill / memory 三类资产与本机启用的各平台（harness）
组合成统一 JSON 矩阵。每个单元格怎么判归平台适配器（hub.platforms）；这里只编排，
不按平台名分支。

- 停用的平台不出列，也不采样（不 import、不探测）。
- 启用却不可用的平台（适配器加载失败、依赖缺失）照样出列，单元格标 health="unknown"＋原因。
- CLI 不可用、平台未安装等局部不可判定场景不中断整个 inventory，消息进返回 dict 的 warnings。
"""
from datetime import datetime
from pathlib import Path

from hub.vault import load_device, current_host
from hub.model import SHARED
from hub.plugin_manifest import load_plugin_manifest
from hub.memview import load_shared_memories, validate_scopes, entries_for_tool, shared_hash
from hub.memwire import view_path
from hub.vaultpaths import shared_skills_dir
from hub import platforms
from hub.platforms.base import InvCtx, plugin_internal_skills, skill_desired


# ---------------------------------------------------------------- helpers

def _iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _path_str(p) -> str:
    return Path(p).resolve().as_posix()


def _view_path(tool: str) -> Path:
    return view_path(tool)


# 视图行的两个定界符,与 hub/memview.py 的 _render_layered_body 一一对应。
# 改渲染定界必须同时改这里 —— 不同步的后果是健康度静默全线误报。
EM_DASH = " — "
MIDDOT = " · "


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


def _unknown_cell(tool, desired, reason):
    return {"harness": tool, "desired": desired, "actual": None, "health": "unknown",
            "control": "direct", "detail": f"{tool} 平台不可用：{reason}"}


class _Sampled:
    """一次 inventory 里各启用平台的采样结果：可用的存 state，不可用的存原因。"""

    def __init__(self, loaded, ctx):
        self.loaded = loaded
        self.names = [x.name for x in loaded]
        self.states = {}
        self.down = {}
        for x in loaded:
            if x.adapter is None:
                self.down[x.name] = x.error
                ctx.warnings.append(f"{x.name} 平台不可用：{x.error}")
                continue
            try:
                self.states[x.name] = x.adapter.sample(ctx)
            except platforms.PlatformUnavailable as e:
                self.down[x.name] = str(e)
                ctx.warnings.append(f"{x.name} 平台不可用：{e}")


# ---------------------------------------------------------------- builders

def _build_plugin_assets(ctx, sp, entries):
    assets = []
    plugin_cells: dict[str, dict] = {}
    for entry in entries:
        cells = {}
        for x in sp.loaded:
            tool = x.name
            if tool not in entry.platforms:
                continue
            if tool in sp.down:
                cells[tool] = _unknown_cell(tool, entry.name in ctx.dev.plugins.get(tool, []),
                                            sp.down[tool])
                continue
            cell = x.adapter.plugin_cell(ctx, sp.states[tool], entry)
            if cell is not None:
                cells[tool] = cell
        if not cells:
            continue
        plugin_cells[entry.name] = cells
        assets.append({
            "type": "plugin",
            "id": f"plugin:{entry.name}",
            "name": entry.name,
            "path": _path_str(Path(ctx.vault_root) / "shared" / "plugins" / entry.name),
            "plugin": None,
            "skill_origin": None,
            "platforms": [t for t in sp.names if t in entry.platforms],
            "harnesses": cells,
        })
    return assets, plugin_cells


def _build_plugin_skill_assets(ctx, sp, entries, plugin_cells):
    assets = []
    for entry in entries:
        for name, src in plugin_internal_skills(ctx.vault_root, entry.name):
            cells = {}
            names = []
            for x in sp.loaded:
                tool = x.name
                if tool not in entry.platforms:
                    continue
                if tool in sp.down:
                    cell = _unknown_cell(tool, skill_desired(ctx.dev, tool, name), sp.down[tool])
                else:
                    cell = x.adapter.plugin_skill_cell(
                        ctx, sp.states[tool], entry, name, src,
                        plugin_cells.get(entry.name, {}).get(tool))
                if cell is None:
                    continue
                cells[tool] = cell
                names.append(tool)
            if not cells:
                continue
            assets.append({
                "type": "skill",
                "id": f"skill:{entry.name}:{name}",
                "name": name,
                "path": _path_str(src),
                "plugin": entry.name,
                "skill_origin": "plugin-internal",
                "platforms": names,
                "harnesses": cells,
            })
    return assets


def _build_standalone_skill_assets(ctx, sp, standalone_pairs):
    assets = []
    for name, src in standalone_pairs:
        cells = {}
        names = []
        for x in sp.loaded:
            tool = x.name
            if tool in sp.down:
                cell = _unknown_cell(tool, skill_desired(ctx.dev, tool, name), sp.down[tool])
            else:
                cell = x.adapter.standalone_skill_cell(ctx, sp.states[tool], name, src)
            if cell is None:
                continue
            cells[tool] = cell
            names.append(tool)
        assets.append({
            "type": "skill",
            "id": f"skill:standalone:{name}",
            "name": name,
            "path": _path_str(src),
            "plugin": None,
            "skill_origin": "standalone",
            "platforms": names,
            "harnesses": cells,
        })
    return assets


def _build_memory_assets(vault_root, dev, names):
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)          # scope 非法 → ViewScopeError（E_NOT_FOUND）
    per_tool = {t: entries_for_tool(mems, parsed, vault_root, dev, t) for t in names}
    cur_hash = shared_hash(mems)
    assets = []
    for m in mems:
        cells = {}
        for t in names:
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
            "platforms": list(names),
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
    if hub_root is not None:
        hub_root = Path(hub_root)

    loaded = platforms.enabled(dev)              # 停用的平台在这里就滤掉：不加载、不采样
    cli_names = [x.name for x in loaded
                 if x.adapter is not None and x.adapter.plugin_channel == "cli"]
    # CLI 平台的插件健康一次查齐；CLI 不可用时整块降级为 unknown，不中断 inventory。
    health_by_name = {}
    if cli_names:
        from hub.plugin_ops import plugin_health
        try:
            health_by_name = {(h.name, h.tool): h.state for h in plugin_health(vault_root, dev)}
        except Exception as e:
            warnings.append(f"{'/'.join(cli_names)} 插件健康检查不可用：{type(e).__name__}: {e}")

    ctx = InvCtx(vault_root=vault_root, dev=dev, hub_root=hub_root,
                 health_by_name=health_by_name, warnings=warnings)
    sp = _Sampled(loaded, ctx)

    plugin_assets, plugin_cells = _build_plugin_assets(ctx, sp, entries)
    plugin_skill_assets = _build_plugin_skill_assets(ctx, sp, entries, plugin_cells)
    standalone_assets = _build_standalone_skill_assets(
        ctx, sp, _standalone_sources(vault_root, hub_root))
    memory_assets = _build_memory_assets(vault_root, dev, sp.names)

    assets = plugin_assets + plugin_skill_assets + standalone_assets + memory_assets
    matrix = []
    for asset in assets:
        for tool, cell in asset.get("harnesses", {}).items():
            matrix.append({
                "asset_type": asset["type"],
                "asset_id": asset["id"],
                "asset_name": asset["name"],
                "harness": tool,
                "desired": cell["desired"],
                "actual": cell["actual"],
                "health": cell["health"],
                "control": cell["control"],
                "detail": cell["detail"],
            })

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
        "harnesses": list(sp.names),             # 本机启用的平台，消费方（GUI）据此出列
        "assets": assets,
        "matrix": matrix,
        "warnings": unique_warnings,
    }
