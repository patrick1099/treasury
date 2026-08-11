"""Claude Code PreToolUse hook：密钥读闸（spec §6）。

**退出码语义（官方，2026-08-10 核实）**——这是最容易致命的一处：

    exit 0 + stdout JSON  → JSON 被解析，三档判定生效
    exit 2                → 阻断，stderr 回喂
    **exit 1 与其它非零码 → 非阻断错误，工具照常执行**

所以顶层必须捕获一切异常并转 exit 2。判定逻辑越严谨，这个坑越致命：
它会把一个"拦得住"的闸变成"崩了就放行"。

**它挡不住什么**（spec §6.5，别让它显得比实际强）：用户自己粘明文、MCP/别的进程绕开工具层、
已经在上下文里的明文、蓄意绕行与提示注入。

**只按路径拦，绝不按内容模式拦**（spec §6.4）：secrets_scan 的误报率高到不能当闸。
"""
import json
import re
import sys
from pathlib import Path

# 只 import guard（纯 stdlib 依赖）。每次工具调用都跑，别把 hub 的其余部分拖进来；
# 尤其**绝不 import 明文解析层**。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub.guard import is_denied                                    # noqa: E402

_DENY_SUB = ("run", "render", "unlock")
# 命令串匹配是**提示层**：`hub` 不在 PATH 上，写法枚举不完（spec §6.7.3.1）。
# 承重闸在 secrets_cli.human_only / secrets_unlock.issue_token 里。
_CMD_HINTS = ("hub secrets", "hub.cli secrets", "cli.py secrets", "secrets_cli")

# `hub://…`、`oss://…`、`https://…` 都不是文件系统路径。
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def _token_valid() -> bool:
    """裸读，**不走 guard 的读取入口**——那会命中 secrets 黑名单把自己挡死。"""
    import time
    import os
    try:
        root = Path(os.environ.get("HUB_SECRETS_ROOT") or (Path.home() / ".claude" / "secrets"))
        return float((root / ".unlock").read_text(encoding="utf-8").strip()) > time.time()
    except Exception:
        return False


def _out(decision: str, reason: str) -> None:
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, sys.stdout)


def _paths(tool: str, ti: dict):
    """只取**真的是路径**的字段。

    **绝不要把 Grep 的 `pattern` 算进来**：`Path("secrets")` 会命中 has_denied_component，
    于是任何"搜一下 secrets 这个词"都被拒——那是纯误伤。误伤会逼人把闸摘掉，
    闸就废了（secrets_scan.py 用学费换来的那条结论，spec §6.4）。

    字段**在但不是字符串**时抛，让顶层转成 exit 2：判不了就拒，不是判不了就放行。
    """
    for key in ("file_path", "path", "notebook_path"):
        if key not in ti:
            continue
        v = ti[key]
        if not isinstance(v, str):
            raise ValueError(f"{key} 不是字符串（{type(v).__name__}），判定不了")
        if v:
            yield v


def _looks_like_path(tok: str) -> bool:
    """只有**带分隔符、且不是 URI** 的 token 才当路径查。

    两条都是为了不误伤：

    - 没有分隔符的裸词要放过，否则 `grep -r secrets .` 里那个 `secrets` 会被
      is_denied 判成命中。代价是 cwd 恰好在 secrets/ 里时敲裸文件名查不出来，
      **这是有意接受的漏**。
    - 带 scheme 的 token 要放过，否则 `hub://secrets/<item>/<field>` 会被判成命中——
      而那正是本项目要推广的引用写法，拦它等于冲着自己的正解开枪。
    """
    if _URI_RE.match(tok):
        return False
    return "/" in tok or "\\" in tok


def _decide_bash(cmd: str):
    low = cmd.lower()
    if any(h in low for h in _CMD_HINTS):
        for sub in _DENY_SUB:
            if f"secrets {sub}" in low:
                return "deny", (
                    f"`secrets {sub}` 是 human-only 通道。AI 请走 "
                    f"`secrets exec <profile>`——它能替你跑上传/发布/提取，但拿不到密钥值。")
    # 命令串里直接出现 secrets 路径（`cmd /c type ...\secrets\x.md`）
    for tok in cmd.replace('"', " ").replace("'", " ").split():
        if _looks_like_path(tok) and is_denied(Path(tok)):
            return "deny", "密钥明文请用 hub:// 引用，别直接读。"
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        raise ValueError(f"tool_input 不是对象（{type(ti).__name__}），判定不了")

    if tool == "Bash":
        got = _decide_bash(str(ti.get("command") or ""))
        if got:
            _out(*got)
        return 0

    writing = tool in ("Write", "Edit", "NotebookEdit")
    for raw in _paths(tool, ti):
        p = Path(raw)
        if not is_denied(p):
            continue
        if writing:
            _out("ask", "要往密钥库写。请确认存到哪、存成什么；存完请把正文改成 hub:// 引用。")
            return 0
        if _token_valid():
            _out("ask", "解锁令牌有效，仍需你逐次确认。批准后读到的明文只用于当次操作。")
            return 0
        _out("deny", "密钥明文读不了。用 hub://secrets/<item>/<field> 引用；"
                     "要跑真实命令走 `secrets exec <profile>`；"
                     "确实需要看明文时，请**你自己**在终端里 `secrets unlock`。")
        return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as e:
        # 任何没接住的异常都必须变成 exit 2。退 1 = 静默放行。
        sys.stderr.write(f"hub secrets guard 自身出错，按拒绝处理：{e!r}\n")
        raise SystemExit(2)
