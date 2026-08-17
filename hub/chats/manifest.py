"""原始对话库的证据台账:读写 <host>/<tool>/chats/manifest.toml。

一个 artifact 一张表,表名是 `artifact.<引号包起来的 rel>`——rel 里可能有 `/`、`.`、
空格、中文,必须交给 tomlout.quote_key 逐字做键,不能自己拼。台账记的是证据的
**身份**(源 stat、落盘字节的 sha、角色 kind),不是内容;内容是 `Writer` 那些写原语
负责落盘的,这里只负责把台账序列化出来交给人去写。

确定性是硬要求:同样一组 entries,**两次 dump 必须字节完全相同**,否则 manifest 自己
就会让每次收集都显示"有改动"。为此表按 rel 排序输出;meta 平铺成 `x_` 前缀的同行键,
值只能是 str/bool/int(dump_toml 遇到别的形状会抛,那是对的,别绕过)。

注意 `artifact."rel"` 这串在 tomllib 里解析成**点状键**:`data["artifact"]` 是一个
subtable,键是 rel、值是那一行字段字典。所以 load 要读 `data["artifact"]`,不是
`data.items()`。
"""
import dataclasses
import tomllib
from pathlib import Path

from hub.chats.model import Entry
from hub.tomlout import dump_toml, quote_key

_META_PREFIX = "x_"
_TABLE_PREFIX = "artifact"


def load(chats_dir: Path) -> dict[str, Entry]:
    """读台账;文件不存在返回空 dict(第一次收集前没有台账很正常)。"""
    p = Path(chats_dir) / "manifest.toml"
    if not p.exists():
        return {}
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    out = {}
    for rel, rows in data.get(_TABLE_PREFIX, {}).items():
        out[rel] = _entry_from_rows(rel, rows)
    return out


def _entry_from_rows(rel: str, rows: dict) -> Entry:
    field_names = {f.name for f in dataclasses.fields(Entry)}
    meta = {k[len(_META_PREFIX):]: v for k, v in rows.items()
            if k.startswith(_META_PREFIX)}
    kwargs = {k: v for k, v in rows.items() if k in field_names and k != "rel"}
    return Entry(rel=rel, **kwargs, meta=meta)


def dump(entries: dict[str, Entry]) -> str:
    """把台账序列化成 TOML 文本,交给 Writer.write_text 落盘。

    表按 rel 排序输出保证同样输入两次 dump 字节相同;rel 本身写进表名
    (_TABLE_PREFIX + "." + quote_key(rel)),不作为行内字段。meta 平铺进同一张表,
    键加 x_ 前缀,dump_toml 只认 str/bool/int,遇到别的形状它抛——那是对的,别绕过。
    """
    tables = []
    for rel in sorted(entries):
        e = entries[rel]
        rows = {}
        for f in dataclasses.fields(Entry):
            if f.name in ("rel", "meta"):
                continue
            rows[f.name] = getattr(e, f.name)
        # meta 也要排序:dataclass 字段顺序是固定的,meta 是普通 dict,顺序跟着插入
        # 走。同一条证据由不同代码路径构造出的 meta 插入顺序可能不同,那就会让
        # "同样输入两次 dump 字节相同"这条硬要求在别处悄悄失效。
        for k, v in sorted(e.meta.items()):
            rows[_META_PREFIX + k] = v
        tables.append((_TABLE_PREFIX + "." + quote_key(rel), rows))
    return dump_toml(tables)