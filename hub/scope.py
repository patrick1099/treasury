"""scope 的**校验**。匹配不在这里——匹配是加载器(项目 C)的判断题。

提取器对 scope 只做一件事:`hub sync` 前 lint 一遍,非法就停。它自己**从不**按 scope
筛掉任何东西(备份区是本机现状的镜像,不做选择)。SCHEMA §2 也是这么对 C 说的。

(这里曾经有个 scope_matches() —— 落地层的遗物。落地层删了之后它没有任何生产调用方,
而 C 不是 Python、根本调不到它。留着只会让人以为"匹配逻辑在提取器这边",那是假的。)
"""

class ScopeError(ValueError):
    pass

_DIMS = {"device", "project", "tool"}

def parse_scope(scope: list[str]) -> dict[str, set[str]]:
    has_global = "global" in scope
    dims: dict[str, set[str]] = {}
    for token in scope:
        if token == "global":
            continue
        dim, sep, val = token.partition(":")
        if not sep or dim not in _DIMS or not val:
            raise ScopeError(f"非法 scope 谓词: {token!r}")
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
