# hub 提取器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 hub 从"既收又发"改成"只收不发"——Python 只把本机各工具的家当提取进金库,落地交给各工具自己的 skill(C 阶段)。

**Architecture:** 删掉整个落地层(`materialize.py` / `roster.py` / `managed_block.py`)。金库改成**两区**:`<设备>/<工具>/` 备份区(原样、按工具分)与 `shared/` 共享区(精选、按类型分)。提取器五条流水线全部幂等全量重写,只写 `<本机>/`,不碰 `shared/`,不写任何工具地盘。所有写操作走唯一的 `Writer`,`--dry-run` 的闸设在它内部。

**Tech Stack:** Python 3.14,纯 stdlib(`tomllib` / `tarfile` / `subprocess` / `argparse`),pytest。

## Global Constraints

- **Python ≥3.11**(用 `tomllib`),纯 stdlib,不建 venv。Windows 上用 `py -3` 调用。
- **提取器只写金库。** 唯一例外是 `bootstrap`,且只写各工具的 skill 目录。
- **提取器只动 `<本机>/`。** `shared/` 与别的设备的文件夹**一个字节都不改**。
- **所有写/删走 `Writer`。** 不允许任何模块直接 `write_text` / `rmtree` 到金库。`--dry-run` 的闸在 `Writer` 内部——预览与真写共用同一条代码路径。
- **硬闸**:`~/.claude/secrets/`、`~/.codex/auth.json` 永不读取;gitignored/untracked 文件不进快照(用 `git archive`,不用 `cp -r`);`sensitive: true` 的记忆不入库。
- 仓库 `C:\Users\huawei\ai-cli-migrate`,git 身份 `patrick1099 <hsheng416@gmail.com>`,commit 结尾附 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 测试:`py -3 -m pytest`(配置在 `pytest.ini`,`pythonpath = .`,`testpaths = tests`)。
- 跑通判据:每个 task 结束时 `py -3 -m pytest` **全绿**。

## 与 spec 的一处偏离(已报备)

spec §4 把 **hooks** 列为独立流水线。实测:`~/.claude/settings.json` **没有 `hooks` 键**(Claude 的 hook 全在插件里,而插件已快照),`~/.codex/config.toml` 也没有 hooks 段。为恒空的东西单开流水线是过度工程。**改为**:hooks 声明并入 Task 9 的"抄声明"流水线(它读的本来就是同两个文件);金库里 `hooks/` 目录**按用户要求预留**(`.gitkeep`),在 `SCHEMA.md` 里注明"当前无内容,待有用户级 hook 时由 decl 流水线填充"。

## 文件结构

| 文件 | 职责 |
|---|---|
| `hub/model.py` | 改:`DeviceProfile.sources`(按工具分的源路径);删 `targets` / `collect_sources` / `Vault.rules` |
| `hub/vault.py` | 改:按两区结构读记忆(`shared/memory/` + `<host>/claude/memory/`) |
| `hub/frontmatter.py` | 改:认 YAML 块状列表;解析失败抛 `FrontmatterError`(调用方不许吞) |
| `hub/writer.py` | **新**:唯一的写/删路径,`--dry-run` 闸在这里 |
| `hub/guard.py` | **新**:硬闸——拒绝读取 secrets 类路径 |
| `hub/snapshot.py` | **新**:`git archive HEAD` 快照 + 仓库元数据(remote / sha / dirty) |
| `hub/tomlout.py` | **新**:极简 TOML 写出器(stdlib 没有 tomli-w) |
| `hub/secrets_scan.py` | **新**:软提醒——扫疑似密钥,只报告不阻断 |
| `hub/collect/__init__.py` | **新**:`run_all()` 串起四条流水线 |
| `hub/collect/memory.py` | **新**:记忆镜像 |
| `hub/collect/skills.py` | **新**:散装 skill 快照 |
| `hub/collect/decl.py` | **新**:自有插件源码快照 + 第三方插件/市场/hooks 声明抄写 |
| `hub/cli.py` | 改:只剩 `collect` / `sync` / `status` / `bootstrap` |
| `hub/derive.py` | 改:索引链接用相对金库根的真实路径 |
| `hub/scaffold_vault.py` | 改:生成两区结构 + `SCHEMA.md` |
| `hub/materialize.py` | **删** |
| `hub/roster.py` | **删**(格式定义搬进 `SCHEMA.md`) |
| `hub/managed_block.py` | **删**(只被 materialize 用) |
| `hub/backend.py` `links.py` `scope.py` | **不动** |

---

### Task 1: 拆除落地层

删掉 Python 里所有"替工具做主"的代码。先拆再建,避免中间态是坏的。

**Files:**
- Delete: `hub/materialize.py`, `hub/roster.py`, `hub/managed_block.py`
- Delete: `tests/hub/test_materialize.py`, `tests/hub/test_managed_block.py`
- Modify: `hub/cli.py`(删 `pull` / `process` / `review` / `accept` / `reject` / `promote` 及其 import)
- Modify: `tests/hub/test_cli.py`(删对应测试)

**Interfaces:**
- Consumes: 无
- Produces: 一个只剩 `collect` / `sync` / `status` 的 `hub.cli.build_parser()`;`hub.cli.main(argv) -> int` 签名不变

- [ ] **Step 1: 删文件**

```bash
cd /c/Users/huawei/ai-cli-migrate
git rm hub/materialize.py hub/roster.py hub/managed_block.py
git rm tests/hub/test_materialize.py tests/hub/test_managed_block.py
```

- [ ] **Step 2: 把 `hub/cli.py` 换成只剩三个子命令的版本**

整个文件替换成:

```python
import argparse
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths, load_lint_exempt
from hub.backend import GitBackend, ConflictError
from hub.collect import collect_memories

def _lint(vault, exempt: set[str]) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        if m.name not in exempt:
            errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _cmd_status(args) -> int:
    print(GitBackend(Path(args.vault)).status(), end="")
    return 0

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    sources = [Path(s) for s in dev.collect_sources]
    collected = collect_memories(sources, vault_root, host)
    print(f"collected {len(collected)} memories: {collected}")
    return 0

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    b = GitBackend(vault_root)
    try:
        b.acquire()
    except ConflictError as e:
        print("sync 停止:git 冲突,请手工解决后 `hub sync` 重试")
        print(e)
        return 2
    vault = load_vault(vault_root)
    errs = _lint(vault, load_lint_exempt(vault_root))
    if errs:
        print("sync 停止:lint 失败(敏感/裸路径/scope):")
        for e in errs:
            print("  -", e)
        return 1
    _write_index(vault_root, vault)
    b.publish("chore(hub): sync")
    return 0

def _write_index(vault_root: Path, vault) -> None:
    (vault_root / "MEMORY.md").write_text(
        render_memory_index(vault.memories), encoding="utf-8", newline="\n")

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("sync", _cmd_sync)):
        sub.add_parser(name, parents=[common]).set_defaults(func=fn)
    return p

def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
```

> 注:`from hub.collect import collect_memories` 现在仍指向旧的 `hub/collect.py`(单文件)。Task 6 会把它换成包。这一步只保证拆完后树是绿的。

- [ ] **Step 3: 删 `tests/hub/test_cli.py` 里所有 pull/review/accept/reject/promote/process 相关测试**

打开 `tests/hub/test_cli.py`,删掉函数名里含下列词的测试:`pull`、`review`、`accept`、`reject`、`promote`、`process`、`materialize`、`foreign`、`shared_pool`、`crlf`、`dry_run`。保留 `_mk_vault` 之类的 fixture 与 `status` / `collect` / `sync` / lint-exempt 相关测试。

- [ ] **Step 4: 跑测试**

Run: `py -3 -m pytest -q`
Expected: 全绿(条数会显著下降,这是预期的——落地层的测试跟着代码一起删了)

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "refactor(hub)!: 拆除落地层——Python 不再替任何工具做主

删 materialize/roster/managed_block 与 pull/process/review/accept/reject/promote。
落地(装进哪个工具、怎么装)归各工具自己的 skill,见 docs/specs/2026-07-12-hub-extractor-design.md。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Writer —— 唯一的写路径

`--dry-run` 的闸必须设在**最底层的写函数**里,而不是靠调用方自觉。2026-07-12 的事故就是"改配置假装预览"——改配置那一步静默失败了,于是"预览"照真实的写。**闸在写函数里,失败模式是"什么都不写";闸在调用方,失败模式是"照真实的写"。**

**Files:**
- Create: `hub/writer.py`
- Test: `tests/hub/test_writer.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class Writer(dry_run: bool = False)`
  - `Writer.write_text(path: Path, text: str) -> None`
  - `Writer.copy_tree(src: Path, dest: Path) -> None`(先清空 dest,再整目录拷)
  - `Writer.rmtree(path: Path) -> None`
  - `Writer.unlink(path: Path) -> None`
  - `Writer.written: list[Path]`、`Writer.removed: list[Path]`(供 dry-run 报告与测试断言)

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_writer.py`:

```python
from pathlib import Path
from hub.writer import Writer

def test_write_text_creates_parents(tmp_path):
    w = Writer()
    w.write_text(tmp_path / "a" / "b.md", "hi\n")
    assert (tmp_path / "a" / "b.md").read_text(encoding="utf-8") == "hi\n"
    assert w.written == [tmp_path / "a" / "b.md"]

def test_dry_run_writes_nothing(tmp_path):
    w = Writer(dry_run=True)
    w.write_text(tmp_path / "a" / "b.md", "hi\n")
    assert not (tmp_path / "a").exists()          # 一个字节都不落盘
    assert w.written == [tmp_path / "a" / "b.md"] # 但报告说它"会"写

def test_dry_run_rmtree_removes_nothing(tmp_path):
    d = tmp_path / "d"
    (d / "x").mkdir(parents=True)
    w = Writer(dry_run=True)
    w.rmtree(d)
    assert (d / "x").exists()
    assert w.removed == [d]

def test_copy_tree_is_full_rewrite(tmp_path):
    src, dest = tmp_path / "s", tmp_path / "d"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "new.txt").write_text("new", encoding="utf-8")
    dest.mkdir()
    (dest / "stale.txt").write_text("stale", encoding="utf-8")   # 上一轮的残留
    Writer().copy_tree(src, dest)
    assert (dest / "sub" / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (dest / "stale.txt").exists()      # 全量重写：残留必须消失

def test_write_text_preserves_existing_newline_style(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes(b"old\r\nline\r\n")
    Writer().write_text(p, "new\nline\n")
    assert p.read_bytes() == b"new\r\nline\r\n"    # 沿用原有 CRLF，不制造整文件重写

def test_new_file_uses_lf(tmp_path):
    p = tmp_path / "a.md"
    Writer().write_text(p, "new\nline\n")
    assert p.read_bytes() == b"new\nline\n"
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_writer.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.writer'`

- [ ] **Step 3: 实现 `hub/writer.py`**

```python
"""金库的唯一写入口。

**所有**写/删都必须走这里。--dry-run 的闸设在这一层,不设在调用方——
配置式预览的失败模式是"照真实的写"(最危险的方向);闸在写函数里的失败模式是
"什么都不写"。这条是 2026-07-12 用一次真实事故换来的。
"""
import shutil
from pathlib import Path

class Writer:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.written: list[Path] = []
        self.removed: list[Path] = []

    def write_text(self, path: Path, text: str) -> None:
        path = Path(path)
        self.written.append(path)
        if self.dry_run:
            n = len(text.encode("utf-8"))
            print(f"  [dry-run] {'改写' if path.exists() else '新建'} {path}  ({n} 字节)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = "\n"
        if path.exists():
            # 沿用目标原有的换行风格：一律按 LF 写回会把仓库里的 CRLF 文件记成整文件重写。
            newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
        path.write_text(text, encoding="utf-8", newline=newline)

    def rmtree(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        self.removed.append(path)
        if self.dry_run:
            print(f"  [dry-run] 删除目录 {path}")
            return
        shutil.rmtree(path)

    def unlink(self, path: Path) -> None:
        path = Path(path)
        if not path.exists():
            return
        self.removed.append(path)
        if self.dry_run:
            print(f"  [dry-run] 删除 {path}")
            return
        path.unlink()

    def copy_tree(self, src: Path, dest: Path) -> None:
        """派生目录的全量重写:先清空 dest,再整棵拷过去。

        不做增量——派生目录的真源永远在别处,金库这份改了也白改。
        """
        self.rmtree(dest)
        if self.dry_run:
            print(f"  [dry-run] 拷贝 {src} → {dest}")
            self.written.append(Path(dest))
            return
        shutil.copytree(src, dest)
        self.written.append(Path(dest))
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_writer.py -q`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add hub/writer.py tests/hub/test_writer.py
git commit -m "feat(hub): Writer —— 唯一的写路径,dry-run 闸设在最底层

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 金库两区结构

**Files:**
- Modify: `hub/model.py`, `hub/vault.py`, `hub/derive.py`
- Test: `tests/hub/test_vault.py`, `tests/hub/test_derive.py`, `tests/hub/test_model.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `hub.model.SHARED = "shared"`
  - `hub.model.ToolSources(memory: list[str], skills: str | None, plugin_repos: str | None, settings: str | None, agents: str | None)`
  - `hub.model.DeviceProfile(host, classes, projects, paths, sources: dict[str, ToolSources])` —— **删掉** `targets` 与 `collect_sources`
  - `hub.model.Vault(root, config, memories)` —— **删掉** `rules`
  - `hub.vault.memory_dirs(root: Path) -> list[tuple[str, Path]]` —— `[(origin, dir), …]`,origin 是 `"shared"` 或 host
  - `hub.vault.load_vault(root) -> Vault`、`hub.vault.load_device(root, host) -> DeviceProfile`、`hub.vault.current_host() -> str`
  - `hub.derive.render_memory_index(memories: list[Memory], vault_root: Path) -> str`

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_vault.py` 整个替换:

```python
import pytest
from pathlib import Path
from hub.vault import load_vault, load_device, memory_dirs
from hub.model import SHARED

_MEM = """---
name: {n}
description: {n} 的摘要
metadata:
  type: reference
  scope: [global]
---
正文
"""

def _mk(root: Path, host: str = "box1"):
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / SHARED / "memory").mkdir(parents=True)
    (root / SHARED / "memory" / "s1.md").write_text(_MEM.format(n="s1"), encoding="utf-8")
    (root / host / "claude" / "memory").mkdir(parents=True)
    (root / host / "claude" / "memory" / "m1.md").write_text(_MEM.format(n="m1"), encoding="utf-8")
    (root / host / "device.toml").write_text(
        'class = ["work"]\n'
        'projects = ["xinao"]\n'
        "\n[paths]\nCLAUDE_HOME = \"C:/x/.claude\"\n"
        "\n[sources.claude]\n"
        'memory = ["C:/x/.claude/projects/p/memory"]\n'
        'skills = "C:/x/.claude/skills"\n'
        'plugin_repos = "C:/x/.claude/plugins-dev"\n'
        'settings = "C:/x/.claude/settings.json"\n'
        "\n[sources.codex]\n"
        'skills = "C:/x/.codex/skills"\n'
        'settings = "C:/x/.codex/config.toml"\n'
        'agents = "C:/x/.codex/AGENTS.md"\n',
        encoding="utf-8")
    return root

def test_memory_dirs_covers_shared_and_each_device(tmp_path):
    _mk(tmp_path)
    got = {origin: d.name for origin, d in memory_dirs(tmp_path)}
    assert got == {SHARED: "memory", "box1": "memory"}

def test_load_vault_tags_origin(tmp_path):
    _mk(tmp_path)
    v = load_vault(tmp_path)
    assert {m.name: m.origin for m in v.memories} == {"s1": SHARED, "m1": "box1"}

def test_device_sources_split_by_tool(tmp_path):
    _mk(tmp_path)
    dev = load_device(tmp_path, "box1")
    assert dev.classes == ["work"]
    assert dev.sources["claude"].skills == "C:/x/.claude/skills"
    assert dev.sources["claude"].memory == ["C:/x/.claude/projects/p/memory"]
    assert dev.sources["codex"].agents == "C:/x/.codex/AGENTS.md"
    assert dev.sources["codex"].plugin_repos is None      # Codex 没有自己写的插件

def test_device_without_codex_section(tmp_path):
    _mk(tmp_path)
    (tmp_path / "box1" / "device.toml").write_text(
        'class = []\nprojects = []\n[sources.claude]\nskills = "C:/x/.claude/skills"\n',
        encoding="utf-8")
    dev = load_device(tmp_path, "box1")
    assert "codex" not in dev.sources                     # 没装的工具就是没有，不是错误
```

`tests/hub/test_derive.py` 整个替换:

```python
from pathlib import Path
from hub.derive import render_memory_index
from hub.model import Memory, SHARED

def _m(name, origin, path):
    return Memory(name=name, description=f"{name} 摘要", type="reference",
                  scope=["global"], portable=True, sensitive=False,
                  body="正文\n", path=path, origin=origin)

def test_index_links_point_at_real_paths(tmp_path):
    ms = [_m("s1", SHARED, tmp_path / "shared" / "memory" / "s1.md"),
          _m("m1", "box1", tmp_path / "box1" / "claude" / "memory" / "m1.md")]
    out = render_memory_index(ms, tmp_path)
    assert "[s1](shared/memory/s1.md)" in out
    assert "[m1](box1/claude/memory/m1.md)" in out
    assert "s1 摘要" in out and "m1 摘要" in out
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_vault.py tests/hub/test_derive.py -q`
Expected: FAIL —— `ImportError: cannot import name 'memory_dirs'`

- [ ] **Step 3: 改 `hub/model.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path

SHARED = "shared"           # 共享区，与各设备文件夹同级

@dataclass
class Memory:
    name: str
    description: str
    type: str
    scope: list[str]
    portable: bool
    sensitive: bool
    body: str
    path: Path | None = None
    # 归属 = 金库顶层文件夹名：SHARED 或某台设备的 host
    origin: str | None = None

@dataclass
class ToolSources:
    """一台设备上、某个工具的源路径。缺的项就是本机没有,不是错误。"""
    memory: list[str] = field(default_factory=list)
    skills: str | None = None
    plugin_repos: str | None = None     # 自己写的插件仓所在目录（Claude 的 plugins-dev）
    settings: str | None = None         # claude: settings.json ; codex: config.toml
    agents: str | None = None           # claude: CLAUDE.md ; codex: AGENTS.md

@dataclass
class DeviceProfile:
    host: str
    classes: list[str]
    projects: list[str]
    paths: dict[str, str]
    sources: dict[str, ToolSources] = field(default_factory=dict)   # "claude" / "codex"

@dataclass(frozen=True)
class Target:
    device_classes: frozenset[str]
    project: str | None
    tool: str

@dataclass
class VaultConfig:
    version: int

@dataclass
class Vault:
    root: Path
    config: VaultConfig
    memories: list[Memory]
```

- [ ] **Step 4: 改 `hub/vault.py`**

整个文件替换:

```python
"""金库的读取。

两个区,语义不同:

    vault/
    ├─ vault.toml  SCHEMA.md  MEMORY.md  lint-exempt.txt
    ├─ <host>/          备份区:这台机的原始数据,按工具分
    │   ├─ device.toml
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    └─ shared/          共享区:跨设备/跨工具的精选,按类型分
        └─ memory/ skills/ plugins/ hooks/ chats/

备份区 = "别丢"(换机照它还原);共享区 = "到处都要有"(skill 照它装)。
两台设备各写各的文件夹,永远碰不到同一个文件 → git 合并零冲突。
"""
import socket
import tomllib
from pathlib import Path
from hub.model import Vault, VaultConfig, DeviceProfile, ToolSources, SHARED
from hub.frontmatter import load_memory

def current_host() -> str:
    return socket.gethostname().lower()

def _owner_dirs(root: Path):
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            yield d

def memory_dirs(root: Path) -> list[tuple[str, Path]]:
    """金库里所有存放记忆的目录:[(归属, 目录), …]。

    共享区在 shared/memory/;备份区在 <host>/claude/memory/
    (记忆是 Claude 的著作物;Codex 的原生 memories 是生成态,不收——见 spec §3)。
    """
    out: list[tuple[str, Path]] = []
    shared = root / SHARED / "memory"
    if shared.is_dir():
        out.append((SHARED, shared))
    for owner in _owner_dirs(root):
        if owner.name == SHARED:
            continue
        d = owner / "claude" / "memory"
        if d.is_dir():
            out.append((owner.name, d))
    return out

def load_vault(root: Path) -> Vault:
    cfg_raw = tomllib.loads((root / "vault.toml").read_text(encoding="utf-8"))
    config = VaultConfig(version=int(cfg_raw.get("version", 1)))
    memories = []
    for origin, d in memory_dirs(root):
        for p in sorted(d.glob("*.md")):
            m = load_memory(p)
            m.origin = origin
            memories.append(m)
    return Vault(root=root, config=config, memories=memories)

def _tool_sources(raw: dict) -> ToolSources:
    return ToolSources(
        memory=list(raw.get("memory", [])),
        skills=raw.get("skills"),
        plugin_repos=raw.get("plugin_repos"),
        settings=raw.get("settings"),
        agents=raw.get("agents"),
    )

def load_device(root: Path, host: str) -> DeviceProfile:
    raw = tomllib.loads((root / host / "device.toml").read_text(encoding="utf-8"))
    return DeviceProfile(
        host=host,
        classes=list(raw.get("class", [])),
        projects=list(raw.get("projects", [])),
        paths=dict(raw.get("paths", {})),
        sources={k: _tool_sources(v) for k, v in raw.get("sources", {}).items()},
    )
```

- [ ] **Step 5: 改 `hub/derive.py`**

```python
from pathlib import Path
from hub.model import Memory

def render_memory_index(memories: list[Memory], vault_root: Path) -> str:
    """金库总览索引。链接是相对金库根的真实路径,一眼看得出哪条是共享的、哪条是哪台设备的。

    这是**派生物**,每次重算。C 阶段的 skill 靠它决定读哪几条正文,
    不必把全文塞进上下文(47 条全文 85 KB,索引 7.3 KB)。
    """
    header = "<!-- 自动生成，勿手改：由 hub 从各 memory/*.md 的 frontmatter 派生 -->\n"
    rows = []
    for m in sorted(memories, key=lambda x: (x.origin or "", x.name)):
        rel = Path(m.path).relative_to(vault_root).as_posix() if m.path else f"{m.name}.md"
        rows.append(f"- [{m.name}]({rel}) — {m.description}")
    return header + "\n".join(rows) + "\n"
```

- [ ] **Step 6: 修 `hub/cli.py` 里被改动波及的两处**

`_cmd_collect` 里 `dev.collect_sources` 已不存在 —— 暂时改成从 `dev.sources` 取 Claude 的记忆源(Task 6 会整体重写这个命令):

```python
def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    src = dev.sources.get("claude")
    sources = [Path(s) for s in (src.memory if src else [])]
    collected = collect_memories(sources, vault_root, host)
    print(f"collected {len(collected)} memories: {collected}")
    return 0
```

`_write_index` 里 `render_memory_index` 现在要两个参数:

```python
def _write_index(vault_root: Path, vault) -> None:
    (vault_root / "MEMORY.md").write_text(
        render_memory_index(vault.memories, vault_root), encoding="utf-8", newline="\n")
```

- [ ] **Step 7: 跑全量测试**

Run: `py -3 -m pytest -q`
Expected: 全绿。若 `test_collect.py` / `test_cli.py` 里还有引用旧结构(`<host>/memory/`、`collect_sources`、`Vault.rules`)的测试,把它们的金库 fixture 改成 `<host>/claude/memory/` 与新版 `device.toml`。

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "refactor(hub): 金库改成两区——备份区(按工具)+ 共享区(按类型)

备份区 = 别丢(换机照它还原);共享区 = 到处都要有(skill 照它装)。
device.toml 的源路径按工具分;删掉 targets/collect_sources/rules(落地层的遗物)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: frontmatter 认块状列表,且解析失败不许静默跳过

`project_ai_hub_shared_data_layer` 那条记忆曾经**悄无声息地漏掉**——它的 frontmatter 用了 YAML 块状列表(`scope:` 换行后 `  - global`),解析器不认,抛 `FrontmatterError`,而 `collect` 把异常吞了。

两头都要修:**解析器认块状列表**(这是标准 YAML,Claude 自己写记忆时就会用;不认它,严格化之后每天都会卡),**调用方不许吞异常**(Task 6)。

**Files:**
- Modify: `hub/frontmatter.py`
- Test: `tests/hub/test_frontmatter.py`

**Interfaces:**
- Consumes: 无
- Produces: `parse_frontmatter(text) -> tuple[dict, str]` 与 `load_memory(path) -> Memory` 签名不变,行为扩展

- [ ] **Step 1: 追加失败的测试**

追加到 `tests/hub/test_frontmatter.py`:

```python
import pytest
from hub.frontmatter import parse_frontmatter, load_memory, FrontmatterError

_BLOCK = """---
name: x
description: 摘要
metadata:
  type: project
  scope:
    - global
  sensitive: false
---
正文
"""

def test_block_list_is_parsed(tmp_path):
    meta, body = parse_frontmatter(_BLOCK)
    assert meta["metadata"]["scope"] == ["global"]
    assert body.strip() == "正文"

def test_block_list_with_multiple_items():
    text = _BLOCK.replace("    - global\n", "    - tool:claude\n    - device:work\n")
    meta, _ = parse_frontmatter(text)
    assert meta["metadata"]["scope"] == ["tool:claude", "device:work"]

def test_top_level_block_list():
    text = "---\nname: x\ndescription: d\ntags:\n  - a\n  - b\n---\n正文\n"
    meta, _ = parse_frontmatter(text)
    assert meta["tags"] == ["a", "b"]

def test_load_memory_roundtrips_block_list(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(_BLOCK, encoding="utf-8")
    m = load_memory(p)
    assert m.scope == ["global"] and m.type == "project"

def test_genuinely_broken_frontmatter_still_raises():
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nname x\n---\n正文\n")     # 没有冒号
    with pytest.raises(FrontmatterError):
        parse_frontmatter("没有 frontmatter\n")
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_frontmatter.py -q`
Expected: FAIL —— 块状列表那几条报 `FrontmatterError: 无法解析行(子集外): '    - global'`

- [ ] **Step 3: 改 `parse_frontmatter` 支持块状列表**

把 `hub/frontmatter.py` 里的 `parse_frontmatter` 换成:

```python
def parse_frontmatter(text: str) -> tuple[dict, str]:
    """YAML 的一个受控子集:标量、一层嵌套、行内列表 [a, b]、块状列表(- a)。

    块状列表必须支持——Claude 自己写记忆时用的就是这个形式。不认它,
    collect 严格化之后每天都会卡在自己的记忆上。
    """
    if not text.startswith("---"):
        raise FrontmatterError("缺少 frontmatter 起始 ---")
    lines = text.splitlines()
    if lines[0].strip() != "---":
        raise FrontmatterError("首行必须是 ---")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise FrontmatterError("缺少 frontmatter 结束 ---")

    meta: dict = {}
    cur: dict = meta          # 当前正在填的表(meta 或某个一层嵌套表)
    pending: list | None = None   # 正在累积的块状列表
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        stripped = ln.strip()
        indent = len(ln) - len(ln.lstrip(" "))

        if stripped.startswith("- "):
            if pending is None:
                raise FrontmatterError(f"块状列表没有对应的键: {ln!r}")
            pending.append(stripped[2:].strip())
            continue
        pending = None        # 非列表行 → 上一个块状列表到此为止

        if ":" not in ln:
            raise FrontmatterError(f"无法解析行(子集外): {ln!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()

        if indent == 0:
            if val == "":
                # 可能是一层嵌套表，也可能是块状列表的键——先按列表挂着，
                # 遇到缩进的 "key: value" 再改判成表。
                lst: list = []
                meta[key] = lst
                pending = lst
                cur = meta
                _last_key, _last_owner = key, meta
            else:
                meta[key] = _coerce(val)
                cur = meta
                pending = None
        elif indent >= 2:
            if cur is meta:
                # 上一行是 "key:" 且被暂挂成列表 —— 现在证明它其实是个表
                if not (isinstance(meta.get(_last_key), list) and meta[_last_key] == []):
                    raise FrontmatterError(f"缩进/结构越界: {ln!r}")
                meta[_last_key] = {}
                cur = meta[_last_key]
            if val == "":
                lst = []
                cur[key] = lst
                pending = lst
            else:
                cur[key] = _coerce(val)
        else:
            raise FrontmatterError(f"缩进/结构越界: {ln!r}")

    body = "\n".join(lines[end + 1:])
    if body and not body.endswith("\n"):
        body += "\n"
    return meta, body
```

> 注:`_last_key` / `_last_owner` 要在循环前初始化为 `None`。若实现时觉得这个"先挂列表再改判"的状态机绕,可以改成**先做一次预扫描**判断每个空值键的下一行是 `- ` 还是 `key:`——只要测试全绿即可,这里给的是一种可行实现,不是唯一实现。

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_frontmatter.py -q`
Expected: 全绿(含原有测试)

- [ ] **Step 5: 用真实记忆验一遍(回归)**

Run:
```bash
py -3 -c "
from pathlib import Path
from hub.frontmatter import load_memory
d = Path(r'C:/Users/huawei/hub-vault/2025-bg-016/memory')
bad = []
for p in sorted(d.glob('*.md')):
    try: load_memory(p)
    except Exception as e: bad.append((p.name, e))
print('解析失败:', bad or '无')
"
```
Expected: `解析失败: 无` —— 47 条真实记忆全部解析得动

- [ ] **Step 6: 提交**

```bash
git add hub/frontmatter.py tests/hub/test_frontmatter.py
git commit -m "fix(hub): frontmatter 认 YAML 块状列表

project_ai_hub_shared_data_layer 曾因块状列表解析失败被 collect 静默跳过。
块状列表是 Claude 自己写记忆时的常用形式,必须认。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: guard —— 硬闸

密钥防线不能靠"扫出来",要靠**把用户自己的约定变成机器强制执行的规则**:私密文件统一放 `~/.claude/secrets/`,提取器**永不碰那个目录**。

**Files:**
- Create: `hub/guard.py`
- Test: `tests/hub/test_guard.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class SecretPathError(RuntimeError)`
  - `hub.guard.DENIED_NAMES: frozenset[str]` —— `{"secrets", "auth.json", ".env"}`
  - `hub.guard.check_source(path: Path) -> None` —— 命中就抛 `SecretPathError`
  - `hub.guard.is_denied(path: Path) -> bool`

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_guard.py`:

```python
import pytest
from pathlib import Path
from hub.guard import check_source, is_denied, SecretPathError

def test_secrets_dir_is_denied():
    assert is_denied(Path("C:/Users/x/.claude/secrets"))
    assert is_denied(Path("C:/Users/x/.claude/secrets/oss.md"))   # 目录下的任何文件

def test_auth_json_is_denied():
    assert is_denied(Path("C:/Users/x/.codex/auth.json"))

def test_dotenv_is_denied():
    assert is_denied(Path("C:/proj/.env"))

def test_normal_paths_pass():
    assert not is_denied(Path("C:/Users/x/.claude/skills"))
    assert not is_denied(Path("C:/Users/x/.claude/projects/p/memory"))

def test_check_source_raises_with_the_path_named():
    with pytest.raises(SecretPathError, match="secrets"):
        check_source(Path("C:/Users/x/.claude/secrets"))

def test_check_source_is_silent_on_normal_paths():
    check_source(Path("C:/Users/x/.claude/skills"))     # 不抛就是通过

def test_case_insensitive():
    assert is_denied(Path("C:/Users/x/.claude/Secrets/a.md"))
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_guard.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.guard'`

- [ ] **Step 3: 实现 `hub/guard.py`**

```python
"""硬闸:提取器永不读取的路径。

用户的全局约定是"私密文件统一放 ~/.claude/secrets/"。这条约定本身就是最好的
硬闸——只要提取器永不碰那个目录,而记忆/skill 里只留指针,密钥就物理上出不去。

secrets/ 连加密了也不进金库:它是**全部密钥的单一集合**,整包搬到 NAS 等于把所有
鸡蛋装进一个篮子,主密钥一泄就是一次性全崩。它换机时另有通道(ai-cli-migrate 点对点搬)。
"""
from pathlib import Path

class SecretPathError(RuntimeError):
    pass

DENIED_NAMES = frozenset({"secrets", "auth.json", ".env"})

def is_denied(path: Path) -> bool:
    """路径自身或它的任一祖先命中黑名单。"""
    p = Path(path)
    return any(part.lower() in DENIED_NAMES for part in p.parts)

def check_source(path: Path) -> None:
    if is_denied(path):
        raise SecretPathError(
            f"硬闸:拒绝读取 {path} —— 命中密钥黑名单 {sorted(DENIED_NAMES)}。"
            f"私密内容留在 ~/.claude/secrets/,记忆/skill 里只写指针。")
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_guard.py -q`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add hub/guard.py tests/hub/test_guard.py
git commit -m "feat(hub): 硬闸 —— secrets/ 与 auth.json 永不读取

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: collect/memory.py —— 记忆镜像

`collect` 对 `<本机>/claude/memory/` 做**镜像同步**:本机源里有的写进去,本机源里没了的**从金库删掉**。`shared/` 与别的设备的文件夹**碰都不碰**。

**Files:**
- Delete: `hub/collect.py`(单文件)
- Create: `hub/collect/__init__.py`, `hub/collect/memory.py`
- Test: `tests/hub/test_collect.py`(整个替换)

**Interfaces:**
- Consumes: `hub.writer.Writer`、`hub.guard.check_source`、`hub.frontmatter.load_memory/dump_memory/FrontmatterError`、`hub.vault.memory_dirs`、`hub.model.SHARED`
- Produces:
  - `hub.collect.memory.MemoryResult(written: list[str], deleted: list[str], skipped_sensitive: list[str])`
  - `hub.collect.memory.plan_memory(source_dirs: list[Path], vault_root: Path, host: str) -> MemoryResult` —— **只算不写**,`deleted` 是"将要删的"
  - `hub.collect.memory.collect_memory(source_dirs, vault_root, host, w: Writer) -> MemoryResult` —— 真写

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_collect.py` 整个替换:

```python
import pytest
from pathlib import Path
from hub.collect.memory import plan_memory, collect_memory
from hub.frontmatter import FrontmatterError
from hub.guard import SecretPathError
from hub.writer import Writer
from hub.model import SHARED

def _mem(d: Path, name: str, sensitive: bool = False, body: str = "正文\n"):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} 摘要\nmetadata:\n"
        f"  type: reference\n  scope: [global]\n"
        f"  sensitive: {'true' if sensitive else 'false'}\n---\n{body}",
        encoding="utf-8")

def _vault(tmp_path: Path, host: str = "box1") -> Path:
    (tmp_path / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / host / "claude" / "memory").mkdir(parents=True)
    (tmp_path / SHARED / "memory").mkdir(parents=True)
    return tmp_path

def test_collects_into_this_devices_claude_memory(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "a")
    collect_memory([src], v, "box1", Writer())
    assert (v / "box1" / "claude" / "memory" / "a.md").exists()

def test_sensitive_is_never_collected(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "secret_one", sensitive=True)
    r = collect_memory([src], v, "box1", Writer())
    assert not (v / "box1" / "claude" / "memory" / "secret_one.md").exists()
    assert r.skipped_sensitive == ["secret_one"]

def test_mirror_deletes_what_source_no_longer_has(tmp_path):
    v = _vault(tmp_path)
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    src = tmp_path / "src"
    _mem(src, "a")
    r = collect_memory([src], v, "box1", Writer())
    assert r.deleted == ["gone"]
    assert not stale.exists()

def test_never_touches_shared_or_other_devices(tmp_path):
    v = _vault(tmp_path)
    (v / "box2" / "claude" / "memory").mkdir(parents=True)
    other = v / "box2" / "claude" / "memory" / "theirs.md"
    other.write_text("---\nname: theirs\ndescription: d\n---\n别人的\n", encoding="utf-8")
    sh = v / SHARED / "memory" / "pooled.md"
    sh.write_text("---\nname: pooled\ndescription: d\n---\n公共的\n", encoding="utf-8")
    before = (other.read_bytes(), sh.read_bytes())
    src = tmp_path / "src"
    _mem(src, "a")
    collect_memory([src], v, "box1", Writer())
    assert (other.read_bytes(), sh.read_bytes()) == before   # 逐字节不变

def test_broken_frontmatter_raises_not_silently_skipped(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.md").write_text("没有 frontmatter\n", encoding="utf-8")
    with pytest.raises(FrontmatterError, match="bad.md"):
        collect_memory([src], v, "box1", Writer())

def test_secrets_source_is_refused(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(SecretPathError):
        collect_memory([tmp_path / ".claude" / "secrets"], v, "box1", Writer())

def test_missing_source_is_skipped_not_an_error(tmp_path):
    v = _vault(tmp_path)
    r = collect_memory([tmp_path / "nope"], v, "box1", Writer())
    assert r.written == []                    # 工具没装 = 正常，不是错误

def test_dry_run_writes_nothing(tmp_path):
    v = _vault(tmp_path)
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    src = tmp_path / "src"
    _mem(src, "a")
    r = collect_memory([src], v, "box1", Writer(dry_run=True))
    assert r.written == ["a"] and r.deleted == ["gone"]     # 报告说会做什么
    assert not (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert stale.exists()                                   # 但一个字节都没动

def test_plan_matches_what_collect_would_do(tmp_path):
    v = _vault(tmp_path)
    src = tmp_path / "src"
    _mem(src, "a")
    p = plan_memory([src], v, "box1")
    r = collect_memory([src], v, "box1", Writer())
    assert (p.written, p.deleted) == (r.written, r.deleted)
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_collect.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.collect.memory'`

- [ ] **Step 3: 把 `hub/collect.py` 换成包**

```bash
git rm hub/collect.py
mkdir hub/collect
```

`hub/collect/__init__.py`(先留空,Task 11 填 `run_all`):

```python
"""提取器:把本机各工具的家当收进金库的备份区。

铁律:只写 <本机>/,不碰 shared/,不碰别的设备,不写任何工具的地盘。
"""
```

`hub/collect/memory.py`:

```python
"""记忆流水线:镜像同步。

本机源里有的 → 写进 <host>/claude/memory/
本机源里没了的 → 从金库删掉(先列出来给人确认)

只镜像**本机自己那一块**。shared/ 与别的设备的文件夹碰都不碰——
本机的 collect 凭什么删别人写的东西。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.frontmatter import load_memory, dump_memory, FrontmatterError
from hub.guard import check_source
from hub.writer import Writer

@dataclass
class MemoryResult:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped_sensitive: list[str] = field(default_factory=list)

def _home(vault_root: Path, host: str) -> Path:
    return Path(vault_root) / host / "claude" / "memory"

def _scan(source_dirs: list[Path]) -> tuple[list, list[str]]:
    """读源目录里的全部记忆。解析失败 → 抛错,**绝不静默跳过**。"""
    mems, sensitive = [], []
    for d in source_dirs:
        d = Path(d)
        check_source(d)                     # 硬闸
        if not d.is_dir():
            continue                        # 工具没装 = 正常
        for p in sorted(d.glob("*.md")):
            if p.name in ("MEMORY.md", "memory-index.md"):
                continue                    # 派生索引，不是记忆
            try:
                m = load_memory(p)
            except FrontmatterError as e:
                raise FrontmatterError(f"{p}: {e}") from e
            if m.sensitive:
                sensitive.append(m.name)    # 硬闸 3：sensitive 不入库
                continue
            mems.append(m)
    return mems, sensitive

def plan_memory(source_dirs: list[Path], vault_root: Path, host: str) -> MemoryResult:
    """只算不写:告诉你这次会写哪些、会删哪些。"""
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    have = {p.stem for p in home.glob("*.md")} if home.is_dir() else set()
    names = {m.name for m in mems}
    return MemoryResult(
        written=sorted(names),
        deleted=sorted(have - names),
        skipped_sensitive=sorted(sensitive),
    )

def collect_memory(source_dirs: list[Path], vault_root: Path, host: str,
                   w: Writer) -> MemoryResult:
    mems, sensitive = _scan(source_dirs)
    home = _home(vault_root, host)
    have = {p.stem for p in home.glob("*.md")} if home.is_dir() else set()
    names = {m.name for m in mems}
    for m in mems:
        w.write_text(home / f"{m.name}.md", dump_memory(m))
    for gone in sorted(have - names):
        w.unlink(home / f"{gone}.md")
    return MemoryResult(written=sorted(names), deleted=sorted(have - names),
                        skipped_sensitive=sorted(sensitive))
```

- [ ] **Step 4: 修 `hub/cli.py` 的 import**

```python
from hub.collect.memory import collect_memory
from hub.writer import Writer
```
并把 `_cmd_collect` 里的 `collect_memories(...)` 换成:
```python
    r = collect_memory(sources, vault_root, host, Writer())
    print(f"记忆: 写 {len(r.written)} 删 {len(r.deleted)}")
```

- [ ] **Step 5: 跑全量**

Run: `py -3 -m pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat(hub): 记忆流水线改成镜像 —— 本机删了金库也删,别人的碰都不碰

frontmatter 解析失败改为抛错,不再静默跳过(那正是 project_ai_hub_shared_data_layer 漏掉的原因)。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: snapshot.py —— git archive 快照

**必须用 `git archive HEAD`,不能用 `cp -r`。** 两个理由,都是硬的:

1. **只含 git 跟踪的文件**——`.git`、`node_modules`、构建产物、`.env` 自动出不去。实测六个仓的快照加起来 ~1 MB(原样拷是 22 MB)。
2. **不产生嵌套仓**——把带 `.git` 的目录原样拷进另一个 git 仓,外层会把它记成 gitlink **空壳**,新机 clone 下来是**空目录**。你以为备份了,其实没有。

**Files:**
- Create: `hub/snapshot.py`
- Test: `tests/hub/test_snapshot.py`

**Interfaces:**
- Consumes: `hub.writer.Writer`
- Produces:
  - `hub.snapshot.RepoMeta(name: str, remote: str | None, sha: str, dirty: bool)`
  - `hub.snapshot.repo_meta(repo: Path) -> RepoMeta`
  - `hub.snapshot.snapshot_repo(repo: Path, dest: Path, w: Writer) -> RepoMeta` —— 全量重写 dest
  - `hub.snapshot.is_git_repo(path: Path) -> bool`

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_snapshot.py`:

```python
import subprocess
from pathlib import Path
from hub.snapshot import snapshot_repo, repo_meta, is_git_repo
from hub.writer import Writer

def _git(repo: Path, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

def _mk_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "myplugin"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
    (repo / ".gitignore").write_text("node_modules/\nbuild/\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "huge.js").write_text("x" * 1000, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", "https://github.com/x/myplugin.git")
    return repo

def test_snapshot_excludes_git_and_ignored(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer())
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"
    assert not (dest / ".git").exists()              # 不产生嵌套仓（否则是 gitlink 空壳）
    assert not (dest / "node_modules").exists()      # gitignored 出不去

def test_snapshot_is_full_rewrite(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    dest.mkdir(parents=True)
    (dest / "stale.txt").write_text("上一轮的残留", encoding="utf-8")
    snapshot_repo(repo, dest, Writer())
    assert not (dest / "stale.txt").exists()

def test_repo_meta_reports_remote_sha_clean(tmp_path):
    repo = _mk_repo(tmp_path)
    m = repo_meta(repo)
    assert m.name == "myplugin"
    assert m.remote == "https://github.com/x/myplugin.git"
    assert len(m.sha) == 40
    assert m.dirty is False

def test_dirty_worktree_is_flagged(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "src" / "a.py").write_text("print(2)\n", encoding="utf-8")   # 改了没提交
    assert repo_meta(repo).dirty is True

def test_snapshot_only_contains_committed_content(tmp_path):
    repo = _mk_repo(tmp_path)
    (repo / "src" / "a.py").write_text("print(2)\n", encoding="utf-8")   # 改了没提交
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer())
    # git archive HEAD 只打包已提交的东西 —— 这正是要 dirty 警告的原因
    assert (dest / "src" / "a.py").read_text(encoding="utf-8") == "print(1)\n"

def test_dry_run_snapshots_nothing(tmp_path):
    repo = _mk_repo(tmp_path)
    dest = tmp_path / "vault" / "myplugin"
    snapshot_repo(repo, dest, Writer(dry_run=True))
    assert not dest.exists()

def test_is_git_repo(tmp_path):
    repo = _mk_repo(tmp_path)
    assert is_git_repo(repo)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not is_git_repo(plain)

def test_repo_without_remote(tmp_path):
    repo = tmp_path / "local_only"
    repo.mkdir()
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    assert repo_meta(repo).remote is None      # 没 remote 不是错误
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_snapshot.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.snapshot'`

- [ ] **Step 3: 实现 `hub/snapshot.py`**

```python
"""仓库快照:git archive HEAD → 一棵干净的普通目录树。

**不能用 cp -r**:
1. 把带 .git 的目录拷进另一个 git 仓,外层会把它记成 gitlink 空壳,
   新机 clone 下来是空目录——你以为备份了,其实没有。
2. cp -r 会把 node_modules / 构建产物 / .env 一起拖进来(实测 1MB → 22MB)。

git archive 只打包 git 跟踪的文件,两个问题一起解决。
"""
import io
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

@dataclass
class RepoMeta:
    name: str
    remote: str | None
    sha: str
    dirty: bool          # 工作区有未提交改动 → 快照里没有它们

def _git(repo: Path, *args: str, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}))

def is_git_repo(path: Path) -> bool:
    return (Path(path) / ".git").exists()

def repo_meta(repo: Path) -> RepoMeta:
    repo = Path(repo)
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    dirty = bool(_git(repo, "status", "--porcelain").stdout.strip())
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8")
    remote = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    return RepoMeta(name=repo.name, remote=remote, sha=sha, dirty=dirty)

def snapshot_repo(repo: Path, dest: Path, w: Writer) -> RepoMeta:
    """把 repo 的 HEAD 快照全量重写到 dest。返回仓库元数据。"""
    repo, dest = Path(repo), Path(dest)
    meta = repo_meta(repo)
    w.rmtree(dest)
    if w.dry_run:
        print(f"  [dry-run] 快照 {repo} → {dest}  (sha {meta.sha[:8]}"
              f"{', 有未提交改动' if meta.dirty else ''})")
        return meta
    dest.mkdir(parents=True, exist_ok=True)
    tar = _git(repo, "archive", "--format=tar", "HEAD", binary=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        tf.extractall(dest, filter="data")
    return meta
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_snapshot.py -q`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add hub/snapshot.py tests/hub/test_snapshot.py
git commit -m "feat(hub): git archive 快照 —— 不产生嵌套仓,不拖 node_modules

cp -r 一个带 .git 的目录进金库 = gitlink 空壳,新机 clone 下来是空的。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: collect/skills.py —— 散装 skill 快照

`~/.claude/skills/` 和 `~/.codex/skills/` 下的散装 skill 是**无主的**(很多没有 git 仓),丢了就真找不回来。整目录拷,全量重写。

**Files:**
- Create: `hub/collect/skills.py`
- Test: `tests/hub/test_collect_skills.py`

**Interfaces:**
- Consumes: `hub.writer.Writer`、`hub.guard.check_source`、`hub.snapshot.is_git_repo/snapshot_repo`
- Produces: `hub.collect.skills.collect_skills(src: Path | None, dest: Path, w: Writer) -> list[str]` —— 返回收到的 skill 名字

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_collect_skills.py`:

```python
import subprocess
from pathlib import Path
from hub.collect.skills import collect_skills
from hub.writer import Writer

def _skill(root: Path, name: str, body: str = "# skill\n"):
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d

def test_copies_each_skill_dir(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    _skill(src, "beta")
    dest = tmp_path / "vault" / "skills"
    got = collect_skills(src, dest, Writer())
    assert sorted(got) == ["alpha", "beta"]
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "# skill\n"

def test_full_rewrite_drops_removed_skills(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    dest = tmp_path / "vault" / "skills"
    _skill(dest, "deleted_last_week")          # 上一轮收的，本机已经删了
    collect_skills(src, dest, Writer())
    assert (dest / "alpha").exists()
    assert not (dest / "deleted_last_week").exists()

def test_skill_with_own_git_repo_is_snapshotted_not_copied(tmp_path):
    src = tmp_path / "skills"
    d = _skill(src, "gamma")
    (d / "junk").mkdir()
    (d / "junk" / "big.bin").write_text("x" * 500, encoding="utf-8")
    (d / ".gitignore").write_text("junk/\n", encoding="utf-8")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "i"]):
        subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
    dest = tmp_path / "vault" / "skills"
    collect_skills(src, dest, Writer())
    assert (dest / "gamma" / "SKILL.md").exists()
    assert not (dest / "gamma" / ".git").exists()    # 不留嵌套仓
    assert not (dest / "gamma" / "junk").exists()    # gitignored 出不去

def test_missing_source_is_not_an_error(tmp_path):
    assert collect_skills(None, tmp_path / "vault" / "skills", Writer()) == []
    assert collect_skills(tmp_path / "nope", tmp_path / "vault" / "skills", Writer()) == []

def test_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    dest = tmp_path / "vault" / "skills"
    got = collect_skills(src, dest, Writer(dry_run=True))
    assert got == ["alpha"]
    assert not dest.exists()

def test_loose_files_at_skills_root_are_ignored(tmp_path):
    src = tmp_path / "skills"
    src.mkdir()
    (src / "README.md").write_text("说明", encoding="utf-8")
    _skill(src, "alpha")
    assert collect_skills(src, tmp_path / "v", Writer()) == ["alpha"]   # 只收目录
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_collect_skills.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.collect.skills'`

- [ ] **Step 3: 实现 `hub/collect/skills.py`**

```python
"""散装 skill 流水线:整目录快照,全量重写。

~/.claude/skills/ 和 ~/.codex/skills/ 下的 skill 很多没有 git 仓,是**唯一副本**。
带仓的走 git archive(避免嵌套仓变空壳),不带仓的直接拷。
"""
from pathlib import Path
from hub.guard import check_source
from hub.snapshot import is_git_repo, snapshot_repo
from hub.writer import Writer

def collect_skills(src: Path | None, dest: Path, w: Writer) -> list[str]:
    if src is None:
        return []
    src, dest = Path(src), Path(dest)
    check_source(src)
    if not src.is_dir():
        return []                       # 工具没装 = 正常
    w.rmtree(dest)                      # 全量重写:本机删掉的 skill，金库也不该留
    names = []
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        if is_git_repo(d):
            snapshot_repo(d, dest / d.name, w)
        else:
            w.copy_tree(d, dest / d.name)
        names.append(d.name)
    return names
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_collect_skills.py -q`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add hub/collect/skills.py tests/hub/test_collect_skills.py
git commit -m "feat(hub): 散装 skill 流水线 —— 整目录快照,全量重写

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: collect/decl.py —— 插件源码快照 + 声明抄写

**按"是不是你的产出"分,不按工具分:**

- **你写的插件**(`~/.claude/plugins-dev/` 六个仓)→ **源码快照**。唯一副本风险:GitHub 没了就真没了。
- **第三方插件**(superpowers / gmail / github / clangd-lsp,两边共 65 MB)→ **抄声明**。别人的代码,市场在就能重装;里面是 LSP 二进制,换台 Mac 就是废的。

Codex 那三个插件恰好**全是第三方**,所以它只有 `plugins.toml` 没有源码目录——这是**结果**,不是双标。

**hooks 也在这条流水线里抄**(见"与 spec 的偏离"):读的本来就是同两个文件。

**Files:**
- Create: `hub/tomlout.py`, `hub/collect/decl.py`
- Test: `tests/hub/test_tomlout.py`, `tests/hub/test_collect_decl.py`

**Interfaces:**
- Consumes: `hub.writer.Writer`、`hub.snapshot.snapshot_repo/is_git_repo/RepoMeta`、`hub.guard.check_source`
- Produces:
  - `hub.tomlout.dump_toml(tables: list[tuple[str, dict]]) -> str`
  - `hub.collect.decl.DeclResult(repos: list[RepoMeta], dirty: list[str], enabled: dict, marketplaces: dict, hooks: dict)`
  - `hub.collect.decl.collect_claude_decl(plugin_repos: Path | None, settings: Path | None, dest_dir: Path, w: Writer) -> DeclResult`
  - `hub.collect.decl.collect_codex_decl(config: Path | None, dest_dir: Path, w: Writer) -> DeclResult`

- [ ] **Step 1: 写 tomlout 的失败测试**

`tests/hub/test_tomlout.py`:

```python
import tomllib
from hub.tomlout import dump_toml

def test_roundtrips_through_tomllib():
    out = dump_toml([
        ("claude.repos.cjt", {"remote": "https://github.com/x/cjt.git",
                              "sha": "abc123", "dirty": False}),
        ("claude.enabled", {"superpowers@claude-plugins-official": True,
                            "compact-plus@xu-local": False}),
    ])
    back = tomllib.loads(out)
    assert back["claude"]["repos"]["cjt"]["dirty"] is False
    assert back["claude"]["enabled"]["superpowers@claude-plugins-official"] is True
    assert back["claude"]["enabled"]["compact-plus@xu-local"] is False

def test_keys_needing_quotes_are_quoted():
    out = dump_toml([("t", {"a@b": True})])
    assert '"a@b" = true' in out
    assert tomllib.loads(out)["t"]["a@b"] is True

def test_windows_paths_are_escaped():
    out = dump_toml([("t", {"path": "C:\\Users\\x\\.claude"})])
    assert tomllib.loads(out)["t"]["path"] == "C:\\Users\\x\\.claude"

def test_empty_table_still_emits_header():
    assert "[t]" in dump_toml([("t", {})])
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_tomlout.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.tomlout'`

- [ ] **Step 3: 实现 `hub/tomlout.py`**

```python
"""极简 TOML 写出器。stdlib 只有 tomllib(读),没有写。

只需支持 str / bool / int —— 声明清单里就这几种。
"""
import re

_BARE = re.compile(r"[A-Za-z0-9_-]+")

def _key(k: str) -> str:
    if _BARE.fullmatch(k):
        return k
    return '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'

def _val(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

def dump_toml(tables: list[tuple[str, dict]]) -> str:
    """tables: [(表名, {键: 值}), …]。表名可以带点(如 "claude.repos.cjt")。"""
    out = ["# 由 hub 生成，勿手改\n"]
    for name, rows in tables:
        out.append(f"[{name}]")
        for k, v in rows.items():
            out.append(f"{_key(k)} = {_val(v)}")
        out.append("")
    return "\n".join(out)
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_tomlout.py -q`
Expected: 4 passed

- [ ] **Step 5: 写 decl 的失败测试**

`tests/hub/test_collect_decl.py`:

```python
import json
import subprocess
import tomllib
from pathlib import Path
from hub.collect.decl import collect_claude_decl, collect_codex_decl
from hub.writer import Writer

def _mk_repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    (repo / "plugin.md").write_text("# " + name, encoding="utf-8")
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "i"]):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://github.com/x/{name}.git"],
                   cwd=repo, check=True, capture_output=True)
    return repo

_SETTINGS = {
    "enabledPlugins": {"superpowers@claude-plugins-official": True,
                       "cjt@cjt": True,
                       "compact-plus@xu-local": False},
    "extraKnownMarketplaces": {
        "xu-local": {"source": {"source": "directory", "path": "C:\\x\\plugins-dev"}}},
}

def test_own_plugins_are_snapshotted(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    _mk_repo(devdir, "true-north")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    r = collect_claude_decl(devdir, settings, dest, Writer())
    assert {m.name for m in r.repos} == {"cjt", "true-north"}
    assert (dest / "plugins" / "cjt" / "plugin.md").exists()
    assert not (dest / "plugins" / "cjt" / ".git").exists()

def test_manifest_records_remote_sha_and_enabled(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(devdir, settings, dest, Writer())
    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert man["repos"]["cjt"]["remote"] == "https://github.com/x/cjt.git"
    assert len(man["repos"]["cjt"]["sha"]) == 40
    assert man["enabled"]["superpowers@claude-plugins-official"] is True
    assert man["enabled"]["compact-plus@xu-local"] is False    # 禁用状态也要记
    assert man["marketplaces"]["xu-local"] == "directory:C:\\x\\plugins-dev"

def test_dirty_repo_is_reported(tmp_path):
    devdir = tmp_path / "plugins-dev"
    repo = _mk_repo(devdir, "cjt")
    (repo / "plugin.md").write_text("改了没提交", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    r = collect_claude_decl(devdir, settings, tmp_path / "v", Writer())
    assert r.dirty == ["cjt"]      # 快照里没有未提交的改动 —— 必须警告

def test_non_repo_dirs_under_plugins_dev_are_skipped(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    (devdir / "docs").mkdir()                       # 没有 .git，不是插件仓
    (devdir / "docs" / "note.md").write_text("笔记", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    r = collect_claude_decl(devdir, settings, tmp_path / "v", Writer())
    assert {m.name for m in r.repos} == {"cjt"}

_CODEX_CFG = """
[plugins."gmail@openai-curated"]
enabled = true

[plugins."superpowers@superpowers-dev"]
enabled = true

[marketplaces.superpowers-dev]
source_type = "git"
source = "https://github.com/obra/superpowers.git"
last_revision = "d884ae0"
"""

def test_codex_decl_copies_declarations_only(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(_CODEX_CFG, encoding="utf-8")
    dest = tmp_path / "vault" / "codex"
    r = collect_codex_decl(cfg, dest, Writer())
    man = tomllib.loads((dest / "plugins.toml").read_text(encoding="utf-8"))
    assert man["enabled"]["gmail@openai-curated"] is True
    assert man["marketplaces"]["superpowers-dev"] == "git:https://github.com/obra/superpowers.git"
    assert r.repos == []            # Codex 本机没有"自己写的"插件 —— 结果如此，不是双标

def test_missing_settings_is_not_an_error(tmp_path):
    r = collect_claude_decl(None, None, tmp_path / "v", Writer())
    assert r.repos == [] and r.enabled == {}

def test_dry_run_writes_nothing(tmp_path):
    devdir = tmp_path / "plugins-dev"
    _mk_repo(devdir, "cjt")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(_SETTINGS), encoding="utf-8")
    dest = tmp_path / "vault" / "claude"
    collect_claude_decl(devdir, settings, dest, Writer(dry_run=True))
    assert not dest.exists()
```

- [ ] **Step 6: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_collect_decl.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.collect.decl'`

- [ ] **Step 7: 实现 `hub/collect/decl.py`**

```python
"""声明流水线:自己写的插件拷源码,第三方插件抄声明。

按"是不是你的产出"分,不按工具分:

- 你写的(plugins-dev 那几个仓)→ 源码快照。GitHub 没了就真没了,这是唯一副本风险。
- 第三方(superpowers/gmail/github/clangd-lsp)→ 抄声明。别人的代码,市场在就能重装;
  两边缓存共 65 MB,里面是 LSP 二进制,换台 Mac 就是废的,而且每次更新都在 git 里堆 delta。

hooks 也在这里抄——它读的本来就是同两个文件(settings.json / config.toml)。
Claude 目前没有用户级 hook(全在插件里),Codex 也没有,所以通常是空的。
"""
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from hub.guard import check_source
from hub.snapshot import RepoMeta, is_git_repo, snapshot_repo
from hub.tomlout import dump_toml
from hub.writer import Writer

@dataclass
class DeclResult:
    repos: list[RepoMeta] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)      # 有未提交改动的仓 → 快照里没有那些改动
    enabled: dict = field(default_factory=dict)
    marketplaces: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)

def _write_manifest(dest_dir: Path, r: DeclResult, w: Writer) -> None:
    tables: list[tuple[str, dict]] = []
    for m in r.repos:
        tables.append((f"repos.{m.name}",
                       {"remote": m.remote or "", "sha": m.sha, "dirty": m.dirty}))
    tables.append(("enabled", r.enabled))
    tables.append(("marketplaces", r.marketplaces))
    if r.hooks:
        tables.append(("hooks", r.hooks))
    w.write_text(Path(dest_dir) / "plugins.toml", dump_toml(tables))

def collect_claude_decl(plugin_repos: Path | None, settings: Path | None,
                        dest_dir: Path, w: Writer) -> DeclResult:
    r = DeclResult()
    dest_dir = Path(dest_dir)

    if plugin_repos is not None:
        plugin_repos = Path(plugin_repos)
        check_source(plugin_repos)
        if plugin_repos.is_dir():
            for d in sorted(p for p in plugin_repos.iterdir() if p.is_dir()):
                if not is_git_repo(d):
                    continue                    # 不是插件仓（如 plugins-dev/docs）
                meta = snapshot_repo(d, dest_dir / "plugins" / d.name, w)
                r.repos.append(meta)
                if meta.dirty:
                    r.dirty.append(meta.name)

    if settings is not None:
        settings = Path(settings)
        check_source(settings)
        if settings.is_file():
            raw = json.loads(settings.read_text(encoding="utf-8"))
            r.enabled = dict(raw.get("enabledPlugins", {}))
            for name, spec in (raw.get("extraKnownMarketplaces") or {}).items():
                s = (spec or {}).get("source", {})
                r.marketplaces[name] = f"{s.get('source', '?')}:{s.get('path') or s.get('url', '')}"
            r.hooks = raw.get("hooks") or {}

    _write_manifest(dest_dir, r, w)
    return r

def collect_codex_decl(config: Path | None, dest_dir: Path, w: Writer) -> DeclResult:
    r = DeclResult()
    if config is None:
        _write_manifest(Path(dest_dir), r, w)
        return r
    config = Path(config)
    check_source(config)
    if not config.is_file():
        _write_manifest(Path(dest_dir), r, w)
        return r
    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    for name, spec in (raw.get("plugins") or {}).items():
        r.enabled[name] = bool(spec.get("enabled", False))
    for name, spec in (raw.get("marketplaces") or {}).items():
        r.marketplaces[name] = f"{spec.get('source_type', '?')}:{spec.get('source', '')}"
    r.hooks = raw.get("hooks") or {}
    _write_manifest(Path(dest_dir), r, w)
    return r
```

- [ ] **Step 8: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_collect_decl.py -q`
Expected: 7 passed

- [ ] **Step 9: 提交**

```bash
git add hub/tomlout.py hub/collect/decl.py tests/hub/test_tomlout.py tests/hub/test_collect_decl.py
git commit -m "feat(hub): 声明流水线 —— 自己的插件拷源码,第三方抄声明

按'是不是你的产出'分,不按工具分。Codex 那三个插件恰好全是第三方,
所以它只有 plugins.toml 没有源码目录——这是结果,不是双标。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: secrets_scan.py —— 软提醒

**只提醒,不阻断。** 实测扫 `plugins-dev` 的 10 条命中**全是误报**——正则里的 `sk-` 撞上了 `ta`**`sk-`**`fix3-report`。阻断只会逼人无脑加白名单,闸就废了。

它的真正用途是**提醒你打 `sensitive` 标**:2026-07-12 那两条含密钥的记忆漏进金库,就是因为没人打标。

**Files:**
- Create: `hub/secrets_scan.py`
- Test: `tests/hub/test_secrets_scan.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `hub.secrets_scan.Hit(path: Path, line: int, kind: str, sample: str)`
  - `hub.secrets_scan.scan_text(text: str, path: Path) -> list[Hit]`
  - `hub.secrets_scan.scan_tree(root: Path) -> list[Hit]` —— 只扫文本文件,二进制跳过

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_secrets_scan.py`:

```python
from pathlib import Path
from hub.secrets_scan import scan_text, scan_tree

def test_catches_known_prefixes():
    hits = scan_text("key = sk-abc123def456ghi789jkl\n", Path("a.md"))
    assert len(hits) == 1 and hits[0].kind == "openai"

def test_catches_aliyun_and_github():
    assert scan_text("LTAI5tSomethingLong123\n", Path("a"))[0].kind == "aliyun"
    assert scan_text("ghp_abcdefghijklmnopqrstuvwxyz0123\n", Path("a"))[0].kind == "github"

def test_does_not_fire_on_task_dash():
    # 真实误报：`sk-` 撞上 `task-fix3-report`。这是本模块只提醒不阻断的理由。
    assert scan_text("# task-fix3-report:收口\n", Path("a.md")) == []

def test_does_not_fire_on_prose():
    assert scan_text("把 token 存进 secrets 目录,记忆里只留指针\n", Path("a.md")) == []

def test_reports_line_number_and_redacts_sample():
    hits = scan_text("行一\n行二\nghp_abcdefghijklmnopqrstuvwxyz0123\n", Path("a.md"))
    assert hits[0].line == 3
    assert "…" in hits[0].sample                 # 只给前缀，不把明文抄进 transcript
    assert "wxyz0123" not in hits[0].sample

def test_scan_tree_skips_binaries(tmp_path):
    (tmp_path / "a.md").write_text("ghp_abcdefghijklmnopqrstuvwxyz0123\n", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\x00\x01ghp_abcdefghijklmnopqrstuvwxyz0123")
    hits = scan_tree(tmp_path)
    assert [h.path.name for h in hits] == ["a.md"]
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_secrets_scan.py -q`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.secrets_scan'`

- [ ] **Step 3: 实现 `hub/secrets_scan.py`**

```python
"""软提醒:扫疑似密钥。**只报告,不阻断。**

误报率高到不能当闸——实测扫 plugins-dev 的 10 条命中全是误报(`sk-` 撞上
`task-fix3-report`)。阻断只会逼人无脑加白名单,闸就废了。

它的用途是**提醒你打 sensitive 标 / 把密钥挪进 ~/.claude/secrets/**。
真正的硬闸在 hub/guard.py。
"""
import re
from dataclasses import dataclass
from pathlib import Path

# 已知前缀 —— 边界靠 (?<![\w-]) 挡掉 "task-fix3" 这类误撞
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai", re.compile(r"(?<![\w-])sk-[A-Za-z0-9_-]{20,}")),
    ("github", re.compile(r"(?<![\w-])ghp_[A-Za-z0-9]{28,}")),
    ("aws",    re.compile(r"(?<![\w-])AKIA[0-9A-Z]{16}")),
    ("aliyun", re.compile(r"(?<![\w-])LTAI[A-Za-z0-9]{12,}")),
    ("jwt",    re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}")),
]

@dataclass
class Hit:
    path: Path
    line: int
    kind: str
    sample: str

def _redact(s: str) -> str:
    return s[:8] + "…"          # 只给前缀，不把明文抄进 transcript

def scan_text(text: str, path: Path) -> list[Hit]:
    hits = []
    for i, ln in enumerate(text.splitlines(), start=1):
        for kind, pat in _PATTERNS:
            m = pat.search(ln)
            if m:
                hits.append(Hit(path=Path(path), line=i, kind=kind,
                                sample=_redact(m.group(0))))
    return hits

def scan_tree(root: Path) -> list[Hit]:
    hits = []
    for p in sorted(Path(root).rglob("*")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue            # 二进制/读不了 → 跳过
        hits.extend(scan_text(text, p))
    return hits
```

- [ ] **Step 4: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_secrets_scan.py -q`
Expected: 6 passed

- [ ] **Step 5: 在真实数据上验一遍误报率**

Run:
```bash
py -3 -c "
from pathlib import Path
from hub.secrets_scan import scan_tree
for h in scan_tree(Path(r'C:/Users/huawei/.claude/skills')):
    print(h.kind, h.path, h.line, h.sample)
print('--- 扫完 ---')
"
```
Expected: 输出条数很少(理想是 0)。若命中的是真密钥,记下来——Task 13 要处理。

- [ ] **Step 6: 提交**

```bash
git add hub/secrets_scan.py tests/hub/test_secrets_scan.py
git commit -m "feat(hub): 软提醒 —— 扫疑似密钥,只报告不阻断

误报率高到不能当闸(sk- 会撞 task-fix3-report)。它的用途是提醒打 sensitive 标。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: CLI 汇总 —— collect / sync / status / bootstrap

**Files:**
- Modify: `hub/collect/__init__.py`(加 `run_all`)
- Modify: `hub/cli.py`
- Test: `tests/hub/test_cli.py`

**Interfaces:**
- Consumes: 前面所有流水线
- Produces:
  - `hub.collect.run_all(vault_root: Path, dev: DeviceProfile, w: Writer) -> CollectReport`
  - `hub.collect.CollectReport(memory: MemoryResult, skills: dict[str, list[str]], decl: dict[str, DeclResult], hits: list[Hit])`
  - `hub.cli.main(argv) -> int`,子命令 `collect`(`--dry-run` / `--yes`) / `sync` / `status` / `bootstrap`

- [ ] **Step 1: 写失败的测试**

追加到 `tests/hub/test_cli.py`(保留已有的 fixture,把金库 fixture 改成新结构):

```python
import json
import subprocess
from pathlib import Path
from hub.cli import main

def _mk_vault(tmp_path: Path, host: str = "box1") -> Path:
    v = tmp_path / "vault"
    (v / host / "claude" / "memory").mkdir(parents=True)
    (v / "shared" / "memory").mkdir(parents=True)
    (v / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=v, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=v, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=v, check=True)
    return v

def _mk_sources(tmp_path: Path) -> dict:
    mem = tmp_path / "cl" / "projects" / "p" / "memory"
    mem.mkdir(parents=True)
    (mem / "a.md").write_text(
        "---\nname: a\ndescription: a 摘要\nmetadata:\n  type: reference\n"
        "  scope: [global]\n---\n正文\n", encoding="utf-8")
    sk = tmp_path / "cl" / "skills" / "alpha"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("# alpha\n", encoding="utf-8")
    st = tmp_path / "cl" / "settings.json"
    st.write_text(json.dumps({"enabledPlugins": {"x@m": True}}), encoding="utf-8")
    return {"memory": [mem.as_posix()], "skills": (tmp_path / "cl" / "skills").as_posix(),
            "settings": st.as_posix()}

def _write_device(v: Path, host: str, s: dict):
    (v / host / "device.toml").write_text(
        'class = ["work"]\nprojects = []\n\n[paths]\n'
        f'CLAUDE_HOME = "{(v.parent / "cl").as_posix()}"\n\n'
        "[sources.claude]\n"
        f'memory = ["{s["memory"][0]}"]\n'
        f'skills = "{s["skills"]}"\n'
        f'settings = "{s["settings"]}"\n',
        encoding="utf-8")

def test_collect_fills_backup_zone(tmp_path):
    v = _mk_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    assert main(["collect", "--vault", str(v), "--host", "box1", "--yes"]) == 0
    assert (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert (v / "box1" / "claude" / "skills" / "alpha" / "SKILL.md").exists()
    assert (v / "box1" / "claude" / "plugins.toml").exists()

def test_collect_dry_run_writes_nothing(tmp_path):
    v = _mk_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    assert main(["collect", "--vault", str(v), "--host", "box1", "--dry-run"]) == 0
    assert not (v / "box1" / "claude" / "memory" / "a.md").exists()
    assert not (v / "box1" / "claude" / "skills").exists()

def test_collect_never_touches_shared(tmp_path):
    v = _mk_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    pooled = v / "shared" / "memory" / "p.md"
    pooled.write_text("---\nname: p\ndescription: d\n---\n公共\n", encoding="utf-8")
    before = pooled.read_bytes()
    main(["collect", "--vault", str(v), "--host", "box1", "--yes"])
    assert pooled.read_bytes() == before

def test_collect_regenerates_index(tmp_path):
    v = _mk_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    main(["collect", "--vault", str(v), "--host", "box1", "--yes"])
    idx = (v / "MEMORY.md").read_text(encoding="utf-8")
    assert "[a](box1/claude/memory/a.md)" in idx

def test_collect_without_yes_aborts_when_it_would_delete(tmp_path, monkeypatch, capsys):
    v = _mk_vault(tmp_path)
    _write_device(v, "box1", _mk_sources(tmp_path))
    stale = v / "box1" / "claude" / "memory" / "gone.md"
    stale.write_text("---\nname: gone\ndescription: d\n---\n旧\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert main(["collect", "--vault", str(v), "--host", "box1"]) == 1
    assert stale.exists()                         # 没确认就不删
    assert "gone" in capsys.readouterr().out      # 但要把要删的列出来
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_cli.py -q`
Expected: FAIL

- [ ] **Step 3: 实现 `hub/collect/__init__.py` 的 `run_all`**

```python
"""提取器:把本机各工具的家当收进金库的备份区。

铁律:只写 <本机>/,不碰 shared/,不碰别的设备,不写任何工具的地盘。
"""
from dataclasses import dataclass, field
from pathlib import Path
from hub.collect.decl import DeclResult, collect_claude_decl, collect_codex_decl
from hub.collect.memory import MemoryResult, collect_memory, plan_memory
from hub.collect.skills import collect_skills
from hub.model import DeviceProfile
from hub.secrets_scan import Hit, scan_tree
from hub.writer import Writer

@dataclass
class CollectReport:
    memory: MemoryResult = field(default_factory=MemoryResult)
    skills: dict[str, list[str]] = field(default_factory=dict)
    decl: dict[str, DeclResult] = field(default_factory=dict)
    hits: list[Hit] = field(default_factory=list)

def plan_deletions(vault_root: Path, dev: DeviceProfile) -> list[str]:
    """这次 collect 会从金库删掉哪些记忆。给 CLI 拿去问人。"""
    src = dev.sources.get("claude")
    dirs = [Path(s) for s in (src.memory if src else [])]
    return plan_memory(dirs, vault_root, dev.host).deleted

def run_all(vault_root: Path, dev: DeviceProfile, w: Writer) -> CollectReport:
    vault_root = Path(vault_root)
    home = vault_root / dev.host
    rep = CollectReport()

    cl = dev.sources.get("claude")
    if cl:
        rep.memory = collect_memory([Path(s) for s in cl.memory], vault_root, dev.host, w)
        rep.skills["claude"] = collect_skills(
            Path(cl.skills) if cl.skills else None, home / "claude" / "skills", w)
        rep.decl["claude"] = collect_claude_decl(
            Path(cl.plugin_repos) if cl.plugin_repos else None,
            Path(cl.settings) if cl.settings else None,
            home / "claude", w)
        if cl.agents:
            p = Path(cl.agents)
            if p.is_file():
                w.write_text(home / "claude" / p.name, p.read_text(encoding="utf-8"))

    cx = dev.sources.get("codex")
    if cx:
        rep.skills["codex"] = collect_skills(
            Path(cx.skills) if cx.skills else None, home / "codex" / "skills", w)
        rep.decl["codex"] = collect_codex_decl(
            Path(cx.settings) if cx.settings else None, home / "codex", w)
        if cx.agents:
            p = Path(cx.agents)
            if p.is_file():
                w.write_text(home / "codex" / p.name, p.read_text(encoding="utf-8"))

    if not w.dry_run and home.is_dir():
        rep.hits = scan_tree(home)      # 软提醒：扫刚落进金库的东西
    return rep
```

- [ ] **Step 4: 实现 `hub/cli.py` 的 `_cmd_collect` / `_cmd_bootstrap`**

把 `hub/cli.py` 里的 `_cmd_collect` 替换,并加 `_cmd_bootstrap`:

```python
from hub.collect import plan_deletions, run_all
from hub.writer import Writer

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)

    doomed = plan_deletions(vault_root, dev)
    if doomed and not args.yes and not args.dry_run:
        print(f"这次会从金库删掉 {len(doomed)} 条记忆(本机源里已经没有它们了):")
        for n in doomed:
            print("  -", n)
        if input("确认删除? [y/N] ").strip().lower() != "y":
            print("已取消。")
            return 1

    w = Writer(dry_run=args.dry_run)
    rep = run_all(vault_root, dev, w)

    print(f"记忆: 写 {len(rep.memory.written)} 删 {len(rep.memory.deleted)}")
    if rep.memory.skipped_sensitive:
        print(f"  跳过 sensitive: {rep.memory.skipped_sensitive}")
    for tool, names in rep.skills.items():
        print(f"{tool} skill: {len(names)} 把 {names}")
    for tool, d in rep.decl.items():
        print(f"{tool} 插件: 自有 {len(d.repos)} 个, 第三方声明 {len(d.enabled)} 条")
        if d.dirty:
            print(f"  ⚠ 有未提交改动，快照里没有这些改动: {d.dirty}")
    if rep.hits:
        print(f"\n⚠ 疑似密钥 {len(rep.hits)} 处(**只是提醒,不阻断**;"
              f"确认是真密钥就挪进 ~/.claude/secrets/ 或给记忆打 sensitive: true):")
        for h in rep.hits:
            print(f"  {h.kind}  {h.path}:{h.line}  {h.sample}")

    if not args.dry_run:
        vault = load_vault(vault_root)
        _write_index(vault_root, vault)
    return 0

def _cmd_bootstrap(args) -> int:
    """换新机:把金库里的加载器 skill 装进各工具,然后退场。

    这是提取器铁律("只写金库")的**唯一例外**——新机上还没有 skill(skill 自己
    也在金库里),这是个鸡生蛋。bootstrap 只打破这个循环,只写各工具的 skill 目录。
    剩下的(记忆怎么装、装哪些)交给 skill 自己跑。
    """
    import shutil
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    src = vault_root / "shared" / "skills"
    if not src.is_dir():
        print("金库的 shared/skills/ 是空的，没有加载器 skill 可装。")
        return 1
    installed = []
    for tool, home_key in (("claude", "CLAUDE_HOME"), ("codex", "CODEX_HOME")):
        home = dev.paths.get(home_key)
        if not home:
            continue
        for d in sorted(p for p in src.iterdir() if p.is_dir() and p.name.startswith("hub-")):
            dest = Path(home) / "skills" / d.name
            if args.dry_run:
                print(f"  [dry-run] 装 {d.name} → {dest}")
                continue
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d, dest)
            installed.append(f"{tool}:{d.name}")
    print(f"已装 {len(installed)} 把加载器 skill: {installed}")
    print("接下来在各工具里跑那把 skill，它会自己去金库取记忆。")
    return 0
```

`build_parser` 换成:

```python
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common]).set_defaults(func=_cmd_status)
    sub.add_parser("sync", parents=[common]).set_defaults(func=_cmd_sync)
    for name, fn in (("collect", _cmd_collect), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.add_argument("--dry-run", action="store_true",
                        help="只报告会写哪些文件，一个字节都不落盘")
        sp.add_argument("--yes", action="store_true",
                        help="不询问，直接执行（含删除）")
        sp.set_defaults(func=fn)
    return p
```

- [ ] **Step 5: 跑全量**

Run: `py -3 -m pytest -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat(hub): collect 汇总四条流水线 + bootstrap

collect --dry-run 预览 / --yes 免确认;删记忆前先列出来问。
bootstrap 是'只写金库'铁律的唯一例外——新机上得先有人把加载器 skill 装进工具。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: scaffold_vault 生成新结构 + SCHEMA.md

`SCHEMA.md` 是 **A 与 C 之间唯一的接口**。C 阶段的 skill 读它,不读 Python 源码。

**Files:**
- Modify: `hub/scaffold_vault.py`
- Create: `hub/schema_md.py`(SCHEMA.md 的正文,单独一个模块,免得把长文本塞进 scaffold)
- Test: `tests/hub/test_scaffold.py`

**Interfaces:**
- Consumes: `hub.writer.Writer`
- Produces:
  - `hub.schema_md.SCHEMA_MD: str`
  - `hub.scaffold_vault.scaffold(root: Path, host: str, w: Writer) -> None`

- [ ] **Step 1: 写失败的测试**

`tests/hub/test_scaffold.py`:

```python
import tomllib
from pathlib import Path
from hub.scaffold_vault import scaffold
from hub.writer import Writer
from hub.vault import load_vault, load_device

def test_scaffold_creates_both_zones(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    for p in ["vault.toml", "SCHEMA.md",
              "shared/memory", "shared/skills", "shared/plugins",
              "shared/hooks", "shared/chats",
              "box1/device.toml",
              "box1/claude/memory", "box1/claude/skills", "box1/claude/plugins",
              "box1/claude/hooks", "box1/claude/chats",
              "box1/codex/skills", "box1/codex/hooks", "box1/codex/chats"]:
        assert (tmp_path / p).exists(), p

def test_placeholder_dirs_have_gitkeep(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    assert (tmp_path / "shared" / "chats" / ".gitkeep").exists()
    assert (tmp_path / "box1" / "claude" / "hooks" / ".gitkeep").exists()

def test_scaffolded_vault_loads(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    v = load_vault(tmp_path)
    assert v.memories == []
    dev = load_device(tmp_path, "box1")
    assert dev.host == "box1"

def test_device_toml_is_valid_toml_with_tool_sections(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    raw = tomllib.loads((tmp_path / "box1" / "device.toml").read_text(encoding="utf-8"))
    assert "claude" in raw["sources"] and "codex" in raw["sources"]

def test_schema_md_documents_the_contract(tmp_path):
    scaffold(tmp_path, "box1", Writer())
    s = (tmp_path / "SCHEMA.md").read_text(encoding="utf-8")
    for token in ["备份区", "共享区", "merged.txt", "rejected.txt",
                  "sensitive", "scope", "生成态"]:
        assert token in s, token

def test_dry_run_creates_nothing(tmp_path):
    scaffold(tmp_path, "box1", Writer(dry_run=True))
    assert not (tmp_path / "vault.toml").exists()
```

- [ ] **Step 2: 跑,确认失败**

Run: `py -3 -m pytest tests/hub/test_scaffold.py -q`
Expected: FAIL

- [ ] **Step 3: 写 `hub/schema_md.py`**

```python
SCHEMA_MD = """# 金库 SCHEMA —— hub 与各工具 skill 之间的契约

这份文件是**唯一接口**。加载器 skill(hub-claude / hub-codex / …)读它,不读 Python 源码。
以后加新工具,只写一把新 skill,提取器一行不用改。

## 两个区

    vault/
    ├─ vault.toml  SCHEMA.md  MEMORY.md  lint-exempt.txt
    │
    ├─ <设备名>/                ┃ 备份区:这台机的原始数据,原样、不加工
    │   ├─ device.toml
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ plugins.toml CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    │
    └─ shared/                 ┃ 共享区:跨设备/跨工具的精选,按类型分
        └─ memory/ skills/ plugins/ hooks/ chats/

**备份区 = "别丢"**。换机照它还原。按工具分,因为原始数据本来就是工具形状的。
**共享区 = "到处都要有"**。skill 照它装。按类型分——两个工具都吃 skill、都有插件系统。

## 谁写哪一区

| 区 | 写者 | 性质 |
|---|---|---|
| 备份区 `<设备>/` | **提取器(Python)** | 机械搬运,不做判断。**幂等全量重写** |
| 共享区 `shared/` | **skill** | 判断题:什么值得跨设备/跨工具共享 |
| 工具地盘 | **skill** | 判断题:什么该进我的脑子 |

**提取器只写 `<本机>/`。** 它不碰 `shared/`,不碰别的设备,不写任何工具的地盘。
唯一例外是 `hub bootstrap`(新机上把加载器 skill 装进工具,打破鸡生蛋),且只写 skill 目录。

## 记忆的格式

一条记忆 = 一个 md 文件,带 frontmatter:

```markdown
---
name: <kebab-case 短名，与文件名一致>
description: <一句话摘要——索引里显示的就是它>
metadata:
  type: user | feedback | project | reference
  scope: [global]          # 见下
  portable: true
  sensitive: false         # true = 不入金库（阶段 B 改成加密入库）
---

正文。用 [[其它记忆名]] 互链。
```

**记忆的位置**:备份区在 `<设备>/claude/memory/`(Claude 的著作物);共享区在 `shared/memory/`(工具无关——知识就是知识)。

**`~/.codex/memories/` 不收。** 那是 Codex 后台从任务里自动蒸馏的**生成态**目录,
官方明说"视为生成状态,不要依赖手工编辑"。格式不公开、不保证稳定,而且会触发自我复制回环
(hub 灌给它的记忆 → 它当"学到的事实"再蒸馏 → 又收回金库 → 又灌回去)。
**记忆的真源只有一处:hub 金库。**

## scope

- 同维度 OR,跨维度 AND,缺省的维度不限制。
- `global` 必须单独出现,不可与维度谓词混用。
- 维度:`device:<class>` / `project:<名>` / `tool:<名>`。

**匹配逻辑归 skill**——"这条记忆该不该进我的脑子"是加载侧的判断题。
提取器只做**格式校验**,自己从不按 scope 筛选任何东西(备份区是本机现状的镜像,不做选择)。

## 跨设备的人工闸门(由 skill 实现)

别的设备写的记忆**不会自动进本机**。skill 负责这道闸:

| 文件 | 位置 | 内容 |
|---|---|---|
| `merged.txt` | `<本机>/` | 已接纳的外来记忆,一行一条 `<归属>/<记忆名>` |
| `rejected.txt` | `<本机>/` | 拒绝过的,别再问。一行一条,格式同上 |

- **可见**:`shared/` 里的 + 本机自产的 + `merged.txt` 里列出的。
- **待审**:别的设备的,且不在 `merged.txt` / `rejected.txt` 里。
- skill 应当**先读一遍待审记忆的正文,判断是否适合合并到本机,给出建议**,由用户拍板。
- 用户说"全部去读一遍看看"时,**忽略 `rejected.txt` 重新过**。
- **提升到共享区** = 把 `<设备>/claude/memory/<名>.md` 移到 `shared/memory/<名>.md`。目标已存在同名时**停下来问**,绝不静默覆盖。

## 插件清单 `plugins.toml`

```toml
[repos.<插件名>]        # 只有"你自己写的"插件才有这一节（源码已快照在 plugins/ 下）
remote = "https://github.com/…"
sha = "<40 位>"
dirty = false           # true = 快照里没有工作区未提交的改动

[enabled]               # 第三方 + 自有，全部的启用状态
"superpowers@claude-plugins-official" = true

[marketplaces]
xu-local = "directory:C:\\\\Users\\\\x\\\\.claude\\\\plugins-dev"
```

**第三方插件只抄声明,不拷源码**(别人的代码,市场在就能重装;里面是 LSP 二进制,换台机就是废的)。

## 阶段 B 预留

`chats/` 与 `hooks/` 目前是空目录。

- **chats**:对话归档。要等加密层(阶段 B)——对话正文必定含密钥/公司代码,明文进 NAS 不可接受。
  设计意图:**加密入库,金库里只暴露名字**;要用时本地下载、本地解锁。
- **hooks**:当前 Claude 的 `settings.json` 没有 `hooks` 键(hook 全在插件里),Codex 也没有。
  一旦出现用户级 hook,由声明流水线填充。

## 硬闸(提取器强制,不靠自觉)

1. `~/.claude/secrets/`、`~/.codex/auth.json` —— **永不读取**。私密内容留在 secrets/,记忆里只写指针。
2. gitignored / untracked 文件 —— **不进快照**(用 `git archive`,不用 `cp -r`)。
3. `sensitive: true` 的记忆 —— **不入库**(阶段 B 改成加密入库)。
"""
```

- [ ] **Step 4: 改 `hub/scaffold_vault.py`**

整个文件替换:

```python
"""脚手架:建一个空金库(两区结构 + SCHEMA.md)。"""
from pathlib import Path
from hub.schema_md import SCHEMA_MD
from hub.writer import Writer

_SHARED_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CLAUDE_DIRS = ["memory", "skills", "plugins", "hooks", "chats"]
_CODEX_DIRS = ["skills", "hooks", "chats"]

_DEVICE_TOML = """# 本机档案。缺的项 = 本机没有那个工具/那个源，不是错误。
class = ["work"]
projects = []

[paths]
VAULT = "<金库路径>"
CLAUDE_HOME = "<~/.claude 的绝对路径>"
CODEX_HOME = "<~/.codex 的绝对路径>"

[sources.claude]
memory = ["<~/.claude/projects/<工程编码>/memory>"]
skills = "<~/.claude/skills>"
plugin_repos = "<~/.claude/plugins-dev>"   # 自己写的插件仓所在目录
settings = "<~/.claude/settings.json>"
agents = "<~/.claude/CLAUDE.md>"

[sources.codex]
skills = "<~/.codex/skills>"
settings = "<~/.codex/config.toml>"
agents = "<~/.codex/AGENTS.md>"
# 注：~/.codex/memories/ 不收 —— 生成态，见 SCHEMA.md
"""

def scaffold(root: Path, host: str, w: Writer) -> None:
    root = Path(root)
    w.write_text(root / "vault.toml", "version = 1\n")
    w.write_text(root / "SCHEMA.md", SCHEMA_MD)
    w.write_text(root / "lint-exempt.txt",
                 "# 一行一个记忆 name：豁免裸路径检查（scope 与 sensitive 仍硬拦）\n")
    for d in _SHARED_DIRS:
        w.write_text(root / "shared" / d / ".gitkeep", "")
    for d in _CLAUDE_DIRS:
        w.write_text(root / host / "claude" / d / ".gitkeep", "")
    for d in _CODEX_DIRS:
        w.write_text(root / host / "codex" / d / ".gitkeep", "")
    w.write_text(root / host / "device.toml", _DEVICE_TOML)

if __name__ == "__main__":
    import sys
    scaffold(Path(sys.argv[1]), sys.argv[2], Writer())
    print(f"金库已建在 {sys.argv[1]}，设备 {sys.argv[2]}。先填 device.toml 里的 <…> 占位。")
```

- [ ] **Step 5: 跑,确认通过**

Run: `py -3 -m pytest tests/hub/test_scaffold.py -q`
Expected: 6 passed

- [ ] **Step 6: 跑全量**

Run: `py -3 -m pytest -q`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat(hub): scaffold 生成两区结构 + SCHEMA.md

SCHEMA.md 是 A 与 C 之间唯一的接口:加载器 skill 读它,不读 Python 源码。
以后加新工具只写一把新 skill,提取器一行不动。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: 迁移真实金库

对 `C:\Users\huawei\hub-vault` 做一次性迁移。**这一步有人工闸门,不能无人值守。**

**Files:**
- Modify(金库,不是代码仓): `C:\Users\huawei\hub-vault\**`
- Modify(记忆): `reference_oss_picgo_imghost.md`、`reference_mineru_extractor.md`
- Create: `~/.claude/secrets/<待确认>`、`~/.claude/secrets/INDEX.md`(补行)

- [ ] **Step 1: 备份现有金库**

```bash
cd /c/Users/huawei/hub-vault
git status --short          # 必须是干净的
git tag pre-two-zone-migration
```

- [ ] **Step 2: 用 `git mv` 把记忆挪进新位置**

```bash
cd /c/Users/huawei/hub-vault
mkdir -p 2025-bg-016/claude
git mv 2025-bg-016/memory 2025-bg-016/claude/memory
```

- [ ] **Step 3: 建新目录骨架并写 SCHEMA.md**

```bash
cd /c/Users/huawei/ai-cli-migrate
py -3 -c "
from pathlib import Path
from hub.schema_md import SCHEMA_MD
from hub.writer import Writer
v = Path(r'C:/Users/huawei/hub-vault')
w = Writer()
w.write_text(v / 'SCHEMA.md', SCHEMA_MD)
for d in ['memory','skills','plugins','hooks','chats']:
    w.write_text(v / 'shared' / d / '.gitkeep', '')
for d in ['skills','plugins','hooks','chats']:
    w.write_text(v / '2025-bg-016' / 'claude' / d / '.gitkeep', '')
for d in ['skills','hooks','chats']:
    w.write_text(v / '2025-bg-016' / 'codex' / d / '.gitkeep', '')
print('骨架 OK')
"
# scaffold 时代遗留的空目录（shared/rules 等）
cd /c/Users/huawei/hub-vault && git rm -r --ignore-unmatch shared/rules
```

- [ ] **Step 4: 重写 `device.toml`**

`C:\Users\huawei\hub-vault\2025-bg-016\device.toml`:

```toml
class = ["work"]
projects = ["xinao"]

[paths]
VAULT = "C:/Users/huawei/hub-vault"
CLAUDE_HOME = "C:/Users/huawei/.claude"
CODEX_HOME = "C:/Users/huawei/.codex"

[sources.claude]
memory = ["C:/Users/huawei/.claude/projects/C--Users-huawei-Desktop-MyProjects-20260525-xinao-Code/memory"]
skills = "C:/Users/huawei/.claude/skills"
plugin_repos = "C:/Users/huawei/.claude/plugins-dev"
settings = "C:/Users/huawei/.claude/settings.json"
agents = "C:/Users/huawei/.claude/CLAUDE.md"

[sources.codex]
skills = "C:/Users/huawei/.codex/skills"
settings = "C:/Users/huawei/.codex/config.toml"
agents = "C:/Users/huawei/.codex/AGENTS.md"
# ~/.codex/memories/ 不收 —— 生成态，见 SCHEMA.md
```

- [ ] **Step 5: 【人工闸门】处理两条含密钥的记忆**

**停下来问用户,不要自作主张。** 涉及的两条:

| 记忆 | 里面有什么 |
|---|---|
| `reference_oss_picgo_imghost` | 阿里云 OSS(picgo-imgs1270)的 AccessKey / Secret |
| `reference_mineru_extractor` | MinerU API token |

按用户的全局约定:**私密内容统一放 `~/.claude/secrets/`,明文;存入前先确认文件名和用途,确认后再存,并在 `INDEX.md` 清单表补一行;撞同名先问、别直接覆盖。**

做法:
1. 读 `~/.claude/secrets/INDEX.md`,看有没有现成的条目可以合并。
2. **问用户**:这两份密钥各自该叫什么文件名、写什么用途。
3. 用户确认后,把密钥写进 `~/.claude/secrets/<确认的文件名>`,`INDEX.md` 补行。
4. 改这两条记忆的正文:**删掉明文密钥,改成指针**(如"凭据见 `~/.claude/secrets/INDEX.md` 里的 `<条目名>`")。
5. 记忆的 frontmatter **不用**打 `sensitive: true` —— 密钥已经不在正文里了,记忆本身可以入库。

改完跑一遍验证:
```bash
cd /c/Users/huawei/ai-cli-migrate
py -3 -c "
from pathlib import Path
from hub.secrets_scan import scan_tree
hits = scan_tree(Path(r'C:/Users/huawei/.claude/projects/C--Users-huawei-Desktop-MyProjects-20260525-xinao-Code/memory'))
print('记忆里的疑似密钥:', [(h.path.name, h.kind) for h in hits] or '无')
"
```
Expected: `无`

- [ ] **Step 6: 跑一次 dry-run,看清楚它想干什么**

```bash
cd /c/Users/huawei/ai-cli-migrate
py -3 -m hub.cli collect --vault C:/Users/huawei/hub-vault --host 2025-bg-016 --dry-run
```
Expected: 报告会写记忆/skill/插件快照,**一个字节都不落盘**。逐行看一遍,尤其是"会删掉"的清单。

- [ ] **Step 7: 真跑**

```bash
py -3 -m hub.cli collect --vault C:/Users/huawei/hub-vault --host 2025-bg-016
```
Expected: 47 条记忆、Claude 7 把 skill、Codex 3 把 skill、6 个自有插件快照、两份 `plugins.toml`。留意"未提交改动"警告。

- [ ] **Step 8: 验收**

```bash
cd /c/Users/huawei/hub-vault
du -sh .                                  # 应该在 5 MB 量级，不是 70 MB
find . -name .git -not -path './.git*'    # 必须为空 —— 金库里不能有嵌套仓
git status --short | head -20
```
Expected: 无嵌套 `.git`;体积在几 MB;`shared/` 除 `.gitkeep` 外无改动。

- [ ] **Step 9: 提交金库**

```bash
cd /c/Users/huawei/hub-vault
git add -A
git commit -m "chore(vault): 迁到两区结构（备份区 + 共享区）

记忆挪进 <设备>/claude/memory/;新增 SCHEMA.md（与 skill 的契约）;
收进 skills / 自有插件快照 / 第三方插件声明。
含密钥的记忆改成指向 ~/.claude/secrets/ 的指针。"
```

---

## Self-Review

**Spec 覆盖检查:**

| spec 节 | 落在哪个 task |
|---|---|
| §1 转向理由 | Task 1(拆除落地层) |
| §2 架构 / 铁律 | Task 1、Task 11(bootstrap 是唯一例外) |
| §3 金库结构 / 两区 | Task 3、Task 12 |
| §3 不备份的东西 | Task 5(硬闸)、Task 7(git archive 排除 ignored)、Task 9(第三方只抄声明) |
| §4 五条流水线 | Task 6(记忆)、Task 8(skill)、Task 9(插件+声明+hooks) |
| §4.1 git archive vs cp -r | Task 7 |
| §4.2 镜像语义 | Task 6、Task 11(删前确认) |
| §4.3 派生目录全量重写 | Task 2(`Writer.copy_tree`)、Task 8 |
| §4.4 索引 | Task 3(derive)、Task 11 |
| §5 三道硬闸 | Task 5(闸 1)、Task 7(闸 2)、Task 6(闸 3) |
| §5 软提醒 | Task 10 |
| §6 CLI | Task 11 |
| §7 错误处理 5 条 | Task 4(1)、Task 9(2)、Task 6(3)、Task 11(4)、Task 2(5) |
| §7 scope 归谁 | Task 12(写进 SCHEMA.md);`scope.py` 不动 |
| §8 代码变动 | Task 1(删)、其余各 task |
| §9 测试 | 每个 task 自带 |
| §10 一次性迁移 | Task 13 |

**偏离**:hooks 从独立流水线降级成 Task 9 的一部分(实测两个工具的用户级 hook 都是空的),已在计划开头报备。

**类型一致性**:`Writer` 在 Task 2 定义,Task 6/7/8/9/11/12 全部按 `Writer(dry_run=...)` + `write_text` / `rmtree` / `unlink` / `copy_tree` 使用。`RepoMeta` 在 Task 7 定义(`name` / `remote` / `sha` / `dirty`),Task 9 按此消费。`MemoryResult` 的三个字段(`written` / `deleted` / `skipped_sensitive`)在 Task 6 定义,Task 11 按此消费。`render_memory_index(memories, vault_root)` 在 Task 3 改成两参,Task 11 按两参调用。
