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
from hub.guard import check_source, read_source_text
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
    """写 plugins.toml。写不出来的 [hooks] **只跳过那一张表**,不带走整份清单。

    dump_toml 遇到没见过的形状就抛错,这条**是对的**(宁可响不可错,见 tomlout.py):
    拿 str() 把嵌套结构糊成语法正确、语义错误的 TOML 才是真正的坏。这里改的不是
    "炸不炸",是**炸的范围**。

    Claude 的 `hooks` 是 dict of lists,写出器只认 str/bool/int → 一个用户级 hook
    就让 collect 抛错。而清单是**最后**写的:记忆、skill、插件快照都已经落盘,
    plugins.toml 和 MEMORY.md 却没有 —— 金库停在半成品状态,而且之后**每一次**
    collect 都在同一处炸,备份从此冻结。对一个"别丢"的备份区来说,TOML 写出器缺一张
    装饰性的表,不该是整份备份的死刑。

    所以:[hooks] 写得出来就写,写不出来就跳过 + 大声警告(静默跳过等于骗用户说
    "hook 备份了"),清单的其余部分照常落盘。**别为此去写通用嵌套表序列化器**(YAGNI):
    真要备份 hook,先想清楚它在金库里该长什么样(SCHEMA §12 的阶段 B)。
    """
    tables: list[tuple[str, dict]] = []
    for m in r.repos:
        tables.append((f"repos.{m.name}",
                       {"remote": m.remote or "", "sha": m.sha, "dirty": m.dirty}))
    tables.append(("enabled", r.enabled))
    tables.append(("marketplaces", r.marketplaces))

    text = None
    if r.hooks:
        try:
            text = dump_toml(tables + [("hooks", r.hooks)])
        except ValueError as e:
            print(f"⚠ plugins.toml 跳过了 [hooks] 表(备份里**没有**这些 hook): "
                  f"{sorted(r.hooks)}\n"
                  f"  原因: {e}\n"
                  f"  清单的其余部分照常写。要备份 hook 需要给 TOML 写出器补嵌套表"
                  f"(见 SCHEMA.md §12),那还没做。")
    if text is None:
        # 注意:这一行在 hooks 之外的键也坏掉时会**再抛一次**——那正是我们要的:
        # 口子只给 hooks 开,别的形状照旧炸。
        text = dump_toml(tables)
    w.write_text(Path(dest_dir) / "plugins.toml", text)

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
        raw = json.loads(read_source_text(settings))    # 读原语自己也过一遍闸
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
    raw = tomllib.loads(read_source_text(config))       # 读原语自己也过一遍闸
    for name, spec in (raw.get("plugins") or {}).items():
        r.enabled[name] = bool(spec.get("enabled", False))
    for name, spec in (raw.get("marketplaces") or {}).items():
        r.marketplaces[name] = f"{spec.get('source_type', '?')}:{spec.get('source', '')}"
    r.hooks = raw.get("hooks") or {}
    _write_manifest(Path(dest_dir), r, w)
    return r
