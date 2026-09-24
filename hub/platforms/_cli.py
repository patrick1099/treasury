"""走官方插件 CLI 的平台（claude / codex）的共同部分。

两家差别只在 CLI 方言（命令怎么拼、`plugin list` 输出长什么样）和「有没有装着但禁用这一态」，
由子类声明 cli_dialect / cli_has_disable；这里不出现任何平台名。
"""
import os
from pathlib import Path

from hub.platforms.base import Platform, ToggleStep, skill_desired


class CliPlatform(Platform):
    plugin_channel = "cli"
    skills_home_key = None      # device.toml [paths] 里指 skills 落点的键
    skills_home_desc = ""       # 人话描述，出现在 inventory 的 detail 里

    # ---- inventory ----
    def sample(self, ctx):
        from hub import plugin_cli
        try:
            return plugin_cli.installed_plugins(self.name)
        except Exception as e:
            ctx.warnings.append(f"{self.name} plugin list 不可用：{type(e).__name__}: {e}")
            return None

    def _active(self, inst, pid) -> bool:
        return pid in inst and (inst[pid].enabled if self.cli_has_disable else True)

    def plugin_cell(self, ctx, state, entry):
        tool = self.name
        name = entry.name
        desired = name in ctx.dev.plugins.get(tool, [])
        pid = f"{name}@{name}"
        inst = state
        actual = bool(self._active(inst, pid)) if inst is not None else None
        health = ctx.health_by_name.get((name, tool), "unknown")
        if health == "unknown":
            detail = f"{tool}: CLI 状态不可用，无法判定安装/启用"
        else:
            detail = f"{tool}: {health}"
        return {"harness": tool, "desired": desired, "actual": actual,
                "health": health, "control": "direct", "detail": detail}

    def plugin_skill_cell(self, ctx, state, entry, name, src, plugin_cell):
        if plugin_cell is None:
            return None
        return {"harness": self.name, "desired": plugin_cell["desired"],
                "actual": plugin_cell["actual"], "health": plugin_cell["health"],
                "control": "plugin",
                "detail": f"{self.name} 不支持插件内单 skill，由插件 {entry.name} 整体控制"}

    def standalone_skill_cell(self, ctx, state, name, src):
        from hub.fslink import resolves_to
        tool = self.name
        dev = ctx.dev
        target = self.skills_home(dev)
        configured = dev.paths.get(self.skills_home_key)
        label = self.skills_home_key if configured is None else self.skills_home_desc
        desired = skill_desired(dev, tool, name)
        if target is None:
            actual, health, detail = False, "missing", f"{tool}: 未配置 {label}，无法判定实际状态"
        else:
            link = target / name
            if not os.path.lexists(link):
                actual, health, detail = False, "missing", str(link)
            elif resolves_to(link, src):
                actual, health, detail = True, "ok", f"{tool}: {link} -> {src}"
            else:
                actual, health, detail = False, "conflict", f"{tool}: {link} 指向别处"
        return {"harness": tool, "desired": desired, "actual": actual,
                "health": health, "control": "direct", "detail": detail}

    # ---- toggle ----
    def toggle_skill_mode(self, origin, plugin_name):
        if origin != "plugin-internal":
            return None
        return ({"harness": self.name, "status": "degraded", "controlled_by": "plugin",
                 "detail": f"{self.name} 不支持插件内单 skill 开关；由插件 {plugin_name} 整体控制，未做独立变更。"},
                f"{self.name} 不支持插件内单 skill；请 toggle 插件 {plugin_name} 实现整体开关。")

    def plan_toggle(self, req):
        if req.asset_type == "plugin":
            return self._plan_toggle_plugin(req)
        if req.origin != "standalone":
            raise ValueError("plugin-internal 的 CLI 平台 skill 应走降级")
        return self._plan_toggle_standalone(req)

    def _plan_toggle_plugin(self, req):
        from hub.plugin_ops import prepare_plugin_register, execute_plugin_plan
        plan = prepare_plugin_register(req.vault_root, req.dev, runner=req.runner)
        tool, name = self.name, req.name

        def commit(w):
            rep = execute_plugin_plan(plan, w, runner=req.runner)
            acts = [a.describe for a in plan.actions if a.id.startswith(name + ":")]
            if rep.failed:
                details = "; ".join(f"{i}: {why}" for i, why in rep.failed)
                return acts, {"harness": tool, "status": "failed", "error": details,
                              "actions": acts}, [{"harness": tool, "error": details}]
            return acts, {"harness": tool, "status": "applied", "actions": acts}, []
        return ToggleStep(commit)

    def _plan_toggle_standalone(self, req):
        from hub.fslink import resolves_to
        from hub.register import RegisterConflict
        tool = self.name
        target_dir = self.skills_home(req.dev)
        link = None if target_dir is None else target_dir / req.name
        to_link, to_unlink, ensured = [], [], []
        if req.on:
            if target_dir is None:
                raise ValueError(f"{tool} 未配置技能目录，无法建链接")
            ensure_real_dir(target_dir)
            if not os.path.lexists(link):
                to_link = [(req.src, link)]
            elif resolves_to(link, req.src):
                ensured = [str(link)]
            else:
                raise RegisterConflict(
                    f"{link} 已被非本来源的同名项占用，hub 不覆盖；请先移开或改名。")
        elif link is not None and os.path.lexists(link) and resolves_to(link, req.src):
            to_unlink = [link]

        def commit(w):
            actions = []
            for src, lk in to_link:
                w.make_dir_link(src, lk)
                actions.append(f"link {src} -> {lk}")
            for lk in to_unlink:
                w.remove_dir_link(lk)
                actions.append(f"unlink {lk}")
            result = None
            if to_link or to_unlink or ensured:
                result = {"harness": tool, "status": "applied", "actions": actions}
            return actions, result, []
        return ToggleStep(commit, ensured)


def ensure_real_dir(target_dir: Path) -> None:
    """skills 容器必须是真目录：链接/文件/坏链一律拒（整个目录是链接时平台不认）。"""
    from hub.register import RegisterConflict
    if os.path.lexists(target_dir):
        real = os.path.realpath(target_dir)
        expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
        if not target_dir.is_dir() or real != expected:
            raise RegisterConflict(
                f"{target_dir}（skills 容器必须是真目录，不能是链接/文件）；未写任何内容。")
