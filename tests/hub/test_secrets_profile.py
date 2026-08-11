import pytest
from hub.secrets_store import SecretsError
from hub.secrets_profile import load_profiles, check_argv, check_args

def _write(tmp_path, body):
    p = tmp_path / "secrets-profiles.toml"
    p.write_text(body, encoding="utf-8")
    return p

OK = """
[profiles.demo]
argv = ["{exe}"]
allow_subcommands = ["cp"]
arg_pattern = "^[A-Za-z0-9._/:@=+-]+$"
[profiles.demo.env]
TOK = "hub://secrets/demo/k1"
"""

def _exe(tmp_path, name="tool.exe"):
    p = tmp_path / name
    p.write_bytes(b"MZ")
    return str(p).replace("\\", "/")

def test_load_ok(tmp_path):
    p = _write(tmp_path, OK.format(exe=_exe(tmp_path)))
    profs = load_profiles(p)
    assert profs["demo"].env == {"TOK": "hub://secrets/demo/k1"}

def test_bat_and_cmd_refused(tmp_path):
    # Windows 上批处理即使 shell=False 也经系统 shell 解析（spec §5.3.1）
    for name in ("tool.bat", "tool.cmd"):
        p = _write(tmp_path, OK.format(exe=_exe(tmp_path, name)))
        with pytest.raises(SecretsError):
            check_argv(load_profiles(p)["demo"])

def test_relative_path_refused(tmp_path):
    p = _write(tmp_path, OK.format(exe="tool.exe"))
    with pytest.raises(SecretsError):
        check_argv(load_profiles(p)["demo"])

def test_missing_executable_refused(tmp_path):
    p = _write(tmp_path, OK.format(exe=str(tmp_path / "nope.exe").replace("\\", "/")))
    with pytest.raises(SecretsError):
        check_argv(load_profiles(p)["demo"])

def test_node_launch_chain_allowed(tmp_path):
    """vsce/mineru 只能这么起：绝对 node.exe + 绝对入口脚本（spec §5.3.1）。"""
    node = _exe(tmp_path, "node.exe")
    entry = tmp_path / "vsce"
    entry.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    body = OK.format(exe=node).replace(
        f'argv = ["{node}"]',
        f'argv = ["{node}", "{str(entry).replace(chr(92), "/")}"]')
    check_argv(load_profiles(_write(tmp_path, body))["demo"])   # 不抛

def test_args_subcommand_whitelist(tmp_path):
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    check_args(prof, ["cp", "a.txt", "oss://b/"])               # 不抛
    with pytest.raises(SecretsError):
        check_args(prof, ["rm", "-rf"])                          # 不在白名单
    with pytest.raises(SecretsError):
        check_args(prof, [])                                     # 必须有子命令

@pytest.mark.parametrize("bad", ["a b", "a;b", "$(x)", "a\x00b", "a|b"])
def test_args_pattern_refuses(tmp_path, bad):
    """arg_pattern 的职责只有一件：**不许出现空白与 shell 元字符**。"""
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    with pytest.raises(SecretsError):
        check_args(prof, ["cp", bad])

def test_interpreter_flag_cannot_be_first(tmp_path):
    """`secrets exec vsce -e "..."` 必须被拒（spec §9 / plan T11 Step 4）。

    挡住它的是**子命令白名单**——`-e` 只可能出现在 args[0]，而 args[0] 必须在白名单里。
    不是 arg_pattern：plan 初稿把这两条用例塞进 test_args_pattern_refuses，
    但那个 pattern 的字符类里本来就含 `-` 和 `=`，`-e` / `--eval=x` 当然能过。
    """
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    with pytest.raises(SecretsError):
        check_args(prof, ["-e", "console.log(1)"])
    with pytest.raises(SecretsError):
        check_args(prof, ["--eval=x"])

def test_option_like_tail_arg_allowed(tmp_path):
    """尾部的 `--force` / `--out` 必须放行。

    它们排在**入口脚本之后**，解释器根本看不到（node 只有在脚本路径之前才会把 -e 当 eval）。
    真正守住"AI 不得控制解释器"的是固定启动链 + 子命令白名单；在这里一刀切禁 `-` 开头，
    只会让 ossutil / vsce 的日常参数全废，闸就被摘掉了。
    """
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    check_args(prof, ["cp", "--force", "a.txt", "oss://b/"])    # 不抛