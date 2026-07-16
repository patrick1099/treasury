# hub C 阶段 · Plan 1：skill 活链闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本机的 skill 有一份真源（金库 `shared/skills/`），经目录链接（Windows junction）活链进 Claude / Codex / opencode 三家，改一处三家实时生效，且 A 的 `collect` 不再把这些活链当本机产物重复备份。

**Architecture:** 新增三个纯函数模块 —— `fslink`（跨平台目录链接 + realpath 归属判断）、`promote`（由 host/tool/name 推导备份区源 → `shared/`，复制、过 guard、冲突即停）、`register`（**非破坏**：写盘前完整只读预检，把 `shared/skills/<n>` 逐个链进各工具 skill 目录，冲突即停不删用户东西）；对既有 `collect_skills` 做两处改动——加"realpath 落进 `shared/` 就跳过"，并把 `rmtree` 从循环前挪到只读分类全过之后（修"先删后验"）；`hub status` 扩一段只查 shared 期望项的链接健康报告。全部走既有 `Writer`（dry-run 闸）与 `guard`（读闸）。

**Tech Stack:** Python ≥ 3.11（纯标准库，无第三方）；pytest；Windows 主力（`mklink /J` junction）。

## Global Constraints

- **纯标准库**，不引第三方依赖；Python ≥ 3.11（实测 3.14）。
- **所有写/删必须走 `hub.writer.Writer`**；`--dry-run` 的闸在 Writer 内部，调用方不得绕过自己写盘。
- **任何"读源"必须先过 `hub.guard.check_source(path)`**（密钥路径硬闸，不可豁免）。
- **link-only**：建链接失败就**明确报错并指名**，绝不静默退化成拷贝。
- **register/promote 非破坏**：写盘前先做**完整只读预检**；发现冲突（目标已被非 hub 管理的同名项占用、
  同名不同内容）就**一个字节都不动**并报错，绝不为"就位"而删用户的东西或覆盖。
- **Windows 用目录 junction**（`mklink /J`，不需管理员）；POSIX 用 symlink。
- **金库两区语义**：备份区 `<host>/<tool>/`（A 只写这里），共享区 `shared/`（A 从不写；C 经 `promote` 写）。
- 提交身份（**已定，2026-07-16**）：个人仓，`user.name = patrick1099`、`user.email =
  245735497+patrick1099@users.noreply.github.com`（GitHub noreply，本仓可能公开，用户已选 noreply 而非真邮箱）。
  已写进本仓 `git config --local`，commit 命令无需再带 `-c user.email=...`。commit message 结尾按会话惯例附
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 运行测试：`py -3 -m pytest tests/hub -q`（Windows 用 `py -3`，不用裸 `python`）。

---

## Task 0：前置手动验证 —— junction 跟随性冒烟测试（门槛，非代码）

link-only 的**唯一真风险**：某个工具不跟随 Windows 目录 junction。此测试由**用户手动**在真机跑（本计划的实现者无法启动这三个工具）。

**门槛判定（NEEDS v1 首要 = Claude + Codex）**：
- **Claude + Codex 都跟随 = 继续 Task 1**；这两家里哪家不跟随 = 停下来找作者具体议，不要自动改成 copy。
- **opencode 只是非阻断观察项**：跟随更好，不跟随也不拦住本计划（opencode 在 NEEDS 里是次级/未来）。记下结论即可。

- [ ] **Step 1：造一个测试 skill 的真目录**（临时、可弃）

```powershell
$src = "$env:USERPROFILE\hub-smoke\skills\hub-smoke-test"
New-Item -ItemType Directory -Force $src | Out-Null
# BOM-free UTF-8：Windows PowerShell 5.1 的 Set-Content -Encoding utf8 会写 BOM，
# frontmatter 头部带 BOM 可能影响解析，这里用 .NET 直写无 BOM。
$body = @"
---
name: hub-smoke-test
description: junction 跟随性冒烟测试，用完即删
---
如果你能看到这把 skill，说明本工具跟随了目录 junction。
"@
[System.IO.File]::WriteAllText("$src\SKILL.md", $body, (New-Object System.Text.UTF8Encoding($false)))
```

- [ ] **Step 2：在三家各建一个指向它的目录 junction**

```powershell
# 先确保两个 skills 父目录都存在（mklink 不会替你建父目录）
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
cmd /c mklink /J "$env:USERPROFILE\.claude\skills\hub-smoke-test"  $src
cmd /c mklink /J "$env:USERPROFILE\.agents\skills\hub-smoke-test"  $src   # Codex + opencode 读这里
```
（注意：链接的是**逐个 skill 目录**，不是把整个 `skills` 目录做成链接。）

- [ ] **Step 3：分别启动 Claude Code / Codex / opencode，确认 `hub-smoke-test` 能被发现**

在每个工具里查看 skill 列表（或直接调用），确认三家都能看到这把 skill。

- [ ] **Step 4：记录结论并清理**

```powershell
# 用 cmd /c rmdir 删 junction 链接点：只摘掉 reparse 点、绝不跟进目标删内容，
# 且不依赖不同 PowerShell 版本对 junction 的处理差异（Remove-Item 各版本行为不一）。
cmd /c rmdir "$env:USERPROFILE\.claude\skills\hub-smoke-test"
cmd /c rmdir "$env:USERPROFILE\.agents\skills\hub-smoke-test"
# 真源目录（不是链接）用 Remove-Item 递归删。
Remove-Item "$env:USERPROFILE\hub-smoke" -Recurse -Force
```
把"哪几家跟随/不跟随"回报。**门槛判定**：Claude + Codex 全绿 → 进 Task 1；这两家有红 → 暂停本计划，回到设计讨论。opencode 结论仅记录。

---

## Task 1：linking 原语（`fslink` 底层 + `Writer` 链接方法）

**Files:**
- Create: `hub/fslink.py`
- Modify: `hub/writer.py`（新增两个链接方法，走 dry-run 闸）
- Test: `tests/hub/test_fslink.py`、`tests/hub/test_writer.py`（新增用例）

**Interfaces:**
- `fslink`（底层 os 操作，不含 dry-run）：
  - `make_dir_link(target: Path, link: Path) -> None` —— 在 `link` 处建指向 `target` 的**目录**链接（Windows junction / POSIX symlink）。父目录自动建。`target` 不是目录 → `NotADirectoryError`。建链失败 → `LinkError`。
  - `remove_dir_link(link: Path) -> None` —— **只删链接点本身，绝不跟随进目标删内容**（Windows `os.rmdir` 删 junction 点；POSIX `os.unlink` 删 symlink）。链接不存在 → no-op。若 `link` 是真实非空目录，`os.rmdir` 会失败——**这是刻意的防线**：绝不误删真目录。
  - `is_under(path: Path, ancestor: Path) -> bool` —— `path` 跟随 junction/symlink 解析后是否落在 `ancestor` 内（含相等）。
  - `class LinkError(RuntimeError)`。
- `Writer`（唯一写入口，dry-run 闸在内）：
  - `make_dir_link(self, target: Path, link: Path) -> None` —— 包 `fslink.make_dir_link`，记入 `self.written`，dry-run 只打印不落盘。
  - `remove_dir_link(self, link: Path) -> None` —— 包 `fslink.remove_dir_link`，记入 `self.removed`，dry-run 只打印；链接不存在 no-op。
- **为什么链接也走 Writer**：项目铁律"所有写/删走 Writer、dry-run 闸在原语里"。链接创建/删除是写盘，直接调 `fslink` 会绕过 dry-run（本项目已因"闸设在调用方"出过四次事故）。
- **`remove_dir_link` 本计划不被 register 调用**（register 改为非破坏、从不删）。它是给将来 `refresh --prune` 用的**已验证安全**原语——在这里先建好并测出"只删链接点、绝不误删真目录"这条不变量，胜过等到要删时才临时写。

- [ ] **Step 1：写失败测试**

```python
# tests/hub/test_fslink.py
import os
import pytest
from pathlib import Path
from hub.fslink import make_dir_link, remove_dir_link, is_under, LinkError

def test_make_dir_link_creates_followable_link(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "marker.txt").write_text("hi", encoding="utf-8")
    link = tmp_path / "sub" / "linked"          # 父目录 sub 不存在，应自动建
    make_dir_link(target, link)
    assert (link / "marker.txt").read_text(encoding="utf-8") == "hi"   # 经链接读到真内容

def test_make_dir_link_rejects_missing_target(tmp_path):
    with pytest.raises(NotADirectoryError):
        make_dir_link(tmp_path / "nope", tmp_path / "link")

def test_remove_dir_link_deletes_link_not_target(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    link = tmp_path / "linked"
    make_dir_link(target, link)
    remove_dir_link(link)
    assert not os.path.lexists(link)                     # 链接没了
    assert (target / "keep.txt").exists()                # 目标内容完好无损

def test_remove_dir_link_absent_is_noop(tmp_path):
    remove_dir_link(tmp_path / "nothing")                # 不抛

def test_is_under_true_through_link(tmp_path):
    shared = tmp_path / "vault" / "shared" / "skills"
    (shared / "foo").mkdir(parents=True)
    link = tmp_path / "home" / "skills" / "foo"
    make_dir_link(shared / "foo", link)
    assert is_under(link, tmp_path / "vault" / "shared") is True

def test_is_under_false_for_unrelated_dir(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert is_under(tmp_path / "a", tmp_path / "b") is False

def test_is_under_true_when_equal(tmp_path):
    (tmp_path / "a").mkdir()
    assert is_under(tmp_path / "a", tmp_path / "a") is True
```

同时给 `tests/hub/test_writer.py` 追加：

```python
# 追加到 tests/hub/test_writer.py
import os
from pathlib import Path
from hub.writer import Writer

def test_writer_make_and_remove_link(tmp_path):
    target = tmp_path / "t"; target.mkdir()
    (target / "m.txt").write_text("hi", encoding="utf-8")
    link = tmp_path / "l"
    w = Writer()
    w.make_dir_link(target, link)
    assert (link / "m.txt").read_text(encoding="utf-8") == "hi"
    assert link in w.written
    w.remove_dir_link(link)
    assert not os.path.lexists(link)
    assert (target / "m.txt").exists()                   # 目标不受影响
    assert link in w.removed

def test_writer_dry_run_link_writes_nothing(tmp_path):
    target = tmp_path / "t"; target.mkdir()
    link = tmp_path / "l"
    w = Writer(dry_run=True)
    w.make_dir_link(target, link)
    assert not os.path.lexists(link)                     # dry-run：没建
    assert link in w.written                             # 但报告说"会"建
```

- [ ] **Step 2：运行，确认失败**

Run: `py -3 -m pytest tests/hub/test_fslink.py tests/hub/test_writer.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.fslink'`（及 Writer 无 `make_dir_link`）

- [ ] **Step 3：写实现**

新建 `hub/fslink.py`：

```python
# hub/fslink.py
"""跨平台目录链接 + realpath 归属判断（底层 os 操作，不含 dry-run）。

link-only：建链失败就抛错，绝不静默拷贝。
Windows 用目录 junction（mklink /J，不需管理员），POSIX 用 symlink。
删除只删链接点、绝不跟随进目标删内容。
"""
import os
import subprocess
from pathlib import Path

class LinkError(RuntimeError):
    pass

def make_dir_link(target: Path, link: Path) -> None:
    target, link = Path(target), Path(link)
    if not target.is_dir():
        raise NotADirectoryError(f"链接目标不是目录或不存在: {target}")
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # junction：不需要管理员/开发者模式（symlink 才需要）
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise LinkError(f"mklink /J 失败 ({link} → {target}): "
                            f"{r.stderr.strip() or r.stdout.strip()}")
    else:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as e:
            raise LinkError(f"symlink 失败 ({link} → {target}): {e}") from e

def remove_dir_link(link: Path) -> None:
    """只删链接点本身。Windows junction 用 os.rmdir（删 reparse 点、不碰目标）；
    POSIX symlink 用 os.unlink。若 link 是真实非空目录，os.rmdir 会抛——刻意的防线，
    绝不误删真目录内容。"""
    link = Path(link)
    if not os.path.lexists(link):
        return
    if os.name == "nt":
        os.rmdir(link)
    else:
        os.unlink(link)

def is_under(path: Path, ancestor: Path) -> bool:
    p = Path(path).resolve()
    a = Path(ancestor).resolve()
    return p == a or a in p.parents
```

在 `hub/writer.py` 顶部 import 后加：

```python
from hub import fslink        # fslink 只依赖 stdlib，无循环导入
```

在 `Writer` 类里加两个方法（放在 `unlink` 附近即可）：

```python
    def make_dir_link(self, target: Path, link: Path) -> None:
        link = Path(link)
        self.written.append(link)
        if self.dry_run:
            print(f"  [dry-run] 建链接 {link} → {target}")
            return
        fslink.make_dir_link(target, link)

    def remove_dir_link(self, link: Path) -> None:
        import os
        link = Path(link)
        if not os.path.lexists(link):
            return
        self.removed.append(link)
        if self.dry_run:
            print(f"  [dry-run] 删除链接 {link}")
            return
        fslink.remove_dir_link(link)
```

- [ ] **Step 4：运行，确认通过**

Run: `py -3 -m pytest tests/hub/test_fslink.py tests/hub/test_writer.py -v`
Expected: PASS（全部）

- [ ] **Step 5：提交**

```bash
git add hub/fslink.py hub/writer.py tests/hub/test_fslink.py tests/hub/test_writer.py
git commit -m "feat(hub): add fslink primitives + Writer.make/remove_dir_link (dry-run gated)"
```

---

## Task 2：`promote_skill` —— 备份区 → shared，复制、冲突即停

**Files:**
- Create: `hub/promote.py`
- Test: `tests/hub/test_promote.py`

**Interfaces:**
- Consumes: `hub.writer.Writer`；`hub.model.SHARED`；`hub.guard.check_source, is_denied`。
- Produces:
  - `promote_skill(vault_root: Path, host: str, tool: str, name: str, w: Writer) -> Path` —— **源由 `vault_root/host/tool/skills/name` 推导**（不收任意绝对路径），复制进 `shared/skills/<name>`，返回目标路径。封死边界：
    - **`host`/`tool`/`name` 三者都必须是单路径组件**（含 `/`、`\`、或为 `.`/`..`/空 → `ValueError`）——挡 `host="../.."` 之类逃出备份区。
    - **先 `check_source(src)` 再碰类型**（guard 先于任何 access，全局约束）。
    - **解析后的 `src` 必须严格落在 `vault_root/host/` 备份区内**（`src.resolve()`），挡"skill 目录本身是指向备份区外的链接"这种逃逸。逃出 → `ValueError`。
    - 源不是目录/不存在 → `FileNotFoundError`。
    - 目标 dest 用 `os.path.lexists` 分类：不存在 → 拷；是**目录**且内容相同 → **严格幂等，直接 `return dest` 不写**；是目录且内容不同 → `PromoteConflict`；是**非目录**（普通文件/坏链/指别处的链接）→ `PromoteConflict`（不让 `rmtree/copytree` 抛底层异常）。
    - 内容比对按 `is_denied` 排除密钥文件，与 `copy_tree` 实际拷贝集合一致。
  - `class PromoteConflict(RuntimeError)`。
- 说明："复制不是移动"（SCHEMA §6/§7）——源在备份区不动，下次 collect 照样镜像它。

- [ ] **Step 1：写失败测试**

```python
# tests/hub/test_promote.py
import pytest
from pathlib import Path
from hub.promote import promote_skill, PromoteConflict
from hub.writer import Writer

def _skill(root: Path, name: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return d

def test_promote_copies_into_shared(tmp_path):
    vault = tmp_path / "vault"
    src = _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    dest = promote_skill(vault, "box1", "claude", "alpha", Writer())
    assert dest == vault / "shared" / "skills" / "alpha"
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# a\n"
    # 复制不是移动：源还在
    assert (src / "SKILL.md").exists()

def test_promote_same_content_is_strictly_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    promote_skill(vault, "box1", "claude", "alpha", Writer())
    w = Writer()
    dest = promote_skill(vault, "box1", "claude", "alpha", w)    # 内容相同：不该再写
    assert dest == vault / "shared" / "skills" / "alpha"
    assert w.written == []                                       # 严格无写入
    assert (vault / "shared" / "skills" / "alpha" / "SKILL.md").exists()

def test_promote_rejects_traversal_in_host(tmp_path):
    vault = tmp_path / "vault"
    with pytest.raises(ValueError):
        promote_skill(vault, "..", "claude", "alpha", Writer())

def test_promote_rejects_src_link_escaping_backup(tmp_path):
    """备份区里的 skill 目录本身是指向备份区外的链接——必须拒（防链接逃逸）。"""
    from hub.fslink import make_dir_link
    vault = tmp_path / "vault"
    outside = tmp_path / "outside_secret"; outside.mkdir()
    (outside / "SKILL.md").write_text("# 外部\n", encoding="utf-8")
    (vault / "box1" / "claude" / "skills").mkdir(parents=True)
    make_dir_link(outside, vault / "box1" / "claude" / "skills" / "alpha")
    with pytest.raises(ValueError, match="逃出备份区"):
        promote_skill(vault, "box1", "claude", "alpha", Writer())

def test_promote_conflict_when_dest_is_file(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    (vault / "shared" / "skills").mkdir(parents=True)
    (vault / "shared" / "skills" / "alpha").write_text("我是文件不是目录", encoding="utf-8")
    with pytest.raises(PromoteConflict):
        promote_skill(vault, "box1", "claude", "alpha", Writer())

def test_promote_conflict_stops_and_does_not_overwrite(tmp_path):
    vault = tmp_path / "vault"
    existing = _skill(vault / "shared" / "skills", "alpha", "# 共享区已有的版本\n")
    before = (existing / "SKILL.md").read_bytes()
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# 备份区不同的版本\n")
    with pytest.raises(PromoteConflict, match="alpha"):
        promote_skill(vault, "box1", "claude", "alpha", Writer())
    assert (existing / "SKILL.md").read_bytes() == before      # 一个字节都没动

def test_promote_missing_source_raises(tmp_path):
    vault = tmp_path / "vault"
    (vault / "box1" / "claude" / "skills").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        promote_skill(vault, "box1", "claude", "nope", Writer())

def test_promote_rejects_path_traversal_in_name(tmp_path):
    vault = tmp_path / "vault"
    with pytest.raises(ValueError):
        promote_skill(vault, "box1", "claude", "../../secrets", Writer())

def test_promote_dry_run_writes_nothing(tmp_path):
    vault = tmp_path / "vault"
    _skill(vault / "box1" / "claude" / "skills", "alpha", "# a\n")
    promote_skill(vault, "box1", "claude", "alpha", Writer(dry_run=True))
    assert not (vault / "shared" / "skills" / "alpha").exists()
```

- [ ] **Step 2：运行，确认失败**

Run: `py -3 -m pytest tests/hub/test_promote.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.promote'`

- [ ] **Step 3：写最小实现**

```python
# hub/promote.py
"""把备份区选定内容提升进共享区 shared/。

规矩（SCHEMA §6/§7）：**复制不是移动**（源在备份区不动，下次 collect 照样镜像）；
同名不同内容**立即停下问**，绝不静默覆盖。源由 host/tool/name 推导，三者都必须是
单路径组件、解析后严格落在备份区内 —— 不接受任意绝对路径，挡穿越/逃逸/密钥/自引用。
"""
import os
from pathlib import Path
from hub.model import SHARED
from hub.writer import Writer
from hub.guard import check_source, is_denied

class PromoteConflict(RuntimeError):
    pass

def _single_component(label: str, value: str) -> None:
    if "/" in value or "\\" in value or value in ("", ".", ".."):
        raise ValueError(f"非法 {label}（含路径分隔符或穿越）: {value!r}")

def _rel_files(root: Path) -> dict[str, bytes]:
    """目录树里所有文件的 {相对posix路径: 字节内容}。按内容比，不用 stat 浅比
    （filecmp.dircmp 默认按 os.stat 签名，同大小改内容会误判"相同"）。
    按 is_denied 排除密钥文件——与 copy_tree 实际拷贝的集合保持一致，
    否则 src 里若混进 .env，比对永远"不同"、还顺手读了密钥字节。"""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and not is_denied(p)}

def _same_tree(a: Path, b: Path) -> bool:
    return _rel_files(a) == _rel_files(b)

def promote_skill(vault_root: Path, host: str, tool: str, name: str, w: Writer) -> Path:
    _single_component("host", host)
    _single_component("tool", tool)
    _single_component("name", name)
    vault_root = Path(vault_root)
    backup_root = (vault_root / host).resolve()          # 本设备备份区根
    src = vault_root / host / tool / "skills" / name
    check_source(src)                                     # 读闸：先于任何 access（全局约束）
    rsrc = src.resolve()                                  # 跟随链接解析（strict=False）
    if rsrc != backup_root and backup_root not in rsrc.parents:
        raise ValueError(f"源逃出备份区（疑似链接逃逸）: {src} → {rsrc}")
    if not src.is_dir():
        raise FileNotFoundError(f"备份区没有这把 skill: {src}")

    dest = vault_root / SHARED / "skills" / name
    if os.path.lexists(dest):
        if not dest.is_dir():
            raise PromoteConflict(
                f"shared/skills/{name} 已被非目录（文件/坏链/异处链接）占用——停下来让你处理。")
        if _same_tree(src, dest):
            return dest                                  # 严格幂等：内容相同，一个字节都不写
        raise PromoteConflict(
            f"shared/skills/{name} 已存在且内容不同——停下来让你决定，"
            f"绝不静默覆盖。要么改名，要么先手工核对合并。")
    w.copy_tree(src, dest)
    return dest
```

- [ ] **Step 4：运行，确认通过**

Run: `py -3 -m pytest tests/hub/test_promote.py -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add hub/promote.py tests/hub/test_promote.py
git commit -m "feat(hub): add promote_skill — backup zone to shared, copy, stop on conflict"
```

---

## Task 3：`register_skills` —— 在各工具 skill 目录逐个建链接

**Files:**
- Create: `hub/register.py`
- Test: `tests/hub/test_register.py`

**Interfaces:**
- Consumes: `hub.model.DeviceProfile`（`paths` 里有 `CLAUDE_HOME`；`AGENTS_HOME` 缺省 `~/.agents`）；`hub.writer.Writer`。
- Produces:
  - `skill_targets(dev: DeviceProfile) -> list[Path]` —— 本机要建 skill 链接的目录集合：`<CLAUDE_HOME>/skills` 与 `<AGENTS_HOME>/skills`（Codex + opencode 共读）。缺失的 home 跳过。
  - `register_skills(vault_root: Path, dev: DeviceProfile, w: Writer) -> list[str]` —— **非破坏**。对 `shared/skills/` 下每把 skill × 每个目标目录，**先做完整只读预检再写**：
    - 目标位置**不存在** → 记入"待建"。
    - 目标已**精确指向**该 `shared/skills/<n>`（`link.resolve() == src.resolve()`）→ 已就位，no-op。
    - 目标已存在但**不是**该 source（用户自己的 skill、或指向别处的链接、或 resolve 失败）→ 记入**冲突**。
    - **预检发现任何冲突 → 抛 `RegisterConflict`，一个字节都不写**（不删空目录、不覆盖非空目录、不留半完成状态）。
    - 预检全过 → 只对"待建"逐个 `w.make_dir_link`。返回"现在已就位"的全部链接标签（待建 + 已就位），幂等重跑数目稳定。`shared/skills` 为空 → `[]`。
  - `class RegisterConflict(RuntimeError)`。
- 说明：`AGENTS_HOME` = `Path(dev.paths.get("AGENTS_HOME"))`，缺省 `Path.home() / ".agents"`。**register 绝不主动删任何路径**——清理残链是以后 `refresh --prune` 的活，不在 v1。**目标 `skills` 目录本身必须是真目录**（不能整个是链接，Codex issue #11314）——只链到 `skills/<name>` 这一层，天然满足。

- [ ] **Step 1：写失败测试**

```python
# tests/hub/test_register.py
import os
import pytest
from pathlib import Path
from hub.register import register_skills, skill_targets, RegisterConflict
from hub.model import DeviceProfile
from hub.fslink import make_dir_link
from hub.writer import Writer

def _dev(tmp_path) -> DeviceProfile:
    return DeviceProfile(
        host="box1", classes=["work"], projects=[],
        paths={"CLAUDE_HOME": str(tmp_path / "home" / ".claude"),
               "AGENTS_HOME": str(tmp_path / "home" / ".agents")},
        sources={})

def _shared_skill(vault: Path, name: str) -> Path:
    d = vault / "shared" / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return d

def test_register_links_each_skill_into_each_target(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    done = register_skills(vault, dev, Writer())
    claude = tmp_path / "home" / ".claude" / "skills" / "alpha"
    agents = tmp_path / "home" / ".agents" / "skills" / "alpha"
    assert (claude / "SKILL.md").read_text(encoding="utf-8") == "# alpha\n"   # 经链接可读
    assert (agents / "SKILL.md").read_text(encoding="utf-8") == "# alpha\n"
    assert len(done) == 2

def test_register_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    dev = _dev(tmp_path)
    first = register_skills(vault, dev, Writer())
    second = register_skills(vault, dev, Writer())        # 重跑不炸、数目稳定
    assert len(first) == len(second) == 2
    assert (tmp_path / "home" / ".claude" / "skills" / "alpha" / "SKILL.md").exists()

def test_register_empty_shared_does_nothing(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills").mkdir(parents=True)
    assert register_skills(vault, _dev(tmp_path), Writer()) == []

def test_register_conflict_nonempty_user_dir_is_untouched(tmp_path):
    """用户自己的同名 skill（非空真目录）——register 报冲突，一个字节不动。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    mine = tmp_path / "home" / ".claude" / "skills" / "alpha"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("# 我自己的 alpha\n", encoding="utf-8")
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "# 我自己的 alpha\n"

def test_register_conflict_empty_user_dir_not_deleted(tmp_path):
    """用户自己的同名空目录——register 报冲突，**不能**把它删掉。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    mine = tmp_path / "home" / ".claude" / "skills" / "alpha"
    mine.mkdir(parents=True)                       # 空目录：os.rmdir 本会成功——绝不许删
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())
    assert mine.is_dir()                            # 还在

def test_register_conflict_link_pointing_elsewhere(tmp_path):
    """同名位置是指向别处的链接——冲突，不覆盖。"""
    vault = tmp_path / "vault"
    _shared_skill(vault, "alpha")
    other = tmp_path / "somewhere_else"; other.mkdir()
    make_dir_link(other, tmp_path / "home" / ".claude" / "skills" / "alpha")
    with pytest.raises(RegisterConflict, match="alpha"):
        register_skills(vault, _dev(tmp_path), Writer())

def test_skill_targets_skips_missing_home(tmp_path):
    dev = DeviceProfile(host="box1", classes=[], projects=[],
                        paths={"CLAUDE_HOME": str(tmp_path / "c")}, sources={})
    targets = skill_targets(dev)
    assert (tmp_path / "c" / "skills") in targets
```

- [ ] **Step 2：运行，确认失败**

Run: `py -3 -m pytest tests/hub/test_register.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.register'`

- [ ] **Step 3：写最小实现**

```python
# hub/register.py
"""C 的注册器：把金库共享源活链进各工具地盘（link-only，非破坏）。

Plan 1 只做 skill。逐个 skill 建目录 junction，改一处三家实时生效。
写盘前完整只读预检：**发现任何冲突就零写入**（一个字节都不写），绝不删用户的东西。
预检通过后逐个建链——**这一步不是原子的**：若第 N 个建链遇系统错误，前 N-1 个已建、
不回滚。但 link-only 且幂等，重跑 register 会把剩下的补齐，不留脏拷贝。
建链走 Writer（dry-run 闸，见 fslink）。register 本身**从不删任何路径**。
"""
import os
from pathlib import Path
from hub.model import SHARED, DeviceProfile
from hub.writer import Writer

class RegisterConflict(RuntimeError):
    pass

def _agents_home(dev: DeviceProfile) -> Path:
    v = dev.paths.get("AGENTS_HOME")
    return Path(v) if v else Path.home() / ".agents"

def skill_targets(dev: DeviceProfile) -> list[Path]:
    """本机要建 skill 链接的 skills 目录集合。缺失的 home 跳过。"""
    out: list[Path] = []
    ch = dev.paths.get("CLAUDE_HOME")
    if ch:
        out.append(Path(ch) / "skills")          # Claude 读这里
    out.append(_agents_home(dev) / "skills")     # Codex + opencode 读这里
    return out

def _points_at(link: Path, src: Path) -> bool:
    """link 是否精确解析到 src。resolve 失败（坏链/环等）→ False（当作不是我们的），
    异常一律吞成 False、不外冒。"""
    try:
        return link.resolve() == src.resolve()
    except (OSError, RuntimeError):
        return False

def register_skills(vault_root: Path, dev: DeviceProfile, w: Writer) -> list[str]:
    vault_root = Path(vault_root)
    shared = vault_root / SHARED / "skills"
    skills = sorted((d for d in shared.iterdir() if d.is_dir()), key=lambda p: p.name) \
        if shared.is_dir() else []

    # ── 只读预检：全过才写，任何冲突立即中止（一个字节不动）──
    to_link: list[tuple[Path, Path]] = []   # (src, link) 待建
    ensured: list[str] = []                 # 现在已就位（待建 + 已就位）
    conflicts: list[str] = []
    for target_dir in skill_targets(dev):
        for src in skills:
            link = target_dir / src.name
            label = f"{target_dir}{os.sep}{src.name}"
            if not os.path.lexists(link):
                to_link.append((src, link)); ensured.append(label)
            elif _points_at(link, src):
                ensured.append(label)                       # 已就位，no-op
            else:
                conflicts.append(label)                     # 用户的/指别处的，不碰
    if conflicts:
        raise RegisterConflict(
            "以下位置已被非 hub 管理的同名项占用，register 不覆盖、未写任何链接。"
            "请先移开或改名：\n  " + "\n  ".join(conflicts))

    for src, link in to_link:
        w.make_dir_link(src, link)
    return ensured
```

- [ ] **Step 4：运行，确认通过**

Run: `py -3 -m pytest tests/hub/test_register.py -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add hub/register.py tests/hub/test_register.py
git commit -m "feat(hub): add register_skills — link shared skills into tool dirs"
```

---

## Task 4：A `collect_skills` 加"realpath 落进 shared 就跳过"

**Files:**
- Modify: `hub/collect/skills.py`
- Modify: `hub/collect/__init__.py:59-84`（`run_all` 两处 `collect_skills` 调用传入金库 `shared` 目录）
- Test: `tests/hub/test_collect_skills.py`（新增用例）

**Interfaces:**
- Changed: `collect_skills(src, dest, w, skip_under: Path | None = None) -> list[str]` —— 新增可选参数 `skip_under`；遍历 `src` 时，若某 skill 目录 `is_under(dir, skip_under)`（realpath 落进它）则**跳过**。`skip_under=None` 时对成功路径行为与旧版一致（向后兼容既有测试）。
- **关键结构改动（修"先删后验"）**：把 `rmtree(dest)` 从循环**之前**挪到**只读分类全部成功之后**。原实现先铲掉本机备份、再逐个解析新链接——一旦后面遇到坏链/权限错，备份已经没了（这正是 A 阶段修过的毁灭形状）。改为：**先只读扫描（skip 判定 + 解析/循环防御 + `check_source` + `is_git_repo` 决策），任何一步失败都在动 dest 之前抛错、备份一个字节不变**；全过才 `rmtree` + 写。
- New: `class SkillScanError(RuntimeError)` —— 源含链接环/坏链、解析不动时抛（分类阶段，早于任何写）。
- `run_all` 两处调用改为传 `skip_under=vault_root / SHARED / "skills"`。

- [ ] **Step 1：写失败测试**（新增到 `tests/hub/test_collect_skills.py`）

```python
# 追加到 tests/hub/test_collect_skills.py
import pytest
from hub.fslink import make_dir_link
from hub.collect.skills import SkillScanError
from hub.guard import SecretPathError
from hub.model import SHARED

def test_skips_skills_that_are_links_into_shared(tmp_path):
    """register 把 shared 的 skill 链进了 ~/.claude/skills；collect 不该把它当本机产物再备份。"""
    vault = tmp_path / "vault"
    shared_skill = vault / SHARED / "skills" / "shared_one"
    shared_skill.mkdir(parents=True)
    (shared_skill / "SKILL.md").write_text("# shared\n", encoding="utf-8")

    src = tmp_path / "home" / "skills"
    _skill(src, "local_one")                                  # 本机独有：要备份
    make_dir_link(shared_skill, src / "shared_one")          # 活链进来的：要跳过

    dest = tmp_path / "vault" / "box1" / "claude" / "skills"
    got = collect_skills(src, dest, Writer(), skip_under=vault / SHARED / "skills")
    assert got == ["local_one"]                               # 只备份本机独有
    assert (dest / "local_one").exists()
    assert not (dest / "shared_one").exists()                 # 活链的没被镜像

def test_skip_under_none_keeps_old_behavior(tmp_path):
    src = tmp_path / "skills"
    _skill(src, "alpha")
    got = collect_skills(src, tmp_path / "v", Writer(), skip_under=None)
    assert got == ["alpha"]

def test_scan_failure_leaves_old_backup_untouched(tmp_path):
    """分类阶段出错（这里用一个命中密钥闸的 skill 目录）时，旧备份一个字节不变——
    证明 rmtree 发生在只读扫描全过之后，不再"先删后验"。"""
    src = tmp_path / "skills"
    _skill(src, "alpha")
    (src / ".env").mkdir()                                    # check_source 会拒它 → 扫描阶段抛错
    dest = tmp_path / "vault" / "box1" / "claude" / "skills"
    _skill(dest, "old_backup")                               # 预置的旧备份
    before = (dest / "old_backup" / "SKILL.md").read_bytes()
    with pytest.raises(SecretPathError):
        collect_skills(src, dest, Writer())
    assert (dest / "old_backup" / "SKILL.md").read_bytes() == before   # 没被铲

def test_scan_raises_on_broken_link_and_keeps_backup(tmp_path):
    """源里有坏链（junction 指向已删目标）——不被 is_dir() 静默吞掉，而是抛
    SkillScanError，且发生在 rmtree 之前，旧备份一个字节不变。"""
    import shutil
    src = tmp_path / "skills"
    _skill(src, "alpha")
    target = tmp_path / "gone"; target.mkdir()
    make_dir_link(target, src / "broken")                    # src/broken → target
    shutil.rmtree(target)                                    # 目标删掉：src/broken 成坏链
    dest = tmp_path / "vault" / "box1" / "claude" / "skills"
    _skill(dest, "old_backup")
    before = (dest / "old_backup" / "SKILL.md").read_bytes()
    with pytest.raises(SkillScanError):
        collect_skills(src, dest, Writer())
    assert (dest / "old_backup" / "SKILL.md").read_bytes() == before   # 没被铲
```

- [ ] **Step 2：运行，确认新用例失败**

Run: `py -3 -m pytest tests/hub/test_collect_skills.py -v`
Expected: FAIL —— `test_skips_skills_that_are_links_into_shared` 报 `TypeError: collect_skills() got an unexpected keyword argument 'skip_under'`

- [ ] **Step 3：改实现**

在 `hub/collect/skills.py` 顶部改导入并定义异常。把原有的 `from hub.guard import check_source` 改为带上 `SecretPathError`，并加 `is_under` 导入：

```python
from hub.guard import check_source, SecretPathError   # 补 SecretPathError
from hub.fslink import is_under                        # 新增导入

class SkillScanError(RuntimeError):
    """skill 源扫描阶段的失败（链接环/坏链等），发生在动 dest 之前。"""
```

把整个 `collect_skills` 函数体替换为（**先枚举全部入口做统一只读预检，全过才 rmtree + 写**）：

```python
def collect_skills(src: Path | None, dest: Path, w: Writer,
                   skip_under: Path | None = None) -> list[str]:
    if src is None:
        return []
    src, dest = Path(src), Path(dest)
    check_source(src)
    require_source(src, "[sources.<工具>] skills")

    # ── 只读分类：枚举**全部**入口，逐个走统一预检（skip / resolve / is_dir /
    #    check_source）。坏链/链接环不再被 is_dir()==False 静默吞掉、悄悄漏备份——
    #    它是异常，转成 SkillScanError 停下来报；任何解析异常都在动 dest 之前抛。
    #    （"配坏读成本机为空 / 先删后验"是 A 阶段的毁灭形状，这里堵死。）──
    plan: list[tuple[str, Path, bool]] = []            # (name, dir, is_repo)
    for d in sorted(src.iterdir(), key=lambda p: p.name):
        try:
            if skip_under is not None and is_under(d, skip_under):
                continue                               # 活链进来的共享 skill，不重复备份
            d.resolve(strict=True)                     # 坏链/环 → OSError（下面转 SkillScanError）
            if not d.is_dir():
                continue                               # 解析成功但不是目录（普通文件）→ 跳过
            check_source(d)                            # 硬闸：每个 skill 目录
        except SecretPathError:
            raise                                      # 密钥闸原样抛（它就是要拒）
        except (OSError, RuntimeError) as e:
            raise SkillScanError(
                f"skill 源无法解析（疑似坏链/链接环）: {d} —— {e}") from e
        plan.append((d.name, d, is_git_repo(d)))

    # 分类全过，才清空并重写。
    w.rmtree(dest)                                     # 全量重写:本机删掉的 skill，金库也不该留
    for name, d, repo in plan:
        if repo:
            snapshot_repo(d, dest / name, w)
        else:
            w.copy_tree(d, dest / name)
    if not plan:
        # 源里一把 skill 都没有:rmtree 把 dest 铲了，补回 .gitkeep 免得金库骨架破洞。
        w.write_text(dest / ".gitkeep", "")
    return [name for name, _, _ in plan]
```

再改 `hub/collect/__init__.py` 的两处调用（Claude 与 Codex）：

```python
        rep.skills["claude"] = collect_skills(
            Path(cl.skills) if cl.skills else None, home / "claude" / "skills", w,
            skip_under=vault_root / SHARED / "skills")
```
```python
        rep.skills["codex"] = collect_skills(
            Path(cx.skills) if cx.skills else None, home / "codex" / "skills", w,
            skip_under=vault_root / SHARED / "skills")
```
并在 `hub/collect/__init__.py` 顶部导入补上 `SHARED`：

```python
from hub.model import DeviceProfile, SHARED
```

- [ ] **Step 4：运行，确认全绿（新用例 + 既有用例都过）**

Run: `py -3 -m pytest tests/hub/test_collect_skills.py tests/hub/test_collect_init.py -v`
Expected: PASS（既有用例因 `skip_under` 默认 None 不受影响）

- [ ] **Step 5：提交**

```bash
git add hub/collect/skills.py hub/collect/__init__.py tests/hub/test_collect_skills.py
git commit -m "feat(hub): collect_skills skips skills linked into shared (no re-absorb loop)"
```

---

## Task 5：`hub status` 增补 skill 链接健康报告

**Files:**
- Create: `hub/status_report.py`
- Test: `tests/hub/test_status_report.py`

**Interfaces:**
- Consumes: `hub.register.skill_targets`；`hub.model.DeviceProfile`。
- Produces:
  - `link_status(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, str]]` —— **只检查 `shared/skills/` 里的期望项**（没 manifest 就无法安全判定"某额外目录以前归不归 hub 管"，故本机自带的本地 skill **一律不报**）。对每个目标目录 × 每把 shared skill，状态 ∈ `{"ok", "missing", "conflict"}`：
    - `missing`：目标处不存在该链接。
    - `ok`：目标处存在且**精确解析到**对应 `shared/skills/<n>`（`link.resolve() == src.resolve()`，不是宽松的"落在 shared 下"）。
    - `conflict`：目标处同名存在，但指向别处 / 是用户自己的真目录 / 解析失败。
  - 只读，不写盘。**不再有 `stale`**（无法在无清单下安全判定残链；清理是以后 `refresh --prune` 的事）。

- [ ] **Step 1：写失败测试**

```python
# tests/hub/test_status_report.py
from pathlib import Path
from hub.status_report import link_status
from hub.fslink import make_dir_link
from hub.model import DeviceProfile

def _dev(tmp_path):
    return DeviceProfile(host="box1", classes=[], projects=[],
                         paths={"CLAUDE_HOME": str(tmp_path / ".claude"),
                                "AGENTS_HOME": str(tmp_path / ".agents")}, sources={})

def test_reports_ok_when_linked(tmp_path):
    vault = tmp_path / "vault"
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    dev = _dev(tmp_path)
    make_dir_link(s, tmp_path / ".claude" / "skills" / "alpha")
    make_dir_link(s, tmp_path / ".agents" / "skills" / "alpha")
    rows = link_status(vault, dev)
    assert ("ok", str(tmp_path / ".claude" / "skills" / "alpha")) in rows
    assert all(st == "ok" for st, _ in rows)

def test_reports_missing_when_not_linked(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills" / "alpha").mkdir(parents=True)
    rows = link_status(vault, _dev(tmp_path))
    assert ("missing", str(tmp_path / ".claude" / "skills" / "alpha")) in rows

def test_reports_conflict_when_points_elsewhere(tmp_path):
    vault = tmp_path / "vault"
    (vault / "shared" / "skills" / "alpha").mkdir(parents=True)
    other = tmp_path / "other"; other.mkdir()
    make_dir_link(other, tmp_path / ".claude" / "skills" / "alpha")   # 同名但指别处
    rows = link_status(vault, _dev(tmp_path))
    assert ("conflict", str(tmp_path / ".claude" / "skills" / "alpha")) in rows

def test_local_only_skill_is_not_reported(tmp_path):
    """用户自己的本地 skill（shared 里没有）——绝不能进结果（既非 conflict 也非任何状态）。"""
    vault = tmp_path / "vault"
    (vault / "shared" / "skills").mkdir(parents=True)                 # shared 空
    mine = tmp_path / ".claude" / "skills" / "my_local"; mine.mkdir(parents=True)
    rows = link_status(vault, _dev(tmp_path))
    assert all("my_local" not in label for _, label in rows)         # 压根不出现
```

- [ ] **Step 2：运行，确认失败**

Run: `py -3 -m pytest tests/hub/test_status_report.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'hub.status_report'`

- [ ] **Step 3：写最小实现**

```python
# hub/status_report.py
"""C 的状态检查（只读）。Plan 1 只报 skill 链接健康。

只检查 shared/skills/ 里的**期望项**——没 manifest 就无法安全判定某额外目录
以前归不归 hub 管，故本机自带的本地 skill 一律不报，免得把用户的东西冤成残留。
"""
import os
from pathlib import Path
from hub.model import SHARED, DeviceProfile
from hub.register import skill_targets

def _points_at(link: Path, src: Path) -> bool:
    try:
        return link.resolve() == src.resolve()
    except (OSError, RuntimeError):                       # 解析异常 → 落成 conflict，不外冒
        return False

def link_status(vault_root: Path, dev: DeviceProfile) -> list[tuple[str, str]]:
    vault_root = Path(vault_root)
    shared = vault_root / SHARED / "skills"
    shared_skills = sorted((d for d in shared.iterdir() if d.is_dir()),
                           key=lambda p: p.name) if shared.is_dir() else []
    rows: list[tuple[str, str]] = []
    for target_dir in skill_targets(dev):
        for src in shared_skills:
            link = target_dir / src.name
            label = str(link)
            if not os.path.lexists(link):
                rows.append(("missing", label))
            elif _points_at(link, src):
                rows.append(("ok", label))
            else:
                rows.append(("conflict", label))     # 指别处 / 用户真目录 / 解析失败
    return rows
```

- [ ] **Step 4：运行，确认通过**

Run: `py -3 -m pytest tests/hub/test_status_report.py -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add hub/status_report.py tests/hub/test_status_report.py
git commit -m "feat(hub): add link_status — report skill-link health (ok/missing/conflict)"
```

---

## Task 6：CLI 接线 —— `hub register` / `hub promote` / `hub status` 扩展

**Files:**
- Modify: `hub/cli.py`（新增 `register`、`promote` 子命令；把 skill 链接状态并进 `status`）
- Test: `tests/hub/test_cli.py`（新增用例）

**Interfaces:**
- Consumes: `hub.register.register_skills, RegisterConflict`；`hub.promote.promote_skill, PromoteConflict`；`hub.status_report.link_status`；既有 `load_device` / `current_host` / `Writer` / `GitBackend`。
- Produces（CLI 行为）：
  - `hub register --vault <v> [--host <h>] [--dry-run]` —— 调 `register_skills`，打印就位链接数；`RegisterConflict` 时打印并返回 1（未写任何链接）。
  - `hub promote --vault <v> [--host <h>] --tool <claude|codex> --name <skill 名> [--dry-run]` —— 由 host/tool/name 推导备份区源（**不收任意绝对路径**），调 `promote_skill`；`PromoteConflict`/`FileNotFoundError`/`ValueError` 时打印并返回 1。
  - `hub status --vault <v> [--host <h>]` —— 在原 git porcelain 之后，追加打印 `link_status` 各行。

- [ ] **Step 1：写失败测试**

```python
# 追加到 tests/hub/test_cli.py
from hub.cli import main as cli_main

def _mini_vault(tmp_path):
    from hub.scaffold_vault import scaffold
    scaffold(tmp_path, "box1", Writer())
    dev = tmp_path / "box1" / "device.toml"
    dev.write_text(
        f'class=["work"]\nprojects=[]\n[paths]\n'
        f'CLAUDE_HOME="{(tmp_path / "h" / ".claude").as_posix()}"\n'
        f'AGENTS_HOME="{(tmp_path / "h" / ".agents").as_posix()}"\n',
        encoding="utf-8")
    return tmp_path

def test_cli_register_builds_links(tmp_path, capsys):
    vault = _mini_vault(tmp_path)
    s = vault / "shared" / "skills" / "alpha"; s.mkdir(parents=True)
    (s / "SKILL.md").write_text("# a\n", encoding="utf-8")
    rc = cli_main(["register", "--vault", str(vault), "--host", "box1"])
    assert rc == 0
    assert (tmp_path / "h" / ".claude" / "skills" / "alpha" / "SKILL.md").exists()

def test_cli_promote_conflict_returns_1(tmp_path, capsys):
    vault = _mini_vault(tmp_path)
    existing = vault / "shared" / "skills" / "alpha"; existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("# 共享区版本\n", encoding="utf-8")
    src = vault / "box1" / "claude" / "skills" / "alpha"; src.mkdir(parents=True)
    (src / "SKILL.md").write_text("# 不同版本\n", encoding="utf-8")
    rc = cli_main(["promote", "--vault", str(vault), "--host", "box1",
                   "--tool", "claude", "--name", "alpha"])
    assert rc == 1
    assert "alpha" in capsys.readouterr().out
```

- [ ] **Step 2：运行，确认失败**

Run: `py -3 -m pytest tests/hub/test_cli.py -v -k "register or promote"`
Expected: FAIL —— argparse 报无效选择 `register` / `invalid choice`

- [ ] **Step 3：改实现**（在 `hub/cli.py`）

顶部导入补：

```python
from hub.register import register_skills, RegisterConflict
from hub.promote import promote_skill, PromoteConflict
from hub.status_report import link_status
```

新增两个命令处理函数：

```python
def _cmd_register(args) -> int:
    vault_root = Path(args.vault)
    dev = load_device(vault_root, args.host or current_host())
    try:
        done = register_skills(vault_root, dev, Writer(dry_run=args.dry_run))
    except RegisterConflict as e:
        print(e)
        return 1
    verb = "预计就位" if args.dry_run else "已就位"
    print(f"{verb} {len(done)} 个 skill 链接")
    for d in done:
        print("  ", d)
    return 0

def _cmd_promote(args) -> int:
    vault_root = Path(args.vault)
    host = args.host or current_host()
    load_device(vault_root, host)                          # 校验 host 存在
    try:
        dest = promote_skill(vault_root, host, args.tool, args.name,
                             Writer(dry_run=args.dry_run))
    except (PromoteConflict, FileNotFoundError, ValueError) as e:
        print(e)
        return 1
    print(f"{'预计提升' if args.dry_run else '已提升'} → {dest}")
    return 0
```

把 `_cmd_status` 改为在 git 状态后追加链接状态：

```python
def _cmd_status(args) -> int:
    vault_root = Path(args.vault)
    print(GitBackend(vault_root).status(), end="")
    try:
        dev = load_device(vault_root, args.host or current_host())
    except FileNotFoundError:
        return 0                       # 本机没有 device.toml：只报 git 状态，不回归旧行为
    rows = link_status(vault_root, dev)
    if rows:
        print("skill 链接:")
        for state, label in rows:
            print(f"  [{state}] {label}")
    return 0
```

在 `build_parser()` 里注册子命令（`register`/`promote` 复用 `--dry-run`，`promote` 加 `--tool`/`--name`）：

```python
    reg = sub.add_parser("register", parents=[common])
    reg.add_argument("--dry-run", action="store_true")
    reg.set_defaults(func=_cmd_register)

    pro = sub.add_parser("promote", parents=[common])
    pro.add_argument("--tool", required=True, choices=["claude", "codex"],
                     help="备份区里哪个工具的 skill")
    pro.add_argument("--name", required=True, help="要提升的 skill 名（单个目录名，不含路径）")
    pro.add_argument("--dry-run", action="store_true")
    pro.set_defaults(func=_cmd_promote)
```
（`status` 子命令已存在，只是 `_cmd_status` 函数体换成上面的版本；注意它现在要读 `--host`，`common` 已带 `--host`。）

- [ ] **Step 4：运行，确认通过（含既有 CLI 测试不回归）**

Run: `py -3 -m pytest tests/hub/test_cli.py -v`
Expected: PASS

- [ ] **Step 5：提交**

```bash
git add hub/cli.py tests/hub/test_cli.py
git commit -m "feat(hub): wire register/promote CLI + skill-link status"
```

---

## Task 7：全量回归 + README 补一段

**Files:**
- Modify: `hub/README.md`（命令一览补 `register`/`promote`；说明 Plan 1 只做 skill）

**Interfaces:** 无新接口，收尾。

- [ ] **Step 1：跑全套测试**

Run: `py -3 -m pytest tests/hub -q`
Expected: PASS（既有 218 + 本计划新增，全绿）

- [ ] **Step 2：在 `hub/README.md` 的"命令一览"表补两行**

```markdown
| `register` | 把 `shared/skills/` 逐个活链进各工具（Claude `~/.claude/skills`、Codex/opencode `~/.agents/skills`）；改一处三家实时生效 | 否 |
| `promote`  | 把备份区选定 skill 复制进 `shared/`（同名不同内容即停）；`--tool <claude\|codex> --name <skill 名>` | 否 |
```
并在 README 顶部加一句：`register`/`promote`/`status(skill 链接)` 属于 C 阶段 Plan 1（只做 skill；memory 视图与 plugin 见后续计划）。

- [ ] **Step 3：提交**

```bash
git add hub/README.md
git commit -m "docs(hub): document register/promote (C-phase Plan 1, skill loop)"
```

---

## 后续计划（不在本计划内，各自独立成 plan）

- **Plan 2 · memory 视图下行**：`promote_memory`（frontmatter 校验 + scope）、生成 `~/.hub/views/<tool>/MEMORY.md`（shared-only + scope 过滤）、`register` 维护 CLAUDE.md/AGENTS.md 的 `hub:begin/end` 受管块 + opencode `instructions[]`、随 hub 发的 `hub-memory` skill、`hub refresh` 重算视图。
- **Plan 3 · plugin 注册/刷新**：换机 clone/恢复 plugins-dev、注册市场、写 `enabledPlugins`/`codex plugin add`、`hub refresh` 缓存重装（Codex cachebuster）。
- **降出 v1**：跨平台 hook 注册、opencode 插件适配（能力墙，NEEDS 次级）。
