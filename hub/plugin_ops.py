import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from hub.plugin_cli import run_cli, CliCommand, installed_plugins, marketplaces, preflight_cli
from hub.plugin_state import record, read_state
from hub.writer import Writer
from hub.vault import require_version_exactly
from hub.plugin_manifest import load_plugin_manifest, check_identity, plugin_version
from hub import platforms

@dataclass
class PluginAction:
    id: str; describe: str; depends_on: tuple = ()
    cli: object = None; state: tuple = None
    # 幂等兜底：置为某 pid 时，该动作 CLI 非零退出后，先向平台确认此 pid 确实 enabled，
    # 是则按成功处理（并发/重跑下的 already-enabled）；否则仍记失败。None = 不做确认。
    confirm_enabled: str = None

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
                if r.returncode != 0 and not _confirm_enabled_ok(a, runner):
                    rep.failed.append((a.id, r.stderr.strip() or f"exit {r.returncode}"))
                    continue
            if a.state is not None:
                record(*a.state, w)
            rep.succeeded.append(a.id)
        except Exception as e:
            rep.failed.append((a.id,str(e)))
    return rep

def _confirm_enabled_ok(a, runner) -> bool:
    # 仅当动作声明 confirm_enabled 时才生效：向平台实测该 pid 是否 enabled。
    # 真为 enabled → 把非零退出（如 already-enabled、并发重跑）按成功处理；
    # 否则返回 False → 调用方记失败。绝不无条件吞掉非零退出。
    if not a.confirm_enabled:
        return False
    try:
        inst = installed_plugins(a.cli.tool, runner=runner).get(a.confirm_enabled)
    except Exception:
        return False
    return bool(inst and inst.enabled)

# 各插件 CLI 方言必需的子命令。键是方言（平台适配器的 cli_dialect），不是平台名。
NEEDED = {"claude": ["install","uninstall","enable","disable","marketplace"],
          "codex":  ["add","remove","marketplace"]}

# 本模块只管**走官方 CLI 装卸**的平台（适配器 plugin_channel == "cli"）。opencode / dsh 不在
# 其中：它们没有插件安装通道，插件里的 skill 由各自适配器链过去或交给 loader，不经 CLI、
# 无台账、无 install/enable 状态可查——不这么滤的话 NEEDED 直接 KeyError，整条
# register/refresh/status 全挂。清单里写 platforms = [..., "opencode"] 仍然有意义：它是那两个
# 平台判断"这插件该不该给它"的依据。
#
# 目标平台 = 清单声明支持 ∩ 本机启用 ∩ 走 CLI。本机停用的平台在这里就被滤掉，**绝不能**
# 把"平台停用"当成"插件不要了"去生成禁用/卸载动作。
def _cli_platforms(entry, dev=None) -> list[str]:
    names = platforms.enabled_names(dev) if dev is not None else platforms.all_names()
    return [t for t in names if t in entry.platforms and platforms.load(t).plugin_channel == "cli"]

def _dialect(tool) -> str:
    return platforms.cli_dialect(tool)

def _needed(tool) -> list:
    d = _dialect(tool)
    if d not in NEEDED:
        raise ValueError(f"{tool} 的插件 CLI 方言 {d!r} 没有登记必需子命令")
    return NEEDED[d]

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
    d = _dialect(tool)
    if d == "codex":                          # 拒绝同名换源 → remove + add
        rm = PluginAction(f"{name}:{tool}:mktrm", f"{tool} 移除旧市场 {name}",
                          cli=CliCommand(tool, ["plugin","marketplace","remove", name]))
        add.depends_on = (rm.id,)
        return [rm, add]
    if d == "claude":
        return [add]                           # Claude 覆盖
    raise ValueError(f"{tool} 的插件 CLI 方言 {d!r} 没有换源规则")

def _ensure_installed_enabled(tool, name, pid, installed, dep_mkt):
    dep = (dep_mkt,) if dep_mkt else ()
    d = _dialect(tool)
    if d == "codex":
        return [] if pid in installed else [PluginAction(f"{name}:{tool}:add",
            f"{tool} 安装启用 {pid}", depends_on=dep, cli=CliCommand(tool,["plugin","add",pid]))]
    if d != "claude":
        raise ValueError(f"{tool} 的插件 CLI 方言 {d!r} 没有安装规则")
    if pid not in installed:
        # claude plugin install 安装即在 user scope 自动启用 —— 不再补发冗余 enable。
        # install 成功即代表 readiness（installed+enabled），退役旧身份可依赖它。
        return [PluginAction(f"{name}:{tool}:install", f"{tool} 安装启用 {pid}", depends_on=dep,
                cli=CliCommand(tool,["plugin","install",pid,"--scope","user"]))]
    if not installed[pid].enabled:
        # 已装但禁用：只补 enable。带幂等兜底：并发/重跑时若已 enabled 则确认后按成功。
        return [PluginAction(f"{name}:{tool}:enable", f"{tool} 启用 {pid}", depends_on=dep,
                cli=CliCommand(tool,["plugin","enable",pid,"--scope","user"]),
                confirm_enabled=pid)]
    return []

def _ensure_disabled(tool, name, pid, installed):
    if pid not in installed: return []
    d = _dialect(tool)
    if d == "codex":
        return [PluginAction(f"{name}:{tool}:remove", f"{tool} 移除 {pid}",
                cli=CliCommand(tool,["plugin","remove",pid]))]
    if d != "claude":
        raise ValueError(f"{tool} 的插件 CLI 方言 {d!r} 没有禁用规则")
    if installed[pid].enabled:
        return [PluginAction(f"{name}:{tool}:disable", f"{tool} 禁用 {pid}",
                cli=CliCommand(tool,["plugin","disable",pid,"--scope","user"]))]
    return []

def prepare_plugin_register(vault_root, dev, runner=None) -> PluginPlan:
    entries = load_plugin_manifest(vault_root)
    if not entries: return PluginPlan([], [])      # 未迁移：跳过、不要求 v3
    require_version_exactly(vault_root, 3)
    plats = sorted({p for e in entries for p in _cli_platforms(e, dev)})
    for tool in plats: preflight_cli(tool, _needed(tool), runner=runner)
    snap = {t: (installed_plugins(t, runner=runner), marketplaces(t, runner=runner)) for t in plats}
    actions = []
    for e in entries:
        _containment(vault_root, e.name); check_identity(vault_root, e)
        src = _plugin_source(vault_root, e.name)
        for tool in _cli_platforms(e, dev):
            installed, mkts = snap[tool]; pid = f"{e.name}@{e.name}"
            macts = _market_actions(tool, e.name, src, mkts); actions += macts
            dep = macts[-1].id if macts else None
            if e.name in dev.plugins.get(tool, []):
                actions += _ensure_installed_enabled(tool, e.name, pid, installed, dep)
            else:
                actions += _ensure_disabled(tool, e.name, pid, installed)
    return PluginPlan(actions, [])

class PluginRepoUnavailable(RuntimeError): pass

def _git_text(src, *argv) -> str:
    r = subprocess.run(["git","-C",str(src),*argv], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise PluginRepoUnavailable(
            f"{src} 不是可用的嵌套 git 仓（需要 restore/rehydrate）：{r.stderr.strip()}")
    return r.stdout.strip()

def _head_sha(src) -> str:
    return _git_text(src, "rev-parse", "HEAD")

def _is_dirty(src) -> bool:
    return bool(_git_text(src, "status", "--porcelain"))

def _reinstall_chain(tool, name, pid, inst, head, version):
    d = _dialect(tool)
    if d == "codex":
        a = PluginAction(f"{name}:{tool}:reinstall", f"{tool} 重装 {pid}",
                         cli=CliCommand(tool,["plugin","add",pid]))
        return [a, PluginAction(f"{name}:{tool}:state", f"台账 {name}/{tool}",
                                depends_on=(a.id,), state=(name,tool,head,version))]
    if d != "claude":
        raise ValueError(f"{tool} 的插件 CLI 方言 {d!r} 没有重装规则")
    u = PluginAction(f"{name}:{tool}:uninstall", f"{tool} 卸载 {pid}",
                     cli=CliCommand(tool,["plugin","uninstall",pid,"--keep-data","--scope","user"]))
    i = PluginAction(f"{name}:{tool}:install", f"{tool} 重装 {pid}", depends_on=(u.id,),
                     cli=CliCommand(tool,["plugin","install",pid,"--scope","user"]))
    chain, last = [u, i], i.id
    if not inst.enabled:                       # reinstall 会重新 enable → 恢复 disabled
        d = PluginAction(f"{name}:{tool}:redisable", f"{tool} 恢复禁用 {pid}", depends_on=(i.id,),
                         cli=CliCommand(tool,["plugin","disable",pid,"--scope","user"]))
        chain.append(d); last = d.id
    chain.append(PluginAction(f"{name}:{tool}:state", f"台账 {name}/{tool}",
                              depends_on=(last,), state=(name,tool,head,version)))
    return chain

def prepare_plugin_refresh(vault_root, dev, runner=None) -> PluginPlan:
    entries = load_plugin_manifest(vault_root)
    if not entries: return PluginPlan([], [])
    require_version_exactly(vault_root, 3)
    ledger = read_state()
    plats = sorted({p for e in entries for p in _cli_platforms(e, dev)})
    for tool in plats: preflight_cli(tool, _needed(tool), runner=runner)
    snap = {t: installed_plugins(t, runner=runner) for t in plats}
    actions = []
    for e in entries:
        _containment(vault_root, e.name)
        check_identity(vault_root, e)
        src = _plugin_source(vault_root, e.name)
        for tool in _cli_platforms(e, dev):
            installed = snap[tool]; pid = f"{e.name}@{e.name}"
            if pid not in installed: continue          # 未装→跳过（refresh 不装）
            if _is_dirty(src): raise PluginRepoDirty(f"仓 {e.name} 未提交，先提交你的 bump")
            head = _head_sha(src); version = plugin_version(vault_root, e.name)
            base = ledger.get(e.name, {}).get(tool)
            if base is None:
                # spec P5：首次不是“只记账”，必须让已安装平台真实重读一次，再建立基线。
                actions += _reinstall_chain(tool, e.name, pid, installed[pid], head, version)
                continue
            if base.sha == head: continue              # no-op
            if version == base.version:
                raise PluginBumpNeeded(
                    f"需 bump {e.name}({tool})：源码已变但 manifest 版本未升，先 bump+commit 再 refresh")
            actions += _reinstall_chain(tool, e.name, pid, installed[pid], head, version)
    return PluginPlan(actions, [])

@dataclass
class PluginHealth:
    name: str; tool: str; state: str

def _health_state(vault_root, dev, e, tool, installed, mkts, ledger) -> str:
    name = e.name; pid = f"{name}@{name}"
    src_dir = Path(vault_root)/"shared/plugins"/name
    try:
        _containment(vault_root, name)
    except PluginContainmentError:
        return "missing-source"                 # 缺失、坏链、逃逸链接都不是可用活源
    if name not in mkts: return "unregistered"
    if not _same_path(mkts[name], _plugin_source(vault_root, name)): return "source-moved"
    desired = name in dev.plugins.get(tool, [])
    present = pid in installed
    active = present and (installed[pid].enabled if platforms.load(tool).cli_has_disable else True)
    if desired and not active: return "enable-drift"
    if not desired and present: return "enable-drift"
    if present:
        try:
            if _is_dirty(src_dir): return "dirty"
            head = _head_sha(src_dir)
        except PluginRepoUnavailable:
            return "missing-source"             # 父仓 clone 后尚未 rehydrate 的目录
        base = ledger.get(name, {}).get(tool)
        if base is None: return "no-baseline"
        if head != base.sha and plugin_version(vault_root, name) == base.version:
            return "stale"
    if e.remote:
        try:
            cur = subprocess.run(["git","-C",str(src_dir),"remote","get-url","origin"],
                                 capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout.strip()
            if (e.sha and _head_sha(src_dir) != e.sha) or cur != e.remote:
                return "drift"
        except PluginRepoUnavailable:
            return "missing-source"             # 父仓 clone 后尚未 rehydrate 的目录
    return "ok"

def plugin_health(vault_root, dev, runner=None) -> list:
    entries = load_plugin_manifest(vault_root)
    if not entries: return []
    require_version_exactly(vault_root, 3)
    ledger = read_state()
    plats = sorted({p for e in entries for p in _cli_platforms(e, dev)})
    snap = {t: (installed_plugins(t, runner=runner), marketplaces(t, runner=runner)) for t in plats}
    out = []
    for e in entries:
        for tool in _cli_platforms(e, dev):          # opencode 的健康由 opencode_skill_status 报
            installed, mkts = snap[tool]
            out.append(PluginHealth(e.name, tool, _health_state(vault_root, dev, e, tool, installed, mkts, ledger)))
    return out
