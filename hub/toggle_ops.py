"""toggle 编排：更新 device.toml 期望 + 按 harness 执行真开关/降级。

设计要点：

- 所有平台动作先只读预检，全部通过后才写 device.toml/建链/改 loader patch。
- dry-run 通过 Writer(dry_run=True) 贯穿到底，一个字节都不落盘。
- claude/codex 插件内 skill 只返回 degraded，不写 [skills.*]。
- dsh standalone skill 返回 unmanaged，不写 [skills.dsh]。
"""
import os
from pathlib import Path

from hub.vault import load_device, current_host
from hub.writer import Writer
from hub.device_toml import update_device_toml
from hub.plugin_manifest import load_plugin_manifest, PluginManifestError
from hub.plugin_ops import prepare_plugin_register, execute_plugin_plan
from hub.opencode_skills import (plan_link_opencode_skills,
                                 commit_link_opencode_skills,
                                 plan_unlink_opencode_skills,
                                 commit_unlink_opencode_skills)
from hub.dsh_ops import (plan_configure_dsh_loader, commit_configure_dsh_loader,
                         plan_update_dsh_loader, commit_update_dsh_loader)
from hub.register import RegisterConflict
from hub.fslink import resolves_to
from hub.vaultpaths import shared_skills_dir, SharedSkillsEscape

HARNESSES = ("claude", "codex", "opencode", "dsh")
ASSET_TYPES = ("plugin", "skill", "memory")


def _copy_lists(d):
    return {k: list(v) for k, v in d.items()}


def _apply_desired(values, name, on):
    out = list(values)
    if on:
        if name not in out:
            out.append(name)
    else:
        if name in out:
            out.remove(name)
    return out


def _find_plugin(vault_root, name):
    for e in load_plugin_manifest(vault_root):
        if e.name == name:
            return e
    raise FileNotFoundError(f"插件不存在：{name}")



def _skill_candidates(vault_root, hub_root):
    """返回 (name, origin, plugin, path) 列表。origin ∈ {standalone, plugin-internal}。"""
    out = []
    try:
        shared = shared_skills_dir(vault_root)
        if shared.is_dir():
            for d in sorted(shared.iterdir(), key=lambda p: p.name):
                if d.is_dir():
                    out.append((d.name, "standalone", None, d))
    except SharedSkillsEscape:
        raise
    if hub_root is not None:
        hm = Path(hub_root) / "hub" / "skills" / "hub-memory"
        if hm.is_dir():
            out.append(("hub-memory", "standalone", None, hm))
    plugins_dir = Path(vault_root) / "shared" / "plugins"
    if plugins_dir.is_dir():
        for p in sorted(plugins_dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            skills = p / "skills"
            if not skills.is_dir():
                continue
            for d in sorted(skills.iterdir(), key=lambda x: x.name):
                if d.is_dir() and (d / "SKILL.md").is_file():
                    out.append((d.name, "plugin-internal", p.name, d))
    return out


def _resolve_skill(vault_root, name, plugin=None, hub_root=None):
    matches = [m for m in _skill_candidates(vault_root, hub_root) if m[0] == name]
    if not matches:
        raise FileNotFoundError(f"skill 不存在：{name}")
    if plugin is not None:
        internal = [m for m in matches if m[1] == "plugin-internal" and m[2] == plugin]
        if internal:
            return internal[0]
        if len(matches) == 1 and matches[0][1] == "standalone":
            return matches[0]
        raise ValueError(
            f"skill 名 {name} 在插件 {plugin} 下不存在；或与其它来源歧义，请确认 --plugin。")
    if len(matches) > 1:
        origins = ", ".join(
            f"{m[2] + ':' if m[2] else ''}{m[1]}" for m in matches)
        raise ValueError(
            f"skill 名 {name} 存在多个来源（{origins}），必须用 --plugin 消歧。")
    return matches[0]


def _standalone_skill_dir(dev, harness):
    """返回 claude/codex 的 standalone skill 落点；未配置时返回 None。"""
    if harness == "claude":
        v = dev.paths.get("CLAUDE_HOME")
        return None if not v else Path(v) / "skills"
    if harness == "codex":
        v = dev.paths.get("AGENTS_HOME")
        return (Path(v) if v else Path.home() / ".agents") / "skills"
    return None


def _ensure_real_dir(target_dir):
    if os.path.lexists(target_dir):
        real = os.path.realpath(target_dir)
        expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
        if not target_dir.is_dir() or real != expected:
            raise RegisterConflict(
                f"{target_dir}（skills 容器必须是真目录，不能是链接/文件）；未写任何内容。")


def _plan_standalone_link(vault_root, dev, harness, name, src):
    target_dir = _standalone_skill_dir(dev, harness)
    if target_dir is None:
        raise ValueError(f"{harness} 未配置技能目录，无法建链接")
    _ensure_real_dir(target_dir)
    link = target_dir / name
    if not os.path.lexists(link):
        return [(src, link)], []
    if resolves_to(link, src):
        return [], [str(link)]
    raise RegisterConflict(
        f"{link} 已被非本来源的同名项占用，hub 不覆盖；请先移开或改名。")


def _plan_standalone_unlink(vault_root, dev, harness, name, src):
    target_dir = _standalone_skill_dir(dev, harness)
    if target_dir is None:
        return []
    link = target_dir / name
    if not os.path.lexists(link):
        return []
    if resolves_to(link, src):
        return [link]
    return []


def _target_plugin_actions(plan, name):
    return [a.describe for a in plan.actions if a.id.startswith(name + ":")]



def toggle_asset(vault_root, host, asset_type, name, harness, on,
                 plugin=None, dry_run=False, hub_root=None, runner=None) -> dict:
    """统一资产开关编排。返回结果 dict；参数/不存在类错误直接抛异常。"""
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type 必须是 {ASSET_TYPES}，收到 {asset_type!r}")
    if harness not in HARNESSES:
        raise ValueError(f"harness 必须是 {HARNESSES}，收到 {harness!r}")
    on = bool(on)
    action = "on" if on else "off"

    vault_root = Path(vault_root)
    host = host or current_host()
    dev = load_device(vault_root, host)
    device_path = vault_root / host / "device.toml"
    w = Writer(dry_run=dry_run)

    if asset_type == "memory":
        raise ValueError("memory 首版只读，不支持 toggle")

    # 预检阶段：只读，不落盘
    to_link = []          # [(src, link)]
    ensured = []          # 已就位链接
    to_unlink = []        # [Path]
    dsh_plan = None
    plugin_plan = None
    plugin_name = None
    skill_origin = None
    src = None
    skills_update = {}
    plugins_update = {}
    results = []
    warnings = []
    errors = []

    if asset_type == "plugin":
        entry = _find_plugin(vault_root, name)
        if harness not in entry.platforms:
            raise ValueError(f"插件 {name} 的清单 platforms 不含 {harness}")
        plugins_update = _copy_lists(dev.plugins)
        plugins_update[harness] = _apply_desired(plugins_update.get(harness, []), name, on)
        dev.plugins = plugins_update

        if harness in ("claude", "codex"):
            plugin_plan = prepare_plugin_register(vault_root, dev, runner=runner)
        elif harness == "opencode":
            if on:
                to_link, ensured = plan_link_opencode_skills(vault_root, dev, hub_root)
            else:
                to_unlink = plan_unlink_opencode_skills(vault_root, dev, hub_root)
        elif harness == "dsh":
            dsh_plan = (plan_configure_dsh_loader(vault_root, dev, hub_root),
                        plan_update_dsh_loader(vault_root, dev, hub_root))


    else:
        # skill
        n, origin, pn, src = _resolve_skill(vault_root, name, plugin, hub_root)
        plugin_name = pn
        skill_origin = origin
        if origin == "plugin-internal":
            if plugin_name is None:
                raise ValueError("内部错误：plugin-internal skill 缺少 plugin 名")
            entry = _find_plugin(vault_root, plugin_name)
            if harness not in entry.platforms:
                raise ValueError(
                    f"插件 {plugin_name} 的清单 platforms 不含 {harness}")

        if origin == "plugin-internal" and harness in ("claude", "codex"):
            # 降级：不写 [skills.*]，不执行独立动作
            results.append({
                "harness": harness,
                "status": "degraded",
                "controlled_by": "plugin",
                "detail": f"{harness} 不支持插件内单 skill 开关；由插件 {plugin_name} 整体控制，未做独立变更。",
            })
            warnings.append(
                f"{harness} 不支持插件内单 skill；请 toggle 插件 {plugin_name} 实现整体开关。")
        elif origin == "standalone" and harness == "dsh":
            results.append({
                "harness": harness,
                "status": "unmanaged",
                "control": "unmanaged",
                "detail": "dsh 独立 skill 本期只读，未纳入单切；未做独立变更。",
            })
            warnings.append("dsh 独立 skill 由插件整体/未来模块管理，本期未开关。")
        else:
            skills_update = _copy_lists(dev.skills)
            skills_update[harness] = _apply_desired(skills_update.get(harness, []), name, on)
            dev.skills = skills_update

            if harness in ("claude", "codex"):
                if origin == "standalone":
                    if on:
                        to_link, ensured = _plan_standalone_link(
                            vault_root, dev, harness, name, src)
                    else:
                        to_unlink = _plan_standalone_unlink(
                            vault_root, dev, harness, name, src)
                else:
                    raise ValueError("plugin-internal claude/codex 应走降级")
            elif harness == "opencode":
                if on:
                    to_link, ensured = plan_link_opencode_skills(vault_root, dev, hub_root)
                else:
                    to_unlink = plan_unlink_opencode_skills(vault_root, dev, hub_root)
            elif harness == "dsh":
                dsh_plan = (plan_configure_dsh_loader(vault_root, dev, hub_root),
                            plan_update_dsh_loader(vault_root, dev, hub_root))



    # 全部预检通过后，开始提交
    changed = []
    actions = []
    if plugins_update or skills_update:
        update_device_toml(
            device_path,
            plugins=plugins_update or None,
            skills=skills_update or None,
            w=w)
        if plugins_update or skills_update:
            changed.append(str(device_path))

    if plugin_plan is not None:
        rep = execute_plugin_plan(plugin_plan, w, runner=runner)
        acts = _target_plugin_actions(plugin_plan, name)
        actions.extend(acts)
        if rep.failed:
            details = "; ".join(f"{i}: {why}" for i, why in rep.failed)
            errors.append({"harness": harness, "error": details})
            results.append({"harness": harness, "status": "failed",
                            "error": details, "actions": acts})
        else:
            results.append({"harness": harness, "status": "applied", "actions": acts})

    if to_link:
        if harness == "opencode":
            commit_link_opencode_skills(to_link, w)
        else:
            from hub.register import commit_register_skills
            commit_register_skills(to_link, w)
        actions.extend([f"link {src} -> {link}" for src, link in to_link])
    if to_unlink:
        if harness == "opencode":
            commit_unlink_opencode_skills(to_unlink, w, vault_root, hub_root)
        else:
            for link in to_unlink:
                w.remove_dir_link(link)
        actions.extend([f"unlink {link}" for link in to_unlink])

    if not results and (to_link or to_unlink or ensured):
        results.append({"harness": harness, "status": "applied", "actions": actions})

    if dsh_plan is not None:
        (copies, cfg_writes, _ensured), updates = dsh_plan
        commit_configure_dsh_loader(copies, cfg_writes, w)
        commit_update_dsh_loader(updates, w)
        for _src, dest in copies:
            actions.append(f"copy {dest}")
        for path, _text in cfg_writes:
            actions.append(f"patch {path}")
        for path, _text in updates:
            actions.append(f"patch {path}")
        if not results:
            results.append({"harness": harness, "status": "applied", "actions": actions})

    if asset_type == "plugin" and harness in ("opencode", "dsh") and not results:
        results.append({"harness": harness, "status": "applied", "actions": actions})

    return {
        "asset_type": asset_type,
        "name": name,
        "plugin": plugin_name,
        "harness": harness,
        "action": action,
        "dry_run": dry_run,
        "results": results,
        "changed": changed,
        "actions": actions,
        "errors": errors,
        "warnings": warnings,
    }
