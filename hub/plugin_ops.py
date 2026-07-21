import os
from dataclasses import dataclass, field
from pathlib import Path
from hub.plugin_cli import run_cli, CliCommand, installed_plugins, marketplaces, preflight_cli
from hub.plugin_state import record
from hub.writer import Writer
from hub.vault import require_version_exactly
from hub.plugin_manifest import load_plugin_manifest, check_identity, plugin_version

@dataclass
class PluginAction:
    id: str; describe: str; depends_on: tuple = ()
    cli: object = None; state: tuple = None

@dataclass
class PluginPlan:
    actions: list; warnings: list

@dataclass
class PluginRunReport:
    succeeded: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)

def execute_plugin_plan(plan: PluginPlan, w: Writer, runner=None) -> PluginRunReport:
    rep = PluginRunReport()
    if w.dry_run:
        for a in plan.actions:
            print(f"  [plan] {a.describe}" + (f"  $ {a.cli.tool} {' '.join(a.cli.argv)}" if a.cli else ""))
        return rep
    for a in plan.actions:
        if any(d not in rep.succeeded for d in a.depends_on):
            rep.skipped.append(a.id); continue
        try:
            if a.cli is not None:
                r = run_cli(a.cli, runner=runner)
                if r.returncode != 0:
                    rep.failed.append((a.id, r.stderr.strip() or f"exit {r.returncode}"))
                    continue
            if a.state is not None:
                record(*a.state, w)
            rep.succeeded.append(a.id)
        except Exception as e:
            rep.failed.append((a.id,str(e)))
    return rep

NEEDED = {"claude": ["install","uninstall","enable","disable","marketplace"],
          "codex":  ["add","remove","marketplace"]}

class PluginBumpNeeded(RuntimeError): pass
class PluginRepoDirty(RuntimeError): pass
class PluginContainmentError(RuntimeError): pass

def _plugin_source(vault_root, name) -> str:
    return str((Path(vault_root)/"shared"/"plugins"/name).resolve())

def _containment(vault_root, name) -> None:
    vault = Path(vault_root).resolve()
    expected = vault/"shared"/"plugins"
    base = Path(os.path.realpath(Path(vault_root)/"shared"/"plugins"))
    real = Path(os.path.realpath(Path(vault_root)/"shared"/"plugins"/name))
    if (base != expected or not base.is_dir() or not real.is_dir()
            or os.path.commonpath([str(real), str(base)]) != str(base)):
        raise PluginContainmentError(f"shared/plugins/{name} 不是金库内真实目录")

def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    if p.startswith("//?/"): p = p[4:]
    return os.path.normcase(os.path.normpath(p))
def _same_path(a, b) -> bool: return _norm(a) == _norm(b)

def _market_actions(tool, name, src, mkts):
    cur = mkts.get(name)
    if cur is not None and _same_path(cur, src): return []
    add = PluginAction(f"{name}:{tool}:mktadd", f"{tool} 注册/换源市场 {name}",
                       cli=CliCommand(tool, ["plugin","marketplace","add", src]))
    if cur is None: return [add]
    if tool == "codex":                       # 拒绝同名换源 → remove + add
        rm = PluginAction(f"{name}:{tool}:mktrm", f"codex 移除旧市场 {name}",
                          cli=CliCommand("codex", ["plugin","marketplace","remove", name]))
        add.depends_on = (rm.id,)
        return [rm, add]
    return [add]                               # Claude 覆盖

def _ensure_installed_enabled(tool, name, pid, installed, dep_mkt):
    dep = (dep_mkt,) if dep_mkt else ()
    if tool == "codex":
        return [] if pid in installed else [PluginAction(f"{name}:codex:add",
            f"codex 安装启用 {pid}", depends_on=dep, cli=CliCommand("codex",["plugin","add",pid]))]
    if pid not in installed:
        install = PluginAction(f"{name}:claude:install", f"claude 安装 {pid}", depends_on=dep,
                cli=CliCommand("claude",["plugin","install",pid,"--scope","user"]))
        enable = PluginAction(f"{name}:claude:enable", f"claude 启用 {pid}",
                depends_on=(install.id,),
                cli=CliCommand("claude",["plugin","enable",pid,"--scope","user"]))
        return [install, enable]
    if not installed[pid].enabled:
        return [PluginAction(f"{name}:claude:enable", f"claude 启用 {pid}", depends_on=dep,
                cli=CliCommand("claude",["plugin","enable",pid,"--scope","user"]))]
    return []

def _ensure_disabled(tool, name, pid, installed):
    if pid not in installed: return []
    if tool == "codex":
        return [PluginAction(f"{name}:codex:remove", f"codex 移除 {pid}",
                cli=CliCommand("codex",["plugin","remove",pid]))]
    if installed[pid].enabled:
        return [PluginAction(f"{name}:claude:disable", f"claude 禁用 {pid}",
                cli=CliCommand("claude",["plugin","disable",pid,"--scope","user"]))]
    return []

def prepare_plugin_register(vault_root, dev, runner=None) -> PluginPlan:
    entries = load_plugin_manifest(vault_root)
    if not entries: return PluginPlan([], [])      # 未迁移：跳过、不要求 v3
    require_version_exactly(vault_root, 3)
    plats = sorted({p for e in entries for p in e.platforms})
    for tool in plats: preflight_cli(tool, NEEDED[tool], runner=runner)
    snap = {t: (installed_plugins(t, runner=runner), marketplaces(t, runner=runner)) for t in plats}
    actions = []
    for e in entries:
        _containment(vault_root, e.name); check_identity(vault_root, e)
        src = _plugin_source(vault_root, e.name)
        for tool in e.platforms:
            installed, mkts = snap[tool]; pid = f"{e.name}@{e.name}"
            macts = _market_actions(tool, e.name, src, mkts); actions += macts
            dep = macts[-1].id if macts else None
            if e.name in dev.plugins.get(tool, []):
                actions += _ensure_installed_enabled(tool, e.name, pid, installed, dep)
            else:
                actions += _ensure_disabled(tool, e.name, pid, installed)
    return PluginPlan(actions, [])
