import json, os, subprocess, uuid
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

class InductionError(RuntimeError): pass

@dataclass
class InductionPlan:
    rel_target: str
    has_nested_git: bool
    gitdir: str            # 父仓 git admin dir 绝对路径

def _run(cwd, *a, check=True):
    return subprocess.run(["git","-C",str(cwd),*a], check=check, capture_output=True, text=True)

def _admin(gitdir: str) -> Path:
    d = Path(gitdir) / "hub-induction"; d.mkdir(parents=True, exist_ok=True); return d

def prepare_induction(parent_root, rel_target: str) -> InductionPlan:
    parent_root = Path(parent_root)
    tgt = (parent_root / rel_target).resolve()
    if os.path.commonpath([str(tgt), str(parent_root.resolve())]) != str(parent_root.resolve()):
        raise InductionError(f"{rel_target} 逃出父仓，拒绝")
    gitdir = os.path.abspath(os.path.join(str(parent_root),
        _run(parent_root, "rev-parse", "--git-dir").stdout.strip()))
    return InductionPlan(rel_target, (parent_root/rel_target/".git").exists(), gitdir)

def _has_gitlink(parent_root, rel) -> bool:
    out = _run(parent_root, "ls-files", "-s", "--", rel, check=False).stdout
    return any(l.startswith("160000") for l in out.splitlines())

def recover_pending(parent_root, w: Writer) -> list[str]:
    parent_root = Path(parent_root)
    gitdir = os.path.abspath(os.path.join(str(parent_root),
        _run(parent_root, "rev-parse", "--git-dir").stdout.strip()))
    j = _admin(gitdir) / "journal.json"
    if not j.exists(): return []
    rec = json.loads(j.read_text(encoding="utf-8"))
    dest = parent_root / rec["rel_target"] / ".git"
    stash = Path(rec["stash_git"])
    if stash.exists() and dest.exists():
        raise InductionError(f"{rec['rel_target']}：stash 与原 .git 同时存在，需人工裁决")
    if stash.exists() and not dest.exists():
        os.replace(str(stash), str(dest))
    if not dest.exists():
        raise InductionError(f"恢复失败：{rec['rel_target']} 的 .git 不见了")
    w.unlink(j)
    return [rec["rel_target"]]

def execute_induction(plan: InductionPlan, parent_root, w: Writer) -> None:
    parent_root = Path(parent_root)
    if w.dry_run:
        print(f"  [dry-run] induct {plan.rel_target}"
              f"（{'移 .git 出树→add→恢复' if plan.has_nested_git else '直接 add'}）")
        return
    recover_pending(parent_root, w)
    if not plan.has_nested_git:
        _run(parent_root, "add", "--", plan.rel_target); return
    admin = _admin(plan.gitdir); stash = admin / "stash" / uuid.uuid4().hex
    stash.mkdir(parents=True); stash_git = stash / ".git"
    gitpath = parent_root / plan.rel_target / ".git"
    w.write_text_atomic(admin/"journal.json",
        json.dumps({"rel_target": plan.rel_target, "stash_git": str(stash_git)}))
    try:
        os.replace(str(gitpath), str(stash_git))
        _run(parent_root, "add", "--", plan.rel_target)
        if _has_gitlink(parent_root, plan.rel_target):
            _run(parent_root, "reset", "-q", "--", plan.rel_target, check=False)  # 回未跟踪态
            raise InductionError(f"{plan.rel_target} 被记成 gitlink，已回滚")
    finally:
        if stash_git.exists() and not gitpath.exists():
            os.replace(str(stash_git), str(gitpath))
    if not gitpath.exists():
        raise InductionError(f"{plan.rel_target} 的 .git 恢复失败")
    w.unlink(admin/"journal.json")
