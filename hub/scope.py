"""scope 的校验**与匹配**。

（历史注记：旧 docstring 说"匹配不在这里，因为 C 不是 Python"——那是落地层时代的判断。
v3 起 register/refresh 就是 hub 的 CLI 命令，C 就是 Python，匹配器理应回到这里。）

- 校验：`hub sync` 前 lint、`promote`/视图生成前预检，非法即停。
- 匹配：视图生成按 (本机 class/projects, 目标 tool) 判一条记忆进不进该视图。

语法：global / class:<名> / project:<名> / tool:<claude|codex|opencode>。
语义：global/class/project 同属"设备订阅"维度内 OR；tool 独立维度内 OR；
两维之间 AND；某维度无标签=该维度匹配全部；global 必须独占。
"""

class ScopeError(ValueError):
    pass

_DIMS = {"class", "project", "tool"}
_TOOLS = {"claude", "codex", "opencode"}

def parse_scope(scope: list[str]) -> dict[str, set[str]]:
    if not scope:
        raise ScopeError("scope 不能为空（至少写 [global]）")
    has_global = "global" in scope
    dims: dict[str, set[str]] = {}
    for token in scope:
        if token == "global":
            continue
        dim, sep, val = token.partition(":")
        if not sep or dim not in _DIMS or not val:
            raise ScopeError(f"非法 scope 谓词: {token!r}（合法维度: class/project/tool）")
        if dim == "tool" and val not in _TOOLS:
            raise ScopeError(f"未知 tool: {val!r}（合法: claude/codex/opencode）")
        dims.setdefault(dim, set()).add(val)
    if has_global and dims:
        raise ScopeError("global 必须单独出现，不可与维度谓词混用")
    return dims

def lint_scope(scope: list[str]) -> list[str]:
    try:
        parse_scope(scope)
        return []
    except ScopeError as e:
        return [str(e)]

def scope_matches(dims: dict[str, set[str]], device_classes: list[str],
                  device_projects: list[str], tool: str) -> bool:
    """dims = parse_scope(...) 的结果。global 场景 dims 为空 → 两维都匹配全部 → True。"""
    subs = dims.get("class", set()) | {f"@proj:{p}" for p in dims.get("project", set())}
    device_tags = set(device_classes) | {f"@proj:{p}" for p in device_projects}
    device_ok = (not subs) or bool(subs & device_tags)
    tools = dims.get("tool", set())
    tool_ok = (not tools) or (tool in tools)
    return device_ok and tool_ok
