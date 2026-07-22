import hashlib, json, shutil, stat, subprocess, tomllib
from dataclasses import dataclass, field
from pathlib import Path
from hub.induction import prepare_induction, execute_induction
from hub.snapshot import is_git_repo
from hub.writer import Writer

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

@dataclass
class MigrationReport:
    done: list = field(default_factory=list)
    failed: list = field(default_factory=list)

def _file_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def _tree_manifest(root: Path) -> list:
    """不跟随目录链接；比较相对路径、对象类型和文件内容/链接目标。"""
    root=Path(root); rows=[]
    for cur, dirs, files in os.walk(root, followlinks=False):
        curp=Path(cur)
        for name in sorted(dirs+files):
            p=curp/name; rel=p.relative_to(root).as_posix()
            if p.is_symlink(): rows.append((rel,"link",os.readlink(p)))
            elif p.is_dir(): rows.append((rel,"dir",""))
            else: rows.append((rel,"file",_file_sha256(p)))
    return sorted(rows)

def _onexc_writable(func, p, exc):
    # git 在 Windows 上把 .git/objects 下的对象文件设为只读，裸 shutil.rmtree 删不动；
    # 沿用 tests/hub/test_plugin_refresh.py 里已有的同款 chmod 后重试写法。
    os.chmod(p, stat.S_IWRITE); func(p)

def _clear_readonly(root: Path) -> None:
    """删源前把整棵树改可写：同一个只读对象文件的问题会挡住 Writer.rmtree 里那句裸
    shutil.rmtree（它是唯一写入口，不在这里改它的行为），所以删除前先在这一层解只读。"""
    for cur, dirs, files in os.walk(root):
        for name in dirs + files:
            p = os.path.join(cur, name)
            try: os.chmod(p, stat.S_IWRITE)
            except OSError: pass
    try: os.chmod(root, stat.S_IWRITE)
    except OSError: pass

def _do_move(src, dest, w: Writer):
    src, dest = Path(src), Path(dest)
    if w.dry_run:
        print(f"  [dry-run] 复制 {src} → {dest} + 校验 + 删源"); return
    if dest.exists():
        raise MigrationInputError(f"目标已存在 {dest}，拒绝覆盖")
    dest.parent.mkdir(parents=True, exist_ok=True)
    before=_tree_manifest(src)
    shutil.copytree(src, dest, symlinks=True)       # 含 .git；保留链接；跨盘安全
    if before != _tree_manifest(dest):
        try: shutil.rmtree(dest, onexc=_onexc_writable)   # 尽力清掉坏副本
        except OSError: pass
        raise MigrationInputError(f"{src}→{dest} 复制校验失败（路径/类型/SHA-256 不同）")
    _clear_readonly(src)
    w.rmtree(src)

def execute_migration(plan, vault_root, w: Writer) -> MigrationReport:
    rep = MigrationReport()
    if plan.needs_author:
        rep.failed.append(("preflight:needs-author",
                           "缺 market-of-one: " + ", ".join(sorted(plan.needs_author))))
        return rep
    done=set()
    for a in plan.actions:
        missing=[d for d in a.depends_on if d not in done]
        if missing:
            rep.failed.append((a.id,"未满足依赖: " + ", ".join(missing))); break
        try:
            if a.kind == "move":
                _do_move(a.src, a.dest, w)
            elif a.kind == "induct":
                execute_induction(prepare_induction(vault_root, a.dest), vault_root, w)
            elif a.kind == "write":
                w.write_text_atomic(Path(a.dest), a.text)
            rep.done.append(a.id); done.add(a.id)
        except Exception as e:
            rep.failed.append((a.id, str(e))); break    # 强序列：失败即停（源已备份，见 T15）
    return rep
