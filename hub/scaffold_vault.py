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

def _entries(root: Path) -> list[str]:
    """root 下的条目,忽略 .git —— 一个刚 `git init` 出来的空仓不算"非空"。

    金库本来就是个 git 仓,`git init && hub-scaffold` 是完全正常的建库姿势。
    把 .git 算成"已有内容"只会把人逼去用 --force,而 --force 才是真正危险的那条路。
    """
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.name != ".git")

def scaffold(root: Path, host: str, w: Writer, force: bool = False) -> None:
    """在 root 建一个空金库,或把**一台新设备**加进一个已有金库。

    这道闸挡的是**数据丢失**,不是"目录非空"本身。精确到两种情况:

    1. 目标非空、却不是金库(没有 vault.toml)→ 拒绝。别往一个陌生目录里乱倒
       一整套骨架。
    2. `<root>/<host>/device.toml` 已经存在 → 拒绝。那是**本机**的档案,里面是
       用户手填的源路径;再跑一次 scaffold 会把它**静默**换回 <占位> 模板。
       这就是当初那个数据丢失 bug。

    反过来:往一个**已有金库**里加一台**新**设备(clone 下来再 scaffold 本机)——
    这正是 SCHEMA.md §10 描述的多设备流程——不动任何已有文件,**不需要 --force**。
    过去这里一律拒绝,把用户逼上 --force,而 --force 会顺手把用户手工整理的
    lint-exempt.txt 清回空模板,下一次 hub sync 就跪在裸路径检查上:同一个 bug,
    换了个地方发作。

    不管走不走 force,这两个文件**已存在就绝不覆盖**:

    - `lint-exempt.txt` —— 用户手工整理的豁免名单,清掉就是删数据。
    - `vault.toml` —— 金库的格式版本标记,由建库那台机写下。第二台机再写一遍
      `version = 1` 是撒谎式降级(万一金库已经是 version = 2)。

    `SCHEMA.md` 相反:它是从代码里派生的契约文本,每次都该重写成当前版本。
    """
    root = Path(root)
    if not force:
        existing = _entries(root)
        if existing and not (root / "vault.toml").is_file():
            raise VaultNotEmptyError(
                f"{root} 非空(已有 {existing[:5]}{' …' if len(existing) > 5 else ''}),"
                f"而且看着不像金库——没有 vault.toml。不敢往陌生目录里倒一整套骨架。"
                f"要么换个空目录,要么确认无误后加 --force。")
        if (root / host / "device.toml").is_file():
            raise VaultNotEmptyError(
                f"{root / host / 'device.toml'} 已经存在——这台机({host})的档案已经建过了。"
                f"再 scaffold 一次会把你手填的源路径静默换回 <占位> 模板。"
                f"要加**别的**设备就把 host 换成那台机的名字;"
                f"确实要把本机档案推倒重来才加 --force(先备份 device.toml)。")
    if not (root / "vault.toml").is_file():
        w.write_text(root / "vault.toml", "version = 1\n")
    w.write_text(root / "SCHEMA.md", SCHEMA_MD)            # 派生物:每次重写
    if not (root / "lint-exempt.txt").is_file():
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
    p.add_argument("vault", help="金库目录(空目录，或一个已有金库——加新设备用)")
    p.add_argument("host", help="本机设备名，通常是 socket.gethostname().lower()")
    p.add_argument("--force", action="store_true",
                   help="两道闸都无视。会覆盖 <host>/device.toml——你手填的源路径会变回"
                        "占位符。(lint-exempt.txt 与 vault.toml 即便 --force 也不覆盖)")
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
