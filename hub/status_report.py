"""C 的状态检查（只读）。Plan 1 只报 skill 链接健康。

只检查 shared/skills/ 里的**期望项**——没 manifest 就无法安全判定某额外目录
以前归不归 hub 管，故本机自带的本地 skill 一律不报，免得把用户的东西冤成残留。
"""
import os
from pathlib import Path
from hub.model import DeviceProfile
from hub.register import skill_targets
from hub.fslink import resolves_to
from hub.vaultpaths import shared_skills_dir, within_shared_skills

def link_status(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, str]]:
    vault_root = Path(vault_root)
    shared = shared_skills_dir(vault_root)             # 逃逸容器→抛 SharedSkillsEscape
    shared_skills = sorted((d for d in shared.iterdir()
                            if d.is_dir() and within_shared_skills(d, vault_root)),
                           key=lambda p: p.name) if shared.is_dir() else []
    rows: list[tuple[str, str]] = []
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                rows.append(("conflict", f"{target_dir}（skills 容器是链接/非目录）"))
                continue
        for src in shared_skills:
            link = target_dir / src.name
            label = str(link)
            if not os.path.lexists(link):
                rows.append(("missing", label))
            elif resolves_to(link, src):
                rows.append(("ok", label))
            else:
                rows.append(("conflict", label))     # 指别处 / 用户真目录 / 解析失败
    return rows

def view_health(vault_root: Path, dev: DeviceProfile, hub_root: Path) -> list[tuple[str, str]]:
    """memory 视图健康。只读。状态 ∈ {ok, missing, conflict, stale, degraded}。"""
    import json
    from hub.memwire import hub_views_home, _view_path, _codex_agents_target
    from hub.hubconfig import hub_config_path, read_config
    from hub.memview import load_shared_memories, shared_hash
    from hub.opencode_cfg import opencode_config_path
    rows: list[tuple[str, str]] = []
    # ① config.toml：存在且 vault/host 一致
    cfg = read_config()
    if not cfg:
        rows.append(("missing", str(hub_config_path())))
    elif cfg.get("vault") != Path(vault_root).resolve().as_posix() or cfg.get("host") != dev.host:
        rows.append(("conflict", f"{hub_config_path()}（绑定的 vault/host 与本次不符）"))
    else:
        rows.append(("ok", str(hub_config_path())))
    # ② hub-memory 链：目标必须精确指向 hub 包里那把
    hm_src = Path(hub_root) / "hub" / "skills" / "hub-memory"
    for target_dir in skill_targets(dev):
        link = target_dir / "hub-memory"
        if not os.path.lexists(link):
            rows.append(("missing", str(link)))
        else:
            rows.append(("ok" if resolves_to(link, hm_src) else "conflict", str(link)))
    # ③ 三份视图 + 新鲜度（视图头嵌的 shared_hash 与当前 shared 比对）
    cur = shared_hash(load_shared_memories(vault_root))
    for tool in ("claude", "codex", "opencode"):
        v = _view_path(tool)
        if not v.exists():
            rows.append(("missing", str(v))); continue
        embedded = ""
        for line in v.read_text(encoding="utf-8").splitlines():
            if "shared_hash:" in line:
                embedded = line.split("shared_hash:")[1].replace("-->", "").strip(); break
        rows.append(("ok" if embedded == cur else "stale", str(v)))
    # ④/⑤ 受管块：必须**良构**（恰一对标记），不能只 "hub:begin" in text 就算 ok
    from hub.textblock import has_one_valid_block
    def _block_state(f: Path) -> str:
        if not f.exists():
            return "missing"
        t = f.read_text(encoding="utf-8")
        if has_one_valid_block(t):
            return "ok"
        return "malformed" if ("hub:begin" in t or "hub:end" in t) else "missing"
    if dev.paths.get("CLAUDE_HOME"):
        cm = Path(dev.paths["CLAUDE_HOME"]) / "CLAUDE.md"
        rows.append((_block_state(cm), str(cm)))
    if dev.paths.get("CODEX_HOME"):                     # Codex **活动**块（override 优先）
        tgt = _codex_agents_target(dev)
        rows.append((_block_state(tgt), str(tgt)))
    # ⑥ opencode 条目（仅设备显式设 OPENCODE_CONFIG 才报；不因默认路径恰有文件就碰它）
    if dev.paths.get("OPENCODE_CONFIG"):
        ocfg = opencode_config_path(dev)
        if ocfg.exists():
            try:
                data = json.loads(ocfg.read_text(encoding="utf-8"))
                instr = data.get("instructions") if isinstance(data, dict) else None
                ok = isinstance(instr, list) and _view_path("opencode").as_posix() in instr
                rows.append(("ok" if ok else "degraded", str(ocfg)))
            except (ValueError, OSError):
                rows.append(("degraded", f"{ocfg}（非严格 JSON，未接线）"))
    return rows
