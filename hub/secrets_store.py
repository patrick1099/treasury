"""密钥库的严格解析器。

**只解析，不读明文之外的判断**：本模块会读到真值，但它不决定谁能拿——那是
secrets_backend 与 policy 层的事。

解析必须 fail-closed（spec §3.1）：一个能接受任意路径的解析器，等于给整条
不变量开了一个参数化的后门。
"""
import os
import re
from pathlib import Path

from hub.frontmatter import parse_frontmatter, FrontmatterError


class SecretsError(RuntimeError):
    pass


# item 名：不许点开头（`.unlock` 不是密钥）、不许任何分隔符与 ..
_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def check_item_name(item: str) -> str:
    """item 名的**唯一**把关处。

    独立成函数是因为不止一个调用方：`item_path`（要落到文件）和
    `secrets_backend.parse_ref`（只解析引用、还不碰文件系统）都得用同一套判据。
    复制一份正则过去就等于开了第二条口径，早晚分岔。
    """
    if not isinstance(item, str) or not _ITEM_RE.match(item) or ".." in item:
        raise SecretsError(f"非法的 item 名 {item!r}：只接受 secrets 根下的直接文件名")
    return item


def item_path(root: Path, item: str) -> Path:
    """把 item 名解析成 secrets 根目录下的**直接普通文件**，别的一律拒。"""
    check_item_name(item)
    root = Path(root)
    p = root / f"{item}.md"
    if p.is_symlink():
        raise SecretsError(f"{p} 是符号链接，拒绝")
    if not p.is_file():
        raise SecretsError(f"{p} 不是普通文件")
    # realpath 双查：挡 junction / reparse point，以及 root 自身被换掉的情况
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(root):
        raise SecretsError(f"{p} 解析后逃出了 {root}")
    return p


def parse_fields(text: str) -> dict[str, str]:
    """只认 `## fields` 段，一行一个 `key = value`。段外全是给人看的。"""
    try:
        _, body = parse_frontmatter(text)
    except FrontmatterError as e:
        raise SecretsError(f"frontmatter 解析失败：{e}") from e

    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## fields":
            start = i + 1
            break
    if start is None:
        raise SecretsError("缺少 `## fields` 段")

    out: dict[str, str] = {}
    for ln in lines[start:]:
        if ln.startswith("## "):          # 下一段开始，fields 到此为止
            break
        s = ln.strip()
        if not s:
            continue
        if "=" not in s:
            raise SecretsError(f"`## fields` 段里无法解析的行：{ln!r}")
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()                  # 只剥两端空白，值内部一字不动
        if not key or "\x00" in key or "\x00" in val:
            raise SecretsError(f"非法的字段：{ln!r}")
        if key in out:
            raise SecretsError(f"重复的字段名 {key!r}")
        out[key] = val
    if not out:
        raise SecretsError("`## fields` 段是空的")
    return out


def load_item(root: Path, item: str) -> dict[str, str]:
    # 裸 read_text：本模块是密钥库自己的解析器，走 guard 会把自己挡死（见 Global Constraints）
    return parse_fields(item_path(root, item).read_text(encoding="utf-8"))


def iter_items(root: Path) -> list[str]:
    """列出可引用的 item。**点开头的文件一律不是 item**（`.unlock` 靠这条被排除）。"""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        p.stem for p in root.iterdir()
        if p.is_file() and not p.is_symlink() and p.suffix == ".md" and not p.name.startswith(".")
    )