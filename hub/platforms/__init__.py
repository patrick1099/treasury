"""平台注册表：hub 认识哪些 AI 平台、这台机器启用哪些。

「平台」是 hub 的一条变化轴（claude / codex / opencode / dsh，以后还会增减）。这里是
成员清单的**唯一出处**：调用方一律从这里派生名单，不另写 `("claude", "codex", ...)`，
也不按平台名分支——平台之间的差别由各自的适配器（本包下同名模块）声明成能力，调用方去问适配器。

- 注册表只登记「名字 → 模块路径」。`all_names()` / `enabled_names()` 不 import 任何适配器，
  scope 校验、argparse choices 这类只要名字的地方随便调。
- 适配器按需惰性加载，逐个加载、逐个记录失败：一个平台的模块坏了（依赖缺失、导入报错），
  `enabled()` 把它标成不可用＋原因，其余平台照常。
- 本机启用哪些由 device.toml 顶层 `platforms = [...]` 决定：不写 = 注册表全部（老设备不改
  配置行为不变）；`[]` = 全部停用；写了未注册的名字或类型不对 → PlatformConfigError。
  停用的平台 hub 完全不碰：不 import、不探测、不出视图、不建链、不写配置。

加一个平台 = 在 REGISTRY 加一行 ＋ 写它的适配器模块；去掉一个平台 = 删这一行和那个模块。
"""
import importlib
from dataclasses import dataclass

REGISTRY: dict[str, str] = {
    "claude": "hub.platforms.claude",
    "codex": "hub.platforms.codex",
    "opencode": "hub.platforms.opencode",
    "dsh": "hub.platforms.dsh",
}


class PlatformConfigError(ValueError):
    """device.toml 的 platforms 写错了（类型不对 / 名字没注册）。"""


class PlatformDisabled(ValueError):
    """点名要一个本机已停用的平台。"""


class PlatformUnavailable(RuntimeError):
    """平台已启用，但这台机器上用不了：适配器加载失败，或它依赖的外部东西缺失。"""


@dataclass
class Loaded:
    name: str
    adapter: object = None      # 加载失败时为 None
    error: str | None = None    # 不可用的原因


def all_names() -> tuple[str, ...]:
    return tuple(REGISTRY)


def enabled_names(dev) -> tuple[str, ...]:
    """本机启用的平台名，按注册表顺序。dev 为 None（还没有 device.toml）按缺省处理。"""
    raw = getattr(dev, "platforms", None) if dev is not None else None
    if raw is None:
        return all_names()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise PlatformConfigError(
            f"device.toml 的 platforms 必须是字符串数组，收到 {raw!r}")
    unknown = [x for x in raw if x not in REGISTRY]
    if unknown:
        raise PlatformConfigError(
            f"device.toml 的 platforms 里有未注册的平台 {unknown}（已注册：{list(REGISTRY)}）")
    return tuple(n for n in REGISTRY if n in raw)


def load(name: str):
    """加载一个平台的适配器。未注册 → PlatformConfigError；导入失败 → PlatformUnavailable。"""
    if name not in REGISTRY:
        raise PlatformConfigError(f"未知平台 {name!r}（已注册：{list(REGISTRY)}）")
    try:
        module = importlib.import_module(REGISTRY[name])
        return module.ADAPTER
    except Exception as e:
        raise PlatformUnavailable(f"{name} 适配器加载失败：{type(e).__name__}: {e}") from e


def enabled(dev) -> list[Loaded]:
    """本机启用的平台，逐个加载。加载失败不抛，记进 Loaded.error，由调用方决定怎么汇总。"""
    out: list[Loaded] = []
    for name in enabled_names(dev):
        try:
            out.append(Loaded(name, load(name)))
        except PlatformUnavailable as e:
            out.append(Loaded(name, None, str(e)))
    return out


def check_enabled(dev, name: str) -> None:
    """点名要一个平台但只需要名字（不加载适配器）：未注册 → PlatformConfigError；停用 → PlatformDisabled。"""
    if name not in REGISTRY:
        raise PlatformConfigError(f"未知平台 {name!r}（已注册：{list(REGISTRY)}）")
    if name not in enabled_names(dev):
        raise PlatformDisabled(
            f"平台 {name} 在本机已停用（device.toml 的 platforms 没有它）；要用先把它加回去。")


def require(dev, name: str):
    """点名要一个平台并加载它：停用 → PlatformDisabled；坏了 → PlatformUnavailable。都是明确失败。"""
    check_enabled(dev, name)
    return load(name)


def cli_dialect(name: str) -> str:
    """走官方插件 CLI 的平台用的是哪种命令方言。不走 CLI 的平台问这个 → ValueError。"""
    adapter = load(name)
    dialect = getattr(adapter, "cli_dialect", None)
    if not dialect:
        raise ValueError(f"平台 {name} 不走插件 CLI")
    return dialect


def unavailable_message(loaded: list[Loaded], extra: list[str] = ()) -> str | None:
    """把加载失败和额外收集到的不可用原因拼成一条消息；都没有返回 None。"""
    reasons = [x.error for x in loaded if x.error] + list(extra)
    if not reasons:
        return None
    return "以下已启用的平台不可用，本次一个字节都没写：\n  " + "\n  ".join(reasons)
