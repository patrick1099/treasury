"""短时效解锁令牌 —— 人工授权开口的承重闸（spec §6.7.3）。

**授权动作必须物理上在人手里。** 四条实测结论决定了写法（spec §6.7.3.2）：

- `sys.stdin.isatty()` 在 AI 工具下是 **True** → **绝不能**拿它当判据；
- `sys.stdout.isatty()` 在 AI 工具下是 False、真终端是 True → 当便宜的前置判据；
- `sys.stdin.readline()` 立刻 EOF，但 `echo X | ...` 就能满足 → 不够；
- 读 **`CONIN$`**（真实控制台键盘缓冲区）在 AI 工具下**永久阻塞**，管道也灌不进去 → 承重。

失败方向永远是"**没有令牌**"。任何异常都不产生令牌。

**诚实边界**：这挡的是会犯错的 AI，不是蓄意的——刻意绕行可以自己分配一个伪终端（spec §2.1）。
"""
import sys
import time
from pathlib import Path

from hub.secrets_store import SecretsError

CONFIRM_PHRASE = "unlock secrets"
MAX_MINUTES = 60


def token_path() -> Path:
    from hub.secrets_backend import secrets_root
    return secrets_root() / ".unlock"


def _read_console_line() -> str:
    """从**控制台设备**读一行，不是从 stdin —— 管道喂不进 CONIN$。"""
    with open("CONIN$", "r", encoding="utf-8", errors="replace") as f:
        return (f.readline() or "").strip()


def issue_token(minutes: int) -> None:
    # bool 是 int 的子类，`1 <= True <= 60` 恒成立——不显式挡一下，一个 True 就能
    # 从这道数值闸里溜过去。闸上不留"取决于调用方传了什么"的口子。
    if isinstance(minutes, bool) or not isinstance(minutes, int) \
            or not (1 <= minutes <= MAX_MINUTES):
        raise SecretsError(f"minutes 必须是 1..{MAX_MINUTES} 的整数（没有『一直开着』的档位）")
    tty = getattr(sys.stdout, "isatty", None)
    if tty is None or not tty():
        raise SecretsError("unlock 只能由人在真实终端里敲。")
    print(f"要开放密钥明文 {minutes} 分钟。请在控制台键入确认短语：{CONFIRM_PHRASE}")
    try:
        line = _read_console_line()
    except OSError as e:
        raise SecretsError(f"读不到控制台，拒绝签发：{e}") from e
    if line != CONFIRM_PHRASE:
        raise SecretsError("确认短语不匹配，未签发。")
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(int(time.time() + minutes * 60)), encoding="utf-8")
    print(f"已开放到 {time.strftime('%H:%M:%S', time.localtime(time.time() + minutes * 60))}")


def token_valid(now: float | None = None) -> bool:
    """hook 每次工具调用都会问一次，必须便宜、且**永不抛**。

    裸 read_text：走 guard 的读取入口会命中 secrets 黑名单把 hook 自己挡死。
    """
    try:
        raw = token_path().read_text(encoding="utf-8").strip()
        return float(raw) > (now if now is not None else time.time())
    except Exception:
        return False        # 读不到 / 解析不了 / 过期 = 无效
