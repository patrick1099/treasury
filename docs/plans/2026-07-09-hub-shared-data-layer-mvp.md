# hub 共享数据层 MVP 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `ai-cli-migrate` 新增 `hub/` 包，实现跨工具/设备共享「规则 + 记忆」的耐久层：金库（git 版本化目录树）经 scope 过滤 + 符号根解析后，materialize 到 Claude Code / Codex 的本地位置；反向 collect 本机记忆入金库。

**Architecture:** 三层解耦——Backend（git，3 动词 acquire/publish/status）/ Vault logic（scope、links、derive）/ Materializer（写工具目录）。金库=固定 schema 的目录树。离线优先：collect/process 全本地，只有 sync 需网络。hub 吸收 migrate 内脏为库。

**Tech Stack:** Python ≥3.11（`tomllib`）、纯标准库（无第三方）、pytest、git CLI。Windows 主场，`py -3`。

## Global Constraints

- **纯标准库，无第三方依赖**。TOML 用 `tomllib`（只读）。YAML frontmatter 用自写的**极小子集**解析器，不引 PyYAML。
- **Python ≥ 3.11**（`tomllib` 内置门槛）。Task 1 先验证。
- **scope 语义**：维度间 AND、同维度多值 OR、缺省维度不限、`global` 必须独占（混用报错）。
- **managed block** `<!-- hub:begin -->…<!-- hub:end -->` 仅用于**聚合/派生文件**（AGENTS.md、CLAUDE.md）；单条 `memory/*.md` 与 `MEMORY.md`、`memory-index.md` 是**整文件 hub 拥有/派生**，不需 block。
- **回环防护**：collect 只收记忆，绝不收规则；AGENTS.md/CLAUDE.md/memory-index 是派生物，永不 collect。
- **敏感/可移植两轴**：`sensitive:true` 绝不 collect/入金库；`portable:false` 可入金库、仅在能解析路径的设备落地。
- **Windows 写文件用 UTF-8 无 BOM、LF 结尾**。
- 提交身份=个人 `patrick1099 <hsheng416@gmail.com>`（仓库默认已是）。

**规范参考：** 设计 spec `docs/specs/2026-07-09-shared-data-layer-mvp-design.md`（读它理解每个机制的“为什么”）。

## File Structure

```
ai-cli-migrate/
  hub/
    __init__.py          # 版本、包导出
    model.py             # dataclass: Memory / Target / DeviceProfile / ProjectTarget / VaultConfig
    frontmatter.py       # YAML 极小子集 parse/dump + load_memory/dump_memory
    scope.py             # parse_scope / scope_matches / lint_scope
    managed_block.py     # replace_block / extract_block
    links.py             # lint_raw_paths / resolve_symbols
    vault.py             # load_vault / load_device / current_host
    derive.py            # render_memory_index
    materialize.py       # render_agents_md / render_claude_md / materialize_memory
    collect.py           # collect_memories
    backend.py           # Backend(ABC) / GitBackend
    cli.py               # argparse: status/collect/process/pull/sync/bootstrap
  tests/hub/
    test_frontmatter.py  test_scope.py  test_managed_block.py  test_links.py
    test_vault.py  test_derive.py  test_materialize.py  test_collect.py
    test_backend_git.py  test_cli.py
```

每个文件单一职责；`materialize.py` 最重，Task 8/9 分两刀（规则 / 记忆），reviewer 可独立取舍。

---

### Task 1: 包骨架 + Python 版本门槛 + 数据模型

**Files:**
- Create: `hub/__init__.py`, `hub/model.py`, `tests/hub/test_model.py`, `pytest.ini`
- 注意：**不要**建 `tests/hub/__init__.py`——它会让 pytest 把 `tests/hub` 当顶层包 `hub` 导入、遮蔽真实 `hub/`。改为提交 `pytest.ini`（`pythonpath = .`、`testpaths = tests`）解决导入。

**Interfaces:**
- Produces: dataclasses `Memory(name:str, description:str, type:str, scope:list[str], portable:bool, sensitive:bool, body:str, path:Path|None=None)`；`Target(device_classes:frozenset[str], project:str|None, tool:str)`；`ProjectTarget(project:str, root:str)`；`DeviceProfile(host:str, classes:list[str], projects:list[str], paths:dict[str,str], targets:list[ProjectTarget], collect_sources:list[str])`；`VaultConfig(version:int)`。

- [ ] **Step 1: 确认 Python ≥ 3.11**

Run: `py -3 -c "import sys, tomllib; print(sys.version_info[:2])"`
Expected: 打印 `(3, 11)` 或更高，且不报 `ModuleNotFoundError: tomllib`。若低于 3.11，停下并在计划开一个前置任务（内置极小 TOML 读取器）——本 MVP 假设满足。

- [ ] **Step 2: 写失败测试**

```python
# tests/hub/test_model.py
from pathlib import Path
from hub.model import Memory, Target, DeviceProfile, ProjectTarget, VaultConfig

def test_memory_defaults():
    m = Memory(name="x", description="d", type="project",
               scope=["global"], portable=True, sensitive=False, body="hi")
    assert m.path is None
    assert m.scope == ["global"]

def test_device_profile_holds_targets():
    dp = DeviceProfile(host="huawei", classes=["work"], projects=["xinao"],
                       paths={"VAULT": "Z:/vault"},
                       targets=[ProjectTarget(project="xinao", root="C:/x")])
    assert dp.targets[0].project == "xinao"
    assert VaultConfig(version=1).version == 1
    assert Target(frozenset({"work"}), "xinao", "claude").tool == "claude"
```

- [ ] **Step 3: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_model.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub'`。

- [ ] **Step 4: 写实现**

```python
# hub/__init__.py
__version__ = "0.1.0"
```
```python
# hub/model.py
from dataclasses import dataclass, field
from pathlib import Path

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

@dataclass
class ProjectTarget:
    project: str
    root: str

@dataclass
class DeviceProfile:
    host: str
    classes: list[str]
    projects: list[str]
    paths: dict[str, str]
    targets: list[ProjectTarget] = field(default_factory=list)
    collect_sources: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class Target:
    device_classes: frozenset[str]
    project: str | None
    tool: str

@dataclass
class VaultConfig:
    version: int
```
```ini
# pytest.ini  (提交此文件；不建 tests/hub/__init__.py)
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 5: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_model.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 6: 提交**

```bash
git add hub/__init__.py hub/model.py pytest.ini tests/hub/test_model.py
git commit -m "feat(hub): 包骨架 + 数据模型 dataclasses"
```

---

### Task 2: frontmatter —— YAML 极小子集解析 + Memory 读写

**Files:**
- Create: `hub/frontmatter.py`, `tests/hub/test_frontmatter.py`

**Interfaces:**
- Consumes: `hub.model.Memory`。
- Produces: `class FrontmatterError(ValueError)`；`parse_frontmatter(text:str) -> tuple[dict, str]`（meta 支持一层嵌套、`key: value`、内联列表 `[a, b]`；越界抛错）；`load_memory(path:Path) -> Memory`；`dump_memory(m:Memory) -> str`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_frontmatter.py
import pytest
from pathlib import Path
from hub.frontmatter import parse_frontmatter, load_memory, dump_memory, FrontmatterError
from hub.model import Memory

SAMPLE = """---
name: project_encoding_workflow
description: CP936 源文件处理
metadata:
  type: project
  scope: [global, tool:claude]
  portable: false
  sensitive: false
---
正文第一行
第二行
"""

def test_parse_nested_and_inline_list():
    meta, body = parse_frontmatter(SAMPLE)
    assert meta["name"] == "project_encoding_workflow"
    assert meta["metadata"]["scope"] == ["global", "tool:claude"]
    assert meta["metadata"]["portable"] is False
    assert body.startswith("正文第一行")

def test_load_memory_roundtrip(tmp_path):
    p = tmp_path / "m.md"
    p.write_text(SAMPLE, encoding="utf-8")
    m = load_memory(p)
    assert isinstance(m, Memory)
    assert m.scope == ["global", "tool:claude"]
    assert m.sensitive is False
    assert m.path == p
    # dump 后再 parse 应稳定
    meta2, _ = parse_frontmatter(dump_memory(m))
    assert meta2["metadata"]["scope"] == ["global", "tool:claude"]

def test_reject_out_of_subset():
    bad = "---\nname: x\ntags:\n  - a:\n      b: 1\n---\nbody\n"  # 二层嵌套列表，越界
    with pytest.raises(FrontmatterError):
        parse_frontmatter(bad)
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_frontmatter.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.frontmatter'`。

- [ ] **Step 3: 写实现**

```python
# hub/frontmatter.py
from pathlib import Path
from hub.model import Memory

class FrontmatterError(ValueError):
    pass

def _coerce(v: str):
    s = v.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [x.strip() for x in inner.split(",")]
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    return s

def parse_frontmatter(text: str) -> tuple[dict, str]:
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
    cur: dict = meta
    cur_key = None
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if ":" not in ln:
            raise FrontmatterError(f"无法解析行(子集外): {ln!r}")
        key, _, val = ln.strip().partition(":")
        key = key.strip()
        if indent == 0:
            if val.strip() == "":
                meta[key] = {}
                cur = meta[key]
                cur_key = key
            else:
                meta[key] = _coerce(val)
                cur = meta
        elif indent >= 2 and cur is not meta:
            # 一层嵌套；值不得再是空(=二层嵌套)
            if val.strip() == "":
                raise FrontmatterError(f"超出一层嵌套子集: {ln!r}")
            cur[key] = _coerce(val)
        else:
            raise FrontmatterError(f"缩进/结构越界: {ln!r}")
    body = "\n".join(lines[end + 1:])
    if body and not body.endswith("\n"):
        body += "\n"
    return meta, body

def load_memory(path: Path) -> Memory:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    md = meta.get("metadata", {})
    return Memory(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        type=md.get("type", "reference"),
        scope=md.get("scope", ["global"]),
        portable=bool(md.get("portable", True)),
        sensitive=bool(md.get("sensitive", False)),
        body=body,
        path=path,
    )

def _fmt_list(xs: list[str]) -> str:
    return "[" + ", ".join(xs) + "]"

def dump_memory(m: Memory) -> str:
    lines = [
        "---",
        f"name: {m.name}",
        f"description: {m.description}",
        "metadata:",
        f"  type: {m.type}",
        f"  scope: {_fmt_list(m.scope)}",
        f"  portable: {str(m.portable).lower()}",
        f"  sensitive: {str(m.sensitive).lower()}",
        "---",
    ]
    body = m.body if m.body.endswith("\n") else m.body + "\n"
    return "\n".join(lines) + "\n" + body
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_frontmatter.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/frontmatter.py tests/hub/test_frontmatter.py
git commit -m "feat(hub): frontmatter 极小 YAML 子集解析 + Memory 读写"
```

---

### Task 3: scope —— 谓词语义（AND/OR/global 独占）

**Files:**
- Create: `hub/scope.py`, `tests/hub/test_scope.py`

**Interfaces:**
- Consumes: `hub.model.Target`。
- Produces: `class ScopeError(ValueError)`；`parse_scope(scope:list[str]) -> dict[str,set[str]]`（返回维度→取值集；`global` → `{}`；`global` 与任何维度混用抛 `ScopeError`）；`scope_matches(scope:list[str], target:Target) -> bool`；`lint_scope(scope:list[str]) -> list[str]`（返回错误串列表，空=合法）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_scope.py
import pytest
from hub.scope import parse_scope, scope_matches, lint_scope, ScopeError
from hub.model import Target

def T(classes=(), project=None, tool="claude"):
    return Target(frozenset(classes), project, tool)

def test_global_matches_everything():
    assert scope_matches(["global"], T(tool="codex")) is True

def test_same_dim_is_or():
    assert parse_scope(["device:work", "device:home"]) == {"device": {"work", "home"}}
    assert scope_matches(["device:work", "device:home"], T(classes=["home"])) is True
    assert scope_matches(["device:work", "device:home"], T(classes=["lab"])) is False

def test_cross_dim_is_and():
    s = ["project:xinao", "tool:claude"]
    assert scope_matches(s, T(project="xinao", tool="claude")) is True
    assert scope_matches(s, T(project="xinao", tool="codex")) is False  # Claude 专属不漏给 Codex

def test_absent_dim_unrestricted():
    assert scope_matches(["tool:claude"], T(project="anything", tool="claude")) is True

def test_global_must_be_alone():
    with pytest.raises(ScopeError):
        parse_scope(["global", "tool:claude"])
    assert lint_scope(["global", "tool:claude"]) != []
    assert lint_scope(["project:xinao", "tool:claude"]) == []

def test_unknown_dimension_rejected():
    assert lint_scope(["weird:x"]) != []
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_scope.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.scope'`。

- [ ] **Step 3: 写实现**

```python
# hub/scope.py
from hub.model import Target

class ScopeError(ValueError):
    pass

_DIMS = {"device", "project", "tool"}

def parse_scope(scope: list[str]) -> dict[str, set[str]]:
    has_global = "global" in scope
    dims: dict[str, set[str]] = {}
    for token in scope:
        if token == "global":
            continue
        dim, sep, val = token.partition(":")
        if not sep or dim not in _DIMS or not val:
            raise ScopeError(f"非法 scope 谓词: {token!r}")
        dims.setdefault(dim, set()).add(val)
    if has_global and dims:
        raise ScopeError("global 必须单独出现，不可与维度谓词混用")
    return dims

def scope_matches(scope: list[str], target: Target) -> bool:
    dims = parse_scope(scope)
    if "device" in dims and target.device_classes.isdisjoint(dims["device"]):
        return False
    if "project" in dims and (target.project is None or target.project not in dims["project"]):
        return False
    if "tool" in dims and target.tool not in dims["tool"]:
        return False
    return True

def lint_scope(scope: list[str]) -> list[str]:
    try:
        parse_scope(scope)
        return []
    except ScopeError as e:
        return [str(e)]
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_scope.py -v`
Expected: PASS（6 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/scope.py tests/hub/test_scope.py
git commit -m "feat(hub): scope 谓词语义(维度间AND/同维OR/global独占)"
```

---

### Task 4: managed_block —— 派生文件的 hub 托管块

**Files:**
- Create: `hub/managed_block.py`, `tests/hub/test_managed_block.py`

**Interfaces:**
- Produces: `BEGIN="<!-- hub:begin -->"`、`END="<!-- hub:end -->"`；`replace_block(text:str, new_inner:str) -> str`（无块则追加到末尾；有块则替换块内；块外内容原样保留）；`extract_block(text:str) -> str|None`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_managed_block.py
from hub.managed_block import replace_block, extract_block, BEGIN, END

def test_append_when_absent():
    out = replace_block("用户手写内容\n", "生成A")
    assert "用户手写内容" in out
    assert BEGIN in out and END in out
    assert extract_block(out) == "生成A"

def test_replace_is_idempotent_and_preserves_outside():
    once = replace_block("头部\n", "V1")
    twice = replace_block(once, "V2")
    assert "头部" in twice
    assert extract_block(twice) == "V2"
    assert twice.count(BEGIN) == 1 and twice.count(END) == 1

def test_extract_none_when_no_block():
    assert extract_block("纯手写\n") is None
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_managed_block.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

```python
# hub/managed_block.py
BEGIN = "<!-- hub:begin -->"
END = "<!-- hub:end -->"

def extract_block(text: str) -> str | None:
    i = text.find(BEGIN)
    j = text.find(END)
    if i == -1 or j == -1 or j < i:
        return None
    inner = text[i + len(BEGIN):j]
    return inner.strip("\n")

def replace_block(text: str, new_inner: str) -> str:
    block = f"{BEGIN}\n{new_inner}\n{END}"
    i = text.find(BEGIN)
    j = text.find(END)
    if i != -1 and j != -1 and j >= i:
        return text[:i] + block + text[j + len(END):]
    prefix = text if text.endswith("\n") or text == "" else text + "\n"
    if prefix and not prefix.endswith("\n\n") and prefix != "":
        prefix = prefix + "\n"
    return prefix + block + "\n"
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_managed_block.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/managed_block.py tests/hub/test_managed_block.py
git commit -m "feat(hub): managed block 读写(追加/替换/保留块外)"
```

---

### Task 5: links —— 裸绝对路径 linter + 符号根解析

**Files:**
- Create: `hub/links.py`, `tests/hub/test_links.py`

**Interfaces:**
- Produces: `lint_raw_paths(body:str) -> list[str]`（返回命中的裸绝对路径片段）；`resolve_symbols(body:str, paths:dict[str,str]) -> tuple[str, list[str]]`（把 `$ROOT/...` 展开为 `paths["ROOT"]/...`；返回解析后文本与**未定义**的根名列表）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_links.py
from hub.links import lint_raw_paths, resolve_symbols

def test_lint_flags_windows_and_posix_abspath():
    assert lint_raw_paths("见 C:\\Users\\huawei\\x.md 里") != []
    assert lint_raw_paths("见 /home/u/x.md") != []
    assert lint_raw_paths("见 $VAULT/x.md 和 [[slug]]") == []

def test_resolve_symbols_expands_defined_roots():
    out, missing = resolve_symbols("看 $SECRETS/INDEX.md", {"SECRETS": "C:/s"})
    assert out == "看 C:/s/INDEX.md"
    assert missing == []

def test_resolve_reports_missing_roots():
    out, missing = resolve_symbols("看 $VAULT/a 与 $NOPE/b", {"VAULT": "Z:/v"})
    assert "Z:/v/a" in out
    assert missing == ["NOPE"]
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_links.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

```python
# hub/links.py
import re

# 盘符绝对路径 C:\ 或 C:/ ；UNC \\host\ ；POSIX 绝对 /a/b（排除行内 http:// 之类由前置空白/行首约束）
_ABS = re.compile(r"(?<![\w$])(?:[A-Za-z]:[\\/]|\\\\[^\s]|/[A-Za-z0-9_.]+/)[^\s)>\]]*")
_SYM = re.compile(r"\$([A-Z][A-Z0-9_]*)(/[^\s)>\]]*)?")

def lint_raw_paths(body: str) -> list[str]:
    hits = []
    for m in _ABS.finditer(body):
        frag = m.group(0)
        if frag.startswith("$"):
            continue
        hits.append(frag)
    return hits

def resolve_symbols(body: str, paths: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    def sub(m: re.Match) -> str:
        root = m.group(1)
        rest = m.group(2) or ""
        if root not in paths:
            if root not in missing:
                missing.append(root)
            return m.group(0)
        base = paths[root].rstrip("/")
        return base + rest
    out = _SYM.sub(sub, body)
    return out, missing
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_links.py -v`
Expected: PASS（3 passed）。若 POSIX 正则误伤，微调 `_ABS` 后重跑，直至 3 passed。

- [ ] **Step 5: 提交**

```bash
git add hub/links.py tests/hub/test_links.py
git commit -m "feat(hub): 裸绝对路径 linter + 符号根解析"
```

---

### Task 6: vault —— 加载金库树与设备档案

**Files:**
- Create: `hub/vault.py`, `tests/hub/test_vault.py`

**Interfaces:**
- Consumes: `load_memory`（Task 2）、model（Task 1）。
- Produces: `@dataclass Vault(root:Path, config:VaultConfig, memories:list[Memory], rules:list[tuple[str,str]])`（rules 按文件名排序的 `(name, content)`）；`load_vault(root:Path) -> Vault`；`load_device(root:Path, host:str) -> DeviceProfile`（读 `devices/<host>.toml`，`tomllib`）；`current_host() -> str`（`socket.gethostname()` 小写）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_vault.py
from pathlib import Path
from hub.vault import load_vault, load_device
from hub.model import Vault, DeviceProfile  # Vault 从 model 或 vault 导出——见实现

def _mk_vault(root: Path):
    (root / "rules").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "devices").mkdir()
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "rules" / "b.md").write_text("规则B\n", encoding="utf-8")
    (root / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / "memory" / "m1.md").write_text(
        "---\nname: m1\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    (root / "devices" / "huawei.toml").write_text(
        'class = ["work"]\nprojects = ["xinao"]\n\n'
        '[paths]\nVAULT = "Z:/vault"\n\n'
        '[[targets]]\nproject = "xinao"\nroot = "C:/x"\n',
        encoding="utf-8")

def test_load_vault(tmp_path):
    _mk_vault(tmp_path)
    v = load_vault(tmp_path)
    assert v.config.version == 1
    assert [name for name, _ in v.rules] == ["a", "b"]  # 排序
    assert len(v.memories) == 1 and v.memories[0].name == "m1"

def test_load_device(tmp_path):
    _mk_vault(tmp_path)
    dp = load_device(tmp_path, "huawei")
    assert dp.classes == ["work"]
    assert dp.paths["VAULT"] == "Z:/vault"
    assert dp.targets[0].project == "xinao" and dp.targets[0].root == "C:/x"
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_vault.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.vault'`。

- [ ] **Step 3: 写实现**（`Vault` 定义放 `hub/model.py`，并在 model 顶部补 import）

在 `hub/model.py` 末尾追加：
```python
@dataclass
class Vault:
    root: "Path"
    config: VaultConfig
    memories: list[Memory]
    rules: list[tuple[str, str]]
```
新建 `hub/vault.py`：
```python
import socket
import tomllib
from pathlib import Path
from hub.model import Vault, VaultConfig, DeviceProfile, ProjectTarget
from hub.frontmatter import load_memory

def current_host() -> str:
    return socket.gethostname().lower()

def load_vault(root: Path) -> Vault:
    cfg_raw = tomllib.loads((root / "vault.toml").read_text(encoding="utf-8"))
    config = VaultConfig(version=int(cfg_raw.get("version", 1)))
    rules = []
    rules_dir = root / "rules"
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*.md")):
            rules.append((p.stem, p.read_text(encoding="utf-8")))
    memories = []
    mem_dir = root / "memory"
    if mem_dir.is_dir():
        for p in sorted(mem_dir.glob("*.md")):
            memories.append(load_memory(p))
    return Vault(root=root, config=config, memories=memories, rules=rules)

def load_device(root: Path, host: str) -> DeviceProfile:
    raw = tomllib.loads((root / "devices" / f"{host}.toml").read_text(encoding="utf-8"))
    targets = [ProjectTarget(project=t["project"], root=t["root"])
               for t in raw.get("targets", [])]
    return DeviceProfile(
        host=host,
        classes=list(raw.get("class", [])),
        projects=list(raw.get("projects", [])),
        paths=dict(raw.get("paths", {})),
        targets=targets,
        collect_sources=list(raw.get("collect_sources", [])),
    )
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_vault.py -v`
Expected: PASS（2 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/model.py hub/vault.py tests/hub/test_vault.py
git commit -m "feat(hub): 加载金库树(规则/记忆/config)与设备档案(tomllib)"
```

---

### Task 7: derive —— 从 frontmatter 重生成 MEMORY.md 索引

**Files:**
- Create: `hub/derive.py`, `tests/hub/test_derive.py`

**Interfaces:**
- Consumes: `list[Memory]`。
- Produces: `render_memory_index(memories:list[Memory]) -> str`（整文件派生物：每条一行 `- [<name>](<name>.md) — <description>`，按 name 排序；文件以说明注释开头声明“自动生成，勿手改”）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_derive.py
from hub.derive import render_memory_index
from hub.model import Memory

def _m(name, desc):
    return Memory(name=name, description=desc, type="project",
                  scope=["global"], portable=True, sensitive=False, body="b")

def test_index_sorted_and_formatted():
    out = render_memory_index([_m("zeta", "最后"), _m("alpha", "最先")])
    lines = [l for l in out.splitlines() if l.startswith("- [")]
    assert lines[0] == "- [alpha](alpha.md) — 最先"
    assert lines[1] == "- [zeta](zeta.md) — 最后"
    assert "自动生成" in out  # 派生物声明
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_derive.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

```python
# hub/derive.py
from hub.model import Memory

def render_memory_index(memories: list[Memory]) -> str:
    header = "<!-- 自动生成，勿手改：由 hub 从各 memory/*.md frontmatter 派生 -->\n"
    rows = [f"- [{m.name}]({m.name}.md) — {m.description}"
            for m in sorted(memories, key=lambda x: x.name)]
    return header + "\n".join(rows) + "\n"
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_derive.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/derive.py tests/hub/test_derive.py
git commit -m "feat(hub): MEMORY.md 索引派生(排序/自动生成声明)"
```

---

### Task 8: materialize（规则）—— AGENTS.md / CLAUDE.md

**Files:**
- Create: `hub/materialize.py`, `tests/hub/test_materialize.py`

**Interfaces:**
- Consumes: `replace_block`（Task 4）。
- Produces: `render_agents_md(existing:str, rules:list[tuple[str,str]], project_memory_inner:str="") -> str`（把规则拼接 + 可选项目记忆块，写入 managed block；块外保留）；`render_claude_md(existing:str, memory_index_import:str) -> str`（managed block 内含 `@AGENTS.md` 与 `@<memory_index_import>` 两行）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_materialize.py
from hub.materialize import render_agents_md, render_claude_md
from hub.managed_block import extract_block

def test_agents_md_embeds_rules_and_preserves_outside():
    out = render_agents_md("# 我的手写抬头\n", [("a", "规则A\n"), ("b", "规则B\n")])
    assert "# 我的手写抬头" in out
    inner = extract_block(out)
    assert "规则A" in inner and "规则B" in inner

def test_agents_md_appends_project_memory_block():
    out = render_agents_md("", [("a", "规则A\n")], project_memory_inner="## 项目记忆\n- 坑X\n")
    inner = extract_block(out)
    assert "规则A" in inner and "项目记忆" in inner and "坑X" in inner

def test_agents_md_idempotent():
    once = render_agents_md("抬头\n", [("a", "规则A\n")])
    twice = render_agents_md(once, [("a", "规则A改\n")])
    assert twice.count("hub:begin") == 1
    assert "规则A改" in extract_block(twice)
    assert "抬头" in twice

def test_claude_md_imports():
    out = render_claude_md("手写\n", "hub/memory-index.md")
    inner = extract_block(out)
    assert "@AGENTS.md" in inner
    assert "@hub/memory-index.md" in inner
    assert "手写" in out
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_materialize.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.materialize'`。

- [ ] **Step 3: 写实现**

```python
# hub/materialize.py
from hub.managed_block import replace_block

def render_agents_md(existing: str, rules: list[tuple[str, str]],
                     project_memory_inner: str = "") -> str:
    parts = []
    for _name, content in rules:
        parts.append(content.rstrip("\n"))
    if project_memory_inner.strip():
        parts.append(project_memory_inner.rstrip("\n"))
    inner = "\n\n".join(parts)
    return replace_block(existing, inner)

def render_claude_md(existing: str, memory_index_import: str) -> str:
    inner = f"@AGENTS.md\n@{memory_index_import}"
    return replace_block(existing, inner)
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_materialize.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/materialize.py tests/hub/test_materialize.py
git commit -m "feat(hub): 规则落地 AGENTS.md/CLAUDE.md(managed block+@import)"
```

---

### Task 9: materialize（记忆）—— Codex/Claude 分流落地

**Files:**
- Modify: `hub/materialize.py`
- Modify: `tests/hub/test_materialize.py`

**Interfaces:**
- Consumes: `scope_matches`（Task 3）、`resolve_symbols`（Task 5）、`Target`（Task 1）、`render_agents_md`（Task 8）。
- Produces:
  - `select_for_target(memories:list[Memory], target:Target) -> list[Memory]`（scope 过滤，排除 `sensitive`）；
  - `render_memory_bundle(memories:list[Memory], paths:dict[str,str]) -> str`（把多条记忆拼成一个 md 文本，逐条 `resolve_symbols`；跳过有未定义根的条目并在文本内标注 `<!-- skipped ... -->`）；
  - `codex_project_inner(memories:list[Memory], paths:dict[str,str]) -> str`（供 AGENTS.md 的项目记忆块）。

- [ ] **Step 1: 写失败测试（追加）**

```python
# 追加到 tests/hub/test_materialize.py
from hub.materialize import select_for_target, render_memory_bundle, codex_project_inner
from hub.model import Memory, Target

def _mem(name, scope, body="正文", sensitive=False):
    return Memory(name=name, description=name, type="project",
                  scope=scope, portable=True, sensitive=sensitive, body=body)

def test_select_filters_scope_and_sensitive():
    mems = [_mem("g", ["global"]),
            _mem("claude_only", ["tool:claude"]),
            _mem("secret", ["global"], sensitive=True)]
    for_codex = select_for_target(mems, Target(frozenset(), None, "codex"))
    names = {m.name for m in for_codex}
    assert names == {"g"}  # claude_only 被 AND 排除；secret 被敏感排除

def test_bundle_resolves_symbols_and_marks_missing():
    mems = [_mem("ok", ["global"], body="看 $VAULT/a\n"),
            _mem("bad", ["global"], body="看 $NOPE/b\n")]
    out = render_memory_bundle(mems, {"VAULT": "Z:/v"})
    assert "Z:/v/a" in out
    assert "skipped" in out and "bad" in out  # 未定义根 -> 跳过并标注

def test_codex_project_inner_wraps():
    inner = codex_project_inner([_mem("p", ["project:xinao"], body="坑\n")], {})
    assert "坑" in inner
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_materialize.py -v`
Expected: FAIL，`ImportError: cannot import name 'select_for_target'`。

- [ ] **Step 3: 写实现（追加到 `hub/materialize.py`）**

```python
from hub.model import Memory, Target
from hub.scope import scope_matches
from hub.links import resolve_symbols

def select_for_target(memories: list[Memory], target: Target) -> list[Memory]:
    out = []
    for m in memories:
        if m.sensitive:
            continue
        if scope_matches(m.scope, target):
            out.append(m)
    return out

def render_memory_bundle(memories: list[Memory], paths: dict[str, str]) -> str:
    chunks = []
    for m in memories:
        resolved, missing = resolve_symbols(m.body, paths)
        if missing:
            chunks.append(f"<!-- skipped {m.name}: 未定义符号根 {missing} -->")
            continue
        chunks.append(f"### {m.name}\n{resolved.rstrip(chr(10))}")
    return "\n\n".join(chunks) + ("\n" if chunks else "")

def codex_project_inner(memories: list[Memory], paths: dict[str, str]) -> str:
    body = render_memory_bundle(memories, paths)
    return "## 项目记忆(hub)\n" + body
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_materialize.py -v`
Expected: PASS（7 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/materialize.py tests/hub/test_materialize.py
git commit -m "feat(hub): 记忆落地分流(scope过滤/敏感排除/符号根解析/项目块)"
```

---

### Task 10: collect —— 扫工具目录入金库（原子文件、跳过敏感/派生）

**Files:**
- Create: `hub/collect.py`, `tests/hub/test_collect.py`

**Interfaces:**
- Consumes: `load_memory`（Task 2）、`dump_memory`（Task 2）。
- Produces: `collect_memories(source_dirs:list[Path], vault_memory_dir:Path) -> list[str]`（把源目录里的 `*.md` 记忆按**整文件**写入金库 `memory/`；跳过 `sensitive:true`；跳过名为 `memory-index.md`/`MEMORY.md` 的派生物；返回收入的 name 列表）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_collect.py
from pathlib import Path
from hub.collect import collect_memories

def _write(p: Path, name, sensitive=False):
    p.write_text(
        f"---\nname: {name}\ndescription: d\nmetadata:\n  type: project\n"
        f"  scope: [global]\n  portable: true\n  sensitive: {str(sensitive).lower()}\n---\n正文\n",
        encoding="utf-8")

def test_collect_skips_sensitive_and_derived(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    vault_mem = tmp_path / "vault" / "memory"; vault_mem.mkdir(parents=True)
    _write(src / "keep.md", "keep")
    _write(src / "secret.md", "secret", sensitive=True)
    (src / "MEMORY.md").write_text("- 派生物\n", encoding="utf-8")
    (src / "memory-index.md").write_text("派生\n", encoding="utf-8")
    collected = collect_memories([src], vault_mem)
    assert collected == ["keep"]
    assert (vault_mem / "keep.md").exists()
    assert not (vault_mem / "secret.md").exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_collect.py -v`
Expected: FAIL，`ModuleNotFoundError`。

- [ ] **Step 3: 写实现**

```python
# hub/collect.py
from pathlib import Path
from hub.frontmatter import load_memory, dump_memory, FrontmatterError

_DERIVED = {"MEMORY.md", "memory-index.md"}

def collect_memories(source_dirs: list[Path], vault_memory_dir: Path) -> list[str]:
    vault_memory_dir.mkdir(parents=True, exist_ok=True)
    collected: list[str] = []
    for d in source_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.name in _DERIVED:
                continue
            try:
                m = load_memory(p)
            except FrontmatterError:
                continue
            if m.sensitive:
                continue
            (vault_memory_dir / f"{m.name}.md").write_text(
                dump_memory(m), encoding="utf-8")
            collected.append(m.name)
    return collected
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_collect.py -v`
Expected: PASS（1 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/collect.py tests/hub/test_collect.py
git commit -m "feat(hub): collect 扫工具目录入金库(原子文件/跳过敏感与派生)"
```

---

### Task 11: backend —— Backend 抽象 + GitBackend

**Files:**
- Create: `hub/backend.py`, `tests/hub/test_backend_git.py`

**Interfaces:**
- Produces: `class ConflictError(RuntimeError)`；`class Backend(ABC)` 三方法 `acquire()`/`publish(message:str)`/`status() -> str`；`class GitBackend(Backend)`（`__init__(self, repo:Path)`；`acquire`=**普通 merge**（`git pull --no-rebase --no-edit`），非冲突的分叉（如两台设备各加不同文件）**自动合并**、只有**真实冲突**才抛 `ConflictError`；`publish`=`add -A` + `commit` +（若有 remote）`push`；`status`=`git status --porcelain`）。

> **为什么不是 `--ff-only`**：对等离线模型下，设备 A、B 各自新增不同 `memory/*.md` 是**正常且应自动 merge** 的场景。`--ff-only` 会把它判成失败。只有当两台改了**同一文件同一处**（理论上仅 `rules/*` 可能）才是真冲突。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_backend_git.py
import subprocess
from pathlib import Path
import pytest
from hub.backend import GitBackend, ConflictError

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)

def _init_repo(path: Path):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A"); _git(path, "commit", "-qm", "seed")

def test_status_and_publish(tmp_path):
    repo = tmp_path / "clone"; _init_repo(repo)
    b = GitBackend(repo)
    (repo / "new.md").write_text("hi\n", encoding="utf-8")
    assert b.status().strip() != ""       # 有未提交改动
    b.publish("add new")
    assert b.status().strip() == ""       # 提交后干净

def test_acquire_conflict_raises(tmp_path):
    # 远端与本地在同一文件分叉 -> 非 ff -> ConflictError
    remote = tmp_path / "remote"; _init_repo(remote)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    # 远端前进一步
    (remote / "seed.txt").write_text("remote\n", encoding="utf-8")
    _git(remote, "commit", "-qam", "remote change")
    # 本地也改同文件并提交 -> 分叉
    (clone / "seed.txt").write_text("local\n", encoding="utf-8")
    _git(clone, "commit", "-qam", "local change")
    with pytest.raises(ConflictError):
        GitBackend(clone).acquire()

def test_acquire_merges_nonconflicting_changes(tmp_path):
    # 对等场景：远端与本地各自新增【不同文件】-> 应自动 merge，不抛
    remote = tmp_path / "remote"; _init_repo(remote)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True,
                   capture_output=True, text=True)
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "t")
    (remote / "a.md").write_text("A\n", encoding="utf-8")
    _git(remote, "add", "-A"); _git(remote, "commit", "-qm", "remote a")
    (clone / "b.md").write_text("B\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-qm", "local b")
    GitBackend(clone).acquire()             # 不应抛
    assert (clone / "a.md").exists() and (clone / "b.md").exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_backend_git.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.backend'`。

- [ ] **Step 3: 写实现**

```python
# hub/backend.py
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

class ConflictError(RuntimeError):
    pass

class Backend(ABC):
    @abstractmethod
    def acquire(self) -> None: ...
    @abstractmethod
    def publish(self, message: str) -> None: ...
    @abstractmethod
    def status(self) -> str: ...

class GitBackend(Backend):
    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.repo, check=check,
                              capture_output=True, text=True)

    def _has_remote(self) -> bool:
        return self._run("remote", check=False).stdout.strip() != ""

    def _conflicted_files(self) -> list[str]:
        out = self._run("diff", "--name-only", "--diff-filter=U", check=False).stdout
        return [l for l in out.splitlines() if l.strip()]

    def acquire(self) -> None:
        if not self._has_remote():
            return
        r = self._run("pull", "--no-rebase", "--no-edit", check=False)
        if r.returncode != 0:
            conflicted = self._conflicted_files()
            if conflicted:
                raise ConflictError("git merge 冲突，需手工解决:\n" + "\n".join(conflicted))
            raise ConflictError(f"git pull 失败:\n{r.stderr or r.stdout}")

    def publish(self, message: str) -> None:
        self._run("add", "-A")
        if self._run("status", "--porcelain").stdout.strip():
            self._run("commit", "-m", message)
        if self._has_remote():
            r = self._run("push", check=False)
            if r.returncode != 0:
                raise ConflictError(f"git push 失败:\n{r.stderr or r.stdout}")

    def status(self) -> str:
        return self._run("status", "--porcelain").stdout
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_backend_git.py -v`
Expected: PASS（3 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/backend.py tests/hub/test_backend_git.py
git commit -m "feat(hub): Backend 抽象 + GitBackend(ff-only 冲突即抛)"
```

---

### Task 12: cli —— 子命令串起端到端

**Files:**
- Create: `hub/cli.py`, `tests/hub/test_cli.py`

**Interfaces:**
- Consumes: 全部前置模块。
- Produces: `main(argv:list[str]) -> int`；子命令 `status` / `collect` / `process` / `pull` / `sync` / `bootstrap`。以 `--vault <path>` 指定本地金库 clone，`--host <name>` 覆盖主机名（默认 `current_host()`）。
  - `collect` = 按设备档案 `collect_sources` 扫本机工具目录，用 `collect_memories`（Task 10）把记忆整文件收进金库 `memory/`。
  - `process` = lint（scope / 裸路径 / **敏感记忆混入**）→ 重生成 `MEMORY.md`（派生）→ 本地 commit；lint 失败返回 1、不 commit。
  - `pull` = `acquire`（自动 merge）+ materialize 到设备 targets 与用户级。
  - `sync` = `acquire`（**真冲突即停返回 2**）→ lint 闸（失败返回 1）→ `publish`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_cli.py
import subprocess
from pathlib import Path
from hub.cli import main

def _init_git(repo):
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

def _mk_vault(root: Path, host: str):
    (root / "rules").mkdir(parents=True)
    (root / "memory").mkdir()
    (root / "devices").mkdir()
    (root / "vault.toml").write_text("version = 1\n", encoding="utf-8")
    (root / "rules" / "a.md").write_text("规则A\n", encoding="utf-8")
    (root / "memory" / "m1.md").write_text(
        "---\nname: m1\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    tgt = root / "proj"; tgt.mkdir()
    (root / "devices" / f"{host}.toml").write_text(
        f'class = ["work"]\nprojects = ["xinao"]\n\n[paths]\nVAULT = "{root.as_posix()}"\n\n'
        f'[[targets]]\nproject = "xinao"\nroot = "{tgt.as_posix()}"\n',
        encoding="utf-8")
    return tgt

def test_process_regenerates_index_and_commits(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "MEMORY.md").exists()
    assert "m1" in (vault / "MEMORY.md").read_text(encoding="utf-8")

def test_pull_materializes_agents_md(tmp_path):
    vault = tmp_path / "vault"; tgt = _mk_vault(vault, "h1"); _init_git(vault)
    rc = main(["pull", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    agents = (tgt / "AGENTS.md").read_text(encoding="utf-8")
    assert "规则A" in agents

def test_process_blocks_sensitive(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1"); _init_git(vault)
    (vault / "memory" / "sec.md").write_text(
        "---\nname: sec\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: true\n---\n密\n",
        encoding="utf-8")
    rc = main(["process", "--vault", str(vault), "--host", "h1"])
    assert rc == 1                       # 敏感记忆混入 -> lint 拦停，不生成索引
    assert not (vault / "MEMORY.md").exists()

def test_collect_pulls_into_vault(tmp_path):
    vault = tmp_path / "vault"; _mk_vault(vault, "h1")
    src = tmp_path / "toolmem"; src.mkdir()
    (src / "new.md").write_text(
        "---\nname: newmem\ndescription: d\nmetadata:\n  type: project\n"
        "  scope: [global]\n  portable: true\n  sensitive: false\n---\n正文\n",
        encoding="utf-8")
    dev_toml = vault / "devices" / "h1.toml"
    dev_toml.write_text(dev_toml.read_text(encoding="utf-8")
                        + f'\ncollect_sources = ["{src.as_posix()}"]\n', encoding="utf-8")
    rc = main(["collect", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    assert (vault / "memory" / "newmem.md").exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'hub.cli'`。

- [ ] **Step 3: 写实现**

```python
# hub/cli.py
import argparse
from pathlib import Path
from hub.vault import load_vault, load_device, current_host
from hub.derive import render_memory_index
from hub.scope import lint_scope
from hub.links import lint_raw_paths
from hub.materialize import (render_agents_md, render_claude_md,
                             select_for_target, codex_project_inner)
from hub.model import Target
from hub.backend import GitBackend, ConflictError
from hub.collect import collect_memories

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

def _lint(vault) -> list[str]:
    errs = []
    for m in vault.memories:
        errs += [f"{m.name}: {e}" for e in lint_scope(m.scope)]
        errs += [f"{m.name}: 裸路径 {h}" for h in lint_raw_paths(m.body)]
        if m.sensitive:
            errs.append(f"{m.name}: sensitive:true 记忆不应进入金库")
    return errs

def _cmd_process(args) -> int:
    vault_root = Path(args.vault)
    vault = load_vault(vault_root)
    errs = _lint(vault)
    if errs:
        print("lint 失败:")
        for e in errs:
            print("  -", e)
        return 1
    _write(vault_root / "MEMORY.md", render_memory_index(vault.memories))
    GitBackend(vault_root).publish("chore(hub): process 重生成索引")
    return 0

def _cmd_pull(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    vault = load_vault(vault_root)
    dev = load_device(vault_root, host)
    GitBackend(vault_root).acquire()
    for t in dev.targets:
        root = Path(t.root)
        # Codex 项目记忆块
        codex_mems = select_for_target(
            vault.memories, Target(frozenset(dev.classes), t.project, "codex"))
        proj_only = [m for m in codex_mems if f"project:{t.project}" in m.scope]
        inner = codex_project_inner(proj_only, dev.paths) if proj_only else ""
        agents_path = root / "AGENTS.md"
        existing = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
        _write(agents_path, render_agents_md(existing, vault.rules, inner))
        claude_path = root / "CLAUDE.md"
        c_existing = claude_path.read_text(encoding="utf-8") if claude_path.exists() else ""
        _write(claude_path, render_claude_md(c_existing, "hub/memory-index.md"))
    return 0

def _cmd_status(args) -> int:
    print(GitBackend(Path(args.vault)).status(), end="")
    return 0

def _cmd_sync(args) -> int:
    vault_root = Path(args.vault)
    b = GitBackend(vault_root)
    try:
        b.acquire()
    except ConflictError as e:
        print("sync 停止：git 冲突，请手工解决后 `hub sync` 重试")
        print(e)
        return 2
    errs = _lint(load_vault(vault_root))
    if errs:
        print("sync 停止：lint 失败（敏感/裸路径/scope）：")
        for e in errs:
            print("  -", e)
        return 1
    b.publish("chore(hub): sync")
    return 0

def _cmd_bootstrap(args) -> int:
    # MVP: 首次落地 = 对已 clone 的金库执行 pull materialize
    return _cmd_pull(args)

def _cmd_collect(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    dev = load_device(vault_root, host)
    sources = [Path(s) for s in dev.collect_sources]
    collected = collect_memories(sources, vault_root / "memory")
    print(f"collected {len(collected)} memories: {collected}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hub")
    p.add_argument("--vault", required=True)
    p.add_argument("--host", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("process", _cmd_process), ("pull", _cmd_pull),
                     ("sync", _cmd_sync), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name)
        sp.set_defaults(func=fn)
    return p

def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
```

> 注：`--vault`/`--host` 定义在**顶层** parser（子命令前）。测试里 `main(["process", "--vault", ...])` 会失败于此顺序——**实现时把 `--vault`/`--host` 加到每个子 parser**，或在测试里把全局参数放最前。采用后者以匹配上面测试：把 `--vault/--host` 用 `parents=` 注入每个子 parser。见下方修正实现。

- [ ] **Step 3b: 用 parents 注入全局参数（修正，使子命令后置 --vault 可用）**

```python
# 替换 build_parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", required=True)
    common.add_argument("--host", default=None)
    p = argparse.ArgumentParser(prog="hub")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("status", _cmd_status), ("collect", _cmd_collect),
                     ("process", _cmd_process), ("pull", _cmd_pull),
                     ("sync", _cmd_sync), ("bootstrap", _cmd_bootstrap)):
        sp = sub.add_parser(name, parents=[common])
        sp.set_defaults(func=fn)
    return p
```

- [ ] **Step 4: 运行验证通过**

Run: `py -3 -m pytest tests/hub/test_cli.py -v`
Expected: PASS（4 passed）。

- [ ] **Step 5: 跑全量测试**

Run: `py -3 -m pytest tests/hub -v`
Expected: 全绿（约 32 passed；Task 13/14 后再增）。

- [ ] **Step 6: 提交**

```bash
git add hub/cli.py tests/hub/test_cli.py
git commit -m "feat(hub): CLI 子命令 status/process/pull/sync/bootstrap 串端到端"
```

---

### Task 13: 用户级记忆落盘 —— Claude memory-index bundle + Codex memories

**Files:**
- Modify: `hub/materialize.py`, `tests/hub/test_materialize.py`
- Modify: `hub/cli.py`（在 `_cmd_pull` 补用户级落盘，落一次）

**Interfaces:**
- Consumes: `select_for_target`、`render_memory_bundle`（Task 9）、`Target`（Task 1）。
- Produces（**注意都要接收当前设备 `device_classes`，否则 `device:work` 这类记忆匹配不上**）：
  - `write_claude_index(memories:list[Memory], paths:dict[str,str], claude_home:Path, device_classes:list[str]) -> Path`（把 `Target(frozenset(device_classes), None, "claude")` 选中的记忆渲染成 bundle，写 `claude_home/hub/memory-index.md`，返回该路径）；
  - `write_codex_user_memories(memories:list[Memory], paths:dict[str,str], codex_mem_dir:Path, device_classes:list[str]) -> list[str]`（用 `Target(frozenset(device_classes), None, "codex")` 选中，再排除含 `project:` 维度的，逐条整文件写入，返回 name 列表）；
  - `ensure_user_claude_import(existing:str, import_target:str) -> str`（在 managed block 内放 `@<import_target>`，块外用户内容保留；供确保 `~/.claude/CLAUDE.md` 真导入 memory-index）。

- [ ] **Step 1: 写失败测试（追加到 test_materialize.py）**

```python
from pathlib import Path
from hub.materialize import write_claude_index, write_codex_user_memories

def test_write_claude_index_bundle(tmp_path):
    home = tmp_path / "claude"
    mems = [_mem("g", ["global"], body="看 $VAULT/a\n")]
    out = write_claude_index(mems, {"VAULT": "Z:/v"}, home, ["work"])
    assert out == home / "hub" / "memory-index.md"
    assert "Z:/v/a" in out.read_text(encoding="utf-8")

def test_write_claude_index_matches_device_scope(tmp_path):
    # device:work 记忆：本机 class 含 work 才应命中（回归 Target 丢 classes 的 bug）
    home = tmp_path / "claude"
    mems = [_mem("w", ["device:work"], body="仅公司机\n")]
    got = write_claude_index(mems, {}, home, ["work"]).read_text(encoding="utf-8")
    assert "仅公司机" in got
    home2 = tmp_path / "claude2"
    got2 = write_claude_index(mems, {}, home2, ["home"]).read_text(encoding="utf-8")
    assert "仅公司机" not in got2

def test_write_codex_user_skips_project_scoped(tmp_path):
    d = tmp_path / "codexmem"
    mems = [_mem("g", ["global"]), _mem("p", ["project:xinao"])]
    written = write_codex_user_memories(mems, {}, d, ["work"])
    assert written == ["g"]                 # project 级不进用户目录
    assert (d / "g.md").exists()
    assert not (d / "p.md").exists()

def test_ensure_user_claude_import_idempotent():
    from hub.materialize import ensure_user_claude_import
    once = ensure_user_claude_import("我的手写\n", "hub/memory-index.md")
    twice = ensure_user_claude_import(once, "hub/memory-index.md")
    assert twice.count("@hub/memory-index.md") == 1
    assert "我的手写" in twice
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_materialize.py -k "claude_index or codex_user" -v`
Expected: FAIL，`ImportError: cannot import name 'write_claude_index'`。

- [ ] **Step 3: 写实现（追加到 `hub/materialize.py`）**

```python
from pathlib import Path
from hub.frontmatter import dump_memory

def write_claude_index(memories: list[Memory], paths: dict[str, str],
                       claude_home: Path, device_classes: list[str]) -> Path:
    target = Target(frozenset(device_classes), None, "claude")
    selected = select_for_target(memories, target)
    out = Path(claude_home) / "hub" / "memory-index.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_memory_bundle(selected, paths),
                   encoding="utf-8", newline="\n")
    return out

def write_codex_user_memories(memories: list[Memory], paths: dict[str, str],
                              codex_mem_dir: Path, device_classes: list[str]) -> list[str]:
    target = Target(frozenset(device_classes), None, "codex")
    d = Path(codex_mem_dir)
    d.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for m in select_for_target(memories, target):
        if any(s.startswith("project:") for s in m.scope):
            continue
        (d / f"{m.name}.md").write_text(dump_memory(m), encoding="utf-8", newline="\n")
        written.append(m.name)
    return written

def ensure_user_claude_import(existing: str, import_target: str) -> str:
    return replace_block(existing, f"@{import_target}")
```

- [ ] **Step 4: 运行验证通过 + CLI 接线**

在 `hub/cli.py` 的 `_cmd_pull` 顶部（`for t in dev.targets:` **之前**）补用户级落盘：
```python
    from hub.materialize import (write_claude_index, write_codex_user_memories,
                                 ensure_user_claude_import)
    claude_home = dev.paths.get("CLAUDE_HOME")
    if claude_home:
        write_claude_index(vault.memories, dev.paths, Path(claude_home), dev.classes)
        cpath = Path(claude_home) / "CLAUDE.md"
        cexist = cpath.read_text(encoding="utf-8") if cpath.exists() else ""
        _write(cpath, ensure_user_claude_import(cexist, "hub/memory-index.md"))
    codex_home = dev.paths.get("CODEX_HOME")
    if codex_home:
        write_codex_user_memories(vault.memories, dev.paths,
                                  Path(codex_home) / "memories", dev.classes)
```
Run: `py -3 -m pytest tests/hub -v`
Expected: 全绿（约 35 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/materialize.py hub/cli.py tests/hub/test_materialize.py
git commit -m "feat(hub): 用户级记忆落盘(Claude memory-index bundle + Codex memories)"
```

---

### Task 14: Claude 工程记忆落地 —— project:<id> 进工程 memory 目录

**Files:**
- Modify: `hub/materialize.py`, `tests/hub/test_materialize.py`, `hub/cli.py`

**Interfaces:**
- Consumes: `select_for_target`（Task 9）、`dump_memory`（Task 2）、`claude_migrate.encode_project_path`（`claude_migrate.py:300`，把绝对路径每个非字母数字字符替换成 `-`）。
- Produces: `materialize_claude_project(memories:list[Memory], project:str, project_root:str, claude_home:Path, device_classes:list[str]) -> Path`（把命中当前设备/工程、且 scope 含 `project:<project>` 的记忆逐条整文件写入 `claude_home/projects/<encode_project_path(project_root)>/memory/`；全局记忆不落此处；返回该 memory 目录）。

> 说明：Claude 工程记忆按**整文件**落地（与 Codex 用户记忆一致），保留符号根原样（MVP 不在原子文件里解析 `$ROOT`，与 bundle 的差异见收尾已知限制）。

- [ ] **Step 1: 写失败测试（追加到 test_materialize.py）**

```python
def test_materialize_claude_project_lands_in_encoded_dir(tmp_path):
    from hub.materialize import materialize_claude_project
    from claude_migrate import encode_project_path
    home = tmp_path / "claude"
    root = "C:/proj/x"
    mems = [_mem("pj", ["project:xinao"], body="坑\n"),
            _mem("g", ["global"], body="全局\n")]
    mem_dir = materialize_claude_project(mems, "xinao", root, home, ["work"])
    assert mem_dir.parent.name == encode_project_path(root)   # 目录名编码一致
    assert (mem_dir / "pj.md").exists()       # 项目级落地
    assert not (mem_dir / "g.md").exists()    # 全局不进工程目录
```

- [ ] **Step 2: 运行验证失败**

Run: `py -3 -m pytest tests/hub/test_materialize.py -k materialize_claude_project -v`
Expected: FAIL，`ImportError: cannot import name 'materialize_claude_project'`。

- [ ] **Step 3: 写实现（追加到 `hub/materialize.py`）**

```python
from claude_migrate import encode_project_path

def materialize_claude_project(memories: list[Memory], project: str,
                               project_root: str, claude_home: Path,
                               device_classes: list[str]) -> Path:
    target = Target(frozenset(device_classes), project, "claude")
    mem_dir = Path(claude_home) / "projects" / encode_project_path(str(project_root)) / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    for m in select_for_target(memories, target):
        if f"project:{project}" not in m.scope:
            continue
        (mem_dir / f"{m.name}.md").write_text(dump_memory(m), encoding="utf-8", newline="\n")
    return mem_dir
```

- [ ] **Step 4: 运行验证通过 + CLI 接线**

在 `hub/cli.py` 顶部 import 追加 `materialize_claude_project`；在 `_cmd_pull` 的 `for t in dev.targets:` 循环内、写完 AGENTS.md/CLAUDE.md 后追加：
```python
        cl_home = dev.paths.get("CLAUDE_HOME")
        if cl_home:
            materialize_claude_project(vault.memories, t.project, t.root,
                                       Path(cl_home), dev.classes)
```
Run: `py -3 -m pytest tests/hub -v`
Expected: 全绿（约 36 passed）。

- [ ] **Step 5: 提交**

```bash
git add hub/materialize.py hub/cli.py tests/hub/test_materialize.py
git commit -m "feat(hub): Claude 工程记忆落地(project:<id> 进 memory 目录,复用 encode_project_path)"
```

---

## 收尾（计划外，落地后人工）

- 在真实金库里建 `devices/<你的主机>.toml`，登记 `[paths]`（含 `CLAUDE_HOME`/`CODEX_HOME`）、`[[targets]]`、`collect_sources`，跑 `hub collect` + `hub process` + `hub pull` 做一次真机往返验证。
- 把 `~/.claude/CLAUDE.md`、`AGENTS.md` 现有重复规则手工迁进金库 `rules/*.md`（一次性）。
- **已知限制**：原子记忆文件（Codex 用户级、Claude 工程级）落地时**不解析符号根**（`$VAULT/...` 原样写出），只有 Claude memory-index bundle 会解析。若某条项目记忆强依赖解析后的绝对路径，暂用 bundle 侧或后续迭代补原子解析。
- §13 两个开放问题（push 默认 scope 推断、新工程登记方式）在此之后再迭代。

## Self-Review

- **Spec 覆盖**：§3 金库结构→Task 6；§4 数据模型/scope→Task 1/2/3；§5 设备相关性→Task 3+CLI 过滤；§6 链接可移植→Task 5+9；§7 免冲突(一条一文件/规则拆分/MEMORY 派生)→Task 7/10；§8.1 collect 防回环→Task 10；§8.2/8.3 materialize+targets→Task 8/9/12；§9 吸收 migrate→包结构(bootstrap 复用，MVP 先最小)；§11 冲突即停/无 BOM/备份→Task 11+CLI(`newline="\n"`)；§14 依赖→Task 1 校验 + tomllib/自写 YAML 子集。§8.2 用户级落盘（Claude memory-index bundle + Codex `memories/`）→ **Task 13**；`project:<id>` 记忆写入 Claude 工程 `memory/` 目录 → **Task 14**（复用 `encode_project_path`）。两处缺口均已闭合，MVP materialize 目标全覆盖。

**评审二轮修订（多机核心场景）**：① Task 11 改普通 merge、只在真冲突停（对等场景自动合并）；② Task 12 collect 真接 `collect_memories`（设备档案加 `collect_sources`）；③ Task 13 `write_*` 接收 `device_classes`，修 `device:work` 匹配不上的 bug；④ 用户级 `~/.claude/CLAUDE.md` 真写 `@memory-index` 导入；⑤ `_lint`+`_cmd_sync` 拦截敏感记忆混入金库。
- **占位符扫描**：无 TBD/TODO；每步含真实代码与命令。
- **类型一致**：`Target`、`Memory`、`select_for_target`/`render_memory_bundle`/`render_agents_md` 签名跨 Task 8/9/12 一致；`GitBackend.acquire/publish/status` 与 CLI 调用一致。
