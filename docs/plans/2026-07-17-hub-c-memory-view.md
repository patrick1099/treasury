# hub C 阶段 Plan 2 —— memory 视图（含 Task 0 边界加固）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 hub 补上 memory 下行视图（备份区记忆经 promote 进 shared，再按 scope 生成各工具只读视图 + 受管块 + `hub-memory` skill 按需读正文），并先修 Plan 1 两个 skill 边界洞。

**Architecture:** 上行 `collect → <host>/claude/memory → promote-memory → shared/memory`（人工闸）；下行单次扫描+过滤+校验产出一批 `MemoryViewEntry`，再分渲染成 `~/.hub/views/<tool>/MEMORY.md` 薄索引、Codex `AGENTS.md` 内联紧凑块、opencode `instructions[]` 条目；正文永远留在金库、由 `hub-memory` skill 按名读取并在内存展开符号根。register 首建、refresh 重算，均显式；sync 只动金库。

**Tech Stack:** Python ≥ 3.11（纯标准库，`py -3`）、pytest、Windows 目录 junction（`mklink /J`）、`os.replace` 原子替换。

## Global Constraints

- **纯标准库**，Python ≥ 3.11；AI 脚本用 `py -3`，不建 venv。
- **所有写/删走 `hub/writer.py` 的 `Writer`**；`--dry-run` 闸在写方法内部，不在调用方。
- **密钥硬闸不可豁免**：路径组件命中 `secrets`/`auth.json`/`.env`（大小写不敏感、字面+realpath 两查）→ 拒绝（`hub/guard.py`）。
- **link-only**：建目录链接用 junction（不需管理员）；建链失败明确报错，绝不静默拷贝。
- **异常即停、非破坏**：配置/校验异常在写任何东西之前全量预检并中止，旧产物原封不动；register 从不删用户路径。
- **原子性承诺**（§9.7）：预检错误→零写入；单文件写→不截断（同目录 temp + `os.replace`）；跨文件提交期 I/O 故障→可能部分完成、不回滚、重跑 register/refresh 幂等收敛。**不做全量 staging。**
- **scope 语法 v2**：`global`/`class:<名>`/`project:<名>`/`tool:<claude|codex|opencode>`；`global`/`class`/`project` 同属设备维度维度内 OR，`tool` 独立维度内 OR，两维 AND，空维度=匹配全部；`global` 必须独占。
- **视图路径**：`~/.hub/views/<tool>/MEMORY.md`；`<tool>` ∈ {claude, codex, opencode}。**本机派生物，不进金库、collect 不收。**
- **UTF-8 无 BOM** 写一切文件（`os.replace` 前的 temp 用 `encoding="utf-8"`，不加 BOM）。
- **提交身份（本仓已定）**：personal `patrick1099`，`user.email = 245735497+patrick1099@users.noreply.github.com`（已写进本仓 `git config --local`，commit 无需再带 `-c`）。commit footer：`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- **测试目录铁律**：测试**绝不**写真实 `~/.claude`/`~/.codex`/`~/.agents`/`~/.hub`/`hub-vault`，一律用 pytest `tmp_path`。
- 关联设计：`docs/specs/2026-07-16-hub-c-register-design.md` §9（v4 校准，本计划的权威依据）。

---

## 文件结构

**新增：**
- `hub/vaultpaths.py` — 金库路径边界断言（`shared_skills_dir`、`within_shared_skills`、`SharedSkillsEscape`）。promote/register/status 共用。
- `hub/memview.py` — `MemoryViewEntry` + `collect_view_entries`（扫描 shared 记忆、按 (device,tool) 过滤、校验）+ 三个渲染器。
- `hub/textblock.py` — 通用 `<!-- hub:begin -->…<!-- hub:end -->` 受管块 upsert/校验。
- `hub/opencode_cfg.py` — opencode `instructions[]` 写入（路径解析、refuse-safe JSONC、最小回滚日志、原子）。
- `hub/hubconfig.py` — `~/.hub/config.toml` 读写 + vault/host 冲突检查 + 备份目录路径。
- `hub/memread.py` — `memory-read` 核心（在本机该 tool 视图里查名 → 读 canonical → 展开符号根）。
- `hub/skills/hub-memory/SKILL.md` + `hub/skills/hub-memory/scripts/read_memory.py` — 随包发的正文读取 skill。

**改动：**
- `hub/promote.py` — 走 `shared_skills_dir`（Task 1）；加 `promote_memory` + `PromoteMemoryConflict`（Task 6）。
- `hub/register.py` — 走 `shared_skills_dir` + 每名 within 校验（Task 1）；工具容器校验（Task 2）；装 hub-memory + 写 config.toml + 生成视图/块/opencode（Task 13）。
- `hub/status_report.py` — 走 `shared_skills_dir`（Task 1）；`link_status` 供 `status --check`（Task 14）。
- `hub/scope.py` — `device`→`class`、`scope_matches`、修 docstring（Task 3）。
- `hub/schema_md.py` — scope 章节升 v2（Task 3）。
- `hub/scaffold_vault.py` — 写 `version = 2`（Task 4）。
- `hub/writer.py` — `write_text_atomic`（Task 5）。
- `hub/cli.py` — 新子命令 `promote-memory`/`memory-read`/`refresh`/`migrate-schema`；`register` 扩展；`sync --refresh`；`status --check`。
- `hub/README.md` — memory 视图 + 新命令；同事复查遗留 ③④（Task 15）。
- `docs/specs/2026-07-16-hub-c-register-design.md` — §8 junction 状态更新（Task 15）。

---

## Task 1: shared/skills 容器边界断言（Plan 1 fix ①）

**Files:**
- Create: `hub/vaultpaths.py`
- Modify: `hub/promote.py`（`promote_skill` 里 dest 计算）、`hub/register.py`（`register_skills` 枚举）、`hub/status_report.py`（`link_status` 枚举）、`hub/cli.py`（三处 catch）
- Test: `tests/hub/test_vaultpaths.py`、`tests/hub/test_promote.py`、`tests/hub/test_register.py`、`tests/hub/test_status_report.py`（各补一条）

**Interfaces:**
- Produces: `hub.vaultpaths.shared_skills_dir(vault_root: Path) -> Path`（容器逃逸→抛 `SharedSkillsEscape`）；`hub.vaultpaths.within_shared_skills(child: Path, vault_root: Path) -> bool`；`class SharedSkillsEscape(RuntimeError)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_vaultpaths.py
import os, pytest
from pathlib import Path
from hub.vaultpaths import shared_skills_dir, within_shared_skills, SharedSkillsEscape
from hub.fslink import make_dir_link

def test_container_absent_is_ok(tmp_path):
    # shared/skills 还没建：不报错，返回路径
    assert shared_skills_dir(tmp_path) == tmp_path / "shared" / "skills"

def test_real_container_is_ok(tmp_path):
    (tmp_path / "shared" / "skills").mkdir(parents=True)
    assert shared_skills_dir(tmp_path).name == "skills"

def test_container_junction_escape_raises(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (tmp_path / "shared").mkdir()
    make_dir_link(outside, tmp_path / "shared" / "skills")   # 容器指向金库外
    with pytest.raises(SharedSkillsEscape):
        shared_skills_dir(tmp_path)

def test_within_rejects_escaping_name(tmp_path):
    (tmp_path / "shared" / "skills").mkdir(parents=True)
    outside = tmp_path / "outside" / "alpha"; outside.mkdir(parents=True)
    make_dir_link(outside, tmp_path / "shared" / "skills" / "alpha")  # 单名逃逸
    assert within_shared_skills(tmp_path / "shared" / "skills" / "alpha", tmp_path) is False

def test_within_accepts_real_child(tmp_path):
    (tmp_path / "shared" / "skills" / "alpha").mkdir(parents=True)
    assert within_shared_skills(tmp_path / "shared" / "skills" / "alpha", tmp_path) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_vaultpaths.py -v`
Expected: FAIL（`ModuleNotFoundError: hub.vaultpaths`）

- [ ] **Step 3: 写实现**

```python
# hub/vaultpaths.py
"""金库路径边界断言：shared/skills 容器不得经链接逃出金库。

Plan 1 只查了叶子 shared/skills/<name> 是不是链接，没查容器本身。若
vault/shared/skills 是指向金库外的 junction，promote 会往金库外落盘、register
会枚举金库外目录建链、status 还报 ok。这里把容器边界一次锁死，三处共用。
"""
import os
from pathlib import Path
from hub.model import SHARED

class SharedSkillsEscape(RuntimeError):
    pass

def shared_skills_dir(vault_root: Path) -> Path:
    """返回 <vault>/shared/skills；经链接解析后逃出金库则抛 SharedSkillsEscape。

    允许 vault_root 整体经链接访问（整个金库挂在被链接的 home 下也行），所以比的是
    realpath(shared/skills) 是否等于 realpath(vault_root)/shared/skills，不是拿
    realpath(vault_root) 去比 vault_root。容器不存在时不报错（首次注册前它可能还没建）。
    """
    vault_root = Path(vault_root)
    container = vault_root / SHARED / "skills"
    if os.path.lexists(container):
        expected = os.path.join(os.path.realpath(vault_root), SHARED, "skills")
        if os.path.realpath(container) != expected:
            raise SharedSkillsEscape(
                f"shared/skills 经链接逃出金库：{container} → {os.path.realpath(container)}；"
                f"应在 {expected} 内。停下来让你处理，绝不往金库外读写。")
    return container

def within_shared_skills(child: Path, vault_root: Path) -> bool:
    """child 解析后是否仍落在（已验证不逃逸的）shared/skills 内。异常一律 False。"""
    container = shared_skills_dir(vault_root)          # 先保证容器本身不逃逸
    try:
        c = os.path.realpath(Path(child))
        base = os.path.realpath(container)
    except (OSError, ValueError):
        return False
    return c == base or c.startswith(base + os.sep)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_vaultpaths.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 把三个消费方接进来**

`hub/promote.py`：把 `promote_skill` 里的
```python
    dest = vault_root / SHARED / "skills" / name
```
改为（顶部加 `from hub.vaultpaths import shared_skills_dir`）：
```python
    dest = shared_skills_dir(vault_root) / name        # 断言容器不逃逸
```

`hub/register.py`：把 `register_skills` 里的
```python
    shared = vault_root / SHARED / "skills"
    skills = sorted((d for d in shared.iterdir() if d.is_dir()), key=lambda p: p.name) \
        if shared.is_dir() else []
```
改为（顶部加 `from hub.vaultpaths import shared_skills_dir, within_shared_skills, SharedSkillsEscape`）：
```python
    shared = shared_skills_dir(vault_root)             # 断言容器不逃逸
    skills = sorted((d for d in shared.iterdir() if d.is_dir()), key=lambda p: p.name) \
        if shared.is_dir() else []
    for d in skills:
        if not within_shared_skills(d, vault_root):    # 单名也不许逃逸
            raise SharedSkillsEscape(
                f"shared/skills/{d.name} 经链接逃出金库，register 拒绝、零写入。")
```

`hub/status_report.py`：把 `link_status` 里的
```python
    shared = vault_root / SHARED / "skills"
    shared_skills = sorted((d for d in shared.iterdir() if d.is_dir()),
                           key=lambda p: p.name) if shared.is_dir() else []
```
改为（顶部加 `from hub.vaultpaths import shared_skills_dir, within_shared_skills`）：
```python
    shared = shared_skills_dir(vault_root)             # 逃逸容器→抛 SharedSkillsEscape
    shared_skills = sorted((d for d in shared.iterdir()
                            if d.is_dir() and within_shared_skills(d, vault_root)),
                           key=lambda p: p.name) if shared.is_dir() else []
```

`hub/cli.py`：`_cmd_promote`、`_cmd_register`、`_cmd_status` 的 except 元组里都加上 `SharedSkillsEscape`（顶部 `from hub.vaultpaths import SharedSkillsEscape`）。`_cmd_status` 用 try 包住 `link_status` 调用：
```python
    try:
        rows = link_status(vault_root, dev)
    except SharedSkillsEscape as e:
        print(e)
        return 1
```

- [ ] **Step 6: 补三条消费方回归测试**

```python
# tests/hub/test_register.py 追加
from hub.vaultpaths import SharedSkillsEscape
from hub.fslink import make_dir_link
from hub.writer import Writer
from hub.register import register_skills
from hub.model import DeviceProfile
import pytest

def test_register_refuses_when_shared_skills_container_escapes(tmp_path):
    outside = tmp_path / "outside"; outside.mkdir()
    (tmp_path / "shared").mkdir()
    make_dir_link(outside, tmp_path / "shared" / "skills")
    dev = DeviceProfile(host="b", classes=[], projects=[],
                        paths={"CLAUDE_HOME": str(tmp_path / ".claude"),
                               "AGENTS_HOME": str(tmp_path / ".agents")}, sources={})
    w = Writer()
    with pytest.raises(SharedSkillsEscape):
        register_skills(tmp_path, dev, w)
    assert w.written == []                              # 金库外一个链接都没建
    assert not (tmp_path / ".claude" / "skills").exists()
```

（`tests/hub/test_promote.py`、`tests/hub/test_status_report.py` 各补一条类似断言：promote 遇逃逸容器抛 `SharedSkillsEscape` 且 `w.written == []`；status 遇逃逸容器抛 `SharedSkillsEscape`。）

- [ ] **Step 7: 跑相关测试**

Run: `py -3 -m pytest tests/hub/test_vaultpaths.py tests/hub/test_promote.py tests/hub/test_register.py tests/hub/test_status_report.py -v`
Expected: PASS（全绿）

- [ ] **Step 8: Commit**

```bash
git add hub/vaultpaths.py hub/promote.py hub/register.py hub/status_report.py hub/cli.py tests/hub/test_vaultpaths.py tests/hub/test_promote.py tests/hub/test_register.py tests/hub/test_status_report.py
git commit -m "fix(hub): assert shared/skills container never escapes vault (Plan 1 fix 1)"
```

---

## Task 2: register 校验工具 skills 容器（Plan 1 fix ②）

**Files:**
- Modify: `hub/register.py`（`register_skills` 预检加容器检查）、`hub/status_report.py`（`link_status` 也标出链接容器）
- Test: `tests/hub/test_register.py`、`tests/hub/test_status_report.py`

**Interfaces:**
- Consumes: `hub.register.skill_targets(dev) -> list[Path]`、`hub.writer.Writer.make_dir_link`、`hub.fslink.resolves_to`。
- Produces: `register_skills` 现在会因目标 `skills` 容器是链接/文件/坏链而抛 `RegisterConflict` 且零写入；容器不存在时允许 Writer 建真目录。`link_status` 遇链接容器**不再报 ok**，而是给出一行 `conflict`（**Task 0 必须同步改 status，不能只修 register**）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_register.py 追加（复用文件已有的 _dev / _shared_skill，**勿重定义**；
# _dev 里 home 在 tmp_path/home/.claude、tmp_path/home/.agents，测试路径按它来）

def test_register_refuses_when_target_skills_container_is_a_link(tmp_path):
    _shared_skill(tmp_path, "alpha")
    # AGENTS_HOME/skills 整个是 junction（违反 issue #11314）
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    agents = tmp_path / "home" / ".agents"; agents.mkdir(parents=True)
    make_dir_link(elsewhere, agents / "skills")
    w = Writer()
    with pytest.raises(RegisterConflict):
        register_skills(tmp_path, _dev(tmp_path), w)
    assert w.written == []                              # 零写入
    assert not (tmp_path / "home" / ".claude" / "skills" / "alpha").exists()  # Claude 侧本可建也没建

def test_register_creates_absent_container_as_real_dir(tmp_path):
    _shared_skill(tmp_path, "alpha")
    w = Writer()
    register_skills(tmp_path, _dev(tmp_path), w)
    assert (tmp_path / "home" / ".claude" / "skills" / "alpha").exists()
    assert not (tmp_path / "home" / ".claude" / "skills").is_symlink()  # 容器是真目录
```

```python
# tests/hub/test_status_report.py 追加（复用文件已有 _dev / link_status / make_dir_link）：
# 链接容器 → status 报 conflict，不假 ok。该文件 _dev 的 home 在 tmp_path/.agents

def test_status_flags_linked_tool_container(tmp_path):
    (tmp_path / "shared" / "skills" / "alpha").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    (tmp_path / ".agents").mkdir()
    make_dir_link(elsewhere, tmp_path / ".agents" / "skills")     # 容器整个是 junction
    rows = link_status(tmp_path, _dev(tmp_path))
    assert any(state == "conflict" and ".agents" in label for state, label in rows)
    assert not any(state == "ok" and str(tmp_path / ".agents" / "skills") in label
                   for state, label in rows)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_register.py -k container -v`
Expected: FAIL（第一条不抛 RegisterConflict）

- [ ] **Step 3: 写实现**

在 `hub/register.py` 的 `register_skills` 里，只读预检**开头**（`to_link` 初始化之后、进入 `for target_dir` 循环内的**最前面**）加容器校验。改后的循环体：

```python
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):
            # 容器必须是真目录：symlink/junction/文件/坏链一律拒（Codex issue #11314：
            # 整个 skills 目录是链接时不被识别）。realpath(容器)!=真身路径 → 是链接/坏链。
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                conflicts.append(f"{target_dir}（skills 容器必须是真目录，不能是链接/文件）")
                continue
        # 不存在：留给 make_dir_link 的 mkdir(parents=True) 建成真目录，放行。
        for src in skills:
            ...
```

注意：`conflicts` 在原代码里是在循环外初始化、循环末尾统一 `if conflicts: raise RegisterConflict(...)`——保持那段不变，这里只是把容器冲突并进同一个 `conflicts` 列表，于是"任何冲突→零写入"的既有不变量自动覆盖到容器场景。`os` 已在 register.py 顶部导入。

`hub/status_report.py`：`link_status` 的 `for target_dir in skill_targets(dev):` 循环体最前面加同样的容器检查（status 也不能对链接容器报 ok）：

```python
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                rows.append(("conflict", f"{target_dir}（skills 容器是链接/非目录）"))
                continue
        for src in shared_skills:
            ...
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_register.py -k container -v`
Expected: PASS

- [ ] **Step 5: 跑全 register + status 测试**

Run: `py -3 -m pytest tests/hub/test_register.py tests/hub/test_status_report.py -v`
Expected: PASS（含既有用例 + 链接容器 status conflict）

- [ ] **Step 6: Commit**

```bash
git add hub/register.py hub/status_report.py tests/hub/test_register.py tests/hub/test_status_report.py
git commit -m "fix(hub): register+status refuse/flag linked tool skills container (Plan 1 fix 2)"
```

---

## Task 3: scope 语法升 v2（class 维度 + scope_matches + 契约文本）

**Files:**
- Modify: `hub/scope.py`、`hub/schema_md.py`（scope 章节）
- Test: `tests/hub/test_scope.py`

**Interfaces:**
- Produces: `hub.scope.parse_scope(scope)` 现在识别 `class`/`project`/`tool`（**不再是 `device`**）；`hub.scope.scope_matches(dims: dict[str, set[str]], device_classes: list[str], device_projects: list[str], tool: str) -> bool`；`ScopeError` 不变。

- [ ] **Step 1: 写失败测试**

**整份覆盖** `tests/hub/test_scope.py`（现有文件里 `test_same_dim_is_or`/`test_malformed_predicate_rejected` 等用 `device:` 断言"合法"，与 v2 冲突，必须删掉——不是追加）：

```python
# tests/hub/test_scope.py（整体替换：旧用例断言 device: 合法，已作废）
import pytest
from hub.scope import parse_scope, scope_matches, ScopeError

def test_class_replaces_device():
    dims = parse_scope(["class:work"])
    assert dims == {"class": {"work"}}

def test_old_device_token_rejected():
    with pytest.raises(ScopeError):
        parse_scope(["device:work"])          # 旧语法，明确拒绝

def test_global_must_be_alone():
    with pytest.raises(ScopeError):
        parse_scope(["global", "tool:claude"])

def test_unknown_prefix_and_empty_rejected():
    for bad in (["projet:xinao"], ["class:"], []):
        with pytest.raises(ScopeError):
            parse_scope(bad)

# ---- 匹配 ----
def _m(scope, classes, projects, tool):
    return scope_matches(parse_scope(scope), classes, projects, tool)

def test_global_matches_everything():
    assert _m(["global"], [], [], "claude") is True

def test_tool_only_matches_all_devices_that_tool():
    assert _m(["tool:claude"], ["work"], ["x"], "claude") is True
    assert _m(["tool:claude"], ["work"], ["x"], "codex") is False

def test_class_or_project_within_device_dimension():
    # class 与 project 同维 OR：命中任一即可
    assert _m(["class:work", "project:xinao"], ["home"], ["xinao"], "claude") is True
    assert _m(["class:work", "project:xinao"], ["work"], ["other"], "claude") is True
    assert _m(["class:work", "project:xinao"], ["home"], ["other"], "claude") is False

def test_device_and_tool_are_anded():
    assert _m(["project:xinao", "tool:codex"], [], ["xinao"], "codex") is True
    assert _m(["project:xinao", "tool:codex"], [], ["xinao"], "claude") is False
    assert _m(["project:xinao", "tool:codex"], [], ["other"], "codex") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_scope.py -v`
Expected: FAIL（`device` 仍被接受、`scope_matches` 不存在）

- [ ] **Step 3: 写实现**

把 `hub/scope.py` 整体替换为：

```python
"""scope 的校验**与匹配**。

（历史注记：旧 docstring 说"匹配不在这里，因为 C 不是 Python"——那是落地层时代的判断。
v3 起 register/refresh 就是 hub 的 CLI 命令，C 就是 Python，匹配器理应回到这里。）

- 校验：`hub sync` 前 lint、`promote`/视图生成前预检，非法即停。
- 匹配：视图生成按 (本机 class/projects, 目标 tool) 判一条记忆进不进该视图。

语法：global / class:<名> / project:<名> / tool:<claude|codex|opencode>。
语义：global/class/project 同属"设备订阅"维度维度内 OR；tool 独立维度内 OR；
两维之间 AND；某维度无标签=该维度匹配全部；global 必须独占。
"""

class ScopeError(ValueError):
    pass

_DIMS = {"class", "project", "tool"}
_TOOLS = {"claude", "codex", "opencode"}

def parse_scope(scope: list[str]) -> dict[str, set[str]]:
    if not scope:
        raise ScopeError("scope 不能为空（至少写 [global]）")
    has_global = "global" in scope
    dims: dict[str, set[str]] = {}
    for token in scope:
        if token == "global":
            continue
        dim, sep, val = token.partition(":")
        if not sep or dim not in _DIMS or not val:
            raise ScopeError(f"非法 scope 谓词: {token!r}（合法维度: class/project/tool）")
        if dim == "tool" and val not in _TOOLS:
            raise ScopeError(f"未知 tool: {val!r}（合法: claude/codex/opencode）")
        dims.setdefault(dim, set()).add(val)
    if has_global and dims:
        raise ScopeError("global 必须单独出现，不可与维度谓词混用")
    return dims

def lint_scope(scope: list[str]) -> list[str]:
    try:
        parse_scope(scope)
        return []
    except ScopeError as e:
        return [str(e)]

def scope_matches(dims: dict[str, set[str]], device_classes: list[str],
                  device_projects: list[str], tool: str) -> bool:
    """dims = parse_scope(...) 的结果。global 场景 dims 为空 → 两维都匹配全部 → True。"""
    subs = dims.get("class", set()) | {f"@proj:{p}" for p in dims.get("project", set())}
    device_tags = set(device_classes) | {f"@proj:{p}" for p in device_projects}
    device_ok = (not subs) or bool(subs & device_tags)
    tools = dims.get("tool", set())
    tool_ok = (not tools) or (tool in tools)
    return device_ok and tool_ok
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_scope.py -v`
Expected: PASS

- [ ] **Step 5: 更新契约文本**

`hub/schema_md.py` 的 `### scope` 段（现文本 `- 同维度 **OR**…` 到 `**匹配逻辑归 skill。**…那一段）整段替换为：

```
### scope

- 语法只有四种谓词：`global` / `class:<名>` / `project:<名>` / `tool:<claude|codex|opencode>`。
- `global` / `class:` / `project:` 同属**设备订阅维度**，维度内 **OR**；`tool:` 是独立维度，
  维度内 **OR**；两维之间 **AND**；**某维度没写标签 = 该维度匹配全部**。
- `global` **必须独占**（不与任何标签混用，混了就是非法，`hub sync` / 视图生成都会停）。
  `[tool:claude]` 本身即"所有设备、仅 Claude"，不必也不许写成 `[global, tool:claude]`。
- `class:<名>` 对的是 `device.toml` 的 `class` 数组；`project:<名>` 对的是 `projects` 数组。
  `project:xinao` 是**设备订阅条件**（本机 projects 含 xinao 才纳入），**不是**"仅 xinao
  工程会话可见"——视图是**用户级全局视图**。
- **异常即停**：未知前缀 / 空值 / 未知 tool / 空 scope → 非法；覆盖任何视图/配置前全量预检，
  报出记忆文件名 + 非法标签，本次失败、旧产物原封不动。
- （v2 契约：`vault.toml` version = 2。旧 `device:` 谓词已废，遇到即报错，见 §10 迁移。）

**匹配归 C（现在就是 hub 自己）**：视图生成按 (本机 class/projects, 目标 tool) 过滤。
提取器 `collect` 仍**从不**按 scope 筛（备份区是本机现状的镜像），只做格式校验。
```

**同一文件其余 `device:` 字样也要一并改**（只替换 scope 段不够，`grep -n "device:" hub/schema_md.py` 逐处核对）：
- §2 frontmatter 示例（行内列表）：`scope: [device:work, tool:claude]` → `scope: [class:work, tool:claude]`。
- §2 表格块状列表示例：`  - device:work` → `  - class:work`。
- §3 `device.toml` 段：`class 是判 device: scope 的唯一依据` → `class 是判 class: scope 的唯一依据`；示例注释 `class = ["work"]  # 本机的类别。device:<class> 谓词对的就是这里` → `# 本机的类别。class:<名> 谓词对的就是这里`。
- 若还有 `device:` 残留（如"公司机器的记忆漏到家里"那段），把谓词名统一改 `class:`，语义文字保留。

- [ ] **Step 6: Commit**

```bash
git add hub/scope.py hub/schema_md.py tests/hub/test_scope.py
git commit -m "feat(hub): scope grammar v2 — class dimension + scope_matches (breaking)"
```

---

## Task 4: Writer.write_text_atomic + 故障注入测试

**Files:**
- Modify: `hub/writer.py`
- Test: `tests/hub/test_writer_atomic.py`

**Interfaces:**
- Produces: `hub.writer.Writer.write_text_atomic(path: Path, text: str) -> None`（同目录**唯一** temp + flush/fsync + `os.replace`；UTF-8 无 BOM；沿用目标原换行；dry-run 只打印不落盘；记入 `self.written`；**任何异常**都清理临时文件，不只 OSError）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_writer_atomic.py
import os, pytest
from pathlib import Path
from hub.writer import Writer

def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "v" / "MEMORY.md"
    Writer().write_text_atomic(p, "hello\n")
    assert p.read_text(encoding="utf-8") == "hello\n"

def test_atomic_write_no_bom(tmp_path):
    p = tmp_path / "a.json"
    Writer().write_text_atomic(p, "{}\n")
    assert p.read_bytes()[:1] != b"\xef"                # 无 UTF-8 BOM

def test_atomic_write_preserves_crlf(tmp_path):
    p = tmp_path / "a.md"; p.write_bytes(b"old\r\n")
    Writer().write_text_atomic(p, "new\n")
    assert b"\r\n" in p.read_bytes()

def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "a.md"
    Writer(dry_run=True).write_text_atomic(p, "x\n")
    assert not p.exists()

def test_replace_failure_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "a.md"; p.write_text("original\n", encoding="utf-8")
    def boom(src, dst): raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        Writer().write_text_atomic(p, "new\n")
    assert p.read_text(encoding="utf-8") == "original\n"  # 原文完整
    assert not list(p.parent.glob("*.hub-tmp"))           # 失败不留临时垃圾

def test_non_oserror_also_cleans_temp(tmp_path, monkeypatch):
    # 编码/fsync 等非 OSError 异常也必须清 temp（不能只在 OSError 分支清）
    p = tmp_path / "a.md"
    def boom(fd): raise RuntimeError("boom")
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(RuntimeError):
        Writer().write_text_atomic(p, "x\n")
    assert not list(p.parent.glob("*.hub-tmp"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_writer_atomic.py -v`
Expected: FAIL（`write_text_atomic` 不存在）

- [ ] **Step 3: 写实现**

在 `hub/writer.py` 文件顶部加一行 `import tempfile`（`import os` 已在），并在 `Writer` 类里加方法：

```python
    def write_text_atomic(self, path: Path, text: str) -> None:
        """原子写：同目录**唯一**临时文件 + flush/fsync + os.replace，绝不留半截文件。

        视图 / 受管块 / 配置都走它——尤其 opencode.json 带明文密钥，截断代价高。
        临时名用 tempfile.mkstemp 生成唯一名（**不能用固定 .hub-tmp**：两次写同一 path 或
        上次崩溃残留会撞名互相覆盖）。**任何异常**（含编码错、fsync 失败）都在退出前清掉临时
        文件——不能只在 OSError 分支清。承诺只到单文件：跨文件一批写不是事务，中途失败可能
        部分完成，靠重跑收敛。
        """
        path = Path(path)
        self.written.append(path)
        if self.dry_run:
            n = len(text.encode("utf-8"))
            print(f"  [dry-run] 原子写 {'改写' if path.exists() else '新建'} {path}  ({n} 字节)")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        newline = "\r\n" if (path.exists() and b"\r\n" in path.read_bytes()) else "\n"
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".hub-tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)              # 原子；失败则原文件不动
        except BaseException:                  # 编码/fsync/replace 任何失败都清 temp
            tmp.unlink(missing_ok=True)
            raise
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_writer_atomic.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add hub/writer.py tests/hub/test_writer_atomic.py
git commit -m "feat(hub): Writer.write_text_atomic (unique temp, cleans on any failure)"
```

---

## Task 5: 金库版本 v2 + migrate-schema 命令

**Files:**
- Modify: `hub/scaffold_vault.py`（写 `version = 2`）、`hub/cli.py`（新 `migrate-schema` 子命令）
- Create: `hub/migrate.py`
- Test: `tests/hub/test_migrate.py`

**Interfaces:**
- Consumes: `hub.vault.load_vault`、`hub.writer.Writer.write_text_atomic`（Task 4）。
- Produces: `hub.migrate.migrate_schema(vault_root: Path, to: int, w: Writer) -> None`（非 v1、或有任何非 global 记忆→抛 `SchemaMigrationError`，列清单）；`class SchemaMigrationError(RuntimeError)`。CLI：`hub migrate-schema --vault <v> --to 2 [--dry-run]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_migrate.py
import pytest
from pathlib import Path
from hub.migrate import migrate_schema, SchemaMigrationError
from hub.writer import Writer

def _mk_vault(tmp_path, memories):
    (tmp_path / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    d = tmp_path / "shared" / "memory"; d.mkdir(parents=True)
    for name, scope in memories:
        (d / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
            f"  scope: {scope}\n---\n\nbody\n", encoding="utf-8")
    return tmp_path

def test_bumps_when_all_global(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]"), ("b", "[global]")])
    migrate_schema(v, 2, Writer())
    assert "version = 2" in (v / "vault.toml").read_text(encoding="utf-8")

def test_refuses_old_device_grammar(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]"), ("b", "[device:work]")])
    with pytest.raises(SchemaMigrationError) as ei:
        migrate_schema(v, 2, Writer())
    assert "b" in str(ei.value)
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")  # 没升

def test_refuses_valid_but_nonglobal(tmp_path):
    # 即便是 v2 合法的 class:work，v1→v2 门槛也要求**全 global** → 拒绝、版本不动
    v = _mk_vault(tmp_path, [("a", "[global]"), ("c", "[class:work]")])
    with pytest.raises(SchemaMigrationError):
        migrate_schema(v, 2, Writer())
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")

def test_refuses_when_not_v1(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]")])
    (v / "vault.toml").write_text("version = 2\n", encoding="utf-8")  # 已是 v2
    with pytest.raises(SchemaMigrationError):
        migrate_schema(v, 2, Writer())

def test_dry_run_writes_nothing(tmp_path):
    v = _mk_vault(tmp_path, [("a", "[global]")])
    migrate_schema(v, 2, Writer(dry_run=True))
    assert "version = 1" in (v / "vault.toml").read_text(encoding="utf-8")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_migrate.py -v`
Expected: FAIL（`ModuleNotFoundError: hub.migrate`）

- [ ] **Step 3: 写实现**

```python
# hub/migrate.py
"""金库 schema 版本迁移。当前只支持 **v1 → v2**（scope 语法 v2）。

scaffold 只管新库；已有金库升版本走这里。两道门槛（spec §9.1，缺一不可）：
1. **只能从 version 1 升**——已是 v2 就拒绝（不重复迁移），非 1 也拒绝。
2. **必须全部记忆都是 [global] 才升**——v1 世界里数据本就全 global；任何非 global 记忆
   （含旧 `device:` 谓词，**也含手写的 `class:`/`project:`**）用的都是 v1 的旧维度语义，
   语义翻转后必须人工复核，故列清单拒绝、版本不动。
（当前真实金库 49 条全是 global，对它就是一次纯升版本。）
"""
import tomllib
from pathlib import Path
from hub.vault import load_vault
from hub.writer import Writer

class SchemaMigrationError(RuntimeError):
    pass

def migrate_schema(vault_root: Path, to: int, w: Writer) -> None:
    vault_root = Path(vault_root)
    if to != 2:
        raise SchemaMigrationError(f"只支持迁移到 version 2，收到 {to}")
    cur = int(tomllib.loads((vault_root / "vault.toml").read_text(encoding="utf-8")).get("version", 1))
    if cur != 1:
        raise SchemaMigrationError(f"迁移只支持 1→2；当前金库是 version {cur}，不动。")
    nonglobal = [f"{m.origin}/{m.name}: scope={m.scope}"
                 for m in load_vault(vault_root).memories if m.scope != ["global"]]
    if nonglobal:
        raise SchemaMigrationError(
            "升 v2 要求全部记忆都是 [global]（非 global 数据用的是 v1 旧维度语义、语义已翻转，"
            "须人工复核）。以下记忆不是 global，迁移中止、版本未升：\n  " + "\n  ".join(nonglobal))
    w.write_text_atomic(vault_root / "vault.toml", "version = 2\n")   # 原子写（Task 4）
```

`hub/scaffold_vault.py`：把 `w.write_text(root / "vault.toml", "version = 1\n")` 改成 `"version = 2\n"`；同段注释里的 `version = 1` 一并改 2。

`hub/cli.py`：加子命令与 handler：
```python
from hub.migrate import migrate_schema, SchemaMigrationError

def _cmd_migrate_schema(args) -> int:
    try:
        migrate_schema(Path(args.vault), args.to, Writer(dry_run=args.dry_run))
    except SchemaMigrationError as e:
        print(e); return 1
    print(f"{'预计升到' if args.dry_run else '已升到'} version {args.to}")
    return 0
```
在 `build_parser` 里：
```python
    mig = sub.add_parser("migrate-schema", parents=[common])
    mig.add_argument("--to", type=int, required=True)
    mig.add_argument("--dry-run", action="store_true")
    mig.set_defaults(func=_cmd_migrate_schema)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_migrate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/migrate.py hub/scaffold_vault.py hub/cli.py tests/hub/test_migrate.py
git commit -m "feat(hub): vault schema v2 + migrate-schema command"
```

---

## Task 6: promote_memory + CLI promote-memory

**Files:**
- Modify: `hub/promote.py`、`hub/cli.py`
- Test: `tests/hub/test_promote_memory.py`

**Interfaces:**
- Consumes: `hub.guard.check_source`/`is_denied`、`hub.frontmatter.load_memory`、`hub.scope.parse_scope`、`hub.writer.Writer.copy_file`、`hub.vaultpaths`（边界思路）。
- Produces: `hub.promote.promote_memory(vault_root, host, name, w) -> Path`；`hub.promote.promote_memory_all(vault_root, host, w) -> list[Path]`；`class PromoteMemoryConflict(RuntimeError)`。CLI：`hub promote-memory --vault <v> --host <h> (--name <slug> | --all) [--dry-run]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_promote_memory.py
import pytest
from pathlib import Path
from hub.writer import Writer
from hub.promote import promote_memory, promote_memory_all, PromoteMemoryConflict

def _backup_mem(vault, host, name, scope="[global]", body="body"):
    d = vault / host / "claude" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\n{body}\n", encoding="utf-8")

def test_promote_copies_new(tmp_path):
    _backup_mem(tmp_path, "box", "a")
    dest = promote_memory(tmp_path, "box", "a", Writer())
    assert dest == tmp_path / "shared" / "memory" / "a.md"
    assert dest.exists()

def test_same_content_is_noop(tmp_path):
    _backup_mem(tmp_path, "box", "a")
    promote_memory(tmp_path, "box", "a", Writer())
    w = Writer(); promote_memory(tmp_path, "box", "a", w)
    assert w.written == []                              # 内容相同零写

def test_diff_content_conflicts(tmp_path):
    _backup_mem(tmp_path, "box", "a", body="v1")
    promote_memory(tmp_path, "box", "a", Writer())
    _backup_mem(tmp_path, "box", "a", body="v2")       # 改了源
    with pytest.raises(PromoteMemoryConflict):
        promote_memory(tmp_path, "box", "a", Writer())

def test_illegal_scope_refused_before_write(tmp_path):
    _backup_mem(tmp_path, "box", "a", scope="[device:work]")  # 旧语法
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", Writer())
    assert not (tmp_path / "shared" / "memory" / "a.md").exists()

def test_missing_source_raises(tmp_path):
    (tmp_path / "box" / "claude" / "memory").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        promote_memory(tmp_path, "box", "nope", Writer())

def test_all_is_not_mirror_and_precheck_zero_write_on_conflict(tmp_path):
    _backup_mem(tmp_path, "box", "a", body="v1")
    _backup_mem(tmp_path, "box", "b", body="ok")
    promote_memory(tmp_path, "box", "a", Writer())     # a 先进 shared
    _backup_mem(tmp_path, "box", "a", body="v2")       # a 现在冲突
    w = Writer()
    with pytest.raises(PromoteMemoryConflict):
        promote_memory_all(tmp_path, "box", w)
    assert w.written == []                              # 任一冲突→全量零写
    assert not (tmp_path / "shared" / "memory" / "b.md").exists()

def test_source_dir_link_escape_refused(tmp_path):
    # 源 memory 目录整个是指向备份区外的链接 → 拒绝、零写
    from hub.fslink import make_dir_link
    outside = tmp_path / "outside"; outside.mkdir()
    (outside / "a.md").write_text(
        "---\nname: a\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nbody\n",
        encoding="utf-8")
    (tmp_path / "box" / "claude").mkdir(parents=True)
    make_dir_link(outside, tmp_path / "box" / "claude" / "memory")   # memory 目录逃逸
    w = Writer()
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", w)
    assert w.written == []

def test_shared_parent_link_escape_refused(tmp_path):
    # shared 父目录是外链、shared/memory 尚不存在 → 仍要挡住（父目录逃逸）
    from hub.fslink import make_dir_link
    _backup_mem(tmp_path, "box", "a")
    outside = tmp_path / "out"; outside.mkdir()
    make_dir_link(outside, tmp_path / "shared")
    w = Writer()
    with pytest.raises(ValueError):
        promote_memory(tmp_path, "box", "a", w)
    assert w.written == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_promote_memory.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 写实现**

在 `hub/promote.py` 追加（顶部补 `from hub.frontmatter import load_memory` 和 `from hub.scope import parse_scope`）：

```python
class PromoteMemoryConflict(RuntimeError):
    pass

def _shared_memory_dir(vault_root: Path) -> Path:
    d = (vault_root / SHARED / "memory")
    # **不加 lexists 守卫**：shared/memory 尚不存在但父目录 shared 是外链时，
    # realpath(d) 会解析到金库外——只有无条件比对才挡得住这种父目录逃逸。
    expected = os.path.join(os.path.realpath(vault_root), SHARED, "memory")
    if os.path.realpath(d) != expected:
        raise ValueError(f"shared/memory 经链接逃出金库: {d} → {os.path.realpath(d)}")
    return d

def _classify_memory(vault_root: Path, host: str, name: str) -> tuple[Path, Path, str]:
    """返回 (src, dest, 动作)；动作 ∈ {copy, noop}；冲突/非法直接抛。"""
    _single_component("host", host)
    _single_component("name", name)
    src = vault_root / host / "claude" / "memory" / f"{name}.md"
    check_source(src)                                  # 读闸先于 access
    # 源 containment：源文件（或其所在 memory 目录）经链接逃出本机备份区 → 拒绝
    backup_root = os.path.realpath(vault_root / host)
    rsrc = os.path.realpath(src)
    if rsrc != backup_root and not rsrc.startswith(backup_root + os.sep):
        raise ValueError(f"记忆源经链接逃出备份区: {src} → {rsrc}")
    if not src.is_file():
        raise FileNotFoundError(f"备份区没有这条记忆: {src}")
    parse_scope(load_memory(src).scope)                # frontmatter/scope 非法即停（抛 ScopeError←ValueError）
    dest = _shared_memory_dir(vault_root) / f"{name}.md"
    if os.path.lexists(dest):
        if os.path.islink(dest) or os.path.isdir(dest) or _is_link_at(dest):
            raise PromoteMemoryConflict(f"shared/memory/{name}.md 被目录/链接占用，停下来让你处理。")
        if not dest.is_file():
            raise PromoteMemoryConflict(f"shared/memory/{name}.md 被非普通文件占用，停下来让你处理。")
        if dest.read_bytes() == src.read_bytes():
            return src, dest, "noop"
        raise PromoteMemoryConflict(
            f"shared/memory/{name}.md 已存在且内容不同——停下来让你决定，绝不静默覆盖。")
    return src, dest, "copy"

def promote_memory(vault_root: Path, host: str, name: str, w: Writer) -> Path:
    vault_root = Path(vault_root)
    src, dest, action = _classify_memory(vault_root, host, name)
    if action == "copy":
        w.copy_file(src, dest)
    return dest

def promote_memory_all(vault_root: Path, host: str, w: Writer) -> list[Path]:
    """把本机备份区所有记忆批量提升。全量预检：任一冲突/非法→零写入、报全清单。非 mirror。"""
    vault_root = Path(vault_root)
    mem_dir = vault_root / host / "claude" / "memory"
    names = sorted(p.stem for p in mem_dir.glob("*.md")) if mem_dir.is_dir() else []
    plans: list[tuple[Path, Path, str]] = []
    errors: list[str] = []
    for n in names:
        try:
            plans.append(_classify_memory(vault_root, host, n))
        except (PromoteMemoryConflict, ValueError, FileNotFoundError) as e:
            errors.append(f"{n}: {e}")
    if errors:
        raise PromoteMemoryConflict(
            "批量提升预检失败，一个字节都没写。请逐条处理后重试：\n  " + "\n  ".join(errors))
    done: list[Path] = []
    for src, dest, action in plans:
        if action == "copy":
            w.copy_file(src, dest)
        done.append(dest)
    return done
```

`hub/cli.py`：handler + 子命令：
```python
from hub.promote import promote_skill, promote_memory, promote_memory_all, PromoteConflict, PromoteMemoryConflict

def _cmd_promote_memory(args) -> int:
    if bool(args.name) == bool(args.all):
        print("--name 与 --all 必须二选一"); return 1
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=args.dry_run)
    try:
        load_device(vault_root, host)
        if args.all:
            done = promote_memory_all(vault_root, host, w)
            print(f"{'预计提升' if args.dry_run else '已提升'} {len(done)} 条记忆")
        else:
            dest = promote_memory(vault_root, host, args.name, w)
            print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    except (PromoteMemoryConflict, FileNotFoundError, ValueError) as e:
        print(e); return 1
    return 0
```
`build_parser`：
```python
    pm = sub.add_parser("promote-memory", parents=[common])
    pm.add_argument("--name", default=None, help="要提升的记忆名（单个，不含路径/后缀）")
    pm.add_argument("--all", action="store_true", help="批量提升本机备份区全部记忆")
    pm.add_argument("--dry-run", action="store_true")
    pm.set_defaults(func=_cmd_promote_memory)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_promote_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/promote.py hub/cli.py tests/hub/test_promote_memory.py
git commit -m "feat(hub): promote-memory (per-name + --all, non-mirror, precheck)"
```

---

## Task 7: MemoryViewEntry + 扫描过滤校验

**Files:**
- Create: `hub/memview.py`
- Test: `tests/hub/test_memview_entries.py`

**Interfaces:**
- Consumes: `hub.model.SHARED`/`Memory`/`DeviceProfile`、`hub.frontmatter.load_memory`、`hub.scope.parse_scope`/`scope_matches`。**不经 `load_vault`**（那会顺带解析各设备未 promote 的记忆，慢且会被无关坏记忆炸到）。
- Produces: `@dataclass MemoryViewEntry(name: str, description: str, scope: list[str], source: Path)`；`hub.memview.load_shared_memories(vault_root) -> list[Memory]`（**只扫 `shared/memory/`**；容器逃逸/stem≠name/重名→抛 `SharedMemoryError`）；`class SharedMemoryError(RuntimeError)`；`hub.memview.validate_scopes(memories) -> dict[str, dict]`（全量预检，任一非法抛 `ViewScopeError`、点名全部坏文件）；`hub.memview.entries_for_tool(memories, parsed, vault_root, dev, tool) -> list[MemoryViewEntry]`（在内存里过滤、不重新扫盘）；`hub.memview.collect_view_entries(vault_root, dev, tool) -> list[MemoryViewEntry]`（单工具便捷入口 = 三者串起来）；`class ViewScopeError(RuntimeError)`。批量落盘（Task 13）用前三者**只扫一次** shared、内存里切三份子集。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_memview_entries.py
import pytest
from pathlib import Path
from hub.memview import collect_view_entries, ViewScopeError
from hub.model import DeviceProfile

def _shared_mem(vault, name, scope):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name} desc\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\nbody of {name}\n", encoding="utf-8")

def _vault_toml(vault):
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")

def _dev(classes=(), projects=()):
    return DeviceProfile(host="box", classes=list(classes), projects=list(projects),
                         paths={}, sources={})

def test_global_goes_to_every_tool(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    names = [e.name for e in collect_view_entries(tmp_path, _dev(), "codex")]
    assert names == ["a"]

def test_tool_filter(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[tool:claude]")
    assert [e.name for e in collect_view_entries(tmp_path, _dev(), "claude")] == ["a"]
    assert collect_view_entries(tmp_path, _dev(), "codex") == []

def test_project_subscription(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[project:xinao]")
    assert collect_view_entries(tmp_path, _dev(projects=["xinao"]), "claude")[0].name == "a"
    assert collect_view_entries(tmp_path, _dev(projects=["other"]), "claude") == []

def test_illegal_scope_anywhere_aborts_before_any_entry(tmp_path):
    _vault_toml(tmp_path)
    _shared_mem(tmp_path, "a", "[global]")
    _shared_mem(tmp_path, "b", "[projet:xinao]")       # 手误
    with pytest.raises(ViewScopeError) as ei:
        collect_view_entries(tmp_path, _dev(), "claude")
    assert "b" in str(ei.value)                          # 点名文件

def test_entry_has_absolute_source(tmp_path):
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    e = collect_view_entries(tmp_path, _dev(), "claude")[0]
    assert e.source.is_absolute() and e.source.name == "a.md"
    assert e.description == "a desc"

def test_scan_ignores_device_memory(tmp_path):
    # 设备区放一条坏记忆——只扫 shared 就不该碰它（若走 load_vault 会被它炸到）
    from hub.memview import load_shared_memories
    _vault_toml(tmp_path); _shared_mem(tmp_path, "a", "[global]")
    dd = tmp_path / "box" / "claude" / "memory"; dd.mkdir(parents=True)
    (dd / "bad.md").write_text("not frontmatter at all", encoding="utf-8")
    assert [m.name for m in load_shared_memories(tmp_path)] == ["a"]

def test_shared_memory_container_escape_raises(tmp_path):
    from hub.memview import load_shared_memories, SharedMemoryError
    from hub.fslink import make_dir_link
    _vault_toml(tmp_path)
    outside = tmp_path / "out"; outside.mkdir()
    make_dir_link(outside, tmp_path / "shared")     # shared 父目录逃逸、shared/memory 尚不存在
    with pytest.raises(SharedMemoryError):
        load_shared_memories(tmp_path)

def test_stem_must_equal_name(tmp_path):
    from hub.memview import load_shared_memories, SharedMemoryError
    _vault_toml(tmp_path)
    d = tmp_path / "shared" / "memory"; d.mkdir(parents=True)
    (d / "wrongfile.md").write_text(          # 文件名 wrongfile，frontmatter name=a
        "---\nname: a\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\nb\n",
        encoding="utf-8")
    with pytest.raises(SharedMemoryError):
        load_shared_memories(tmp_path)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_memview_entries.py -v`
Expected: FAIL（`hub.memview` 不存在）

- [ ] **Step 3: 写实现**

```python
# hub/memview.py
"""memory 下行视图核心：从 shared/memory **只扫一次**，全量 scope 预检，再在内存里按
(设备, 工具) 切出各工具子集，喂给渲染器。绝不各扫各的、也绝不经 load_vault 顺带解析
各设备未 promote 的记忆（那会被无关坏记忆炸到，且违反"只取 shared/memory 已闸门项"）。
"""
import os
from dataclasses import dataclass
from pathlib import Path
from hub.model import SHARED, DeviceProfile, Memory
from hub.frontmatter import load_memory
from hub.scope import parse_scope, scope_matches, ScopeError

class ViewScopeError(RuntimeError):
    pass

class SharedMemoryError(RuntimeError):
    pass

@dataclass
class MemoryViewEntry:
    name: str
    description: str
    scope: list[str]
    source: Path            # 绝对路径 <vault>/shared/memory/<name>.md

def _shared_memory_dir(vault_root: Path) -> Path:
    """<vault>/shared/memory；经链接逃出金库→抛（含 shared/memory 尚不存在但父目录是外链，
    故**无条件**比 realpath，不加 lexists 守卫）。"""
    d = Path(vault_root) / SHARED / "memory"
    expected = os.path.join(os.path.realpath(vault_root), SHARED, "memory")
    if os.path.realpath(d) != expected:
        raise SharedMemoryError(f"shared/memory 经链接逃出金库: {d} → {os.path.realpath(d)}")
    return d

def load_shared_memories(vault_root: Path) -> list[Memory]:
    """**只扫 shared/memory/**——不碰各设备备份区、不经 load_vault。落三条不变量（否则会索引
    错文件、覆盖 parsed[name]、甚至让视图指向不存在的路径）：容器不逃逸、文件 stem == frontmatter
    `name`、`name` 不重复。"""
    d = _shared_memory_dir(vault_root)
    out: list[Memory] = []
    seen: set[str] = set()
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            m = load_memory(p); m.origin = SHARED
            if m.name != p.stem:
                raise SharedMemoryError(
                    f"{p.name}: frontmatter name={m.name!r} 与文件名 stem={p.stem!r} 不一致")
            if m.name in seen:
                raise SharedMemoryError(f"shared/memory 有重名记忆: {m.name!r}")
            seen.add(m.name)
            out.append(m)
    return out

def validate_scopes(memories: list[Memory]) -> dict[str, dict]:
    """全量预检：任一 scope 非法 → 抛 ViewScopeError、点名全部坏文件。返回 {name: dims}。"""
    parsed, errors = {}, []
    for m in memories:
        try:
            parsed[m.name] = parse_scope(m.scope)
        except ScopeError as e:
            errors.append(f"{m.name}.md: scope={m.scope} — {e}")
    if errors:
        raise ViewScopeError(
            "shared/memory 有 scope 非法的记忆，视图生成中止、旧产物不动：\n  " + "\n  ".join(errors))
    return parsed

def entries_for_tool(memories: list[Memory], parsed: dict[str, dict],
                     vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """在内存里按 (设备 class/projects, 目标 tool) 过滤已扫好的一批——不重新扫盘。"""
    vault_root = Path(vault_root)
    out = [MemoryViewEntry(
               name=m.name, description=m.description, scope=m.scope,
               source=(vault_root / SHARED / "memory" / f"{m.name}.md").resolve())
           for m in memories
           if scope_matches(parsed[m.name], dev.classes, dev.projects, tool)]
    out.sort(key=lambda e: e.name)
    return out

def collect_view_entries(vault_root: Path, dev: DeviceProfile, tool: str) -> list[MemoryViewEntry]:
    """单工具便捷入口（memory-read 用）。批量落盘走 load_shared_memories→validate_scopes→
    entries_for_tool 三步，只扫一次。"""
    mems = load_shared_memories(vault_root)
    parsed = validate_scopes(mems)
    return entries_for_tool(mems, parsed, vault_root, dev, tool)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_memview_entries.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/memview.py tests/hub/test_memview_entries.py
git commit -m "feat(hub): MemoryViewEntry + collect_view_entries (scan/filter/validate)"
```

---

## Task 8: 三个视图渲染器

**Files:**
- Modify: `hub/memview.py`
- Test: `tests/hub/test_memview_render.py`

**Interfaces:**
- Consumes: `MemoryViewEntry`、`hub.model.Memory`。
- Produces: `hub.memview.shared_hash(memories) -> str`（全部 shared 记忆内容的短哈希，供新鲜度比对）；`hub.memview.render_view_file(entries, tool, shared_hash="") -> str`（薄索引，绝对路径 `<...>`，头部嵌 `shared_hash`）；`hub.memview.render_codex_block(entries) -> str`（紧凑，仅 name/description/scope，无绝对路径）；`hub.memview.EMPTY_VIEW_NOTE`（空结果占位常量）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_memview_render.py
from pathlib import Path
from hub.memview import MemoryViewEntry, render_view_file, render_codex_block

def _e(name, scope):
    return MemoryViewEntry(name=name, description=f"{name} desc", scope=scope,
                           source=Path("C:/hub-vault/shared/memory") / f"{name}.md")

def test_view_file_has_absolute_angle_bracket_links(tmp_path):
    out = render_view_file([_e("a", ["global"])], "claude")
    assert "- [a](<C:/hub-vault/shared/memory/a.md>)" in out
    assert "自动生成" in out

def test_view_file_uses_forward_slashes(tmp_path):
    out = render_view_file([_e("a", ["global"])], "codex")
    assert "\\" not in out.split("](<")[1].split(">)")[0]   # 链接段无反斜杠

def test_view_file_empty_has_placeholder():
    out = render_view_file([], "opencode")
    assert "无匹配共享记忆" in out

def test_codex_block_is_compact_no_paths():
    out = render_codex_block([_e("a", ["project:xinao"])])
    assert "`a`" in out and "a desc" in out and "project:xinao" in out
    assert "shared/memory" not in out                    # 不含绝对/相对源路径
    assert "$hub-memory" in out                            # 指到 skill 读正文

def test_codex_block_empty_has_placeholder():
    assert "无匹配共享记忆" in render_codex_block([])

def test_view_file_embeds_shared_hash():
    from hub.memview import render_view_file
    out = render_view_file([_e("a", ["global"])], "claude", shared_hash="deadbeef")
    assert "<!-- shared_hash: deadbeef -->" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_memview_render.py -v`
Expected: FAIL（渲染器不存在）

- [ ] **Step 3: 写实现**

在 `hub/memview.py` 追加：

```python
import hashlib

EMPTY_VIEW_NOTE = "（当前设备/该工具无匹配共享记忆）"

def shared_hash(memories: list["Memory"]) -> str:
    """全部 shared 记忆内容的短哈希——status --check 用它判视图是否陈旧。
    必须含 description（它进视图索引，改了就该判 stale）。"""
    h = hashlib.sha256()
    for m in sorted(memories, key=lambda x: x.name):
        for part in (m.name, m.description, m.body, " ".join(m.scope)):
            h.update(part.encode("utf-8")); h.update(b"\0")
    return h.hexdigest()[:16]

def _abs_posix(p: Path) -> str:
    return p.as_posix()

def render_view_file(entries: list["MemoryViewEntry"], tool: str, shared_hash: str = "") -> str:
    """~/.hub/views/<tool>/MEMORY.md：薄索引，绝对源路径用 <...> 包（空格安全）、/ 分隔。
    只把金库相对地址变本机绝对地址，不展开正文符号根。头部嵌 shared_hash 供新鲜度比对。"""
    head = (f"<!-- 自动生成，勿手改：hub memory 视图（{tool}）。正文用 $hub-memory skill 按名读 -->\n"
            f"<!-- shared_hash: {shared_hash} -->\n"
            f"# 共享记忆索引 — {tool}\n\n")
    if not entries:
        return head + EMPTY_VIEW_NOTE + "\n"
    rows = [f"- [{e.name}](<{_abs_posix(e.source)}>)\n  — {e.description}\n  — scope: `{' '.join(e.scope)}`"
            for e in entries]
    return head + "\n".join(rows) + "\n"

def render_codex_block(entries: list["MemoryViewEntry"]) -> str:
    """Codex AGENTS.md 内联紧凑索引：仅 name/description/scope，无绝对路径。"""
    head = "## 共享记忆索引（自动生成，勿手改）\n\n"
    if not entries:
        return head + EMPTY_VIEW_NOTE + "\n"
    rows = [f"- `{e.name}` — {e.description} — scope: `{' '.join(e.scope)}`" for e in entries]
    tail = "\n\n正文请用 `$hub-memory` skill 按名读取；不要一次性加载全部正文。\n"
    return head + "\n".join(rows) + tail
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_memview_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/memview.py tests/hub/test_memview_render.py
git commit -m "feat(hub): memory view renderers (view file + codex compact block)"
```

---

## Task 9: 受管块编辑器 textblock

**Files:**
- Create: `hub/textblock.py`
- Test: `tests/hub/test_textblock.py`

**Interfaces:**
- Produces: `hub.textblock.upsert_block(text: str, body: str) -> str`（无标记→追加块；正好一对合法标记→只换块内、保留块外；重复/缺半边/错序/嵌套→抛 `BlockError`）；`hub.textblock.has_one_valid_block(text) -> bool`（status 判块良构用）；`hub.textblock.BEGIN`/`END` 标记常量；`class BlockError(RuntimeError)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_textblock.py
import pytest
from hub.textblock import upsert_block, BlockError, BEGIN, END

def test_append_when_absent():
    out = upsert_block("user stuff\n", "HELLO")
    assert "user stuff" in out and BEGIN in out and END in out and "HELLO" in out

def test_replace_inside_preserves_outside():
    src = f"top\n{BEGIN}\nold\n{END}\nbottom\n"
    out = upsert_block(src, "NEW")
    assert "top" in out and "bottom" in out and "NEW" in out and "old" not in out

def test_idempotent():
    once = upsert_block("x\n", "B")
    assert upsert_block(once, "B") == once

def test_duplicate_markers_raise():
    src = f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}\n"
    with pytest.raises(BlockError):
        upsert_block(src, "N")

def test_missing_end_raises():
    with pytest.raises(BlockError):
        upsert_block(f"{BEGIN}\nno end\n", "N")

def test_reversed_markers_raise():
    with pytest.raises(BlockError):
        upsert_block(f"{END}\nx\n{BEGIN}\n", "N")

def test_has_one_valid_block():
    from hub.textblock import has_one_valid_block
    assert has_one_valid_block(f"{BEGIN}\nx\n{END}\n") is True
    assert has_one_valid_block("no markers") is False
    assert has_one_valid_block(f"{BEGIN}\nno end\n") is False           # 缺半边
    assert has_one_valid_block(f"{BEGIN}\na\n{END}\n{BEGIN}\nb\n{END}") is False  # 重复
    assert has_one_valid_block(f"{END}\nx\n{BEGIN}\n") is False         # 颠倒
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_textblock.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

```python
# hub/textblock.py
"""通用受管块编辑：<!-- hub:begin --> … <!-- hub:end -->。

无标记→在末尾追加块；正好一对合法标记→只替换块内、保留块外用户文本；
重复/缺半边/错序/嵌套→抛 BlockError（校验失败，调用方据此零写入，旧文件不动）。
块内用户手改的内容下次会被覆盖——块头已写"自动生成，勿手改"。
"""
BEGIN = "<!-- hub:begin -->"
END = "<!-- hub:end -->"

class BlockError(RuntimeError):
    pass

def _positions(text: str, marker: str) -> list[int]:
    out, i = [], text.find(marker)
    while i != -1:
        out.append(i)
        i = text.find(marker, i + len(marker))
    return out

def upsert_block(text: str, body: str) -> str:
    begins, ends = _positions(text, BEGIN), _positions(text, END)
    if not begins and not ends:
        sep = "" if text == "" or text.endswith("\n") else "\n"
        return f"{text}{sep}{BEGIN}\n{body.rstrip(chr(10))}\n{END}\n"
    if len(begins) != 1 or len(ends) != 1:
        raise BlockError(f"受管块标记不成对/重复（begin×{len(begins)}, end×{len(ends)}），拒绝写入")
    b, e = begins[0], ends[0]
    if b > e:
        raise BlockError("受管块标记顺序颠倒（end 在 begin 之前），拒绝写入")
    before, after = text[:b], text[e + len(END):]
    return f"{before}{BEGIN}\n{body.rstrip(chr(10))}\n{END}{after}"

def has_one_valid_block(text: str) -> bool:
    """恰好一对、顺序正确的受管块 → True；缺失/重复/缺半边/颠倒 → False。
    status --check 用它判受管块良构（不能只 `"hub:begin" in text` 就算 ok）。"""
    b, e = _positions(text, BEGIN), _positions(text, END)
    return len(b) == 1 and len(e) == 1 and b[0] < e[0]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_textblock.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/textblock.py tests/hub/test_textblock.py
git commit -m "feat(hub): managed text-block upsert with strict marker validation"
```

---

## Task 10: opencode instructions 写入器

**Files:**
- Create: `hub/opencode_cfg.py`
- Test: `tests/hub/test_opencode_cfg.py`

**Interfaces:**
- Consumes: `hub.writer.Writer.write_text_atomic`、`hub.model.DeviceProfile`。
- Produces: `hub.opencode_cfg.opencode_config_path(dev) -> Path`（优先 `dev.paths["OPENCODE_CONFIG"]`，缺省 `~/.config/opencode/opencode.json`）；`@dataclass OpencodePlan(action, config_path, entry, new_text=None, log_text=None, reason=None)`，`action ∈ {"present","add","refuse"}`；`hub.opencode_cfg.plan_instruction(dev, view_path) -> OpencodePlan`（**纯只读**：缺 instructions→创建、`list[str]`→去重追加、其余（JSONC/解析失败/instructions 非数组）→ `refuse` 且 `reason` 含手动条目，**绝不抛异常、绝不覆盖**）；`hub.opencode_cfg.commit_instruction(plan, w, backups_dir) -> None`（action=="add" 才写：最小回滚日志 + 原子写配置）。**refuse 是数据不是异常**——由编排方降为 warning/status degraded，不阻断主链路。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_opencode_cfg.py
import json
from pathlib import Path
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.opencode_cfg import plan_instruction, commit_instruction

def _dev(cfg): return DeviceProfile(host="b", classes=[], projects=[],
                                    paths={"OPENCODE_CONFIG": str(cfg)}, sources={})

def test_adds_to_existing_array(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"model": "x", "instructions": ["a.md"]}), encoding="utf-8")
    view = tmp_path / "v" / "MEMORY.md"
    plan = plan_instruction(_dev(cfg), view)
    assert plan.action == "add"
    commit_instruction(plan, Writer(), tmp_path / "bk")
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert view.as_posix() in data["instructions"] and "a.md" in data["instructions"]
    assert data["model"] == "x"                          # 其余键保留

def test_creates_array_when_absent(tmp_path):
    cfg = tmp_path / "opencode.json"; cfg.write_text("{}", encoding="utf-8")
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    commit_instruction(plan, Writer(), tmp_path / "bk")
    assert "instructions" in json.loads(cfg.read_text(encoding="utf-8"))

def test_dedup_is_present_noop(tmp_path):
    cfg = tmp_path / "opencode.json"; view = tmp_path / "v.md"
    cfg.write_text(json.dumps({"instructions": [view.as_posix()]}), encoding="utf-8")
    plan = plan_instruction(_dev(cfg), view)
    assert plan.action == "present"
    w = Writer(); commit_instruction(plan, w, tmp_path / "bk")
    assert w.written == []

def test_jsonc_refused_no_write(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text('{\n  // comment\n  "model": "x"\n}', encoding="utf-8")
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "refuse" and "instructions" in plan.reason
    w = Writer(); commit_instruction(plan, w, tmp_path / "bk")
    assert w.written == []                               # refuse 不写、不抛

def test_instructions_not_a_list_refused_not_overwritten(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": "one.md"}), encoding="utf-8")  # 是字符串不是数组
    plan = plan_instruction(_dev(cfg), tmp_path / "v.md")
    assert plan.action == "refuse"
    commit_instruction(plan, Writer(), tmp_path / "bk")
    assert json.loads(cfg.read_text(encoding="utf-8"))["instructions"] == "one.md"  # 原值没被覆盖

def test_rollback_log_written_no_key_copy(tmp_path):
    cfg = tmp_path / "opencode.json"
    cfg.write_text(json.dumps({"instructions": []}), encoding="utf-8")
    bk = tmp_path / "bk"
    commit_instruction(plan_instruction(_dev(cfg), tmp_path / "v.md"), Writer(), bk)
    logs = list(bk.glob("opencode-*.log"))
    assert logs and "hash" in logs[0].read_text(encoding="utf-8")
    assert not list(bk.glob("*opencode.json"))           # 不复制整份密钥文件
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_opencode_cfg.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

```python
# hub/opencode_cfg.py
"""opencode.json 的 instructions[] 写入。该文件含明文密钥（guard 范畴）。

拆成 plan（纯只读）/ commit（写）两段，让编排方能在写任何东西之前完成全量预检。
- 路径：优先 device.toml 的 OPENCODE_CONFIG，缺省 ~/.config/opencode/opencode.json。
- **能严格 json.loads 且 instructions 缺失或是 list[str] 才改**：缺失→创建、list→去重追加。
- 以下一律 refuse（**不抛异常、绝不覆盖**，由编排方降为 warning）：注释/尾逗号/解析失败、
  顶层非对象、`instructions` 存在但**不是数组**（曾经会被静默换成新数组、毁掉用户数据）。
- 保留未知键，但**不声称保留原格式**（json.dumps 会重排版）。
- 不复制整份密钥文件；只写最小回滚日志（路径/改前哈希/原 instructions 是缺失还是具体值/本次条目）。
"""
import hashlib, json, time, uuid
from dataclasses import dataclass
from pathlib import Path
from hub.writer import Writer

@dataclass
class OpencodePlan:
    action: str                     # "present" | "add" | "refuse"
    config_path: Path
    entry: str
    new_text: str | None = None
    log_text: str | None = None
    reason: str | None = None

def opencode_config_path(dev) -> Path:
    p = dev.paths.get("OPENCODE_CONFIG")
    return Path(p) if p else Path.home() / ".config" / "opencode" / "opencode.json"

def _manual(cfg: Path, entry: str, why: str) -> str:
    return (f"{why} hub 不敢重写带密钥的 {cfg}。请手工在 instructions 数组里加一行："
            f"{json.dumps(entry, ensure_ascii=False)}")

def plan_instruction(dev, view_path: Path) -> OpencodePlan:
    cfg = opencode_config_path(dev)
    entry = Path(view_path).as_posix()
    raw = cfg.read_text(encoding="utf-8") if cfg.exists() else "{}"
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("顶层不是对象")
    except ValueError:
        return OpencodePlan("refuse", cfg, entry,
                            reason=_manual(cfg, entry, "不是严格 JSON（可能含注释/尾逗号）。"))
    old = data.get("instructions")
    if old is None:
        new_list = [entry]
    elif isinstance(old, list):
        if entry in old:
            return OpencodePlan("present", cfg, entry)
        new_list = list(old) + [entry]
    else:
        return OpencodePlan("refuse", cfg, entry,
                            reason=_manual(cfg, entry, "instructions 存在但不是数组。"))
    data["instructions"] = new_list
    log = (f"path={cfg}\nhash={hashlib.sha256(raw.encode('utf-8')).hexdigest()}\n"
           f"instructions_before={'MISSING' if old is None else json.dumps(old, ensure_ascii=False)}\n"
           f"added={entry}\n")
    return OpencodePlan("add", cfg, entry,
                        new_text=json.dumps(data, ensure_ascii=False, indent=2) + "\n", log_text=log)

def commit_instruction(plan: OpencodePlan, w: Writer, backups_dir: Path) -> None:
    if plan.action != "add":
        return
    # 先写配置：若它失败，异常上抛、**不留假日志**（避免"日志说改了、配置其实没动"）。
    w.write_text_atomic(plan.config_path, plan.new_text)
    if plan.log_text:
        # 配置写成功后才记回滚日志；文件名带 uuid，防同秒多次调用互相覆盖。
        name = f"opencode-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.log"
        w.write_text_atomic(backups_dir / name, plan.log_text)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_opencode_cfg.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/opencode_cfg.py tests/hub/test_opencode_cfg.py
git commit -m "feat(hub): opencode instructions writer (refuse-safe JSONC, atomic, rollback log)"
```

---

## Task 11: ~/.hub/config.toml + memory-read 核心 + CLI

**Files:**
- Create: `hub/hubconfig.py`、`hub/memread.py`
- Modify: `hub/cli.py`
- Test: `tests/hub/test_hubconfig.py`、`tests/hub/test_memread.py`

**Interfaces:**
- Consumes: `hub.vault.load_device`/`load_vault`、`hub.memview.collect_view_entries`、`hub.frontmatter.load_memory`、`hub.links.resolve_symbols`、`hub.writer.Writer.write_text_atomic`。
- Produces: `hub.hubconfig.hub_config_path() -> Path`（`~/.hub/config.toml`）；`hub.hubconfig.backups_dir() -> Path`（`~/.hub/backups`）；`hub.hubconfig.check_config(vault_root, host) -> None`（只读冲突检查，已绑定不同 vault/host→抛 `ConfigConflict`）；`hub.hubconfig.write_config(vault_root, host, hub_root, w) -> None`（先 check 后原子写）；`hub.hubconfig.read_config() -> dict`；`class ConfigConflict(RuntimeError)`；`hub.memread.read_memory(vault_root, host, tool, name) -> str`（名字不在该 tool 视图→抛 `MemoryNotInView`）；`class MemoryNotInView(RuntimeError)`。CLI：`hub memory-read --vault <v> --host <h> --tool <t> --name <n>`（`--vault` 可省，省则读 config）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_hubconfig.py
import pytest
from hub.hubconfig import write_config, read_config, ConfigConflict, hub_config_path
from hub.writer import Writer

def test_write_and_read(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    write_config(tmp_path / "vault", "box", tmp_path / "repo", Writer())
    cfg = read_config()
    assert cfg["host"] == "box" and cfg["vault"].endswith("vault")

def test_conflict_on_different_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    write_config(tmp_path / "v1", "box", tmp_path / "repo", Writer())
    with pytest.raises(ConfigConflict):
        write_config(tmp_path / "v2", "box", tmp_path / "repo", Writer())
```

```python
# tests/hub/test_memread.py
import pytest
from pathlib import Path
from hub.memread import read_memory, MemoryNotInView

def _setup(vault, host, name, scope, body):
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (vault / host).mkdir(parents=True, exist_ok=True)
    (vault / host / "device.toml").write_text(
        "class = []\nprojects = []\n[paths]\nVAULT = \"" + vault.as_posix() + "\"\n",
        encoding="utf-8")
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\n{body}\n", encoding="utf-8")

def test_reads_in_scope_and_expands_symbols(tmp_path):
    _setup(tmp_path, "box", "a", "[global]", "see $VAULT/shared/memory/a.md")
    out = read_memory(tmp_path, "box", "claude", "a")
    assert tmp_path.as_posix() in out                    # 符号根展开成本机绝对路径
    assert "$VAULT" not in out

def test_refuses_out_of_scope(tmp_path):
    _setup(tmp_path, "box", "a", "[tool:codex]", "body")
    with pytest.raises(MemoryNotInView):                  # claude 视图里没有它
        read_memory(tmp_path, "box", "claude", "a")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_hubconfig.py tests/hub/test_memread.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写实现**

```python
# hub/hubconfig.py
"""本机 hub 指针：~/.hub/config.toml（vault / host / hub_root）+ ~/.hub/backups。

register 写它，memory-read 缺 --vault 时读它，skill 包装脚本靠 hub_root 找到 hub。
已存在且指向不同 vault/host → 冲突停下，不覆盖（一台机被绑到另一个金库时要人来决定）。
不进金库、collect 不收。
"""
import os, tomllib
from pathlib import Path
from hub.writer import Writer

class ConfigConflict(RuntimeError):
    pass

def _hub_home() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub"))

def hub_config_path() -> Path:
    return _hub_home() / "config.toml"

def backups_dir() -> Path:
    return _hub_home() / "backups"

def read_config() -> dict:
    p = hub_config_path()
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

def _canon(p) -> str:
    """canonical 绝对 posix 路径——config 存它，保证 skill 从任意 cwd 启动都能定位。"""
    return Path(p).resolve().as_posix()

def check_config(vault_root: Path, host: str) -> None:
    """只读冲突检查（供 register 先检后写）：已绑定到不同 vault/host → 抛 ConfigConflict，不写。"""
    cur = read_config()
    if cur and (cur.get("host") != host or cur.get("vault") != _canon(vault_root)):
        raise ConfigConflict(
            f"~/.hub/config.toml 已绑定 vault={cur.get('vault')} host={cur.get('host')}，"
            f"与本次 vault={_canon(vault_root)} host={host} 不符。停下来让你决定，不覆盖。")

def write_config(vault_root: Path, host: str, hub_root: Path, w: Writer) -> None:
    check_config(vault_root, host)
    body = (f'vault = "{_canon(vault_root)}"\n'
            f'host = "{host}"\n'
            f'hub_root = "{_canon(hub_root)}"\n')
    w.write_text_atomic(hub_config_path(), body)
```

```python
# hub/memread.py
"""memory-read 核心：只在本机该 tool 的视图里查名（拒读越 scope），读 canonical 正文，
在内存里用 device.toml 的 [paths] 展开符号根，返回正文。不写第二份、不改 shared。"""
from pathlib import Path
from hub.vault import load_device
from hub.memview import collect_view_entries
from hub.frontmatter import load_memory
from hub.links import resolve_symbols

class MemoryNotInView(RuntimeError):
    pass

def read_memory(vault_root: Path, host: str, tool: str, name: str) -> str:
    dev = load_device(vault_root, host)
    entries = {e.name: e for e in collect_view_entries(vault_root, dev, tool)}
    if name not in entries:
        raise MemoryNotInView(f"记忆 {name!r} 不在本机 {tool} 视图里（不存在或越 scope），拒读。")
    m = load_memory(entries[name].source)
    body, _missing = resolve_symbols(m.body, dev.paths)
    return body
```

`hub/cli.py`：handler + 子命令（`--vault` 变为可省，省则读 config）：
```python
from hub.hubconfig import read_config
from hub.memread import read_memory, MemoryNotInView
from hub.memview import ViewScopeError, SharedMemoryError

def _cmd_memory_read(args) -> int:
    vault = args.vault or read_config().get("vault")
    host = args.host or read_config().get("host") or current_host()
    if not vault:
        print("没有 --vault 也没有 ~/.hub/config.toml，无法定位金库"); return 1
    try:
        print(read_memory(Path(vault), host, args.tool, args.name), end="")
    except (MemoryNotInView, FileNotFoundError, ViewScopeError, SharedMemoryError) as e:
        print(e); return 1
    return 0
```
在 `build_parser` 里（**不**用 `common`，因为它要求 `--vault`；单独建 parser）：
```python
    mr = sub.add_parser("memory-read")
    mr.add_argument("--vault", default=None)
    mr.add_argument("--host", default=None)
    mr.add_argument("--tool", required=True, choices=["claude", "codex", "opencode"])
    mr.add_argument("--name", required=True)
    mr.set_defaults(func=_cmd_memory_read)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_hubconfig.py tests/hub/test_memread.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/hubconfig.py hub/memread.py hub/cli.py tests/hub/test_hubconfig.py tests/hub/test_memread.py
git commit -m "feat(hub): ~/.hub/config.toml + memory-read (scope-scoped, symbol-expanded)"
```

---

## Task 12: hub-memory skill 文件

**Files:**
- Create: `hub/skills/hub-memory/SKILL.md`、`hub/skills/hub-memory/scripts/read_memory.py`
- Test: `tests/hub/test_hub_memory_skill.py`

**Interfaces:**
- Consumes: `hub memory-read` CLI（Task 11）、`~/.hub/config.toml` 的 `hub_root`。
- Produces: `hub/skills/hub-memory/scripts/read_memory.py`（稳定启动包装：读 config 的 `hub_root`，转调 `py -3 -m hub.cli memory-read`，核心逻辑不重复实现）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_hub_memory_skill.py
from pathlib import Path

def test_skill_files_exist():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts" / "read_memory.py").is_file()

def test_skill_md_frontmatter():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    txt = (root / "SKILL.md").read_text(encoding="utf-8")
    assert txt.startswith("---")
    assert "name: hub-memory" in txt and "description:" in txt

def test_wrapper_delegates_not_reimplements():
    root = Path(__file__).resolve().parents[2] / "hub" / "skills" / "hub-memory"
    src = (root / "scripts" / "read_memory.py").read_text(encoding="utf-8")
    assert "hub.cli" in src and "memory-read" in src      # 只转调，不自己解析记忆
    assert "resolve_symbols" not in src                    # 核心逻辑不在包装里
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_hub_memory_skill.py -v`
Expected: FAIL（文件不存在）

- [ ] **Step 3: 写文件**

`hub/skills/hub-memory/SKILL.md`：
```markdown
---
name: hub-memory
description: 按名读取 hub 金库共享记忆的正文（在本机该工具视图范围内，自动展开符号根）。当你在自动加载的"共享记忆索引"里看到某条记忆、需要它的完整正文时使用。
---

# hub-memory

自动加载的**索引**（CLAUDE.md/AGENTS.md 受管块或视图文件）只给了 name / 一句话
description / scope；要读某条记忆的**正文**时，用本 skill。

## 怎么用

对当前工具（claude / codex / opencode）跑：

    py -3 <此skill>/scripts/read_memory.py --tool <当前工具> --name <记忆名>

包装脚本会从 `~/.hub/config.toml` 读金库位置与 `hub_root`，转调 `hub memory-read`，
在**本机该工具视图范围内**按名取正文并把符号根（`$VAULT` 等）展开成本机真实路径。
名字不在视图里（不存在或越 scope）会被拒绝——这是有意的，别绕过。

**只读**：本 skill 从不写金库、不改记忆、不落第二份展开文件。
```

`hub/skills/hub-memory/scripts/read_memory.py`：
```python
#!/usr/bin/env python3
"""hub-memory skill 的稳定启动包装：只负责找到 hub 并转调 `hub memory-read`。
核心逻辑（查视图、读正文、展开符号根）唯一落在 hub 模块/CLI，这里不重复实现。"""
import os, subprocess, sys, tomllib
from pathlib import Path

def _hub_root() -> str | None:
    cfg = Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub")) / "config.toml"
    if cfg.exists():
        return tomllib.loads(cfg.read_text(encoding="utf-8")).get("hub_root")
    return None

def main(argv: list[str]) -> int:
    root = _hub_root()
    env = dict(os.environ)
    if root:
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    # 转调 hub CLI 的 memory-read；--vault/--host 由 CLI 从 ~/.hub/config.toml 补全
    return subprocess.run([sys.executable, "-m", "hub.cli", "memory-read", *argv], env=env).returncode

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_hub_memory_skill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/skills/hub-memory/SKILL.md hub/skills/hub-memory/scripts/read_memory.py tests/hub/test_hub_memory_skill.py
git commit -m "feat(hub): ship hub-memory skill (thin wrapper delegating to memory-read)"
```

---

## Task 13: register 扩展 —— 装 hub-memory + 写 config.toml + 生成视图/块/opencode + refresh

**Files:**
- Modify: `hub/register.py`、`hub/cli.py`
- Create: `hub/memwire.py`（视图/块/opencode 的落盘编排，register 与 refresh 共用）
- Test: `tests/hub/test_memwire.py`、`tests/hub/test_register_memory.py`

**Interfaces:**
- Consumes: `hub.memview.load_shared_memories`/`validate_scopes`/`entries_for_tool`/`render_view_file`/`render_codex_block`/`shared_hash`、`hub.textblock.upsert_block`/`BlockError`、`hub.opencode_cfg.plan_instruction`/`commit_instruction`、`hub.hubconfig`、`hub.writer.Writer.write_text_atomic`、`hub.fslink`。
- Produces（**全部 prepare/validate → commit**）：`hub.memwire.prepare_memory_views(vault_root, dev) -> (writes: list[tuple[Path,str]], warnings: list[str], opencode_plan)`（**纯只读**，只扫一次 shared、内存切三份子集、渲染全部目标；ViewScopeError/BlockError 在此抛、零副作用；opencode refuse 归 warnings）；`hub.memwire.commit_memory_views(writes, plan, w) -> None`；`hub.memwire.wire_memory_views(vault_root, dev, w) -> dict`（= prepare+commit，refresh 用）；`hub.memwire.hub_views_home() -> Path`。register 侧 plan/commit 拆分：`hub.register.plan_register_skills(vault_root, dev) -> (to_link, ensured)`、`commit_register_skills(to_link, w)`、`plan_hub_memory_skill(hub_root, dev) -> list[tuple[Path,Path]]`、`commit_hub_memory_skill(links, w) -> list[str]`（wrapper `register_skills`/`install_hub_memory_skill` 保留）。CLI：`hub refresh --vault <v> [--dry-run]`；`_cmd_register` 改成**先全量预检、后统一提交**。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_memwire.py
import pytest
from pathlib import Path
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.memwire import wire_memory_views, prepare_memory_views, hub_views_home
from hub.textblock import BEGIN, END, BlockError

def _dev(tmp_path):
    return DeviceProfile(host="box", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "CODEX_HOME": (tmp_path / ".codex").as_posix(),
        "OPENCODE_CONFIG": (tmp_path / "opencode.json").as_posix(),
    }, sources={})

def _shared_mem(vault, name, scope):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: {name}d\nmetadata:\n  type: reference\n"
        f"  scope: {scope}\n---\n\nbody\n", encoding="utf-8")

def test_wires_three_views_and_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()
    assert (hub_views_home() / "codex" / "MEMORY.md").exists()
    claude_md = (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "hub:begin" in claude_md and "@" in claude_md   # Claude @import 指针
    assert "`a`" in (tmp_path / ".codex" / "AGENTS.md").read_text(encoding="utf-8")  # Codex 内联

def test_codex_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "AGENTS.override.md").write_text("my override\n", encoding="utf-8")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert "hub:begin" in (tmp_path / ".codex" / "AGENTS.override.md").read_text(encoding="utf-8")
    assert not (tmp_path / ".codex" / "AGENTS.md").exists()  # 没写被遮蔽的那份

def test_deterministic_error_leaves_no_partial_views(tmp_path, monkeypatch):
    # #2 关键回归：CLAUDE.md 里有坏受管块（重复标记）→ 预检期抛 BlockError、三份视图一个都不该落
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    claude = tmp_path / ".claude"; claude.mkdir()
    (claude / "CLAUDE.md").write_text(f"{BEGIN}\nx\n{END}\n{BEGIN}\ny\n{END}\n", encoding="utf-8")
    with pytest.raises(BlockError):
        wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert not (hub_views_home() / "claude" / "MEMORY.md").exists()   # 没留半套视图

def test_opencode_refuse_is_warning_not_failure(tmp_path, monkeypatch):
    # #5：opencode 是 JSONC → refuse 归 warnings，不抛、不阻断视图落盘
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text('{\n  // c\n}', encoding="utf-8")
    summary = wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()
    assert any("opencode" in x for x in summary["warnings"])

def test_commit_partial_then_rerun_converges(tmp_path, monkeypatch):
    # spec §9.7：提交期第 N 次写失败 → 可能部分完成、不回滚；重跑 wire 幂等收敛
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _shared_mem(tmp_path, "a", "[global]")
    (tmp_path / "opencode.json").write_text("{}", encoding="utf-8")
    real = Writer.write_text_atomic
    n = {"i": 0}
    def flaky(self, path, text):
        n["i"] += 1
        if n["i"] == 2:                         # 第 2 次写（codex 视图）失败
            raise OSError("boom")
        return real(self, path, text)
    monkeypatch.setattr(Writer, "write_text_atomic", flaky)
    with pytest.raises(OSError):
        wire_memory_views(tmp_path, _dev(tmp_path), Writer())
    assert (hub_views_home() / "claude" / "MEMORY.md").exists()   # 部分完成：第一份在
    monkeypatch.setattr(Writer, "write_text_atomic", real)         # 恢复正常
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())          # 重跑收敛
    for t in ("claude", "codex", "opencode"):
        assert (hub_views_home() / t / "MEMORY.md").exists()
    assert "hub:begin" in (tmp_path / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
```

```python
# tests/hub/test_register_memory.py
from pathlib import Path
from hub.writer import Writer
from hub.model import DeviceProfile
from hub.register import install_hub_memory_skill

def test_installs_hub_memory_by_link(tmp_path):
    repo = tmp_path / "repo"; (repo / "hub" / "skills" / "hub-memory").mkdir(parents=True)
    (repo / "hub" / "skills" / "hub-memory" / "SKILL.md").write_text("---\nname: hub-memory\n---\n", encoding="utf-8")
    dev = DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "AGENTS_HOME": (tmp_path / ".agents").as_posix()}, sources={})
    install_hub_memory_skill(repo, dev, Writer())
    assert (tmp_path / ".claude" / "skills" / "hub-memory").exists()
    assert (tmp_path / ".agents" / "skills" / "hub-memory").exists()

def test_hub_memory_name_collision_zero_write(tmp_path):
    # 金库里若也有一把名为 hub-memory 的普通 shared skill → 与随包 hub-memory 撞同一链接路径，
    # 跨来源冲突预检必须在提交前拦下（零写）
    import pytest
    from hub.register import (plan_register_skills, plan_hub_memory_skill,
                              check_link_collisions, RegisterConflict)
    (tmp_path / "shared" / "skills" / "hub-memory").mkdir(parents=True)
    (tmp_path / "shared" / "skills" / "hub-memory" / "SKILL.md").write_text("# vault\n", encoding="utf-8")
    repo = tmp_path / "repo"; (repo / "hub" / "skills" / "hub-memory").mkdir(parents=True)
    (repo / "hub" / "skills" / "hub-memory" / "SKILL.md").write_text("# bundled\n", encoding="utf-8")
    dev = DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "AGENTS_HOME": (tmp_path / ".agents").as_posix()}, sources={})
    to_link, _ = plan_register_skills(tmp_path, dev)
    hm = plan_hub_memory_skill(repo, dev)
    with pytest.raises(RegisterConflict):
        check_link_collisions(to_link, hm)          # 提交前拦下，什么都没建
    assert not (tmp_path / ".claude" / "skills").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_memwire.py tests/hub/test_register_memory.py -v`
Expected: FAIL（模块/函数不存在）

- [ ] **Step 3: 写实现**

```python
# hub/memwire.py
"""memory 视图/受管块/opencode 条目的落盘编排。**prepare/validate all → commit writes**：
先只读预检并渲染全部目标 (path, text)（确定性错误 ViewScopeError/BlockError 在此抛、零副作用），
再逐个原子写。opencode 的 refuse 归 warnings、不抛不阻断。提交期 I/O 故障才可能部分完成、重跑收敛。
**一次扫 shared、内存里切三份工具子集**——三种产物绝不各扫各的。
"""
import os
from pathlib import Path
from hub.memview import (load_shared_memories, validate_scopes, entries_for_tool,
                         render_view_file, render_codex_block, shared_hash)
from hub.textblock import upsert_block
from hub.opencode_cfg import plan_instruction, commit_instruction
from hub.hubconfig import backups_dir
from hub.writer import Writer

_TOOLS = ("claude", "codex", "opencode")

def hub_views_home() -> Path:
    return Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub")) / "views"

def _view_path(tool: str) -> Path:
    return hub_views_home() / tool / "MEMORY.md"

def _codex_agents_target(dev) -> Path:
    """Codex 受管块目标：活动的非空 AGENTS.override.md 优先，否则 AGENTS.md。"""
    home = Path(dev.paths["CODEX_HOME"])
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8").strip():
        return override
    return home / "AGENTS.md"

def prepare_memory_views(vault_root: Path, dev):
    """只读预检 + 渲染全部目标。返回 (writes, warnings, opencode_plan)。
    ViewScopeError/BlockError 在此抛、零副作用；opencode refuse 归 warnings。"""
    mems = load_shared_memories(vault_root)                 # 只扫一次
    parsed = validate_scopes(mems)                           # scope 非法→ViewScopeError
    sh = shared_hash(mems)
    per_tool = {t: entries_for_tool(mems, parsed, vault_root, dev, t) for t in _TOOLS}
    writes: list[tuple[Path, str]] = []
    warnings: list[str] = []
    for t in _TOOLS:
        writes.append((_view_path(t), render_view_file(per_tool[t], t, sh)))
    if dev.paths.get("CLAUDE_HOME"):
        claude_md = Path(dev.paths["CLAUDE_HOME"]) / "CLAUDE.md"
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        body = f"# hub 共享记忆（自动生成，勿手改）\n@{_view_path('claude').as_posix()}"
        writes.append((claude_md, upsert_block(existing, body)))   # 坏块→BlockError（预检期）
    if dev.paths.get("CODEX_HOME"):
        target = _codex_agents_target(dev)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        writes.append((target, upsert_block(existing, render_codex_block(per_tool["codex"]))))
    plan = None
    if dev.paths.get("OPENCODE_CONFIG") or (Path.home() / ".config" / "opencode" / "opencode.json").exists():
        plan = plan_instruction(dev, _view_path("opencode"))
        if plan.action == "refuse":
            warnings.append(f"opencode: {plan.reason}")
    return writes, warnings, plan

def commit_memory_views(writes, plan, w: Writer) -> None:
    for path, text in writes:
        w.write_text_atomic(path, text)
    if plan is not None:
        commit_instruction(plan, w, backups_dir())

def wire_memory_views(vault_root: Path, dev, w: Writer) -> dict:
    writes, warnings, plan = prepare_memory_views(vault_root, dev)   # 全量预检；确定性错误→零写
    commit_memory_views(writes, plan, w)
    return {"written": len(writes), "warnings": warnings}
```

`hub/register.py`：把 `register_skills` 拆成 **plan/commit**（预检零写、提交才建链），并加 hub-memory 的 plan/commit：
```python
def plan_register_skills(vault_root, dev):
    """register_skills 的只读预检（含 Task 1/2 的容器与逃逸检查）：返回 (to_link, ensured)；
    任何冲突→RegisterConflict/SharedSkillsEscape，零写入。"""
    vault_root = Path(vault_root)
    shared = shared_skills_dir(vault_root)             # 容器逃逸→抛（Task 1）
    skills = sorted((d for d in shared.iterdir() if d.is_dir()), key=lambda p: p.name) \
        if shared.is_dir() else []
    for d in skills:
        if not within_shared_skills(d, vault_root):    # 单名逃逸→抛（Task 1）
            raise SharedSkillsEscape(f"shared/skills/{d.name} 经链接逃出金库，register 拒绝、零写入。")
    to_link: list[tuple[Path, Path]] = []
    ensured: list[str] = []
    conflicts: list[str] = []
    for target_dir in skill_targets(dev):
        if os.path.lexists(target_dir):                # 容器必须真目录（Task 2）
            real = os.path.realpath(target_dir)
            expected = os.path.join(os.path.realpath(target_dir.parent), target_dir.name)
            if not target_dir.is_dir() or real != expected:
                conflicts.append(f"{target_dir}（skills 容器必须是真目录，不能是链接/文件）")
                continue
        for src in skills:
            link = target_dir / src.name
            label = f"{target_dir}{os.sep}{src.name}"
            if not os.path.lexists(link):
                to_link.append((src, link)); ensured.append(label)
            elif resolves_to(link, src):
                ensured.append(label)
            else:
                conflicts.append(label)
    if conflicts:
        raise RegisterConflict(
            "以下位置已被非 hub 管理的同名项占用，register 不覆盖、未写任何链接。"
            "请先移开或改名：\n  " + "\n  ".join(conflicts))
    return to_link, ensured

def commit_register_skills(to_link, w) -> None:
    for src, link in to_link:
        w.make_dir_link(src, link)

def register_skills(vault_root, dev, w) -> list[str]:      # wrapper 保留（既有测试/调用不变）
    to_link, ensured = plan_register_skills(vault_root, dev)
    commit_register_skills(to_link, w)
    return ensured

def plan_hub_memory_skill(hub_root: Path, dev: DeviceProfile) -> list[tuple[Path, Path]]:
    """随包发的 hub-memory skill 待建链接（源是 hub 包、非金库）。同名被别的占用→RegisterConflict。"""
    src = Path(hub_root) / "hub" / "skills" / "hub-memory"
    if not src.is_dir():
        raise FileNotFoundError(f"hub 包里没有 hub-memory skill: {src}")
    links: list[tuple[Path, Path]] = []
    for target_dir in skill_targets(dev):
        link = target_dir / "hub-memory"
        if os.path.lexists(link) and not resolves_to(link, src):
            raise RegisterConflict(f"{link} 已被非 hub 的同名项占用，register 不覆盖。")
        if not os.path.lexists(link):
            links.append((src, link))
    return links

def commit_hub_memory_skill(links, w) -> list[str]:
    for src, link in links:
        w.make_dir_link(src, link)
    return [str(link) for _, link in links]

def install_hub_memory_skill(hub_root, dev, w) -> list[str]:   # wrapper（既有测试用）
    return commit_hub_memory_skill(plan_hub_memory_skill(hub_root, dev), w)

def check_link_collisions(*link_lists) -> None:
    """跨来源的 link 路径唯一性预检。若金库里恰好也有一把名为 `hub-memory` 的普通 shared
    skill，`plan_register_skills` 会计划把它链进 `<tool>/skills/hub-memory`，而
    `plan_hub_memory_skill` 又计划把随包 skill 链进同一路径——两段预检都通过、提交时才撞、
    留下半套。这里在提交前把两批待建路径并起来查唯一性：同一目标被两个不同源指向→
    RegisterConflict，零写入。"""
    seen: dict[str, Path] = {}
    for links in link_lists:
        for src, link in links:
            key = os.path.join(os.path.realpath(Path(link).parent), Path(link).name)
            if key in seen and os.path.realpath(seen[key]) != os.path.realpath(src):
                raise RegisterConflict(
                    f"链接路径 {link} 被两个不同来源同时占用（{seen[key]} vs {src}），register 拒绝、零写入。")
            seen[key] = src
```

`hub/cli.py`：`_cmd_register` 改成**先全量预检、后统一提交**，并加 `refresh`：
```python
from hub.memwire import prepare_memory_views, commit_memory_views, wire_memory_views
from hub.register import (plan_register_skills, commit_register_skills,
                          plan_hub_memory_skill, commit_hub_memory_skill,
                          check_link_collisions, RegisterConflict)
from hub.hubconfig import write_config, check_config, ConfigConflict
from hub.memview import ViewScopeError, SharedMemoryError
from hub.textblock import BlockError

def _hub_root() -> Path:
    return Path(__file__).resolve().parents[1]      # 仓库根（hub/ 的上一级）

def _cmd_register(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=args.dry_run); hub_root = _hub_root()
    try:
        dev = load_device(vault_root, host)
        # ---- 预检/准备（只读；任何确定性错误在此抛、零写入）----
        to_link, ensured = plan_register_skills(vault_root, dev)
        hm_links = plan_hub_memory_skill(hub_root, dev)
        check_link_collisions(to_link, hm_links)     # 跨来源同名（如金库也有 hub-memory）→ 零写
        check_config(vault_root, host)
        writes, warnings, oc_plan = prepare_memory_views(vault_root, dev)
        # ---- 提交（预检全过之后才动笔）----
        commit_register_skills(to_link, w)
        commit_hub_memory_skill(hm_links, w)
        write_config(vault_root, host, hub_root, w)
        commit_memory_views(writes, oc_plan, w)
    except (RegisterConflict, FileNotFoundError, LinkError, SharedSkillsEscape,
            ConfigConflict, ViewScopeError, SharedMemoryError, BlockError) as e:
        print(e); return 1
    print(f"{'预计就位' if args.dry_run else '已就位'} {len(ensured)} 个 skill 链接 + hub-memory")
    for x in warnings:                               # opencode refuse 等：提示不阻断
        print("  ⚠", x)
    return 0

def _cmd_refresh(args) -> int:
    vault_root = Path(args.vault); host = args.host or current_host()
    w = Writer(dry_run=getattr(args, "dry_run", False))
    try:
        dev = load_device(vault_root, host)
        summary = wire_memory_views(vault_root, dev, w)
    except (FileNotFoundError, ViewScopeError, SharedMemoryError, BlockError) as e:
        print(e); return 1
    print(f"memory 视图已重算: {summary}")
    for x in summary.get("warnings", []):
        print("  ⚠", x)
    return 0
```
`build_parser`：
```python
    rf = sub.add_parser("refresh", parents=[common])
    rf.add_argument("--dry-run", action="store_true")
    rf.set_defaults(func=_cmd_refresh)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_memwire.py tests/hub/test_register_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/memwire.py hub/register.py hub/cli.py tests/hub/test_memwire.py tests/hub/test_register_memory.py
git commit -m "feat(hub): register/refresh wire memory views + managed blocks + opencode"
```

---

## Task 14: sync 提示/--refresh + status --check

**Files:**
- Modify: `hub/cli.py`、`hub/status_report.py`
- Test: `tests/hub/test_status_check.py`、`tests/hub/test_sync_refresh_hint.py`

**Interfaces:**
- Consumes: `hub.memwire.hub_views_home`/`_view_path`/`_codex_agents_target`、`hub.hubconfig.read_config`/`hub_config_path`、`hub.memview.load_shared_memories`/`shared_hash`、`hub.register.skill_targets`、`hub.fslink.resolves_to`、`hub.opencode_cfg.opencode_config_path`。
- Produces: `hub.status_report.view_health(vault_root, dev, hub_root) -> list[tuple[str, str]]`（**逐项真检**：config.toml 存在且一致、hub-memory 链目标正确、三份视图存在且**新鲜度**哈希匹配（否则 `stale`）、Claude 受管块、Codex **活动**受管块、opencode 条目（非严格 JSON→`degraded`）；状态 ∈ {ok, missing, conflict, stale, degraded}）；CLI：`hub status --check`（缺 device 或任一非 ok→**非零**）；`hub sync --refresh`（串联 refresh 并**传播其返回码**）；未加 `--refresh` 打印 refresh 提示。**sync 不再有 `--dry-run`**（此前是声明未实现的死旗）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_status_check.py
from pathlib import Path
from hub.model import DeviceProfile
from hub.writer import Writer
from hub.status_report import view_health
from hub.memwire import wire_memory_views

def _dev(tmp_path):
    return DeviceProfile(host="b", classes=[], projects=[], paths={
        "CLAUDE_HOME": (tmp_path / ".claude").as_posix(),
        "CODEX_HOME": (tmp_path / ".codex").as_posix()}, sources={})

def _mem(vault, name, body="body"):
    d = vault / "shared" / "memory"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        f"---\nname: {name}\ndescription: x\nmetadata:\n  type: reference\n  scope: [global]\n---\n\n{body}\n",
        encoding="utf-8")

def test_flags_missing_before_register(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _mem(tmp_path, "a")
    rows = view_health(tmp_path, _dev(tmp_path), tmp_path / "repo")
    assert any(state != "ok" for state, _ in rows)       # config/视图/链接都还没有

def test_flags_stale_after_shared_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_HOME", str(tmp_path / ".hub"))
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    _mem(tmp_path, "a", body="v1")
    wire_memory_views(tmp_path, _dev(tmp_path), Writer())   # 生成视图（嵌当时哈希）
    _mem(tmp_path, "a", body="v2 changed")                  # shared 变了但没 refresh
    rows = view_health(tmp_path, _dev(tmp_path), tmp_path / "repo")
    assert any(state == "stale" for state, _ in rows)       # 新鲜度被识破
```

```python
# tests/hub/test_sync_refresh_hint.py
# sync 不写工具地盘：--refresh 缺省时只提示。用 monkeypatch 把 GitBackend/lint 短路，
# 断言 sync 成功路径不触碰 CLAUDE.md/AGENTS.md（工具地盘）。
from pathlib import Path
import hub.cli as cli

def test_sync_does_not_write_tool_dirs(tmp_path, monkeypatch, capsys):
    # 构造最小金库；sync 只应写 MEMORY.md（金库内），不写任何 ~/.claude 之类
    (tmp_path / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (tmp_path / "shared" / "memory").mkdir(parents=True)
    class _B:
        def __init__(self, *a): pass
        def acquire(self): pass
        def publish(self, *a): pass
        def status(self): return ""
    monkeypatch.setattr(cli, "GitBackend", _B)
    rc = cli.main(["sync", "--vault", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / ".claude").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -3 -m pytest tests/hub/test_status_check.py tests/hub/test_sync_refresh_hint.py -v`
Expected: FAIL（`view_health` 不存在；`sync` 尚无 `--refresh` 参数但该用例应已能过——若报 unknown args 则说明需加参数）

- [ ] **Step 3: 写实现**

`hub/status_report.py` 追加（逐项真检，不再只查存在）：
```python
def view_health(vault_root, dev, hub_root) -> list[tuple[str, str]]:
    """memory 视图健康。只读。状态 ∈ {ok, missing, conflict, stale, degraded}。"""
    import os, json
    from pathlib import Path
    from hub.memwire import hub_views_home, _view_path, _codex_agents_target
    from hub.hubconfig import hub_config_path, read_config
    from hub.memview import load_shared_memories, shared_hash
    from hub.fslink import resolves_to
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
    # ⑥ opencode 条目（非严格 JSON→degraded）
    ocfg = opencode_config_path(dev)
    if ocfg.exists():
        try:
            data = json.loads(ocfg.read_text(encoding="utf-8"))
            instr = data.get("instructions") if isinstance(data, dict) else None
            ok = isinstance(instr, list) and _view_path("opencode").as_posix() in instr
            rows.append(("ok" if ok else "degraded", str(ocfg)))
        except ValueError:
            rows.append(("degraded", f"{ocfg}（非严格 JSON，未接线）"))
    return rows
```

`hub/cli.py`：`_cmd_status` 加 `--check`；`sync` 加 `--refresh` + 提示。
```python
def _cmd_status(args) -> int:
    vault_root = Path(args.vault)
    print(GitBackend(vault_root).status(), end="")
    check = getattr(args, "check", False)
    try:
        dev = load_device(vault_root, args.host or current_host())
    except FileNotFoundError:
        if check:
            print("status --check 停止：本机没有 device.toml"); return 1   # 缺 device → 非零
        return 0
    try:
        rows = link_status(vault_root, dev)
    except SharedSkillsEscape as e:
        print(e); return 1
    if rows:
        print("skill 链接:")
        for state, label in rows:
            print(f"  [{state}] {label}")
    if check:
        vh = view_health(vault_root, dev, _hub_root())
        print("memory 视图:")
        for state, label in vh:
            print(f"  [{state}] {label}")
        return 1 if any(x[0] != "ok" for x in (rows + vh)) else 0
    return 0
```
（`hub/status_report.py` 顶部加 `from hub.status_report import view_health` 到 cli.py 的 import；`_hub_root` 见 Task 13。）
`build_parser`：`status` 带 `--check`：
```python
    st = sub.add_parser("status", parents=[common])
    st.add_argument("--check", action="store_true", help="健康检查，不健康返回非零")
    st.set_defaults(func=_cmd_status)
```
`sync`：串联并**传播** refresh 返回码（`_cmd_sync` 末尾 `b.publish(...)` 之后）：
```python
    if getattr(args, "refresh", False):
        return _cmd_refresh(args)          # 传播 refresh 的返回码，不再吞掉失败
    print("提示：若 shared/ 有变化，运行 `hub refresh` 重算 memory 视图。")
    return 0
```
`build_parser` 里 `sync` 只加 `--refresh`（**不加 --dry-run**，那是此前声明未实现的死旗）：
```python
    sy = sub.add_parser("sync", parents=[common])
    sy.add_argument("--refresh", action="store_true", help="成功后串联 hub refresh 并传播其返回码")
    sy.set_defaults(func=_cmd_sync)
```
（把原来 `sub.add_parser("sync", ...)` 与 `sub.add_parser("status", ...)` 两行删掉，换成上面两段。cli.py 顶部 import 加 `from hub.status_report import link_status, view_health`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `py -3 -m pytest tests/hub/test_status_check.py tests/hub/test_sync_refresh_hint.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hub/cli.py hub/status_report.py tests/hub/test_status_check.py tests/hub/test_sync_refresh_hint.py
git commit -m "feat(hub): status --check health + sync stays vault-only with refresh hint"
```

---

## Task 15: 文档收尾（README + schema + spec + 同事遗留 ③④）

**Files:**
- Modify: `hub/README.md`、`docs/specs/2026-07-16-hub-c-register-design.md`
- Test: 无（纯文档；用 `py -3 -m pytest tests/hub -q` 全量回归兜底）

**Interfaces:** 无新接口。

- [ ] **Step 1: 改 README 命令表与源码地图**

`hub/README.md` §4 命令表加三行（`promote-memory` / `refresh` / `migrate-schema`），并把 `memory-read` 记进"随 hub-memory skill 用"的说明；§6 源码地图加 `memview.py` / `textblock.py` / `opencode_cfg.py` / `hubconfig.py` / `memread.py` / `memwire.py` / `vaultpaths.py` / `migrate.py` 各一行。

- [ ] **Step 2: 修同事复查遗留 ③（README 措辞）**

- 第 97 行 `**会写金库以外地方的命令…**` 段：把"会写金库以外地方的命令"改为"**会写备份区以外位置的命令**"（promote 只写金库内 `shared/`，"金库以外"不准）。
- §6 源码地图/命令表里 `status` 的归属从"A"改标"**A/C**"（status 现也报 C 的链接与视图健康）。

- [ ] **Step 3: 修同事复查遗留 ④（spec junction 状态）**

`docs/specs/2026-07-16-hub-c-register-design.md` §8 最后一条"本会话未真机验证"里，把 junction 一项更新为：**Claude/Codex junction 冒烟已通过（Task 0，用户手动）；opencode 因 `~/.config/opencode` EEXIST 非阻断跳过；临时 junction 已清**。其余未验证项（autoMemoryDirectory 读写、多机 sync）保留。

- [ ] **Step 4: 加 memory 视图使用说明到 README**

`hub/README.md` 新增一节"## 7. memory 视图（下行）"，正文写清：上行 `collect → promote-memory → shared/memory`；下行 `register`/`refresh` 生成 `~/.hub/views/<tool>/MEMORY.md` + 受管块 + opencode 条目；正文靠 `hub-memory` skill 按名读；scope v2 语法与 `project:` 是设备订阅条件；sync 不越界、refresh 显式。

- [ ] **Step 5: 全量回归**

Run: `py -3 -m pytest tests/hub -q`
Expected: PASS（全绿；记录总数，应显著多于 Plan 1 的 246）

- [ ] **Step 6: Commit**

```bash
git add hub/README.md docs/specs/2026-07-16-hub-c-register-design.md
git commit -m "docs(hub): memory-view docs + scope v2 + colleague review fixes (README/spec)"
```

---

## Self-Review 记录（第二轮，2026-07-17 同事复查七点 + 两项返修后重跑）

**同事七点闭合核对**：
1. **migrate-schema 门槛** → Task 4：`migrate_schema` 现在**只从 version 1 升**（非 1 拒绝）且**要求全部记忆 [global]**（含合法但非 global 的 `class:`/`project:` 也拒），补 `test_refuses_valid_but_nonglobal`/`test_refuses_when_not_v1`。
2. **预检零写被编排破坏** → Task 13：`wire_memory_views` 拆 `prepare_memory_views`（纯只读、渲染全部目标、ViewScopeError/BlockError 在此抛）+ `commit_memory_views`；`_cmd_register` 改「全量 plan/check → 统一 commit」（`plan_register_skills`/`plan_hub_memory_skill`/`check_config`/`prepare_memory_views` 全过才提交）。补 `test_deterministic_error_leaves_no_partial_views`。
3. **promote 链接逃逸** → Task 6：`_shared_memory_dir` 去掉 `lexists` 守卫（挡父目录逃逸）+ `_classify_memory` 加源 containment。补 `test_source_dir_link_escape_refused`/`test_shared_parent_link_escape_refused`（均断言 `w.written == []`）。
4. **假单扫** → Task 7：新增 `load_shared_memories`（只扫 shared/memory、不经 load_vault）/`validate_scopes`/`entries_for_tool`；memwire **一次扫描、内存切三份**。补 `test_scan_ignores_device_memory`。
5. **opencode 语义矛盾** → Task 10：`add_instruction` 换成 `plan_instruction`（纯只读，缺失才创建、`list[str]` 才追加、**instructions 非数组→refuse 不覆盖**、JSONC→refuse）+ `commit_instruction`；refuse 是数据、由编排降为 warning，register/refresh **不再因它返回失败**。补 `test_instructions_not_a_list_refused_not_overwritten`/`test_opencode_refuse_is_warning_not_failure`。
6. **status --check 空壳** → Task 14：`view_health(vault_root, dev, hub_root)` 逐项真检（config 一致、hub-memory 链目标、三份视图 + 新鲜度 hash、Claude 块、Codex 活动块、opencode 条目）；`status --check` 缺 device → 非零。补 `test_flags_stale_after_shared_changes`。
7. **sync --refresh 吞返回码** → Task 14：`return _cmd_refresh(args)` 传播返回码；**删掉 sync 的死 `--dry-run`**。

**两项返修**：原子写用 `tempfile.mkstemp` 唯一名（Task 5，补"失败不留临时垃圾"断言）；Task 0 fix ② **同步改 status**（`link_status` 也把链接容器标 conflict，补 `test_status_flags_linked_tool_container`）。

**spec §9 覆盖**（注：第三轮把原子写提前，故 T4=原子写、T5=migrate-schema）：9.0→T1/T2；9.1→T3/T5；9.2→T6；9.3→T7/T8；9.4→T11/T12/T13；9.5→T9/T13；9.6→T10；9.7→T4；9.8→T14；9.9→T14；9.10→T15。无遗漏。

**跨任务类型一致（返修后）**：`load_shared_memories(vault_root)`→`validate_scopes(mems)`→`entries_for_tool(mems, parsed, vault_root, dev, tool)`；`collect_view_entries(vault_root, dev, tool)`（便捷）；`render_view_file(entries, tool, shared_hash="")`；`render_codex_block(entries)`；`shared_hash(memories)`；`upsert_block(text, body)`；`plan_instruction(dev, view_path)`/`commit_instruction(plan, w, backups_dir)`；`check_config(vault_root, host)`/`write_config(vault_root, host, hub_root, w)`；`read_memory(vault_root, host, tool, name)`；`prepare_memory_views(vault_root, dev)`/`commit_memory_views(writes, plan, w)`/`wire_memory_views(vault_root, dev, w)`；`plan_register_skills(vault_root, dev)`/`commit_register_skills(to_link, w)`；`plan_hub_memory_skill(hub_root, dev)`/`commit_hub_memory_skill(links, w)`；`view_health(vault_root, dev, hub_root)`。全计划已对齐（`wire_memory_views` 与 `view_health` 的调用点均已同步去/加参数）。

**占位扫描**：无 TODO/TBD；每个代码步给了完整代码。

**已知真机待验证**（实现中确认，非计划缺口）：Codex `AGENTS.override.md` 遮蔽行为、opencode 配置真实路径/JSONC、junction 跟随、autoMemoryDirectory。

---

## Self-Review 记录（第三轮，2026-07-17 同事复查四个执行阻断点 + 两项后重跑）

**四个执行阻断点闭合**：
1. **Task 3 撞旧测试/旧契约** → Step 1 改「**整体替换** `test_scope.py`」（旧 `device:`-合法用例作废）；Step 5(schema) 扩成逐处改 §2 行内/块状示例 + §3 `device.toml` 注释（`grep device:` 核对）；Task 1/2 测试**不再重定义 `_dev`**，复用现有 `_dev`/`_shared_skill` 并对齐 `home/` 路径。
2. **统一预检的跨来源冲突洞** → Task 13 新增 `check_link_collisions(*link_lists)`，`_cmd_register` 在 commit 前调用（金库若也有名为 `hub-memory` 的 shared skill → 与随包撞同一链接路径 → RegisterConflict 零写）。补 `test_hub_memory_name_collision_zero_write`。
3. **memory 身份 + shared 边界** → Task 7 `load_shared_memories` 落三不变量：`_shared_memory_dir` 容器不逃逸、文件 stem==frontmatter `name`、`name` 不重复；新增 `SharedMemoryError` 并接进 register/refresh/memory-read 的 except。补 `test_shared_memory_container_escape_raises`/`test_stem_must_equal_name`。
4. **原子性 + status 假绿** → ①**物理交换 Task 4↔5**（原子写变 T4、先做；migrate 变 T5 并改用 `write_text_atomic`）；②`write_text_atomic` 改 `except BaseException` 清 temp，补 `test_non_oserror_also_cleans_temp`；③补 Task 13 `test_commit_partial_then_rerun_converges`（第 N 次写失败→部分完成→重跑收敛）；④`shared_hash` 纳入 `description`；⑤`view_health` 用 `textblock.has_one_valid_block` 判受管块**良构**（新增 helper + 测试），不再只 `"hub:begin" in text`。

**两项**：`config.toml` 存 `resolve()` canonical 绝对路径（`_canon`；`view_health` 比对同步 resolve），保证非仓库 cwd 启动；opencode 回滚日志用 **uuid 唯一名** + **先写配置再记日志**（配置失败则不留假记录）。

**类型一致（第三轮增量）**：`check_link_collisions(*link_lists)`；`load_shared_memories` 抛 `SharedMemoryError`；`has_one_valid_block(text)`；`shared_hash` 现含 description；`write_text_atomic` 任意异常清 temp；Task 编号 4/5 已互换（`task-brief` 按编号抽取，执行顺序 = 数字序，原子写先于 migrate）。

**占位/一致性复扫**：无 TODO/TBD；Task 4/5 互换后文内引用（§9 映射、依赖注记）已同步；`ViewScopeError`/`SharedMemoryError`/`BlockError`/`RegisterConflict`/`ConfigConflict`/`SharedSkillsEscape` 在 cli 各 except 元组齐备。
