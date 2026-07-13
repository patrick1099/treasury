from pathlib import Path
from hub.model import Memory

class FrontmatterError(ValueError):
    pass

def _unquote(s: str) -> str:
    """剥掉**一层配对的**外层引号。只认首尾同一个引号字符、且长度 ≥ 2 的情况。

    为什么必须剥:用户真实的记忆里有 21/47 条 `description:` 是 Claude 自己
    加了双引号写的。不剥,引号就原样进 MEMORY.md 索引;`name: "x"` 更会去写一个
    文件名带引号的文件(NTFS 上非法),`scope: ["global"]` 会被判成非法 scope。

    为什么只剥配对的外层:`别把设计重心压在'我认为重要的风险'上` 这种**内层**
    引号必须原样活下来。首尾不是同一个引号字符 → 一个字都不动。

    这里**不**做 YAML 注释剥离:`description: a # b` 里的 ` # b` 是值的一部分,
    照剥会静默毁掉任何正当含 " # " 的摘要。
    """
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'"):
        return s[1:-1]
    return s

def _coerce(v: str):
    s = v.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_unquote(x.strip()) for x in inner.split(",")]
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("\"", "'"):
        # 带引号的标量一律是**字符串**(标准 YAML 也这么读):`sensitive: "false"`
        # 是字符串 "false",不是布尔 false。真布尔由 _require_bool 把关,炸得响。
        return _unquote(s)
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    return s

def _indent_of(ln: str) -> int:
    return len(ln) - len(ln.lstrip(" "))

def _parse_block_list(lines: list[str], i: int, indent: int) -> tuple[list, int]:
    """从第 i 行开始收集缩进为 indent 的 '- item' 行,直到缩进变化或不再是列表项。"""
    n = len(lines)
    items: list = []
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if _indent_of(ln) != indent:
            break
        stripped = ln.strip()
        if not stripped.startswith("- "):
            break
        items.append(_unquote(stripped[2:].strip()))
        i += 1
    return items, i

def _parse_mapping(lines: list[str], i: int, indent: int) -> tuple[dict, int]:
    """从第 i 行开始解析缩进为 indent 的一层 'key: value' 映射。

    值为空时向下看一行:缩进 +2 且以 '- ' 开头 → 块状列表;
    缩进 +2 且是 'key: value' → 一层嵌套表(仅当 indent == 0 时允许,不然越界);
    否则视为空表(兼容旧行为)。
    """
    n = len(lines)
    result: dict = {}
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        cur_indent = _indent_of(ln)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            raise FrontmatterError(f"缩进/结构越界: {ln!r}")
        stripped = ln.strip()
        if stripped.startswith("- "):
            raise FrontmatterError(f"块状列表没有对应的键: {ln!r}")
        if ":" not in ln:
            raise FrontmatterError(f"无法解析行(子集外): {ln!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if val != "":
            result[key] = _coerce(val)
            i += 1
            continue

        # 值为空 —— 向下看一行判断是块状列表、嵌套表还是空表
        j = i + 1
        while j < n and not lines[j].strip():
            j += 1
        if j >= n or _indent_of(lines[j]) <= indent:
            # 没有更深缩进的后续行 —— 空表(兼容旧行为),下一轮循环重新处理 j 行
            result[key] = {}
            i += 1
            continue

        child_indent = _indent_of(lines[j])
        if child_indent != indent + 2:
            raise FrontmatterError(f"缩进/结构越界: {lines[j]!r}")

        if lines[j].strip().startswith("- "):
            items, j = _parse_block_list(lines, j, child_indent)
            result[key] = items
            i = j
        else:
            if indent != 0:
                raise FrontmatterError(f"超出一层嵌套子集: {lines[j]!r}")
            sub, j = _parse_mapping(lines, j, child_indent)
            result[key] = sub
            i = j
    return result, i

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """YAML 的一个受控子集:标量、一层嵌套、行内列表 [a, b]、块状列表(- a)。

    块状列表必须支持——Claude 自己写记忆时用的就是这个形式。
    """
    if not text.startswith("---"):
        raise FrontmatterError("缺少 frontmatter 起始 ---")
    lines = text.splitlines()
    if lines[0].strip() != "---":
        raise FrontmatterError("首行必须是 ---")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise FrontmatterError("缺少 frontmatter 结束 ---")

    meta, _ = _parse_mapping(lines[1:end], 0, 0)

    body = "\n".join(lines[end + 1:])
    if body and not body.endswith("\n"):
        body += "\n"
    return meta, body

def _require_bool(md: dict, key: str, default: bool, path: Path) -> bool:
    """`portable` / `sensitive` 必须是**真布尔**,不是"能 bool() 出个值的东西"。

    宁可响,不可错。旧写法 `bool(md.get("sensitive", False))` 把任何非空字符串
    都当 True:`sensitive: false  # 不入库` 解析成字符串 'false  # 不入库',
    bool() 判 True,collect 就把这条**本意 false** 的记忆当敏感内容静默跳过——
    这条记忆从此不在任何一次备份里,而且哪儿都不报错。标志位是**反的**。

    键缺失 = 用默认值,那是正常的;键**写了但不是布尔**才是错。
    """
    if key not in md:
        return default
    v = md[key]
    if isinstance(v, bool):
        return v
    raise FrontmatterError(
        f"{path}: metadata.{key} 必须是布尔字面量 true / false(不加引号、不带行内注释),"
        f"实际拿到 {type(v).__name__}: {v!r}。"
        f"注意本解析器**不剥行内注释**——`{key}: false  # 说明` 整串都是值。")

_KNOWN_TOP = frozenset({"name", "description", "metadata"})
_KNOWN_META = frozenset({"type", "scope", "portable", "sensitive"})

def load_memory(path: Path) -> Memory:
    try:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (FrontmatterError, UnicodeDecodeError) as e:
        raise FrontmatterError(f"{path}: {e}") from e
    md = meta.get("metadata", {})
    return Memory(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        type=md.get("type", "reference"),
        scope=md.get("scope", ["global"]),
        portable=_require_bool(md, "portable", True, path),
        sensitive=_require_bool(md, "sensitive", False, path),
        body=body,
        path=path,
        # 认不出来的键**不丢**,原样带着(见 model.Memory 的注释)。顺序照源文件里的
        # 出现顺序留着——dict 保序,于是 dump 出来也稳定,不会每次 collect 都抖出
        # 一堆无谓的 git diff。
        extra={k: v for k, v in meta.items() if k not in _KNOWN_TOP},
        extra_metadata={k: v for k, v in md.items() if k not in _KNOWN_META},
    )

def _fmt_list(xs: list[str]) -> str:
    return "[" + ", ".join(str(x) for x in xs) + "]"

def _fmt_scalar(v) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, list):
        return _fmt_list(v)
    return str(v)

def _fmt_extra(d: dict, indent: str) -> list[str]:
    """把未识别的键写回去,写法必须落在 parse_frontmatter 认得的那个子集里
    (标量 / 行内列表 / 一层嵌套),否则我们"保住"的键下一轮就解析不回来了。"""
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{indent}{k}:")
            lines += [f"{indent}  {k2}: {_fmt_scalar(v2)}" for k2, v2 in v.items()]
        else:
            lines.append(f"{indent}{k}: {_fmt_scalar(v)}")
    return lines

def dump_memory(m: Memory) -> str:
    """序列化一条记忆。

    已知的 7 个字段占**固定位置、固定写法**;`m.extra` / `m.extra_metadata` 里那些
    hub 不认识的键**原样搭车**,分别跟在各自那一层的已知键后面(见 model.Memory)。
    顺序沿用源文件里的出现顺序 → dump 是幂等的,不会每次 collect 都抖出无谓的 diff。
    """
    lines = [
        "---",
        f"name: {m.name}",
        f"description: {m.description}",
    ]
    lines += _fmt_extra(m.extra, "")
    lines += [
        "metadata:",
        f"  type: {m.type}",
        f"  scope: {_fmt_list(m.scope)}",
        f"  portable: {str(m.portable).lower()}",
        f"  sensitive: {str(m.sensitive).lower()}",
    ]
    lines += _fmt_extra(m.extra_metadata, "  ")
    lines.append("---")
    b = m.body
    if not b.endswith("\n"):
        b += "\n"
    return "\n".join(lines) + "\n" + b
