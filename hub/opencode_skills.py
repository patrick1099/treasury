"""opencode 的原生落点：把金库里的 skill 逐个活链进 opencode **自己**的 skill 目录。

为什么不并进 `register.skill_targets` 而单开一个模块——两处不一样：

1. **落点不同**。Claude/Codex 拿的是 `<home>/skills`；opencode 拿的是它自己的
   `<config>/skill`（它内置文档里 "Global skills" 那一行的位置）。链到自己家，
   opencode 就不必再去读 `~/.claude/` 或 `~/.agents/`——那两处是它的**兼容扫描**，
   靠它同步等于把别家的目录约定变成事实标准。配上环境变量
   `OPENCODE_DISABLE_EXTERNAL_SKILLS=1` 可以把兼容扫描整个关掉（那是环境变量、
   不是配置项，hub 装不了，只能提示）。
2. **来源集合也不同，且更宽**。Claude/Codex 的插件走各自的插件安装通道，只有独立
   skill 需要建链；opencode **没有插件通道**，所以插件里打包的 skill 也得逐个链过去。
   这里枚举的是 `shared/skills/*` ＋ `shared/plugins/<p>/skills/*`。

与 register 同一套脾气：只读预检全过才动笔、任何冲突零写入、link-only（建链失败就抛，
绝不静默拷贝）、**从不删任何路径**。因此源侧删掉一个 skill、或从 device.toml 的 enabled
里去掉一个插件之后，这边会留下一条不再期望的链接——`opencode_skill_status` 把它报成
`orphan`（判据是链接目标指回金库/hub 包，那是归属证据），由人来清，hub 不自作主张删。
"""
import os
from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.fslink import resolves_to
from hub.register import RegisterConflict
from hub.vaultpaths import shared_skills_dir, within_shared_skills
from hub.plugin_manifest import load_plugin_manifest
from hub.plugin_ops import _containment, PluginContainmentError, _norm

def _link_target(entry: Path) -> str | None:
    """entry 是链接就返回它的目标，**不要求目标还存在**（断链也得问得出来）；不是链接→None。

    Windows 的 junction 上 `os.path.islink` 是 False、`os.readlink` 却读得出来，所以
    判定只能靠 readlink 试一把。返回值可能带 `\\\\?\\` 前缀，比对前交给 _norm 归一。
    """
    try:
        return os.readlink(entry)
    except OSError:
        return None

# opencode 的 "Global skills" 目录名。它单复数都扫（实测 skill/ 与 skills/ 都认），
# 取单数与同级的 agent/ command/ 保持一致。
_SKILL_DIRNAME = "skill"

def opencode_skill_dir(dev: DeviceProfile) -> Path | None:
    """本机 opencode 的 skill 落点；设备没接 opencode 则 None（不是错误，是没装）。

    优先 device.toml 的 OPENCODE_HOME（配置目录本身），否则从 OPENCODE_CONFIG 反推它的
    父目录。两个都没有 → None：**绝不因为 `~/.config/opencode` 恰好存在就往里写**，
    与 opencode_cfg 对那份带密钥的 json 的态度一致。
    """
    home = dev.paths.get("OPENCODE_HOME")
    if home:
        return Path(home) / _SKILL_DIRNAME
    cfg = dev.paths.get("OPENCODE_CONFIG")
    if cfg:
        return Path(cfg).parent / _SKILL_DIRNAME
    return None

def _standalone_sources(vault_root: Path) -> list[tuple[str, Path]]:
    """shared/skills/<name>——与 register 同一批源（容器逃逸→SharedSkillsEscape）。"""
    shared = shared_skills_dir(vault_root)
    if not shared.is_dir():
        return []
    return [(d.name, d) for d in sorted(shared.iterdir(), key=lambda p: p.name)
            if d.is_dir() and within_shared_skills(d, vault_root)]

def _plugin_sources(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, Path]]:
    """shared/plugins/<p>/skills/<name>——只取「清单声明支持 opencode」且「本机 enabled」的插件。

    两道闸都要过：manifest 的 platforms 说这插件支持 opencode，device.toml 的
    [plugins.opencode].enabled 说这台机器要它。与 claude/codex 的判定口径一致。
    """
    enabled = set(dev.plugins.get("opencode", []))
    if not enabled:
        return []
    out: list[tuple[str, Path]] = []
    for entry in load_plugin_manifest(vault_root):
        if "opencode" not in entry.platforms or entry.name not in enabled:
            continue
        _containment(vault_root, entry.name)        # 逃逸/坏链/非目录→PluginContainmentError
        skills = Path(vault_root) / "shared" / "plugins" / entry.name / "skills"
        if not skills.is_dir():
            continue
        base = os.path.realpath(skills)
        for d in sorted(skills.iterdir(), key=lambda p: p.name):
            if not d.is_dir() or not (d / "SKILL.md").is_file():
                continue                            # 没 SKILL.md 的目录 opencode 也不认，不链
            real = os.path.realpath(d)
            if real != base and not real.startswith(base + os.sep):
                raise PluginContainmentError(
                    f"shared/plugins/{entry.name}/skills/{d.name} 经链接逃出插件目录，拒绝建链。")
            out.append((d.name, d))
    return out

def _hub_memory_source(hub_root: Path | None) -> list[tuple[str, Path]]:
    """随包发的 hub-memory：源在 hub 包里、**不在金库**，所以上面两批都枚举不到它。

    漏了它的后果是隐蔽的：兼容扫描还开着时，opencode 仍能从 ~/.claude/skills 读到，
    一切正常；等真把 OPENCODE_DISABLE_EXTERNAL_SKILLS 打开，它才无声消失。
    """
    if hub_root is None:
        return []
    src = Path(hub_root) / "hub" / "skills" / "hub-memory"
    if not src.is_dir():
        raise FileNotFoundError(f"hub 包里没有 hub-memory skill: {src}")
    return [("hub-memory", src)]

def collect_opencode_sources(vault_root: Path, dev: DeviceProfile,
                             hub_root: Path | None = None) -> list[tuple[str, Path]]:
    """三批源合并，并做**跨来源重名**预检。

    opencode 的 skill 名是全局扁平的（它自己遇到重名只会 WARN 一条再丢掉一个），所以
    两个插件各带一个同名 skill、或插件 skill 与独立 skill 撞名时，链过去必然有一个被
    悄悄吞掉。与其让它到运行期才丢，不如在这里就停。
    """
    pairs = (_standalone_sources(vault_root) + _plugin_sources(vault_root, dev)
             + _hub_memory_source(hub_root))
    seen: dict[str, Path] = {}
    dupes: list[str] = []
    for name, src in pairs:
        if name in seen and os.path.realpath(seen[name]) != os.path.realpath(src):
            dupes.append(f"{name}（{seen[name]} vs {src}）")
        else:
            seen[name] = src
    if dupes:
        raise RegisterConflict(
            "以下 skill 名在多个来源里重复，opencode 的 skill 名是全局扁平的、重名会被丢掉一个。"
            "请先改名再注册；本次未写任何链接：\n  " + "\n  ".join(dupes))
    return sorted(seen.items())

def plan_link_opencode_skills(vault_root: Path, dev: DeviceProfile,
                              hub_root: Path | None = None):
    """只读预检：返回 (to_link, ensured)。任何冲突→RegisterConflict，零写入。

    设备没接 opencode 时返回 ([], [])，静默跳过。
    """
    target_dir = opencode_skill_dir(dev)
    if target_dir is None:
        return [], []
    pairs = collect_opencode_sources(Path(vault_root), dev, hub_root)

    if os.path.lexists(target_dir):
        # 容器必须是真目录：整个 skill/ 是链接时，用户很可能已经把它指去了别处，
        # 往里建链等于往别人的地盘写。与 register 对 skills 容器的规矩一致。
        real = os.path.realpath(target_dir)
        expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
        if not target_dir.is_dir() or real != expected:
            raise RegisterConflict(
                f"{target_dir}（opencode 的 skill 容器必须是真目录，不能是链接/文件）；未写任何链接。")

    to_link: list[tuple[Path, Path]] = []
    ensured: list[str] = []
    conflicts: list[str] = []
    for name, src in pairs:
        link = target_dir / name
        if not os.path.lexists(link):
            to_link.append((src, link)); ensured.append(str(link))
        elif resolves_to(link, src):
            ensured.append(str(link))                   # 已就位，no-op
        else:
            conflicts.append(str(link))                 # 用户的/指别处的/断链，不碰
    if conflicts:
        raise RegisterConflict(
            "opencode 的 skill 目录下，以下位置已被非本次来源的同名项占用，"
            "hub 不覆盖、未写任何链接。请先移开或改名：\n  " + "\n  ".join(conflicts))
    return to_link, ensured

def commit_link_opencode_skills(to_link, w: Writer) -> None:
    for src, link in to_link:
        w.make_dir_link(src, link)

def opencode_skill_status(vault_root: Path, dev: DeviceProfile,
                          hub_root: Path | None = None) -> list[tuple[str, str]]:
    """只读健康检查。状态 ∈ {ok, missing, conflict}。设备没接 opencode → 空表。

    只报**期望项**：本次该链的那些。多出来的目录一律不报——没有归属清单就判不出它
    以前归不归 hub 管，冤枉用户自己放的 skill 比漏报更糟（与 status_report 同口径）。
    """
    target_dir = opencode_skill_dir(dev)
    if target_dir is None:
        return []
    try:
        pairs = collect_opencode_sources(Path(vault_root), dev, hub_root)
    except (RegisterConflict, PluginContainmentError, FileNotFoundError) as e:
        return [("conflict", f"{target_dir}（来源不可用：{e.args[0].splitlines()[0]}）")]
    if os.path.lexists(target_dir):
        real = os.path.realpath(target_dir)
        expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
        if not target_dir.is_dir() or real != expected:
            return [("conflict", f"{target_dir}（skill 容器是链接/非目录）")]
    rows: list[tuple[str, str]] = []
    for name, src in pairs:
        link = target_dir / name
        if not os.path.lexists(link):
            rows.append(("missing", str(link)))
        elif resolves_to(link, src):
            rows.append(("ok", str(link)))
        else:
            rows.append(("conflict", str(link)))        # 指别处 / 断链 / 用户真目录
    rows += _orphan_rows(target_dir, {n for n, _ in pairs}, vault_root, hub_root)
    return rows

def _orphan_rows(target_dir: Path, expected: set[str], vault_root, hub_root) -> list[tuple[str, str]]:
    """报**我们留下的残留**：不再期望、但确实是一条指回金库/hub 包的链接。

    别的地方（status_report.link_status）对"多出来的条目"一律不报，理由是没有归属清单就
    判不出它以前归不归 hub 管，冤枉用户自己放的 skill 比漏报更糟。这里能报，是因为
    **链接的目标本身就是归属证据**：一条指进金库的 junction 不可能是用户手放的普通
    skill。用户自己的真目录、或指向别处的链接，仍然一概不报。

    典型触发：从 device.toml 的 enabled 里去掉一个插件，或源侧删了某个 skill——链接会
    留在原地（本模块从不删任何路径），不报出来就永远没人知道。
    """
    if not target_dir.is_dir():
        return []
    owned = [_norm(str(p)) for p in (Path(vault_root),) + ((Path(hub_root),) if hub_root else ())]
    rows: list[tuple[str, str]] = []
    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name):
        if entry.name in expected:
            continue
        tgt = _link_target(entry)
        if tgt is None:
            continue                                    # 用户自己的真目录，不碰不报
        t = _norm(tgt)
        # 前缀必须按 os.sep 切：_norm 末尾走的是 normcase+normpath，Windows 上会把分隔符
        # 规回反斜杠。这里若写死 "/"，判据永远不成立、孤儿一条都报不出来（静默失效）。
        if any(t == o or t.startswith(o + os.sep) for o in owned):
            rows.append(("orphan", str(entry)))
    return rows

def stale_skills_paths_hint(dev: DeviceProfile, vault_root: Path) -> str | None:
    """接完原生落点后，opencode.json 里那行手加的 `skills.paths` 就多余了——它指着金库，
    与本模块建的链是同一批内容的第二条发现路径。

    只**提示**、不改：那份文件含明文密钥，hub 对它的既有戒律是能不碰就不碰
    （见 opencode_cfg 模块头）。解析失败一律当作没有、不吭声。
    """
    import json
    cfg = dev.paths.get("OPENCODE_CONFIG")
    if not cfg or not Path(cfg).exists():
        return None
    try:
        data = json.loads(Path(cfg).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    skills = data.get("skills")
    paths = skills.get("paths") if isinstance(skills, dict) else None
    if not isinstance(paths, list):
        return None
    vault = os.path.realpath(vault_root)
    def _in_vault(p: str) -> bool:
        real = os.path.realpath(p)
        return real == vault or real.startswith(vault + os.sep)   # 按分隔符切边界，别让同前缀目录误判
    hits = [p for p in paths if isinstance(p, str) and _in_vault(p)]
    if not hits:
        return None
    return (f"{cfg} 里的 skills.paths 仍指着金库 {hits}；skill 已链进 opencode 自己的目录，"
            f"这行可以删了（同一批内容两条发现路径，opencode 会报 duplicate skill name）。"
            f"hub 不改这份带密钥的文件，请手工删。")
