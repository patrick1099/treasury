import json, subprocess
from dataclasses import dataclass

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
        p = subprocess.run([cmd.tool, *cmd.argv], capture_output=True, text=True)
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
    data = _json(tool, ["plugin", "list", "--json"], runner)
    out = {}
    if tool == "claude":                              # [{id,version,enabled,scope,installPath}]
        for p in data:
            _, _, mkt = p["id"].partition("@")
            out[p["id"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                     mkt, p.get("installPath", ""))
    else:                                             # {installed:[{pluginId,version,enabled,marketplaceName,source{path}}]}
        for p in data.get("installed", []):
            out[p["pluginId"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                           p.get("marketplaceName", ""),
                                           (p.get("source") or {}).get("path", ""))
    return out

def marketplaces(tool, runner=None) -> dict:
    data = _json(tool, ["plugin", "marketplace", "list", "--json"], runner)
    if tool == "claude":                              # [{name,source,path,installLocation}]
        return {m["name"]: (m.get("path") or m.get("installLocation", "")) for m in data}
    return {m["name"]: m.get("root", "") for m in data.get("marketplaces", [])}  # codex

def preflight_cli(tool, needed, runner=None) -> None:
    plug = run_cli(CliCommand(tool, ["plugin", "--help"]), runner=runner)
    mkt = run_cli(CliCommand(tool, ["plugin", "marketplace", "--help"]), runner=runner)
    if plug.returncode != 0 or mkt.returncode != 0:
        raise CliUnavailable(f"{tool} plugin CLI 不可用（缺失或不认子命令）")
    have = plug.stdout + mkt.stdout
    for sub in needed:
        if sub not in have:
            raise CliUnavailable(f"{tool} plugin 缺子命令 `{sub}`")
