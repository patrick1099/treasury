import argparse
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.backend import GitBackend, ConflictError
from hub.collect import collect_memories

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
    print(GitBackend(Path(args.vault)).status(), end="")
    return 0

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    src = dev.sources.get("claude")
    sources = [Path(s) for s in (src.memory if src else [])]
    collected = collect_memories(sources, vault_root, host)
    print(f"collected {len(collected)} memories: {collected}")
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
    _write_index(vault_root, vault)
    b.publish("chore(hub): sync")
    return 0

def _write_index(vault_root: Path, vault) -> None:
    (vault_root / "MEMORY.md").write_text(
        render_memory_index(vault.memories, vault_root), encoding="utf-8", newline="\n")

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("sync", _cmd_sync)):
        sub.add_parser(name, parents=[common]).set_defaults(func=fn)
    return p

def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
