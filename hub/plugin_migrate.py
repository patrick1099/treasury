import hashlib, json, shutil, stat, subprocess, tomllib
from dataclasses import dataclass, field
from pathlib import Path
from hub.induction import prepare_induction, execute_induction
from hub.snapshot import is_git_repo
from hub.writer import Writer
from hub.plugin_ops import (prepare_plugin_register, PluginAction, PluginPlan, _same_path,
                            _plugin_source, _head_sha, _norm)
from hub.plugin_manifest import load_plugin_manifest, plugin_version
from hub.plugin_cli import CliCommand, installed_plugins, marketplaces, CliUnavailable

# os 用于 lexists/realpath/commonpath 的容器与源目录 containment 预检。
import os

@dataclass
class MigrationAction:
    id: str; kind: str; describe: str
    src: str = ""; dest: str = ""; text: str = ""; depends_on: tuple = ()

@dataclass
class MigrationPlan:
    actions: list; warnings: list; needs_author: list

class MigrationInputError(RuntimeError): pass

def load_migration_input(path) -> dict:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, body in raw.items():
        if "platforms" not in body:
            raise MigrationInputError(f"{name}: 迁移输入缺 platforms")
        platforms = list(body["platforms"]); enabled = list(body.get("enabled", []))
        if not platforms or any(t not in {"claude","codex"} for t in platforms):
            raise MigrationInputError(f"{name}: platforms 必须是非空 claude/codex 列表")
        if any(t not in platforms for t in enabled):
            raise MigrationInputError(f"{name}: enabled 必须是 platforms 的子集")
        out[name] = {"platforms": platforms, "enabled": enabled}
    return out

def _q(lst): return "[" + ", ".join(f'"{x}"' for x in lst) + "]"

def _market_ready(src: Path, name: str) -> bool:
    try:
        m = json.loads((src/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        p = json.loads((src/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        rows = m.get("plugins") or []
        return (m.get("name") == name and len(rows) == 1
                and rows[0].get("name") == name and rows[0].get("source") == "."
                and p.get("name") == name and bool(p.get("version")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return False

def _index_modes(vault_root: Path, rel: str) -> list[str]:
    r=subprocess.run(["git","-C",str(vault_root),"ls-files","-s","--",rel],
                     capture_output=True,text=True)
    if r.returncode!=0:
        raise MigrationInputError(f"父金库 git index 不可读: {r.stderr.strip()}")
    return [line.split()[0] for line in r.stdout.splitlines() if line.strip()]

def prepare_migration(src_dir, vault_root, input_path) -> MigrationPlan:
    src_dir = Path(src_dir); vault_root = Path(vault_root)
    inp = load_migration_input(input_path)
    src_real=src_dir.resolve(); vault_real=vault_root.resolve()
    shared=vault_root/"shared"; plugins=shared/"plugins"
    if ((os.path.lexists(shared) and Path(os.path.realpath(shared)) != vault_real/"shared")
            or (os.path.lexists(plugins)
                and Path(os.path.realpath(plugins)) != vault_real/"shared"/"plugins")):
        raise MigrationInputError("shared/plugins 容器是链接/逃逸路径，拒绝迁移")
    src_names={p.name for p in src_dir.iterdir() if p.is_dir() and is_git_repo(p)}
    dest_root=vault_root/"shared/plugins"
    dest_names=({p.name for p in dest_root.iterdir() if p.is_dir() and is_git_repo(p)}
                if dest_root.is_dir() else set())
    known=src_names|dest_names
    if known != set(inp):
        raise MigrationInputError(
            f"迁移输入与源/目标仓集合不一致：未声明={sorted(known-set(inp))}，不存在={sorted(set(inp)-known)}")
    actions, warnings, needs_author = [], [], []
    mf_lines, enabled_by_tool = [], {}
    def _valid_repo(active, base) -> bool:
        real=active.resolve()
        return not (active.is_symlink() or not active.is_dir() or not is_git_repo(active)
                    or os.path.commonpath([str(real),str(base)]) != str(base))
    def _induct_only(name, rel):
        # dest 已在:只确保 induct(幂等);父仓已是 gitlink 则拒绝
        modes=_index_modes(vault_root,rel)
        if "160000" in modes:
            raise MigrationInputError(f"{name}: 父仓 index 仍是 gitlink，拒绝继续")
        if modes:                                 # 已跟踪:仍 induct 一次以幂等收敛(git add no-op)
            actions.append(MigrationAction(f"{name}:induct","induct",f"induct {name}(幂等)",dest=rel))
        else:                                     # 上次只 copy 未 induct;本次从 induction 继续
            actions.append(MigrationAction(f"{name}:induct","induct",f"induct {name}",dest=rel))
    for name, spec in inp.items():
        s=src_dir/name; rel=f"shared/plugins/{name}"; dest=vault_root/rel
        in_src=name in src_names; in_dest=name in dest_names
        if in_src and in_dest:
            # 三段式:phase1 不删源 → src+dest 共存是重跑常态。内容+身份一致→幂等(只 induct);
            # 不同→冲突失败、零删除(缺陷 dcea199 边界 2)。
            if not _valid_repo(s, src_real) or not _valid_repo(dest, dest_root.resolve()):
                raise MigrationInputError(f"{name}: 当前仓不是预期容器内真实 git 目录")
            if not _same_repo(s, dest):
                raise MigrationInputError(
                    f"{name}: plugins-dev 与 shared/plugins 两份内容/Git 身份不一致，冲突拒绝（零删除）")
            if not _market_ready(dest, name):
                needs_author.append(name)
            _induct_only(name, rel)
        elif in_src:
            if not _valid_repo(s, src_real):
                raise MigrationInputError(f"{name}: 当前仓不是预期容器内真实 git 目录")
            if not _market_ready(s, name):
                needs_author.append(name)
            cp=MigrationAction(f"{name}:copy","copy",f"复制 {name} → {rel}（保留旧源）",
                               src=str(s),dest=str(dest))
            actions += [cp,MigrationAction(f"{name}:induct","induct",f"induct {name}",
                                           dest=rel,depends_on=(cp.id,))]
        else:                                     # not in_src and in_dest
            if not _valid_repo(dest, dest_root.resolve()):
                raise MigrationInputError(f"{name}: 当前仓不是预期容器内真实 git 目录")
            if not _market_ready(dest, name):
                needs_author.append(name)
            _induct_only(name, rel)
        mf_lines.append(f"[{name}]\nplatforms = {_q(spec['platforms'])}\n")
        for tool in spec["enabled"]:
            enabled_by_tool.setdefault(tool, []).append(name)
    actions.append(MigrationAction("write:manifest", "write", "写 shared/plugins/manifest.toml",
                   dest=str(vault_root/"shared/plugins/manifest.toml"), text="\n".join(mf_lines)))
    dev_lines = "".join(f"[plugins.{t}]\nenabled = {_q(sorted(v))}\n"
                        for t, v in sorted(enabled_by_tool.items()))
    actions.append(MigrationAction("write:device-snippet", "write",
                   "写 device 的 [plugins.*] 建议片段（作者审后并入 device.toml）",
                   dest=str(vault_root/"plugins-device-snippet.toml"), text=dev_lines))
    return MigrationPlan(actions, warnings, needs_author)

@dataclass
class MigrationReport:
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)

def _file_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def _tree_manifest(root: Path, prune_git: bool=False) -> list:
    """不跟随目录链接；比较相对路径、对象类型和文件内容/链接目标。
    prune_git=True 时跳过整个 .git 子树（内容比对用，别去 SHA 整座对象库）。"""
    root=Path(root); rows=[]
    for cur, dirs, files in os.walk(root, followlinks=False):
        if prune_git and ".git" in dirs:
            dirs.remove(".git")              # 不下降、也不记这一行
        curp=Path(cur)
        for name in sorted(dirs+files):
            p=curp/name; rel=p.relative_to(root).as_posix()
            if p.is_symlink(): rows.append((rel,"link",os.readlink(p)))
            elif p.is_dir(): rows.append((rel,"dir",""))
            else: rows.append((rel,"file",_file_sha256(p)))
    return sorted(rows)

def _git_out(cwd, *a):
    r=subprocess.run(["git","-C",str(cwd),*a], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode==0 else None

def _content_manifest_no_git(root: Path) -> list:
    return _tree_manifest(root, prune_git=True)

def _same_repo(a: Path, b: Path) -> bool:
    """两份是否内容+Git 身份一致(phase1 重跑幂等判据)。
    身份=HEAD sha + origin remote 都一致(两边都无 remote 也算一致);内容=去 .git 的树清单一致。
    任一不同即视为漂移 → 调用方冲突拒绝、零删除。
    注:未出生 HEAD(无提交)时 rev-parse 失败→_git_out 返 None→按漂移拒绝(安全方向;
    真实插件仓总有提交,不会走到这)。"""
    ha, hb = _git_out(a,"rev-parse","HEAD"), _git_out(b,"rev-parse","HEAD")
    if ha is None or hb is None or ha != hb:
        return False
    if _git_out(a,"remote","get-url","origin") != _git_out(b,"remote","get-url","origin"):
        return False
    return _content_manifest_no_git(a) == _content_manifest_no_git(b)

def _under(path: str, base: Path) -> bool:
    if not path: return False
    p=_norm(path); b=_norm(str(base))            # _norm 用 normpath → 原生分隔符,拼 os.sep
    return p==b or p.startswith(b + os.sep)

def _onexc_writable(func, p, exc):
    # git 在 Windows 上把 .git/objects 下的对象文件设为只读，裸 shutil.rmtree 删不动；
    # 沿用 tests/hub/test_plugin_refresh.py 里已有的同款 chmod 后重试写法。
    os.chmod(p, stat.S_IWRITE); func(p)

def _clear_readonly(root: Path) -> None:
    """删源前把整棵树改可写：同一个只读对象文件的问题会挡住 Writer.rmtree 里那句裸
    shutil.rmtree（它是唯一写入口，不在这里改它的行为），所以删除前先在这一层解只读。"""
    for cur, dirs, files in os.walk(root):
        for name in dirs + files:
            p = os.path.join(cur, name)
            try: os.chmod(p, stat.S_IWRITE)
            except OSError: pass
    try: os.chmod(root, stat.S_IWRITE)
    except OSError: pass

def _do_copy(src, dest, w: Writer):
    # 三段式 phase1：只复制 + 校验，**绝不删源**。旧源退役由 phase3
    # retire-plugin-sources 在平台切换成功后显式做（缺陷 dcea199：切指向前不删旧市场根）。
    src, dest = Path(src), Path(dest)
    if w.dry_run:
        print(f"  [dry-run] 复制 {src} → {dest} + 校验（保留旧源）"); return
    if dest.exists():
        raise MigrationInputError(f"目标已存在 {dest}，拒绝覆盖")
    dest.parent.mkdir(parents=True, exist_ok=True)
    before=_tree_manifest(src)
    shutil.copytree(src, dest, symlinks=True)       # 含 .git；保留链接；跨盘安全
    if before != _tree_manifest(dest):
        try: shutil.rmtree(dest, onexc=_onexc_writable)   # 尽力清掉坏副本
        except OSError: pass
        raise MigrationInputError(f"{src}→{dest} 复制校验失败（路径/类型/SHA-256 不同）")

def execute_migration(plan, vault_root, w: Writer) -> MigrationReport:
    rep = MigrationReport()
    if plan.needs_author:
        rep.failed.append(("preflight:needs-author",
                           "缺 market-of-one: " + ", ".join(sorted(plan.needs_author))))
        return rep
    done=set()
    for a in plan.actions:
        missing=[d for d in a.depends_on if d not in done]
        if missing:
            rep.failed.append((a.id,"未满足依赖: " + ", ".join(missing))); break
        try:
            if a.kind == "copy":
                _do_copy(a.src, a.dest, w)
            elif a.kind == "induct":
                execute_induction(prepare_induction(vault_root, a.dest), vault_root, w)
            elif a.kind == "write":
                w.write_text_atomic(Path(a.dest), a.text)
            rep.done.append(a.id); done.add(a.id)
        except Exception as e:
            rep.failed.append((a.id, str(e))); break    # 强序列：失败即停（phase1 从不删源，旧源完好）
    return rep

# ── phase3：退役旧源(retire-plugin-sources) ────────────────────────────────
# 三段式的第三阶段：平台已通过官方 CLI 切到 shared 且验证成功后，才删除迁移输入声明的旧子仓。
# 全量预检两平台已无旧 marketplace/source/身份引用、新身份均装且启用策略正确；任一失败→零删除。
# 只删声明的旧子仓 src_dir/<name>，绝不删外层容器及其独有文档。dry-run 与真跑共用此 planner/executor。

@dataclass
class RetireAction:
    id: str; describe: str; target: str

@dataclass
class RetirePlan:
    actions: list; blocks: list

@dataclass
class RetireReport:
    done: list = field(default_factory=list)
    blocked: list = field(default_factory=list)

def prepare_retire(src_dir, vault_root, input_path, dev, runner=None,
                   old_market="xu-local") -> RetirePlan:
    src_dir=Path(src_dir)
    inp=load_migration_input(input_path)
    tools=sorted({t for spec in inp.values() for t in spec["platforms"]})
    blocks=[]
    snap={}
    for tool in tools:                            # 只走官方 CLI 读实时态,绝不读 config 猜
        try:
            snap[tool]=(installed_plugins(tool,runner=runner), marketplaces(tool,runner=runner))
        except CliUnavailable as e:               # 读不到(如 Codex 悬空市场硬失败)→不敢删
            blocks.append(f"{tool}: 平台状态不可读，拒绝退役（{e}）")
    if blocks:
        return RetirePlan([], blocks)
    for tool in tools:
        installed, mkts = snap[tool]
        if old_market in mkts:
            blocks.append(f"{tool}: 旧聚合市场 {old_market} 仍注册")
        for mname, mpath in mkts.items():
            if _under(mpath, src_dir):
                blocks.append(f"{tool}: 市场 {mname} 仍指向旧源目录（{mpath}）")
        for pid, inst in installed.items():
            if pid.endswith("@"+old_market):
                blocks.append(f"{tool}: 旧身份 {pid} 仍安装")
            if inst.source_path and _under(inst.source_path, src_dir):
                blocks.append(f"{tool}: {pid} 来源仍在旧源目录（{inst.source_path}）")
    for name, spec in inp.items():                # 新身份均装且启用策略正确
        pid=f"{name}@{name}"
        for tool in spec["platforms"]:
            installed,_=snap[tool]
            desired=name in dev.plugins.get(tool, [])
            present=pid in installed
            active=present and (installed[pid].enabled if tool=="claude" else True)
            if desired and not active:
                blocks.append(f"{tool}: 新身份 {pid} 未按期望安装/启用，退役被拒")
            if not desired and present:
                blocks.append(f"{tool}: {pid} 应禁用/不装但仍在，退役被拒")
    if blocks:
        return RetirePlan([], blocks)
    actions=[RetireAction(f"{name}:retire-src", f"删除旧源 {src_dir/name}", str(src_dir/name))
             for name in inp if (src_dir/name).exists()]   # 已删则跳过(幂等)
    return RetirePlan(actions, [])

def execute_retire(plan: RetirePlan, w: Writer) -> RetireReport:
    rep=RetireReport()
    if plan.blocks:                               # 任一预检失败→零删除
        rep.blocked=list(plan.blocks); return rep
    for a in plan.actions:
        tgt=Path(a.target)
        if not w.dry_run:
            _clear_readonly(tgt)                  # Windows 只读 .git 对象,删前解只读(dry 不碰)
        w.rmtree(tgt)                             # dry-run 安全:打印+零写
        rep.done.append(a.id)
    return rep

def _drop_policy_actions(actions, name, tool):
    drop={f"{name}:{tool}:enable",f"{name}:{tool}:disable"}
    return [a for a in actions if a.id not in drop]

def _cutover_reinstall(tool, name, desired, inst, dep, vault_root):
    pid=f"{name}@{name}"; head=_head_sha(_plugin_source(vault_root,name))
    version=plugin_version(vault_root,name); deps=(dep,) if dep else ()
    if tool=="codex":
        if not desired: return []              # register 的 remove 已收敛“不安装”策略
        add=PluginAction(f"{name}:codex:cutover-reinstall",f"codex 换源后重装 {pid}",
            depends_on=deps,cli=CliCommand("codex",["plugin","add",pid]))
        state=PluginAction(f"{name}:codex:cutover-state",f"台账 {name}/codex",
            depends_on=(add.id,),state=(name,"codex",head,version))
        return [add,state]
    uninstall=PluginAction(f"{name}:claude:cutover-uninstall",f"claude 换源前卸载 {pid}",
        depends_on=deps,cli=CliCommand("claude",["plugin","uninstall",pid,"--keep-data","--scope","user"]))
    install=PluginAction(f"{name}:claude:cutover-install",f"claude 从新源重装 {pid}",
        depends_on=(uninstall.id,),cli=CliCommand("claude",["plugin","install",pid,"--scope","user"]))
    # claude plugin install 装即自动启用：desired 时不补冗余 enable，readiness=cutover-install；
    # 仅当期望禁用时才补一条 cutover-disable。
    chain=[uninstall,install]; last=install.id
    if not desired:
        disable=PluginAction(f"{name}:claude:cutover-disable",f"claude 重装后disable {pid}",
            depends_on=(install.id,),cli=CliCommand("claude",["plugin","disable",pid,"--scope","user"]))
        chain.append(disable); last=disable.id
    chain.append(PluginAction(f"{name}:claude:cutover-state",f"台账 {name}/claude",
        depends_on=(last,),state=(name,"claude",head,version)))
    return chain

def _ready_dep(actions, name, tool):
    # 返回本次真正建立 readiness（installed+enabled）的动作 id，供退役旧身份依赖。
    # 不再固定挂在 :enable 上——install 装即启用即代表就绪；若预检时新身份已 ready，
    # 则本轮无对应动作，返回 None（退役无需虚假依赖，可无条件执行）。
    prefix=f"{name}:{tool}:"
    preferred=("cutover-install","cutover-reinstall","install","enable","add")
    for verb in preferred:
        found=[a.id for a in actions if a.id==prefix+verb]
        if found: return found[-1]
    return None

def prepare_cutover(vault_root, dev, runner=None, old_market="xu-local") -> PluginPlan:
    entries=load_plugin_manifest(vault_root)
    if not entries:
        raise MigrationInputError("shared/plugins/manifest.toml 为空或不存在，不能执行 cutover")
    tools=sorted({tool for e in entries for tool in e.platforms})
    snaps={tool:(installed_plugins(tool,runner=runner),marketplaces(tool,runner=runner))
           for tool in tools}
    reg=prepare_plugin_register(vault_root,dev,runner=runner)
    actions=list(reg.actions)

    # 同身份换源必须强制重装；单纯 marketplace add/remove 不会更新已装 cache。
    for e in entries:
        src=_plugin_source(vault_root,e.name); pid=f"{e.name}@{e.name}"
        for tool in e.platforms:
            installed,mkts=snaps[tool]
            if pid not in installed or e.name not in mkts or _same_path(mkts[e.name],src):
                continue
            desired=e.name in dev.plugins.get(tool,[])
            actions=_drop_policy_actions(actions,e.name,tool)
            dep=f"{e.name}:{tool}:mktadd"
            actions += _cutover_reinstall(tool,e.name,desired,installed[pid],dep,vault_root)

    known={e.name for e in entries}
    for tool in tools:
        installed,mkts=snaps[tool]
        old_ids=[pid for pid in installed if pid.endswith("@"+old_market)]
        unknown=sorted(pid for pid in old_ids if pid.split("@",1)[0] not in known)
        if unknown:
            raise MigrationInputError(
                f"{tool}: {old_market} 仍有 manifest 外已装身份 {unknown}，拒绝删除市场")
        retired=[]
        for oldpid in old_ids:
            name=oldpid.split("@",1)[0]; desired=name in dev.plugins.get(tool,[])
            dep=(_ready_dep(actions,name,tool)
                 or (f"{name}:{tool}:mktadd"
                     if any(a.id==f"{name}:{tool}:mktadd" for a in actions) else None))
            newpid=f"{name}@{name}"
            if desired and newpid not in installed and dep is None:
                raise MigrationInputError(f"{tool}: {name} 新身份未规划成功，不能退役 {oldpid}")
            argv=(["plugin","uninstall",oldpid,"--keep-data","--scope","user"] if tool=="claude"
                  else ["plugin","remove",oldpid])
            a=PluginAction(f"{name}:{tool}:retire-old",f"{tool} 退役旧身份 {oldpid}",
                depends_on=((dep,) if dep else ()),cli=CliCommand(tool,argv))
            actions.append(a); retired.append(a.id)
        if old_market in mkts:
            # 删除聚合市场依赖本平台此前所有新市场/新身份/旧身份动作；任一失败都必须 skip。
            market_deps=tuple(dict.fromkeys(
                [a.id for a in actions if f":{tool}:" in a.id] + retired))
            actions.append(PluginAction(f"{tool}:retire-market:{old_market}",
                f"{tool} 退役旧聚合市场 {old_market}",depends_on=market_deps,
                cli=CliCommand(tool,["plugin","marketplace","remove",old_market])))
    return PluginPlan(actions,reg.warnings)
