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

def _real_plugin_dir(vault_root, name):
    """在 shared/plugins/ 下按 casefold 找磁盘上真实的目录项，拒绝大小写错配/歧义。"""
    plugins_dir = Path(vault_root) / "shared/plugins"
    if not plugins_dir.is_dir():
        raise PluginIdentityError(f"{name}: shared/plugins 目录不存在")
    matches = [c for c in plugins_dir.iterdir() if c.is_dir() and c.name.casefold() == name.casefold()]
    if len(matches) != 1:
        raise PluginIdentityError(
            f"{name}: shared/plugins 下按名匹配到 {len(matches)} 个目录 "
            f"({[m.name for m in matches]})，须恰好 1 个")
    real = matches[0]
    if real.name != name:
        raise PluginIdentityError(
            f"{name}: 磁盘目录名 {real.name!r} 与清单名 {name!r} 大小写不一致")
    return real

def check_identity(vault_root, entry: PluginEntry) -> None:
    n = entry.name
    real_dir = _real_plugin_dir(vault_root, n)
    cp = real_dir / ".claude-plugin"
    try:
        mkt = json.loads((cp/"marketplace.json").read_text(encoding="utf-8"))
        plug = json.loads((cp/"plugin.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PluginIdentityError(f"{n}: 缺 .claude-plugin 清单 ({e})")
    names = {"mkt": mkt.get("name"),
             "mkt_plugin": (mkt.get("plugins") or [{}])[0].get("name"),
             "plugin.json": plug.get("name")}
    bad = {k: v for k, v in names.items() if v != n}
    if bad:
        raise PluginIdentityError(f"{n}: 身份不一致 {bad}（须全等 {n}）")
