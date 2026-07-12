import argparse
import shutil
from datetime import datetime
from pathlib import Path
from hub.vault import load_vault, load_device, load_device_rules, current_host
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.materialize import (render_agents_md, render_claude_md,
                             select_for_target, codex_project_inner)
from hub.model import Target
from hub.backend import GitBackend, ConflictError
from hub.collect import collect_memories
from hub import roster

_backup_dir: Path | None = None      # 本次 pull 的备份目录，首次要备份时才建
_dry_run = False                     # True 时只报告要写什么，一个字节都不落盘

def _write(path: Path, text: str) -> None:
    """写文件：先备份原件，并沿用它原有的换行风格。

    AGENTS.md/CLAUDE.md 往往是仓库里已存在的 CRLF 文件；若一律按 LF 写回，
    git 会把它记成整文件重写。新文件仍用 LF。

    --dry-run 时在这里就地拦下——预览与真实落地共用同一条代码路径，才不会出现
    "预览其实写了真盘"这种事。
    """
    if _dry_run:
        n = len(text.encode("utf-8"))
        print(f"  [dry-run] {'改写' if path.exists() else '新建'} {path}  ({n} 字节)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = "\n"
    if path.exists():
        newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
        _backup(path)
    path.write_text(text, encoding="utf-8", newline=newline)

def _backup(path: Path) -> None:
    """覆写前把原件留一份。备份目录在 pull 开始时定，整轮共用一个时间戳。"""
    if _backup_dir is None:
        return
    _backup_dir.mkdir(parents=True, exist_ok=True)
    flat = str(path).replace(":", "").replace("\\", "-").replace("/", "-").lstrip("-")
    shutil.copy2(path, _backup_dir / flat)

def _lint(vault, exempt: set[str]) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        if m.name not in exempt:
            errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _cmd_process(args) -> int:
    vault_root = Path(args.vault)
    vault = load_vault(vault_root)
    exempt = load_lint_exempt(vault_root)
    if exempt:
        print(f"已豁免裸路径检查: {len(exempt)} 条(见 lint-exempt.txt)")
    errs = _lint(vault, exempt)
    if errs:
        print("lint 失败:")
        for e in errs:
            print("  -", e)
        return 1
    _write(vault_root / "MEMORY.md", render_memory_index(vault.memories))
    GitBackend(vault_root).publish("chore(hub): process 重生成索引", push=False)
    return 0

def _materialize_user_level(mems, dev, tool_home: Path, tool: str) -> str:
    """把某工具的用户级记忆落成**文件**,返回要放进上下文的**索引**。

    正文一条一文件写到 <工具家目录>/hub/memory/;上下文里只常驻索引——
    跟 Claude 原生记忆一个套路(索引常驻、正文按需读),而不是把全文灌进每个会话。
    """
    from hub.materialize import render_index, resolved_body, select_user_level
    from hub.frontmatter import dump_memory
    body_dir = tool_home / "hub" / "memory"
    picked = []
    for m in select_user_level(mems, dev.classes, tool):
        body = resolved_body(m, dev.paths)
        if body is None:
            print(f"  跳过 {m.name}: 本机没有它引用的符号根")
            continue
        _write(body_dir / f"{m.name}.md", dump_memory(m, body=body))
        picked.append(m)
    return render_index(picked, body_dir.as_posix())

def _cmd_pull(args) -> int:
    global _backup_dir, _dry_run
    _dry_run = getattr(args, "dry_run", False)
    vault_root = Path(args.vault)
    host = args.host or current_host()
    vault = load_vault(vault_root)
    dev = load_device(vault_root, host)
    if _dry_run:
        print(f"[dry-run] 只报告，不落盘。设备 {host}:")
    else:
        GitBackend(vault_root).acquire()

    merged = roster.load_merged(vault_root, host)
    rejected = roster.load_rejected(vault_root, host)
    waiting = roster.pending(vault.memories, host, merged, rejected)
    if waiting:
        print(f"注意: 有 {len(waiting)} 条外来记忆待审，本次不落地。"
              f"跑 `hub review --vault {args.vault} --host {host}` 过目。")
    mems = roster.visible(vault.memories, host, merged)

    claude_home = dev.paths.get("CLAUDE_HOME")
    _backup_dir = (Path(claude_home) / "hub" / "backups" /
                   datetime.now().strftime("%Y%m%d-%H%M%S")) if claude_home else None
    if _backup_dir is None:
        print("警告: 设备档案没有 CLAUDE_HOME，本次覆写不做备份。")

    from hub.materialize import (render_index, render_codex_global_agents, resolved_body,
                                 select_user_level, ensure_user_claude_import,
                                 claude_project_memory_dir, select_claude_project)
    from hub.frontmatter import dump_memory
    if claude_home:
        idx = _materialize_user_level(mems, dev, Path(claude_home), "claude")
        _write(Path(claude_home) / "hub" / "memory-index.md", idx)
        cpath = Path(claude_home) / "CLAUDE.md"
        cexist = cpath.read_text(encoding="utf-8") if cpath.exists() else ""
        _write(cpath, ensure_user_claude_import(cexist, "hub/memory-index.md"))
    codex_home = dev.paths.get("CODEX_HOME")
    if codex_home:
        # Codex 的用户级知识走 ~/.codex/AGENTS.md，不是 memories/ 目录
        idx = _materialize_user_level(mems, dev, Path(codex_home), "codex")
        ca = Path(codex_home) / "AGENTS.md"
        ca_exist = ca.read_text(encoding="utf-8") if ca.exists() else ""
        _write(ca, render_codex_global_agents(ca_exist, idx))
    rules = vault.rules + load_device_rules(vault_root, host)   # 公共规则 + 本机私有规则
    for t in dev.targets:
        root = Path(t.root)
        # Codex 项目记忆块
        codex_mems = select_for_target(
            mems, Target(frozenset(dev.classes), t.project, "codex"))
        proj_only = [m for m in codex_mems if f"project:{t.project}" in m.scope]
        inner = codex_project_inner(proj_only, dev.paths) if proj_only else ""
        agents_path = root / "AGENTS.md"
        existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        _write(agents_path, render_agents_md(existing, rules, inner))
        claude_path = root / "CLAUDE.md"
        c_existing = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
        _write(claude_path, render_claude_md(c_existing))
        if claude_home:
            mem_dir = claude_project_memory_dir(t.root, Path(claude_home))
            for m in select_claude_project(mems, t.project, dev.classes):
                _write(mem_dir / f"{m.name}.md", dump_memory(m))
    if _backup_dir is not None and _backup_dir.exists():
        print(f"覆写前的原件已备份到 {_backup_dir}")
    _backup_dir = None
    _dry_run = False
    return 0

def _cmd_status(args) -> int:
    print(GitBackend(Path(args.vault)).status(), end="")
    return 0

def _cmd_review(args) -> int:
    """列出外来记忆里还没拍板的，连正文一起打印——供人(或 AI)读完再决定。"""
    vault_root = Path(args.vault)
    host = args.host or current_host()
    vault = load_vault(vault_root)
    merged = roster.load_merged(vault_root, host)
    rejected = roster.load_rejected(vault_root, host)
    waiting = roster.pending(vault.memories, host, merged, rejected,
                             include_rejected=args.all)
    if not waiting:
        print("没有待审的外来记忆。")
        return 0
    have = {m.name for m in vault.memories if roster.is_native(m, host)}
    print(f"待审 {len(waiting)} 条(来自别的设备，尚未决定是否合并到本机):\n")
    for m in waiting:
        e = roster.entry_of(m)
        dup = "  ⚠ 本机已有同名记忆" if m.name in have else ""
        print(f"--- {e}{dup}")
        print(f"    描述: {m.description}")
        print(f"    scope: {m.scope}  type: {m.type}")
        for line in m.body.strip().splitlines():
            print(f"    | {line}")
        print()
    print("决定后:")
    print(f"  hub accept  --vault {args.vault} --host {host} <条目>...   # 只本机要")
    print(f"  hub promote --vault {args.vault} --host {host} <条目>...   # 提进公共池，所有设备都要")
    print(f"  hub reject  --vault {args.vault} --host {host} <条目>...   # 不要，且以后别再问")
    return 0

def _cmd_accept(args) -> int:
    roster.accept(Path(args.vault), args.host or current_host(), args.entries)
    print(f"已接受 {len(args.entries)} 条，下次 pull 会落地到本机。")
    return 0

def _cmd_reject(args) -> int:
    roster.reject(Path(args.vault), args.host or current_host(), args.entries)
    print(f"已拒绝 {len(args.entries)} 条，以后不再打扰"
          f"(要重新过目用 `hub review --all`)。")
    return 0

def _cmd_promote(args) -> int:
    moved = roster.promote(Path(args.vault), args.entries)
    print(f"已提进公共池 {len(moved)} 条: {moved}")
    skipped = set(args.entries) - set(moved)
    if skipped:
        print(f"跳过(文件不存在或公共池已有同名): {sorted(skipped)}")
    return 0

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    b = GitBackend(vault_root)
    try:
        b.acquire()
    except ConflictError as e:
        print("sync 停止：git 冲突，请手工解决后 `hub sync` 重试")
        print(e)
        return 2
    errs = _lint(load_vault(vault_root), load_lint_exempt(vault_root))
    if errs:
        print("sync 停止：lint 失败（敏感/裸路径/scope）：")
        for e in errs:
            print("  -", e)
        return 1
    b.publish("chore(hub): sync")
    return 0

def _cmd_bootstrap(args) -> int:
    # MVP: 首次落地 = 对已 clone 的金库执行 pull materialize
    return _cmd_pull(args)

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    sources = [Path(s) for s in dev.collect_sources]
    collected = collect_memories(sources, vault_root, host)
    print(f"collected {len(collected)} memories: {collected}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("process", _cmd_process), ("sync", _cmd_sync)):
        sub.add_parser(name, parents=[common]).set_defaults(func=fn)
    for name, fn in (("pull", _cmd_pull), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("--dry-run", action="store_true",
                        help="只报告会写哪些文件，一个字节都不落盘")
        sp.set_defaults(func=fn)
    rv = sub.add_parser("review", parents=[common])
    rv.add_argument("--all", action="store_true",
                    help="忽略拒绝名单，把拒绝过的也重新过一遍")
    rv.set_defaults(func=_cmd_review)
    for name, fn in (("accept", _cmd_accept), ("reject", _cmd_reject),
                     ("promote", _cmd_promote)):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("entries", nargs="+", help="<来源>/<记忆名>")
        sp.set_defaults(func=fn)
    return p

def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
