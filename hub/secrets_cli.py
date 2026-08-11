"""secrets 子命令。

**双通道（spec §5.2）**：

    run / render   → human-only，AI 一律走不通
    exec <profile> → 给 AI 的那条

**为什么 human-only 的闸长在这里而不是只在 hook 上**：`hub` 根本不在 PATH 上，
真实写法是 `py -3 -m hub.cli secrets ...`，hook 的命令串匹配枚举不完（spec §6.7.3.1）。
hook 那层是提示，这层才承重。

**绝不用 sys.stdin.isatty()**：实测在 Claude Code 的 Bash/PowerShell 工具下它是 True，
拿它当"是不是人"的判据等于没写。有区分度的是 stdout（spec §6.7.3.2 的实测表）。

**render 没有 `--out`**，这是设计不是遗漏：v1 的 `render --in tpl --out file` 破在
AI 把 `--out` 指向工作区再 Read 一遍就完了，而且它重新制造了「下游明文副本」
（spec §5.4）。修法不是校验落点，是根本不提供这个参数。
"""
import os
import subprocess
import sys

from hub.secrets_backend import resolve_env, secrets_root
from hub.secrets_profile import load_profiles, profiles_path
from hub.secrets_run import run_profile
from hub.secrets_store import SecretsError


def human_only() -> None:
    tty = getattr(sys.stdout, "isatty", None)
    if tty is None or not tty():
        raise SecretsError(
            "这条命令只给人在终端里用。AI 请走 `secrets exec <profile>`——"
            "它能替你跑上传/发布/提取，但拿不到密钥值。")


def _profile(name: str):
    profs = load_profiles()
    if name not in profs:
        raise SecretsError(
            f"没有名为 {name!r} 的 profile。{profiles_path()} 里现有：{sorted(profs)}")
    return profs[name]


def _fail(e: SecretsError) -> int:
    sys.stderr.write(f"{e}\n")
    return 2


def cmd_exec(args) -> int:
    """给 AI 的通道，**不设自守**。

    能力边界靠 profile 兜：启动链写死、子命令白名单、尾参过语法校验、输出经精确遮罩。
    AI 能请求"上传/发布/提取"，拿不到密钥值。
    """
    try:
        res = run_profile(_profile(args.profile), list(args.args), secrets_root())
    except SecretsError as e:
        return _fail(e)
    if res.out:
        sys.stdout.write(res.out)
    if res.err:
        sys.stderr.write(res.err)
    return res.rc


def cmd_run(args) -> int:
    """只给人：用某个 profile 声明的密钥，跑**任意**命令。

    这条通道保留完整灵活性，所以 stdio 直通、不捕获也不遮罩——遮罩是给 `exec` 那条
    通道用的，对着人遮没有意义。它的全部安全性来自 human_only()。
    """
    try:
        human_only()
        prof = _profile(args.profile)
        argv = [a for a in list(args.argv) if a != "--"]
        if not argv:
            raise SecretsError("secrets run 要在 `--` 后面给一条命令")
        injected = resolve_env(secrets_root(), prof.env)
    except SecretsError as e:
        return _fail(e)
    env = dict(os.environ)          # 父进程的 os.environ 一个字节都不动
    env.update(injected)
    try:
        return subprocess.run(argv, env=env, shell=False, close_fds=True).returncode
    finally:
        injected.clear()


def cmd_render(args) -> int:
    """只给人：把某个 profile 的密钥以 `KEY=value` 打到**终端**。

    没有 `--out`（见模块 docstring）。要落盘请人自己决定落到哪，本命令不代劳。
    """
    try:
        human_only()
        injected = resolve_env(secrets_root(), _profile(args.profile).env)
    except SecretsError as e:
        return _fail(e)
    try:
        for k, v in injected.items():
            print(f"{k}={v}")
    finally:
        injected.clear()
    return 0


def cmd_unlock(args) -> int:
    """只给人。承重闸在 issue_token 里（读 CONIN$），这里不重复一道。"""
    from hub.secrets_unlock import issue_token
    try:
        issue_token(args.minutes)
    except SecretsError as e:
        return _fail(e)
    return 0
