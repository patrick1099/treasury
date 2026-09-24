"""C 的状态检查（只读）。

只检查 shared/skills/ 里的**期望项**——没 manifest 就无法安全判定某额外目录
以前归不归 hub 管，故本机自带的本地 skill 一律不报，免得把用户的东西冤成残留。

只查本机启用的平台（hub.platforms）。启用的平台加载失败或依赖缺失，报一行 unavailable，
其余平台照常检查；停用的平台完全不碰。
"""
import os
from dataclasses import dataclass
from pathlib import Path
from hub.model import DeviceProfile
from hub.register import skill_targets
from hub.fslink import resolves_to
from hub.vaultpaths import shared_skills_dir, within_shared_skills
from hub import platforms


def link_status(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, str]]:
    vault_root = Path(vault_root)
    shared = shared_skills_dir(vault_root)             # 逃逸容器→抛 SharedSkillsEscape
    shared_skills = sorted((d for d in shared.iterdir()
                            if d.is_dir() and within_shared_skills(d, vault_root)),
                           key=lambda p: p.name) if shared.is_dir() else []
    rows: list[tuple[str, str]] = []
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                rows.append(("conflict", f"{target_dir}（skills 容器是链接/非目录）"))
                continue
        for src in shared_skills:
            link = target_dir / src.name
            label = str(link)
            if not os.path.lexists(link):
                rows.append(("missing", label))
            elif resolves_to(link, src):
                rows.append(("ok", label))
            else:
                rows.append(("conflict", label))     # 指别处 / 用户真目录 / 解析失败
    return rows


@dataclass
class PlatformRows:
    name: str
    title: str
    key: str | None          # status --json 里的键；None = 只进健康汇总
    rows: list


def platform_status(vault_root: Path, dev, hub_root: Path) -> list[PlatformRows]:
    """各启用平台自己的附加检查（opencode 的 skill 链、dsh 的 loader……）。

    平台不可用（适配器加载失败 / 抛 PlatformUnavailable）→ 一行 unavailable，继续下一个。
    其它异常（清单坏了、链接逃逸）照旧上抛，由调用方按原来的方式停下。
    """
    out: list[PlatformRows] = []
    for x in platforms.enabled(dev):
        if x.adapter is None:
            out.append(PlatformRows(x.name, f"{x.name} 平台", None,
                                    [("unavailable", f"{x.name}（{x.error}）")]))
            continue
        a = x.adapter
        try:
            rows = a.status_rows(vault_root, dev, hub_root)
        except platforms.PlatformUnavailable as e:
            rows = [("unavailable", f"{x.name}（{e}）")]
        if a.status_title is None and not rows:
            continue
        out.append(PlatformRows(x.name, a.status_title or f"{x.name} 平台", a.status_key, rows))
    return out


def view_health(vault_root: Path, dev: DeviceProfile, hub_root: Path) -> list[tuple[str, str]]:
    """memory 视图健康。只读。状态 ∈ {ok, missing, conflict, stale, degraded, malformed}。"""
    from hub.memwire import view_path
    from hub.hubconfig import hub_config_path, read_config
    from hub.memview import load_shared_memories, shared_hash
    rows: list[tuple[str, str]] = []
    # ① config.toml：存在且 vault/host 一致
    cfg = read_config()
    if not cfg:
        rows.append(("missing", str(hub_config_path())))
    elif cfg.get("vault") != Path(vault_root).resolve().as_posix() or cfg.get("host") != dev.host:
        rows.append(("conflict", f"{hub_config_path()}（绑定的 vault/host 与本次不符）"))
    else:
        rows.append(("ok", str(hub_config_path())))
    # ② hub-memory 链：目标必须精确指向 hub 包里那把
    hm_src = Path(hub_root) / "hub" / "skills" / "hub-memory"
    for target_dir in skill_targets(dev):
        link = target_dir / "hub-memory"
        if not os.path.lexists(link):
            rows.append(("missing", str(link)))
        else:
            rows.append(("ok" if resolves_to(link, hm_src) else "conflict", str(link)))
    # ③ 各启用平台的视图 + 新鲜度（视图头嵌的 shared_hash 与当前 shared 比对）
    cur = shared_hash(load_shared_memories(vault_root))
    loaded = platforms.enabled(dev)
    for x in loaded:
        v = view_path(x.name)
        if not v.exists():
            rows.append(("missing", str(v))); continue
        embedded = ""
        for line in v.read_text(encoding="utf-8").splitlines():
            if "shared_hash:" in line:
                embedded = line.split("shared_hash:")[1].replace("-->", "").strip(); break
        rows.append(("ok" if embedded == cur else "stale", str(v)))
    # ④ 各平台把视图接进自己入口文件的那一处（受管块必须良构、Codex 块还要验版本、opencode 条目）
    for x in loaded:
        if x.adapter is not None:
            rows += x.adapter.wiring_health(dev, cur)
    return rows
