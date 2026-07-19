import argparse
import sys
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.migrate import migrate_schema, SchemaMigrationError
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.backend import GitBackend, ConflictError
from hub.collect import plan_deletions, preflight, run_all
from hub.collect.errors import MissingSourceError
from hub.frontmatter import FrontmatterError
from hub.writer import Writer
from hub.register import register_skills, RegisterConflict
from hub.promote import (promote_skill, promote_memory, promote_memory_all,
                         PromoteConflict, PromoteMemoryConflict)
from hub.status_report import link_status
from hub.fslink import LinkError
from hub.vaultpaths import SharedSkillsEscape

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
    try:
        dev = load_device(vault_root, args.host or current_host())
    except FileNotFoundError:
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
    return 0

def _cmd_register(args) -> int:
    vault_root = Path(args.vault)
    try:
        dev = load_device(vault_root, args.host or current_host())
        done = register_skills(vault_root, dev, Writer(dry_run=args.dry_run))
    except (RegisterConflict, FileNotFoundError, LinkError, SharedSkillsEscape) as e:
        print(e)
        return 1
    verb = "预计就位" if args.dry_run else "已就位"
    print(f"{verb} {len(done)} 个 skill 链接")
    for d in done:
        print("  ", d)
    return 0

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

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    b = GitBackend(vault_root)
    try:
        b.acquire()
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
    b.publish("chore(hub): sync")
    return 0

def _write_index(vault_root: Path, vault, w: Writer) -> None:
    w.write_text(vault_root / "MEMORY.md", render_memory_index(vault.memories, vault_root))

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common]).set_defaults(func=_cmd_status)
    sub.add_parser("sync", parents=[common]).set_defaults(func=_cmd_sync)
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

    mig = sub.add_parser("migrate-schema", parents=[common])
    mig.add_argument("--to", type=int, required=True)
    mig.add_argument("--dry-run", action="store_true")
    mig.set_defaults(func=_cmd_migrate_schema)
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
