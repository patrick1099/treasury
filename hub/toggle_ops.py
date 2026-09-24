"""toggle 编排：更新 device.toml 期望 + 在目标平台上执行真开关/降级。

设计要点：

- 所有平台动作先只读预检，全部通过后才写 device.toml/建链/改 loader patch。
- dry-run 通过 Writer(dry_run=True) 贯穿到底，一个字节都不落盘。
- 每个平台怎么开关归它的适配器（hub.platforms）：CLI 平台的插件内 skill 返回 degraded、
  dsh 的独立 skill 返回 unmanaged，都由适配器声明，这里不按平台名分支。
- 点名一个本机停用或不可用的平台 → 明确报错，不改任何东西。
"""
from pathlib import Path

from hub.vault import load_device, current_host
from hub.writer import Writer
from hub.device_toml import update_device_toml
from hub.plugin_manifest import load_plugin_manifest
from hub.vaultpaths import shared_skills_dir, SharedSkillsEscape
from hub import platforms
from hub.platforms.base import ToggleReq

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


def toggle_asset(vault_root, host, asset_type, name, harness, on,
                 plugin=None, dry_run=False, hub_root=None, runner=None) -> dict:
    """统一资产开关编排。返回结果 dict；参数/不存在类错误直接抛异常。"""
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"asset_type 必须是 {ASSET_TYPES}，收到 {asset_type!r}")
    if harness not in platforms.all_names():
        raise ValueError(f"harness 必须是 {platforms.all_names()}，收到 {harness!r}")
    on = bool(on)
    action = "on" if on else "off"

    vault_root = Path(vault_root)
    host = host or current_host()
    dev = load_device(vault_root, host)
    device_path = vault_root / host / "device.toml"
    w = Writer(dry_run=dry_run)

    if asset_type == "memory":
        raise ValueError("memory 首版只读，不支持 toggle")

    adapter = platforms.require(dev, harness)      # 停用 → PlatformDisabled；坏了 → PlatformUnavailable

    # 预检阶段：只读，不落盘
    plugin_name = None
    skill_origin = None
    src = None
    skills_update = {}
    plugins_update = {}
    results = []
    warnings = []
    step = None

    if asset_type == "plugin":
        entry = _find_plugin(vault_root, name)
        if harness not in entry.platforms:
            raise ValueError(f"插件 {name} 的清单 platforms 不含 {harness}")
        plugins_update = _copy_lists(dev.plugins)
        plugins_update[harness] = _apply_desired(plugins_update.get(harness, []), name, on)
        dev.plugins = plugins_update
    else:
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
        mode = adapter.toggle_skill_mode(origin, plugin_name)
        if mode is not None:
            # 该平台对这类 skill 不做独立开关：不写 [skills.*]，不执行任何动作
            result, warning = mode
            results.append(result)
            warnings.append(warning)
        else:
            skills_update = _copy_lists(dev.skills)
            skills_update[harness] = _apply_desired(skills_update.get(harness, []), name, on)
            dev.skills = skills_update

    if plugins_update or skills_update:
        step = adapter.plan_toggle(ToggleReq(
            vault_root=vault_root, dev=dev, asset_type=asset_type, name=name,
            origin=skill_origin, plugin_name=plugin_name, src=src, on=on,
            hub_root=hub_root, runner=runner))

    # 全部预检通过后，开始提交
    changed = []
    actions = []
    errors = []
    if plugins_update or skills_update:
        update_device_toml(
            device_path,
            plugins=plugins_update or None,
            skills=skills_update or None,
            w=w)
        changed.append(str(device_path))

    if step is not None:
        acts, result, errs = step.commit(w)
        actions.extend(acts)
        errors.extend(errs)
        if result is not None:
            results.append(result)

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
