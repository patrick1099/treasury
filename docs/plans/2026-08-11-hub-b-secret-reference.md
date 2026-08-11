# Plan B —— hub 引用式密钥实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或
> superpowers:executing-plans 逐任务实现。步骤用 `- [ ]` 复选框跟踪。

**Goal:** 密钥本体只存 `~/.claude/secrets/` 一处且格式统一；别处（记忆、skill、配置、对话）只出现
`hub://secrets/<item>/<field>` 引用；执行时把真值注进子进程环境；Claude Code 原生工具对
`secrets/` 的读取受 PreToolUse guardrail 约束，并留一个**人工授权的开口**。

**Architecture:** 三层，边界就是将来换 age 的换装线（spec §5.6）：

```text
secrets backend :  hub:// 引用 → 真值 dict      ← 唯一读明文的一层；将来换 age 只动这里
runner          :  固定 argv + 局部 env → 子进程 → 遮罩输出
policy          :  human `run`/`render` / AI `exec <profile>` / hook 判定 / unlock 令牌
```

**Tech Stack:** Python 3（**stdlib only，无新第三方、无 Node**——见 spec §5.6 撤回 dotenvx 的理由）；
`subprocess`；pytest。**权威设计：** `docs/specs/2026-08-10-hub-secret-reference-design.md` **v2.2**。

---

## Global Constraints

- **威胁模型（spec §2.1）**：防的是**会犯错的**AI，不是蓄意绕行的 AI，也不是提示注入。
  任何一处写「AI 拿不到明文」都是错的；准确表述是「Claude Code 原生工具的读取受 guardrail 约束」。
  **验收标题里不许出现跨工具的「AI 读不到明文」**（spec §6.6）。
- **`secrets_backend` 是唯一读明文的模块**，它**必须绕开 `guard`**（`guard` 的黑名单正是
  `secrets`，走 `read_source_text()` 会把自己挡死）。除它以外，任何模块读本机源文件仍走
  `guard.read_source_text()`。这条不对称是有意的，实现时别"顺手统一"。
- **`DENIED_NAMES` 不加任何豁免参数**（spec §6.3）。让 `guard` 认识 `secrets_backend` 的
  任何写法都是把不变量从"结构上做不到"退化成"取决于调用方传了什么"。
- **架构边界 ≠ 能力边界**：`hub.collect.*` 不 import `secrets_backend` 由 AST 测试保证（T11），
  它防的是**误耦合**，不是防 AI。别在注释里把它写成安全边界。
- **真值绝不进 argv**；**全程不产生任何明文临时文件**（不是"用完删"，是结构上不产生）；
  **不修改父进程的全局 `os.environ`**（spec §5.5）。
- **遮罩覆盖四条路径**：成功、非零退出、超时、解码失败。只测成功路径等于没测。
  遮罩**先在 bytes 上做**再解码。**遮罩不是安全边界**（只做精确值匹配）。
- **hook 的三档与 fail-open 坑（spec §6.1）**：JSON 只在 **exit 0** 时被解析；**exit 2 阻断**；
  **exit 1 与其它非零码都是非阻断错误，工具照常执行**。故 hook **顶层必须捕获一切异常并转 exit 2**。
- **hook 是判定者不是被判定者**：它读 `.unlock` 走**裸 `Path.read_text()`**，不走
  `guard.read_source_text()`（spec §6.7.3.4）。
- **hook 每次工具调用都跑**，只许 import `hub.guard`（纯 stdlib 依赖）；**不许 import 其余 hub 模块**，
  更不许 import `secrets_backend`。
- **开口的承重闸在进程里，不在 hook 的命令串匹配上**（spec §6.7.3.1）：`hub` 不在 PATH 上，
  真实写法是 `py -3 -m hub.cli secrets ...`，matcher 枚举不完。
  **禁止用 `sys.stdin.isatty()` 判"是不是人"——实测在 AI 工具下它是 `True`。**
- **测试隔离**：`tmp_path` + `HUB_HOME`；`tests/hub/conftest.py` 的 autouse `_sandbox_home` 已把
  `Path.home()` 重定向进 tmp，**任何测试都不许碰真实的 `~/.claude/secrets/`**。
  真实密钥只在 T3 / T12 两个**人工闸**里出现。
- **Esafenet DRM**：本仓 `.py` 被加密。读用 Read/Grep 工具或 `cmd /c type`，**写必须走 python**
  （`Path.write_text` / `write_bytes`）；**禁止** PowerShell 的 `Set-Content`/`Copy-Item`，
  **也禁止子 agent 自己的 Write/Edit 工具**。非白名单进程写入不是失败，是**写进去且不加密**，
  exit 0、测试全绿、`git diff` 干净，零痕迹。派 opencode 时**必须把这三条写进 prompt**。
- **提交身份** `patrick1099`（本仓 `git config --local` 已定，commit 无需 `-c`）；
  footer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`；Windows 用 `py -3`。

## 前置：本机事实（2026-08-11 实测，不要凭想象重推一遍）

| 事实 | 值 | 影响 |
|---|---|---|
| `hub` 在 PATH 上？ | **不在**。真实写法 `py -3 -m hub.cli <cmd>` | hook 的命令串匹配注定不完备 → T9/T8 分层 |
| `sys.stdin.isatty()` | AI 工具下 **True** | **不能**当"是不是人"的判据 |
| `sys.stdout.isatty()` | AI 工具下 False，真终端 True | 可当便宜的前置判据 |
| `sys.stdin.readline()` | AI 工具下立刻 `''` | 挡不住 `echo X \| ...` |
| 读 `CONIN$` | AI 工具下**永久阻塞** | **承重闸**（T8） |
| ossutil | `…\Programs\bin\ossutil.exe`，原生 exe | 启动链一段 |
| vsce | npm shim，实体 `node.exe …\node_modules\@vscode\vsce\vsce` | 启动链两段（T5） |
| mineru-open-api | 同上，npm shim | 启动链两段 |
| `~/.claude/secrets/` | 3 个文件，3 种格式，**明文** | T1 格式 / T3 迁移 |
| `~/.hub/config.toml` | `vault` / `host` / `hub_root` 三键已在 | T5 的 profile 放同目录 |

## 文件结构

```
hub/secrets_store.py     (新) SecretsError + 严格 item/field 解析 + `## fields` 段解析 + iter_items
hub/secrets_backend.py   (新) 唯一读明文层：resolve_ref / resolve_env —— 绕开 guard，将来换 age 只动这里
hub/secrets_profile.py   (新) Profile + load_profiles + 启动链校验 + 尾参语法校验
hub/secrets_run.py       (新) redact_bytes + run_profile（局部 env、四条路径遮罩、close_fds）
hub/secrets_unlock.py    (新) 令牌：issue_token(CONIN$ 确认) / read_token / token_valid
hub/secrets_cli.py       (新) secrets 子命令：exec / run / render / unlock（run/render 进程内自守）
hub/cli.py               (改) 挂 `secrets` 子命令
hub/hooks/__init__.py    (新) 空
hub/hooks/secrets_guard.py (新) PreToolUse hook：路径判定 + 命令串匹配 + 三档 + 顶层 exit 2
tests/hub/test_secrets_*.py            (新)
tests/hub/test_arch_secrets_isolation.py (新) AST 架构测试
```

---

## Task 1: 密钥库解析器（`hub/secrets_store.py`）

**派谁：** opencode（格式解析，判断成分低，测试契约明确）。**派发时必须带上 Esafenet 三条。**

**Files:** New `hub/secrets_store.py`；Test `tests/hub/test_secrets_store.py`。

**Interfaces (Produces):** `SecretsError(RuntimeError)`；`item_path(root, item) -> Path`（严格解析，
违规抛 `SecretsError`）；`parse_fields(text) -> dict[str, str]`；`load_item(root, item) -> dict[str,str]`；
`iter_items(root) -> list[str]`（**排除点开头文件**）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_store.py 新建
import pytest
from hub.secrets_store import SecretsError, item_path, parse_fields, load_item, iter_items

DOC = """---
name: demo
description: d
metadata:
  type: secret
---

## fields

accessKeyId = LTAIxxxxxxxxxxxx
accessKeySecret = aB3-dE_f.gH

## notes

下游副本：~/.mineru/config.yaml
accessKeyId = 这一行在 notes 段里，不许被解析出来
"""

def _mk(root, name, text=DOC):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(text, encoding="utf-8")

def test_fields_section_only(tmp_path):
    assert parse_fields(DOC) == {
        "accessKeyId": "LTAIxxxxxxxxxxxx",
        "accessKeySecret": "aB3-dE_f.gH",
    }                                    # notes 段里那行不许混进来

def test_value_kept_verbatim(tmp_path):
    jwt = "a." + "x" * 380 + "-_"        # 402 位量级，含 . - _
    text = DOC.replace("LTAIxxxxxxxxxxxx", jwt)
    assert parse_fields(text)["accessKeyId"] == jwt   # 不剥引号、不 strip 内部、不转义

def test_duplicate_key_refused(tmp_path):
    text = DOC.replace("accessKeySecret = aB3-dE_f.gH", "accessKeyId = second")
    with pytest.raises(SecretsError):
        parse_fields(text)

def test_missing_fields_section_refused(tmp_path):
    with pytest.raises(SecretsError):
        parse_fields("---\nname: x\n---\n\n## notes\n\nnothing\n")

@pytest.mark.parametrize("bad", [
    "..", ".", "a/b", "a\\b", "/abs", "C:/abs", ".hidden", "", "a\x00b",
])
def test_item_name_strictly_refused(tmp_path, bad):
    with pytest.raises(SecretsError):
        item_path(tmp_path, bad)

def test_item_must_be_regular_file(tmp_path):
    (tmp_path / "adir.md").mkdir()
    with pytest.raises(SecretsError):
        item_path(tmp_path, "adir")

def test_load_item_ok(tmp_path):
    _mk(tmp_path, "demo")
    assert load_item(tmp_path, "demo")["accessKeyId"] == "LTAIxxxxxxxxxxxx"

def test_iter_items_excludes_dotfiles(tmp_path):
    _mk(tmp_path, "demo")
    (tmp_path / ".unlock").write_text("whatever", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("# idx\n", encoding="utf-8")
    assert iter_items(tmp_path) == ["INDEX", "demo"]   # .unlock 绝不是一条密钥
```

- [ ] **Step 2: 运行确认失败** — `py -3 -m pytest tests/hub/test_secrets_store.py -q`，预期 `ImportError`。

- [ ] **Step 3: 实现**

```python
# hub/secrets_store.py 新建
"""密钥库的严格解析器。

**只解析，不读明文之外的判断**：本模块会读到真值，但它不决定谁能拿——那是
secrets_backend 与 policy 层的事。

解析必须 fail-closed（spec §3.1）：一个能接受任意路径的解析器，等于给整条
不变量开了一个参数化的后门。
"""
import os
import re
from pathlib import Path

from hub.frontmatter import parse_frontmatter, FrontmatterError


class SecretsError(RuntimeError):
    pass


# item 名：不许点开头（`.unlock` 不是密钥）、不许任何分隔符与 ..
_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def check_item_name(item: str) -> str:
    """item 名的**唯一**把关处。

    独立成函数是因为不止一个调用方：`item_path`（要落到文件）和
    `secrets_backend.parse_ref`（只解析引用、还不碰文件系统）都得用同一套判据。
    复制一份正则过去就等于开了第二条口径，早晚分岔。
    """
    if not isinstance(item, str) or not _ITEM_RE.match(item) or ".." in item:
        raise SecretsError(f"非法的 item 名 {item!r}：只接受 secrets 根下的直接文件名")
    return item


def item_path(root: Path, item: str) -> Path:
    """把 item 名解析成 secrets 根目录下的**直接普通文件**，别的一律拒。"""
    check_item_name(item)
    root = Path(root)
    p = root / f"{item}.md"
    if p.is_symlink():
        raise SecretsError(f"{p} 是符号链接，拒绝")
    if not p.is_file():
        raise SecretsError(f"{p} 不是普通文件")
    # realpath 双查：挡 junction / reparse point，以及 root 自身被换掉的情况
    if os.path.dirname(os.path.realpath(p)) != os.path.realpath(root):
        raise SecretsError(f"{p} 解析后逃出了 {root}")
    return p


def parse_fields(text: str) -> dict[str, str]:
    """只认 `## fields` 段，一行一个 `key = value`。段外全是给人看的。"""
    try:
        _, body = parse_frontmatter(text)
    except FrontmatterError as e:
        raise SecretsError(f"frontmatter 解析失败：{e}") from e

    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## fields":
            start = i + 1
            break
    if start is None:
        raise SecretsError("缺少 `## fields` 段")

    out: dict[str, str] = {}
    for ln in lines[start:]:
        if ln.startswith("## "):          # 下一段开始，fields 到此为止
            break
        s = ln.strip()
        if not s:
            continue
        if "=" not in s:
            raise SecretsError(f"`## fields` 段里无法解析的行：{ln!r}")
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip()                  # 只剥两端空白，值内部一字不动
        if not key or "\x00" in key or "\x00" in val:
            raise SecretsError(f"非法的字段：{ln!r}")
        if key in out:
            raise SecretsError(f"重复的字段名 {key!r}")
        out[key] = val
    if not out:
        raise SecretsError("`## fields` 段是空的")
    return out


def load_item(root: Path, item: str) -> dict[str, str]:
    # 裸 read_text：本模块是密钥库自己的解析器，走 guard 会把自己挡死（见 Global Constraints）
    return parse_fields(item_path(root, item).read_text(encoding="utf-8"))


def iter_items(root: Path) -> list[str]:
    """列出可引用的 item。**点开头的文件一律不是 item**（`.unlock` 靠这条被排除）。"""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        p.stem for p in root.iterdir()
        if p.is_file() and not p.is_symlink() and p.suffix == ".md" and not p.name.startswith(".")
    )
```

- [ ] **Step 4: 运行确认通过** — `py -3 -m pytest tests/hub/test_secrets_store.py -q` 全绿；
      再跑 `py -3 -m pytest tests/ -q` 确认零回归。
- [ ] **Step 5: 提交** — `feat(hub): 密钥库严格解析器——只认 ## fields 段，点开头文件不是密钥`

---

## Task 2: `hub://` 引用解析 + backend（`hub/secrets_backend.py`）

**派谁：** opencode。

**Files:** New `hub/secrets_backend.py`；Test `tests/hub/test_secrets_backend.py`。

**Interfaces (Produces):** `parse_ref(ref) -> tuple[str, str]`；`resolve_ref(root, ref) -> str`；
`resolve_env(root, mapping) -> dict[str, str]`；`secrets_root() -> Path`。

> **实施修正（2026-08-11）**：初稿的 `parse_ref` 注释写着「item 的合法性交给
> `item_path` 统一把关」，于是 `hub://secrets/.unlock/token` 在 `parse_ref` 这一层不抛，
> 与自己的 `test_parse_refuses` 用例直接掐架。**修法不是在 `parse_ref` 里复制一份正则**
> ——那就变成两条口径了——而是把判据提成 `secrets_store.check_item_name()`，
> `item_path` 与 `parse_ref` 共用（T1 的代码块已同步）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_backend.py 新建
import pytest
from hub.secrets_store import SecretsError
from hub.secrets_backend import parse_ref, resolve_ref, resolve_env

DOC = """---
name: demo
description: d
---

## fields

k1 = v1
k2 = v2
"""

@pytest.fixture
def root(tmp_path):
    (tmp_path / "demo.md").write_text(DOC, encoding="utf-8")
    return tmp_path

def test_parse_ok():
    assert parse_ref("hub://secrets/aliyun-oss-picgo/accessKeyId") == (
        "aliyun-oss-picgo", "accessKeyId")

@pytest.mark.parametrize("bad", [
    "hub://secrets/a", "hub://secrets/a/b/c", "hub://other/a/b",
    "secrets/a/b", "hub://secrets//b", "hub://secrets/../x/y",
    "hub://secrets/.unlock/token", "", "hub://secrets/a/",
])
def test_parse_refuses(bad):
    with pytest.raises(SecretsError):
        parse_ref(bad)

def test_resolve_ok(root):
    assert resolve_ref(root, "hub://secrets/demo/k1") == "v1"

def test_resolve_missing_field(root):
    with pytest.raises(SecretsError):
        resolve_ref(root, "hub://secrets/demo/nope")

def test_resolve_env(root):
    got = resolve_env(root, {"A": "hub://secrets/demo/k1", "B": "hub://secrets/demo/k2"})
    assert got == {"A": "v1", "B": "v2"}

def test_resolve_env_refuses_case_collision(root):
    # Windows 环境变量名大小写不敏感：A 与 a 同时声明是配置错误，必须炸
    with pytest.raises(SecretsError):
        resolve_env(root, {"A": "hub://secrets/demo/k1", "a": "hub://secrets/demo/k2"})

def test_resolve_env_refuses_bad_var_name(root):
    for bad in ("A=B", "A\x00B", ""):
        with pytest.raises(SecretsError):
            resolve_env(root, {bad: "hub://secrets/demo/k1"})

def test_error_never_contains_value(root):
    try:
        resolve_ref(root, "hub://secrets/demo/nope")
    except SecretsError as e:
        assert "v1" not in str(e) and "v2" not in str(e)
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# hub/secrets_backend.py 新建
"""引用 → 真值。**本仓唯一读密钥明文的一层。**

三件事必须写在最前面：

1. **本模块绕开 hub.guard，这是有意的。** guard 的黑名单第一项就是 `secrets`，
   走 read_source_text() 会把自己挡死。除本模块外，任何模块读本机源文件仍走 guard。
   **不要为了"统一"给 guard 加豁免参数**——那会让不变量退化成"取决于调用方传了什么"
   （spec §6.3）。
2. **hub.collect.* 永远不 import 本模块**，由 AST 测试（tests/hub/test_arch_secrets_isolation.py）
   保证。那是**架构边界**，防误耦合；它不是对抗 AI 的安全边界（spec §6.3）。
3. **将来要静态加密就只改这一层**（spec §5.6）：把 read → decrypt 换进来，
   runner 与 policy 拿到的仍是同一个 dict，外部契约不动。

错误信息里**永远不带真值**——§1.3 那次事故就是一个"只打印结构"的东西漏了一条分支。
"""
import os
import re
from pathlib import Path

from hub.secrets_store import SecretsError, check_item_name, load_item

_PREFIX = "hub://secrets/"
_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def secrets_root() -> Path:
    """密钥库位置。允许 HUB_SECRETS_ROOT 覆盖——**只为测试**，生产不设这个变量。"""
    return Path(os.environ.get("HUB_SECRETS_ROOT") or (Path.home() / ".claude" / "secrets"))


def parse_ref(ref: str) -> tuple[str, str]:
    """`hub://secrets/<item>/<field>` → (item, field)。严格，别的一律拒。"""
    if not isinstance(ref, str) or not ref.startswith(_PREFIX):
        raise SecretsError(f"不是一个 hub:// 引用：{ref!r}")
    rest = ref[len(_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SecretsError(f"引用形状必须是 hub://secrets/<item>/<field>：{ref!r}")
    item, field = parts
    # item 名走 secrets_store 那一处唯一判据（`.unlock` 这类点开头的在这里就被拒，
    # 不必等到 resolve_ref 去碰文件系统才发现）。
    check_item_name(item)
    if not _VAR_RE.match(field.replace("-", "_")):
        raise SecretsError(f"非法的字段名：{ref!r}")
    return item, field


def resolve_ref(root: Path, ref: str) -> str:
    item, field = parse_ref(ref)
    fields = load_item(root, item)          # item 名非法 / 不是普通文件 → 这里抛
    if field not in fields:
        raise SecretsError(f"{item} 里没有字段 {field!r}")
    return fields[field]


def resolve_env(root: Path, mapping: dict[str, str]) -> dict[str, str]:
    """env 变量名 → 引用 的映射，解析成 env 变量名 → 真值。

    Windows 的环境变量名**大小写不敏感**，所以同一份声明里 `A` 与 `a` 是冲突而不是两项——
    静默让后者覆盖前者会让注入结果取决于 dict 顺序。宁可炸。
    """
    out: dict[str, str] = {}
    seen: dict[str, str] = {}
    for name, ref in mapping.items():
        if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
            raise SecretsError(f"非法的环境变量名：{name!r}")
        low = name.lower()
        if low in seen:
            raise SecretsError(f"环境变量名大小写冲突：{seen[low]!r} 与 {name!r}")
        seen[low] = name
        val = resolve_ref(root, ref)
        if "\x00" in val:
            raise SecretsError(f"{name} 的值含 NUL，无法作为环境变量")
        out[name] = val
    return out
```

- [ ] **Step 4: 运行确认通过** + 全量回归。
- [ ] **Step 5: 提交** — `feat(hub): hub:// 引用解析与 backend——唯一读明文层，绕开 guard 是有意的`

---

## Task 3 🔴 人工闸：迁移 3 个真实密钥文件

**派谁：不派，也不由 AI 代劳读写。** 这一步碰的是真实明文。

**为什么是人工闸**：spec §4.3 明写「迁移脚本本身不打印任何值」，而 §1.3 那次事故正是一个
"只打印结构、不打印值"的脚本漏了一条分支造成的。**同一个失败形状不要再走一遍。**

- [ ] **Step 1: 交给用户的迁移说明**（AI 只提供这段文本，不代跑）

  把 `~/.claude/secrets/` 下这 3 个文件各自改成下面的形状。**只加 `## fields` 段，
  原有正文整段挪进 `## notes`，值一个字符都不要重打**（复制粘贴，别手敲）：

```markdown
---
name: aliyun-oss-picgo
description: 阿里云 OSS 图床 picgo-imgs1270
metadata:
  type: secret
  rotated: 2026-08-10
---

## fields

accessKeyId = <原值>
accessKeySecret = <原值>

## notes

（原来的说明、用途、bucket、endpoint 都挪到这里；**再补一行下游副本清单**）
下游副本：<例如 ~/.mineru/config.yaml、~/.config/opencode/opencode.json>
```

  三个文件分别是 `aliyun-oss-picgo.md`（表格 → fields）、`mineru-api.md`（裸行 JWT → fields，
  **注意别把前后那两行 ``` 一起粘进值里**）、`vscode-marketplace-vsce.md`（`## VSCE_PAT` 标题
  + 代码块 → fields）。

- [ ] **Step 2: 用户自己验证**（在**普通终端**里跑，不要让 AI 跑）

```
py -3 -c "from pathlib import Path; from hub.secrets_store import load_item, iter_items; r=Path.home()/'.claude'/'secrets'; print(iter_items(r)); [print(i, sorted(load_item(r,i))) for i in iter_items(r) if i!='INDEX']"
```

  它**只打印 item 名与字段名，不打印任何值**。三个文件的字段名都出来了就算通过。

- [ ] **Step 3: `INDEX.md` 补一句** —— 说明本库已改成 `## fields` 格式，引用写法是
      `hub://secrets/<item>/<field>`。
- [ ] **Step 4: 无提交**（`~/.claude/secrets/` 不在本仓里）。

> **给 AI 的边界**：这一步完成前不要往下走 T5/T12；这一步过程中**不要**为了"帮忙确认"
> 去读那三个文件。

---

## Task 4: profile 声明与启动链校验（`hub/secrets_profile.py`）

**派谁：** opencode。

**Files:** New `hub/secrets_profile.py`；Test `tests/hub/test_secrets_profile.py`。

**位置决定**：profile 放 `~/.hub/secrets-profiles.toml`（**运行态，不进金库**——与
`~/.hub/plugin-state.toml` 同一个理由：里面全是本机绝对路径）。

**格式**：

```toml
[profiles.ossutil]
argv = ["C:/Users/huawei/AppData/Local/Programs/bin/ossutil.exe"]
allow_subcommands = ["cp", "ls", "rm", "stat"]
arg_pattern = "^[A-Za-z0-9._/:@=+-]+$"
[profiles.ossutil.env]
OSS_ACCESS_KEY_ID = "hub://secrets/aliyun-oss-picgo/accessKeyId"
OSS_ACCESS_KEY_SECRET = "hub://secrets/aliyun-oss-picgo/accessKeySecret"

[profiles.vsce]
argv = ["C:/Users/huawei/AppData/Local/Programs/nodejs/node.exe",
        "C:/Users/huawei/AppData/Local/Programs/nodejs/node_modules/@vscode/vsce/vsce"]
allow_subcommands = ["publish", "package", "ls"]
arg_pattern = "^[A-Za-z0-9._/:@=+-]+$"
[profiles.vsce.env]
VSCE_PAT = "hub://secrets/vscode-marketplace-vsce/VSCE_PAT"
```

**Interfaces (Produces):** `Profile`（dataclass: `name/argv/env/allow_subcommands/arg_pattern`）；
`profiles_path() -> Path`；`load_profiles(path=None) -> dict[str, Profile]`；
`check_argv(profile) -> None`；`check_args(profile, args) -> None`。

> **实施修正（2026-08-11）**：初稿把 `-e` / `--eval=x` 塞进 `test_args_pattern_refuses`，
> 但 `arg_pattern` 的字符类 `[A-Za-z0-9._/:@=+-]` 里本来就含 `-` 和 `=`，这两条当然过得去。
> **不是收紧 pattern**——那会把 `--force`、`--out=x.vsix` 这些日常尾参一起废掉，闸迟早被摘。
> 真正挡住 `-e` 的是**子命令白名单**（它只可能出现在 `args[0]`）；尾参里的 `-开头` 排在
> 入口脚本之后，解释器根本看不到。测试拆成 `test_interpreter_flag_cannot_be_first`
> 与 `test_option_like_tail_arg_allowed` 两条，把这个分工写死。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_profile.py 新建
import pytest
from hub.secrets_store import SecretsError
from hub.secrets_profile import load_profiles, check_argv, check_args

def _write(tmp_path, body):
    p = tmp_path / "secrets-profiles.toml"
    p.write_text(body, encoding="utf-8")
    return p

OK = """
[profiles.demo]
argv = ["{exe}"]
allow_subcommands = ["cp"]
arg_pattern = "^[A-Za-z0-9._/:@=+-]+$"
[profiles.demo.env]
TOK = "hub://secrets/demo/k1"
"""

def _exe(tmp_path, name="tool.exe"):
    p = tmp_path / name
    p.write_bytes(b"MZ")
    return str(p).replace("\\", "/")

def test_load_ok(tmp_path):
    p = _write(tmp_path, OK.format(exe=_exe(tmp_path)))
    profs = load_profiles(p)
    assert profs["demo"].env == {"TOK": "hub://secrets/demo/k1"}

def test_bat_and_cmd_refused(tmp_path):
    # Windows 上批处理即使 shell=False 也经系统 shell 解析（spec §5.3.1）
    for name in ("tool.bat", "tool.cmd"):
        p = _write(tmp_path, OK.format(exe=_exe(tmp_path, name)))
        with pytest.raises(SecretsError):
            check_argv(load_profiles(p)["demo"])

def test_relative_path_refused(tmp_path):
    p = _write(tmp_path, OK.format(exe="tool.exe"))
    with pytest.raises(SecretsError):
        check_argv(load_profiles(p)["demo"])

def test_missing_executable_refused(tmp_path):
    p = _write(tmp_path, OK.format(exe=str(tmp_path / "nope.exe").replace("\\", "/")))
    with pytest.raises(SecretsError):
        check_argv(load_profiles(p)["demo"])

def test_node_launch_chain_allowed(tmp_path):
    """vsce/mineru 只能这么起：绝对 node.exe + 绝对入口脚本（spec §5.3.1）。"""
    node = _exe(tmp_path, "node.exe")
    entry = tmp_path / "vsce"
    entry.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    body = OK.format(exe=node).replace(
        f'argv = ["{node}"]',
        f'argv = ["{node}", "{str(entry).replace(chr(92), "/")}"]')
    check_argv(load_profiles(_write(tmp_path, body))["demo"])   # 不抛

def test_args_subcommand_whitelist(tmp_path):
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    check_args(prof, ["cp", "a.txt", "oss://b/"])               # 不抛
    with pytest.raises(SecretsError):
        check_args(prof, ["rm", "-rf"])                          # 不在白名单
    with pytest.raises(SecretsError):
        check_args(prof, [])                                     # 必须有子命令

@pytest.mark.parametrize("bad", ["a b", "a;b", "$(x)", "a\x00b", "a|b"])
def test_args_pattern_refuses(tmp_path, bad):
    """arg_pattern 的职责只有一件：**不许出现空白与 shell 元字符**。"""
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    with pytest.raises(SecretsError):
        check_args(prof, ["cp", bad])

def test_interpreter_flag_cannot_be_first(tmp_path):
    """`secrets exec vsce -e "..."` 必须被拒（spec §9 / plan T11 Step 4）。

    挡住它的是**子命令白名单**——`-e` 只可能出现在 args[0]，而 args[0] 必须在白名单里。
    不是 arg_pattern：plan 初稿把这两条用例塞进 test_args_pattern_refuses，
    但那个 pattern 的字符类里本来就含 `-` 和 `=`，`-e` / `--eval=x` 当然能过。
    """
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    with pytest.raises(SecretsError):
        check_args(prof, ["-e", "console.log(1)"])
    with pytest.raises(SecretsError):
        check_args(prof, ["--eval=x"])

def test_option_like_tail_arg_allowed(tmp_path):
    """尾部的 `--force` / `--out` 必须放行。

    它们排在**入口脚本之后**，解释器根本看不到（node 只有在脚本路径之前才会把 -e 当 eval）。
    真正守住"AI 不得控制解释器"的是固定启动链 + 子命令白名单；在这里一刀切禁 `-` 开头，
    只会让 ossutil / vsce 的日常参数全废，闸就被摘掉了。
    """
    prof = load_profiles(_write(tmp_path, OK.format(exe=_exe(tmp_path))))["demo"]
    check_args(prof, ["cp", "--force", "a.txt", "oss://b/"])    # 不抛
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# hub/secrets_profile.py 新建
"""profile：一份**声明**，不是脚本。

规则是「**AI 不得控制解释器/入口脚本/固定前缀**」，不是「禁止解释器」——后者照字面实现
会让 3 个 profile 起不来 2 个（vsce / mineru-open-api 在 Windows 上是 npm shim，
实体就是 `node.exe <入口脚本>`）。见 spec §5.3.1。

所以 `argv` 是一条**固定启动链**：每一段都是 profile 里写死的绝对路径，AI 只能往后追加
经语法校验的尾部参数。它仍然传不了 -e/-c、换不了入口、注入不了 NODE_OPTIONS。
"""
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hub.secrets_store import SecretsError

_BANNED_SUFFIX = {".bat", ".cmd"}


@dataclass
class Profile:
    name: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allow_subcommands: list[str] = field(default_factory=list)
    arg_pattern: str = r"^[A-Za-z0-9._/:@=+-]+$"


def profiles_path() -> Path:
    base = Path(os.environ.get("HUB_HOME") or (Path.home() / ".hub"))
    return base / "secrets-profiles.toml"


def load_profiles(path: Path | None = None) -> dict[str, Profile]:
    p = Path(path) if path else profiles_path()
    if not p.is_file():
        raise SecretsError(f"没有 profile 声明：{p}")
    raw = tomllib.loads(p.read_text(encoding="utf-8")).get("profiles") or {}
    out: dict[str, Profile] = {}
    for name, d in raw.items():
        argv = d.get("argv") or []
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise SecretsError(f"profile {name}：argv 必须是非空字符串数组")
        out[name] = Profile(
            name=name,
            argv=argv,
            env=dict(d.get("env") or {}),
            allow_subcommands=list(d.get("allow_subcommands") or []),
            arg_pattern=d.get("arg_pattern") or Profile.arg_pattern,
        )
    return out


def check_argv(profile: Profile) -> None:
    """启动链：每段绝对路径、真实存在；**首段必须是 .exe**，.bat/.cmd 一律拒。"""
    for i, seg in enumerate(profile.argv):
        p = Path(seg)
        if not p.is_absolute():
            raise SecretsError(f"profile {profile.name}：启动链第 {i} 段不是绝对路径：{seg}")
        if p.suffix.lower() in _BANNED_SUFFIX:
            raise SecretsError(
                f"profile {profile.name}：拒绝 {p.suffix} —— Windows 上批处理文件"
                f"即使 shell=False 也会经系统 shell 解析，参数语义不再受控")
        if not p.is_file():
            raise SecretsError(f"profile {profile.name}：启动链第 {i} 段不存在：{seg}")
    if Path(profile.argv[0]).suffix.lower() != ".exe":
        raise SecretsError(f"profile {profile.name}：启动链首段必须是 .exe")


def check_args(profile: Profile, args: list[str]) -> None:
    """尾部参数：首个必须落在子命令白名单里，其余每个都要过 arg_pattern。

    **两道闸分工不同，别指望 arg_pattern 挡解释器**：`-e` / `--eval=x` 这类东西只可能
    出现在 args[0]，而 args[0] 必须命中子命令白名单——挡它的是白名单。arg_pattern 只管
    "不许有空白与 shell 元字符"；它的字符类里本来就得含 `-` 和 `=`，否则 `--force`、
    `--out=x.vsix` 这些日常尾参全废，闸就会被人摘掉。

    尾参里出现 `-开头` 也不危险：它们排在**入口脚本之后**，解释器看不到
    （node 只有在脚本路径之前才把 -e 当 eval）。
    """
    if not args:
        raise SecretsError(f"profile {profile.name}：缺子命令")
    if args[0] not in profile.allow_subcommands:
        raise SecretsError(
            f"profile {profile.name}：子命令 {args[0]!r} 不在白名单 "
            f"{sorted(profile.allow_subcommands)} 内")
    rx = re.compile(profile.arg_pattern)
    for a in args[1:]:
        if not isinstance(a, str) or "\x00" in a or not rx.match(a):
            raise SecretsError(f"profile {profile.name}：参数不合语法：{a!r}")
```

- [ ] **Step 4: 运行确认通过** + 全量回归。
- [ ] **Step 5: 提交** — `feat(hub): profile 声明与固定启动链——规则是禁止 AI 控制解释器`

---

## Task 5: runner —— 局部 env 注入 + 四条路径遮罩（`hub/secrets_run.py`）

**派谁：** opencode，但**遮罩的四条路径要在 prompt 里逐条点名**（最容易只做成功路径）。

**Files:** New `hub/secrets_run.py`；Test `tests/hub/test_secrets_run.py`。

**Interfaces (Produces):** `redact_bytes(b, values) -> bytes`；`RunResult(rc, out, err)`；
`run_profile(profile, args, secrets_root, timeout=600) -> RunResult`。

> **实施修正（2026-08-11，动工前就发现的）**：初稿的测试助手写成
> `Profile(argv=[sys.executable, "-c", script])`，但 T4 的 `check_argv` 要求启动链
> **每一段都是存在的绝对路径**，`-c` 第一个就过不去——`run_profile` 开头就调 `check_argv`，
> 那 8 条测试会全挂。改成"当前解释器 + 真实入口脚本"，正好也是 vsce / mineru 的真实形状。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_run.py 新建
import os
import sys
import pytest
from hub.secrets_profile import Profile
from hub.secrets_run import redact_bytes, run_profile

DOC = """---
name: demo
description: d
---

## fields

k1 = s3cr3t-VALUE-xyz
"""

@pytest.fixture
def root(tmp_path):
    (tmp_path / "demo.md").write_text(DOC, encoding="utf-8")
    return tmp_path

def _py_profile(tmp_path, script: str) -> Profile:
    """当前解释器 + 一个真实入口脚本 = 固定启动链，形状与 node.exe + 入口脚本一致。

    **不能写成 `[sys.executable, "-c", script]`**：check_argv 要求启动链每一段都是
    存在的绝对路径，`-c` 第一个就过不去。这正是"启动链写死、AI 只能追加尾参"的
    直接后果——测试也得照这个形状搭，否则测的就不是真实通路。
    """
    entry = tmp_path / "entry.py"
    entry.write_text(script, encoding="utf-8")
    return Profile(name="t", argv=[sys.executable, str(entry)],
                   env={"TOK": "hub://secrets/demo/k1"},
                   allow_subcommands=["go"], arg_pattern="^[A-Za-z0-9._/:@=+-]*$")

def test_redact_exact_only():
    assert redact_bytes(b"a s3cr3t b", ["s3cr3t"]) == b"a <redacted> b"
    assert redact_bytes(b"s3-cr3t", ["s3cr3t"]) == b"s3-cr3t"     # 变形挡不住，这是已知局限

def test_value_reaches_child_verbatim(root):
    p = _py_profile(root, "import os,sys; sys.stdout.write(str(len(os.environ['TOK'])))")
    r = run_profile(p, ["go"], root)
    assert r.rc == 0 and r.out.strip() == str(len("s3cr3t-VALUE-xyz"))   # 长度对 → 逐字符保真

def test_stdout_redacted(root):
    p = _py_profile(root, "import os,sys; sys.stdout.write(os.environ['TOK'])")
    r = run_profile(p, ["go"], root)
    assert "s3cr3t-VALUE-xyz" not in r.out and "<redacted>" in r.out

def test_stderr_redacted_on_nonzero(root):
    p = _py_profile(root, "import os,sys; sys.stderr.write(os.environ['TOK']); sys.exit(3)")
    r = run_profile(p, ["go"], root)
    assert r.rc == 3 and "s3cr3t-VALUE-xyz" not in r.err

def test_timeout_output_redacted(root):
    p = _py_profile(root, "import os,sys,time; sys.stdout.write(os.environ['TOK']); "
                    "sys.stdout.flush(); time.sleep(30)")
    r = run_profile(p, ["go"], root, timeout=2)
    assert r.rc != 0 and "s3cr3t-VALUE-xyz" not in r.out

def test_undecodable_output_redacted(root):
    p = _py_profile(root, "import os,sys; sys.stdout.buffer.write(b'\\xff\\xfe' + "
                    "os.environ['TOK'].encode())")
    r = run_profile(p, ["go"], root)
    assert "s3cr3t-VALUE-xyz" not in r.out          # 解码失败路径也要先遮罩

def test_value_not_in_argv(root, monkeypatch):
    seen = {}
    import subprocess
    real = subprocess.run
    def spy(argv, **kw):
        seen["argv"] = argv
        return real(argv, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert all("s3cr3t-VALUE-xyz" not in a for a in seen["argv"])

def test_parent_environ_untouched(root):
    before = dict(os.environ)
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert dict(os.environ) == before and "TOK" not in os.environ

def test_no_temp_file_left(root, tmp_path):
    import tempfile
    before = set(os.listdir(tempfile.gettempdir()))
    run_profile(_py_profile(root, "pass"), ["go"], root)
    assert set(os.listdir(tempfile.gettempdir())) == before
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# hub/secrets_run.py 新建
"""runner：固定 argv + 一次性局部 env → 子进程 → 遮罩输出。

不变量（spec §5.5，每一条都有对应测试）：

- 真值绝不进 argv（进程列表可见）
- 不生成任何明文临时文件——**结构上不产生**，不是"用完删掉"
- 不修改父进程的全局 os.environ；只构造一次性局部 mapping
- 不做变量展开、不做命令替换——现在是结构上不存在这个环节
- 遮罩覆盖**成功 / 非零退出 / 超时 / 解码失败**四条路径，且**先在 bytes 上做**再解码

**遮罩不是安全边界**：只做精确值匹配，变形/截断/编码后的值挡不住（与 secrets_scan 同构）。
子进程自己想打印、写盘、发网络，谁也拦不住——env 注入不是隔离（spec §10）。
"""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hub.secrets_backend import resolve_env
from hub.secrets_profile import Profile, check_args, check_argv

_MASK = b"<redacted>"


@dataclass
class RunResult:
    rc: int
    out: str
    err: str


def redact_bytes(b: bytes, values) -> bytes:
    """精确值匹配替换。长的先替，避免一个值是另一个的前缀时替出半截。"""
    if not b:
        return b
    for v in sorted({x for x in values if x}, key=len, reverse=True):
        b = b.replace(v.encode("utf-8", "surrogatepass"), _MASK)
    return b


def _decode(b: bytes, values) -> str:
    # 先遮罩再解码：解码失败退化成 replace 也不会把真值漏出来
    return redact_bytes(b or b"", values).decode("utf-8", "replace")


def run_profile(profile: Profile, args: list[str], secrets_root: Path,
                timeout: int = 600) -> RunResult:
    check_argv(profile)
    check_args(profile, args)
    injected = resolve_env(Path(secrets_root), profile.env)
    values = list(injected.values())

    # env 是**完整替代**不是 overlay：从父进程副本出发再覆盖，
    # 免得子进程丢掉 SystemRoot/TEMP 这类 Windows 上不给就起不来的东西。
    # 父进程的 os.environ 本身一个字节都不动。
    env = dict(os.environ)
    env.update(injected)

    argv = [*profile.argv, *args]
    try:
        cp = subprocess.run(argv, env=env, shell=False, close_fds=True,
                            capture_output=True, timeout=timeout)
        return RunResult(cp.returncode, _decode(cp.stdout, values), _decode(cp.stderr, values))
    except subprocess.TimeoutExpired as e:
        # 超时对象里**也带着已经产出的输出**，同样要过遮罩
        return RunResult(124, _decode(e.stdout or b"", values),
                         _decode(e.stderr or b"", values) + f"\n[hub] 超时 {timeout}s")
    finally:
        injected.clear()
        values.clear()
```

- [ ] **Step 4: 运行确认通过** + 全量回归。
- [ ] **Step 5: 提交** — `feat(hub): profile runner——局部 env 注入 + 四条路径遮罩`

---

## Task 6: `secrets` 子命令 + 进程内自守（`hub/secrets_cli.py`、`hub/cli.py`）

**派谁：** 我自己写（`run`/`render` 的自守属于闸，闸写错是零痕迹失效）。

**Files:** New `hub/secrets_cli.py`；Modify `hub/cli.py`；Test `tests/hub/test_secrets_cli.py`。

**Interfaces (Produces):** `human_only() -> None`（`sys.stdout.isatty()` 为假即抛）；
`cmd_exec/cmd_run/cmd_render/cmd_unlock`；`hub secrets ...` 子命令挂进 `build_parser()`。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_cli.py 新建
import pytest
from hub.secrets_store import SecretsError
from hub.secrets_cli import human_only

class _S:
    def __init__(self, tty): self._tty = tty
    def isatty(self): return self._tty

def test_human_only_refuses_when_stdout_not_tty(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    with pytest.raises(SecretsError):
        human_only()

def test_human_only_passes_in_terminal(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    human_only()                    # 不抛

def test_human_only_never_uses_stdin_isatty(monkeypatch):
    """实测 stdin.isatty() 在 AI 工具下是 True——用它当判据等于没写（spec §6.7.3.2）。"""
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    monkeypatch.setattr(sys, "stdin", _S(True))     # 故意把 stdin 摆成"像终端"
    with pytest.raises(SecretsError):
        human_only()                                 # 仍然必须拒

def test_exec_does_not_require_tty(monkeypatch, tmp_path):
    """exec 是给 AI 的那条通道，不设自守。"""
    from hub import secrets_cli
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    # exec 路径不调用 human_only
    assert "human_only" not in secrets_cli.cmd_exec.__code__.co_names
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现（要点，实现时补全 argparse 接线）**

```python
# hub/secrets_cli.py 新建（节选：承重的部分）
"""secrets 子命令。

**双通道（spec §5.2）**：
  run / render  → human-only，AI 一律走不通
  exec <profile> → 给 AI 的那条

**为什么 human-only 的闸长在这里而不是只在 hook 上**：`hub` 根本不在 PATH 上，
真实写法是 `py -3 -m hub.cli secrets ...`，hook 的命令串匹配枚举不完（spec §6.7.3.1）。
hook 那层是提示，这层才承重。

**绝不用 sys.stdin.isatty()**：实测在 Claude Code 的 Bash/PowerShell 工具下它是 True，
拿它当"是不是人"的判据等于没写。有区分度的是 stdout（spec §6.7.3.2 的实测表）。
"""
import sys

from hub.secrets_store import SecretsError


def human_only() -> None:
    tty = getattr(sys.stdout, "isatty", None)
    if tty is None or not tty():
        raise SecretsError(
            "这条命令只给人在终端里用。AI 请走 `secrets exec <profile>`——"
            "它能替你跑上传/发布/提取，但拿不到密钥值。")


def cmd_run(args) -> int:
    human_only()
    ...


def cmd_render(args) -> int:
    human_only()
    ...


def cmd_exec(args) -> int:
    # 不设自守：这就是给 AI 的通道
    ...
```

- [ ] **Step 4: 接进 `hub/cli.py`** —— 加一个 `secrets` 子命令（**不带 `--vault`**，
      密钥库与金库无关，别跟着 `common` 走）：

```python
    sec = sub.add_parser("secrets")
    ssub = sec.add_subparsers(dest="subcmd", required=True)
    se = ssub.add_parser("exec"); se.add_argument("profile"); se.add_argument("args", nargs="*")
    se.set_defaults(func=cmd_exec)
    sr = ssub.add_parser("run"); sr.add_argument("argv", nargs=argparse.REMAINDER)
    sr.set_defaults(func=cmd_run)
    su = ssub.add_parser("unlock"); su.add_argument("--minutes", type=int, default=10)
    su.set_defaults(func=cmd_unlock)
```

- [ ] **Step 5: 运行确认通过** + 全量回归。
- [ ] **Step 6: 提交** — `feat(hub): secrets 双通道 CLI——run/render 进程内自守，exec 放行`

---

## Task 7: 解锁令牌（`hub/secrets_unlock.py`）—— 开口的承重闸

**派谁：** 我自己写。**这是整个开口成不成立的那一件事。**

**Files:** New `hub/secrets_unlock.py`；Test `tests/hub/test_secrets_unlock.py`。

**Interfaces (Produces):** `token_path() -> Path`；`issue_token(minutes) -> None`（**从 `CONIN$`
读确认短语**）；`token_valid(now=None) -> bool`（hook 用，**裸 read_text**）。

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_unlock.py 新建
import time
import pytest
from hub.secrets_store import SecretsError
from hub import secrets_unlock as U

class _S:
    def __init__(self, tty): self._tty = tty
    def isatty(self): return self._tty

@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SECRETS_ROOT", str(tmp_path))
    return tmp_path

def test_refuses_without_tty(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(False))
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()            # fail-closed：不产生令牌

def test_refuses_when_console_unreadable(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: (_ for _ in ()).throw(OSError("no console")))
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()

def test_refuses_on_wrong_phrase(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: "nope")
    with pytest.raises(SecretsError):
        U.issue_token(10)
    assert not U.token_path().exists()

def test_issues_on_correct_phrase(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_valid()

def test_expires(root, monkeypatch):
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_valid(now=time.time() + 9 * 60)
    assert not U.token_valid(now=time.time() + 11 * 60)      # 时间边界

def test_no_forever_option():
    import inspect
    src = inspect.getsource(U)
    assert "--forever" not in src and "minutes=0" not in src   # 没有"一直开着"的档位

def test_garbage_token_is_invalid(root):
    U.token_path().write_text("not-a-timestamp", encoding="utf-8")
    assert U.token_valid() is False                            # 解析不了 = 无效，不是有效

def test_token_valid_uses_bare_read(root):
    """hook 是判定者不是被判定者：走 guard.read_source_text 会命中 secrets 黑名单
    把自己挡死（spec §6.7.3.4 第 1 条）。"""
    import inspect
    assert "read_source_text" not in inspect.getsource(U.token_valid)

def test_unlock_is_not_a_secret_item(root, monkeypatch):
    """`.unlock` 不能被当成一条可引用的密钥（spec §6.7.3.4 第 2 条）。"""
    from hub.secrets_store import iter_items
    import sys
    monkeypatch.setattr(sys, "stdout", _S(True))
    monkeypatch.setattr(U, "_read_console_line", lambda: U.CONFIRM_PHRASE)
    U.issue_token(10)
    assert U.token_path().name not in iter_items(root)
    assert ".unlock" not in [f"{i}.md" for i in iter_items(root)]
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# hub/secrets_unlock.py 新建
"""短时效解锁令牌 —— 人工授权开口的承重闸（spec §6.7.3）。

**授权动作必须物理上在人手里。** 三条实测结论决定了写法（spec §6.7.3.2）：

- `sys.stdin.isatty()` 在 AI 工具下是 **True** → **绝不能**拿它当判据；
- `sys.stdout.isatty()` 在 AI 工具下是 False、真终端是 True → 当便宜的前置判据；
- `sys.stdin.readline()` 立刻 EOF，但 `echo X | ...` 就能满足 → 不够；
- 读 **`CONIN$`**（真实控制台键盘缓冲区）在 AI 工具下**永久阻塞**，管道也灌不进去 → 承重。

失败方向永远是"**没有令牌**"。任何异常都不产生令牌。

**诚实边界**：这挡的是会犯错的 AI，不是蓄意的——刻意绕行可以自己分配一个伪终端（spec §2.1）。
"""
import sys
import time
from pathlib import Path

from hub.secrets_store import SecretsError

CONFIRM_PHRASE = "unlock secrets"
MAX_MINUTES = 60


def token_path() -> Path:
    from hub.secrets_backend import secrets_root
    return secrets_root() / ".unlock"


def _read_console_line() -> str:
    """从**控制台设备**读一行，不是从 stdin —— 管道喂不进 CONIN$。"""
    with open("CONIN$", "r", encoding="utf-8", errors="replace") as f:
        return (f.readline() or "").strip()


def issue_token(minutes: int) -> None:
    if not isinstance(minutes, int) or not (1 <= minutes <= MAX_MINUTES):
        raise SecretsError(f"minutes 必须在 1..{MAX_MINUTES} 之间（没有『一直开着』的档位）")
    tty = getattr(sys.stdout, "isatty", None)
    if tty is None or not tty():
        raise SecretsError("unlock 只能由人在真实终端里敲。")
    print(f"要开放密钥明文 {minutes} 分钟。请在控制台键入确认短语：{CONFIRM_PHRASE}")
    try:
        line = _read_console_line()
    except OSError as e:
        raise SecretsError(f"读不到控制台，拒绝签发：{e}") from e
    if line != CONFIRM_PHRASE:
        raise SecretsError("确认短语不匹配，未签发。")
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(int(time.time() + minutes * 60)), encoding="utf-8")
    print(f"已开放到 {time.strftime('%H:%M:%S', time.localtime(time.time() + minutes * 60))}")


def token_valid(now: float | None = None) -> bool:
    """hook 每次工具调用都会问一次，必须便宜、且**永不抛**。

    裸 read_text：走 guard.read_source_text 会命中 secrets 黑名单把 hook 自己挡死。
    """
    try:
        raw = token_path().read_text(encoding="utf-8").strip()
        return float(raw) > (now if now is not None else time.time())
    except Exception:
        return False        # 读不到 / 解析不了 / 过期 = 无效
```

- [ ] **Step 4: 运行确认通过** + 全量回归。
- [ ] **Step 5: 提交** — `feat(hub): 解锁令牌——承重闸读 CONIN$，绝不用 stdin.isatty`

---

## Task 8: PreToolUse hook（`hub/hooks/secrets_guard.py`）

**派谁：** 我自己写。**闸写错是零痕迹失效：测试全绿、exit 0、看不出来。**

**Files:** New `hub/hooks/__init__.py`、`hub/hooks/secrets_guard.py`；
Test `tests/hub/test_secrets_hook.py`。

**判定表就是实现规格（spec §6.7.4）：**

| 场景 | 判定 |
|---|---|
| 读已存在的密钥文件，无令牌 | deny |
| 读已存在的密钥文件，令牌有效 | ask |
| 写一个**还不存在**的密钥文件 | ask |
| 改已存在的密钥文件 | ask（需令牌） |
| Bash 命中 `secrets run` / `render` / `unlock` | deny（**提示层**，漏了不致命） |
| Bash 命中 `secrets exec` | allow |
| hook 自身出错 | **exit 2** |

- [ ] **Step 1: 写失败测试**

```python
# tests/hub/test_secrets_hook.py 新建
import json
import subprocess
import sys
from pathlib import Path
import pytest

HOOK = Path(__file__).resolve().parents[2] / "hub" / "hooks" / "secrets_guard.py"

def _run(payload, env_extra=None):
    import os
    env = dict(os.environ); env.update(env_extra or {})
    cp = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                        capture_output=True, text=True, env=env)
    return cp

def _decide(cp):
    return json.loads(cp.stdout)["hookSpecificOutput"]["permissionDecision"]

@pytest.fixture
def sroot(tmp_path, monkeypatch):
    d = tmp_path / "secrets"; d.mkdir()
    (d / "demo.md").write_text("---\nname: demo\n---\n\n## fields\n\nk = v\n", encoding="utf-8")
    return d

def test_read_existing_denied(sroot):
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and _decide(cp) == "deny"

def test_read_with_token_asks(sroot):
    import time
    (sroot / ".unlock").write_text(str(int(time.time() + 600)), encoding="utf-8")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(sroot / "demo.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "ask"

def test_write_new_file_asks(sroot):
    cp = _run({"tool_name": "Write", "tool_input": {"file_path": str(sroot / "brand-new.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "ask"          # 首次录入：拦写没意义，弹窗让用户看见存到哪

def test_symlink_bypass_blocked(tmp_path, sroot):
    link = tmp_path / "innocent.md"
    try:
        link.symlink_to(sroot / "demo.md")
    except OSError:
        pytest.skip("本机没有创建符号链接的权限")
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(link)}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"         # guard.is_denied 的双查在这里兑现

def test_unrelated_path_allowed(tmp_path, sroot):
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "readme.md")}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and cp.stdout.strip() == ""     # 不相干就别插嘴

@pytest.mark.parametrize("cmd", [
    "hub secrets unlock --minutes 10",
    "py -3 -m hub.cli secrets unlock --minutes 10",           # ← 本机的**真实**写法
    "python -m hub.cli secrets unlock",
    "py -3 C:/Users/huawei/ai-cli-migrate/hub/cli.py secrets unlock",
    "hub secrets run -- cmd /c echo %TOK%",
    "py -3 -m hub.cli secrets render --out x.txt",
])
def test_bash_denied_forms(sroot, cmd):
    cp = _run({"tool_name": "Bash", "tool_input": {"command": cmd}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny", cmd

def test_bash_exec_allowed(sroot):
    cp = _run({"tool_name": "Bash",
               "tool_input": {"command": "py -3 -m hub.cli secrets exec ossutil cp a oss://b/"}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and (cp.stdout.strip() == "" or _decide(cp) == "allow")

def test_bash_reading_secrets_by_type_denied(sroot):
    cp = _run({"tool_name": "Bash",
               "tool_input": {"command": f'cmd /c type "{sroot / "demo.md"}"'}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert _decide(cp) == "deny"

@pytest.mark.parametrize("payload", [
    {"tool_name": "Grep", "tool_input": {"pattern": "secrets", "path": "."}},
    {"tool_name": "Bash", "tool_input": {"command": "grep -rn secrets ."}},
    {"tool_name": "Bash", "tool_input": {"command": "git log --oneline | head"}},
])
def test_no_false_positive(sroot, payload):
    """误伤会逼人把闸摘掉，闸就废了（spec §6.4）。裸词 `secrets` 必须放行。"""
    cp = _run(payload, {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 0 and cp.stdout.strip() == ""

def test_malformed_input_exits_2(sroot):
    import os
    env = dict(os.environ); env["HUB_SECRETS_ROOT"] = str(sroot)
    cp = subprocess.run([sys.executable, str(HOOK)], input="{not json",
                        capture_output=True, text=True, env=env)
    assert cp.returncode == 2        # **不是 1** —— exit 1 是非阻断，工具照跑

def test_guard_exception_exits_2(sroot, monkeypatch):
    """判定逻辑一崩就静默放行是最致命的坑（spec §6.1）。"""
    cp = _run({"tool_name": "Read", "tool_input": {"file_path": None}},
              {"HUB_SECRETS_ROOT": str(sroot)})
    assert cp.returncode == 2

def test_hook_does_not_import_backend():
    """hook 每次工具调用都跑；也绝不能把明文层拖进来。"""
    src = HOOK.read_text(encoding="utf-8")
    assert "secrets_backend" not in src
    assert "read_source_text" not in src      # 判定者不是被判定者
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# hub/hooks/secrets_guard.py 新建
"""Claude Code PreToolUse hook：密钥读闸（spec §6）。

**退出码语义（官方，2026-08-10 核实）**——这是最容易致命的一处：
  exit 0 + stdout JSON  → JSON 被解析，三档判定生效
  exit 2                → 阻断，stderr 回喂
  **exit 1 与其它非零码 → 非阻断错误，工具照常执行**

所以顶层必须捕获一切异常并转 exit 2。判定逻辑越严谨，这个坑越致命：
它会把一个"拦得住"的闸变成"崩了就放行"。

**它挡不住什么**（spec §6.5，别让它显得比实际强）：用户自己粘明文、MCP/别的进程绕开工具层、
已经在上下文里的明文、蓄意绕行与提示注入。

**只按路径拦，绝不按内容模式拦**（spec §6.4）：secrets_scan 的误报率高到不能当闸。
"""
import json
import sys
from pathlib import Path

# 只 import guard（纯 stdlib 依赖）。每次工具调用都跑，别把 hub 的其余部分拖进来；
# 尤其**绝不 import secrets_backend**——那是读明文的一层。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hub.guard import is_denied                                    # noqa: E402

_DENY_SUB = ("run", "render", "unlock")
# 命令串匹配是**提示层**：`hub` 不在 PATH 上，写法枚举不完（spec §6.7.3.1）。
# 承重闸在 secrets_cli.human_only / secrets_unlock.issue_token 里。
_CMD_HINTS = ("hub secrets", "hub.cli secrets", "cli.py secrets", "secrets_cli")


def _token_valid() -> bool:
    """裸读，**不走 guard.read_source_text**——那会命中 secrets 黑名单把自己挡死。"""
    import time
    import os
    try:
        root = Path(os.environ.get("HUB_SECRETS_ROOT") or (Path.home() / ".claude" / "secrets"))
        return float((root / ".unlock").read_text(encoding="utf-8").strip()) > time.time()
    except Exception:
        return False


def _out(decision: str, reason: str) -> None:
    json.dump({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, sys.stdout)


def _paths(tool: str, ti: dict):
    """只取**真的是路径**的字段。

    **绝不要把 Grep 的 `pattern` 算进来**：`Path("secrets")` 会命中 has_denied_component，
    于是任何"搜一下 secrets 这个词"都被拒——那是纯误伤。误伤会逼人把闸摘掉，
    闸就废了（secrets_scan.py 用学费换来的那条结论，spec §6.4）。
    """
    for key in ("file_path", "path", "notebook_path"):
        v = ti.get(key)
        if isinstance(v, str) and v:
            yield v


def _looks_like_path(tok: str) -> bool:
    """只有**带分隔符**的 token 才当路径查。

    否则 `grep -r secrets .` 里那个裸词 `secrets` 会被 is_denied 判成命中 —— 又是误伤。
    代价是：cwd 恰好在 secrets/ 里时敲裸文件名查不出来。**这是有意接受的漏**，
    宁可漏也不能误伤（同上）。
    """
    return "/" in tok or "\\" in tok


def _decide_bash(cmd: str):
    low = cmd.lower()
    if any(h in low for h in _CMD_HINTS):
        for sub in _DENY_SUB:
            if f"secrets {sub}" in low:
                return "deny", (
                    f"`secrets {sub}` 是 human-only 通道。AI 请走 "
                    f"`secrets exec <profile>`——它能替你跑上传/发布/提取，但拿不到密钥值。")
    # 命令串里直接出现 secrets 路径（`cmd /c type ...\secrets\x.md`）
    for tok in cmd.replace('"', " ").replace("'", " ").split():
        if _looks_like_path(tok) and is_denied(Path(tok)):
            return "deny", "密钥明文请用 hub:// 引用，别直接读。"
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}

    if tool == "Bash":
        got = _decide_bash(str(ti.get("command") or ""))
        if got:
            _out(*got)
        return 0

    writing = tool in ("Write", "Edit", "NotebookEdit")
    for raw in _paths(tool, ti):
        p = Path(raw)
        if not is_denied(p):
            continue
        if writing:
            _out("ask", "要往密钥库写。请确认存到哪、存成什么；存完请把正文改成 hub:// 引用。")
            return 0
        if _token_valid():
            _out("ask", "解锁令牌有效，仍需你逐次确认。批准后读到的明文只用于当次操作。")
            return 0
        _out("deny", "密钥明文读不了。用 hub://secrets/<item>/<field> 引用；"
                     "要跑真实命令走 `secrets exec <profile>`；"
                     "确实需要看明文时，请**你自己**在终端里 `secrets unlock`。")
        return 0
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as e:
        # 任何没接住的异常都必须变成 exit 2。退 1 = 静默放行。
        sys.stderr.write(f"hub secrets guard 自身出错，按拒绝处理：{e!r}\n")
        raise SystemExit(2)
```

- [ ] **Step 4: 运行确认通过** + 全量回归。
- [ ] **Step 5: 提交** — `feat(hub): PreToolUse 密钥读闸——三档判定 + 顶层 exit 2 fail-closed`

---

## Task 9: AST 架构测试（`hub.collect.*` 不 import `secrets_backend`）

**派谁：** opencode。

**Files:** Test `tests/hub/test_arch_secrets_isolation.py`。

- [ ] **Step 1 & 3: 测试即实现**

```python
# tests/hub/test_arch_secrets_isolation.py 新建
"""架构边界，**不是安全边界**（spec §6.3）。

它保的不变量只有一条：`collect` 的传递依赖图永远到不了 `secrets_backend`，
它的全部本机读取仍经过 guard。防的是**未来某次重构把两条路径接通**，不是防 AI——
Python 的模块边界不是 capability boundary，任何代码都能 import，AI 也能直接调 CLI。
"""
import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "hub"
FORBIDDEN = {"secrets_backend", "secrets_store", "secrets_run", "secrets_cli", "secrets_unlock"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def test_collect_never_reaches_secrets():
    bad = []
    for f in sorted((PKG / "collect").rglob("*.py")):
        for name in _imports(f):
            if any(x in name for x in FORBIDDEN):
                bad.append(f"{f.name} → {name}")
    assert not bad, "collect 不许碰密钥层：" + "; ".join(bad)


def test_guard_has_no_exemption_parameter():
    """DENIED_NAMES 不加任何豁免参数（spec §6.3）——那会让不变量退化成
    '取决于调用方传了什么'，正是 feedback_preview_must_share_write_path 那次事故的形状。"""
    src = (PKG / "guard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        if fn.name in ("is_denied", "check_source", "read_source_text", "has_denied_component"):
            args = fn.args
            assert len(args.args) == 1 and not args.kwonlyargs and not args.defaults, \
                f"guard.{fn.name} 多了参数——豁免口子就是这么开的"
```

- [ ] **Step 4: 运行确认通过**（这个测试**现在就该绿**，它锁的是现状）。
- [ ] **Step 5: 提交** — `test(hub): AST 架构测试——collect 永远到不了密钥层`

---

## Task 10 🔴 人工闸：挂 hook + 真机验证

**派谁：不派。** 改的是用户自己的 `~/.claude/settings.json`。

- [ ] **Step 1: 备份** —— 先把 `~/.claude/settings.json` 复制一份带日期的副本。
- [ ] **Step 2: 加 PreToolUse**（`matcher` 少一个就是一个洞，spec §6.1）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read|Edit|Write|Grep|Glob|Bash|NotebookEdit",
        "hooks": [
          { "type": "command",
            "command": "py -3 C:/Users/huawei/ai-cli-migrate/hub/hooks/secrets_guard.py" }
        ]
      }
    ]
  }
}
```

  （hook 自己 `sys.path.insert` 到仓库根，所以不依赖 `PYTHONPATH`，也不依赖 `~/.hub/config.toml`。）

- [ ] **Step 3: 真机四项验证**（在新开的 Claude Code 会话里，由用户看结果）：
  1. 让 AI `Read ~/.claude/secrets/aliyun-oss-picgo.md` → 应当被 **deny**，且理由里提到 `hub://`。
  2. 让 AI 跑 `cmd /c type ~/.claude/secrets/mineru-api.md` → 应当被 **deny**。
  3. 让 AI 跑 `py -3 -m hub.cli secrets unlock --minutes 10` → 应当被 **deny**；
     即便 hook 漏了，命令自身也应当因为 `stdout.isatty()` 为假而拒绝（**两层都要看到**）。
  4. 日常读一个**不相干**的文件 → 必须**毫无感觉**（hook 不插嘴）。
- [ ] **Step 4: 回归确认**（最容易被忽略的一条）—— 挂上闸之后，把平时最常跑的几件事
      各跑一遍（collect / status / 读代码 / grep），确认**没有误伤**。
      有误伤就先摘掉 hook 再修，别带着误伤过夜。

> **顺序警告（spec §11.2）**：这一步必须在 T4–T6 之后。先落闸再建 `exec` 通道，
> 中间那段时间 AI 既读不到明文、又没有替代通道，**日常工作会直接卡死**。

---

## Task 11 🔴 人工闸：三条真实工作流跑通

**派谁：不派。** 碰真实密钥与真实外部服务（会真的上传/发布）。

- [ ] **Step 1: 写 `~/.hub/secrets-profiles.toml`** —— 按 T4 的格式，三个 profile。
      vsce / mineru 用 `node.exe + 绝对入口脚本`；ossutil 直接 exe。
      入口脚本的绝对路径从 `…\nodejs\vsce.cmd` 里那行 `"%dp0%\node_modules\…"` 抄。
- [ ] **Step 2: 逐条跑**（每条都要**看输出里有没有真值**）：
  - `secrets exec ossutil ls oss://picgo-imgs1270/`
  - `secrets exec vsce ls`（只读，别直接 publish）
  - `secrets exec mineru <一个只读子命令>`
- [ ] **Step 3: 记录 env 基线** —— 若某个 profile 因为缺环境变量起不来，把它**真正需要**的
      变量记进 profile 的 notes；这是将来把 `env` 从 inherit 收紧成白名单的依据。
- [ ] **Step 4: 反向验收** —— 确认 `secrets exec` **跑不了**解释器：
      试 `secrets exec vsce -e "console.log(process.env)"` 应当被拒
      （拒它的是**子命令白名单**，`-e` 落在 `args[0]` 上；见 T4 的实施修正）。

---

## Task 12: README + 全量回归 + 收尾

- [ ] **Step 1: `hub/README.md` 加一节**

```markdown
## 密钥：引用式，不入库

密钥本体只存 `~/.claude/secrets/<item>.md` 的 `## fields` 段，**从不进金库**（`hub/guard.py` 的硬闸）。
别处一律只写引用：`hub://secrets/<item>/<field>`。

- `py -3 -m hub.cli secrets exec <profile> [args]` —— **给 AI 的通道**。只能跑
  `~/.hub/secrets-profiles.toml` 里预先声明好的 profile：启动链写死、子命令白名单、
  尾参过语法校验、输出经精确遮罩。AI 能请求"上传/发布/提取"，拿不到密钥值。
- `py -3 -m hub.cli secrets run -- <任意命令>` —— **只给人**，在真实终端里。
- `py -3 -m hub.cli secrets unlock --minutes N` —— **只给人**，需要在控制台键入确认短语。

Claude Code 侧挂了一个 PreToolUse 闸（`hub/hooks/secrets_guard.py`）：读密钥路径默认拒绝，
写新密钥文件与持令牌读取弹窗确认。**它约束的是 Claude Code 原生工具的读取**——
Codex / opencode 没有等价闸，也不防蓄意绕行与提示注入。
```

- [ ] **Step 2: 全量回归** — `py -3 -m pytest tests/ -q`，零失败。
- [ ] **Step 3: 更新 `docs/NEEDS.md`** —— 把 B 那一行从「spec 已立，未动工」改成实际状态。
- [ ] **Step 4: 提交** — `docs(hub): README 密钥引用一节 + Plan B 回归绿`

---

## 依赖与顺序

```
T1(解析器) ─▶ T2(引用/backend) ─▶ T3🔴(迁移真实文件)
                  └─▶ T4(profile) ─▶ T5(runner) ─▶ T6(CLI 双通道)
                                                      └─▶ T7(unlock 承重闸) ─▶ T8(hook)
                                                                                 └─▶ T10🔴(挂闸真机验)
T9(AST 架构测试)  —— 任何时候都能做，锁的是现状
T11🔴(三条真实工作流)  —— 需要 T3 + T4 + T5 + T6
T12(README + 回归)     —— 最后
```

**顺序上唯一不能反的一条（spec §11.2）**：**T10 必须在 T6 之后**。先落闸再建 `exec` 通道，
中间那段时间 AI 既读不到明文、又没有替代通道，日常工作直接卡死。

## 派活分配（spec §11.3）

| 任务 | 派 opencode | 理由 |
|---|---|---|
| T1 / T2 / T4 / T5 / T9 | **派** | 格式解析、env 注入、AST 遍历，测试契约明确，判断成分低 |
| T6 / T7 / T8 | **不派** | 闸写错是**零痕迹失效**：测试全绿、exit 0、看不出来。难点是"有没有漏一条路径"，正是子 agent 最容易漏的那类 |
| T3 / T10 / T11 | **人工闸** | 碰真实明文、改用户 settings、调真实外部服务 |

**派 opencode 时 prompt 里必须写死**（不明说等于没说，实测它会自己挑 PowerShell 落盘）：
读用 `cmd /c type`；**写必须走 python**（`Path.write_text`/`write_bytes`）；
禁止 PowerShell 的 `Set-Content`/`Copy-Item`；禁止它自己的 Write/Edit 工具。

## 自审（对照 spec v2.2）

- **spec 覆盖**：§3/§4 → T1/T2；§4.3 迁移 → T3；§5.3+§5.3.1 启动链 → T4；§5.5 注入不变量 → T5；
  §5.2 双通道 + 进程内自守 → T6；§6.7.3 承重闸 → T7；§6.1/§6.2/§6.4/§6.7.4 → T8；§6.3 → T9；
  §9 验收 1–8 → T1/T5/T8/T11 分别兑现。
- **v2.2 三处修正各有落点**：去 dotenvx → T5 的 Tech Stack 与实现（零第三方）；
  启动链 → T4 的 `test_node_launch_chain_allowed` + `test_bat_and_cmd_refused`；
  承重闸挪进程内 → T7 全部 + T6 的 `test_human_only_never_uses_stdin_isatty`。
- **fail-open 三个坑各有专测**：hook 退 1 静默放行 → `test_malformed_input_exits_2` /
  `test_guard_exception_exits_2`；`stdin.isatty()` 恒真 → `test_human_only_never_uses_stdin_isatty`；
  hook 用 `read_source_text` 把自己挡死 → `test_hook_does_not_import_backend` + `test_token_valid_uses_bare_read`。
- **诚实边界写进了代码注释而不只是 spec**：`secrets_run` 的"遮罩不是安全边界"、
  `secrets_unlock` 的"挡的是会犯错的 AI"、`test_arch_secrets_isolation` 的"架构边界不是安全边界"。
- **spec §9 那条"扫描的诚实声明"**：`secrets_scan` 的 0 命中只是辅助信号，**不作为任何任务的通过条件**——
  本 plan 全程没把它列进验收。
- **未覆盖（有意）**：`chats/` 回溯脱敏、`secrets.age` 静态加密、多设备同步、
  Codex/opencode 的等价读闸——spec §2.3 明确不做。
