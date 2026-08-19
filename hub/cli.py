import argparse
import json
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from datetime import date, datetime
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.migrate import migrate_schema, SchemaMigrationError
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.backend import (GitBackend, ConflictError, RemoteUnavailable,
                         GitlinkTracked, ChatsTracked, tracked_gitlinks)
from hub.collect import plan_deletions, preflight, run_all
from hub.collect.errors import MissingSourceError
from hub.frontmatter import FrontmatterError
from hub.writer import Writer
from hub.register import (register_skills, RegisterConflict,
                          plan_register_skills, commit_register_skills,
                          plan_hub_memory_skill, commit_hub_memory_skill,
                          check_link_collisions)
from hub.opencode_skills import (plan_link_opencode_skills, commit_link_opencode_skills,
                                 opencode_skill_status, stale_skills_paths_hint)
from hub.promote import (promote_skill, promote_memory, promote_memory_all,
                         PromoteConflict, PromoteMemoryConflict)
from hub.status_report import link_status, view_health
from hub.fslink import LinkError
from hub.vaultpaths import SharedSkillsEscape
from hub.hubconfig import read_config, write_config, check_config, ConfigConflict
from hub.memread import read_memory, MemoryNotInView
from hub.secrets_cli import cmd_exec, cmd_render, cmd_run, cmd_unlock
from hub.memview import ViewScopeError, SharedMemoryError
from hub.memwire import prepare_memory_views, commit_memory_views
from hub.textblock import BlockError
from hub.plugin_ops import (prepare_plugin_register, prepare_plugin_refresh, execute_plugin_plan,
                            plugin_health, PluginBumpNeeded, PluginRepoDirty, PluginRepoUnavailable,
                            PluginContainmentError)
from hub.plugin_manifest import PluginManifestError, PluginIdentityError
from hub.plugin_cli import CliUnavailable
from hub.vault import UnsupportedVaultVersion
from hub.plugin_migrate import (prepare_migration, execute_migration, prepare_cutover,
                                prepare_retire, execute_retire, MigrationInputError)
from hub.induction import (recover_pending, InductionError,
                           prepare_induction, execute_induction, drop_gitlink)

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
_MAIN_ARGV: list[str] | None = None

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
    if isinstance(exc, RemoteUnavailable):
        return "E_NETWORK"
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

class _JsonFriendlyParser(argparse.ArgumentParser):
    def error(self, message):
        if _json_requested(_MAIN_ARGV):
            _emit_error("E_VALIDATION", message)
            raise SystemExit(2)
        super().error(message)

def _add_output_flags(parser) -> None:
    parser.add_argument("--json", action="store_true", default=False,
                        help="输出 JSON 信封（与 --format json 等价）")
    parser.add_argument("--format", choices=("json",), default="json",
                        help="输出格式：仅支持 json（与 --json 等价）")

AI_HELP = """---
name: hub
description: >
  hub CLI——跨工具共享记忆金库的读写入口。memory-read 等命令按 CLI-AI 规范输出
  统一信封；其余命令保持人类可读文本。Use when user asks to read shared memory,
  sync the vault, register skills, promote memories, or manage the hub.
ai_help_version: 0.1.0
---

# hub AI Help Guide

## Quick Reference

- **读一条记忆:** `hub memory-read --vault <金库> --host <主机> --tool claude --name <名>`
- **读成 JSON:** 追加 `--json`（等价 `--format json` / `--format=json`）
- **看全部命令:** `hub --help`

## When to Use

Use this tool when the user asks to:
- 读金库里的共享记忆正文（memory-read）
- 同步金库到远端 / 生成索引（sync）
- 把 skill / 记忆提升进共享区（promote / promote-memory）
- 注册各工具的 skill 链接（register）
- 管理插件迁移（migrate-plugins / cutover-plugins / retire-plugin-sources）
- 密钥库操作（secrets，纯人用，不走 --json）

Do NOT use for:
- 写入或编辑记忆正文（hub 是金库的搬运工，不是编辑器）
- 替换各工具自身的 skill 流程

## Command Reference

- `memory-read --vault P --host H --tool T --name N`：读一条共享记忆的正文。
  默认人类模式 stdout 只有正文；`--json` 时 stdout 是 `{ok,data,error,meta}` 信封。
- `sync`：git 拉取 + lint + 写 MEMORY.md 索引 + 推送。
- `collect`：把本机配置的源镜像进金库备份区。
- `register` / `refresh` / `promote` / `promote-memory`：链接与提升。
- `secrets`：密钥库（exec/run/render/unlock），只给人用，无 --json。

## Input / Output

- **机器通道（--json / --format json / --ai-help）**：UTF-8 字节，走统一信封
  `{ok, data, error, meta}`；失败信封走 stderr，成功信封走 stdout。
- **人类通道（默认）**：保持各命令既有的纯文本输出（过渡期不改）。
- memory-read --json 的成功 data 含 `name` / `tool` / `host` / `vault` / `body`
  （body 是正文原样，不 trim、不改换行）。

## Side Effects & Safety

- `sync` / `collect` 会写金库并可能触发 git 提交/推送；`--dry-run` 只报告不落盘。
- 其余命令只读。共享记忆是唯一备份，删除类操作要确认。
- 不联网（除 sync 的 git 远端）。

## Exit Codes

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 运行失败（E_NOT_FOUND / E_INTERNAL / E_INTERRUPTED 等） |
| 2 | 参数/用法错误（E_VALIDATION，含 argparse 解析失败） |

| error.code | 含义 |
|---|---|
| `E_VALIDATION` | 参数/用法错误 |
| `E_NOT_FOUND` | 记忆不存在或越 scope |
| `E_INTERRUPTED` | 用户中断 |
| `E_INTERNAL` | 未预期内部错误 |

## Errors & Recovery

| 现象 | 处理 |
|---|---|
| 记忆读不到（E_NOT_FOUND） | 确认名字拼写 / scope 含 global 或本机 class/project / tool 归属；先跑 `hub register` 刷新视图 |
| 没配 vault 读不了 | 跑 `hub register` 绑定金库，或显式传 `--vault` |
| git 冲突（sync 返回 1） | 手工解决冲突后重试 |
| 参数拼错（E_VALIDATION） | `hub --help` 看用法 |

❌ 错：`hub memory-read --tool claude --name 不存在`
✅ 对：`hub memory-read --vault <金库> --host <主机> --tool claude --name <存在的名>`
"""

def _handle_ai_help(argv: list[str] | None) -> bool:
    if argv is None:
        argv = sys.argv[1:]
    stopped = False
    for token in argv:
        if stopped:
            break
        if token == "--":
            stopped = True
            continue
        if token == "--ai-help":
            _machine_write("out", AI_HELP)
            return True
    return False

def _lint(vault, exempt: set[str]) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        if m.name not in exempt:
            errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _status_json(vault_root: Path, host, check: bool, git_text: str) -> int:
    data = {"git": git_text, "skill_links": [], "opencode_links": [], "gitlinks": []}
    try:
        dev = load_device(vault_root, host or current_host())
    except FileNotFoundError:
        if check:
            _emit_error("E_NOT_FOUND", "status --check 停止：本机没有 device.toml",
                        suggestion="先跑 `hub register` 绑定金库，或显式传 --host <主机>")
            return 1
        return 0 if _emit_result(data) else 1
    try:
        rows = link_status(vault_root, dev)
    except SharedSkillsEscape as e:
        _emit_error(_error_code(e), str(e), retryable=False)
        return 1
    data["skill_links"] = [[state, label] for state, label in rows]
    try:
        oc_rows = opencode_skill_status(vault_root, dev, _hub_root())
    except (PluginManifestError, PluginIdentityError, PluginContainmentError) as e:
        _emit_error(_error_code(e), str(e), retryable=False)
        return 1
    data["opencode_links"] = [[state, label] for state, label in oc_rows]
    if not check:
        return 0 if _emit_result(data) else 1
    data["check"] = True
    links = tracked_gitlinks(vault_root)
    data["gitlinks"] = list(links)
    vh = view_health(vault_root, dev, _hub_root())
    try:
        ph = plugin_health(vault_root, dev)
    except (PluginManifestError, PluginIdentityError, PluginContainmentError,
            PluginRepoUnavailable, CliUnavailable, UnsupportedVaultVersion) as e:
        _emit_error(_error_code(e), str(e), retryable=False)
        return 1
    rows_all = rows + oc_rows + vh
    bad_rows = [r for r in rows_all if r[0] != "ok"]
    bad_plugin = [h for h in ph if h.state != "ok"]
    health = {"ok": not links and not bad_rows and not bad_plugin,
              "rows": [[state, label] for state, label in rows_all],
              "plugin": [[h.state, f"{h.name}@{h.tool}"] for h in ph]}
    data["health"] = health
    if not health["ok"]:
        parts = []
        if links:
            parts.append(f"{len(links)} 个 gitlink")
        if bad_rows:
            parts.append(f"{len(bad_rows)} 项不健康")
        if bad_plugin:
            parts.append(f"{len(bad_plugin)} 个插件不健康")
        _emit_error("E_VALIDATION", "status --check 不健康：" + "；".join(parts),
                    details={"gitlinks": list(links),
                             "rows": [[state, label] for state, label in rows_all],
                             "plugin": [[h.state, f"{h.name}@{h.tool}"] for h in ph]},
                    retryable=False,
                    suggestion="按 details 逐项处理：`hub register` 重建链接、"
                               "`hub refresh` 重算视图、gitlink 用 `hub induct` 纳入")
        return 1
    return 0 if _emit_result(data) else 1

def _cmd_status(args) -> int:
    vault_root = Path(args.vault)
    json_mode = getattr(args, "json", False)
    check = getattr(args, "check", False)
    git_text = GitBackend(vault_root).status()
    if json_mode:
        return _status_json(vault_root, args.host, check, git_text)
    print(git_text, end="")
    try:
        dev = load_device(vault_root, args.host or current_host())
    except FileNotFoundError:
        if check:
            print("status --check 停止：本机没有 device.toml"); return 1   # 缺 device → 非零
        return 0                       # 本机没有 device.toml：只报 git 状态，不回归旧行为
    try:
        rows = link_status(vault_root, dev)
    except SharedSkillsEscape as e:
        print(e)
        return 1
    if rows:
        print("skill 链接:")
        for state, label in rows:
            print(f"  [{state}] {label}")
    try:
        oc_rows = opencode_skill_status(vault_root, dev, _hub_root())
    except (PluginManifestError, PluginIdentityError, PluginContainmentError) as e:
        print(e)
        return 1
    if oc_rows:
        print("opencode skill 链接:")
        for state, label in oc_rows:
            print(f"  [{state}] {label}")
    links = tracked_gitlinks(vault_root) if check else []
    if links:
        # 插件健康判据读的是**盘上那个嵌套仓**,盘上永远是好的,所以它看不见这个坑。
        print("gitlink(空壳,别的设备 clone 拿不到内容,跑 `hub induct` 纳入):")
        for l in links:
            print(f"  [gitlink] {l}")
    if check:
        vh = view_health(vault_root, dev, _hub_root())
        print("memory 视图:")
        for state, label in vh:
            print(f"  [{state}] {label}")
        try:
            ph = plugin_health(vault_root, dev)
        except (PluginManifestError, PluginIdentityError, PluginContainmentError,
                PluginRepoUnavailable, CliUnavailable, UnsupportedVaultVersion) as e:
            print(f"plugin status 停止: {e}")
            return 1
        if ph:
            print("插件:")
            for h in ph:
                print(f"  [{h.state}] {h.name}@{h.tool}")
        return 1 if (links or any(x[0] != "ok" for x in (rows + oc_rows + vh))
                     or any(h.state != "ok" for h in ph)) else 0
    return 0

def _hub_root() -> Path:
    return Path(__file__).resolve().parents[1]      # 仓库根（hub/ 的上一级）

def _cmd_register(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    json_mode = getattr(args, "json", False)
    w = Writer(dry_run=args.dry_run); hub_root = _hub_root()
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            dev = load_device(vault_root, host)
            # ---- 预检/准备（只读；任何确定性错误在此抛、零写入）----
            to_link, ensured = plan_register_skills(vault_root, dev)
            hm_links = plan_hub_memory_skill(hub_root, dev)
            check_link_collisions(to_link, hm_links)     # 跨来源同名（如金库也有 hub-memory）→ 零写
            oc_link, oc_ensured = plan_link_opencode_skills(vault_root, dev, hub_root)  # opencode 自己的落点
            check_config(vault_root, host)
            writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
            plugin_plan = prepare_plugin_register(vault_root, dev)          # 预检并入 prepare
            hint = stale_skills_paths_hint(dev, vault_root)
            if hint:
                warnings.append(hint)
            # ---- 提交（预检全过之后才动笔）----
            commit_register_skills(to_link, w)
            commit_hub_memory_skill(hm_links, w)
            commit_link_opencode_skills(oc_link, w)
            write_config(vault_root, host, hub_root, w)
            commit_memory_views(writes, oc_plan, w)
            prep = execute_plugin_plan(plugin_plan, w)                      # 提交期执行 CLI
    except (RegisterConflict, FileNotFoundError, LinkError, SharedSkillsEscape,
            ConfigConflict, ViewScopeError, SharedMemoryError, BlockError,
            PluginManifestError, PluginIdentityError, PluginContainmentError,
            CliUnavailable, UnsupportedVaultVersion) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        data = {"dry_run": bool(args.dry_run),
                "skills_linked": len(ensured),
                "opencode_links": len(oc_ensured),
                "plugin": {"succeeded": len(prep.succeeded),
                           "skipped": len(prep.skipped),
                           "failed": len(prep.failed)}}
        if prep.failed:
            _emit_error("E_PARTIAL_FAILURE",
                        f"链接已就位，但 {len(prep.failed)} 个插件动作失败",
                        details={"failed": [[i, why] for i, why in prep.failed],
                                 "succeeded": list(prep.succeeded),
                                 "skipped": list(prep.skipped)},
                        retryable=True,
                        suggestion="查看 details.failed 里的原因，修复后重试 `hub register`")
            return 1
        return 0 if _emit_result(data, meta={"warnings": warnings}) else 1
    verb = '预计就位' if args.dry_run else '已就位'
    print(f"{verb} {len(ensured)} 个 skill 链接 + hub-memory")
    if oc_ensured:
        print(f"{verb} {len(oc_ensured)} 个 opencode skill 链接（它自己的 skill 目录）")
    for x in warnings:                               # opencode refuse 等：提示不阻断
        print("  ⚠", x)
    if plugin_plan.actions and not args.dry_run:
        print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
        for i, why in prep.failed:
            print(f"  ✗ {i}: {why}")
    return 0 if not prep.failed else 1

def _cmd_refresh(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    json_mode = getattr(args, "json", False)
    dry = getattr(args, "dry_run", False); w = Writer(dry_run=dry)
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            dev = load_device(vault_root, host)
            writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
            plugin_plan = prepare_plugin_refresh(vault_root, dev)
            commit_memory_views(writes, oc_plan, w)
            prep = execute_plugin_plan(plugin_plan, w)
    except (FileNotFoundError, ViewScopeError, SharedMemoryError, BlockError,
            PluginBumpNeeded, PluginRepoDirty, PluginManifestError, PluginIdentityError,
            PluginRepoUnavailable, PluginContainmentError, CliUnavailable,
            UnsupportedVaultVersion) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        data = {"dry_run": dry, "written": len(writes),
                "warnings": warnings,
                "plugin": {"succeeded": len(prep.succeeded),
                           "skipped": len(prep.skipped),
                           "failed": len(prep.failed)}}
        if prep.failed:
            _emit_error("E_PARTIAL_FAILURE",
                        f"视图已重算，但 {len(prep.failed)} 个插件动作失败",
                        details={"failed": [[i, why] for i, why in prep.failed],
                                 "succeeded": list(prep.succeeded),
                                 "skipped": list(prep.skipped)},
                        retryable=True,
                        suggestion="查看 details.failed 里的原因，修复后重试 `hub refresh`")
            return 1
        return 0 if _emit_result(data) else 1
    summary = {"written": len(writes), "warnings": warnings}
    print(f"memory 视图已重算: {summary}")
    for x in summary.get("warnings", []):
        print("  ⚠", x)
    if plugin_plan.actions and not dry:
        print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
    return 0 if not prep.failed else 1

def _cmd_promote(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    json_mode = getattr(args, "json", False)
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            load_device(vault_root, host)                      # 校验 host 存在
            dest = promote_skill(vault_root, host, args.tool, args.name,
                                 Writer(dry_run=args.dry_run))
    except (PromoteConflict, FileNotFoundError, ValueError, SharedSkillsEscape) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e)
        return 1
    if json_mode:
        return 0 if _emit_result({"dry_run": bool(args.dry_run), "dest": dest}) else 1
    print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    return 0

def _cmd_promote_memory(args) -> int:
    json_mode = getattr(args, "json", False)
    if bool(args.name) == bool(args.all):
        if json_mode:
            _emit_error("E_VALIDATION", "--name 与 --all 必须二选一",
                        suggestion="传 --name <名> 提升单条，或 --all 批量提升全部")
            return 2
        print("--name 与 --all 必须二选一"); return 2
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=args.dry_run)
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            load_device(vault_root, host)
            if args.all:
                done = promote_memory_all(vault_root, host, w)
                count = len(done)
            else:
                dest = promote_memory(vault_root, host, args.name, w)
                count = 1
    except (PromoteMemoryConflict, FileNotFoundError, ValueError) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        data = {"dry_run": bool(args.dry_run), "name": args.name,
                "all": bool(args.all), "count": count}
        if not args.all:
            data["dest"] = dest
        return 0 if _emit_result(data) else 1
    if args.all:
        print(f"{'预计提升' if args.dry_run else '已提升'} {len(done)} 条记忆")
    else:
        print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    return 0

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    json_mode = getattr(args, "json", False)

    try:
        # 先验后写(一):配了的源必须真的在。配置坏了**不是**"用户把记忆删光了",绝不能
        # 顺着镜像语义把金库清空——那是 2026-07-13 评审复现的 CRITICAL。
        preflight(dev)
        doomed = plan_deletions(vault_root, dev)
    except MissingSourceError as e:
        if json_mode:
            _emit_error("E_NOT_FOUND", f"collect 停止:device.toml 里的源路径有问题\n{e}",
                        retryable=False)
            return 1
        print("collect 停止:device.toml 里的源路径有问题\n")
        print(e)
        return 1

    try:
        # 先验后写(二):把金库里**所有**记忆先解析一遍(含 shared/ 和别的设备的)。
        #
        # 这一步过去在 run_all 的**后面**——写完才发现金库里有一条坏记忆,于是备份
        # 落了盘、collect 抛错、MEMORY.md 停在旧版本。而 SCHEMA §5 明确告诉加载器
        # "索引里没有的记忆,金库里就是没有,不必自己遍历兜底" —— 那条记忆就此从 C
        # 的视野里蒸发,尽管它明明躺在金库里;collect 和 sync 也双双卡死。
        #
        # 一条坏记忆该做的事是**在动笔之前**把这次 run 拦下来:什么都没写,索引也就
        # 永远不会陈旧。错误信息里已经点名了是哪个文件。
        load_vault(vault_root)
    except FrontmatterError as e:
        if json_mode:
            _emit_error("E_VALIDATION",
                        f"collect 停止:金库里有一条记忆解析不了(在写任何东西之前就停了,金库没变)\n{e}",
                        retryable=False)
            return 1
        print("collect 停止:金库里有一条记忆解析不了(在写任何东西之前就停了,金库没变)\n")
        print(e)
        return 1
    if doomed and not args.yes and not args.dry_run:
        if json_mode:
            _emit_error("E_VALIDATION",
                        f"这次 collect 会从金库删掉 {len(doomed)} 条记忆,但没给 --yes",
                        details={"doomed": list(doomed)},
                        retryable=False,
                        suggestion="确认无误后加 --yes 执行,或加 --dry-run 只预览不动盘")
            return 1
        print(f"这次会从金库删掉 {len(doomed)} 条记忆(本机源里已经没有它们了):")
        for n in doomed:
            print("  -", n)
        if input("确认删除? [y/N] ").strip().lower() != "y":
            print("已取消。")
            return 1

    w = Writer(dry_run=args.dry_run)
    with _stdout_to_stderr() if json_mode else nullcontext():
        rep = run_all(vault_root, dev, w)

    if json_mode:
        with _stdout_to_stderr():
            vault = load_vault(vault_root)
            _write_index(vault_root, vault, w)
        data = {
            "dry_run": bool(args.dry_run),
            "memory_written": len(rep.memory.written),
            "memory_deleted": len(rep.memory.deleted),
            "skipped_sensitive": len(rep.memory.skipped_sensitive),
            "skills": {tool: list(names) for tool, names in rep.skills.items()},
            "decl": {tool: {"repos": len(d.repos), "enabled": len(d.enabled),
                            "dirty": len(d.dirty)}
                     for tool, d in rep.decl.items()},
            "hits": [{"kind": h.kind, "path": str(h.path), "line": h.line,
                      "sample": h.sample} for h in rep.hits],
        }
        return 0 if _emit_result(data) else 1

    print(f"记忆: 写 {len(rep.memory.written)} 删 {len(rep.memory.deleted)}")
    if rep.memory.skipped_sensitive:
        print(f"  跳过 sensitive: {rep.memory.skipped_sensitive}")
    for tool, names in rep.skills.items():
        print(f"{tool} skill: {len(names)} 把 {names}")
    for tool, d in rep.decl.items():
        print(f"{tool} 插件: 自有 {len(d.repos)} 个, 第三方声明 {len(d.enabled)} 条")
        if d.dirty:
            print(f"  ⚠ 有未提交改动，快照里没有这些改动: {d.dirty}")
    if rep.hits:
        print(f"\n⚠ 疑似密钥 {len(rep.hits)} 处(**只是提醒,不阻断**;"
              f"确认是真密钥就挪进 ~/.claude/secrets/ 或给记忆打 sensitive: true):")
        for h in rep.hits:
            print(f"  {h.kind}  {h.path}:{h.line}  {h.sample}")

    # 无论是不是 --dry-run 都重新算一遍索引再"写"——闸在 Writer 里,dry-run 下
    # 这行只是打印预览、不落盘,不能在这里用 if not args.dry_run 跳过整段。
    vault = load_vault(vault_root)
    _write_index(vault_root, vault, w)
    return 0

def _cmd_bootstrap(args) -> int:
    """换新机:把金库里的加载器 skill 装进各工具,然后退场。

    这是提取器铁律("只写金库")的**唯一例外**——新机上还没有 skill(skill 自己
    也在金库里),这是个鸡生蛋。bootstrap 只打破这个循环,只写各工具的 skill 目录。
    剩下的(记忆怎么装、装哪些)交给 skill 自己跑。

    即便这次写的是工具的地盘而不是金库,dry-run 的闸依旧走 Writer(复用
    copy_tree 的"先清空目标再整棵拷"语义和预览打印),不在这里手写
    if args.dry_run 分支。
    """
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    json_mode = getattr(args, "json", False)
    src = vault_root / "shared" / "skills"
    if not src.is_dir():
        if json_mode:
            _emit_error("E_NOT_FOUND", "金库的 shared/skills/ 是空的，没有加载器 skill 可装。",
                        suggestion="先把加载器 skill 提升进金库的 shared/skills/")
            return 1
        print("金库的 shared/skills/ 是空的，没有加载器 skill 可装。")
        return 1
    w = Writer(dry_run=args.dry_run)
    installed = []
    for tool, home_key in (("claude", "CLAUDE_HOME"), ("codex", "CODEX_HOME")):
        home = dev.paths.get(home_key)
        if not home:
            continue
        for d in sorted(p for p in src.iterdir() if p.is_dir() and p.name.startswith("hub-")):
            dest = Path(home) / "skills" / d.name
            with _stdout_to_stderr() if json_mode else nullcontext():
                w.copy_tree(d, dest)
            installed.append(f"{tool}:{d.name}")
    if json_mode:
        return 0 if _emit_result({"dry_run": bool(args.dry_run),
                                  "installed": installed}) else 1
    verb = "预计会装" if args.dry_run else "已装"
    print(f"{verb} {len(installed)} 把加载器 skill: {installed}")
    print("接下来在各工具里跑那把 skill，它会自己去金库取记忆。")
    return 0

def _cmd_migrate_schema(args) -> int:
    json_mode = getattr(args, "json", False)
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            migrate_schema(Path(args.vault), args.to, Writer(dry_run=args.dry_run))
    except SchemaMigrationError as e:
        if json_mode:
            _emit_error("E_VALIDATION", str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        return 0 if _emit_result({"dry_run": bool(args.dry_run), "to": args.to}) else 1
    print(f"{'预计升到' if args.dry_run else '已升到'} version {args.to}")
    return 0

def _cmd_migrate_plugins(args) -> int:
    w = Writer(dry_run=args.dry_run)
    json_mode = getattr(args, "json", False)
    try:
        vault = Path(args.vault)
        if not w.dry_run:
            recover_pending(vault, w)      # C4：先恢复上次崩在".git 已移出"的事务，再做新 prepare
        plan = prepare_migration(Path(args.src), vault, Path(args.input))
        with _stdout_to_stderr() if json_mode else nullcontext():
            rep = execute_migration(plan, vault, w)
    except (MigrationInputError, InductionError, OSError, ValueError,
            subprocess.CalledProcessError) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        data = {
            "dry_run": bool(args.dry_run),
            "warnings": list(plan.warnings),
            "failed": [[aid, why] for aid, why in rep.failed],
            "succeeded": list(rep.done),
        }
        if rep.failed:
            _emit_error("E_PARTIAL_FAILURE",
                        f"迁移完成,但有 {len(rep.failed)} 项失败",
                        details={"failed": [[aid, why] for aid, why in rep.failed],
                                 "succeeded": list(rep.done),
                                 "warnings": list(plan.warnings)},
                        retryable=True,
                        suggestion="查看 details.failed 里的原因,修复后重试 `hub migrate-plugins`")
            return 1
        return 0 if _emit_result(data) else 1
    for warning in plan.warnings:
        print("  ⚠", warning)
    for aid, why in rep.failed:
        print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1

def _cmd_cutover_plugins(args) -> int:
    w = Writer(dry_run=args.dry_run)
    json_mode = getattr(args, "json", False)
    try:
        vault = Path(args.vault); dev = load_device(vault, args.host or current_host())
        with _stdout_to_stderr() if json_mode else nullcontext():
            plan = prepare_cutover(vault, dev, old_market=args.old_market)
            rep = execute_plugin_plan(plan, w)
    except (MigrationInputError, PluginManifestError, PluginIdentityError,
            PluginContainmentError, PluginRepoUnavailable, CliUnavailable,
            UnsupportedVaultVersion, FileNotFoundError) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if json_mode:
        data = {"dry_run": bool(args.dry_run),
                "plugin": {"succeeded": len(rep.succeeded),
                           "skipped": len(rep.skipped),
                           "failed": len(rep.failed)}}
        if rep.failed:
            _emit_error("E_PARTIAL_FAILURE",
                        f"cutover 完成,但有 {len(rep.failed)} 个插件动作失败",
                        details={"failed": [[i, why] for i, why in rep.failed],
                                 "succeeded": list(rep.succeeded),
                                 "skipped": list(rep.skipped)},
                        retryable=True,
                        suggestion="查看 details.failed 里的原因,修复后重试 `hub cutover-plugins`")
            return 1
        return 0 if _emit_result(data) else 1
    for aid, why in rep.failed:
        print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1

def _cmd_retire_plugin_sources(args) -> int:
    # 三段式 phase3：平台切换成功且验证后，才删除迁移输入声明的旧子仓。
    # 任一预检失败→零删除；只删声明的子仓，不碰外层容器。dry-run 与真跑共用 planner/executor。
    w = Writer(dry_run=args.dry_run)
    json_mode = getattr(args, "json", False)
    try:
        vault = Path(args.vault); dev = load_device(vault, args.host or current_host())
        with _stdout_to_stderr() if json_mode else nullcontext():
            plan = prepare_retire(Path(args.src), vault, Path(args.input), dev,
                                  old_market=args.old_market)
            rep = execute_retire(plan, w)
    except (MigrationInputError, CliUnavailable, UnsupportedVaultVersion,
            FileNotFoundError, OSError) as e:
        if json_mode:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        print(e); return 1
    if rep.blocked:
        if json_mode:
            _emit_error("E_VALIDATION",
                        f"退役被拒:还有 {len(rep.blocked)} 个活动引用(零删除)",
                        details={"blocked": list(rep.blocked)},
                        retryable=False,
                        suggestion="先解决 details.blocked 里的活动引用,再重试 `hub retire-plugin-sources`")
            return 1
        print("退役被拒（零删除）——先解决以下活动引用：")
        for b in rep.blocked:
            print(f"  ✗ {b}")
        return 1
    if json_mode:
        return 0 if _emit_result({"dry_run": bool(args.dry_run),
                                  "actions": [a.target for a in plan.actions]}) else 1
    if not plan.actions:
        print("没有待退役的旧源（已删或未声明）。")
        return 0
    verb = "预计删除" if args.dry_run else "已删除"
    for a in plan.actions:
        print(f"  {verb} {a.target}")
    return 0

def _cmd_induct(args) -> int:
    """把金库里带 `.git` 的目录正规纳入父仓跟踪(存文件,不存 gitlink)。

    日常新增插件不走 migrate-plugins,以前就没有任何一条路能做这件事:
    手 `git add` 得到 gitlink 空壳,而 migrate-plugins 见到 gitlink 直接拒绝。
    """
    vault_root = Path(args.vault)
    json_mode = getattr(args, "json", False)
    w = Writer(dry_run=args.dry_run)
    done = []
    fail = None
    with _stdout_to_stderr() if json_mode else nullcontext():
        for raw in args.path:
            rel = str(raw).replace("\\", "/").strip("/")
            if not (vault_root / rel).is_dir():
                if not json_mode:
                    print(f"induct 停止:{rel} 不是金库里的目录")
                fail = (2, f"induct 停止:{rel} 不是金库里的目录")
                break
            try:
                plan = prepare_induction(vault_root, rel)
                if args.dry_run:
                    print(f"  [dry-run] 摘 gitlink(若有)+ induct {rel}")
                else:
                    if drop_gitlink(vault_root, rel):
                        print(f"  已摘掉 {rel} 的 gitlink 条目(文件留在盘上)")
                    execute_induction(plan, vault_root, w)
                    print(f"  已纳入 {rel}")
                done.append(rel)
            except InductionError as e:
                if not json_mode:
                    print(f"induct 停止:{e}")
                fail = (1, f"induct 停止:{e}")
                break
    if fail is not None:
        rc, msg = fail
        if json_mode:
            if rc == 2:
                _emit_error("E_VALIDATION", msg,
                            suggestion="传金库内的相对路径(如 shared/plugins/foo)")
            else:
                _emit_error("E_VALIDATION", msg, retryable=False)
        return rc
    if json_mode:
        return 0 if _emit_result({"dry_run": bool(args.dry_run), "paths": done}) else 1
    if not args.dry_run:
        print("提示:改动还在 index 里,跑 `hub sync` 提交并推送。")
    return 0

DEFAULT_SYNC_MESSAGE = "chore(hub): sync"

def sync_message(args) -> str:
    """本次 sync 的 commit message。缺省是快照语义的固定串。

    金库大部分内容是**派生/快照**（记忆、索引、视图），那种提交没什么可说的，固定串反而
    诚实。但 `manifest.toml` / `<设备>/device.toml` 这类是**有意图的配置**，改动理由有价值、
    丢了就没了——这时候用 -m 写清楚。

    只做两件校验：去掉首尾空白；空串（或全空白）视为没给、回落缺省。**绝不接受空消息**：
    `git commit -m ""` 会造出一条没有标题的提交，在 log 里就是一行空白，事后谁都看不懂。
    """
    msg = (getattr(args, "message", None) or "").strip()
    return msg or DEFAULT_SYNC_MESSAGE

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    json_mode = getattr(args, "json", False)
    b = GitBackend(vault_root)
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            b.acquire()
    except RemoteUnavailable as e:          # 必须排在 ConflictError 前面(它是子类)
        if json_mode:
            _emit_error("E_NETWORK", f"sync 停止:够不着远端(网络/超时/认证):\n{e}",
                        retryable=True,
                        suggestion="检查网络/认证后重试 `hub sync`")
            return 1
        print("sync 停止:够不着远端(网络/超时/认证)——不是内容冲突,自动重试过了仍不通,手工解冲突没用")
        print(e)
        return 1
    except ConflictError as e:
        if json_mode:
            try:
                conflicted = b._conflicted_files() or []
            except Exception:
                conflicted = None
            _emit_error("E_VALIDATION", f"sync 停止:git 冲突,需手工解决:\n{e}",
                        details={"conflicted": conflicted} if conflicted is not None else None,
                        retryable=False,
                        suggestion="手工解决冲突后 `hub sync` 重试")
            return 1
        print("sync 停止:git 冲突,请手工解决后 `hub sync` 重试")
        print(e)
        return 1
    vault = load_vault(vault_root)
    errs = _lint(vault, load_lint_exempt(vault_root))
    if errs:
        if json_mode:
            _emit_error("E_VALIDATION", "sync 停止:lint 失败(敏感/裸路径/scope)",
                        details={"errors": errs},
                        retryable=False,
                        suggestion="修记忆内容或加豁免后重试 `hub sync`")
            return 1
        print("sync 停止:lint 失败(敏感/裸路径/scope):")
        for e in errs:
            print("  -", e)
        return 1
    msg = sync_message(args)
    committed = False
    try:
        with _stdout_to_stderr() if json_mode else nullcontext():
            _write_index(vault_root, vault, Writer())
            committed = bool(b.status().strip())
            b.publish(msg)
    except GitlinkTracked as e:
        if json_mode:
            _emit_error(_error_code(e), str(e),
                        details={"paths": e.paths},
                        retryable=False,
                        suggestion="跑 `hub induct --vault <金库> <路径>` 正规纳入后重试")
            return 1
        print("sync 停止:")
        print(e, end="")
        return 1
    except ChatsTracked as e:
        if json_mode:
            _emit_error(_error_code(e), str(e),
                        details={"paths": e.paths},
                        retryable=False,
                        suggestion="跑 `git rm --cached -r <路径>` 解除跟踪后重试")
            return 1
        print("sync 停止:")
        print(e, end="")
        return 1
    except RemoteUnavailable as e:
        if json_mode:
            _emit_error("E_PARTIAL_FAILURE",
                        f"sync 停止:本地已提交,但推不上去:\n{e}",
                        details={"state_preserved": True},
                        retryable=True,
                        suggestion="改动已安全留在本地,稍后重试 `hub sync` 即可")
            return 1
        print("sync 停止:本地已提交,但推不上去(网络/超时/认证),自动重试过了仍不通;稍后再 `hub sync` 即可")
        print(e)
        return 1
    data = {"message": msg, "committed": committed, "refreshed": False,
            "git_clean": not bool(b.status().strip())}
    if getattr(args, "refresh", False):
        if not json_mode:
            return _cmd_refresh(args)          # 传播 refresh 的返回码，不再吞掉失败
        try:
            with _stdout_to_stderr():
                dev = load_device(vault_root, args.host or current_host())
                writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
                plugin_plan = prepare_plugin_refresh(vault_root, dev)
                commit_memory_views(writes, oc_plan, Writer())
                prep = execute_plugin_plan(plugin_plan, Writer())
        except (FileNotFoundError, ViewScopeError, SharedMemoryError, BlockError,
                PluginBumpNeeded, PluginRepoDirty, PluginManifestError, PluginIdentityError,
                PluginRepoUnavailable, PluginContainmentError, CliUnavailable,
                UnsupportedVaultVersion) as e:
            _emit_error(_error_code(e), str(e), retryable=False)
            return 1
        if prep.failed:
            _emit_error("E_PARTIAL_FAILURE",
                        f"sync+refresh:视图已重算,但 {len(prep.failed)} 个插件动作失败",
                        details={"failed": [[i, why] for i, why in prep.failed],
                                 "succeeded": list(prep.succeeded),
                                 "skipped": list(prep.skipped)},
                        retryable=True,
                        suggestion="查看 details.failed 里的原因,修复后重试 `hub sync --refresh`")
            return 1
        data.update({"refreshed": True, "written": len(writes), "warnings": warnings,
                     "plugin": {"succeeded": len(prep.succeeded),
                                "skipped": len(prep.skipped),
                                "failed": len(prep.failed)}})
        return 0 if _emit_result(data) else 1
    if json_mode:
        return 0 if _emit_result(data) else 1
    print("提示：若 shared/ 有变化，运行 `hub refresh` 重算 memory 视图。")
    return 0

def _cmd_memory_read(args) -> int:
    vault = args.vault or read_config().get("vault")
    host = args.host or read_config().get("host") or current_host()
    json_mode = getattr(args, "json", False)
    if not vault:
        if json_mode:
            _emit_error("E_NOT_FOUND", "没有 --vault 也没有 ~/.hub/config.toml，无法定位金库",
                        suggestion="跑 `hub register` 绑定金库，或显式传 --vault <路径>")
            return 1
        print("没有 --vault 也没有 ~/.hub/config.toml，无法定位金库"); return 1
    try:
        body = read_memory(Path(vault), host, args.tool, args.name)
    except (MemoryNotInView, FileNotFoundError, ViewScopeError, SharedMemoryError) as e:
        if json_mode:
            _emit_error("E_NOT_FOUND", str(e), retryable=False,
                        suggestion="确认名字拼写、scope 含 global 或本机 class/project、"
                                   "tool 属于该工具；可先 `hub register` 刷新视图")
            return 1
        print(e); return 1
    if json_mode:
        return 0 if _emit_result({"name": args.name, "tool": args.tool, "host": host,
                                  "vault": str(Path(vault)), "body": body}) else 1
    print(body, end="")
    return 0

def _write_index(vault_root: Path, vault, w: Writer) -> None:
    w.write_text(vault_root / "MEMORY.md", render_memory_index(vault.memories, vault_root))

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    _add_output_flags(common)
    p = _JsonFriendlyParser(
        prog="hub",
        description="hub CLI——跨工具共享记忆金库。"
        " LLMs/agents: run 'hub --ai-help' for usage guidance.")
    _add_output_flags(p)
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", parents=[common])
    st.add_argument("--check", action="store_true", help="健康检查，不健康返回非零")
    st.set_defaults(func=_cmd_status)

    sy = sub.add_parser("sync", parents=[common])
    sy.add_argument("--refresh", action="store_true", help="成功后串联 hub refresh 并传播其返回码")
    sy.add_argument("-m", "--message", default=None,
                    help=f"本次提交说明（缺省 {DEFAULT_SYNC_MESSAGE!r}）。"
                         "配置类改动（manifest/device.toml）值得写清理由，日常快照用缺省即可")
    sy.set_defaults(func=_cmd_sync)
    for name, fn in (("collect", _cmd_collect), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("--dry-run", action="store_true",
                        help="只报告会写哪些文件，一个字节都不落盘")
        sp.add_argument("--yes", action="store_true",
                        help="不询问，直接执行（含删除）")
        sp.set_defaults(func=fn)

    reg = sub.add_parser("register", parents=[common])
    reg.add_argument("--dry-run", action="store_true",
                     help="只报告会建哪些链接，一个字节都不落盘")
    reg.set_defaults(func=_cmd_register)

    rf = sub.add_parser("refresh", parents=[common])
    rf.add_argument("--dry-run", action="store_true")
    rf.set_defaults(func=_cmd_refresh)

    pro = sub.add_parser("promote", parents=[common])
    pro.add_argument("--tool", required=True, choices=["claude", "codex"],
                     help="备份区里哪个工具的 skill")
    pro.add_argument("--name", required=True, help="要提升的 skill 名（单个目录名，不含路径）")
    pro.add_argument("--dry-run", action="store_true",
                     help="只报告会提升到哪，一个字节都不落盘")
    pro.set_defaults(func=_cmd_promote)

    pm = sub.add_parser("promote-memory", parents=[common])
    pm.add_argument("--name", default=None, help="要提升的记忆名（单个，不含路径/后缀）")
    pm.add_argument("--all", action="store_true", help="批量提升本机备份区全部记忆")
    pm.add_argument("--dry-run", action="store_true")
    pm.set_defaults(func=_cmd_promote_memory)

    ind = sub.add_parser("induct", parents=[common])
    ind.add_argument("path", nargs="+", help="金库内的相对路径(如 shared/plugins/foo)")
    ind.add_argument("--dry-run", action="store_true")
    ind.set_defaults(func=_cmd_induct)

    mig = sub.add_parser("migrate-schema", parents=[common])
    mig.add_argument("--to", type=int, required=True)
    mig.add_argument("--dry-run", action="store_true")
    mig.set_defaults(func=_cmd_migrate_schema)

    mp = sub.add_parser("migrate-plugins", parents=[common])
    mp.add_argument("--src", required=True)
    mp.add_argument("--input", required=True)
    mp.add_argument("--dry-run", action="store_true")
    mp.set_defaults(func=_cmd_migrate_plugins)

    cp = sub.add_parser("cutover-plugins", parents=[common])
    cp.add_argument("--old-market", default="xu-local")
    cp.add_argument("--dry-run", action="store_true")
    cp.set_defaults(func=_cmd_cutover_plugins)

    rp = sub.add_parser("retire-plugin-sources", parents=[common])
    rp.add_argument("--src", required=True, help="旧插件仓容器目录（如 ~/.claude/plugins-dev）")
    rp.add_argument("--input", required=True, help="迁移输入（声明要退役哪些子仓）")
    rp.add_argument("--old-market", default="xu-local")
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=_cmd_retire_plugin_sources)

    mr = sub.add_parser("memory-read")
    _add_output_flags(mr)
    mr.add_argument("--vault", default=None)
    mr.add_argument("--host", default=None)
    mr.add_argument("--tool", required=True, choices=["claude", "codex", "opencode"])
    mr.add_argument("--name", required=True)
    mr.set_defaults(func=_cmd_memory_read)

    # secrets：**不带 parents=[common]**。密钥库在 ~/.claude/secrets/，与金库无关，
    # 不该跟着吃一个 required 的 --vault。
    sec = sub.add_parser("secrets", help="密钥：本体只存一处，别处只写 hub:// 引用")
    ssub = sec.add_subparsers(dest="subcmd", required=True)

    se = ssub.add_parser("exec", help="给 AI 的通道：只能跑预先声明好的 profile")
    se.add_argument("profile")
    # REMAINDER 而不是 "*"：尾参里的 --force / --out=x 必须原样透传给目标程序，
    # 不能被 hub 自己的 argparse 抢走。
    se.add_argument("args", nargs=argparse.REMAINDER)
    se.set_defaults(func=cmd_exec)

    sr = ssub.add_parser("run", help="只给人：在真实终端里，用某 profile 的密钥跑任意命令")
    sr.add_argument("--profile", required=True)
    sr.add_argument("argv", nargs=argparse.REMAINDER)
    sr.set_defaults(func=cmd_run)

    srd = ssub.add_parser("render",
                          help="只给人：把某 profile 的密钥以 KEY=value 打到终端（没有 --out）")
    srd.add_argument("--profile", required=True)
    srd.set_defaults(func=cmd_render)

    su = ssub.add_parser("unlock", help="只给人：需要在控制台键入确认短语")
    su.add_argument("--minutes", type=int, default=10)
    su.set_defaults(func=cmd_unlock)
    return p

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
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

def main(argv: list[str]) -> int:
    global _MAIN_ARGV
    _MAIN_ARGV = argv if argv is not None else sys.argv[1:]
    _make_console_output_tolerant()
    if _handle_ai_help(_MAIN_ARGV):
        return 0
    args = build_parser().parse_args(_MAIN_ARGV)
    json_mode = _json_requested(_MAIN_ARGV)
    setattr(args, "json", json_mode)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        if json_mode:
            _emit_error("E_INTERRUPTED", "interrupted", retryable=True)
        else:
            print("interrupted", file=sys.stderr)
        return 1
    except Exception as e:
        if json_mode:
            _emit_error("E_INTERNAL", f"{type(e).__name__}: {e}")
        else:
            print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
