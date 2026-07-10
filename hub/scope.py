from hub.model import Target

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

def scope_matches(scope: list[str], target: Target) -> bool:
    dims = parse_scope(scope)
    if "device" in dims and target.device_classes.isdisjoint(dims["device"]):
        return False
    if "project" in dims and (target.project is None or target.project not in dims["project"]):
        return False
    if "tool" in dims and target.tool not in dims["tool"]:
        return False
    return True

def lint_scope(scope: list[str]) -> list[str]:
    try:
        parse_scope(scope)
        return []
    except ScopeError as e:
        return [str(e)]
