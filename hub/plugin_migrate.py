import json, subprocess, tomllib
from dataclasses import dataclass
from pathlib import Path
from hub.snapshot import is_git_repo

# os 用于 lexists/realpath/commonpath 的容器与源目录 containment 预检。
import os

@dataclass
class MigrationAction:
    id: str; kind: str; describe: str
    src: str = ""; dest: str = ""; text: str = ""; depends_on: tuple = ()

@dataclass
class MigrationPlan:
    actions: list; warnings: list; needs_author: list

class MigrationInputError(RuntimeError): pass

def load_migration_input(path) -> dict:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, body in raw.items():
        if "platforms" not in body:
            raise MigrationInputError(f"{name}: 迁移输入缺 platforms")
        platforms = list(body["platforms"]); enabled = list(body.get("enabled", []))
        if not platforms or any(t not in {"claude","codex"} for t in platforms):
            raise MigrationInputError(f"{name}: platforms 必须是非空 claude/codex 列表")
        if any(t not in platforms for t in enabled):
            raise MigrationInputError(f"{name}: enabled 必须是 platforms 的子集")
        out[name] = {"platforms": platforms, "enabled": enabled}
    return out

def _q(lst): return "[" + ", ".join(f'"{x}"' for x in lst) + "]"

def _market_ready(src: Path, name: str) -> bool:
    try:
        m = json.loads((src/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        p = json.loads((src/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        rows = m.get("plugins") or []
        return (m.get("name") == name and len(rows) == 1
                and rows[0].get("name") == name and rows[0].get("source") == "."
                and p.get("name") == name and bool(p.get("version")))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return False

def _index_modes(vault_root: Path, rel: str) -> list[str]:
    r=subprocess.run(["git","-C",str(vault_root),"ls-files","-s","--",rel],
                     capture_output=True,text=True)
    if r.returncode!=0:
        raise MigrationInputError(f"父金库 git index 不可读: {r.stderr.strip()}")
    return [line.split()[0] for line in r.stdout.splitlines() if line.strip()]

def prepare_migration(src_dir, vault_root, input_path) -> MigrationPlan:
    src_dir = Path(src_dir); vault_root = Path(vault_root)
    inp = load_migration_input(input_path)
    src_real=src_dir.resolve(); vault_real=vault_root.resolve()
    shared=vault_root/"shared"; plugins=shared/"plugins"
    if ((os.path.lexists(shared) and Path(os.path.realpath(shared)) != vault_real/"shared")
            or (os.path.lexists(plugins)
                and Path(os.path.realpath(plugins)) != vault_real/"shared"/"plugins")):
        raise MigrationInputError("shared/plugins 容器是链接/逃逸路径，拒绝迁移")
    src_names={p.name for p in src_dir.iterdir() if p.is_dir() and is_git_repo(p)}
    dest_root=vault_root/"shared/plugins"
    dest_names=({p.name for p in dest_root.iterdir() if p.is_dir() and is_git_repo(p)}
                if dest_root.is_dir() else set())
    known=src_names|dest_names
    if known != set(inp):
        raise MigrationInputError(
            f"迁移输入与源/目标仓集合不一致：未声明={sorted(known-set(inp))}，不存在={sorted(set(inp)-known)}")
    actions, warnings, needs_author = [], [], []
    mf_lines, enabled_by_tool = [], {}
    for name, spec in inp.items():
        s=src_dir/name; rel=f"shared/plugins/{name}"; dest=vault_root/rel
        in_src=name in src_names; in_dest=name in dest_names
        if in_src and in_dest:
            raise MigrationInputError(f"{name}: plugins-dev 与 shared/plugins 同时存在，需人工裁决")
        active=s if in_src else dest
        base=src_real if in_src else dest_root.resolve()
        real=active.resolve()
        if (active.is_symlink() or not active.is_dir() or not is_git_repo(active)
                or os.path.commonpath([str(real),str(base)]) != str(base)):
            raise MigrationInputError(f"{name}: 当前仓不是预期容器内真实 git 目录")
        if not _market_ready(active, name):
            needs_author.append(name)
        if in_src:
            mv=MigrationAction(f"{name}:move","move",f"复制 {name} → {rel}",src=str(s),dest=str(dest))
            actions += [mv,MigrationAction(f"{name}:induct","induct",f"induct {name}",
                                           dest=rel,depends_on=(mv.id,))]
        else:
            modes=_index_modes(vault_root,rel)
            if "160000" in modes:
                raise MigrationInputError(f"{name}: 父仓 index 仍是 gitlink，拒绝继续")
            if not modes:                         # 上次只完成 copy+删源；本次从 induction 继续
                actions.append(MigrationAction(f"{name}:induct","induct",f"induct {name}",dest=rel))
        mf_lines.append(f"[{name}]\nplatforms = {_q(spec['platforms'])}\n")
        for tool in spec["enabled"]:
            enabled_by_tool.setdefault(tool, []).append(name)
    actions.append(MigrationAction("write:manifest", "write", "写 shared/plugins/manifest.toml",
                   dest=str(vault_root/"shared/plugins/manifest.toml"), text="\n".join(mf_lines)))
    dev_lines = "".join(f"[plugins.{t}]\nenabled = {_q(sorted(v))}\n"
                        for t, v in sorted(enabled_by_tool.items()))
    actions.append(MigrationAction("write:device-snippet", "write",
                   "写 device 的 [plugins.*] 建议片段（作者审后并入 device.toml）",
                   dest=str(vault_root/"plugins-device-snippet.toml"), text=dev_lines))
    return MigrationPlan(actions, warnings, needs_author)
