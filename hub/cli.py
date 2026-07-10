import argparse
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths
from hub.materialize import (render_agents_md, render_claude_md,
                             select_for_target, codex_project_inner)
from hub.model import Target
from hub.backend import GitBackend, ConflictError
from hub.collect import collect_memories

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

def _lint(vault) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _cmd_process(args) -> int:
    vault_root = Path(args.vault)
    vault = load_vault(vault_root)
    errs = _lint(vault)
    if errs:
        print("lint 失败:")
        for e in errs:
            print("  -", e)
        return 1
    _write(vault_root / "MEMORY.md", render_memory_index(vault.memories))
    GitBackend(vault_root).publish("chore(hub): process 重生成索引")
    return 0

def _cmd_pull(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    vault = load_vault(vault_root)
    dev = load_device(vault_root, host)
    GitBackend(vault_root).acquire()
    for t in dev.targets:
        root = Path(t.root)
        # Codex 项目记忆块
        codex_mems = select_for_target(
            vault.memories, Target(frozenset(dev.classes), t.project, "codex"))
        proj_only = [m for m in codex_mems if f"project:{t.project}" in m.scope]
        inner = codex_project_inner(proj_only, dev.paths) if proj_only else ""
        agents_path = root / "AGENTS.md"
        existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        _write(agents_path, render_agents_md(existing, vault.rules, inner))
        claude_path = root / "CLAUDE.md"
        c_existing = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
        _write(claude_path, render_claude_md(c_existing, "hub/memory-index.md"))
    return 0

def _cmd_status(args) -> int:
    print(GitBackend(Path(args.vault)).status(), end="")
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
    errs = _lint(load_vault(vault_root))
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
    collected = collect_memories(sources, vault_root / "memory")
    print(f"collected {len(collected)} memories: {collected}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("process", _cmd_process), ("pull", _cmd_pull),
                     ("sync", _cmd_sync), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.set_defaults(func=fn)
    return p

def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
