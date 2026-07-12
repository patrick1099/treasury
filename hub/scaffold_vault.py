"""hub 金库脚手架:一条命令建出金库骨架 + 本机设备档案模板。

用法:
    py -3 -m hub.scaffold_vault <金库目录> [--host <主机名>] [--git]

- <金库目录> 会被创建(已存在且非空则拒绝,除非 --force)。
- --host 省略时用本机 hostname(小写),与 hub CLI 的默认一致。
- --git 顺带 git init + 首次提交(process/sync 需要金库是 git 仓)。

生成后编辑 <host>/device.toml 里标了 TODO 的项,再跑:
    py -3 -m hub.cli collect --vault <金库目录> --host <主机名>
    py -3 -m hub.cli process --vault <金库目录> --host <主机名>
    py -3 -m hub.cli pull    --vault <金库目录> --host <主机名>
"""
import argparse
import socket
import subprocess
import sys
from pathlib import Path
from hub.model import SHARED

_VAULT_TOML = "version = 1\n"

_SAMPLE_RULE = "## 示例规则(可删)\n- 提交前跑测试,保持 0 error 0 warning\n"

_SAMPLE_MEMORY = (
    "---\n"
    "name: sample_note\n"
    "description: 示例记忆,可删\n"
    "metadata:\n"
    "  type: reference\n"
    "  scope: [global]\n"
    "  portable: true\n"
    "  sensitive: false\n"
    "---\n"
    "这是一条示例记忆。正文里引用路径请用 $VAULT/... 这类符号根,不要写死绝对路径。\n"
)


def _device_toml(vault: Path, host: str) -> str:
    home = Path.home()
    claude_home = (home / ".claude").as_posix()
    codex_home = (home / ".codex").as_posix()
    return (
        f'# {host} 的设备档案。标 TODO 的按本机情况改。\n'
        f'\n'
        f'# 本机属于哪些设备类(scope 里的 device:<class> 据此匹配)。\n'
        f'class = ["personal"]        # TODO: 例如 ["work"] / ["home"]\n'
        f'\n'
        f'# 本机参与的工程(信息性;真正的落地看 [[targets]])。\n'
        f'projects = []               # TODO: 例如 ["xinao"]\n'
        f'\n'
        f'# collect 会扫这些目录里的 *.md 记忆收进金库(跳过敏感/派生)。\n'
        f'# 只有 Claude 有人写的记忆文件;Codex 没有可收的源(它的记忆是 sqlite 内部流水线),\n'
        f'# 故 Codex 是单向接收方——经 ~/.codex/AGENTS.md 落地。\n'
        f'collect_sources = [         # TODO: 填本机工具的记忆目录\n'
        f'    # "{(home / ".claude" / "projects").as_posix()}/<工程编码>/memory",\n'
        f']\n'
        f'\n'
        f'# 符号根:记忆正文里的 $NAME/... 落地时按这里解析(仅 Claude 用户级 bundle 解析)。\n'
        f'[paths]\n'
        f'VAULT = "{vault.as_posix()}"\n'
        f'CLAUDE_HOME = "{claude_home}"\n'
        f'CODEX_HOME = "{codex_home}"\n'
        f'# SECRETS = "{(home / ".claude" / "secrets").as_posix()}"   # 可选\n'
        f'\n'
        f'# 每个 target = 一个工程根目录,pull 会往它写 AGENTS.md / CLAUDE.md。\n'
        f'# 可重复多段。project 要与记忆 scope 里的 project:<id> 对应。\n'
        f'# [[targets]]                # TODO: 取消注释并填写\n'
        f'# project = "xinao"\n'
        f'# root = "C:/path/to/your/project"\n'
    )


def scaffold(vault: Path, host: str, do_git: bool, force: bool) -> None:
    if vault.exists() and any(vault.iterdir()) and not force:
        raise SystemExit(f"目录非空,拒绝覆盖(加 --force 强制):{vault}")
    # 顶层按归属切:shared/ 是公共池(所有设备无条件拿),<host>/ 是这台设备的全部家当。
    # skills/plugins/chats 先占位,分发逻辑不在 MVP。
    for sub in (f"{SHARED}/rules", f"{SHARED}/memory", f"{SHARED}/skills", f"{SHARED}/plugins",
                f"{host}/memory", f"{host}/skills", f"{host}/plugins", f"{host}/chats"):
        (vault / sub).mkdir(parents=True, exist_ok=True)
    (vault / "vault.toml").write_text(_VAULT_TOML, encoding="utf-8", newline="\n")
    (vault / SHARED / "rules" / "00_sample.md").write_text(
        _SAMPLE_RULE, encoding="utf-8", newline="\n")
    (vault / SHARED / "memory" / "sample_note.md").write_text(
        _SAMPLE_MEMORY, encoding="utf-8", newline="\n")
    dev = vault / host / "device.toml"
    dev.write_text(_device_toml(vault, host), encoding="utf-8", newline="\n")
    # git 不跟踪空目录,占位目录靠 .gitkeep 留住
    for sub in (f"{SHARED}/skills", f"{SHARED}/plugins",
                f"{host}/skills", f"{host}/plugins", f"{host}/chats"):
        (vault / sub / ".gitkeep").write_text("", encoding="utf-8")

    if do_git:
        def git(*a: str) -> None:
            subprocess.run(["git", *a], cwd=vault, check=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if not (vault / ".git").exists():
            git("init", "-q")
        git("add", "-A")
        git("commit", "-qm", "chore(hub): 金库骨架")

    print(f"金库已创建:{vault}")
    print(f"设备档案:{dev}  (编辑里面标 TODO 的项)")
    print("下一步:")
    print(f'  py -3 -m hub.cli collect --vault "{vault}" --host {host}')
    print(f'  py -3 -m hub.cli process --vault "{vault}" --host {host}')
    print(f'  py -3 -m hub.cli pull    --vault "{vault}" --host {host}')


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="hub.scaffold_vault")
    ap.add_argument("vault", help="要创建的金库目录")
    ap.add_argument("--host", default=None, help="主机名(默认本机 hostname 小写)")
    ap.add_argument("--git", action="store_true", help="顺带 git init + 首次提交")
    ap.add_argument("--force", action="store_true", help="目录非空也继续")
    args = ap.parse_args(argv)
    host = args.host or socket.gethostname().lower()
    scaffold(Path(args.vault), host, args.git, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
