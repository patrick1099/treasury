"""架构边界，**不是安全边界**（spec §6.3）。

它保的不变量只有一条：`collect` 的传递依赖图永远到不了 `secrets_backend`，
它的全部本机读取仍经过 guard。防的是**未来某次重构把两条路径接通**，不是防 AI——
Python 的模块边界不是 capability boundary，任何代码都能 import，AI 也能直接调 CLI。
"""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "hub"
FORBIDDEN = {"secrets_backend", "secrets_store", "secrets_run", "secrets_cli", "secrets_unlock"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def test_collect_never_reaches_secrets():
    bad = []
    for f in sorted((PKG / "collect").rglob("*.py")):
        for name in _imports(f):
            if any(x in name for x in FORBIDDEN):
                bad.append(f"{f.name} → {name}")
    assert not bad, "collect 不许碰密钥层：" + "; ".join(bad)


def test_guard_has_no_exemption_parameter():
    """DENIED_NAMES 不加任何豁免参数（spec §6.3）——那会让不变量退化成
    '取决于调用方传了什么'，正是 feedback_preview_must_share_write_path 那次事故的形状。"""
    src = (PKG / "guard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if fn.name in ("is_denied", "check_source", "read_source_text", "has_denied_component"):
            args = fn.args
            assert len(args.args) == 1 and not args.kwonlyargs and not args.defaults, \
                f"guard.{fn.name} 多了参数——豁免口子就是这么开的"
