"""极简 TOML 写出器。stdlib 只有 tomllib(读),没有写。

只需支持 str / bool / int —— 声明清单里就这几种。遇到别的形状(嵌套 dict/list
之类,比如未来真的接入 hooks 结构)不拿 str()/repr() 糊成语法正确、语义错误的
TOML——那是静默腐蚀整份清单;宁可炸,炸出来的错误还能指明是哪个键坏的。
YAGNI:不为了"以防万一"去写一个支持嵌套表的通用 TOML 序列化器。
"""
import re

_BARE = re.compile(r"[A-Za-z0-9_-]+")

def _key(k: str) -> str:
    if _BARE.fullmatch(k):
        return k
    return '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'

def _escape_str(s: str) -> str:
    """TOML basic string 里必须转义的字符。漏了 \\n/\\r/\\t 中任意一个,值里
    一旦真的带上对应字符,原样吐出的换行/回车/制表符就会让 tomllib.loads()
    在这一行直接报"非法字符",拒绝解析的是**整份文件**,不是这一个字段。"""
    return (s.replace("\\", "\\\\")
             .replace('"', '\\"')
             .replace("\n", "\\n")
             .replace("\r", "\\r")
             .replace("\t", "\\t"))

def _val(v, key: str = "?") -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"' + _escape_str(v) + '"'
    raise ValueError(
        f"dump_toml: 键 {key!r} 的值类型 {type(v).__name__} 不受支持——"
        f"TOML 写出器只认 str/bool/int,遇到没见过的形状必须报错命名,"
        f"不能拿 str() 静默糊成语法正确、语义错误的 TOML。值: {v!r}")

def dump_toml(tables: list[tuple[str, dict]]) -> str:
    """tables: [(表名, {键: 值}), …]。表名可以带点(如 "claude.repos.cjt")。"""
    out = ["# 由 hub 生成，勿手改\n"]
    for name, rows in tables:
        out.append(f"[{name}]")
        for k, v in rows.items():
            out.append(f"{_key(k)} = {_val(v, k)}")
        out.append("")
    return "\n".join(out)
