#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
claude_migrate.py —— 迁移 Claude Code 的全部个人数据(换电脑用)

只用标准库,Windows 上跑: py -3 claude_migrate.py <命令>

迁移范围(白名单,见 ALLOWLIST):
  settings.json / history.jsonl / skills/ / projects/(含 memory 与全部聊天记录)
  plugins 的清单 json + marketplaces/(让插件离线可用)
  .claude.json 里只抽 mcpServers(不整文件覆盖)

绝不迁:
  .credentials.json、oauth token、各种 cache/telemetry/shell-snapshots 等机器相关数据

子命令:
  export    打包成 claude-backup-<时间戳>.zip
  import    从 zip 恢复到本机 ~/.claude(导入前自动备份,可 --dry-run 预览)
  git-init  把 ~/.claude 变成 git 仓库并写好 .gitignore(日常多机同步用)
"""

import argparse
import getpass
import json
import os
import shutil
import socket
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
CLAUDE_JSON = HOME / ".claude.json"

# 相对 ~/.claude 的迁移白名单。dir=True 表示整个目录递归。
# optional=True 表示不存在就跳过(不报错)。history=True 表示属于聊天记录,--no-history 时排除。
ALLOWLIST = [
    {"rel": "settings.json", "dir": False},
    {"rel": "history.jsonl", "dir": False, "optional": True},
    {"rel": "CLAUDE.md", "dir": False, "optional": True},
    {"rel": "keybindings.json", "dir": False, "optional": True},
    {"rel": "skills", "dir": True},
    {"rel": "projects", "dir": True, "history": True},
    {"rel": "plugins/installed_plugins.json", "dir": False, "optional": True},
    {"rel": "plugins/known_marketplaces.json", "dir": False, "optional": True},
    {"rel": "plugins/plugin-catalog-cache.json", "dir": False, "optional": True},
    {"rel": "plugins/marketplaces", "dir": True, "optional": True},
]

# git-init 写入的 .gitignore 内容
GITIGNORE = """\
# === 机密,绝不入库 ===
.credentials.json

# === 机器相关 / 可重建,不入库 ===
cache/
downloads/
telemetry/
shell-snapshots/
paste-cache/
session-env/
sessions/
ide/
file-history/
backups/
tasks/
stats-cache.json
.last-cleanup
.last-update-result.json
.last_inuse_sweep

# === 插件缓存(清单与 marketplaces/ 保留) ===
plugins/cache/
plugins/data/

# 保留: settings.json  skills/  projects/  history.jsonl
#       plugins/*.json  plugins/marketplaces/
"""


def log(msg):
    print(msg, flush=True)


def read_json(path):
    """读 JSON,容忍 UTF-8 BOM;文件不存在或空返回 None。"""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    text = text.strip()
    if not text:
        return None
    return json.loads(text)


def write_json(path, obj):
    """写 JSON,UTF-8 无 BOM,缩进 2。"""
    Path(path).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def iter_allowlist(include_history):
    for item in ALLOWLIST:
        if item.get("history") and not include_history:
            continue
        yield item


def add_path_to_zip(zf, abs_path, arc_prefix):
    """把单个文件或整个目录加入 zip,arcname 以 arc_prefix 开头。"""
    if abs_path.is_dir():
        for root, _dirs, files in os.walk(abs_path):
            for fn in files:
                fp = Path(root) / fn
                arc = Path(arc_prefix) / fp.relative_to(abs_path.parent)
                zf.write(fp, arc.as_posix())
    else:
        arc = Path(arc_prefix) / abs_path.name
        zf.write(abs_path, arc.as_posix())


def extract_mcp_servers():
    """从 ~/.claude.json 抽出 mcpServers,没有返回 {}。"""
    data = read_json(CLAUDE_JSON)
    if not data:
        return {}
    return data.get("mcpServers", {}) or {}


# ---------------------------------------------------------------- export


def build_archive(dest_zip, include_history):
    """构建迁移包,返回包含项的清单列表。"""
    included = []
    skipped = []
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in iter_allowlist(include_history):
            src = CLAUDE_DIR / item["rel"]
            if not src.exists():
                if item.get("optional"):
                    skipped.append(item["rel"])
                    continue
                log(f"  ! 缺少非可选项,跳过: {item['rel']}")
                skipped.append(item["rel"])
                continue
            # arcname 形如 claude/<rel 的父目录>/...
            arc_prefix = (Path("claude") / item["rel"]).parent.as_posix()
            add_path_to_zip(zf, src, arc_prefix)
            included.append(item["rel"])

        # mcpServers 单独抽成一个文件
        mcp = extract_mcp_servers()
        zf.writestr(
            "mcp-servers.json",
            json.dumps(mcp, ensure_ascii=False, indent=2),
        )

        manifest = {
            "tool": "claude_migrate",
            "version": 1,
            "created": datetime.now().isoformat(timespec="seconds"),
            "source_user": getpass.getuser(),
            "source_host": socket.gethostname(),
            "source_home": str(HOME),
            "include_history": include_history,
            "included": included,
            "skipped_absent": skipped,
            "mcp_server_count": len(mcp),
        }
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return included, skipped


def cmd_export(args):
    if not CLAUDE_DIR.exists():
        log(f"找不到 {CLAUDE_DIR},这台机器没装 Claude Code?")
        return 1
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path.cwd() / f"claude-backup-{ts}.zip"
    out = out.resolve()
    if out.is_dir():
        out = out / f"claude-backup-{ts}.zip"
    log(f"导出到: {out}")
    log(f"聊天记录: {'包含' if not args.no_history else '不包含'}")
    included, skipped = build_archive(out, include_history=not args.no_history)
    size_mb = out.stat().st_size / 1024 / 1024
    log(f"\n完成,共 {len(included)} 项,{size_mb:.1f} MB")
    log(f"包含: {', '.join(included)}")
    if skipped:
        log(f"跳过(不存在): {', '.join(skipped)}")
    log("\n提示: 这个包不含登录凭证,新机导入后请运行 /login。")
    return 0


# ---------------------------------------------------------------- import


def backup_current(include_history):
    """导入前把现状打包到 ~/.claude/backups/pre-import-<ts>.zip。"""
    bdir = CLAUDE_DIR / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"pre-import-{ts}.zip"
    build_archive(dest, include_history=include_history)
    # .claude.json 整文件也单独留一份,因为导入会改它
    if CLAUDE_JSON.exists():
        shutil.copy2(CLAUDE_JSON, bdir / f"claude.json.{ts}.bak")
    return dest


def merge_mcp_servers(archive_mcp):
    """把迁移包里的 mcpServers 并入本机 .claude.json,保留本机其它键和已有 server。"""
    if not archive_mcp:
        return 0
    data = read_json(CLAUDE_JSON) or {}
    existing = data.get("mcpServers", {}) or {}
    added = 0
    for name, cfg in archive_mcp.items():
        if name not in existing:
            added += 1
        existing[name] = cfg  # 迁移包优先
    data["mcpServers"] = existing
    write_json(CLAUDE_JSON, data)
    return added


def remap_user_projects(projects_dir, old, new, dry_run=False):
    """把 projects/ 下按旧用户名编码的会话目录改写成新用户名。

    只动 `Users<分隔符><用户名><分隔符>` 形态,避免误伤正文里别的 'dell'。
    返回 (重命名目录数, 改写内容文件数)。
    """
    if not projects_dir.exists():
        return 0, 0

    seg_old, seg_new = f"Users-{old}-", f"Users-{new}-"
    renamed = 0
    for d in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
        if seg_old not in d.name:
            continue
        target = projects_dir / d.name.replace(seg_old, seg_new)
        if dry_run:
            log(f"    {d.name}  ->  {target.name}")
            renamed += 1
            continue
        if target.exists():
            # 新机已有同名项目历史: 把文件并过去再删旧目录
            for f in d.rglob("*"):
                if f.is_file():
                    dst = target / f.relative_to(d)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(dst))
            shutil.rmtree(d, ignore_errors=True)
        else:
            d.rename(target)
        renamed += 1

    if dry_run:
        return renamed, 0

    # 内容改写: 会话 jsonl 里的绝对路径(JSON 里反斜杠转义成 \\)
    bs = b"\\"
    ob, nb = old.encode("utf-8"), new.encode("utf-8")
    patterns = [
        (b"Users" + bs + bs + ob + bs + bs, b"Users" + bs + bs + nb + bs + bs),  # Users\\dell\\
        (b"Users" + bs + ob + bs, b"Users" + bs + nb + bs),                      # Users\dell\
        (b"Users/" + ob + b"/", b"Users/" + nb + b"/"),                          # Users/dell/
        (b"Users-" + ob + b"-", b"Users-" + nb + b"-"),                          # Users-dell-
    ]
    rewritten = 0
    for f in projects_dir.rglob("*"):
        if not f.is_file():
            continue
        data = f.read_bytes()
        new_data = data
        for a, b in patterns:
            if a in new_data:
                new_data = new_data.replace(a, b)
        if new_data != data:
            f.write_bytes(new_data)
            rewritten += 1
    return renamed, rewritten


def cmd_import(args):
    archive = Path(args.archive).resolve()
    if not archive.exists():
        log(f"找不到迁移包: {archive}")
        return 1

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8")) \
            if "MANIFEST.json" in names else {}
        archive_mcp = json.loads(zf.read("mcp-servers.json").decode("utf-8")) \
            if "mcp-servers.json" in names else {}

        log("=== 迁移包信息 ===")
        for k in ("created", "source_user", "source_host", "source_home",
                  "include_history", "mcp_server_count"):
            if k in manifest:
                log(f"  {k}: {manifest[k]}")

        # 用户名/路径不一致时,聊天记录目录名(按绝对路径编码)可能对不上新机项目
        cur_user = getpass.getuser()
        if manifest.get("source_user") and manifest["source_user"] != cur_user:
            log(f"\n  ⚠ 源用户名 '{manifest['source_user']}' != 本机 '{cur_user}'。")
            log("    projects/ 下的会话目录按绝对路径命名,新机项目路径不同会导致")
            log("    历史不自动关联(文件已迁,内容没丢)。建议新机用相同用户名/项目路径。")

        claude_members = [n for n in names if n.startswith("claude/")]

        if args.dry_run:
            log(f"\n[dry-run] 将写入 {len(claude_members)} 个文件到 {CLAUDE_DIR}")
            log(f"[dry-run] 将并入 {len(archive_mcp)} 个 mcpServers 到 {CLAUDE_JSON}")
            if args.remap_user:
                old, new = args.remap_user
                seg_old = f"Users-{old}-"
                proj_dirs = sorted({
                    n.split("/")[2] for n in names
                    if n.startswith("claude/projects/") and len(n.split("/")) > 3
                })
                hits = [d for d in proj_dirs if seg_old in d]
                log(f"[dry-run] 改写用户名 {old} -> {new}: 命中 {len(hits)} 个会话目录")
                for d in hits:
                    log(f"    {d}  ->  {d.replace(seg_old, f'Users-{new}-')}")
            log("[dry-run] 未做任何改动。")
            return 0

        CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

        if not args.no_backup:
            log("\n导入前备份当前状态...")
            bk = backup_current(include_history=manifest.get("include_history", True))
            log(f"  已备份到: {bk}")

        log("\n写入文件...")
        for n in claude_members:
            rel = n[len("claude/"):]
            if not rel:
                continue
            dest = CLAUDE_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(n) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        log(f"  写入 {len(claude_members)} 个文件")

    added = merge_mcp_servers(archive_mcp)
    log(f"  并入 mcpServers: 新增 {added} 个(同名以迁移包为准)")

    if args.remap_user:
        old, new = args.remap_user
        log(f"\n改写会话目录用户名: {old} -> {new}")
        renamed, rewritten = remap_user_projects(CLAUDE_DIR / "projects", old, new)
        log(f"  目录改名 {renamed} 个,内容路径改写 {rewritten} 个文件")

    log("\n完成。下一步:")
    log("  1) 启动 claude 后运行 /login 重新登录(迁移包不含凭证)")
    log("  2) 如有本机专属的 MCP 路径,检查 ~/.claude.json 的 mcpServers")
    return 0


# ---------------------------------------------------------------- git-init


def run_git(args_list, cwd):
    return subprocess.run(
        ["git"] + args_list, cwd=str(cwd),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def cmd_git_init(args):
    if not CLAUDE_DIR.exists():
        log(f"找不到 {CLAUDE_DIR}")
        return 1
    if shutil.which("git") is None:
        log("没找到 git,请先安装 git。")
        return 1

    gi = CLAUDE_DIR / ".gitignore"
    gi.write_text(GITIGNORE, encoding="utf-8")
    log(f"写入 {gi}")

    if not (CLAUDE_DIR / ".git").exists():
        r = run_git(["init"], CLAUDE_DIR)
        log(r.stdout.strip() or r.stderr.strip())
    else:
        log("已是 git 仓库,跳过 init")

    run_git(["add", "-A"], CLAUDE_DIR)
    status = run_git(["status", "--short"], CLAUDE_DIR)
    log("\n暂存区状态(前 20 行):")
    for line in status.stdout.splitlines()[:20]:
        log("  " + line)

    if args.remote:
        run_git(["remote", "remove", "origin"], CLAUDE_DIR)
        r = run_git(["remote", "add", "origin", args.remote], CLAUDE_DIR)
        if r.returncode == 0:
            log(f"\n已设置 origin = {args.remote}")

    if args.commit:
        r = run_git(["commit", "-m", "claude config snapshot"], CLAUDE_DIR)
        log(r.stdout.strip() or r.stderr.strip())
        log("\n下一步推送: git -C \"%USERPROFILE%\\.claude\" push -u origin main")
    else:
        log("\n未自动提交(没加 --commit)。检查无误后:")
        log('  git -C "%USERPROFILE%\\.claude" commit -m "claude config snapshot"')
    log("\n⚠ 推送前务必确认 .credentials.json 已被 .gitignore 挡住(本工具已配置)。")
    return 0


# ---------------------------------------------------------------- main


def main():
    p = argparse.ArgumentParser(
        prog="claude_migrate",
        description="迁移 Claude Code 个人数据(skills/memory/聊天记录/plugins/MCP)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export", help="打包成 zip")
    pe.add_argument("--out", help="输出路径(文件或目录),默认当前目录")
    pe.add_argument("--no-history", action="store_true", help="不含聊天记录(projects/)")
    pe.set_defaults(func=cmd_export)

    pi = sub.add_parser("import", help="从 zip 恢复到本机")
    pi.add_argument("archive", help="迁移包 zip 路径")
    pi.add_argument("--dry-run", action="store_true", help="只预览,不改动")
    pi.add_argument("--no-backup", action="store_true", help="导入前不备份当前状态")
    pi.add_argument(
        "--remap-user", nargs=2, metavar=("OLD", "NEW"),
        help="新机用户名不同时,把会话目录(及其中路径)的旧用户名改写为新用户名",
    )
    pi.set_defaults(func=cmd_import)

    pg = sub.add_parser("git-init", help="把 ~/.claude 变成 git 仓库")
    pg.add_argument("--remote", help="顺便设置 origin 远程地址")
    pg.add_argument("--commit", action="store_true", help="顺便创建首个提交")
    pg.set_defaults(func=cmd_git_init)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
