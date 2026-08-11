"""profile：一份**声明**，不是脚本。

规则是「**AI 不得控制解释器/入口脚本/固定前缀**」，不是「禁止解释器」——后者照字面实现
会让 3 个 profile 起不来 2 个（vsce / mineru-open-api 在 Windows 上是 npm shim，
实体就是 `node.exe <入口脚本>`）。见 spec §5.3.1。

所以 `argv` 是一条**固定启动链**：每一段都是 profile 里写死的绝对路径，AI 只能往后追加
经语法校验的尾部参数。它仍然传不了 -e/-c、换不了入口、注入不了 NODE_OPTIONS。
"""
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hub.secrets_store import SecretsError

_BANNED_SUFFIX = {".bat", ".cmd"}


@dataclass
class Profile:
    name: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allow_subcommands: list[str] = field(default_factory=list)
    arg_pattern: str = r"^[A-Za-z0-9._/:@=+-]+$"


def profiles_path() -> Path:
    base = Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub"))
    return base / "secrets-profiles.toml"


def load_profiles(path: Path | None = None) -> dict[str, Profile]:
    p = Path(path) if path else profiles_path()
    if not p.is_file():
        raise SecretsError(f"没有 profile 声明：{p}")
    raw = tomllib.loads(p.read_text(encoding="utf-8")).get("profiles") or {}
    out: dict[str, Profile] = {}
    for name, d in raw.items():
        argv = d.get("argv") or []
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise SecretsError(f"profile {name}：argv 必须是非空字符串数组")
        out[name] = Profile(
            name=name,
            argv=argv,
            env=dict(d.get("env") or {}),
            allow_subcommands=list(d.get("allow_subcommands") or []),
            arg_pattern=d.get("arg_pattern") or Profile.arg_pattern,
        )
    return out


def check_argv(profile: Profile) -> None:
    """启动链：每段绝对路径、真实存在；**首段必须是 .exe**，.bat/.cmd 一律拒。"""
    for i, seg in enumerate(profile.argv):
        p = Path(seg)
        if not p.is_absolute():
            raise SecretsError(f"profile {profile.name}：启动链第 {i} 段不是绝对路径：{seg}")
        if p.suffix.lower() in _BANNED_SUFFIX:
            raise SecretsError(
                f"profile {profile.name}：拒绝 {p.suffix} —— Windows 上批处理文件"
                f"即使 shell=False 也会经系统 shell 解析，参数语义不再受控")
        if not p.is_file():
            raise SecretsError(f"profile {profile.name}：启动链第 {i} 段不存在：{seg}")
    if Path(profile.argv[0]).suffix.lower() != ".exe":
        raise SecretsError(f"profile {profile.name}：启动链首段必须是 .exe")


def check_args(profile: Profile, args: list[str]) -> None:
    """尾部参数：首个必须落在子命令白名单里，其余每个都要过 arg_pattern。

    **两道闸分工不同，别指望 arg_pattern 挡解释器**：`-e` / `--eval=x` 这类东西只可能
    出现在 args[0]，而 args[0] 必须命中子命令白名单——挡它的是白名单。arg_pattern 只管
    "不许有空白与 shell 元字符"；它的字符类里本来就得含 `-` 和 `=`，否则 `--force`、
    `--out=x.vsix` 这些日常尾参全废，闸就会被人摘掉。

    尾参里出现 `-开头` 也不危险：它们排在**入口脚本之后**，解释器看不到
    （node 只有在脚本路径之前才把 -e 当 eval）。
    """
    if not args:
        raise SecretsError(f"profile {profile.name}：缺子命令")
    if args[0] not in profile.allow_subcommands:
        raise SecretsError(
            f"profile {profile.name}：子命令 {args[0]!r} 不在白名单 "
            f"{sorted(profile.allow_subcommands)} 内")
    rx = re.compile(profile.arg_pattern)
    for a in args[1:]:
        if not isinstance(a, str) or "\x00" in a or not rx.match(a):
            raise SecretsError(f"profile {profile.name}：参数不合语法：{a!r}")