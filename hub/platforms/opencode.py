"""opencode。没有插件安装通道：插件里打包的 skill 连同独立 skill 逐个活链进它自己的 skill 目录
（实现在 hub/opencode_skills.py）；记忆视图写进 opencode.json 的 instructions[]（hub/opencode_cfg.py）。
两件事都只在 device.toml 显式配了 OPENCODE_HOME / OPENCODE_CONFIG 时才做。
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

from hub.platforms.base import (Platform, RegisterPlan, ToggleStep, Wiring,
                                plugin_internal_skills, skill_desired)


@dataclass
class _InstructionPlan:
    plan: object

    def commit(self, w) -> None:
        from hub.opencode_cfg import commit_instruction
        from hub.hubconfig import backups_dir
        commit_instruction(self.plan, w, backups_dir())


class Opencode(Platform):
    name = "opencode"
    plugin_channel = "links"
    status_title = "opencode skill 链接"
    status_key = "opencode_links"
    register_key = "opencode_links"
    register_label = "opencode skill 链接（它自己的 skill 目录）"

    # ---- 记忆视图 ----
    def prepare_wiring(self, ctx):
        from hub.opencode_cfg import plan_instruction
        if not ctx.dev.paths.get("OPENCODE_CONFIG"):   # 仅设备显式 opt-in 才接；绝不因默认路径
            return Wiring()                            # 恰好存在一份带密钥的 opencode.json 就去写它
        plan = plan_instruction(ctx.dev, ctx.view_path(self.name))
        warnings = [f"opencode: {plan.reason}"] if plan.action == "refuse" else []
        return Wiring(warnings=warnings, plan=_InstructionPlan(plan))

    def wiring_health(self, dev, cur_hash):
        from hub.memwire import view_path
        from hub.opencode_cfg import opencode_config_path
        if not dev.paths.get("OPENCODE_CONFIG"):
            return []
        ocfg = opencode_config_path(dev)
        if not ocfg.exists():
            return []
        try:
            data = json.loads(ocfg.read_text(encoding="utf-8"))
            instr = data.get("instructions") if isinstance(data, dict) else None
            ok = isinstance(instr, list) and view_path(self.name).as_posix() in instr
            return [("ok" if ok else "degraded", str(ocfg))]
        except (ValueError, OSError):
            return [("degraded", f"{ocfg}（非严格 JSON，未接线）")]

    # ---- register / status ----
    def prepare_register(self, vault_root, dev, hub_root):
        from hub.opencode_skills import plan_link_opencode_skills, stale_skills_paths_hint
        to_link, ensured = plan_link_opencode_skills(vault_root, dev, hub_root)
        hint = stale_skills_paths_hint(dev, vault_root)
        return RegisterPlan(links=to_link, ensured=ensured, warnings=[hint] if hint else [])

    def status_rows(self, vault_root, dev, hub_root):
        from hub.opencode_skills import opencode_skill_status
        return opencode_skill_status(vault_root, dev, hub_root)

    # ---- inventory ----
    def sample(self, ctx):
        from hub.opencode_skills import opencode_skill_dir, opencode_skill_status
        oc_dir = opencode_skill_dir(ctx.dev)
        try:
            oc_rows = opencode_skill_status(ctx.vault_root, ctx.dev, ctx.hub_root)
        except Exception as e:
            oc_rows = []
            ctx.warnings.append(f"opencode skill 状态不可用：{type(e).__name__}: {e}")
        return oc_dir, oc_rows

    def plugin_cell(self, ctx, state, entry):
        from hub.fslink import resolves_to
        oc_dir, oc_rows = state
        name = entry.name
        desired = name in ctx.dev.plugins.get("opencode", [])
        skills = plugin_internal_skills(ctx.vault_root, name)
        skill_names = {n for n, _ in skills}
        if oc_dir is None:
            if desired:
                return {"harness": "opencode", "desired": True, "actual": False,
                        "health": "missing", "control": "direct",
                        "detail": "opencode 未配置（无 OPENCODE_HOME/OPENCODE_CONFIG）"}
            return {"harness": "opencode", "desired": False, "actual": False,
                    "health": "ok", "control": "direct",
                    "detail": "插件未启用，opencode 也未配置"}
        statuses = []
        for sname, src in skills:
            link = oc_dir / sname
            if not os.path.lexists(link):
                statuses.append(("missing", str(link)))
            elif resolves_to(link, src):
                statuses.append(("ok", str(link)))
            else:
                statuses.append(("conflict", str(link)))
        if desired and not skills:
            actual, health = True, "ok"
            detail = f"opencode: 插件 {name} 无内部 skill，空转 ok"
        elif desired:
            actual = all(s == "ok" for s, _ in statuses)
            if any(s == "conflict" for s, _ in statuses):
                health = "conflict"
            elif any(s == "missing" for s, _ in statuses):
                health = "missing"
            else:
                health = "ok"
            detail = "opencode: " + "; ".join(f"{s}={l}" for s, l in statuses) or "ok"
        else:
            orphan = next((l for s, l in oc_rows if s == "orphan"
                           and Path(l).name in skill_names), None)
            if orphan:
                actual, health = True, "orphan"
                detail = f"opencode: 插件 {name} 已关闭，仍存在遗留链 {orphan}"
            else:
                actual, health = False, "ok"
                detail = "opencode: 插件未启用"
        return {"harness": "opencode", "desired": desired, "actual": actual,
                "health": health, "control": "direct", "detail": detail}

    def _direct_cell(self, ctx, state, name, src):
        from hub.fslink import resolves_to
        oc_dir, _oc_rows = state
        desired = skill_desired(ctx.dev, "opencode", name)
        if oc_dir is None:
            return {"harness": "opencode", "desired": desired, "actual": False,
                    "health": "missing" if desired else "ok", "control": "direct",
                    "detail": "opencode 未配置"}
        link = oc_dir / name
        if not os.path.lexists(link):
            actual, health, detail = False, "missing", f"opencode: {link}"
        elif resolves_to(link, src):
            if desired:
                actual, health, detail = True, "ok", f"opencode: {link} -> {src}"
            else:
                actual, health, detail = True, "orphan", f"opencode: {link} 已关闭但仍存在"
        else:
            actual, health, detail = False, "conflict", f"opencode: {link} 指向别处"
        return {"harness": "opencode", "desired": desired, "actual": actual,
                "health": health, "control": "direct", "detail": detail}

    def plugin_skill_cell(self, ctx, state, entry, name, src, plugin_cell):
        return self._direct_cell(ctx, state, name, src)

    def standalone_skill_cell(self, ctx, state, name, src):
        return self._direct_cell(ctx, state, name, src)

    # ---- toggle ----
    def plan_toggle(self, req):
        from hub.opencode_skills import (plan_link_opencode_skills, commit_link_opencode_skills,
                                         plan_unlink_opencode_skills, commit_unlink_opencode_skills)
        to_link, ensured, to_unlink = [], [], []
        if req.on:
            to_link, ensured = plan_link_opencode_skills(req.vault_root, req.dev, req.hub_root)
        else:
            to_unlink = plan_unlink_opencode_skills(req.vault_root, req.dev, req.hub_root)

        def commit(w):
            actions = []
            if to_link:
                commit_link_opencode_skills(to_link, w)
                actions += [f"link {src} -> {link}" for src, link in to_link]
            if to_unlink:
                commit_unlink_opencode_skills(to_unlink, w, req.vault_root, req.hub_root)
                actions += [f"unlink {link}" for link in to_unlink]
            result = None
            if to_link or to_unlink or ensured or req.asset_type == "plugin":
                result = {"harness": "opencode", "status": "applied", "actions": actions}
            return actions, result, []
        return ToggleStep(commit, ensured)


ADAPTER = Opencode()
