"""dsh。没有插件安装通道：由 dsh-claude-plugin-loader 直接扫描 Claude 式插件源，hub 只管
把 loader 放进 dsh profile 并维护它的 patch（实现在 hub/dsh_ops.py）。独立 skill 本期只读展示。
"""
import re

from hub.platforms.base import Platform, RegisterPlan, ToggleStep, skill_desired


def _patch_has(patch_text: str | None, section: str, item: str) -> bool:
    """极简 YAML 列表解析：在 hub 生成的 patch 里读 enabledPlugins/enabledSkills。"""
    if not patch_text:
        return False
    m = re.compile(rf"^{re.escape(section)}\s*:", re.M).search(patch_text)
    if not m:
        return False
    found = False
    for line in patch_text[m.end():].splitlines():
        if re.match(r"^\s*-", line):
            if re.search(rf"['\"]?{re.escape(item)}['\"]?", line):
                found = True
        elif line.strip() and not line.startswith(("#", " ")):
            break
    return found


def _patch_text(dev) -> str | None:
    from hub.dsh_ops import patch_path
    patch = patch_path(dev)
    if patch is None or not patch.exists():
        return None
    try:
        return patch.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


class Dsh(Platform):
    name = "dsh"
    plugin_channel = "loader"
    status_title = "dsh loader"
    status_key = "dsh_loader"
    register_key = "dsh_loader"
    register_label = "dsh loader 配置项"

    # ---- register / status ----
    def prepare_register(self, vault_root, dev, hub_root):
        from hub.dsh_ops import plan_configure_dsh_loader, DshConfigError, DshLoaderMissing
        from hub.register import RegisterConflict
        try:
            copies, writes, ensured = plan_configure_dsh_loader(vault_root, dev, hub_root)
        except DshLoaderMissing:
            raise                                   # 平台不可用，由编排方汇总
        except DshConfigError as e:                 # patch 指向别的金库：用户配置冲突，全局零写入
            raise RegisterConflict(str(e)) from e
        return RegisterPlan(copies=copies, writes=writes, ensured=ensured)

    def status_rows(self, vault_root, dev, hub_root):
        from hub.dsh_ops import dsh_loader_status
        return dsh_loader_status(vault_root, dev, hub_root)

    # ---- inventory ----
    def sample(self, ctx):
        from hub.dsh_ops import dsh_loader_status
        from hub.platforms import PlatformUnavailable
        from pathlib import Path
        try:
            root = ctx.hub_root if ctx.hub_root is not None else Path(__file__).resolve().parents[2]
            rows = dsh_loader_status(ctx.vault_root, ctx.dev, root)
        except Exception as e:
            ctx.warnings.append(f"dsh loader 状态不可用：{type(e).__name__}: {e}")
            return []
        missing = [label for state, label in rows if state == "unavailable"]
        if missing:
            raise PlatformUnavailable("; ".join(missing))
        return rows

    def plugin_cell(self, ctx, state, entry):
        from hub.dsh_ops import dsh_profile_dir
        dsh_rows = state
        name = entry.name
        desired = name in ctx.dev.plugins.get("dsh", [])
        enabled = _patch_has(_patch_text(ctx.dev), "enabledPlugins", name)
        if dsh_profile_dir(ctx.dev) is None:
            return {"harness": "dsh", "desired": desired, "actual": False,
                    "health": "missing", "control": "direct",
                    "detail": "dsh 未安装（无 DSH_HOME 或 .dsh）"}
        if any(s == "conflict" for s, _ in dsh_rows):
            return {"harness": "dsh", "desired": desired, "actual": bool(enabled),
                    "health": "conflict", "control": "direct",
                    "detail": "dsh loader patch 冲突"}
        if desired and enabled:
            return {"harness": "dsh", "desired": True, "actual": True,
                    "health": "ok", "control": "direct",
                    "detail": f"dsh enabledPlugins 已含 {name}"}
        if desired and not enabled:
            return {"harness": "dsh", "desired": True, "actual": False,
                    "health": "missing", "control": "direct",
                    "detail": f"dsh enabledPlugins 未含 {name}"}
        if not desired and enabled:
            return {"harness": "dsh", "desired": False, "actual": True,
                    "health": "conflict", "control": "direct",
                    "detail": f"dsh 已关闭但在 patch 中仍启用 {name}"}
        return {"harness": "dsh", "desired": False, "actual": False,
                "health": "ok", "control": "direct", "detail": "dsh 未启用"}

    def plugin_skill_cell(self, ctx, state, entry, name, src, plugin_cell):
        from hub.dsh_ops import dsh_profile_dir
        desired = skill_desired(ctx.dev, "dsh", name)
        key = f"{entry.name}:{name}"
        enabled = _patch_has(_patch_text(ctx.dev), "enabledSkills", key)
        if dsh_profile_dir(ctx.dev) is None:
            return {"harness": "dsh", "desired": desired, "actual": False,
                    "health": "missing", "control": "direct",
                    "detail": "dsh 未安装，无法判定 enabledSkills"}
        if desired and enabled:
            return {"harness": "dsh", "desired": True, "actual": True,
                    "health": "ok", "control": "direct",
                    "detail": f"dsh enabledSkills 已含 {key}"}
        if desired and not enabled:
            return {"harness": "dsh", "desired": True, "actual": False,
                    "health": "missing", "control": "direct",
                    "detail": f"dsh enabledSkills 未含 {key}"}
        if not desired and enabled:
            return {"harness": "dsh", "desired": False, "actual": True,
                    "health": "conflict", "control": "direct",
                    "detail": f"dsh 已关闭但 enabledSkills 仍含 {key}"}
        return {"harness": "dsh", "desired": False, "actual": False,
                "health": "ok", "control": "direct", "detail": "dsh 未启用"}

    def standalone_skill_cell(self, ctx, state, name, src):
        return {"harness": "dsh", "desired": skill_desired(ctx.dev, "dsh", name), "actual": None,
                "health": "unknown", "control": "unmanaged",
                "detail": "dsh 独立 skill 本期只读展示，未纳入单切"}

    # ---- toggle ----
    def toggle_skill_mode(self, origin, plugin_name):
        if origin != "standalone":
            return None
        return ({"harness": "dsh", "status": "unmanaged", "control": "unmanaged",
                 "detail": "dsh 独立 skill 本期只读，未纳入单切；未做独立变更。"},
                "dsh 独立 skill 由插件整体/未来模块管理，本期未开关。")

    def plan_toggle(self, req):
        from hub.dsh_ops import (plan_configure_dsh_loader, commit_configure_dsh_loader,
                                 plan_update_dsh_loader, commit_update_dsh_loader)
        copies, cfg_writes, _ensured = plan_configure_dsh_loader(req.vault_root, req.dev, req.hub_root)
        updates = plan_update_dsh_loader(req.vault_root, req.dev, req.hub_root)

        def commit(w):
            commit_configure_dsh_loader(copies, cfg_writes, w)
            commit_update_dsh_loader(updates, w)
            actions = [f"copy {dest}" for _src, dest in copies]
            actions += [f"patch {path}" for path, _text in cfg_writes]
            actions += [f"patch {path}" for path, _text in updates]
            return actions, {"harness": "dsh", "status": "applied", "actions": actions}, []
        return ToggleStep(commit)


ADAPTER = Dsh()
