"""金库 schema 版本迁移。当前支持 **v1 → v2**（scope 语法 v2）与 **v2 → v3**。

scaffold 只管新库；已有金库升版本走这里。`to` 只接受 2 或 3，且只能从紧邻的上一版升：
`to==2` 只能从 v1 升，`to==3` 只能从 v2 升。同版本、跨版本（如 1→3）、或 `to` 不是
2/3，一律拒绝、版本不动。

v1→v2 额外两道门槛（spec §9.1，缺一不可）：
1. **只能从 version 1 升**——已是 v2 就拒绝（不重复迁移），非 1 也拒绝。
2. **必须全部记忆都是 [global] 才升**——v1 世界里数据本就全 global；任何非 global 记忆
   （含旧 `device:` 谓词，**也含手写的 `class:`/`project:`**）用的都是 v1 的旧维度语义，
   语义翻转后必须人工复核，故列清单拒绝、版本不动。
（当前真实金库 49 条全是 global，对它就是一次纯升版本。）

v2→v3 是纯格式标记升级，不涉及数据语义翻转，无需扫记忆。
"""
import tomllib
from pathlib import Path
from hub.vault import load_vault
from hub.writer import Writer

class SchemaMigrationError(RuntimeError):
    pass

def migrate_schema(vault_root: Path, to: int, w: Writer) -> None:
    vault_root = Path(vault_root)
    if to not in (2, 3):
        raise SchemaMigrationError(f"只支持迁移到 version 2 或 3，收到 {to}")
    cur = int(tomllib.loads((vault_root / "vault.toml").read_text(encoding="utf-8")).get("version", 1))
    want_from = to - 1
    if cur != want_from:
        raise SchemaMigrationError(f"迁移只支持 {want_from}→{to}；当前金库是 version {cur}，不动。")
    if to == 2:
        nonglobal = [f"{m.origin}/{m.name}: scope={m.scope}"
                     for m in load_vault(vault_root).memories if m.scope != ["global"]]
        if nonglobal:
            raise SchemaMigrationError(
                "升 v2 要求全部记忆都是 [global]（非 global 数据用的是 v1 旧维度语义、语义已翻转，"
                "须人工复核）。以下记忆不是 global，迁移中止、版本未升：\n  " + "\n  ".join(nonglobal))
    w.write_text_atomic(vault_root / "vault.toml", f"version = {to}\n")   # 原子写（Task 4）
