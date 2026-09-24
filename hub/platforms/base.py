"""平台适配器的公共形状。

每个平台一个 `Platform` 子类实例（模块级 `ADAPTER`）。调用方只调这里列出的能力；某个平台
没有某项能力就继承这里的缺省（什么都不做 / 空）。平台之间的差别写在适配器里，不写在调用方。
"""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RegisterPlan:
    """register 时本平台要做的额外动作（通用 skill 链接之外的）。只读预检产物，commit 才落盘。"""
    links: list = field(default_factory=list)      # [(src, link)] 目录链接
    copies: list = field(default_factory=list)     # [(src, dest)] 文件拷贝
    writes: list = field(default_factory=list)     # [(path, text)] 文本写入
    ensured: list = field(default_factory=list)    # 已就位 + 待建的条目（汇报用）
    warnings: list = field(default_factory=list)   # 只提示不阻断

    def commit(self, w) -> None:
        for src, link in self.links:
            w.make_dir_link(src, link)
        for src, dest in self.copies:
            w.copy_file(src, dest)
        for path, text in self.writes:
            w.write_text(path, text)


@dataclass
class WiringCtx:
    """记忆视图接线的输入：各平台视图已由编排器渲染，适配器只管把视图接进平台自己的入口文件。"""
    vault_root: Path
    dev: object
    per_tool: dict          # {平台名: 视图条目}
    shared_hash: str
    view_path: object       # callable(平台名) -> Path


@dataclass
class Wiring:
    writes: list = field(default_factory=list)     # [(path, text)]，原子写
    warnings: list = field(default_factory=list)
    plan: object = None                            # 需要自己提交的额外计划（有 .commit(w)）


@dataclass
class InvCtx:
    """inventory 一次采样的公共输入。"""
    vault_root: Path
    dev: object
    hub_root: Path | None
    health_by_name: dict        # {(插件名, 平台名): 插件 CLI 健康}
    warnings: list


@dataclass
class ToggleReq:
    vault_root: Path
    dev: object                 # 已套用本次期望（plugins/skills 已改）的设备配置
    asset_type: str             # plugin | skill
    name: str
    origin: str | None          # skill 才有：standalone | plugin-internal
    plugin_name: str | None
    src: Path | None
    on: bool
    hub_root: Path | None
    runner: object = None


@dataclass
class ToggleStep:
    """toggle 在一个平台上的计划。commit 返回 (actions, result 或 None, errors)。"""
    commit_fn: object = None
    ensured: list = field(default_factory=list)

    def commit(self, w):
        if self.commit_fn is None:
            return [], None, []
        return self.commit_fn(w)


class Platform:
    name = ""
    # 插件怎么到这个平台：cli = 官方插件 CLI 装卸；links = 插件里的 skill 逐个活链进它的
    # skill 目录；loader = 交给平台自己的加载器扫描；None = 不接插件。
    plugin_channel = None
    cli_dialect = None          # plugin_channel == "cli" 时，命令与输出格式用哪种方言
    cli_has_disable = False     # 插件 CLI 有没有「装着但禁用」这一态
    status_title = None         # status 人类输出里本平台附加行的小标题；None = 没有附加行
    status_key = None           # status --json 里附加行的键名
    register_key = None         # register --json 里本平台附加动作计数的键名
    register_label = None       # register 人类输出里那一行的说明

    # ---- skill 落点 ----
    def skills_home(self, dev) -> Path | None:
        """hub 通用链接器管理的 skills 目录（shared/skills 与 hub-memory 链进这里）。"""
        return None

    def bootstrap_dir(self, dev) -> Path | None:
        """换新机 bootstrap 拷加载器 skill 的目录。"""
        return None

    # ---- 记忆视图接线 ----
    def prepare_wiring(self, ctx: WiringCtx) -> Wiring:
        return Wiring()

    def wiring_health(self, dev, cur_hash: str) -> list:
        return []

    # ---- register / status ----
    def prepare_register(self, vault_root, dev, hub_root) -> RegisterPlan | None:
        return None

    def status_rows(self, vault_root, dev, hub_root) -> list:
        return []

    # ---- inventory ----
    def sample(self, ctx: InvCtx):
        return None

    def plugin_cell(self, ctx: InvCtx, state, entry) -> dict | None:
        return None

    def plugin_skill_cell(self, ctx: InvCtx, state, entry, name, src, plugin_cell) -> dict | None:
        return None

    def standalone_skill_cell(self, ctx: InvCtx, state, name, src) -> dict | None:
        return None

    # ---- toggle ----
    def toggle_skill_mode(self, origin: str, plugin_name: str | None) -> tuple | None:
        """这个平台对某类 skill 不做独立开关时返回 (result, warning)；正常开关返回 None。"""
        return None

    def plan_toggle(self, req: ToggleReq) -> ToggleStep:
        return ToggleStep()


def skill_desired(dev, tool: str, name: str) -> bool:
    """[skills.<平台>].enabled 缺省=全部开启；出现 key 后即为权威名单。"""
    enabled = dev.skills.get(tool)
    if enabled is None:
        return True
    return name in enabled


def link_state(link: Path, src: Path) -> str:
    from hub.fslink import resolves_to
    if not os.path.lexists(link):
        return "missing"
    return "ok" if resolves_to(link, src) else "conflict"


def plugin_internal_skills(vault_root, plugin: str) -> list[tuple[str, Path]]:
    """shared/plugins/<plugin>/skills/ 下带 SKILL.md 的 skill，按名排序。"""
    d = Path(vault_root) / "shared" / "plugins" / plugin / "skills"
    if not d.is_dir():
        return []
    return [(x.name, x) for x in sorted(d.iterdir(), key=lambda p: p.name)
            if x.is_dir() and (x / "SKILL.md").is_file()]
