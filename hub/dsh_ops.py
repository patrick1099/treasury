"""dsh 平台接入：让 hub 认识 dsh，并管理 dsh-claude-plugin-loader 的配置。

dsh 与 opencode 一样**没有 Claude/Codex 那种插件安装 CLI**。它的能力装载靠
`dsh-claude-plugin-loader`（dsh plugin）直接扫描 Claude 式插件源。hub 在这一侧
只做两件事：

1. **配置管理**：把 loader 源码放进目标 dsh profile，并在 `cordis.patch.yml`
   里写入/更新 loader 条目（pluginRoots + enabledPlugins）。
2. **健康检查**：`hub status --check` 检查 loader 是否已安装、是否指向当前金库。

与 opencode 同口径的“两道闸”：
- `manifest.toml` 的 `platforms` 含 `dsh`：插件声明支持 dsh；
- `device.toml` 的 `[plugins.dsh].enabled`：这台机器要它。

loader 侧用 `config.enabledPlugins` 过滤插件名，因此未启用的插件不会把 skill
暴露给 dsh。
"""
import json
import os
from pathlib import Path

from hub.model import DeviceProfile
from hub.writer import Writer
from hub.plugin_manifest import load_plugin_manifest

DEFAULT_DSH_PROFILE = "headless"

class DshConfigError(RuntimeError):
    pass


def dsh_home(dev: DeviceProfile) -> Path | None:
    """dsh 配置目录。device.toml 显式设 DSH_HOME 优先，否则用默认 ~/.dsh（存在才认）。"""
    v = dev.paths.get("DSH_HOME")
    if v:
        return Path(v)
    default = Path.home() / ".dsh"
    return default if default.exists() else None


def dsh_profile(dev: DeviceProfile) -> str:
    return dev.paths.get("DSH_PROFILE") or DEFAULT_DSH_PROFILE


def dsh_profile_dir(dev: DeviceProfile) -> Path | None:
    home = dsh_home(dev)
    if home is None:
        return None
    return home / "profiles" / dsh_profile(dev)


def loader_source(hub_root: Path) -> Path:
    return Path(hub_root) / "dsh-claude-plugin-loader" / "dsh-claude-plugin-loader.mjs"


def loader_dest(dev: DeviceProfile) -> Path | None:
    prof = dsh_profile_dir(dev)
    return None if prof is None else prof / "dsh-claude-plugin-loader.mjs"


def patch_path(dev: DeviceProfile) -> Path | None:
    prof = dsh_profile_dir(dev)
    return None if prof is None else prof / "cordis.patch.yml"


def enabled_dsh_plugins(vault_root: Path, dev: DeviceProfile) -> list[str]:
    """manifest 声明 dsh 且本机 [plugins.dsh].enabled 的插件名（排序）。"""
    enabled = set(dev.plugins.get("dsh", []))
    if not enabled:
        return []
    out = []
    for entry in load_plugin_manifest(vault_root):
        if "dsh" in entry.platforms and entry.name in enabled:
            out.append(entry.name)
    return sorted(out)


def _claude_plugin_cache_root(dev: DeviceProfile) -> Path:
    ch = dev.paths.get("CLAUDE_HOME")
    if ch:
        return Path(ch) / "plugins" / "cache"
    return Path.home() / ".claude" / "plugins" / "cache"


def _patch_block(vault_root: Path, dev: DeviceProfile) -> str:
    roots = [str((Path(vault_root) / "shared" / "plugins").resolve().as_posix())]
    cache = _claude_plugin_cache_root(dev)
    if cache.exists():
        roots.append(cache.as_posix())
    lines = [
        "- insert:",
        "    - id: claude-plugin-loader",
        "      name: ./dsh-claude-plugin-loader.mjs",
        "      config:",
        "        pluginRoots:",
    ]
    for r in roots:
        lines.append(f'          - "{r}"')
    enabled = enabled_dsh_plugins(vault_root, dev)
    if enabled:
        lines.append("        enabledPlugins:")
        for name in enabled:
            lines.append(f'          - "{name}"')
    dsh_skills = desired_dsh_skills(vault_root, dev)
    if dsh_skills:
        lines.append("        enabledSkills:")
        for key in dsh_skills:
            lines.append(f'          - "{key}"')
    return "\n".join(lines)


def _upsert_patch(existing: str, new_block: str) -> str:
    """把 loader 的 insert 块安全加进现有 patch。

    - 已有 loader 条目 → 原样保留（不覆盖用户手工调整）；
    - 文件还是 `[]` 空列表 → 替换成新块；
    - 已有其它列表项 → 追加到列表末尾。
    """
    if "claude-plugin-loader" in existing:
        return existing
    stripped = existing.rstrip()
    if stripped.endswith("[]"):
        idx = stripped.rfind("[]")
        return stripped[:idx] + new_block + "\n"
    # 非空列表：确保以换行分隔后追加
    if stripped == "" or stripped.endswith("---"):
        return stripped + new_block + "\n"
    return existing.rstrip() + "\n" + new_block + "\n"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skill_desired(dev: DeviceProfile, name: str) -> bool:
    """[skills.dsh].enabled 缺省=全部开启；出现 key 后即为权威名单。"""
    enabled = dev.skills.get("dsh")
    if enabled is None:
        return True
    return name in enabled


def _plugin_internal_skill_names(vault_root: Path, plugin: str) -> list[str]:
    d = Path(vault_root) / "shared" / "plugins" / plugin / "skills"
    if not d.is_dir():
        return []
    return [x.name for x in sorted(d.iterdir(), key=lambda p: p.name)
            if x.is_dir() and (x / "SKILL.md").is_file()]


def desired_dsh_skills(vault_root: Path, dev: DeviceProfile) -> list[str]:
    """dsh 侧期望的 plugin-internal skill 列表，格式 "<plugin>:<skill>"。"""
    enabled_plugins = set(enabled_dsh_plugins(vault_root, dev))
    out: list[str] = []
    for entry in load_plugin_manifest(vault_root):
        if entry.name not in enabled_plugins or "dsh" not in entry.platforms:
            continue
        for name in _plugin_internal_skill_names(vault_root, entry.name):
            if _skill_desired(dev, name):
                out.append(f"{entry.name}:{name}")
    return sorted(out)


def _patch_set_array(text: str, key: str, items: list[str]) -> str:
    """在 claude-plugin-loader 的 config 块中更新/插入一个标量数组键。

    只重写目标键（含其列表行），保留块内其它键和注释。未找到 loader 条目时原样返回。
    """
    lines = text.splitlines()
    id_idx = None
    for i, line in enumerate(lines):
        if "id: claude-plugin-loader" in line:
            id_idx = i
            break
    if id_idx is None:
        return text
    id_indent = _indent(lines[id_idx])
    config_idx = None
    config_indent = None
    for i in range(id_idx + 1, len(lines)):
        if lines[i].strip() and _indent(lines[i]) < id_indent:
            break
        if lines[i].lstrip().startswith("config:"):
            config_idx = i
            config_indent = _indent(lines[i])
            break
    if config_idx is None:
        return text
    block_end = len(lines)
    for i in range(config_idx + 1, len(lines)):
        if lines[i].strip() and _indent(lines[i]) <= config_indent:
            block_end = i
            break
    out = lines[:config_idx + 1]
    children = lines[config_idx + 1:block_end]

    def _key_block(index: int, key_indent: int) -> int:
        end = index + 1
        while end < len(children):
            line = children[end]
            if not line.strip():
                end += 1
            elif line.lstrip().startswith("#") or _indent(line) > key_indent:
                end += 1
            else:
                break
        return end

    key_indent = config_indent + 2
    idx = None
    for j, line in enumerate(children):
        if (_indent(line) == key_indent and line.lstrip().startswith(key + ":")
                and not line.lstrip().startswith("#")):
            idx = j
            break

    def _new_lines():
        if items:
            return ([f"{' ' * key_indent}{key}:"] +
                    [f"{' ' * (key_indent + 2)}- {json.dumps(it)}" for it in items])
        return [f"{' ' * key_indent}{key}: []"]

    if idx is not None:
        end = _key_block(idx, key_indent)
        children = children[:idx] + _new_lines() + children[end:]
    else:
        children = children + _new_lines()

    result = chr(10).join(out + children + lines[block_end:])
    if text.endswith((chr(10), chr(13))) and not result.endswith((chr(10), chr(13))):
        result += chr(10)
    return result


def plan_update_dsh_loader(vault_root: Path, dev: DeviceProfile, hub_root: Path):
    """比较当前 loader patch 与期望的 enabledPlugins/enabledSkills，返回写入计划。

    无变化时返回空列表。只更新已存在的 loader 条目；未配置 loader 时返回空（由
    plan_configure_dsh_loader 负责首次创建/复制）。
    """
    patch = patch_path(dev)
    if patch is None or not patch.exists():
        return []
    text = patch.read_text(encoding="utf-8")
    if "claude-plugin-loader" not in text:
        return []
    enabled_plugins = enabled_dsh_plugins(vault_root, dev)
    enabled_skills = desired_dsh_skills(vault_root, dev)
    new_text = _patch_set_array(text, "enabledPlugins", enabled_plugins)
    # 只有在确实存在 dsh 插件内 skill 时才维护 enabledSkills；无内部 skill 时保持
    # 不写入该键（避免把“没有独立 skill 过滤”变成“全禁”）。
    has_plugin_skills = any(
        _plugin_internal_skill_names(vault_root, entry.name)
        for entry in load_plugin_manifest(vault_root)
        if entry.name in enabled_plugins and "dsh" in entry.platforms)
    if has_plugin_skills:
        new_text = _patch_set_array(new_text, "enabledSkills", enabled_skills)
    if new_text == text:
        return []
    return [(patch, new_text)]


def commit_update_dsh_loader(writes, w: Writer) -> None:
    for path, text in writes:
        w.write_text(path, text)


def plan_configure_dsh_loader(vault_root: Path, dev: DeviceProfile, hub_root: Path):
    """只读预检。返回 (copies, writes, ensured)。dsh 未安装/未配置时返回空，不报错。"""
    prof = dsh_profile_dir(dev)
    if prof is None:
        return [], [], []
    src = loader_source(hub_root)
    if not src.is_file():
        raise DshConfigError(f"hub 包缺 dsh loader 源码：{src}")
    dest = loader_dest(dev)
    patch = patch_path(dev)
    assert dest is not None and patch is not None

    copies: list[tuple[Path, Path]] = []
    writes: list[tuple[Path, str]] = []
    ensured: list[str] = []

    if not dest.exists():
        copies.append((src, dest))
        ensured.append(str(dest))
    else:
        ensured.append(str(dest))

    block = _patch_block(vault_root, dev)
    if not patch.exists():
        text = (
            "# Your patch layer for this dsh profile, applied after every bundle layer:\n"
            "# a top-level YAML array of loader patch entries (id-targeted config\n"
            "# overrides, disables, and insert lists; `!!js` expressions allowed).\n"
            + block + "\n"
        )
        writes.append((patch, text))
        ensured.append(str(patch))
    else:
        existing = patch.read_text(encoding="utf-8")
        if "claude-plugin-loader" not in existing:
            writes.append((patch, _upsert_patch(existing, block)))
            ensured.append(str(patch))
        elif (Path(vault_root) / "shared" / "plugins").as_posix() not in existing:
            # 已有 loader 但没指向当前金库：报冲突，不自动覆盖。
            raise DshConfigError(
                f"{patch} 已含 claude-plugin-loader 但 pluginRoots 未指向当前金库；"
                f"请人工核对后更新。")
        else:
            ensured.append(str(patch))

    return copies, writes, ensured


def commit_configure_dsh_loader(copies, writes, w: Writer) -> None:
    for src, dest in copies:
        w.copy_file(src, dest)
    for path, text in writes:
        w.write_text(path, text)


def dsh_loader_status(vault_root: Path, dev: DeviceProfile,
                      hub_root: Path) -> list[tuple[str, str]]:
    """只读健康检查。dsh 未安装/未配置 → 空表。状态 ∈ {ok, missing, conflict}。"""
    prof = dsh_profile_dir(dev)
    if prof is None:
        return []
    src = loader_source(hub_root)
    if not src.is_file():
        return [("conflict", f"{src}（hub 包缺 dsh loader 源码）")]
    dest = loader_dest(dev)
    patch = patch_path(dev)
    assert dest is not None and patch is not None
    if not prof.is_dir():
        return [("missing", str(prof))]
    if not dest.is_file():
        return [("missing", str(dest))]
    if not patch.is_file():
        return [("missing", str(patch))]
    text = patch.read_text(encoding="utf-8")
    if "claude-plugin-loader" not in text:
        return [("missing", f"{patch}（缺 claude-plugin-loader 条目）")]
    if (Path(vault_root) / "shared" / "plugins").as_posix() not in text:
        return [("conflict", f"{patch}（pluginRoots 未指向当前金库）")]
    return [("ok", f"dsh profile {dsh_profile(dev)} loader 已配置")]
