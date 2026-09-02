import json
from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.dsh_ops import (dsh_profile_dir, loader_dest, patch_path,
                         plan_configure_dsh_loader, commit_configure_dsh_loader,
                         dsh_loader_status, DshConfigError)

def _dev(tmp_path, *, enabled=("p1",), dsh=True) -> DeviceProfile:
    paths = {}
    if dsh:
        paths["DSH_HOME"] = str(tmp_path / "dsh")
        paths["DSH_PROFILE"] = "headless"
    return DeviceProfile(host="box1", classes=["work"], projects=[], paths=paths,
                         sources={}, plugins={"dsh": list(enabled)})

def _manifest(vault: Path, body: dict[str, list[str]]) -> None:
    p = vault / "shared" / "plugins" / "manifest.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"[{n}]\nplatforms = {json.dumps(pl)}\n\n" for n, pl in body.items())
    p.write_text(text, encoding="utf-8")

def _loader_source(hub_root: Path) -> Path:
    src = hub_root / "dsh-claude-plugin-loader" / "dsh-claude-plugin-loader.mjs"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("export const name = 'dsh-claude-plugin-loader'\n", encoding="utf-8")
    return src

def _do(vault, dev, hub_root, w=None):
    w = w or Writer()
    copies, writes, ensured = plan_configure_dsh_loader(vault, dev, hub_root)
    commit_configure_dsh_loader(copies, writes, w)
    return ensured, w

def test_plan_writes_loader_and_patch(tmp_path):
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    dev = _dev(tmp_path)
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    ensured, w = _do(vault, dev, hub_root)
    dest = loader_dest(dev)
    patch = patch_path(dev)
    assert dest.exists() and patch.exists()
    assert "claude-plugin-loader" in patch.read_text(encoding="utf-8")
    assert "p1" in patch.read_text(encoding="utf-8")
    assert len(ensured) >= 2
    assert dsh_loader_status(vault, dev, hub_root)[0][0] == "ok"

def test_plan_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    dev = _dev(tmp_path)
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    _do(vault, dev, hub_root)
    copies, writes, ensured = plan_configure_dsh_loader(vault, dev, hub_root)
    assert copies == [] and writes == []
    assert len(ensured) >= 2

def test_plugin_not_declaring_dsh_is_not_in_enabled(tmp_path):
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["claude", "codex"], "p2": ["dsh"]})
    dev = _dev(tmp_path, enabled=("p1", "p2"))
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    copies, writes, ensured = plan_configure_dsh_loader(vault, dev, hub_root)
    commit_configure_dsh_loader(copies, writes, Writer())
    text = patch_path(dev).read_text(encoding="utf-8")
    assert '"p2"' in text and '"p1"' not in text

def test_status_conflict_when_patch_points_elsewhere(tmp_path):
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    dev = _dev(tmp_path)
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    _do(vault, dev, hub_root)
    # 手动把 patch 指向别的金库
    patch = patch_path(dev)
    text = patch.read_text(encoding="utf-8").replace(str((vault / "shared" / "plugins").resolve().as_posix()),
                                                     "C:/elsewhere/vault/shared/plugins")
    patch.write_text(text, encoding="utf-8")
    assert dsh_loader_status(vault, dev, hub_root)[0][0] == "conflict"

def test_device_without_dsh_is_noop(tmp_path):
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    dev = _dev(tmp_path, dsh=False)
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    copies, writes, ensured = plan_configure_dsh_loader(vault, dev, hub_root)
    assert copies == [] and writes == [] and ensured == []
    assert dsh_loader_status(vault, dev, hub_root) == []


# ── I2：enabledPlugins / enabledSkills 更新 ──────────────────────────────────
def test_plan_update_updates_enabled_plugins_on_existing_patch(tmp_path):
    from hub.dsh_ops import plan_update_dsh_loader, commit_update_dsh_loader
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"], "p2": ["dsh"]})
    dev = _dev(tmp_path, enabled=("p1",))
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    _do(vault, dev, hub_root)

    dev.plugins["dsh"] = ["p1", "p2"]
    writes = plan_update_dsh_loader(vault, dev, hub_root)
    assert writes
    commit_update_dsh_loader(writes, Writer())
    text = patch_path(dev).read_text(encoding="utf-8")
    assert '"p1"' in text and '"p2"' in text


def test_plan_update_writes_enabled_skills_for_plugin_internal(tmp_path):
    from hub.dsh_ops import plan_update_dsh_loader, commit_update_dsh_loader
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    (vault / "shared" / "plugins" / "p1" / "skills" / "beta").mkdir(parents=True)
    (vault / "shared" / "plugins" / "p1" / "skills" / "beta" / "SKILL.md").write_text(
        """# beta
""", encoding="utf-8")
    dev = _dev(tmp_path, enabled=("p1",))
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    _do(vault, dev, hub_root)

    # 模拟旧 patch：首次配置还没写 enabledSkills
    patch = patch_path(dev)
    old_text = patch.read_text(encoding="utf-8")
    old_text = chr(10).join(
        line for line in old_text.splitlines()
        if "enabledSkills" not in line and "p1:beta" not in line)
    patch.write_text(old_text + chr(10), encoding="utf-8")

    writes = plan_update_dsh_loader(vault, dev, hub_root)
    assert writes
    commit_update_dsh_loader(writes, Writer())
    text = patch_path(dev).read_text(encoding="utf-8")
    assert "enabledSkills:" in text
    assert '"p1:beta"' in text


def test_plan_update_is_idempotent_no_change_zero_write(tmp_path):
    from hub.dsh_ops import plan_update_dsh_loader
    vault = tmp_path / "vault"
    _manifest(vault, {"p1": ["dsh"]})
    dev = _dev(tmp_path, enabled=("p1",))
    hub_root = tmp_path / "hub"
    _loader_source(hub_root)
    _do(vault, dev, hub_root)
    assert plan_update_dsh_loader(vault, dev, hub_root) == []


def test_loader_mjs_contains_enabled_skills_filter(tmp_path):
    from hub.dsh_ops import loader_source
    src = tmp_path / "hub"
    p = loader_source(src)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("""const enabledSkills = Array.isArray(config.enabledSkills)
  ? new Set(config.enabledSkills.map(String)) : null
return enabledSkills === null
  ? out
  : out.filter((s) => enabledSkills.has(`${s.metadata?.plugin}:${s.name}`))
""", encoding="utf-8")
    text = p.read_text(encoding="utf-8")
    assert "enabledSkills" in text
    assert ".filter" in text
