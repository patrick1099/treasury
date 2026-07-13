"""脚手架:建一个空金库(两区结构 + SCHEMA.md)。"""
from pathlib import Path
from hub.schema_md import SCHEMA_MD
from hub.writer import Writer

_SHARED_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CLAUDE_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CODEX_DIRS = ["skills", "hooks", "chats"]

_DEVICE_TOML = """# 本机档案。缺的项 = 本机没有那个工具/那个源，不是错误。
class = ["work"]
projects = []

[paths]
VAULT = "<金库路径>"
CLAUDE_HOME = "<~/.claude 的绝对路径>"
CODEX_HOME = "<~/.codex 的绝对路径>"

[sources.claude]
memory = ["<~/.claude/projects/<工程编码>/memory>"]
skills = "<~/.claude/skills>"
plugin_repos = "<~/.claude/plugins-dev>"   # 自己写的插件仓所在目录
settings = "<~/.claude/settings.json>"
agents = "<~/.claude/CLAUDE.md>"

[sources.codex]
skills = "<~/.codex/skills>"
settings = "<~/.codex/config.toml>"
agents = "<~/.codex/AGENTS.md>"
# 注：~/.codex/memories/ 不收 —— 生成态，见 SCHEMA.md
"""

class VaultNotEmptyError(RuntimeError):
    pass

def scaffold(root: Path, host: str, w: Writer, force: bool = False) -> None:
    """在 root 建一个空金库。root 非空时拒绝动手,除非 force=True。

    这道闸是必须的:scaffold 无条件覆盖写 device.toml,而 device.toml 里是用户
    手填的源路径。往一个已经配好的金库上再跑一次 scaffold,会把那些路径**静默**
    换回 <占位> 模板——用户的配置就没了,还不报错。
    """
    root = Path(root)
    if not force and root.is_dir():
        existing = sorted(p.name for p in root.iterdir())
        if existing:
            raise VaultNotEmptyError(
                f"{root} 不是空目录(已有 {existing[:5]}{' …' if len(existing) > 5 else ''})。"
                f"scaffold 会覆盖写 device.toml,把你手填的源路径换回占位符。"
                f"确实要重建就加 --force。")
    w.write_text(root / "vault.toml", "version = 1\n")
    w.write_text(root / "SCHEMA.md", SCHEMA_MD)
    w.write_text(root / "lint-exempt.txt",
                 "# 一行一个记忆 name：豁免裸路径检查（scope 与 sensitive 仍硬拦）\n")
    for d in _SHARED_DIRS:
        w.write_text(root / "shared" / d / ".gitkeep", "")
    for d in _CLAUDE_DIRS:
        w.write_text(root / host / "claude" / d / ".gitkeep", "")
    for d in _CODEX_DIRS:
        w.write_text(root / host / "codex" / d / ".gitkeep", "")
    w.write_text(root / host / "device.toml", _DEVICE_TOML)

def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="hub-scaffold", description="建一个空金库(两区结构)")
    p.add_argument("vault", help="金库目录(不存在或为空)")
    p.add_argument("host", help="本机设备名，通常是 socket.gethostname().lower()")
    p.add_argument("--force", action="store_true",
                   help="目标非空也照建。会覆盖 device.toml——你手填的源路径会变回占位符")
    p.add_argument("--dry-run", action="store_true", help="只报告会写哪些文件，一个字节都不落盘")
    args = p.parse_args(argv)
    try:
        scaffold(Path(args.vault), args.host, Writer(dry_run=args.dry_run), force=args.force)
    except VaultNotEmptyError as e:
        print(e)
        return 1
    print(f"金库已建在 {args.vault}，设备 {args.host}。先填 device.toml 里的 <…> 占位。")
    return 0

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
