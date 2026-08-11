"""runner：固定 argv + 一次性局部 env → 子进程 → 遮罩输出。

不变量（spec §5.5，每一条都有对应测试）：

- 真值绝不进 argv（进程列表可见）
- 不生成任何明文临时文件——**结构上不产生**，不是"用完删掉"
- 不修改父进程的全局 os.environ；只构造一次性局部 mapping
- 不做变量展开、不做命令替换——现在是结构上不存在这个环节
- 遮罩覆盖**成功 / 非零退出 / 超时 / 解码失败**四条路径，且**先在 bytes 上做**再解码

**遮罩不是安全边界**：只做精确值匹配，变形/截断/编码后的值挡不住（与 secrets_scan 同构）。
子进程自己想打印、写盘、发网络，谁也拦不住——env 注入不是隔离（spec §10）。
"""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hub.secrets_backend import resolve_env
from hub.secrets_profile import Profile, check_args, check_argv

_MASK = b"<redacted>"


@dataclass
class RunResult:
    rc: int
    out: str
    err: str


def redact_bytes(b: bytes, values) -> bytes:
    """精确值匹配替换。长的先替，避免一个值是另一个的前缀时替出半截。"""
    if not b:
        return b
    for v in sorted({x for x in values if x}, key=len, reverse=True):
        b = b.replace(v.encode("utf-8", "surrogatepass"), _MASK)
    return b


def _decode(b: bytes, values) -> str:
    # 先遮罩再解码：解码失败退化成 replace 也不会把真值漏出来
    return redact_bytes(b or b"", values).decode("utf-8", "replace")


def run_profile(profile: Profile, args: list[str], secrets_root: Path,
                timeout: int = 600) -> RunResult:
    check_argv(profile)
    check_args(profile, args)
    injected = resolve_env(Path(secrets_root), profile.env)
    values = list(injected.values())

    # env 是**完整替代**不是 overlay：从父进程副本出发再覆盖，
    # 免得子进程丢掉 SystemRoot/TEMP 这类 Windows 上不给就起不来的东西。
    # 父进程的 os.environ 本身一个字节都不动。
    env = dict(os.environ)
    env.update(injected)

    argv = [*profile.argv, *args]
    try:
        cp = subprocess.run(argv, env=env, shell=False, close_fds=True,
                            capture_output=True, timeout=timeout)
        return RunResult(cp.returncode, _decode(cp.stdout, values), _decode(cp.stderr, values))
    except subprocess.TimeoutExpired as e:
        # 超时对象里**也带着已经产出的输出**，同样要过遮罩
        return RunResult(124, _decode(e.stdout or b"", values),
                         _decode(e.stderr or b"", values) + f"\n[hub] 超时 {timeout}s")
    finally:
        injected.clear()
        values.clear()