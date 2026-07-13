"""声明流水线:自己写的插件拷源码,第三方插件抄声明。

按"是不是你的产出"分,不按工具分:

- 你写的(plugins-dev 那几个仓)→ 源码快照。GitHub 没了就真没了,这是唯一副本风险。
- 第三方(superpowers/gmail/github/clangd-lsp)→ 抄声明。别人的代码,市场在就能重装;
  两边缓存共 65 MB,里面是 LSP 二进制,换台 Mac 就是废的,而且每次更新都在 git 里堆 delta。

hooks 也在这里抄——它读的本来就是同两个文件(settings.json / config.toml)。
Claude 目前没有用户级 hook(全在插件里),Codex 也没有,所以通常是空的。
"""
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from hub.collect.errors import require_source
from hub.guard import check_source
from hub.snapshot import RepoMeta, is_git_repo, snapshot_repo
from hub.tomlout import dump_toml
from hub.writer import Writer

@dataclass
class DeclResult:
    repos: list[RepoMeta] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)      # 有未提交改动的仓 → 快照里没有那些改动
    enabled: dict = field(default_factory=dict)
    marketplaces: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)

def _write_manifest(dest_dir: Path, r: DeclResult, w: Writer) -> None:
    tables: list[tuple[str, dict]] = []
    for m in r.repos:
        tables.append((f"repos.{m.name}",
                       {"remote": m.remote or "", "sha": m.sha, "dirty": m.dirty}))
    tables.append(("enabled", r.enabled))
    tables.append(("marketplaces", r.marketplaces))
    if r.hooks:
        tables.append(("hooks", r.hooks))
    w.write_text(Path(dest_dir) / "plugins.toml", dump_toml(tables))

def collect_claude_decl(plugin_repos: Path | None, settings: Path | None,
                        dest_dir: Path, w: Writer) -> DeclResult:
    r = DeclResult()
    dest_dir = Path(dest_dir)

    if plugin_repos is not None:
        plugin_repos = Path(plugin_repos)
        check_source(plugin_repos)
        require_source(plugin_repos, "[sources.claude] plugin_repos")
        for d in sorted(p for p in plugin_repos.iterdir() if p.is_dir()):
            check_source(d)                 # 硬闸:每个插件仓目录
            if not is_git_repo(d):
                continue                    # 不是插件仓（如 plugins-dev/docs）
            meta = snapshot_repo(d, dest_dir / "plugins" / d.name, w)
            r.repos.append(meta)
            if meta.dirty:
                r.dirty.append(meta.name)

    if settings is not None:
        settings = Path(settings)
        check_source(settings)
        require_source(settings, "[sources.claude] settings", kind="file")
        raw = json.loads(settings.read_text(encoding="utf-8"))
        r.enabled = dict(raw.get("enabledPlugins", {}))
        for name, spec in (raw.get("extraKnownMarketplaces") or {}).items():
            s = (spec or {}).get("source", {})
            r.marketplaces[name] = f"{s.get('source', '?')}:{s.get('path') or s.get('url', '')}"
        r.hooks = raw.get("hooks") or {}

    _write_manifest(dest_dir, r, w)
    return r

def collect_codex_decl(config: Path | None, dest_dir: Path, w: Writer) -> DeclResult:
    r = DeclResult()
    if config is None:
        _write_manifest(Path(dest_dir), r, w)
        return r
    config = Path(config)
    check_source(config)
    require_source(config, "[sources.codex] settings", kind="file")
    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    for name, spec in (raw.get("plugins") or {}).items():
        r.enabled[name] = bool(spec.get("enabled", False))
    for name, spec in (raw.get("marketplaces") or {}).items():
        r.marketplaces[name] = f"{spec.get('source_type', '?')}:{spec.get('source', '')}"
    r.hooks = raw.get("hooks") or {}
    _write_manifest(Path(dest_dir), r, w)
    return r
