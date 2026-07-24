import argparse
import subprocess
import sys
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.migrate import migrate_schema, SchemaMigrationError
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.backend import (GitBackend, ConflictError, RemoteUnavailable,
                         GitlinkTracked, tracked_gitlinks)
from hub.collect import plan_deletions, preflight, run_all
from hub.collect.errors import MissingSourceError
from hub.frontmatter import FrontmatterError
from hub.writer import Writer
from hub.register import (register_skills, RegisterConflict,
                          plan_register_skills, commit_register_skills,
                          plan_hub_memory_skill, commit_hub_memory_skill,
                          check_link_collisions)
from hub.promote import (promote_skill, promote_memory, promote_memory_all,
                         PromoteConflict, PromoteMemoryConflict)
from hub.status_report import link_status, view_health
from hub.fslink import LinkError
from hub.vaultpaths import SharedSkillsEscape
from hub.hubconfig import read_config, write_config, check_config, ConfigConflict
from hub.memread import read_memory, MemoryNotInView
from hub.memview import ViewScopeError, SharedMemoryError
from hub.memwire import prepare_memory_views, commit_memory_views
from hub.textblock import BlockError
from hub.plugin_ops import (prepare_plugin_register, prepare_plugin_refresh, execute_plugin_plan,
                            plugin_health, PluginBumpNeeded, PluginRepoDirty, PluginRepoUnavailable,
                            PluginContainmentError)
from hub.plugin_manifest import PluginManifestError, PluginIdentityError
from hub.plugin_cli import CliUnavailable
from hub.vault import UnsupportedVaultVersion
from hub.plugin_migrate import (prepare_migration, execute_migration, prepare_cutover,
                                prepare_retire, execute_retire, MigrationInputError)
from hub.induction import (recover_pending, InductionError,
                           prepare_induction, execute_induction, drop_gitlink)

def _lint(vault, exempt: set[str]) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        if m.name not in exempt:
            errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _cmd_status(args) -> int:
    vault_root = Path(args.vault)
    print(GitBackend(vault_root).status(), end="")
    check = getattr(args, "check", False)
    try:
        dev = load_device(vault_root, args.host or current_host())
    except FileNotFoundError:
        if check:
            print("status --check 停止：本机没有 device.toml"); return 1   # 缺 device → 非零
        return 0                       # 本机没有 device.toml：只报 git 状态，不回归旧行为
    try:
        rows = link_status(vault_root, dev)
    except SharedSkillsEscape as e:
        print(e)
        return 1
    if rows:
        print("skill 链接:")
        for state, label in rows:
            print(f"  [{state}] {label}")
    links = tracked_gitlinks(vault_root) if check else []
    if links:
        # 插件健康判据读的是**盘上那个嵌套仓**,盘上永远是好的,所以它看不见这个坑。
        print("gitlink(空壳,别的设备 clone 拿不到内容,跑 `hub induct` 纳入):")
        for l in links:
            print(f"  [gitlink] {l}")
    if check:
        vh = view_health(vault_root, dev, _hub_root())
        print("memory 视图:")
        for state, label in vh:
            print(f"  [{state}] {label}")
        try:
            ph = plugin_health(vault_root, dev)
        except (PluginManifestError, PluginIdentityError, PluginContainmentError,
                PluginRepoUnavailable, CliUnavailable, UnsupportedVaultVersion) as e:
            print(f"plugin status 停止: {e}")
            return 1
        if ph:
            print("插件:")
            for h in ph:
                print(f"  [{h.state}] {h.name}@{h.tool}")
        return 1 if (links or any(x[0] != "ok" for x in (rows + vh))
                     or any(h.state != "ok" for h in ph)) else 0
    return 0

def _hub_root() -> Path:
    return Path(__file__).resolve().parents[1]      # 仓库根（hub/ 的上一级）

def _cmd_register(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=args.dry_run); hub_root = _hub_root()
    try:
        dev = load_device(vault_root, host)
        # ---- 预检/准备（只读；任何确定性错误在此抛、零写入）----
        to_link, ensured = plan_register_skills(vault_root, dev)
        hm_links = plan_hub_memory_skill(hub_root, dev)
        check_link_collisions(to_link, hm_links)     # 跨来源同名（如金库也有 hub-memory）→ 零写
        check_config(vault_root, host)
        writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
        plugin_plan = prepare_plugin_register(vault_root, dev)          # 预检并入 prepare
        # ---- 提交（预检全过之后才动笔）----
        commit_register_skills(to_link, w)
        commit_hub_memory_skill(hm_links, w)
        write_config(vault_root, host, hub_root, w)
        commit_memory_views(writes, oc_plan, w)
        prep = execute_plugin_plan(plugin_plan, w)                      # 提交期执行 CLI
    except (RegisterConflict, FileNotFoundError, LinkError, SharedSkillsEscape,
            ConfigConflict, ViewScopeError, SharedMemoryError, BlockError,
            PluginManifestError, PluginIdentityError, PluginContainmentError,
            CliUnavailable, UnsupportedVaultVersion) as e:
        print(e); return 1
    print(f"{'预计就位' if args.dry_run else '已就位'} {len(ensured)} 个 skill 链接 + hub-memory")
    for x in warnings:                               # opencode refuse 等：提示不阻断
        print("  ⚠", x)
    if plugin_plan.actions and not args.dry_run:
        print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
        for i, why in prep.failed:
            print(f"  ✗ {i}: {why}")
    return 0 if not prep.failed else 1

def _cmd_refresh(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    dry = getattr(args, "dry_run", False); w = Writer(dry_run=dry)
    try:
        dev = load_device(vault_root, host)
        writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
        plugin_plan = prepare_plugin_refresh(vault_root, dev)
        commit_memory_views(writes, oc_plan, w)
        prep = execute_plugin_plan(plugin_plan, w)
    except (FileNotFoundError, ViewScopeError, SharedMemoryError, BlockError,
            PluginBumpNeeded, PluginRepoDirty, PluginManifestError, PluginIdentityError,
            PluginRepoUnavailable, PluginContainmentError, CliUnavailable,
            UnsupportedVaultVersion) as e:
        print(e); return 1
    summary = {"written": len(writes), "warnings": warnings}
    print(f"memory 视图已重算: {summary}")
    for x in summary.get("warnings", []):
        print("  ⚠", x)
    if plugin_plan.actions and not dry:
        print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
    return 0 if not prep.failed else 1

def _cmd_promote(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    try:
        load_device(vault_root, host)                      # 校验 host 存在
        dest = promote_skill(vault_root, host, args.tool, args.name,
                             Writer(dry_run=args.dry_run))
    except (PromoteConflict, FileNotFoundError, ValueError, SharedSkillsEscape) as e:
        print(e)
        return 1
    print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    return 0

def _cmd_promote_memory(args) -> int:
    if bool(args.name) == bool(args.all):
        print("--name 与 --all 必须二选一"); return 1
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=args.dry_run)
    try:
        load_device(vault_root, host)
        if args.all:
            done = promote_memory_all(vault_root, host, w)
            print(f"{'预计提升' if args.dry_run else '已提升'} {len(done)} 条记忆")
        else:
            dest = promote_memory(vault_root, host, args.name, w)
            print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    except (PromoteMemoryConflict, FileNotFoundError, ValueError) as e:
        print(e); return 1
    return 0

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)

    try:
        # 先验后写(一):配了的源必须真的在。配置坏了**不是**"用户把记忆删光了",绝不能
        # 顺着镜像语义把金库清空——那是 2026-07-13 评审复现的 CRITICAL。
        preflight(dev)
        doomed = plan_deletions(vault_root, dev)
    except MissingSourceError as e:
        print("collect 停止:device.toml 里的源路径有问题\n")
        print(e)
        return 1

    try:
        # 先验后写(二):把金库里**所有**记忆先解析一遍(含 shared/ 和别的设备的)。
        #
        # 这一步过去在 run_all 的**后面**——写完才发现金库里有一条坏记忆,于是备份
        # 落了盘、collect 抛错、MEMORY.md 停在旧版本。而 SCHEMA §5 明确告诉加载器
        # "索引里没有的记忆,金库里就是没有,不必自己遍历兜底" —— 那条记忆就此从 C
        # 的视野里蒸发,尽管它明明躺在金库里;collect 和 sync 也双双卡死。
        #
        # 一条坏记忆该做的事是**在动笔之前**把这次 run 拦下来:什么都没写,索引也就
        # 永远不会陈旧。错误信息里已经点名了是哪个文件。
        load_vault(vault_root)
    except FrontmatterError as e:
        print("collect 停止:金库里有一条记忆解析不了(在写任何东西之前就停了,金库没变)\n")
        print(e)
        return 1
    if doomed and not args.yes and not args.dry_run:
        print(f"这次会从金库删掉 {len(doomed)} 条记忆(本机源里已经没有它们了):")
        for n in doomed:
            print("  -", n)
        if input("确认删除? [y/N] ").strip().lower() != "y":
            print("已取消。")
            return 1

    w = Writer(dry_run=args.dry_run)
    rep = run_all(vault_root, dev, w)

    print(f"记忆: 写 {len(rep.memory.written)} 删 {len(rep.memory.deleted)}")
    if rep.memory.skipped_sensitive:
        print(f"  跳过 sensitive: {rep.memory.skipped_sensitive}")
    for tool, names in rep.skills.items():
        print(f"{tool} skill: {len(names)} 把 {names}")
    for tool, d in rep.decl.items():
        print(f"{tool} 插件: 自有 {len(d.repos)} 个, 第三方声明 {len(d.enabled)} 条")
        if d.dirty:
            print(f"  ⚠ 有未提交改动，快照里没有这些改动: {d.dirty}")
    if rep.hits:
        print(f"\n⚠ 疑似密钥 {len(rep.hits)} 处(**只是提醒,不阻断**;"
              f"确认是真密钥就挪进 ~/.claude/secrets/ 或给记忆打 sensitive: true):")
        for h in rep.hits:
            print(f"  {h.kind}  {h.path}:{h.line}  {h.sample}")

    # 无论是不是 --dry-run 都重新算一遍索引再"写"——闸在 Writer 里,dry-run 下
    # 这行只是打印预览、不落盘,不能在这里用 if not args.dry_run 跳过整段。
    vault = load_vault(vault_root)
    _write_index(vault_root, vault, w)
    return 0

def _cmd_bootstrap(args) -> int:
    """换新机:把金库里的加载器 skill 装进各工具,然后退场。

    这是提取器铁律("只写金库")的**唯一例外**——新机上还没有 skill(skill 自己
    也在金库里),这是个鸡生蛋。bootstrap 只打破这个循环,只写各工具的 skill 目录。
    剩下的(记忆怎么装、装哪些)交给 skill 自己跑。

    即便这次写的是工具的地盘而不是金库,dry-run 的闸依旧走 Writer(复用
    copy_tree 的"先清空目标再整棵拷"语义和预览打印),不在这里手写
    if args.dry_run 分支。
    """
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    src = vault_root / "shared" / "skills"
    if not src.is_dir():
        print("金库的 shared/skills/ 是空的，没有加载器 skill 可装。")
        return 1
    w = Writer(dry_run=args.dry_run)
    installed = []
    for tool, home_key in (("claude", "CLAUDE_HOME"), ("codex", "CODEX_HOME")):
        home = dev.paths.get(home_key)
        if not home:
            continue
        for d in sorted(p for p in src.iterdir() if p.is_dir() and p.name.startswith("hub-")):
            dest = Path(home) / "skills" / d.name
            w.copy_tree(d, dest)
            installed.append(f"{tool}:{d.name}")
    verb = "预计会装" if args.dry_run else "已装"
    print(f"{verb} {len(installed)} 把加载器 skill: {installed}")
    print("接下来在各工具里跑那把 skill，它会自己去金库取记忆。")
    return 0

def _cmd_migrate_schema(args) -> int:
    try:
        migrate_schema(Path(args.vault), args.to, Writer(dry_run=args.dry_run))
    except SchemaMigrationError as e:
        print(e); return 1
    print(f"{'预计升到' if args.dry_run else '已升到'} version {args.to}")
    return 0

def _cmd_migrate_plugins(args) -> int:
    w = Writer(dry_run=args.dry_run)
    try:
        vault = Path(args.vault)
        if not w.dry_run:
            recover_pending(vault, w)      # C4：先恢复上次崩在".git 已移出"的事务，再做新 prepare
        plan = prepare_migration(Path(args.src), vault, Path(args.input))
        rep = execute_migration(plan, vault, w)
    except (MigrationInputError, InductionError, OSError, ValueError,
            subprocess.CalledProcessError) as e:
        print(e); return 1
    for warning in plan.warnings:
        print("  ⚠", warning)
    for aid, why in rep.failed:
        print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1

def _cmd_cutover_plugins(args) -> int:
    w = Writer(dry_run=args.dry_run)
    try:
        vault = Path(args.vault); dev = load_device(vault, args.host or current_host())
        plan = prepare_cutover(vault, dev, old_market=args.old_market)
        rep = execute_plugin_plan(plan, w)
    except (MigrationInputError, PluginManifestError, PluginIdentityError,
            PluginContainmentError, PluginRepoUnavailable, CliUnavailable,
            UnsupportedVaultVersion, FileNotFoundError) as e:
        print(e); return 1
    for aid, why in rep.failed:
        print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1

def _cmd_retire_plugin_sources(args) -> int:
    # 三段式 phase3：平台切换成功且验证后，才删除迁移输入声明的旧子仓。
    # 任一预检失败→零删除；只删声明的子仓，不碰外层容器。dry-run 与真跑共用 planner/executor。
    w = Writer(dry_run=args.dry_run)
    try:
        vault = Path(args.vault); dev = load_device(vault, args.host or current_host())
        plan = prepare_retire(Path(args.src), vault, Path(args.input), dev,
                              old_market=args.old_market)
        rep = execute_retire(plan, w)
    except (MigrationInputError, CliUnavailable, UnsupportedVaultVersion,
            FileNotFoundError, OSError) as e:
        print(e); return 1
    if rep.blocked:
        print("退役被拒（零删除）——先解决以下活动引用：")
        for b in rep.blocked:
            print(f"  ✗ {b}")
        return 1
    if not plan.actions:
        print("没有待退役的旧源（已删或未声明）。")
        return 0
    verb = "预计删除" if args.dry_run else "已删除"
    for a in plan.actions:
        print(f"  {verb} {a.target}")
    return 0

def _cmd_induct(args) -> int:
    """把金库里带 `.git` 的目录正规纳入父仓跟踪(存文件,不存 gitlink)。

    日常新增插件不走 migrate-plugins,以前就没有任何一条路能做这件事:
    手 `git add` 得到 gitlink 空壳,而 migrate-plugins 见到 gitlink 直接拒绝。
    """
    vault_root = Path(args.vault)
    w = Writer(dry_run=args.dry_run)
    for raw in args.path:
        rel = str(raw).replace("\\", "/").strip("/")
        if not (vault_root / rel).is_dir():
            print(f"induct 停止:{rel} 不是金库里的目录"); return 1
        try:
            plan = prepare_induction(vault_root, rel)
            if args.dry_run:
                print(f"  [dry-run] 摘 gitlink(若有)+ induct {rel}")
            else:
                if drop_gitlink(vault_root, rel):
                    print(f"  已摘掉 {rel} 的 gitlink 条目(文件留在盘上)")
                execute_induction(plan, vault_root, w)
                print(f"  已纳入 {rel}")
        except InductionError as e:
            print(f"induct 停止:{e}"); return 1
    if not args.dry_run:
        print("提示:改动还在 index 里,跑 `hub sync` 提交并推送。")
    return 0

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    b = GitBackend(vault_root)
    try:
        b.acquire()
    except RemoteUnavailable as e:          # 必须排在 ConflictError 前面(它是子类)
        print("sync 停止:够不着远端(网络/超时/认证)——不是内容冲突,自动重试过了仍不通,手工解冲突没用")
        print(e)
        return 2
    except ConflictError as e:
        print("sync 停止:git 冲突,请手工解决后 `hub sync` 重试")
        print(e)
        return 2
    vault = load_vault(vault_root)
    errs = _lint(vault, load_lint_exempt(vault_root))
    if errs:
        print("sync 停止:lint 失败(敏感/裸路径/scope):")
        for e in errs:
            print("  -", e)
        return 1
    _write_index(vault_root, vault, Writer())
    try:
        b.publish("chore(hub): sync")
    except GitlinkTracked as e:
        print("sync 停止:")
        print(e, end="")
        return 1
    except RemoteUnavailable as e:
        print("sync 停止:本地已提交,但推不上去(网络/超时/认证),自动重试过了仍不通;稍后再 `hub sync` 即可")
        print(e)
        return 2
    if getattr(args, "refresh", False):
        return _cmd_refresh(args)          # 传播 refresh 的返回码，不再吞掉失败
    print("提示：若 shared/ 有变化，运行 `hub refresh` 重算 memory 视图。")
    return 0

def _cmd_memory_read(args) -> int:
    vault = args.vault or read_config().get("vault")
    host = args.host or read_config().get("host") or current_host()
    if not vault:
        print("没有 --vault 也没有 ~/.hub/config.toml，无法定位金库"); return 1
    try:
        print(read_memory(Path(vault), host, args.tool, args.name), end="")
    except (MemoryNotInView, FileNotFoundError, ViewScopeError, SharedMemoryError) as e:
        print(e); return 1
    return 0

def _write_index(vault_root: Path, vault, w: Writer) -> None:
    w.write_text(vault_root / "MEMORY.md", render_memory_index(vault.memories, vault_root))

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", parents=[common])
    st.add_argument("--check", action="store_true", help="健康检查，不健康返回非零")
    st.set_defaults(func=_cmd_status)

    sy = sub.add_parser("sync", parents=[common])
    sy.add_argument("--refresh", action="store_true", help="成功后串联 hub refresh 并传播其返回码")
    sy.set_defaults(func=_cmd_sync)
    for name, fn in (("collect", _cmd_collect), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("--dry-run", action="store_true",
                        help="只报告会写哪些文件，一个字节都不落盘")
        sp.add_argument("--yes", action="store_true",
                        help="不询问，直接执行（含删除）")
        sp.set_defaults(func=fn)

    reg = sub.add_parser("register", parents=[common])
    reg.add_argument("--dry-run", action="store_true",
                     help="只报告会建哪些链接，一个字节都不落盘")
    reg.set_defaults(func=_cmd_register)

    rf = sub.add_parser("refresh", parents=[common])
    rf.add_argument("--dry-run", action="store_true")
    rf.set_defaults(func=_cmd_refresh)

    pro = sub.add_parser("promote", parents=[common])
    pro.add_argument("--tool", required=True, choices=["claude", "codex"],
                     help="备份区里哪个工具的 skill")
    pro.add_argument("--name", required=True, help="要提升的 skill 名（单个目录名，不含路径）")
    pro.add_argument("--dry-run", action="store_true",
                     help="只报告会提升到哪，一个字节都不落盘")
    pro.set_defaults(func=_cmd_promote)

    pm = sub.add_parser("promote-memory", parents=[common])
    pm.add_argument("--name", default=None, help="要提升的记忆名（单个，不含路径/后缀）")
    pm.add_argument("--all", action="store_true", help="批量提升本机备份区全部记忆")
    pm.add_argument("--dry-run", action="store_true")
    pm.set_defaults(func=_cmd_promote_memory)

    ind = sub.add_parser("induct", parents=[common])
    ind.add_argument("path", nargs="+", help="金库内的相对路径(如 shared/plugins/foo)")
    ind.add_argument("--dry-run", action="store_true")
    ind.set_defaults(func=_cmd_induct)

    mig = sub.add_parser("migrate-schema", parents=[common])
    mig.add_argument("--to", type=int, required=True)
    mig.add_argument("--dry-run", action="store_true")
    mig.set_defaults(func=_cmd_migrate_schema)

    mp = sub.add_parser("migrate-plugins", parents=[common])
    mp.add_argument("--src", required=True)
    mp.add_argument("--input", required=True)
    mp.add_argument("--dry-run", action="store_true")
    mp.set_defaults(func=_cmd_migrate_plugins)

    cp = sub.add_parser("cutover-plugins", parents=[common])
    cp.add_argument("--old-market", default="xu-local")
    cp.add_argument("--dry-run", action="store_true")
    cp.set_defaults(func=_cmd_cutover_plugins)

    rp = sub.add_parser("retire-plugin-sources", parents=[common])
    rp.add_argument("--src", required=True, help="旧插件仓容器目录（如 ~/.claude/plugins-dev）")
    rp.add_argument("--input", required=True, help="迁移输入（声明要退役哪些子仓）")
    rp.add_argument("--old-market", default="xu-local")
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=_cmd_retire_plugin_sources)

    mr = sub.add_parser("memory-read")
    mr.add_argument("--vault", default=None)
    mr.add_argument("--host", default=None)
    mr.add_argument("--tool", required=True, choices=["claude", "codex", "opencode"])
    mr.add_argument("--name", required=True)
    mr.set_defaults(func=_cmd_memory_read)
    return p

def _make_console_output_tolerant() -> None:
    """本机 py -3 -c "print(sys.stdout.encoding)" 报 gbk,而 gbk 编不出 ⚠(U+26A0)——
    secrets-scan/脏仓警告一旦真的命中,print() 就会以 UnicodeEncodeError 崩溃,
    唯一该报警的时刻反而看着像随机 Python bug。这里只把 errors 换成 replace(
    编不出就退化成 ?),不动 encoding——强改 encoding="utf-8" 会让 gbk 控制台上
    其余中文输出变乱码,那是比崩溃更隐蔽的坏。捕获测试用的替身 stdout 之类不支持
    reconfigure() 的场景一律跳过,不当作错误。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):
                pass

def main(argv: list[str]) -> int:
    _make_console_output_tolerant()
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
