import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from hub.backend import RemoteUnavailable, GitlinkTracked, ChatsTracked
from hub.collect.errors import MissingSourceError
from hub.frontmatter import FrontmatterError
from hub.migrate import SchemaMigrationError
from hub.memread import MemoryNotInView
from hub.memview import ViewScopeError, SharedMemoryError
from hub.promote import PromoteConflict, PromoteMemoryConflict
from hub.register import RegisterConflict
from hub.hubconfig import ConfigConflict
from hub.vaultpaths import SharedSkillsEscape
from hub.textblock import BlockError
from hub.plugin_ops import PluginRepoUnavailable, PluginContainmentError
from hub.plugin_manifest import PluginManifestError, PluginIdentityError
from hub.plugin_cli import CliUnavailable
from hub.vault import UnsupportedVaultVersion
from hub.plugin_migrate import MigrationInputError
from hub.induction import InductionError
from hub.secrets_cli import SecretsError, _secrets_error_code

def _envelope(ok: bool, data=None, error=None, meta=None) -> dict:
    return {"ok": ok, "data": data, "error": error, "meta": meta or {}}

_MINIMAL_INTERNAL = {"ok": False, "data": None,
                     "error": {"code": "E_INTERNAL", "message": "序列化失败", "retryable": False},
                     "meta": {}}

def _json_default(o):
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, bytes):
        try:
            return o.decode("utf-8")
        except UnicodeDecodeError:
            return repr(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"{type(o).__name__} 不是 JSON 可序列化类型")

_MACHINE_OUT = None
_MACHINE_ERR = None

def _machine_write(channel: str, text: str) -> None:
    sink = _MACHINE_OUT if channel == "out" else _MACHINE_ERR
    if sink is not None:
        sink.write(text.encode("utf-8"))
        return
    stream = sys.stdout if channel == "out" else sys.stderr
    buf = getattr(stream, "buffer", None)
    if buf is not None:
        buf.write(text.encode("utf-8"))
    else:
        stream.write(text)

def _emit_result(data, meta=None) -> bool:
    try:
        text = json.dumps(_envelope(True, data=data, meta=meta),
                          ensure_ascii=False, indent=2, default=_json_default) + "\n"
    except Exception:
        _machine_write("err", json.dumps(_MINIMAL_INTERNAL, ensure_ascii=False, indent=2) + "\n")
        return False
    _machine_write("out", text)
    return True

def _emit_error(code: str, message: str, details=None, retryable: bool = False,
                suggestion=None) -> bool:
    error = {"code": code, "message": message, "retryable": retryable}
    if details is not None:
        error["details"] = details
    if suggestion is not None:
        error["suggestion"] = suggestion
    try:
        text = json.dumps(_envelope(False, error=error),
                          ensure_ascii=False, indent=2, default=_json_default) + "\n"
    except Exception:
        _machine_write("err", json.dumps(_MINIMAL_INTERNAL, ensure_ascii=False, indent=2) + "\n")
        return False
    _machine_write("err", text)
    return True

def _error_code(exc: Exception) -> str:
    """把异常映射到规范错误码总表。显式领域错误优先，再沿 __cause__/__context__ 链向上找。"""
    if isinstance(exc, PermissionError):
        return "E_PERMISSION"
    if isinstance(exc, FileNotFoundError):
        return "E_NOT_FOUND"
    if isinstance(exc, OSError):
        return "E_IO"
    if isinstance(exc, (MemoryNotInView, ViewScopeError, SharedMemoryError)):
        return "E_NOT_FOUND"
    if isinstance(exc, (PromoteConflict, PromoteMemoryConflict, RegisterConflict, ConfigConflict)):
        return "E_VALIDATION"
    if isinstance(exc, (SharedSkillsEscape, BlockError)):
        return "E_VALIDATION"
    if isinstance(exc, (PluginManifestError, PluginIdentityError, PluginContainmentError)):
        return "E_VALIDATION"
    if isinstance(exc, (RemoteUnavailable, PluginRepoUnavailable)):
        return "E_NETWORK"
    if isinstance(exc, UnsupportedVaultVersion):
        return "E_PLATFORM"
    if isinstance(exc, CliUnavailable):
        return "E_EXTERNAL_TOOL"
    if isinstance(exc, MissingSourceError):
        return "E_NOT_FOUND"
    if isinstance(exc, (FrontmatterError, SchemaMigrationError, MigrationInputError,
                        InductionError)):
        return "E_VALIDATION"
    if isinstance(exc, (GitlinkTracked, ChatsTracked)):
        return "E_VALIDATION"
    if isinstance(exc, subprocess.CalledProcessError):
        return "E_EXTERNAL_TOOL"
    if isinstance(exc, SecretsError):
        return _secrets_error_code(exc)
    if isinstance(exc, ValueError):
        return "E_VALIDATION"
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        code = _error_code(cause)
        if code != "E_INTERNAL":
            return code
    return "E_INTERNAL"

@contextmanager
def _stdout_to_stderr():
    """json 模式：执行期间模块的进度 print（dry-run 的 [dry-run]/[plan]）改道 stderr，
    保住 stdout 只有最终信封。异常路径会先恢复再出，_emit_* 总在恢复后调用。"""
    real = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = real

def _json_requested(argv: list[str] | None) -> bool:
    if argv is None:
        argv = sys.argv[1:]
    stopped = False
    for i, tok in enumerate(argv):
        if stopped:
            break
        if tok == "--":
            stopped = True
            continue
        if tok == "--json":
            return True
        if tok == "--format":
            if i + 1 < len(argv) and argv[i + 1] == "json":
                return True
        elif tok.startswith("--format=") and tok.split("=", 1)[1] == "json":
            return True
    return False

def _make_console_output_tolerant() -> None:
    """本机 py -3 -c "print(sys.stdout.encoding)" 报 gbk,而 gbk 编不出 ⚠(U+26A0)——
    secrets-scan/脏仓警告一旦真的命中,print() 就会以 UnicodeEncodeError 崩溃,
    唯一该报警的时刻反而看着像随机 Python bug。TTY(真实控制台)保持 encoding 不动、
    只把 errors 换成 replace(编不出就退化成 ?),强改 encoding="utf-8" 会让 gbk 控制台
    上其余中文输出变乱码;非 TTY(管道/重定向,AI/agent 消费的场景)强制 UTF-8——
    机器通道与契约闸都要求 UTF-8 字节。捕获测试用的替身 stdout 之类不支持
    reconfigure() 的场景一律跳过,不当作错误。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if getattr(stream, "isatty", lambda: False)():
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
