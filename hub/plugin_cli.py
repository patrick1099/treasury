import json, subprocess
from hub.platforms import cli_dialect
from dataclasses import dataclass

# 插件 CLI 的命令与输出格式按「方言」分支（平台适配器声明 cli_dialect），不按平台名分支。
# 现在只有 claude / codex 两种方言；新方言必须在这里显式补上解析，否则明确报错，
# 绝不落进某个已有方言的默认分支。
class CliUnavailable(RuntimeError): pass

@dataclass
class CliCommand:
    tool: str
    argv: list
    def describe(self) -> str:
        return f"{self.tool} " + " ".join(self.argv)

@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str

@dataclass
class Installed:
    version: str
    enabled: bool
    marketplace: str
    source_path: str

def run_cli(cmd: CliCommand, runner=None) -> CliResult:
    if runner is not None:
        return runner([cmd.tool, *cmd.argv])          # 注入假 runner：收 [tool, *argv]
    try:
        # 显式 utf-8 + replace:平台 CLI 的输出一律按 utf-8 读。绝不能交给本机 locale——
        # cp936 机器上 `claude plugin --help` 的非 ASCII 字符会让读取线程抛
        # UnicodeDecodeError,p.stdout 静默变成 None(返回码仍是 0),下游 str 运算才崩。
        p = subprocess.run([cmd.tool, *cmd.argv], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except OSError as e:
        raise CliUnavailable(f"{cmd.tool} CLI 不可执行: {e}") from e
    return CliResult(p.returncode, p.stdout, p.stderr)

def _json(tool, argv, runner):
    r = run_cli(CliCommand(tool, argv), runner=runner)
    if r.returncode != 0:
        raise CliUnavailable(f"{tool} {' '.join(argv)} 失败: {r.stderr.strip() or r.returncode}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise CliUnavailable(f"{tool} {' '.join(argv)} 未返回合法 JSON: {e}") from e

def installed_plugins(tool, runner=None) -> dict:
    dialect = cli_dialect(tool)
    data = _json(tool, ["plugin", "list", "--json"], runner)
    out = {}
    if dialect == "claude":                           # [{id,version,enabled,scope,installPath}]
        for p in data:
            _, _, mkt = p["id"].partition("@")
            out[p["id"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                     mkt, p.get("installPath", ""))
    elif dialect == "codex":                          # {installed:[{pluginId,version,enabled,marketplaceName,source{path}}]}
        for p in data.get("installed", []):
            out[p["pluginId"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                           p.get("marketplaceName", ""),
                                           (p.get("source") or {}).get("path", ""))
    else:
        raise ValueError(f"{tool} 的插件 CLI 方言 {dialect!r} 没有对应的 list 解析")
    return out

def marketplaces(tool, runner=None) -> dict:
    dialect = cli_dialect(tool)
    data = _json(tool, ["plugin", "marketplace", "list", "--json"], runner)
    if dialect == "claude":                           # [{name,source,path,installLocation}]
        return {m["name"]: (m.get("path") or m.get("installLocation", "")) for m in data}
    if dialect == "codex":
        return {m["name"]: m.get("root", "") for m in data.get("marketplaces", [])}
    raise ValueError(f"{tool} 的插件 CLI 方言 {dialect!r} 没有对应的 marketplace 解析")

def preflight_cli(tool, needed, runner=None) -> None:
    plug = run_cli(CliCommand(tool, ["plugin", "--help"]), runner=runner)
    mkt = run_cli(CliCommand(tool, ["plugin", "marketplace", "--help"]), runner=runner)
    if plug.returncode != 0 or mkt.returncode != 0:
        raise CliUnavailable(f"{tool} plugin CLI 不可用（缺失或不认子命令）")
    have = plug.stdout + mkt.stdout
    for sub in needed:
        if sub not in have:
            raise CliUnavailable(f"{tool} plugin 缺子命令 `{sub}`")
