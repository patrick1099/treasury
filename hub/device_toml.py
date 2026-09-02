"""最小 TOML 数组写入器：只更新 device.toml 的 [plugins.*] / [skills.*] enabled 数组。

策略是**行级最小改写**：

- 保留原文件除目标数组外的所有行（包括注释、其它字段、顺序、空白）。
- 只重写 `enabled = [...]` 这一行；没有该行就在对应 section 下补一行。
- `[plugins.<tool>]` / `[skills.<tool>]` 不存在时就地追加一个 TOML section。
- 目标数组内容没变时完全不调用 Writer，保证 dry-run 也不会产生无谓的“计划写入”。
"""
import re
import tomllib
from pathlib import Path
from hub.writer import Writer

_LIST_RE = re.compile(r"^(\s*)(\w+)\s*=\s*(.*)$")
_SECTION_RE = re.compile(r"^\s*\[([^]]+)\]\s*$")


def _array_text(items) -> str:
    """TOML 单行数组。空数组用 []，字符串统一双引号。"""
    return "[" + ", ".join(json_quote(i) for i in items) + "]"


def json_quote(s: str) -> str:
    import json
    return json.dumps(str(s), ensure_ascii=False)


def _parse_array(text: str) -> list[str] | None:
    """从 `enabled = [...]` 右侧文本解析字符串数组；失败返回 None。"""
    raw = text.strip()
    if not raw.startswith("["):
        return None
    try:
        data = tomllib.loads("_x = " + raw)
    except (tomllib.TOMLDecodeError, ValueError):
        return None
    v = data.get("_x")
    if not isinstance(v, list):
        return None
    return [str(x) for x in v]


def _section_enabled_indent(lines, section_name) -> tuple[int, int | None] | None:
    """在 lines 中找到 section_name 的 header 行和 enabled 行。

    返回 (header_index, enabled_index or None)。目标只认顶层 section；
    不在嵌套 section 里找，避免误改同名深层键。
    """
    in_target = False
    depth = 0
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            name = m.group(1)
            # 简单判断嵌套：section 名里的点代表 table 层级，这里按顶层处理；
            # 插件/技能 section 形如 plugins.claude / skills.opencode。
            if name == section_name:
                in_target = True
                header_idx = i
                enabled_idx = None
                for j in range(i + 1, len(lines)):
                    lm = _SECTION_RE.match(lines[j])
                    if lm:
                        break
                    em = _LIST_RE.match(lines[j])
                    if em and em.group(2) == "enabled" and not lines[j].lstrip().startswith("#"):
                        enabled_idx = j
                        break
                return (header_idx, enabled_idx), in_target
    return None


def _insert_section(lines, section_name, items) -> list[str]:
    if lines and lines[-1].strip() != "":
        lines = list(lines) + [""]
    else:
        lines = list(lines)
    indent = ""
    out = list(lines)
    out.append(f"[{section_name}]")
    out.append(f"{indent}enabled = {_array_text(items)}")
    return out


def update_device_toml(path, plugins=None, skills=None, w: Writer | None = None) -> bool:
    """更新 device.toml 的 [plugins.<tool>].enabled / [skills.<tool>].enabled。

    - plugins / skills 都是 `{tool: [enabled names]}` 形式的 dict；传 None 表示不更新该类。
    - w 缺省为 Writer()；dry-run 通过 Writer(dry_run=True) 传入。
    - 返回 True 表示文件文本发生了变化（dry-run 也会返回 True，但不会落盘）。
    """
    path = Path(path)
    w = w if w is not None else Writer()
    if not path.exists():
        raise FileNotFoundError(f"device.toml 不存在：{path}")

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    changed = False

    for key, section_name in (
        ("plugins", "plugins"),
        ("skills", "skills"),
    ):
        mapping = plugins if key == "plugins" else skills
        if mapping is None:
            continue
        for tool, items in mapping.items():
            section = f"{key}.{tool}"
            found = _section_enabled_indent(lines, section)
            if found is None:
                # section 不存在
                lines = _insert_section(lines, section, items)
                changed = True
                continue
            (header_idx, enabled_idx), _ = found
            if enabled_idx is None:
                # 插入 enabled 行
                insert_at = header_idx + 1
                # 保持与 header 同一缩进（顶层通常为空）
                lines = list(lines)
                lines.insert(insert_at, f"enabled = {_array_text(items)}")
                changed = True
                continue
            em = _LIST_RE.match(lines[enabled_idx])
            assert em
            old_text = em.group(3).strip()
            old_items = _parse_array(old_text)
            if old_items is not None and old_items == list(items):
                continue
            indent = em.group(1)
            lines[enabled_idx] = f"{indent}enabled = {_array_text(items)}"
            changed = True

    if not changed:
        return False

    # 保留原有换行风格；Writer 本身也会沿用目标文件风格。
    new_text = "\n".join(lines)
    if not original.endswith(("\n", "\r")):
        new_text += "\n"
    w.write_text(path, new_text)
    return True
