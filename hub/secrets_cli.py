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


def _secrets_error_code(e: SecretsError) -> str:
    """SecretsError → 规范错误码（唯一口径，cli._error_code 也走这里）。

    缺资源（profile/字段/item 文件不存在）→ E_NOT_FOUND；其余（参数/状态/通道限制）
    一律 E_VALIDATION。SecretsError 不是 IO 包装器，没有 E_IO 分支。
    """
    m = str(e)
    if ("没有名为" in m and "profile" in m
            or "不是普通文件" in m
            or "里没有字段" in m
            or "没有 profile 声明" in m
            or "段不存在" in m):
        return "E_NOT_FOUND"
    return "E_VALIDATION"


def _secrets_rc(e: SecretsError) -> int:
    """SecretsError → 退出码：`--` 后空（缺操作数）= 用法错误 rc2，其余统一 rc1。

    与 promote-memory/induct 的先例一致：E_VALIDATION 里"参数少了"才 rc2，
    通道限制/状态类的 E_VALIDATION 是 rc1。
    """
    if str(e).startswith("secrets run 要在"):
        return 2
    return 1


def _fail(e: SecretsError, json_mode: bool = False) -> int:
    """把 SecretsError 落到人类 stderr 或 json 失败信封；人类/json 退出码一致。"""
    code = _secrets_error_code(e)
    rc = _secrets_rc(e)
    if json_mode:
        from hub.cli import _emit_error
        _emit_error(code, str(e), retryable=False)
    else:
        sys.stderr.write(f"{e}\n")
    return rc


def _strip_json_markers(tokens: list[str]) -> list[str]:
    """从 REMAINDER 里剔除 hub 自己的 json 标记，别让它们漏进子进程 argv。

    REMAINDER 陷阱：`secrets exec prof cmd --json` 里 `--json` 会被 REMAINDER 收走、
    原样传给子进程。json_mode 时在这里剔掉（--json / --format json / --format=json）；
    `--` 之后一个都不动——那是子进程的地盘。
    """
    out: list[str] = []
    stopped = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if stopped:
            out.append(tok)
        elif tok == "--":
            stopped = True
            out.append(tok)
        elif tok == "--json" or tok == "--format=json":
            pass
        elif tok == "--format" and i + 1 < len(tokens) and tokens[i + 1] == "json":
            i += 1                       # 连同它的值一起跳过
        else:
            out.append(tok)
        i += 1
    return out


def cmd_exec(args) -> int:
    """给 AI 的通道，**不设自守**。

    能力边界靠 profile 兜：启动链写死、子命令白名单、尾参过语法校验、输出经精确遮罩。
    AI 能请求"上传/发布/提取"，拿不到密钥值。

    json 模式把子进程退出码**定界**进信封：成功 data 放 exit_code + 遮罩后的 stdout
    （不放 stderr，stderr 属诊断流）；失败是 E_EXTERNAL_TOOL（details 只放 tool /
    exit_code / stderr_tail），退出码一律归一成 0/1，不再透传。人类模式是
    **legacy passthrough**：stdout/stderr 直写、return res.rc 原样透传。
    """
    json_mode = getattr(args, "json", False)
    try:
        res = run_profile(_profile(args.profile),
                          _strip_json_markers(list(args.args)), secrets_root())
    except SecretsError as e:
        return _fail(e, json_mode)
    if json_mode:
        if res.rc == 0:
            from hub.cli import _emit_result
            return 0 if _emit_result({"exit_code": 0, "stdout": res.out}) else 1
        from hub.cli import _emit_error
        _emit_error("E_EXTERNAL_TOOL",
                    f"secrets exec {args.profile} 退出码非零：{res.rc}",
                    details={"tool": args.profile, "exit_code": res.rc,
                             "stderr_tail": (res.err or "")[-500:]},
                    retryable=True,
                    suggestion="看 details.stderr_tail 里的输出修复后重试；"
                               "同一退出码反复出现说明问题在 profile 本身")
        return 1
    if res.out:
        sys.stdout.write(res.out)
    if res.err:
        sys.stderr.write(res.err)
    return res.rc


def cmd_run(args) -> int:
    """只给人：用某个 profile 声明的密钥，跑**任意**命令。

    这条通道保留完整灵活性，所以 stdio 直通、不捕获也不遮罩——遮罩是给 `exec` 那条
    通道用的，对着人遮没有意义。它的全部安全性来自 human_only()。

    json 模式先过 human_only()（非 TTY → E_VALIDATION rc1），通过后用 capture 跑：
    成功只报 exit_code 0；失败是 E_EXTERNAL_TOOL。**run 不遮罩，原始输出可能含密钥，
    所以信封/详情里绝不放 stdout/stderr**——这是泄密审查，不是功能取舍。交互式子进程
    在 capture 下可能挂起（已知边界，AI 不要用 run，用 exec）。
    """
    json_mode = getattr(args, "json", False)
    try:
        human_only()
        prof = _profile(args.profile)
        argv = _strip_json_markers([a for a in list(args.argv) if a != "--"])
        if not argv:
            raise SecretsError("secrets run 要在 `--` 后面给一条命令")
        injected = resolve_env(secrets_root(), prof.env)
    except SecretsError as e:
        return _fail(e, json_mode)
    env = dict(os.environ)          # 父进程的 os.environ 一个字节都不动
    env.update(injected)
    try:
        if json_mode:
            cp = subprocess.run(argv, env=env, shell=False, close_fds=True,
                                capture_output=True)
            if cp.returncode == 0:
                from hub.cli import _emit_result
                return 0 if _emit_result({"exit_code": 0}) else 1
            from hub.cli import _emit_error
            _emit_error("E_EXTERNAL_TOOL",
                        f"secrets run 的命令以非零退出码结束：{cp.returncode}",
                        details={"exit_code": cp.returncode},
                        retryable=True,
                        suggestion="查看命令自身的日志；信封不放 run 的原始输出"
                                   "（不遮罩，可能含密钥）")
            return 1
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
