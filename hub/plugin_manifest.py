import json, tomllib
from dataclasses import dataclass
from pathlib import Path

class PluginManifestError(RuntimeError): pass
class PluginIdentityError(RuntimeError): pass

@dataclass
class PluginEntry:
    name: str; platforms: list[str]; remote: str | None; sha: str | None

def _mf_path(v): return Path(v)/"shared/plugins/manifest.toml"

def load_plugin_manifest(vault_root) -> list[PluginEntry]:
    p = _mf_path(vault_root)
    if not p.exists(): return []
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    out = []
    for name, body in raw.items():
        if "platforms" not in body:
            raise PluginManifestError(f"{name}: manifest 缺 platforms")
        repo = body.get("repository", {})
        out.append(PluginEntry(name, list(body["platforms"]),
                               repo.get("remote"), repo.get("sha")))
    return out

def _cp_dir(v, name): return Path(v)/"shared/plugins"/name/".claude-plugin"

def plugin_version(vault_root, name) -> str:
    return json.loads((_cp_dir(vault_root,name)/"plugin.json").read_text(encoding="utf-8"))["version"]

def check_identity(vault_root, entry: PluginEntry) -> None:
    n = entry.name
    cp = _cp_dir(vault_root, n)
    try:
        mkt = json.loads((cp/"marketplace.json").read_text(encoding="utf-8"))
        plug = json.loads((cp/"plugin.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PluginIdentityError(f"{n}: 缺 .claude-plugin 清单 ({e})")
    names = {"dir": n, "mkt": mkt.get("name"),
             "mkt_plugin": (mkt.get("plugins") or [{}])[0].get("name"),
             "plugin.json": plug.get("name")}
    bad = {k: v for k, v in names.items() if v != n}
    if bad:
        raise PluginIdentityError(f"{n}: 身份不一致 {bad}（须全等 {n}）")
