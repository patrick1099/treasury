"""极简 TOML 写出器。stdlib 只有 tomllib(读),没有写。

只需支持 str / bool / int —— 声明清单里就这几种。
"""
import re

_BARE = re.compile(r"[A-Za-z0-9_-]+")

def _key(k: str) -> str:
    if _BARE.fullmatch(k):
        return k
    return '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'

def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

def dump_toml(tables: list[tuple[str, dict]]) -> str:
    """tables: [(表名, {键: 值}), …]。表名可以带点(如 "claude.repos.cjt")。"""
    out = ["# 由 hub 生成，勿手改\n"]
    for name, rows in tables:
        out.append(f"[{name}]")
        for k, v in rows.items():
            out.append(f"{_key(k)} = {_val(v)}")
        out.append("")
    return "\n".join(out)
