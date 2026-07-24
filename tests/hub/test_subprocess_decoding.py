"""防线:hub 里任何解文本的子进程调用都必须自己钉死编码,不许落到本机 locale。

真机事故(2026-07-23):`claude plugin --help` 里有个非 ASCII 字符,本机 preferred
encoding 是 cp936 → 读取线程 UnicodeDecodeError → CompletedProcess.stdout 变成
None(**返回码仍是 0**)→ 两层之后 `plug.stdout + mkt.stdout` 才抛 TypeError。
返回码骗人是这个坑最毒的地方,所以用静态防线一次盯住全部调用点,
而不是等哪台机器的哪条输出恰好带了非 ASCII 才发现。

git / claude / codex 的输出都是 UTF-8;唯一例外是 cmd.exe,中文 Windows 下它按
CP936 吐字,那里交给 locale 才是对的(见 fslink.make_dir_link)。
"""
import ast
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "hub"


def _prog(call: ast.Call) -> str:
    """取 argv 字面量的第 0 项(拿不到就返回空串)。"""
    if not call.args:
        return ""
    argv = call.args[0]
    if isinstance(argv, (ast.List, ast.Tuple)) and argv.elts:
        first = argv.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    return ""


def _decoding_calls(tree: ast.AST):
    """所有「显式要求解成文本」的 subprocess.run 调用。

    只认直接写在关键字里的 text=/universal_newlines=;用 ** 展开 kwargs 的调用
    静态看不出来,不在本防线覆盖范围内(hub 里那一处 snapshot._git 本身是合规的)。
    """
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        if any(isinstance(kw.get(n), ast.Constant) and kw[n].value is True
               for n in ("text", "universal_newlines")):
            yield node, kw


def test_all_text_subprocess_calls_pin_encoding():
    offenders = []
    for py in sorted(HUB.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node, kw in _decoding_calls(tree):
            if _prog(node) == "cmd":
                continue                      # 唯一豁免:cmd.exe 本就按本机代码页输出
            missing = [n for n in ("encoding", "errors") if n not in kw]
            if missing:
                offenders.append(f"{py.relative_to(HUB.parent)}:{node.lineno} 缺 {'+'.join(missing)}")
    assert not offenders, (
        "这些子进程调用把解码交给了本机 locale;非 ASCII 输出会让 stdout 静默变 None"
        "(返回码仍是 0),下游 str 运算才崩:\n  " + "\n  ".join(offenders))


def test_lint_actually_catches_a_bare_text_call(tmp_path):
    """防线自检:装一段有病的源码进去,必须被抓出来(否则上面那条是空跑的)。"""
    bad = ast.parse('import subprocess\n'
                    'subprocess.run(["git", "log"], capture_output=True, text=True)\n')
    found = [kw for _, kw in _decoding_calls(bad)]
    assert len(found) == 1 and "encoding" not in found[0]


def test_lint_exempts_cmd_exe():
    ok = ast.parse('import subprocess\n'
                   'subprocess.run(["cmd", "/c", "mklink"], text=True, errors="replace")\n')
    node, _ = next(_decoding_calls(ok))
    assert _prog(node) == "cmd"
