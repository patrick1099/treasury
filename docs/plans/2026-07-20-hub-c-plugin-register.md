# Plan 3 —— hub C 阶段插件 register/refresh/status 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或
> superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 自有插件活源住进 `hub-vault/shared/plugins/<name>/`（独立嵌套 git 仓，父仓跟踪源码文件、排除嵌套
`.git`）；hub 用官方 CLI 把各平台**指向/加载 shared**，实现 `register`/`refresh`/`status` 三链路。主路径
「改插件 → bump+commit → refresh → 加载新版、幂等、仓干净」端到端可跑。

**Architecture:** 通用 `induction` 原语（prepare/execute 分离）把带 `.git` 的产物纳入父仓跟踪。插件层：纯计划
`plugin_ops.prepare_*() -> PluginPlan`（含 `PluginAction.id/depends_on` 依赖）+ 单一执行器
`execute_plugin_plan()`；dry-run 与真跑**消费同一 PluginPlan**、只在执行器分流。平台变化只经 `claude/codex
plugin` CLI；hub 自有状态走原子 `Writer`。

**Tech Stack:** Python 3（stdlib + 现有 hub 依赖，无新第三方）；`subprocess` 调平台 CLI（**测试注入假
runner，绝不真调**）；`git`；pytest。**权威设计：** `docs/specs/2026-07-16-hub-c-register-design.md` §10。

## Global Constraints

- **vault 契约 v3**：`vault.toml` version 2→3；一般命令遇 version>3 拒绝；**插件链路要求精确 version==3**
  （v1/v2 上不得跑插件命令）。
- **平台变化只经官方 CLI**；**绝不**直写 `cache/`/`installed_plugins.json`/`known_marketplaces.json`/Codex
  `config.toml`。hub 自有状态（`~/.hub/plugin-state.toml`、induction 事务日志）走 `Writer` 原子写。
- **dry-run 与真跑消费同一 `PluginPlan`/`InductionPlan`/`MigrationPlan`**，只在执行器分流；prepare 阶段**纯只读**，
  不移动文件、不调 induction、不发 CLI 写命令。
- **确定性错误全量预检在前**（version!=3、CLI 缺失/子命令不认、manifest 缺失/身份不一致、容器逃逸、SHA 变但
  版本未 bump、仓 dirty）→ 抛错、零副作用。执行期 CLI 部分失败：按 `depends_on` **阻断后继**、报清
  「成功/未执行/失败」、幂等重跑收敛；**台账只在整条链成功后写**。
- **register 全量 prepare→commit**：`prepare_memory + prepare_links + prepare_plugins` 全部确定性校验通过后
  才 commit，任一预检失败**零写入**（不破坏 Plan 2 的视图/链接零写保证）。
- **身份稳定 `<name>@<name>`**：目录名 = manifest name = marketplace 名 = marketplace 内 plugin 名 =
  `.claude-plugin/plugin.json` name（Claude 与 Codex 兼容模式共用），全等 `<name>`。
- **平台命令与 JSON 形状（spike 实测锁定）**：
  - Claude 重装：`uninstall <n>@<n> --keep-data --scope user` + `install <n>@<n> --scope user`；reinstall 会
    **重新 enable**，原 disabled 需事后 `disable` 恢复。禁用：`disable <n>@<n>`（不卸载）。
  - Codex 重装：`add <n>@<n>`；禁用=期望安装集合外→`remove <n>@<n>`（Codex 无 enable/disable）。
  - 同名换源：Codex 拒绝→`marketplace remove`+`add`；Claude `marketplace add` 直接覆盖。
  - `claude plugin list --json` → `[{id,version,scope,enabled,installPath}]`；`claude plugin marketplace list
    --json` → `[{name,source,path,installLocation}]`。
  - `codex plugin list --json` → `{installed:[{pluginId,name,marketplaceName,version,enabled,source:{path}}],
    available:[...]}`；`codex plugin marketplace list --json` → `{marketplaces:[{name,root}]}`。
- **测试隔离**：`tmp_path`/`HUB_HOME`；CLI 用**注入假 runner**；真机 CLI 冒烟仅在隔离 `CODEX_HOME`/
  `CLAUDE_CONFIG_DIR`。**唯一真机迁移在 T15，设人工闸。**
- **Esafenet DRM**：`.py` 用 Read/Edit/Grep + `py -3`/pytest，绝不裸 `cat`/`sed`。**提交身份** `patrick1099`
  （repo 已配 noreply）；footer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`；Windows 用 `py -3`。

## 前置：Claude/Codex CLI spike（已完成，findings 在 spec §10.2 P2/P4/P5/P8 + 上方 Global Constraints）

## 文件结构

```
hub/induction.py        (新) 通用 induction：prepare_induction/execute_induction/recover_pending；日志+暂存在父仓 .git 内
hub/plugin_manifest.py  (新) PluginEntry + load_plugin_manifest + check_identity + plugin_version
hub/plugin_state.py     (新) Baseline + read_state + record（HUB_HOME/plugin-state.toml，插件×平台）
hub/plugin_cli.py       (新) CliCommand/CliResult + run_cli(runner) + preflight_cli + installed_plugins + marketplaces
hub/plugin_ops.py       (新) PluginAction(id,depends_on)/PluginPlan/PluginRunReport/PluginHealth
                              prepare_plugin_register/prepare_plugin_refresh/execute_plugin_plan/plugin_health
hub/plugin_migrate.py   (新) Migration* 类型 + load_migration_input + prepare_migration(纯,14a) + execute_migration(14b) + prepare_cutover(14c)
hub/migrate.py          (改) migrate-schema 2→3
hub/scaffold_vault.py   (改) 写 version=3
hub/schema_md.py        (改) SCHEMA_MD 常量升 v3 正文
hub/vault.py            (改) require_supported_version/require_version_exactly；load_device [plugins.<tool>]
hub/model.py            (改) DeviceProfile.plugins
hub/cli.py              (改) register/refresh/status 接线 + 全量 prepare→commit + 双 dry-run
tests/hub/test_*.py     (新)
```

---

## Task 2: vault v3 gating + migrate-schema 2→3 + scaffold v3

**Files:** Modify `hub/migrate.py`、`hub/scaffold_vault.py`、`hub/vault.py`；Test `tests/hub/test_migrate.py`、
`tests/hub/test_vault_version.py`。

**Interfaces (Produces):** `require_supported_version(root, max_known=3) -> int`（>max_known 抛
`UnsupportedVaultVersion`）；`require_version_exactly(root, want) -> None`（!=want 抛 `UnsupportedVaultVersion`，
插件链路用）；`migrate_schema(root, to, w)` 接受 `to∈{2,3}`（2→3 仅从 v2）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_vault_version.py 新建
import pytest
from hub.vault import require_supported_version, require_version_exactly, UnsupportedVaultVersion

def _v(tmp, n): (tmp/"vault.toml").write_text(f"version = {n}\n", encoding="utf-8")

def test_supported_v3_ok(tmp_path):
    _v(tmp_path, 3); assert require_supported_version(tmp_path) == 3

def test_future_refused(tmp_path):
    _v(tmp_path, 4)
    with pytest.raises(UnsupportedVaultVersion):
        require_supported_version(tmp_path)

def test_exactly_3_required(tmp_path):
    _v(tmp_path, 2)
    with pytest.raises(UnsupportedVaultVersion):
        require_version_exactly(tmp_path, 3)     # 插件命令在 v2 上必须拒绝
```

```python
# tests/hub/test_migrate.py 追加
import pytest
from hub.writer import Writer
from hub.migrate import migrate_schema, SchemaMigrationError

def test_migrate_2_to_3(tmp_path):
    (tmp_path/"vault.toml").write_text("version = 2\n", encoding="utf-8")
    migrate_schema(tmp_path, 3, Writer())
    assert (tmp_path/"vault.toml").read_text(encoding="utf-8").strip() == "version = 3"

def test_migrate_3_only_from_2(tmp_path):
    (tmp_path/"vault.toml").write_text("version = 1\n", encoding="utf-8")
    with pytest.raises(SchemaMigrationError):
        migrate_schema(tmp_path, 3, Writer())

def test_migrate_rejects_unknown_target(tmp_path):
    (tmp_path/"vault.toml").write_text("version = 2\n", encoding="utf-8")
    with pytest.raises(SchemaMigrationError):
        migrate_schema(tmp_path, 4, Writer())
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_vault_version.py tests/hub/test_migrate.py -q`，预期 FAIL（`ImportError`/未支持 to=3）。

- [ ] **Step 3: 实现**

```python
# hub/vault.py 追加
class UnsupportedVaultVersion(RuntimeError): pass

def _read_version(root) -> int:
    return int(tomllib.loads((Path(root)/"vault.toml").read_text(encoding="utf-8")).get("version", 1))

def require_supported_version(root, max_known: int = 3) -> int:
    v = _read_version(root)
    if v > max_known:
        raise UnsupportedVaultVersion(
            f"金库版本 {v} 高于本 hub 所知（最高 {max_known}）——请先升级 hub，绝不按旧模型运行。")
    return v

def require_version_exactly(root, want: int) -> None:
    v = _read_version(root)
    if v != want:
        raise UnsupportedVaultVersion(f"本命令要求金库 version=={want}，当前是 {v}——先 `hub migrate-schema --to {want}`。")
```

`hub/migrate.py`：现有实现（1→2）改成支持 `to∈{2,3}`：`to==2` 从 v1、`to==3` 从 v2，其余/同版/跨版拒
`SchemaMigrationError`；写 `f"version = {to}\n"`（原子）。`hub/scaffold_vault.py`：`version = 2\n` → `version = 3\n`（含注释文字）。

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `git add hub/migrate.py hub/vault.py hub/scaffold_vault.py tests/hub/test_migrate.py tests/hub/test_vault_version.py && git commit -m "feat(hub): vault schema v3 gating + migrate-schema 2->3"`

---

## Task 3: SCHEMA_MD 常量升 v3 正文

**Files:** Modify `hub/schema_md.py`（`SCHEMA_MD` 常量）；Test `tests/hub/test_schema_md.py`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_schema_md.py 追加
from hub.schema_md import SCHEMA_MD
def test_schema_v3_contract():
    assert "version = 3" in SCHEMA_MD
    assert "shared/plugins/manifest.toml" in SCHEMA_MD
    assert "induction" in SCHEMA_MD.lower()
    assert "嵌套" in SCHEMA_MD and ".git" in SCHEMA_MD
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_schema_md.py -q`（`AssertionError`）。
- [ ] **Step 3: 实现**（对 `hub/schema_md.py` 的 `SCHEMA_MD` 常量做两处编辑）：

  **(a)** 用 Edit 把常量里这行的 `version = 2` 改成 `version = 3`：
  ```
  ├─ vault.toml        金库格式版本(version = 2)。以后改布局靠它做迁移判断
  ```
  改为：
  ```
  ├─ vault.toml        金库格式版本(version = 3)。以后改布局靠它做迁移判断
  ```

  **(b)** 在 `SCHEMA_MD` 结尾的闭合 `"""` **之前**，原样追加下面这段（`\n` 后紧接 `"""`）：
  ```
  ## 12. v3：shared 三分跟踪与插件（v3 新增）

  `shared/` 是所有"项目无关、每机都同步"基础设施的**唯一稳态活源**：改/commit/push 都从这里发生。

  **三分跟踪**：父仓（hub-vault）跟踪产物源码文件；**排除每个产物内的嵌套 `.git/`**（一个 `shared/<类>/<name>`
  可以自身是独立 git 仓）；密钥/token/auth **永不进 shared**，留本机私密区。

  **通用 induction**：把带 `.git` 的产物首次纳入父仓跟踪时，hub 会临时把该产物的 `.git` 移到父仓 git admin 目录、
  `git add` 成文件 blob（非 gitlink）、再移回——因此父仓 clone 只得**文件、无嵌套 `.git`**，恢复时按清单重贴 remote。

  **`shared/plugins/manifest.toml`**（父仓跟踪，权威清单）：每插件一表——
  ```toml
  [<name>]
  platforms = ["claude", "codex"]   # 必填：该插件面向哪些平台
  [<name>.repository]               # 可选：声明为独立仓才要
  remote = "git@github.com:you/<name>.git"
  sha = "..."                       # 可选：钉住版本
  ```
  ```
  （追加的这段用 Edit 定位到常量末尾 `"""` 前插入，不要动其它章节。）

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_schema_md.py -q`。
- [ ] **Step 5: 提交** — `git add hub/schema_md.py tests/hub/test_schema_md.py && git commit -m "feat(hub): SCHEMA v3 contract text"`

---

## Task 4: 通用 induction 原语（hub/induction.py，prepare/execute 分离）

**Files:** Create `hub/induction.py`；Test `tests/hub/test_induction.py`。

**关键修正（对照审阅 gap 2）**：事务日志 + 暂存都放**父仓 git admin dir**（`git rev-parse --git-dir` →
通常 `parent/.git/hub-induction/`）——git 原生不跟踪、与工作树**同文件系统**（`os.replace` 目录不跨盘）；
**prepare/execute 分离**，dry-run 不移动；回滚用 `git reset -- <rel>` 回未跟踪态；stash 与原 `.git` **同时存在**
视为冲突。

**Interfaces (Produces):**
- `@dataclass InductionPlan(rel_target: str, has_nested_git: bool, gitdir: str)`
- `prepare_induction(parent_root, rel_target) -> InductionPlan` —— **纯只读**：解析 `git rev-parse --git-dir`、
  判断 `rel_target/.git` 是否存在（文件或目录）。容器逃逸（rel_target realpath 不在 parent 内）→ `InductionError`。
- `execute_induction(plan, parent_root, w) -> None` —— **唯一 dry-run 闸为 `w.dry_run`**；dry-run 打印计划、**不移动/不 add**；真跑执行
  「日志先落 → 移 `.git` 进 admin stash → `git add` → 验无 160000（否则 `git reset` 回滚 + 恢复 + 报错）→
  finally 恢复 `.git` → 验证 → 清日志」。
- `recover_pending(parent_root, w) -> list[str]` —— 读 admin 日志，把中断留在 stash 的 `.git` 贴回、验证、清日志；
  stash 与原 `.git` 同时存在 → `InductionError`。
- `InductionError(RuntimeError)`。

- [ ] **Step 1: 写失败测试（真 git，tmp，json.dumps 造记录）**

```python
# tests/hub/test_induction.py 新建
import json, os, subprocess
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.induction import (prepare_induction, execute_induction, recover_pending, InductionError)

def _git(cwd, *a): subprocess.run(["git","-C",str(cwd),*a], check=True, capture_output=True)
def _parent(tmp):
    p = tmp/"parent"; (p/"shared/plugins").mkdir(parents=True)
    subprocess.run(["git","init","-q",str(p)], check=True)
    _git(p,"config","user.email","t@t"); _git(p,"config","user.name","t"); return p
def _nested(parent, name, ver="0.1.0"):
    d = parent/"shared/plugins"/name; d.mkdir(parents=True)
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","n@n"); _git(d,"config","user.name","n")
    (d/"code.txt").write_text("v1\n", encoding="utf-8")
    (d/"plugin.json").write_text(json.dumps({"version":ver}), encoding="utf-8")
    _git(d,"add","-A"); _git(d,"commit","-qm","nested"); return d
def _idx(p, rel): return subprocess.run(["git","-C",str(p),"ls-files","-s",rel],
                                        capture_output=True,text=True).stdout
def _gitdir(p): return subprocess.run(["git","-C",str(p),"rev-parse","--git-dir"],
                                      capture_output=True,text=True).stdout.strip()

def test_induct_tracks_files_not_gitlink(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer())
    ls = _idx(p,"shared/plugins/foo")
    assert "160000" not in ls and "code.txt" in ls
    assert (p/"shared/plugins/foo/.git").exists()
    # 日志已清（admin dir 下无残留 journal）
    assert not (Path(p/_gitdir(p))/"hub-induction"/"journal.json").exists()

def test_nested_repo_still_alive(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer())
    r = subprocess.run(["git","-C",str(p/"shared/plugins/foo"),"log","--oneline"],
                       capture_output=True,text=True)
    assert r.returncode == 0 and "nested" in r.stdout

def test_dry_run_moves_nothing(tmp_path):
    p = _parent(tmp_path); _nested(p,"foo")
    execute_induction(prepare_induction(p,"shared/plugins/foo"), p, Writer(dry_run=True))
    assert (p/"shared/plugins/foo/.git").is_dir()          # 没被移动
    assert "160000" not in _idx(p,"shared/plugins/foo") and _idx(p,"shared/plugins/foo") == ""  # 没 add

def test_recover_pending(tmp_path):
    p = _parent(tmp_path); d = _nested(p,"foo")
    admin = Path(p/_gitdir(p))/"hub-induction"; (admin/"stash").mkdir(parents=True)
    os.replace(str(d/".git"), str(admin/"stash"/".git"))
    (admin/"journal.json").write_text(json.dumps(
        {"rel_target":"shared/plugins/foo","stash_git":str(admin/"stash"/".git")}), encoding="utf-8")
    done = recover_pending(p, Writer())
    assert "shared/plugins/foo" in done and (d/".git").exists()
    assert not (admin/"journal.json").exists()

def test_containment_escape_refused(tmp_path):
    p = _parent(tmp_path)
    with pytest.raises(InductionError):
        prepare_induction(p, "../outside")
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_induction.py -q`。

- [ ] **Step 3: 实现 hub/induction.py**

```python
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
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `git add hub/induction.py tests/hub/test_induction.py && git commit -m "feat(hub): crash-safe induction primitive (prepare/execute, admin-dir journal)"`

---

## Task 5: plugin manifest 解析 + 身份一致性（hub/plugin_manifest.py）

**Files:** Create `hub/plugin_manifest.py`；Test `tests/hub/test_plugin_manifest.py`。

**Interfaces (Produces):**
- `@dataclass PluginEntry(name: str, platforms: list[str], remote: str|None, sha: str|None)`
- `load_plugin_manifest(vault_root) -> list[PluginEntry]`（读 `shared/plugins/manifest.toml`；缺 `platforms` →
  `PluginManifestError`）
- `check_identity(vault_root, entry) -> None`（逐声明平台比对 5 处名全等 `entry.name`；否则 `PluginIdentityError`）
- `plugin_version(vault_root, name) -> str`（读 `.claude-plugin/plugin.json.version`）
- `PluginManifestError`/`PluginIdentityError`

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_plugin_manifest.py 新建
import json
import pytest
from pathlib import Path
from hub.plugin_manifest import (load_plugin_manifest, check_identity, plugin_version,
                                 PluginIdentityError, PluginManifestError)

def _plugin(vault, name, mkt=None, plug=None, ver="0.1.0"):
    d = vault/"shared/plugins"/name/".claude-plugin"; d.mkdir(parents=True)
    (d/"marketplace.json").write_text(json.dumps(
        {"name": mkt or name, "plugins":[{"name": plug or name, "source":".","description":"d"}]}),
        encoding="utf-8")
    (d/"plugin.json").write_text(json.dumps({"name": plug or name, "version": ver}), encoding="utf-8")

def _manifest(vault, body):
    (vault/"shared/plugins").mkdir(parents=True, exist_ok=True)
    (vault/"shared/plugins/manifest.toml").write_text(body, encoding="utf-8")

def test_load_version_identity_ok(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude","codex"]\n')
    _plugin(tmp_path, "cjt")
    e = load_plugin_manifest(tmp_path)[0]
    assert e.name=="cjt" and e.platforms==["claude","codex"] and e.remote is None
    check_identity(tmp_path, e)
    assert plugin_version(tmp_path, "cjt") == "0.1.0"

def test_platforms_required(tmp_path):
    _manifest(tmp_path, '[cjt]\n')      # 缺 platforms
    _plugin(tmp_path, "cjt")
    with pytest.raises(PluginManifestError):
        load_plugin_manifest(tmp_path)

def test_identity_mismatch(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms = ["claude"]\n')
    _plugin(tmp_path, "cjt", plug="WRONG")
    with pytest.raises(PluginIdentityError):
        check_identity(tmp_path, load_plugin_manifest(tmp_path)[0])

def test_remote_optional_repo(tmp_path):
    _manifest(tmp_path, '[cjt]\nplatforms=["claude"]\n[cjt.repository]\nremote="git@x"\n')
    _plugin(tmp_path, "cjt")
    assert load_plugin_manifest(tmp_path)[0].remote == "git@x"
```

- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现 hub/plugin_manifest.py**

```python
import json, tomllib
from dataclasses import dataclass
from pathlib import Path

class PluginManifestError(RuntimeError): pass
class PluginIdentityError(RuntimeError): pass

@dataclass
class PluginEntry:
    name: str; platforms: list[str]; remote: str | None; sha: str | None

def _mf_path(v): return Path(v)/"shared/plugins/manifest.toml"

def load_plugin_manifest(vault_root) -> list[PluginEntry]:
    p = _mf_path(vault_root)
    if not p.exists(): return []
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    out = []
    for name, body in raw.items():
        if "platforms" not in body:
            raise PluginManifestError(f"{name}: manifest 缺 platforms")
        repo = body.get("repository", {})
        out.append(PluginEntry(name, list(body["platforms"]),
                               repo.get("remote"), repo.get("sha")))
    return out

def _cp_dir(v, name): return Path(v)/"shared/plugins"/name/".claude-plugin"

def plugin_version(vault_root, name) -> str:
    return json.loads((_cp_dir(vault_root,name)/"plugin.json").read_text(encoding="utf-8"))["version"]

def check_identity(vault_root, entry: PluginEntry) -> None:
    n = entry.name
    cp = _cp_dir(vault_root, n)
    try:
        mkt = json.loads((cp/"marketplace.json").read_text(encoding="utf-8"))
        plug = json.loads((cp/"plugin.json").read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise PluginIdentityError(f"{n}: 缺 .claude-plugin 清单 ({e})")
    names = {"dir": n, "mkt": mkt.get("name"),
             "mkt_plugin": (mkt.get("plugins") or [{}])[0].get("name"),
             "plugin.json": plug.get("name")}
    bad = {k: v for k, v in names.items() if v != n}
    if bad:
        raise PluginIdentityError(f"{n}: 身份不一致 {bad}（须全等 {n}）")
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `feat(hub): plugin manifest parse + identity preflight`。

---

## Task 6: device.toml `[plugins.<tool>]` 启用策略

**Files:** Modify `hub/model.py`（`DeviceProfile.plugins: dict[str,list[str]]`）、`hub/vault.py`（`load_device`
解析）；Test `tests/hub/test_device_plugins.py`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_device_plugins.py 新建
from hub.vault import load_device
def test_device_plugins(tmp_path):
    (tmp_path/"box").mkdir()
    (tmp_path/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'
        '[plugins.claude]\nenabled=["cjt","xu-skills"]\n[plugins.codex]\nenabled=["cjt"]\n',
        encoding="utf-8")
    dev = load_device(tmp_path, "box")
    assert dev.plugins == {"claude":["cjt","xu-skills"], "codex":["cjt"]}

def test_device_no_plugins_section(tmp_path):
    (tmp_path/"box").mkdir()
    (tmp_path/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    assert load_device(tmp_path, "box").plugins == {}
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_device_plugins.py -q`（`TypeError`/`AttributeError`）。
- [ ] **Step 3: 实现**（两处字面编辑）：

  **`hub/model.py`** —— 在 `DeviceProfile` 数据类里，`sources` 字段后加一行（`field` 已 import；若无则补
  `from dataclasses import field`）：
  ```python
  @dataclass
  class DeviceProfile:
      host: str
      classes: list
      projects: list
      paths: dict
      sources: dict
      plugins: dict = field(default_factory=dict)      # 新增：{tool: [enabled plugin names]}
  ```

  **`hub/vault.py`** —— `load_device` 的返回值补一个 `plugins=`：
  ```python
  def load_device(root: Path, host: str) -> DeviceProfile:
      raw = tomllib.loads((root / host / "device.toml").read_text(encoding="utf-8"))
      return DeviceProfile(
          host=host,
          classes=list(raw.get("class", [])),
          projects=list(raw.get("projects", [])),
          paths=dict(raw.get("paths", {})),
          sources={k: _tool_sources(v) for k, v in raw.get("sources", {}).items()},
          plugins={t: list((v or {}).get("enabled", []))
                   for t, v in (raw.get("plugins") or {}).items()},   # 新增
      )
  ```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_device_plugins.py -q`。
- [ ] **Step 5: 提交** — `git add hub/model.py hub/vault.py tests/hub/test_device_plugins.py && git commit -m "feat(hub): parse device.toml [plugins.<tool>] enabled allowlist"`

---

## Task 7: plugin-state 台账（hub/plugin_state.py，插件×平台）

**Files:** Create `hub/plugin_state.py`；Test `tests/hub/test_plugin_state.py`。

**Interfaces (Produces):** `@dataclass Baseline(sha,version)`；`state_path()`（`HUB_HOME/plugin-state.toml`）；
`read_state() -> dict[str, dict[str, Baseline]]`；`record(name,tool,sha,version,w)`（原子读改写，只动该格）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_plugin_state.py 新建
from hub.writer import Writer
from hub.plugin_state import read_state, record
def test_per_plugin_per_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    record("cjt","claude","aaa","0.1.0", Writer())
    record("cjt","codex","bbb","0.1.0", Writer())
    st = read_state()
    assert st["cjt"]["claude"].sha=="aaa" and st["cjt"]["codex"].sha=="bbb"
    record("cjt","claude","ccc","0.2.0", Writer())
    st = read_state()
    assert st["cjt"]["claude"].version=="0.2.0" and st["cjt"]["codex"].sha=="bbb"  # codex 不动
def test_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    assert read_state() == {}
```

- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**

```python
import os, tomllib
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

@dataclass
class Baseline: sha: str; version: str

def state_path() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home()/".hub")) / "plugin-state.toml"

def read_state() -> dict:
    p = state_path()
    if not p.exists(): return {}
    raw = tomllib.loads(p.read_text(encoding="utf-8")).get("plugins", {})
    return {n: {t: Baseline(b["sha"], b["version"]) for t, b in tools.items()}
            for n, tools in raw.items()}

def record(name, tool, sha, version, w: Writer) -> None:
    st = read_state()
    st.setdefault(name, {})[tool] = Baseline(sha, version)
    lines = []
    for n, tools in sorted(st.items()):
        for t, b in sorted(tools.items()):
            lines.append(f'[plugins.{n}.{t}]\nsha = "{b.sha}"\nversion = "{b.version}"\n')
    w.write_text_atomic(state_path(), "\n".join(lines))
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `feat(hub): per-plugin-per-tool state ledger`。

---

## Task 8: 平台 CLI runner + 查询（hub/plugin_cli.py）

**Files:** Create `hub/plugin_cli.py`；Test `tests/hub/test_plugin_cli.py`。

**Interfaces (Produces)（对照 gap 5 补齐）:**
- `@dataclass CliCommand(tool, argv)`；`describe()` → `"<tool> <argv...>"`。
- `@dataclass CliResult(returncode, stdout, stderr)`。
- `run_cli(cmd, runner=None) -> CliResult`（默认 subprocess；测试注入 runner）。
- `preflight_cli(tool, needed: list[str], runner=None)` —— 确认 `<tool> plugin --help` 与 `<tool> plugin
  marketplace --help` 列出 `needed` 子命令；缺 → `CliUnavailable`。
- `@dataclass Installed(version, enabled, marketplace, source_path)`。
- `installed_plugins(tool, runner=None) -> dict[str, Installed]`（键 `<name>@<market>`）——Claude 解析
  `plugin list --json`（数组）；Codex 解析 `.installed[]`（`pluginId/version/enabled/marketplaceName/source.path`）。
- `marketplaces(tool, runner=None) -> dict[str, str]`（name→source 路径）——Claude `marketplace list --json`
  取 `path` 缺则 `installLocation`；Codex `marketplace list --json` 取 `.marketplaces[].root`。
- `CliUnavailable(RuntimeError)`。

- [ ] **Step 1: 写失败测试（注入假 runner，含两平台真实 JSON 形状）**

```python
# tests/hub/test_plugin_cli.py 新建
import json
import pytest
import hub.plugin_cli as plugin_cli
from hub.plugin_cli import (CliCommand, CliResult, run_cli, installed_plugins, marketplaces)

CLAUDE_LIST = json.dumps([{"id":"cjt@cjt","version":"0.1.0","scope":"user","enabled":True,
                           "installPath":"x"}])
CLAUDE_MKT = json.dumps([{"name":"cjt","source":"directory","path":"P","installLocation":"P"}])
CODEX_LIST = json.dumps({"installed":[{"pluginId":"cjt@cjt","name":"cjt","marketplaceName":"cjt",
                          "version":"0.2.0","enabled":True,"source":{"source":"local","path":"Q"}}],
                          "available":[]})
CODEX_MKT = json.dumps({"marketplaces":[{"name":"cjt","root":"Q"}]})
def runner(argv):
    key = " ".join(argv)
    return CliResult(0, {"claude plugin list --json": CLAUDE_LIST,
        "claude plugin marketplace list --json": CLAUDE_MKT,
        "codex plugin list --json": CODEX_LIST,
        "codex plugin marketplace list --json": CODEX_MKT}.get(key, "ok"), "")

def test_run_cli_uses_runner():
    assert run_cli(CliCommand("codex",["plugin","add","cjt@cjt"]), runner=runner).returncode == 0
def test_installed_claude():
    i = installed_plugins("claude", runner=runner)["cjt@cjt"]
    assert i.version=="0.1.0" and i.enabled is True and i.marketplace=="cjt"
def test_installed_codex():
    i = installed_plugins("codex", runner=runner)["cjt@cjt"]
    assert i.version=="0.2.0" and i.enabled is True and i.source_path=="Q"
def test_marketplaces_both():
    assert marketplaces("claude", runner=runner)["cjt"]=="P"
    assert marketplaces("codex", runner=runner)["cjt"]=="Q"
def test_missing_executable_becomes_cli_unavailable(monkeypatch):
    from hub.plugin_cli import CliUnavailable
    monkeypatch.setattr(plugin_cli.subprocess,"run",
                        lambda *a,**k: (_ for _ in ()).throw(FileNotFoundError("missing")))
    with pytest.raises(CliUnavailable):
        run_cli(CliCommand("claude",["plugin","--help"]))
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_cli.py -q`。
- [ ] **Step 3: 实现 hub/plugin_cli.py**

```python
import json, subprocess
from dataclasses import dataclass

class CliUnavailable(RuntimeError): pass

@dataclass
class CliCommand:
    tool: str
    argv: list
    def describe(self) -> str:
        return f"{self.tool} " + " ".join(self.argv)

@dataclass
class CliResult:
    returncode: int
    stdout: str
    stderr: str

@dataclass
class Installed:
    version: str
    enabled: bool
    marketplace: str
    source_path: str

def run_cli(cmd: CliCommand, runner=None) -> CliResult:
    if runner is not None:
        return runner([cmd.tool, *cmd.argv])          # 注入假 runner：收 [tool, *argv]
    try:
        p = subprocess.run([cmd.tool, *cmd.argv], capture_output=True, text=True)
    except OSError as e:
        raise CliUnavailable(f"{cmd.tool} CLI 不可执行: {e}") from e
    return CliResult(p.returncode, p.stdout, p.stderr)

def _json(tool, argv, runner):
    r = run_cli(CliCommand(tool, argv), runner=runner)
    if r.returncode != 0:
        raise CliUnavailable(f"{tool} {' '.join(argv)} 失败: {r.stderr.strip() or r.returncode}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise CliUnavailable(f"{tool} {' '.join(argv)} 未返回合法 JSON: {e}") from e

def installed_plugins(tool, runner=None) -> dict:
    data = _json(tool, ["plugin", "list", "--json"], runner)
    out = {}
    if tool == "claude":                              # [{id,version,enabled,scope,installPath}]
        for p in data:
            _, _, mkt = p["id"].partition("@")
            out[p["id"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                     mkt, p.get("installPath", ""))
    else:                                             # {installed:[{pluginId,version,enabled,marketplaceName,source{path}}]}
        for p in data.get("installed", []):
            out[p["pluginId"]] = Installed(p.get("version", ""), bool(p.get("enabled", True)),
                                           p.get("marketplaceName", ""),
                                           (p.get("source") or {}).get("path", ""))
    return out

def marketplaces(tool, runner=None) -> dict:
    data = _json(tool, ["plugin", "marketplace", "list", "--json"], runner)
    if tool == "claude":                              # [{name,source,path,installLocation}]
        return {m["name"]: (m.get("path") or m.get("installLocation", "")) for m in data}
    return {m["name"]: m.get("root", "") for m in data.get("marketplaces", [])}  # codex

def preflight_cli(tool, needed, runner=None) -> None:
    plug = run_cli(CliCommand(tool, ["plugin", "--help"]), runner=runner)
    mkt = run_cli(CliCommand(tool, ["plugin", "marketplace", "--help"]), runner=runner)
    if plug.returncode != 0 or mkt.returncode != 0:
        raise CliUnavailable(f"{tool} plugin CLI 不可用（缺失或不认子命令）")
    have = plug.stdout + mkt.stdout
    for sub in needed:
        if sub not in have:
            raise CliUnavailable(f"{tool} plugin 缺子命令 `{sub}`")
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_plugin_cli.py -q`。
- [ ] **Step 5: 提交** — `git add hub/plugin_cli.py tests/hub/test_plugin_cli.py && git commit -m "feat(hub): platform plugin CLI runner + JSON queries"`

---

## Task 9: 统一 PluginPlan（含依赖）+ 执行器（hub/plugin_ops.py 骨架）

**Files:** Create `hub/plugin_ops.py`（数据类 + `execute_plugin_plan`）；Test `tests/hub/test_plugin_exec.py`。

**关键修正（gap 3）**：`PluginAction` 带 `id` + `depends_on`；执行器按顺序跑，**任一依赖 failed/skipped → 本
action 记 skipped**（不执行、不写台账）。

**Interfaces (Produces):**
- `@dataclass PluginAction(id, describe, depends_on=(), cli=None, state=None)`（`cli:CliCommand|None`；
  `state:(name,tool,sha,version)|None`——台账写，依赖其前置 cli 成功）。
- `@dataclass PluginPlan(actions: list[PluginAction], warnings: list[str])`。
- `@dataclass PluginRunReport(succeeded, skipped, failed)`（failed: `list[(id,reason)]`）。
- `execute_plugin_plan(plan, w, runner=None) -> PluginRunReport`（**唯一 dry-run 闸为 `w.dry_run`**；dry-run 打印 describe+CLI，不跑不写；
  真跑：依赖不满足→skip；cli 成功→succeeded、失败→failed；state action 依赖满足→`plugin_state.record`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_plugin_exec.py 新建
from hub.writer import Writer
from hub.plugin_cli import CliCommand, CliResult
from hub.plugin_ops import PluginAction, PluginPlan, execute_plugin_plan
from hub.plugin_state import read_state

ok = lambda argv: CliResult(0,"ok","")
def fail_add(argv): return CliResult(1,"","boom") if argv[:2]==["plugin","add"] else CliResult(0,"ok","")

def _chain():
    return PluginPlan([
        PluginAction("add","codex plugin add cjt@cjt", cli=CliCommand("codex",["plugin","add","cjt@cjt"])),
        PluginAction("state","ledger cjt/codex", depends_on=("add",), state=("cjt","codex","sha","0.1.0")),
    ], [])

def test_dryrun_zero_side_effects(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    execute_plugin_plan(_chain(), Writer(dry_run=True), runner=ok)
    assert "cjt@cjt" in capsys.readouterr().out and read_state()=={}

def test_dep_blocks_state_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    rep = execute_plugin_plan(_chain(), Writer(), runner=fail_add)
    assert ("add" in [f[0] for f in rep.failed]) and "state" in rep.skipped
    assert read_state()=={}                          # 前置失败→不写台账

def test_success_writes_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    execute_plugin_plan(_chain(), Writer(), runner=ok)
    assert read_state()["cjt"]["codex"].version=="0.1.0"

def test_state_write_failure_reported_not_raised(tmp_path, monkeypatch):
    import hub.plugin_ops as ops
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    monkeypatch.setattr(ops,"record",lambda *a,**k: (_ for _ in ()).throw(OSError("disk full")))
    rep=execute_plugin_plan(_chain(),Writer(),runner=ok)
    assert "add" in rep.succeeded
    assert rep.failed==[("state","disk full")]

def test_unknown_or_not_yet_satisfied_dependency_skips():
    plan=PluginPlan([PluginAction("danger","must not run",depends_on=("missing",),
                                  cli=CliCommand("codex",["plugin","remove","x@x"]))],[])
    rep=execute_plugin_plan(plan,Writer(),runner=ok)
    assert rep.skipped==["danger"] and not rep.succeeded
```

- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现**

```python
from dataclasses import dataclass, field
from pathlib import Path
from hub.plugin_cli import run_cli
from hub.plugin_state import record
from hub.writer import Writer

@dataclass
class PluginAction:
    id: str; describe: str; depends_on: tuple = ()
    cli: object = None; state: tuple = None

@dataclass
class PluginPlan:
    actions: list; warnings: list

@dataclass
class PluginRunReport:
    succeeded: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)

def execute_plugin_plan(plan: PluginPlan, w: Writer, runner=None) -> PluginRunReport:
    rep = PluginRunReport()
    if w.dry_run:
        for a in plan.actions:
            print(f"  [plan] {a.describe}" + (f"  $ {a.cli.tool} {' '.join(a.cli.argv)}" if a.cli else ""))
        return rep
    for a in plan.actions:
        if any(d not in rep.succeeded for d in a.depends_on):
            rep.skipped.append(a.id); continue
        try:
            if a.cli is not None:
                r = run_cli(a.cli, runner=runner)
                if r.returncode != 0:
                    rep.failed.append((a.id, r.stderr.strip() or f"exit {r.returncode}"))
                    continue
            if a.state is not None:
                record(*a.state, w)
            rep.succeeded.append(a.id)
        except Exception as e:
            rep.failed.append((a.id,str(e)))
    return rep
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `feat(hub): PluginPlan with action deps + single executor gate`。

---

## Task 10: register 插件规划（prepare_plugin_register）

**Files:** Modify `hub/plugin_ops.py`；Test `tests/hub/test_plugin_register.py`。

**Interfaces:** `prepare_plugin_register(vault_root, dev, runner=None) -> PluginPlan`（**纯只读**）。确定性预检：
`require_version_exactly(vault_root,3)`；每声明平台 `preflight_cli`；每插件 `check_identity` + containment。
规划（分平台，依 `dev.plugins[tool]` 允许列表 + `installed_plugins`/`marketplaces` 现状；用 `depends_on` 串链）：
- 市场：source 已对→跳；source 不符→Codex `marketplace remove`+`add`、Claude `marketplace add`。
- 允许列表内、未装：Claude `install --scope user`+`enable`（enable 依赖 install）；Codex `add`。
- 允许列表外、已装：**Claude 只 `disable`（不卸载）**；Codex `remove`。列表外未装：不动。

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_register.py**

```python
import json
import pytest
from pathlib import Path
from hub.plugin_cli import CliResult
from hub.plugin_ops import prepare_plugin_register, PluginContainmentError
from hub.plugin_manifest import PluginIdentityError

def _setup(tmp, entries, plugins, ver="0.1.0", identity_ok=True):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    body = ""
    for name, plats in entries.items():
        body += f'[{name}]\nplatforms = {json.dumps(plats)}\n'
        cp = tmp/"shared/plugins"/name/".claude-plugin"; cp.mkdir(parents=True)
        pn = "WRONG" if (not identity_ok and name == "cjt") else name
        (cp/"marketplace.json").write_text(json.dumps(
            {"name": name, "plugins":[{"name": pn, "source":".","description":"d"}]}), encoding="utf-8")
        (cp/"plugin.json").write_text(json.dumps({"name": pn, "version": ver}), encoding="utf-8")
    (tmp/"shared/plugins/manifest.toml").write_text(body, encoding="utf-8")
    (tmp/"box").mkdir()
    dev_plugins = "".join(f'[plugins.{t}]\nenabled={json.dumps(v)}\n' for t, v in plugins.items())
    (tmp/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dev_plugins, encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp, "box")

HELP = "install uninstall enable disable add remove marketplace list"
def make_runner(mkts_claude=None, mkts_codex=None, inst_claude=None, inst_codex=None):
    def runner(argv):
        s = " ".join(argv)
        if s.endswith("--help"): return CliResult(0, HELP, "")
        if s == "claude plugin marketplace list --json": return CliResult(0, json.dumps(mkts_claude or []), "")
        if s == "codex plugin marketplace list --json": return CliResult(0, json.dumps({"marketplaces": mkts_codex or []}), "")
        if s == "claude plugin list --json": return CliResult(0, json.dumps(inst_claude or []), "")
        if s == "codex plugin list --json": return CliResult(0, json.dumps({"installed": inst_codex or [], "available": []}), "")
        return CliResult(0, "ok", "")
    return runner
def _ids(plan): return [a.id for a in plan.actions]

def test_no_manifest_empty_plan(tmp_path):
    (tmp_path/"vault.toml").write_text("version = 2\n", encoding="utf-8")  # 无 manifest：不要求 v3
    (tmp_path/"box").mkdir(); (tmp_path/"box"/"device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    from hub.vault import load_device
    plan = prepare_plugin_register(tmp_path, load_device(tmp_path,"box"), runner=make_runner())
    assert plan.actions == []

def test_allowlist_inside_not_installed_installs(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]})
    plan = prepare_plugin_register(tmp_path, dev, runner=make_runner())
    ids = _ids(plan)
    assert "cjt:claude:mktadd" in ids
    assert "cjt:claude:install" in ids
    assert "cjt:claude:enable" in ids
    enable = next(a for a in plan.actions if a.id == "cjt:claude:enable")
    assert enable.depends_on == ("cjt:claude:install",)
    assert enable.cli.argv[-2:] == ["--scope", "user"]

def test_allowlist_outside_installed_disables_not_uninstalls(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":[]})
    src = str((tmp_path/"shared/plugins/cjt").resolve())
    runner = make_runner(mkts_claude=[{"name":"cjt","path":src}],
        inst_claude=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"x"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner)
    ids = _ids(plan)
    assert "cjt:claude:disable" in ids and not any("install" in i for i in ids)
    disable = next(a for a in plan.actions if a.id == "cjt:claude:disable")
    assert disable.cli.argv[-2:] == ["--scope", "user"]

def test_codex_source_moved_remove_then_add(tmp_path):
    dev = _setup(tmp_path, {"cjt":["codex"]}, {"codex":["cjt"]})
    runner = make_runner(mkts_codex=[{"name":"cjt","root":"C:/old/path"}])
    plan = prepare_plugin_register(tmp_path, dev, runner=runner); ids = _ids(plan)
    assert ids.index("cjt:codex:mktrm") < ids.index("cjt:codex:mktadd")
    add = [a for a in plan.actions if a.id == "cjt:codex:mktadd"][0]
    assert "cjt:codex:mktrm" in add.depends_on

def test_identity_mismatch_raises(tmp_path):
    dev = _setup(tmp_path, {"cjt":["claude"]}, {"claude":["cjt"]}, identity_ok=False)
    with pytest.raises(PluginIdentityError):
        prepare_plugin_register(tmp_path, dev, runner=make_runner())

def test_shared_plugins_container_escape_refused(tmp_path):
    import os
    outside=tmp_path/"outside"; cp=outside/"cjt/.claude-plugin"; cp.mkdir(parents=True)
    (cp/"marketplace.json").write_text(json.dumps(
        {"name":"cjt","plugins":[{"name":"cjt","source":".","description":"d"}]}),encoding="utf-8")
    (cp/"plugin.json").write_text(json.dumps({"name":"cjt","version":"0.1.0"}),encoding="utf-8")
    (outside/"manifest.toml").write_text('[cjt]\nplatforms=["claude"]\n',encoding="utf-8")
    (tmp_path/"shared").mkdir(); (tmp_path/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    try: os.symlink(outside,tmp_path/"shared/plugins",target_is_directory=True)
    except OSError: pytest.skip("本机无 symlink 权限")
    (tmp_path/"box").mkdir(); (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n[plugins.claude]\nenabled=["cjt"]\n',encoding="utf-8")
    from hub.vault import load_device
    with pytest.raises(PluginContainmentError):
        prepare_plugin_register(tmp_path,load_device(tmp_path,"box"),runner=make_runner())
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_register.py -q`。

- [ ] **Step 3: 实现**（追加到 `hub/plugin_ops.py`——共用 import/helper + `prepare_plugin_register`）

```python
import os
from pathlib import Path
from hub.vault import require_version_exactly
from hub.plugin_manifest import load_plugin_manifest, check_identity, plugin_version
from hub.plugin_cli import CliCommand, installed_plugins, marketplaces, preflight_cli

NEEDED = {"claude": ["install","uninstall","enable","disable","marketplace"],
          "codex":  ["add","remove","marketplace"]}

class PluginBumpNeeded(RuntimeError): pass
class PluginRepoDirty(RuntimeError): pass
class PluginContainmentError(RuntimeError): pass

def _plugin_source(vault_root, name) -> str:
    return str((Path(vault_root)/"shared"/"plugins"/name).resolve())

def _containment(vault_root, name) -> None:
    vault = Path(vault_root).resolve()
    expected = vault/"shared"/"plugins"
    base = Path(os.path.realpath(Path(vault_root)/"shared"/"plugins"))
    real = Path(os.path.realpath(Path(vault_root)/"shared"/"plugins"/name))
    if (base != expected or not base.is_dir() or not real.is_dir()
            or os.path.commonpath([str(real), str(base)]) != str(base)):
        raise PluginContainmentError(f"shared/plugins/{name} 不是金库内真实目录")

def _norm(p: str) -> str:
    p = p.replace("\\", "/")
    if p.startswith("//?/"): p = p[4:]
    return os.path.normcase(os.path.normpath(p))
def _same_path(a, b) -> bool: return _norm(a) == _norm(b)

def _market_actions(tool, name, src, mkts):
    cur = mkts.get(name)
    if cur is not None and _same_path(cur, src): return []
    add = PluginAction(f"{name}:{tool}:mktadd", f"{tool} 注册/换源市场 {name}",
                       cli=CliCommand(tool, ["plugin","marketplace","add", src]))
    if cur is None: return [add]
    if tool == "codex":                       # 拒绝同名换源 → remove + add
        rm = PluginAction(f"{name}:{tool}:mktrm", f"codex 移除旧市场 {name}",
                          cli=CliCommand("codex", ["plugin","marketplace","remove", name]))
        add.depends_on = (rm.id,)
        return [rm, add]
    return [add]                               # Claude 覆盖

def _ensure_installed_enabled(tool, name, pid, installed, dep_mkt):
    dep = (dep_mkt,) if dep_mkt else ()
    if tool == "codex":
        return [] if pid in installed else [PluginAction(f"{name}:codex:add",
            f"codex 安装启用 {pid}", depends_on=dep, cli=CliCommand("codex",["plugin","add",pid]))]
    if pid not in installed:
        install = PluginAction(f"{name}:claude:install", f"claude 安装 {pid}", depends_on=dep,
                cli=CliCommand("claude",["plugin","install",pid,"--scope","user"]))
        enable = PluginAction(f"{name}:claude:enable", f"claude 启用 {pid}",
                depends_on=(install.id,),
                cli=CliCommand("claude",["plugin","enable",pid,"--scope","user"]))
        return [install, enable]
    if not installed[pid].enabled:
        return [PluginAction(f"{name}:claude:enable", f"claude 启用 {pid}", depends_on=dep,
                cli=CliCommand("claude",["plugin","enable",pid,"--scope","user"]))]
    return []

def _ensure_disabled(tool, name, pid, installed):
    if pid not in installed: return []
    if tool == "codex":
        return [PluginAction(f"{name}:codex:remove", f"codex 移除 {pid}",
                cli=CliCommand("codex",["plugin","remove",pid]))]
    if installed[pid].enabled:
        return [PluginAction(f"{name}:claude:disable", f"claude 禁用 {pid}",
                cli=CliCommand("claude",["plugin","disable",pid,"--scope","user"]))]
    return []

def prepare_plugin_register(vault_root, dev, runner=None) -> PluginPlan:
    entries = load_plugin_manifest(vault_root)
    if not entries: return PluginPlan([], [])      # 未迁移：跳过、不要求 v3
    require_version_exactly(vault_root, 3)
    plats = sorted({p for e in entries for p in e.platforms})
    for tool in plats: preflight_cli(tool, NEEDED[tool], runner=runner)
    snap = {t: (installed_plugins(t, runner=runner), marketplaces(t, runner=runner)) for t in plats}
    actions = []
    for e in entries:
        _containment(vault_root, e.name); check_identity(vault_root, e)
        src = _plugin_source(vault_root, e.name)
        for tool in e.platforms:
            installed, mkts = snap[tool]; pid = f"{e.name}@{e.name}"
            macts = _market_actions(tool, e.name, src, mkts); actions += macts
            dep = macts[-1].id if macts else None
            if e.name in dev.plugins.get(tool, []):
                actions += _ensure_installed_enabled(tool, e.name, pid, installed, dep)
            else:
                actions += _ensure_disabled(tool, e.name, pid, installed)
    return PluginPlan(actions, [])
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_plugin_register.py -q`。
- [ ] **Step 5: 提交** — `git add hub/plugin_ops.py tests/hub/test_plugin_register.py && git commit -m "feat(hub): prepare_plugin_register -> PluginPlan"`

---

## Task 11: refresh 插件规划（prepare_plugin_refresh，四态 + 恢复 disabled）

**Files:** Modify `hub/plugin_ops.py`；Test `tests/hub/test_plugin_refresh.py`。

**Interfaces:** `prepare_plugin_refresh(vault_root, dev, runner=None) -> PluginPlan`。规则（每插件×平台）：
- `require_version_exactly(3)`；**先读该平台 `installed_plugins`；未装→跳过（绝不安装）**。
- 读 `shared/plugins/<name>` HEAD sha + `plugin_version()`，对台账四态：无台账→**首次重读后**建基线（已安装插件
  原地重装，不新增安装）；SHA 未变→no-op；SHA 变&version 变→重装链；**SHA 变&version 未变→
  `PluginBumpNeeded`**；**仓 dirty→`PluginRepoDirty`**；`.git` 缺失/损坏→`PluginRepoUnavailable`
  （needs restore，绝不拿空 SHA 建基线）。
- 重装链（带 `depends_on`，末条成功后写 state）：
  - Codex：`add <n>@<n>` → state。
  - Claude：`uninstall <n>@<n> --keep-data --scope user` → `install <n>@<n> --scope user` →（**若刷新前 enabled 为
    false**）`disable <n>@<n>` → state。（保持启用策略；reinstall 会重新 enable，故 disabled 需恢复。）

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_refresh.py**

```python
import json, subprocess
from pathlib import Path
import pytest
from hub.writer import Writer
from hub.plugin_cli import CliResult
from hub.plugin_ops import (prepare_plugin_refresh, PluginBumpNeeded, PluginRepoDirty,
                            PluginRepoUnavailable)
from hub.plugin_state import record

def _git(cwd,*a): subprocess.run(["git","-C",str(cwd),*a], check=True, capture_output=True)
def _setup(tmp, name, ver, platforms):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    d = tmp/"shared/plugins"/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}), encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":name,"version":ver}), encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t")
    _git(d,"add","-A"); _git(d,"commit","-qm","c")
    (tmp/"shared/plugins/manifest.toml").write_text(f'[{name}]\nplatforms={json.dumps(platforms)}\n', encoding="utf-8")
    (tmp/"box").mkdir(); (tmp/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n', encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box"), d
def _head(d): return subprocess.run(["git","-C",str(d),"rev-parse","HEAD"], capture_output=True, text=True).stdout.strip()
def _bump(d, ver):
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":d.name,"version":ver}), encoding="utf-8")
    _git(d,"add","-A"); _git(d,"commit","-qm","bump")
def _runner(codex=None, claude=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="codex plugin list --json": return CliResult(0, json.dumps({"installed":codex or [],"available":[]}),"")
        if s=="claude plugin list --json": return CliResult(0, json.dumps(claude or []),"")
        if "codex" in s and s.endswith("marketplace list --json"): return CliResult(0, json.dumps({"marketplaces":[]}),"")
        if s.endswith("marketplace list --json"): return CliResult(0, "[]","")
        return CliResult(0,"ok","")
    return r
def _ids(p): return [a.id for a in p.actions]
_CI = [{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,"marketplaceName":"cjt","source":{"path":"x"}}]

def test_not_installed_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,_ = _setup(tmp_path,"cjt","0.2.0",["codex"])
    assert prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=[])).actions == []

def test_no_baseline_rereads_then_records(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,_ = _setup(tmp_path,"cjt","0.1.0",["codex"])
    plan = prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))
    assert _ids(plan) == ["cjt:codex:reinstall", "cjt:codex:state"]
    state = plan.actions[-1]
    assert state.depends_on == ("cjt:codex:reinstall",)

def test_nongit_source_refused(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    shutil.rmtree(d/".git")
    with pytest.raises(PluginRepoUnavailable):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_bump_needed(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer())
    (d/"x.txt").write_text("c\n",encoding="utf-8"); _git(d,"add","-A"); _git(d,"commit","-qm","c2")  # sha 变 version 没变
    with pytest.raises(PluginBumpNeeded):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_dirty_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer())
    (d/"x.txt").write_text("dirty\n",encoding="utf-8")
    with pytest.raises(PluginRepoDirty):
        prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI))

def test_codex_reinstall_on_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["codex"])
    record("cjt","codex",_head(d),"0.1.0", Writer()); _bump(d,"0.2.0")
    ids=_ids(prepare_plugin_refresh(tmp_path, dev, runner=_runner(codex=_CI)))
    assert "cjt:codex:reinstall" in ids and "cjt:codex:state" in ids

def test_claude_disabled_restored(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    dev,d = _setup(tmp_path,"cjt","0.1.0",["claude"])
    record("cjt","claude",_head(d),"0.1.0", Writer()); _bump(d,"0.2.0")
    ci=[{"id":"cjt@cjt","version":"0.1.0","enabled":False,"installPath":"x"}]
    ids=_ids(prepare_plugin_refresh(tmp_path, dev, runner=_runner(claude=ci)))
    assert ids[:3]==["cjt:claude:uninstall","cjt:claude:install","cjt:claude:redisable"]
    assert "cjt:claude:state" in ids
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_refresh.py -q`。

- [ ] **Step 3: 实现**（追加到 `hub/plugin_ops.py`——顶部补 `import subprocess` 与
  `from hub.plugin_state import read_state`）

```python
class PluginRepoUnavailable(RuntimeError): pass

def _git_text(src, *argv) -> str:
    r = subprocess.run(["git","-C",str(src),*argv], capture_output=True, text=True)
    if r.returncode != 0:
        raise PluginRepoUnavailable(
            f"{src} 不是可用的嵌套 git 仓（需要 restore/rehydrate）：{r.stderr.strip()}")
    return r.stdout.strip()

def _head_sha(src) -> str:
    return _git_text(src, "rev-parse", "HEAD")

def _is_dirty(src) -> bool:
    return bool(_git_text(src, "status", "--porcelain"))

def _reinstall_chain(tool, name, pid, inst, head, version):
    if tool == "codex":
        a = PluginAction(f"{name}:codex:reinstall", f"codex 重装 {pid}",
                         cli=CliCommand("codex",["plugin","add",pid]))
        return [a, PluginAction(f"{name}:codex:state", f"台账 {name}/codex",
                                depends_on=(a.id,), state=(name,"codex",head,version))]
    u = PluginAction(f"{name}:claude:uninstall", f"claude 卸载 {pid}",
                     cli=CliCommand("claude",["plugin","uninstall",pid,"--keep-data","--scope","user"]))
    i = PluginAction(f"{name}:claude:install", f"claude 重装 {pid}", depends_on=(u.id,),
                     cli=CliCommand("claude",["plugin","install",pid,"--scope","user"]))
    chain, last = [u, i], i.id
    if not inst.enabled:                       # reinstall 会重新 enable → 恢复 disabled
        d = PluginAction(f"{name}:claude:redisable", f"claude 恢复禁用 {pid}", depends_on=(i.id,),
                         cli=CliCommand("claude",["plugin","disable",pid,"--scope","user"]))
        chain.append(d); last = d.id
    chain.append(PluginAction(f"{name}:claude:state", f"台账 {name}/claude",
                              depends_on=(last,), state=(name,"claude",head,version)))
    return chain

def prepare_plugin_refresh(vault_root, dev, runner=None) -> PluginPlan:
    entries = load_plugin_manifest(vault_root)
    if not entries: return PluginPlan([], [])
    require_version_exactly(vault_root, 3)
    ledger = read_state()
    plats = sorted({p for e in entries for p in e.platforms})
    for tool in plats: preflight_cli(tool, NEEDED[tool], runner=runner)
    snap = {t: installed_plugins(t, runner=runner) for t in plats}
    actions = []
    for e in entries:
        _containment(vault_root, e.name)
        check_identity(vault_root, e)
        src = _plugin_source(vault_root, e.name)
        for tool in e.platforms:
            installed = snap[tool]; pid = f"{e.name}@{e.name}"
            if pid not in installed: continue          # 未装→跳过（refresh 不装）
            if _is_dirty(src): raise PluginRepoDirty(f"仓 {e.name} 未提交，先提交你的 bump")
            head = _head_sha(src); version = plugin_version(vault_root, e.name)
            base = ledger.get(e.name, {}).get(tool)
            if base is None:
                # spec P5：首次不是“只记账”，必须让已安装平台真实重读一次，再建立基线。
                actions += _reinstall_chain(tool, e.name, pid, installed[pid], head, version)
                continue
            if base.sha == head: continue              # no-op
            if version == base.version:
                raise PluginBumpNeeded(
                    f"需 bump {e.name}({tool})：源码已变但 manifest 版本未升，先 bump+commit 再 refresh")
            actions += _reinstall_chain(tool, e.name, pid, installed[pid], head, version)
    return PluginPlan(actions, [])
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_plugin_refresh.py -q`。
- [ ] **Step 5: 提交** — `git add hub/plugin_ops.py tests/hub/test_plugin_refresh.py && git commit -m "feat(hub): prepare_plugin_refresh (cachebuster 4-state, preserve disabled)"`

---

## Task 12: status 插件健康（plugin_health）

**Files:** Modify `hub/plugin_ops.py`；Test `tests/hub/test_plugin_health.py`。

**Interfaces:** `@dataclass PluginHealth(name,tool,state)`；`plugin_health(vault_root, dev, runner=None) ->
list[PluginHealth]`（只读）。状态（spec P7）：`unregistered`（仅市场缺失）、`source-moved`、`enable-drift`
（列表 desired 与实际 enabled/installed 不符）、`stale`、`dirty`、`no-baseline`、`missing-source`、`drift`
（仅 manifest 有 remote 时）、`ok`。manifest 无钉 SHA → freshness 只对台账比。

**状态优先级（定死，单状态/条目，取首个命中）**：`missing-source` > `unregistered` > `source-moved` >
`enable-drift` > `dirty` > `no-baseline` > `stale` > `drift` > `ok`。

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_health.py**

```python
import json, subprocess
from pathlib import Path
from hub.writer import Writer
from hub.plugin_cli import CliResult
from hub.plugin_ops import plugin_health
from hub.plugin_state import record

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _base(tmp): (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8"); (tmp/"box").mkdir()
def _entry(tmp, name, git=False):
    d=tmp/"shared/plugins"/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}), encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(json.dumps({"name":name,"version":"0.1.0"}), encoding="utf-8")
    if git:
        subprocess.run(["git","init","-q",str(d)], check=True)
        _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")
    return str(d.resolve())
def _write(tmp, manifest, dev_plugins):
    (tmp/"shared/plugins").mkdir(parents=True, exist_ok=True)
    (tmp/"shared/plugins/manifest.toml").write_text(manifest, encoding="utf-8")
    (tmp/"box"/"device.toml").write_text('class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dev_plugins, encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box")
def _runner(mkts=None, inst=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="claude plugin marketplace list --json": return CliResult(0, json.dumps(mkts or []),"")
        if s=="claude plugin list --json": return CliResult(0, json.dumps(inst or []),"")
        if s=="codex plugin marketplace list --json": return CliResult(0, json.dumps({"marketplaces":[]}),"")
        if s=="codex plugin list --json": return CliResult(0, json.dumps({"installed":[],"available":[]}),"")
        return CliResult(0,"ok","")
    return r
def _one(hs,name,tool): return [h.state for h in hs if h.name==name and h.tool==tool][0]
MF='[cjt]\nplatforms=["claude"]\n'

def test_missing_source(tmp_path):
    _base(tmp_path)
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner()),"cjt","claude")=="missing-source"

def test_unregistered(tmp_path):
    _base(tmp_path); _entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[])),"cjt","claude")=="unregistered"

def test_enable_drift_desired_not_installed(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],inst=[])),"cjt","claude")=="enable-drift"

def test_outside_not_installed_ok(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=[]\n')
    assert _one(plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],inst=[])),"cjt","claude")=="ok"

def _ci(enabled=True):
    return [{"id":"cjt@cjt","version":"0.1.0","enabled":enabled,"installPath":"x"}]

def test_source_moved_beats_enable_drift(tmp_path):
    _base(tmp_path); _entry(tmp_path,"cjt")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":"C:/old"}],inst=[])),"cjt","claude")
    assert state=="source-moved"                 # 优先于“期望启用但未安装”

def test_dirty_beats_no_baseline(tmp_path):
    _base(tmp_path); src=_entry(tmp_path,"cjt",git=True)
    Path(src,"dirty.txt").write_text("x\n", encoding="utf-8")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":src}],inst=_ci())),"cjt","claude")
    assert state=="dirty"

def test_no_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=_entry(tmp_path,"cjt",git=True)
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":src}],inst=_ci())),"cjt","claude")
    assert state=="no-baseline"

def test_stale_when_sha_changed_without_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=Path(_entry(tmp_path,"cjt",git=True))
    head=subprocess.run(["git","-C",str(src),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0",Writer())
    (src/"code.txt").write_text("changed\n",encoding="utf-8")
    _git(src,"add","-A"); _git(src,"commit","-qm","change-without-bump")
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":str(src)}],inst=_ci())),"cjt","claude")
    assert state=="stale"

def test_remote_drift(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=Path(_entry(tmp_path,"cjt",git=True))
    _git(src,"remote","add","origin","git@actual/repo.git")
    head=subprocess.run(["git","-C",str(src),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0",Writer())
    manifest='[cjt]\nplatforms=["claude"]\n[cjt.repository]\nremote="git@expected/repo.git"\n'
    dev=_write(tmp_path, manifest, '[plugins.claude]\nenabled=["cjt"]\n')
    state=_one(plugin_health(tmp_path,dev,
        runner=_runner(mkts=[{"name":"cjt","path":str(src)}],inst=_ci())),"cjt","claude")
    assert state=="drift"

def test_ok_installed_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    _base(tmp_path); src=_entry(tmp_path,"cjt", git=True)
    head=subprocess.run(["git","-C",src,"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
    record("cjt","claude",head,"0.1.0", Writer())
    dev=_write(tmp_path, MF, '[plugins.claude]\nenabled=["cjt"]\n')
    hs=plugin_health(tmp_path,dev,runner=_runner(mkts=[{"name":"cjt","path":src}],
        inst=[{"id":"cjt@cjt","version":"0.1.0","enabled":True,"installPath":"x"}]))
    assert _one(hs,"cjt","claude")=="ok"
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_health.py -q`。

- [ ] **Step 3: 实现**（追加到 `hub/plugin_ops.py`）

```python
from dataclasses import dataclass

@dataclass
class PluginHealth:
    name: str; tool: str; state: str

def _health_state(vault_root, dev, e, tool, installed, mkts, ledger) -> str:
    name = e.name; pid = f"{name}@{name}"
    src_dir = Path(vault_root)/"shared/plugins"/name
    try:
        _containment(vault_root, name)
    except PluginContainmentError:
        return "missing-source"                 # 缺失、坏链、逃逸链接都不是可用活源
    if name not in mkts: return "unregistered"
    if not _same_path(mkts[name], _plugin_source(vault_root, name)): return "source-moved"
    desired = name in dev.plugins.get(tool, [])
    present = pid in installed
    active = present and (installed[pid].enabled if tool == "claude" else True)
    if desired and not active: return "enable-drift"
    if not desired and present: return "enable-drift"
    if present:
        try:
            if _is_dirty(src_dir): return "dirty"
            head = _head_sha(src_dir)
        except PluginRepoUnavailable:
            return "missing-source"             # 父仓 clone 后尚未 rehydrate 的目录
        base = ledger.get(name, {}).get(tool)
        if base is None: return "no-baseline"
        if head != base.sha and plugin_version(vault_root, name) == base.version:
            return "stale"
    if e.remote:
        cur = subprocess.run(["git","-C",str(src_dir),"remote","get-url","origin"],
                             capture_output=True, text=True).stdout.strip()
        if (e.sha and _head_sha(src_dir) != e.sha) or cur != e.remote:
            return "drift"
    return "ok"

def plugin_health(vault_root, dev, runner=None) -> list:
    entries = load_plugin_manifest(vault_root)
    if not entries: return []
    require_version_exactly(vault_root, 3)
    ledger = read_state()
    plats = sorted({p for e in entries for p in e.platforms})
    snap = {t: (installed_plugins(t, runner=runner), marketplaces(t, runner=runner)) for t in plats}
    out = []
    for e in entries:
        for tool in e.platforms:
            installed, mkts = snap[tool]
            out.append(PluginHealth(e.name, tool, _health_state(vault_root, dev, e, tool, installed, mkts, ledger)))
    return out
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_plugin_health.py -q`。
- [ ] **Step 5: 提交** — `git add hub/plugin_ops.py tests/hub/test_plugin_health.py && git commit -m "feat(hub): plugin_health read-only state check"`

---

## Task 13: CLI 集成 —— 全量 prepare→commit + 双 dry-run

**Files:** Modify `hub/cli.py`（`_cmd_register`/`_cmd_refresh`/`_cmd_status`）、`hub/status_report.py`；
Test `tests/hub/test_cli_plugin.py`。

**关键修正（gap 4）**：`_cmd_register` 改成 **prepare-all→commit-all**：先 `plan_register_skills` +
`plan_hub_memory_skill` + `prepare_memory_views` + **`prepare_plugin_register`**（全部确定性校验），**任一抛错则
零写入**；全过后再 `commit_*` + `execute_plugin_plan(plan, w)`（唯一 dry-run 闸在 `w`）。`_cmd_refresh` 同样
`prepare_plugin_refresh`→`execute_plugin_plan`。`status --check` 汇入 `plugin_health`，非 ok 计非零退出。

**测试注入点**：CLI 层调 `prepare_plugin_register/refresh(vault_root, dev)`（不传 runner=真 subprocess）。
测试 monkeypatch `hub.cli.prepare_plugin_register` 等为返回罐装 `PluginPlan`/抛错的桩，验接线顺序与零写，
不碰真平台。

- [ ] **Step 1: 写失败测试 tests/hub/test_cli_plugin.py**

```python
import pytest
from pathlib import Path
from hub import cli
from hub.plugin_ops import PluginAction, PluginPlan, PluginRunReport, PluginRepoDirty
from hub.plugin_cli import CliCommand
from hub.plugin_manifest import PluginIdentityError

def _vault(tmp):
    # 最小 v3 金库：device + 一条 shared 记忆，令 memory/skill 预检可跑
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    d=tmp/"shared/memory"; d.mkdir(parents=True)
    (d/"a.md").write_text("---\nname: a\ndescription: d\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nb\n", encoding="utf-8")
    (tmp/"box").mkdir()
    (tmp/"box"/"device.toml").write_text(
        f'class=[]\nprojects=[]\n[paths]\nCLAUDE_HOME="{(tmp/".claude").as_posix()}"\n', encoding="utf-8")
    return tmp

def test_register_dryrun_prints_plugin_cli_and_zero_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    plan=PluginPlan([PluginAction("a:codex:add","codex 安装 a@a", cli=CliCommand("codex",["plugin","add","a@a"]))],[])
    monkeypatch.setattr(cli, "prepare_plugin_register", lambda *a, **k: plan)
    rc=cli.main(["register","--vault",str(v),"--host","box","--dry-run"])
    out=capsys.readouterr().out
    assert rc==0 and "codex plugin add a@a" in out
    from hub.memwire import hub_views_home
    assert not (hub_views_home()/"claude"/"MEMORY.md").exists()      # dry-run 零写

def test_register_plugin_preflight_failure_zero_write(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    def boom(*a, **k): raise PluginIdentityError("bad identity")
    monkeypatch.setattr(cli, "prepare_plugin_register", boom)
    rc=cli.main(["register","--vault",str(v),"--host","box"])
    from hub.memwire import hub_views_home
    assert rc==1
    assert not (hub_views_home()/"claude"/"MEMORY.md").exists()      # 插件预检失败→memory/skill 也没写

def test_register_cli_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    monkeypatch.setattr(cli, "prepare_plugin_register", lambda *a, **k: PluginPlan([], []))
    monkeypatch.setattr(cli, "execute_plugin_plan",
        lambda *a, **k: PluginRunReport(failed=[("cjt:codex:add","boom")]))
    assert cli.main(["register","--vault",str(v),"--host","box"])==1

def test_refresh_plugin_preflight_failure_preserves_old_view(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    from hub.memwire import hub_views_home
    old=hub_views_home()/"claude"/"MEMORY.md"
    old.parent.mkdir(parents=True); old.write_text("OLD\n",encoding="utf-8")
    monkeypatch.setattr(cli, "prepare_plugin_refresh",
        lambda *a, **k: (_ for _ in ()).throw(PluginRepoDirty("dirty")))
    rc=cli.main(["refresh","--vault",str(v),"--host","box"])
    assert rc==1 and old.read_text(encoding="utf-8")=="OLD\n"

def test_status_check_lists_plugin_health(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_HOME", str(tmp_path/".hub"))
    v=_vault(tmp_path)
    from hub.plugin_ops import PluginHealth
    monkeypatch.setattr(cli, "plugin_health",
                        lambda *a, **k: [PluginHealth("a","codex","enable-drift")])
    rc=cli.main(["status","--vault",str(v),"--host","box","--check"])
    out=capsys.readouterr().out
    assert rc==1
    assert "[enable-drift] a@codex" in out
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_cli_plugin.py -q`。

- [ ] **Step 3: 实现**（编辑 `hub/cli.py`）

  **(a)** 顶部 import 追加：
  ```python
  from hub.plugin_ops import (prepare_plugin_register, prepare_plugin_refresh, execute_plugin_plan,
                              plugin_health, PluginBumpNeeded, PluginRepoDirty, PluginRepoUnavailable,
                              PluginContainmentError)
  from hub.plugin_manifest import PluginManifestError, PluginIdentityError
  from hub.plugin_cli import CliUnavailable
  from hub.vault import UnsupportedVaultVersion
  ```

  **(b)** `_cmd_register`——在 `prepare_memory_views` 后、任何 `commit_*` 前加 `prepare_plugin_register`（并入
  prepare 阶段）；在 `commit_memory_views` 后加 `execute_plugin_plan`；扩捕获异常并打印插件报告：
  ```python
  def _cmd_register(args) -> int:
      vault_root = Path(args.vault); host = args.host or current_host()
      w = Writer(dry_run=args.dry_run); hub_root = _hub_root()
      try:
          dev = load_device(vault_root, host)
          to_link, ensured = plan_register_skills(vault_root, dev)
          hm_links = plan_hub_memory_skill(hub_root, dev)
          check_link_collisions(to_link, hm_links)
          check_config(vault_root, host)
          writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
          plugin_plan = prepare_plugin_register(vault_root, dev)          # 预检并入 prepare
          commit_register_skills(to_link, w)
          commit_hub_memory_skill(hm_links, w)
          write_config(vault_root, host, hub_root, w)
          commit_memory_views(writes, oc_plan, w)
          prep = execute_plugin_plan(plugin_plan, w)                      # 提交期执行 CLI
      except (RegisterConflict, FileNotFoundError, LinkError, SharedSkillsEscape,
              ConfigConflict, ViewScopeError, SharedMemoryError, BlockError,
              PluginManifestError, PluginIdentityError, PluginContainmentError,
              CliUnavailable, UnsupportedVaultVersion) as e:
          print(e); return 1
      print(f"{'预计就位' if args.dry_run else '已就位'} {len(ensured)} 个 skill 链接 + hub-memory")
      for x in warnings: print("  ⚠", x)
      if plugin_plan.actions and not args.dry_run:
          print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
          for i, why in prep.failed: print(f"  ✗ {i}: {why}")
      return 0 if not prep.failed else 1
  ```

  **(c)** `_cmd_refresh`——必须和 register 一样先把 memory + plugin **全部 prepare 完**，再提交视图并执行 CLI；
  禁止先调用 `wire_memory_views` 写完视图才发现插件确定性错误：
  ```python
  def _cmd_refresh(args) -> int:
      vault_root = Path(args.vault); host = args.host or current_host()
      dry = getattr(args, "dry_run", False); w = Writer(dry_run=dry)
      try:
          dev = load_device(vault_root, host)
          writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
          plugin_plan = prepare_plugin_refresh(vault_root, dev)
          commit_memory_views(writes, oc_plan, w)
          prep = execute_plugin_plan(plugin_plan, w)
      except (FileNotFoundError, ViewScopeError, SharedMemoryError, BlockError,
              PluginBumpNeeded, PluginRepoDirty, PluginManifestError, PluginIdentityError,
              PluginRepoUnavailable, PluginContainmentError, CliUnavailable,
              UnsupportedVaultVersion) as e:
          print(e); return 1
      summary = {"written": len(writes), "warnings": warnings}
      print(f"memory 视图已重算: {summary}")
      for x in summary.get("warnings", []): print("  ⚠", x)
      if plugin_plan.actions and not dry:
          print(f"插件: 成功 {len(prep.succeeded)} / 未执行 {len(prep.skipped)} / 失败 {len(prep.failed)}")
      return 0 if not prep.failed else 1
  ```

  **(d)** `_cmd_status`——`--check` 分支汇入 `plugin_health`：在算 `vh` 后加
  ```python
          try:
              ph = plugin_health(vault_root, dev)
          except (PluginManifestError, PluginIdentityError, PluginContainmentError,
                  PluginRepoUnavailable, CliUnavailable, UnsupportedVaultVersion) as e:
              print(f"plugin status 停止: {e}")
              return 1
          if ph:
              print("插件:")
              for h in ph: print(f"  [{h.state}] {h.name}@{h.tool}")
          return 1 if (any(x[0] != "ok" for x in (rows + vh))
                       or any(h.state != "ok" for h in ph)) else 0
  ```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_cli_plugin.py -q`；再跑
  `py -3 -m pytest tests/hub/ -q` 确认未回归 Plan 1/2 的 register/refresh 测试。
- [ ] **Step 5: 提交** — `git add hub/cli.py tests/hub/test_cli_plugin.py && git commit -m "feat(hub): wire plugin register/refresh/status (prepare-all -> commit)"`

---

## Task 14a: 迁移输入解析 + 纯 planner（hub/plugin_migrate.py）

**Files:** Create `hub/plugin_migrate.py`（类型 + `load_migration_input` + `prepare_migration`）；Test
`tests/hub/test_plugin_migrate_plan.py`。

**关键修正（gap 7）**：**显式迁移输入**——作者写 `plugins-migration.toml`：`[<name>] platforms=[...]
enabled=[...]`（`enabled` = 该插件在哪些平台默认启用）。**不从安装态推断**。`prepare_migration` **纯只读**：产出
`MigrationPlan`，**不移动/不 induct/不写**。缺 market-of-one 的插件进 `needs_author`（**标注需作者补，不静默生成**）。

**Interfaces (Produces):**
```python
@dataclass
class MigrationAction:
    id: str; kind: str; describe: str            # kind ∈ {"move","induct","write"}
    src: str = ""; dest: str = ""; text: str = ""; depends_on: tuple = ()
@dataclass
class MigrationPlan:
    actions: list; warnings: list; needs_author: list
class MigrationInputError(RuntimeError): pass
def load_migration_input(path) -> dict            # {name: {"platforms":[...], "enabled":[...]}}
def prepare_migration(src_dir, vault_root, input_path) -> MigrationPlan
```

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_migrate_plan.py**

```python
import json, subprocess
from pathlib import Path
import pytest
from hub.plugin_migrate import prepare_migration, MigrationInputError

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _repo(src_dir, name, market=True):
    d=src_dir/name; d.mkdir(parents=True)
    if market:
        (d/".claude-plugin").mkdir()
        (d/".claude-plugin/marketplace.json").write_text(json.dumps(
            {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
        (d/".claude-plugin/plugin.json").write_text(
            json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    (d/"code.txt").write_text("v\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")

def test_prepare_is_pure(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt"); _repo(src,"tn", market=False)
    (tmp_path/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude","codex"]\nenabled=["claude","codex"]\n'
        '[tn]\nplatforms=["claude"]\nenabled=[]\n', encoding="utf-8")
    plan=prepare_migration(src, tmp_path, inp)
    kinds=[(a.kind,a.id) for a in plan.actions]
    assert ("move","cjt:move") in kinds and ("induct","cjt:induct") in kinds
    assert any(a.kind=="write" and "manifest" in a.id for a in plan.actions)
    assert "tn" in plan.needs_author                       # 缺 market-of-one → 标注
    # 纯：源仍在、目标未建
    assert (src/"cjt/.git").exists() and not (tmp_path/"shared/plugins/cjt").exists()
    # induct 依赖 move
    ind=[a for a in plan.actions if a.id=="cjt:induct"][0]
    assert "cjt:move" in ind.depends_on

def test_missing_platforms_raises(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nenabled=[]\n', encoding="utf-8")
    with pytest.raises(MigrationInputError):
        prepare_migration(src, tmp_path, inp)

def test_enabled_must_be_subset_of_platforms(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude"]\nenabled=["codex"]\n',encoding="utf-8")
    with pytest.raises(MigrationInputError):
        prepare_migration(src,tmp_path,inp)

def test_prepare_rerun_accepts_repo_already_moved(tmp_path):
    src=tmp_path/"plugins-dev"; src.mkdir()
    subprocess.run(["git","init","-q",str(tmp_path)],check=True)
    _repo(tmp_path/"shared/plugins","cjt")
    inp=tmp_path/"m.toml"; inp.write_text(
        '[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    plan=prepare_migration(src,tmp_path,inp)
    assert not any(a.id=="cjt:move" for a in plan.actions)
    assert any(a.id=="cjt:induct" for a in plan.actions)  # move 已完成但父仓未 add → 重跑从 induct 收敛
    assert any(a.id=="write:manifest" for a in plan.actions)
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_migrate_plan.py -q`。

- [ ] **Step 3: 实现 hub/plugin_migrate.py（本任务部分）**

```python
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
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `git add hub/plugin_migrate.py tests/hub/test_plugin_migrate_plan.py && git commit -m "feat(hub): migration input + pure planner"`

---

## Task 14b: 迁移执行器 —— 复制+校验+删源 + induction（hub/plugin_migrate.py）

**Files:** Modify `hub/plugin_migrate.py`（`execute_migration`）；Test `tests/hub/test_plugin_migrate_exec.py`。

**Interfaces:** `@dataclass MigrationReport(done, failed)`；`execute_migration(plan, vault_root, w) ->
MigrationReport`。**唯一 dry-run 闸为 `w.dry_run`**。`move`=`shutil.copytree(..., symlinks=True)`（含 `.git`、
保留链接、跨盘安全）+ 相对路径/类型/内容 SHA-256 清单校验 + `Writer.rmtree` 源；
`induct`=`execute_induction(prepare_induction(...))`；`write`=`Writer.write_text_atomic`。**强序列：任一失败即停**
（`break`）；`needs_author` 非空或依赖未完成时在首个动作前失败，零移动。源删除前 T15 runbook 已备份
plugins-dev，提交期失败可从备份恢复。

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_migrate_exec.py**

```python
import json, subprocess
from pathlib import Path
from hub.writer import Writer
from hub.plugin_migrate import prepare_migration, execute_migration

def _git(c,*a): subprocess.run(["git","-C",str(c),*a], check=True, capture_output=True)
def _repo(src, name):
    d=src/name; (d/".claude-plugin").mkdir(parents=True)
    (d/".claude-plugin/marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
    (d/".claude-plugin/plugin.json").write_text(
        json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    (d/"code.txt").write_text("v\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(d)], check=True)
    _git(d,"config","user.email","t@t"); _git(d,"config","user.name","t"); _git(d,"add","-A"); _git(d,"commit","-qm","c")
def _idx(p, rel): return subprocess.run(["git","-C",str(p),"ls-files","-s",rel], capture_output=True, text=True).stdout

def test_execute_moves_inducts(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)], check=True)
    _git(v,"config","user.email","t@t"); _git(v,"config","user.name","t")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    plan=prepare_migration(src, v, inp)
    rep=execute_migration(plan, v, Writer())
    assert not rep.failed
    assert not (src/"cjt").exists()                          # 源已删
    assert (v/"shared/plugins/cjt/.git").exists()            # 嵌套仓在
    assert "160000" not in _idx(v,"shared/plugins/cjt")      # 父仓跟踪文件非 gitlink
    assert (v/"shared/plugins/manifest.toml").read_text(encoding="utf-8").strip().startswith("[cjt]")

def test_dry_run_moves_nothing(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)], check=True)
    _git(v,"config","user.email","t@t"); _git(v,"config","user.name","t")
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=["claude"]\n', encoding="utf-8")
    execute_migration(prepare_migration(src,v,inp), v, Writer(dry_run=True))
    assert (src/"cjt").exists() and not (v/"shared/plugins/cjt").exists()

def test_needs_author_blocks_before_move(tmp_path):
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    (src/"cjt/.claude-plugin/marketplace.json").write_text("{}",encoding="utf-8")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)],check=True)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    rep=execute_migration(prepare_migration(src,v,inp),v,Writer())
    assert rep.failed and rep.failed[0][0]=="preflight:needs-author"
    assert (src/"cjt").exists() and not (v/"shared/plugins/cjt").exists()

def test_unmet_dependency_stops_before_action(tmp_path):
    from hub.plugin_migrate import MigrationAction, MigrationPlan
    v=tmp_path/"vault"; v.mkdir(); subprocess.run(["git","init","-q",str(v)],check=True)
    plan=MigrationPlan([MigrationAction("x:induct","induct","bad",dest="shared/plugins/x",
                                       depends_on=("x:move",))],[],[])
    rep=execute_migration(plan,v,Writer())
    assert rep.failed==[("x:induct","未满足依赖: x:move")]

def test_copy_verification_failure_keeps_source(tmp_path, monkeypatch):
    import hub.plugin_migrate as pm
    src=tmp_path/"plugins-dev"; _repo(src,"cjt")
    v=tmp_path/"vault"; v.mkdir(); (v/"vault.toml").write_text("version = 3\n",encoding="utf-8")
    subprocess.run(["git","init","-q",str(v)],check=True)
    inp=tmp_path/"m.toml"; inp.write_text('[cjt]\nplatforms=["claude"]\nenabled=[]\n',encoding="utf-8")
    real=pm._tree_manifest; calls={"n":0}
    def mismatch(path):
        calls["n"]+=1
        return real(path) if calls["n"]==1 else [("CORRUPT","file","0")]
    monkeypatch.setattr(pm,"_tree_manifest",mismatch)
    rep=execute_migration(prepare_migration(src,v,inp),v,Writer())
    assert rep.failed and (src/"cjt").exists()
    assert not (v/"shared/plugins/cjt").exists()
```

- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 实现（追加到 hub/plugin_migrate.py）**

```python
import hashlib, os, shutil
from dataclasses import dataclass, field
from hub.induction import prepare_induction, execute_induction

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
        shutil.rmtree(dest, ignore_errors=True)
        raise MigrationInputError(f"{src}→{dest} 复制校验失败（路径/类型/SHA-256 不同）")
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
```

- [ ] **Step 4: 运行通过。**
- [ ] **Step 5: 提交** — `git add hub/plugin_migrate.py tests/hub/test_plugin_migrate_exec.py && git commit -m "feat(hub): migration executor (copy+verify+rm source + induction)"`

---

## Task 14c: 平台 cutover planner/executor（hub/plugin_migrate.py）

**Files:** Modify `hub/plugin_migrate.py`（`prepare_cutover`）；Test `tests/hub/test_plugin_cutover.py`。

**Interfaces:** `prepare_cutover(vault_root, dev, runner=None, old_market="xu-local") -> PluginPlan`。先复用
`prepare_plugin_register` 规划新 market-of-one 与新身份，再补两类迁移专属动作：

1. **身份不变、source-moved（cjt 类）**：换源动作成功后强制重装当前 `<name>@<name>`；Claude 按当前
   device 策略在重装后 enable/disable，Codex 期望安装时重新 `add`，最后写该平台台账。
2. **身份变化（`<name>@xu-local` → `<name>@<name>`）**：新身份达到 device 期望态后，逐个 uninstall/remove
   旧身份；全部旧身份退役成功后才删除 `xu-local` 市场。发现 manifest 外的 `*@xu-local` 已装项时预检失败，
   绝不静默删市场。

执行仍复用 T9 `execute_plugin_plan(plan, w)`；所有依赖失败都会把后继标为 skipped。

- [ ] **Step 1: 写失败测试 tests/hub/test_plugin_cutover.py**

```python
import json, subprocess
from pathlib import Path
import pytest
from hub.plugin_cli import CliResult
from hub.plugin_migrate import prepare_cutover, MigrationInputError

def _git(c,*a): subprocess.run(["git","-C",str(c),*a],check=True,capture_output=True)

def _setup(tmp, name="cjt", platforms=("codex",), enabled_tools=("codex",)):
    (tmp/"vault.toml").write_text("version = 3\n", encoding="utf-8")
    root=tmp/"shared/plugins"/name; cp=root/".claude-plugin"; cp.mkdir(parents=True)
    (cp/"marketplace.json").write_text(json.dumps(
        {"name":name,"plugins":[{"name":name,"source":".","description":"d"}]}),encoding="utf-8")
    (cp/"plugin.json").write_text(json.dumps({"name":name,"version":"0.1.0"}),encoding="utf-8")
    subprocess.run(["git","init","-q",str(root)],check=True)
    _git(root,"config","user.email","t@t"); _git(root,"config","user.name","t")
    _git(root,"add","-A"); _git(root,"commit","-qm","initial")
    (tmp/"shared/plugins/manifest.toml").write_text(
        f'[{name}]\nplatforms={json.dumps(list(platforms))}\n',encoding="utf-8")
    (tmp/"box").mkdir()
    dp="".join(f'[plugins.{t}]\nenabled=["{name}"]\n' for t in enabled_tools)
    (tmp/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n'+dp,encoding="utf-8")
    from hub.vault import load_device
    return load_device(tmp,"box"), root

def _runner(codex_mkts=None, codex_inst=None, claude_mkts=None, claude_inst=None):
    def r(argv):
        s=" ".join(argv)
        if s.endswith("--help"): return CliResult(0,"install uninstall enable disable add remove marketplace list","")
        if s=="codex plugin marketplace list --json":
            return CliResult(0,json.dumps({"marketplaces":codex_mkts or []}),"")
        if s=="codex plugin list --json":
            return CliResult(0,json.dumps({"installed":codex_inst or [],"available":[]}),"")
        if s=="claude plugin marketplace list --json": return CliResult(0,json.dumps(claude_mkts or []),"")
        if s=="claude plugin list --json": return CliResult(0,json.dumps(claude_inst or []),"")
        return CliResult(0,"ok","")
    return r

def _ids(plan): return [a.id for a in plan.actions]

def test_old_identity_retired_only_after_new_identity_ready(tmp_path):
    dev,_=_setup(tmp_path)
    runner=_runner(
        codex_mkts=[{"name":"xu-local","root":"C:/old"}],
        codex_inst=[{"pluginId":"cjt@xu-local","version":"0.1.0","enabled":True,
                    "marketplaceName":"xu-local","source":{"path":"x"}}])
    plan=prepare_cutover(tmp_path,dev,runner=runner)
    ids=_ids(plan)
    assert "cjt:codex:add" in ids
    assert "cjt:codex:retire-old" in ids
    old=next(a for a in plan.actions if a.id=="cjt:codex:retire-old")
    assert "cjt:codex:add" in old.depends_on
    market=next(a for a in plan.actions if a.id=="codex:retire-market:xu-local")
    assert old.id in market.depends_on

def test_same_identity_source_move_forces_codex_reinstall(tmp_path):
    dev,_=_setup(tmp_path)
    installed=[{"pluginId":"cjt@cjt","version":"0.1.0","enabled":True,
                "marketplaceName":"cjt","source":{"path":"C:/old"}}]
    markets=[{"name":"cjt","root":"C:/old"}]
    plan=prepare_cutover(tmp_path,dev,runner=_runner(codex_mkts=markets,codex_inst=installed))
    reinstall=next(a for a in plan.actions if a.id=="cjt:codex:cutover-reinstall")
    assert reinstall.depends_on==("cjt:codex:mktadd",)
    assert reinstall.cli.argv==["plugin","add","cjt@cjt"]

def test_unknown_old_market_identity_blocks(tmp_path):
    dev,_=_setup(tmp_path)
    installed=[{"pluginId":"mystery@xu-local","version":"1","enabled":True,
                "marketplaceName":"xu-local","source":{"path":"x"}}]
    with pytest.raises(MigrationInputError):
        prepare_cutover(tmp_path,dev,runner=_runner(
            codex_mkts=[{"name":"xu-local","root":"C:/old"}],codex_inst=installed))

def test_cutover_requires_manifest(tmp_path):
    (tmp_path/"box").mkdir(parents=True)
    (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n',encoding="utf-8")
    from hub.vault import load_device
    with pytest.raises(MigrationInputError):
        prepare_cutover(tmp_path,load_device(tmp_path,"box"),runner=_runner())
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_plugin_cutover.py -q`。

- [ ] **Step 3: 实现（追加到 hub/plugin_migrate.py）**

```python
from hub.plugin_ops import (prepare_plugin_register, PluginAction, PluginPlan, _same_path,
                            _plugin_source, _head_sha)
from hub.plugin_manifest import load_plugin_manifest, plugin_version
from hub.plugin_cli import CliCommand, installed_plugins, marketplaces

def _drop_policy_actions(actions, name, tool):
    drop={f"{name}:{tool}:enable",f"{name}:{tool}:disable"}
    return [a for a in actions if a.id not in drop]

def _cutover_reinstall(tool, name, desired, inst, dep, vault_root):
    pid=f"{name}@{name}"; head=_head_sha(_plugin_source(vault_root,name))
    version=plugin_version(vault_root,name); deps=(dep,) if dep else ()
    if tool=="codex":
        if not desired: return []              # register 的 remove 已收敛“不安装”策略
        add=PluginAction(f"{name}:codex:cutover-reinstall",f"codex 换源后重装 {pid}",
            depends_on=deps,cli=CliCommand("codex",["plugin","add",pid]))
        state=PluginAction(f"{name}:codex:cutover-state",f"台账 {name}/codex",
            depends_on=(add.id,),state=(name,"codex",head,version))
        return [add,state]
    uninstall=PluginAction(f"{name}:claude:cutover-uninstall",f"claude 换源前卸载 {pid}",
        depends_on=deps,cli=CliCommand("claude",["plugin","uninstall",pid,"--keep-data","--scope","user"]))
    install=PluginAction(f"{name}:claude:cutover-install",f"claude 从新源重装 {pid}",
        depends_on=(uninstall.id,),cli=CliCommand("claude",["plugin","install",pid,"--scope","user"]))
    verb="enable" if desired else "disable"
    policy=PluginAction(f"{name}:claude:cutover-{verb}",f"claude 重装后{verb} {pid}",
        depends_on=(install.id,),cli=CliCommand("claude",["plugin",verb,pid,"--scope","user"]))
    state=PluginAction(f"{name}:claude:cutover-state",f"台账 {name}/claude",
        depends_on=(policy.id,),state=(name,"claude",head,version))
    return [uninstall,install,policy,state]

def _ready_dep(actions, name, tool):
    prefix=f"{name}:{tool}:"
    preferred=("cutover-enable","cutover-reinstall","enable","add")
    for verb in preferred:
        found=[a.id for a in actions if a.id==prefix+verb]
        if found: return found[-1]
    return None

def prepare_cutover(vault_root, dev, runner=None, old_market="xu-local") -> PluginPlan:
    entries=load_plugin_manifest(vault_root)
    if not entries:
        raise MigrationInputError("shared/plugins/manifest.toml 为空或不存在，不能执行 cutover")
    tools=sorted({tool for e in entries for tool in e.platforms})
    snaps={tool:(installed_plugins(tool,runner=runner),marketplaces(tool,runner=runner))
           for tool in tools}
    reg=prepare_plugin_register(vault_root,dev,runner=runner)
    actions=list(reg.actions)

    # 同身份换源必须强制重装；单纯 marketplace add/remove 不会更新已装 cache。
    for e in entries:
        src=_plugin_source(vault_root,e.name); pid=f"{e.name}@{e.name}"
        for tool in e.platforms:
            installed,mkts=snaps[tool]
            if pid not in installed or e.name not in mkts or _same_path(mkts[e.name],src):
                continue
            desired=e.name in dev.plugins.get(tool,[])
            actions=_drop_policy_actions(actions,e.name,tool)
            dep=f"{e.name}:{tool}:mktadd"
            actions += _cutover_reinstall(tool,e.name,desired,installed[pid],dep,vault_root)

    known={e.name for e in entries}
    for tool in tools:
        installed,mkts=snaps[tool]
        old_ids=[pid for pid in installed if pid.endswith("@"+old_market)]
        unknown=sorted(pid for pid in old_ids if pid.split("@",1)[0] not in known)
        if unknown:
            raise MigrationInputError(
                f"{tool}: {old_market} 仍有 manifest 外已装身份 {unknown}，拒绝删除市场")
        retired=[]
        for oldpid in old_ids:
            name=oldpid.split("@",1)[0]; desired=name in dev.plugins.get(tool,[])
            dep=(_ready_dep(actions,name,tool)
                 or (f"{name}:{tool}:mktadd"
                     if any(a.id==f"{name}:{tool}:mktadd" for a in actions) else None))
            newpid=f"{name}@{name}"
            if desired and newpid not in installed and dep is None:
                raise MigrationInputError(f"{tool}: {name} 新身份未规划成功，不能退役 {oldpid}")
            argv=(["plugin","uninstall",oldpid,"--keep-data","--scope","user"] if tool=="claude"
                  else ["plugin","remove",oldpid])
            a=PluginAction(f"{name}:{tool}:retire-old",f"{tool} 退役旧身份 {oldpid}",
                depends_on=((dep,) if dep else ()),cli=CliCommand(tool,argv))
            actions.append(a); retired.append(a.id)
        if old_market in mkts:
            # 删除聚合市场依赖本平台此前所有新市场/新身份/旧身份动作；任一失败都必须 skip。
            market_deps=tuple(dict.fromkeys(
                [a.id for a in actions if f":{tool}:" in a.id] + retired))
            actions.append(PluginAction(f"{tool}:retire-market:{old_market}",
                f"{tool} 退役旧聚合市场 {old_market}",depends_on=market_deps,
                cli=CliCommand(tool,["plugin","marketplace","remove",old_market])))
    return PluginPlan(actions,reg.warnings)
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_plugin_cutover.py -q`。
- [ ] **Step 5: 提交** — `git add hub/plugin_migrate.py tests/hub/test_plugin_cutover.py && git commit -m "feat(hub): cutover old identities and source-moved caches safely"`

---

## Task 14d: 迁移/cutover CLI 入口（真机 runbook 的可执行接口）

**Files:** Modify `hub/cli.py`；Test `tests/hub/test_cli_plugin_migrate.py`。

**Interfaces:**
- `hub migrate-plugins --vault <v> --src <plugins-dev> --input <plugins-migration.toml> [--dry-run]`
- `hub cutover-plugins --vault <v> --host <h> [--old-market xu-local] [--dry-run]`

两条命令分别消费 T14a/b 与 T14c 的同一计划/执行器；`--dry-run` 只通过 `Writer(dry_run=True)` 传入，
不另造预览路径。任一 report failure 返回非零。

- [ ] **Step 1: 写失败测试 tests/hub/test_cli_plugin_migrate.py**

```python
from hub import cli
from hub.plugin_migrate import MigrationPlan, MigrationReport
from hub.plugin_ops import PluginPlan, PluginRunReport

def test_migrate_plugins_dryrun_uses_writer_gate(tmp_path, monkeypatch):
    captured={}
    monkeypatch.setattr(cli,"prepare_migration",lambda *a,**k:MigrationPlan([],[],[]))
    def execute(plan,vault,w):
        captured["dry"]=w.dry_run
        return MigrationReport()
    monkeypatch.setattr(cli,"execute_migration",execute)
    rc=cli.main(["migrate-plugins","--vault",str(tmp_path),"--src",str(tmp_path/"old"),
                 "--input",str(tmp_path/"m.toml"),"--dry-run"])
    assert rc==0 and captured=={"dry":True}

def test_migrate_plugins_failure_is_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(cli,"recover_pending",lambda *a,**k:[])
    monkeypatch.setattr(cli,"prepare_migration",lambda *a,**k:MigrationPlan([],[],[]))
    monkeypatch.setattr(cli,"execute_migration",
        lambda *a,**k:MigrationReport(failed=[("move","boom")]))
    rc=cli.main(["migrate-plugins","--vault",str(tmp_path),"--src",str(tmp_path/"old"),
                 "--input",str(tmp_path/"m.toml")])
    assert rc==1

def test_cutover_dryrun_uses_plugin_executor(tmp_path, monkeypatch):
    (tmp_path/"box").mkdir(); (tmp_path/"box/device.toml").write_text(
        'class=[]\nprojects=[]\n[paths]\nVAULT="x"\n',encoding="utf-8")
    monkeypatch.setattr(cli,"prepare_cutover",lambda *a,**k:PluginPlan([],[]))
    seen={}
    def execute(plan,w):
        seen["dry"]=w.dry_run
        return PluginRunReport()
    monkeypatch.setattr(cli,"execute_plugin_plan",execute)
    rc=cli.main(["cutover-plugins","--vault",str(tmp_path),"--host","box","--dry-run"])
    assert rc==0 and seen=={"dry":True}
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_cli_plugin_migrate.py -q`。

- [ ] **Step 3: 实现 hub/cli.py 接线**

顶部 import（若 `subprocess` 尚未导入，一并加入）：

```python
import subprocess
from hub.plugin_migrate import (prepare_migration, execute_migration, prepare_cutover,
                                MigrationInputError)
from hub.induction import recover_pending, InductionError
```

新增 handler：

```python
def _cmd_migrate_plugins(args) -> int:
    w=Writer(dry_run=args.dry_run)
    try:
        vault=Path(args.vault)
        if not w.dry_run:
            recover_pending(vault,w)       # C4：先恢复上次崩在“.git 已移出”的事务，再做新 prepare
        plan=prepare_migration(Path(args.src),vault,Path(args.input))
        rep=execute_migration(plan,vault,w)
    except (MigrationInputError, InductionError, OSError, ValueError,
            subprocess.CalledProcessError) as e:
        print(e); return 1
    for warning in plan.warnings: print("  ⚠",warning)
    for aid,why in rep.failed: print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1

def _cmd_cutover_plugins(args) -> int:
    w=Writer(dry_run=args.dry_run)
    try:
        vault=Path(args.vault); dev=load_device(vault,args.host or current_host())
        plan=prepare_cutover(vault,dev,old_market=args.old_market)
        rep=execute_plugin_plan(plan,w)
    except (MigrationInputError, PluginManifestError, PluginIdentityError,
            PluginContainmentError, PluginRepoUnavailable, CliUnavailable,
            UnsupportedVaultVersion, FileNotFoundError) as e:
        print(e); return 1
    for aid,why in rep.failed: print(f"  ✗ {aid}: {why}")
    return 0 if not rep.failed else 1
```

在 `build_parser()` 的 `migrate-schema` 后追加：

```python
    mp=sub.add_parser("migrate-plugins",parents=[common])
    mp.add_argument("--src",required=True)
    mp.add_argument("--input",required=True)
    mp.add_argument("--dry-run",action="store_true")
    mp.set_defaults(func=_cmd_migrate_plugins)

    cp=sub.add_parser("cutover-plugins",parents=[common])
    cp.add_argument("--old-market",default="xu-local")
    cp.add_argument("--dry-run",action="store_true")
    cp.set_defaults(func=_cmd_cutover_plugins)
```

- [ ] **Step 4: 运行通过** — `py -3 -m pytest tests/hub/test_cli_plugin_migrate.py -q`。
- [ ] **Step 5: 提交** — `git add hub/cli.py tests/hub/test_cli_plugin_migrate.py && git commit -m "feat(hub): expose plugin migration and cutover commands"`

---

## Task 15: 真机迁移 runbook + cutover（人工检查点，禁 subagent 自动越过）

> **执行须知（控制器）**：本任务**移动真实 6 仓、改真实平台状态**。**不得由实现 subagent 自动执行**；控制器
> 只准备 runbook + 干跑，真机写操作交回用户逐步确认。

**Files:** Create `docs/runbooks/2026-07-hub-plugin-cutover.md`。

- [ ] **Step 1: 写 runbook（以下正文原样落入文件）**

````markdown
# Hub 插件 shared/ cutover runbook

> 这是一次性真机迁移。执行者在每个“人工确认”处停下；不得由 subagent 自动确认。备份目录在最终幂等验收前不得删除。

## 0. 固定路径与身份

```powershell
$HubRepo   = 'C:\Users\huawei\ai-cli-migrate'
$Vault     = 'C:\Users\huawei\hub-vault'
$HostName  = '2025-bg-016'
$OldSource = 'C:\Users\huawei\.claude\plugins-dev'
$Stamp     = Get-Date -Format 'yyyyMMdd-HHmmss'
$Backup    = "C:\Users\huawei\hub-plugin-cutover-$Stamp"
$Input     = Join-Path $Vault 'plugins-migration.toml'

git -C $HubRepo config user.name
git -C $HubRepo config user.email
git -C $Vault config user.name
git -C $Vault config user.email
```

人工确认：两仓都必须是个人身份 `patrick1099`；当前 ai-cli-migrate 预期邮箱为
`245735497+patrick1099@users.noreply.github.com`，hub-vault 当前为 `hsheng416@gmail.com`。若现场不同，先判断原因，
不要由 runbook 静默覆盖现有 Git identity。

## 1. 只读前检与备份

```powershell
git -C $HubRepo status --short
git -C $Vault status --short
Get-ChildItem -LiteralPath $OldSource -Directory | ForEach-Object {
    git -C $_.FullName status --short
}

New-Item -ItemType Directory -Path $Backup | Out-Null
Copy-Item -LiteralPath $OldSource -Destination (Join-Path $Backup 'plugins-dev') -Recurse
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Backup 'claude-plugins.json'),
    ((claude plugin list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'claude-markets.json'),
    ((claude plugin marketplace list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'codex-plugins.json'),
    ((codex plugin list --json) | Out-String), $Utf8NoBom)
[IO.File]::WriteAllText((Join-Path $Backup 'codex-markets.json'),
    ((codex plugin marketplace list --json) | Out-String), $Utf8NoBom)
```

停止条件：hub/vault/任一嵌套插件仓有非预期脏改；任一平台 JSON 快照失败；备份目录缺文件。

## 2. 作者检查点：market-of-one 与迁移输入

1. true-north 必须由作者补齐 `.claude-plugin/marketplace.json`，名称、唯一 plugin 名、`source="."`、
   plugin.json name 全等 `true-north`，然后在 true-north 子仓 commit。
2. 作者逐插件填写 `$Input`。`platforms` 是适配声明；`enabled` 是本机允许列表且必须为 `platforms` 子集。
   禁止从平台当前状态自动推断。compact-plus 当前 Claude disabled，不能误写进其 enabled。
3. 对每个插件子仓确认 `git status --short` 为空且 HEAD 已包含最新 manifest/version。

```powershell
py -3 -m hub.cli migrate-schema --vault $Vault --host $HostName --to 3 --dry-run
py -3 -m hub.cli migrate-plugins --vault $Vault --host $HostName --src $OldSource --input $Input --dry-run
```

人工确认：dry-run 必须列出全部 6 仓；`needs_author` 为空；没有未声明/不存在仓；没有真实文件、Git index 或平台状态变化。

## 3. 执行文件迁移

```powershell
py -3 -m hub.cli migrate-schema --vault $Vault --host $HostName --to 3
py -3 -m hub.cli migrate-plugins --vault $Vault --host $HostName --src $OldSource --input $Input
git -C $Vault status --short
git -C $Vault ls-files -s shared/plugins
```

验收：`shared/plugins/<name>/.git` 都存在且子仓 `git log -1` 可读；父仓索引的 shared/plugins 下无 `160000`；
`plugins-dev` 原 6 仓已移走；`shared/plugins/manifest.toml` 与 `plugins-device-snippet.toml` 已生成。
作者审阅 snippet 后，把 `[plugins.claude]`/`[plugins.codex]` 合并进 `<host>/device.toml`，再删 snippet。

```powershell
git -C $Vault add vault.toml SCHEMA.md shared/plugins "$HostName/device.toml"
git -C $Vault commit -m "feat(hub): move plugin active sources into shared"
```

## 4. 平台 cutover（第二个人工闸）

```powershell
py -3 -m hub.cli cutover-plugins --vault $Vault --host $HostName --old-market xu-local --dry-run
```

人工确认：每个旧 `*@xu-local` 都先有新身份 ready 依赖；cjt 同身份换源含重装；最后才删除 xu-local 市场；
没有 manifest 外旧身份。确认后执行：

```powershell
py -3 -m hub.cli cutover-plugins --vault $Vault --host $HostName --old-market xu-local
py -3 -m hub.cli register --vault $Vault --host $HostName
py -3 -m hub.cli status --vault $Vault --host $HostName --check
```

## 5. refresh 与幂等验收

选择一个同时适配 Claude/Codex 的测试插件：在 `shared/plugins/<name>` 修改源码、显式 bump plugin.json version、
在该子仓 commit；然后：

```powershell
py -3 -m hub.cli refresh --vault $Vault --host $HostName
py -3 -m hub.cli refresh --vault $Vault --host $HostName
py -3 -m hub.cli register --vault $Vault --host $HostName
py -3 -m hub.cli status --vault $Vault --host $HostName --check
git -C $Vault status --short
```

验收：第一次 refresh 两平台加载新版本；第二次 no-op；register no-op；status 全 ok；各插件子仓 clean；父仓仅有
预期的子仓内容指针更新。此时旧 `$OldSource` 才正式退役，备份仍至少保留到下一次正常使用后。

## 6. 回滚

- 文件迁移阶段失败：停止平台 cutover；从 `$Backup\plugins-dev` 恢复 `$OldSource`，保留 shared 现场供诊断。
- 平台 cutover 部分失败：不要手改平台文件；修正失败项后重跑 `cutover-plugins`，依赖图会跳过未满足后继。
- 新身份不可用：用平台官方 CLI 重新注册备份路径并安装旧身份；不要删除备份或强行改 cache/config。
````

- [ ] **Step 2: 干跑** —— 控制器只执行 runbook §1、§2 的只读命令与 `--dry-run`，把完整计划和任何 warning
  交给用户；停在 §3 之前。用户明确批准后才可继续真实迁移。
- [ ] **Step 3: 提交 runbook** — `docs(hub): plugin cutover runbook`。

---

## Task 16: README + 全量回归 + 干跑验收

**Files:** Modify `hub/README.md`；运行 `py -3 -m pytest tests/`。

- [ ] **Step 1: README** —— 在命令说明后加入以下正文：

```markdown
## 插件：shared 活源 + market-of-one

自有插件的稳态活源位于 `<vault>/shared/plugins/<name>/`；每个插件继续保留自己的 `.git`、remote 和提交历史，
父金库同时跟踪除嵌套 `.git` 外的源码文件。`~/.claude/plugins-dev` 只是一轮迁移输入，cutover 完成后不再是活源。

每个插件自带 market-of-one，稳定身份为 `<name>@<name>`。`shared/plugins/manifest.toml` 声明插件及适配平台；
`<host>/device.toml` 的 `[plugins.claude].enabled` / `[plugins.codex].enabled` 是本机分平台允许列表。

- `hub register --vault <v> --host <h>`：注册全部适配市场，并按 device 允许列表收敛安装/启用状态。
- `hub refresh --vault <v> --host <h>`：只刷新已经安装且已显式 bump+commit 的插件；不替用户改版本或源码仓。
- `hub status --vault <v> --host <h> --check`：只读检查 source、启用态、仓状态和本机刷新基线。
- `hub migrate-plugins ...` / `hub cutover-plugins ...`：仅用于一次性迁移；严格按
  `docs/runbooks/2026-07-hub-plugin-cutover.md` 的人工检查点执行。

平台 marketplace、安装、启用和卸载全部通过 Claude/Codex 官方 CLI；hub 不直接修改平台 cache、
installed_plugins.json、known_marketplaces.json 或 Codex config.toml。本机刷新基线保存在
`~/.hub/plugin-state.toml`，它是运行态，不进金库。
```
- [ ] **Step 2: 全量回归** — `py -3 -m pytest tests/ -q`，零失败（跳过允许）。
- [ ] **Step 3: 干跑验收** — 沙箱金库跑 `register --dry-run`/`refresh --dry-run`/`status --check`，确认双 dry-run
  输出（Writer 字段 + CLI 命令）、零副作用。
- [ ] **Step 4: 提交** — `docs(hub): README plugin section + Plan 3 regression green`。

---

## 依赖与顺序

```
T2,T3(契约) · T4(induction) · T5(manifest) · T6(device) · T7(state) · T8(cli) ── 底座
        └─▶ T9(PluginPlan/执行器) ─▶ T10 register · T11 refresh · T12 status ─▶ T13 CLI 集成
T14a(迁移 planner) ─▶ T14b(复制+induct executor) ─▶ T14c(cutover planner, 依赖 T9/T10)
        └─▶ T14d(迁移/cutover CLI) ─▶ T15 真机 cutover(人工闸) ─▶ T16 收尾
```
（共 18 个实现任务：T2–T13 + T14a/b/c/d + T15 + T16。）

## 自审（对照 spec §10 + 8 组返修）

- **8 组缺口（全部字面展开）**：①**每任务 RED 测试代码 + 命令 + 最小实现代码 + GREEN 命令 + 精确提交文件**——T2–T13
  与 T14a/b/c/d 均给出可直接复制的测试与实现（无 `Step 2–4`/描述式步骤）；②induction admin-dir 日志/暂存 +
  prepare/execute 分离 + 冲突检测 + `git reset` 回滚 + json.dumps 测试（T4）；③`PluginAction.depends_on` 阻断后继
  （T9）；④register/refresh 都是 prepare-all→commit，确定性错误零写（T13）；⑤plugin_cli 补
  installed(enabled/scope)/marketplaces/preflight
  + 两平台真实 JSON 形状（T8）；⑥列表外只 disable、Claude install 后显式 enable、uninstall --keep-data、
  首次 refresh 真实重读、恢复 disabled、末条成功才写台账（T10/T11）；⑦迁移 **prepare 纯(T14a)/execute
  移动(T14b)/cutover(T14c) 三拆**、显式 input、SHA-256 树校验、部分完成重跑收敛、needs_author 零移动、
  旧身份逐个退役、同身份换源强制重装、`Migration*` 类型与可执行 CLI（T14a/b/c/d）；⑧version==3 精确门槛
  （T2）+ `SCHEMA_MD` 常量真实接口（T3）。
- **spec 覆盖**：C0(T2)/schema(T3)/C4 induction(T4)/C5 containment(T4/T10/T14b)/C6 manifest+身份(T5)/P4 启用态
  (T6/T10)/P6 台账(T7)/P3 CLI+双 dry-run(T8/T9/T13)/P4 register(T10)/P5 refresh(T11)/P7 status(T12)/P8 迁移
  (T14a/b/c/d/T15)。Plan 3.2 排除，符合 §10.3。
- **类型一致**：`PluginEntry`(T5)/`Baseline`(T7)/`CliCommand`·`CliResult`·`Installed`(T8)/`PluginAction`·
  `PluginPlan`·`PluginRunReport`(T9)/`PluginHealth`(T12)/`InductionPlan`(T4)/`MigrationAction`·`MigrationPlan`·
  `MigrationReport`(T14a/b)跨任务引用一致。
- **真机隔离**：单测注入 runner + tmp；唯一真机动作 T15 设人工闸。
