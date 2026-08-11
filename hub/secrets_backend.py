"""引用 → 真值。**本仓唯一读密钥明文的一层。**

三件事必须写在最前面：

1. **本模块绕开 hub.guard，这是有意的。** guard 的黑名单第一项就是 `secrets`，
   走 read_source_text() 会把自己挡死。除本模块外，任何模块读本机源文件仍走 guard。
   **不要为了"统一"给 guard 加豁免参数**——那会让不变量退化成"取决于调用方传了什么"
   （spec §6.3）。
2. **hub.collect.* 永远不 import 本模块**，由 AST 测试（tests/hub/test_arch_secrets_isolation.py）
   保证。那是**架构边界**，防误耦合；它不是对抗 AI 的安全边界（spec §6.3）。
3. **将来要静态加密就只改这一层**（spec §5.6）：把 read → decrypt 换进来，
   runner 与 policy 拿到的仍是同一个 dict，外部契约不动。

错误信息里**永远不带真值**——§1.3 那次事故就是一个"只打印结构"的东西漏了一条分支。
"""
import os
import re
from pathlib import Path

from hub.secrets_store import SecretsError, check_item_name, load_item

_PREFIX = "hub://secrets/"
_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def secrets_root() -> Path:
    """密钥库位置。允许 HUB_SECRETS_ROOT 覆盖——**只为测试**，生产不设这个变量。"""
    return Path(os.environ.get("HUB_SECRETS_ROOT") or (Path.home() / ".claude" / "secrets"))


def parse_ref(ref: str) -> tuple[str, str]:
    """`hub://secrets/<item>/<field>` → (item, field)。严格，别的一律拒。"""
    if not isinstance(ref, str) or not ref.startswith(_PREFIX):
        raise SecretsError(f"不是一个 hub:// 引用：{ref!r}")
    rest = ref[len(_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SecretsError(f"引用形状必须是 hub://secrets/<item>/<field>：{ref!r}")
    item, field = parts
    # item 名走 secrets_store 那一处唯一判据（`.unlock` 这类点开头的在这里就被拒，
    # 不必等到 resolve_ref 去碰文件系统才发现）。
    check_item_name(item)
    if not _VAR_RE.match(field.replace("-", "_")):
        raise SecretsError(f"非法的字段名：{ref!r}")
    return item, field


def resolve_ref(root: Path, ref: str) -> str:
    item, field = parse_ref(ref)
    fields = load_item(root, item)          # item 名非法 / 不是普通文件 → 这里抛
    if field not in fields:
        raise SecretsError(f"{item} 里没有字段 {field!r}")
    return fields[field]


def resolve_env(root: Path, mapping: dict[str, str]) -> dict[str, str]:
    """env 变量名 → 引用 的映射，解析成 env 变量名 → 真值。

    Windows 的环境变量名**大小写不敏感**，所以同一份声明里 `A` 与 `a` 是冲突而不是两项——
    静默让后者覆盖前者会让注入结果取决于 dict 顺序。宁可炸。
    """
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for name, ref in mapping.items():
        if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
            raise SecretsError(f"非法的环境变量名：{name!r}")
        low = name.lower()
        if low in seen:
            raise SecretsError(f"环境变量名大小写冲突：{seen[low]!r} 与 {name!r}")
        seen[low] = name
        val = resolve_ref(root, ref)
        if "\x00" in val:
            raise SecretsError(f"{name} 的值含 NUL，无法作为环境变量")
        out[name] = val
    return out