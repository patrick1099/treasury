#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一入口:一条命令同时迁移 Claude Code 和 Codex 的个人数据。

底层是两个独立工具,各自仍可单独使用:
  claude_migrate.py  ——  ~/.claude(skills/memory/聊天记录/plugins/MCP)
  codex_migrate.py   ——  ~/.codex(sessions/state/memories/config/skills)

用法:
  py -3 migrate.py status
  py -3 migrate.py export [--out-dir DIR] [--include-logs] [--no-history] [--only claude|codex]
  py -3 migrate.py import [--claude ZIP] [--codex ZIP] [--remap-user OLD NEW]
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CODEX_DIR = HOME / ".codex"
CLAUDE_TOOL = HERE / "claude_migrate.py"
CODEX_TOOL = HERE / "codex_migrate.py"


def run(tool, tool_args):
    """调用某个子工具,回显其输出,返回退出码。"""
    cmd = [sys.executable, str(tool), *tool_args]
    print(f"\n$ {Path(tool).name} {' '.join(tool_args)}")
    result = subprocess.run(cmd)
    return result.returncode


def dir_size_mb(path):
    if not path.exists():
        return None
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1024 / 1024


def cmd_status(_args):
    for label, path in (("Claude Code", CLAUDE_DIR), ("Codex", CODEX_DIR)):
        size = dir_size_mb(path)
        if size is None:
            print(f"  {label:<12} 未安装 ({path} 不存在)")
        else:
            print(f"  {label:<12} {path}  约 {size:.0f} MB")
    return 0


def cmd_export(args):
    out_dir = Path(args.out_dir).resolve() if args.out_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rc = 0

    if args.only in (None, "claude"):
        if CLAUDE_DIR.exists():
            a = ["export", "--out", str(out_dir / f"claude-backup-{ts}.zip")]
            if args.no_history:
                a.append("--no-history")
            rc |= run(CLAUDE_TOOL, a)
        else:
            print(f"  跳过 Claude:{CLAUDE_DIR} 不存在")

    if args.only in (None, "codex"):
        if CODEX_DIR.exists():
            a = ["export", "--out", str(out_dir / f"codex-backup-{ts}.zip"), "--force"]
            if args.include_logs:
                a.append("--include-logs")
            rc |= run(CODEX_TOOL, a)
        else:
            print(f"  跳过 Codex:{CODEX_DIR} 不存在")

    print(f"\n导出目录: {out_dir}")
    print("两者都不含登录凭证,新机导入后各自重新登录 (/login)。")
    return rc


def cmd_import(args):
    if not args.claude and not args.codex:
        print("ERROR: 至少指定 --claude ZIP 或 --codex ZIP 之一", file=sys.stderr)
        return 2
    rc = 0

    if args.claude:
        a = ["import", str(Path(args.claude).resolve())]
        if args.remap_user:
            a += ["--remap-user", args.remap_user[0], args.remap_user[1]]
        rc |= run(CLAUDE_TOOL, a)

    if args.codex:
        a = ["import", "--from", str(Path(args.codex).resolve())]
        if args.remap_user:
            a += ["--remap-user", args.remap_user[0], args.remap_user[1]]
        rc |= run(CODEX_TOOL, a)

    print("\n完成。两边都记得在新机重新登录。")
    return rc


def main():
    p = argparse.ArgumentParser(
        prog="migrate",
        description="同时迁移 Claude Code 和 Codex 的个人数据",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("status", help="查看本机两者的安装情况与体积")
    ps.set_defaults(func=cmd_status)

    pe = sub.add_parser("export", help="导出两者")
    pe.add_argument("--out-dir", help="输出目录,默认当前目录")
    pe.add_argument("--include-logs", action="store_true", help="Codex 一并打包 logs_*.sqlite")
    pe.add_argument("--no-history", action="store_true", help="Claude 不含聊天记录")
    pe.add_argument("--only", choices=["claude", "codex"], help="只导出其中一个")
    pe.set_defaults(func=cmd_export)

    pi = sub.add_parser("import", help="导入两者(各给一个 zip)")
    pi.add_argument("--claude", help="Claude 迁移包 zip")
    pi.add_argument("--codex", help="Codex 迁移包 zip")
    pi.add_argument(
        "--remap-user", nargs=2, metavar=("OLD", "NEW"),
        help="新机用户名不同时,改写旧用户名(Claude 改会话目录名+jsonl;Codex 改会话文件+sqlite 路径列)",
    )
    pi.set_defaults(func=cmd_import)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
