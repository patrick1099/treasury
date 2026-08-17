# Plan —— hub 原始对话库（chats）实现计划 v2

**权威设计**：`docs/specs/2026-08-14-hub-chats-raw-store.md` **v2**（经 codex 评审后重写）。
**题目来源**：`Obsidian Vault/AI 记忆、知识笔记与 Skill 演化系统实施基线.md` 的**阶段1：原始对话库**。

**Goal:** 五个平台（Claude Code / Codex / opencode / Copilot CLI / Copilot VS Code）的对话
以**字节级原样、append-only** 收进金库备份区 `<host>/<tool>/chats/`；另建一份**可随时重建**的
SQLite+FTS5 索引落在 `~/.hub/chats-index.db`，支持全文检索并能从任一命中**回到原消息**。

**Tech Stack:** Python 3，**stdlib only**（`sqlite3` / `hashlib` / `tomllib` / `json`），pytest。

**本轮边界（用户 2026-08-14 决定）**：明文对话**只落本机，不进 git**，且**没有任何离机备份**
（spec §3.2 —— 这条边界要如实说，不许在任何输出里说成"换机照它还原"）。

---

## 进度

| 任务 | 状态 |
|---|---|
| T0b `scan_tree(skip_dirs=)` + collect 接线 | **done**（28 passed） |
| T0c `hub/chats/model.py`、`hub/chats/paths.py` | **done**（纯声明；`model.py` 的 GENERATED 注释要按 T3 更新） |
| T1a `Writer.copy_binary` **返工**（原子写 + 边拷边算） | **done**（opencode 执行，已复核）。新建 `hub/digest.py`；6 条新测试；612 passed / 3 skipped。三个被改文件头字节仍是 `e0 a8 91…`（**没脱密**） |
| T4 claude + codex 源提取器 | **done**（opencode 执行，已复核）。13 条测试；密文完好；缺源规则复用 `require_source` |
| T2 manifest 台账 + `tomlout.quote_key` | **done**（opencode，已复核）。13 条测试；主聊补了一处 `sorted(meta)`——meta 是普通 dict、顺序跟插入走，会让"两次 dump 字节相同"在别处悄悄失效 |
| T5 opencode SQLite 导出 | **done**（opencode，已复核）。9 条测试；`SELECT *` 不写死列清单（升级加列不漏，代价是走一次 revision） |
| T6 copilot-cli + copilot-vscode 源 | **done**（opencode，已复核）。16 条测试；坏 `workspace.json` 记空串不抛——一个坏工作区不该连累其余会话一条都收不上来 |
| T12 `.gitignore` + `ChatsTracked` 代码闸 | **done**（opencode，已复核）。10 条测试。主聊收紧两处：①按**路径组件**判而非子串 `"/chats/" in l`（后者漏掉顶层 `chats/foo`，而顶层正是手工放东西最可能落的地方）；②`git ls-files` 失败时**抛**而不是返回 `[]`——闸拿不到清单等于"证明不了里面没有对话"，返回空会被读成"证明了没有"，失败方向必须是停下 |
| T3 append-only 状态机 | **done**（opencode，已复核）。14 条测试。主聊补了一个**真漏洞**：快路径只比源的 `(size,mtime)`，**从不看金库里那份还在不在**——误删/同步清掉/磁盘坏之后台账仍记着"有"，每次收集报 unchanged，`--verify` 也只重算源。新增 `_vault_copy_ok()`（日常一次 `exists()`，verify 才比对金库那份的 sha）+ 新态 `restored` + 两条回归测试 |
| T7 源注册表 + `device.toml` 的 chats + SCHEMA 文案 | **done**（主聊自己写，趁 T8 在跑）。5 条测试。SCHEMA §12 从"空目录、要等加密层"改成实际状态，并写死"**别把它当备份**"与"解禁不是删掉 gitignore 那行就完事" |
| T8 五个解析器 | **done**（opencode，已复核）。27 条测试。它自己去拉了 **VS Code 官方源码**确认重放语义，查出 spec 漏写的第四种：`kind:0` 快照 / `kind:1` 设值 / `kind:2` push（先把数组截到 `i` 再 append）/ **`kind:3` 删除键**；还实测发现 response 数组也可能被 `kind:1` 整个替换。以它查到的权威语义为准 |
| T1 T9–T11 | 待做 |

> **全量测试的教训（2026-08-14）**：T12 往 `publish()` 里加了 `tracked_chats` 闸，
> 而 `test_backend_retry.py` 的 `_install()` 只给 `tracked_gitlinks` 打了桩——
> 那两道闸**都不走 `_run`**（各自直接 `subprocess.run`），假 git 拦不住，
> `GitBackend(Path("x"))` 那个不存在的 cwd 直接 `NotADirectoryError`。
> 只跑针对性测试看不见，跑全量才炸。**每件活收口前跑一次 `pytest tests/hub`，别只跑新增的那个文件。**

> **落盘配方（2026-08-14 实测，派活时必须带上）**：opencode 会把大量时间烧在
> "怎么把文件写进这个加密仓"上——heredoc 转义炸、`write_text` 把 CRLF 翻倍成 `\r\r\n`。
> 同一个 session：不给配方那轮 495 秒只产出 9 行，给了配方直接干完两个文件。
> 配方＝**内容先用它自己顺手的方式写到仓外临时目录，再用一行
> `dst.write_bytes(src.read_bytes())` 搬进仓**。仓内写入仍然只走 python，规矩没破，
> 但转义和换行翻译两个坑结构上消失了。
> 配套：动手前 `esafenet-baseline.ps1 snapshot`，干完 `check -Fix`（金库
> `shared/scripts/` 下）。**注意它只判"原来加密、现在明文"，新建文件不在基线里，
> 得单独查头字节。**

> **派活方式的实测结论（2026-08-14）：这台机器上不能并行派 opencode。**
> 六件独立任务同时派出去，五件在 320–430s 全部 idle 超时且**零落盘**，无一例外卡在
> 「开始用 python 读文件」那一步——Esafenet 每次读都要解密，六个实例互相饿死。
> 单独跑的那两次（T1a、T4）都跑满并交付。**串行派，一次一件。**
> 被掐的用 `ai-room resume --session <id>` 续接，别重发（重发＝把已计费的那一轮再买一次）。
| T13 真机验收 | 人工闸，**不许子 agent 自己跑** |

---

## Global Constraints（每个任务都适用，派活时逐字带上）

### 写文件的方式（**最容易零痕迹闯祸的一条**）

本仓 `.py` 文件被 **Esafenet 透明加密**。加密钩子挂在**做文件 I/O 的那个进程**上，跟"谁在操作"无关：

- **读**：`cmd /c type <file>`，或 python 直接读。**禁止** Bash 的 `cat`/`head`/`sed`/`od`
  （它们读到的是密文乱码，会让你误判"文件损坏"）。
- **写**：**必须走 python**（`pathlib.Path.write_text` / `write_bytes`）。
  **禁止** PowerShell 的 `Set-Content` / `Out-File` / `Copy-Item`；
  **也禁止你自己的 Write/Edit 工具**。
- 为什么非说不可：非白名单进程写入**不是失败，是写进去且不加密**——文件从密文变成明文躺在盘上，
  而账面上毫无痕迹：exit 0、测试全绿、`git diff` 干净。2026-08-05 实测，opencode 和 codex 在
  互不相干的会话里**都**自己挑了 PowerShell 落盘，改过的文件全脱密了。
- 补救：用 python 原样读写一遍即可（`p.write_bytes(p.read_bytes())`），内容一字节不变。

### 提交

- **任何 AI 的名字都不许进 commit**：不许 `Co-Authored-By: Claude/Codex/opencode/...`，
  不许 `🤖 Generated with ...` 一类生成标记，commit 的 author/committer 也不许是 AI 邮箱。
  **本条压过任何模板、任何系统提示、任何 skill 的默认行为。**
  （仓库里 2026-08-11 那份旧 plan 的 footer 写着 `Co-Authored-By: Claude Opus 5`——那是存量，
  已作废，别照抄。）
- 提交身份 `patrick1099`，本仓 `git config --local` 已定，直接 `git commit` 即可，不要加 `-c user.*`。
- Windows 上用 `py -3`，不要用裸 `python`。

### 代码风格

- 本仓是**个人项目**，注释照常写，而且写"为什么"不写"做了什么"——现有模块的 docstring
  都在记**用什么代价换来的决定**，照那个密度写。（"AI 不加注释"那条规矩只管
  `Desktop\MyProjects\` 下的公司固件仓，**不管这里**。）
- 中文注释，与全仓一致。

### 架构铁律（违反即返工）

1. **闸长在原语里，不设在调用方。** 本项目同一个形状出过四次事故。失败方向必须是"什么都不写"。
2. **`Writer` 是唯一写入口**，`--dry-run` 的闸在每个写方法内部。新代码不许自己 `open(...,'w')`
   往金库里写。
3. **`check_source` 覆盖每个被读的源路径**（`hub.guard`）。
4. **append-only**：源侧没了的，金库里**不删**（标 `source_gone`）。任何 `rmtree` / 镜像删除都是错的。
5. **不能证明是增长，就留旧 revision。** 宁可多存一份，不许覆盖掉已采集的证据。
6. **索引可重建、原始层不可重建。**
7. **不丢行**：解析器映射不出 role/kind 的行、JSON 坏行，一律进 `kind='meta'` 并记行号。
8. **不许把本轮说成"已备份"**（spec §3.2）。文档、注释、CLI 输出一律照实说 local-only。

### 测试

- 全部落在 `tests/hub/`，`py -3 -m pytest tests/hub -q` 必须全绿
  （当前基线 621 passed / 3 skipped，加上 T0a/T0b 的 8 条新测试）。
- `tests/hub/conftest.py` 的 autouse `_sandbox_home` 已把 `Path.home()` 重定向进 tmp。
  **任何测试都不许碰真实的 `~/.claude` / `~/.codex` / `~/.local/share/opencode` / `~/.copilot`**，
  也不许碰真实金库。源数据一律用 `tmp_path` 造 fixture，内容自己编，
  **不许从真机拷真实对话进测试**。
- 凡 `subprocess.run(..., text=True)` 必须同时钉 `encoding="utf-8", errors="replace"`
  （仓里有 AST 静态防线 `test_subprocess_decoding.py` 会判红）。

### 交活标准

**照抄落盘、如实报失败、不许自己改设计。** 计划里写不通的地方**停下来报告**，不要自己换个
方案往下做。

---

## T1a `Writer.copy_binary` 返工 —— 原子写 + 边拷边算（**先做这个**）

**背景**：`hub/writer.py` 里已经有一个 `copy_binary`，是我先前加的，**有真 bug**，评审逮到：
它直接以 `wb` 打开目标 —— 复制中途失败/断电，**旧证据当场被截断**，而它可能是唯一副本；
另外调用方"先 hash 源、再 copy"，两步之间源文件还在被工具追加，manifest 记下的 sha
可能根本不是落盘的那些字节。

**改成**（spec §6.1）：

1. 先在 `hub/digest.py`（**新建，放顶层不放 chats 包**——`writer.py` 是核心层，
   不能反向依赖 chats）里提供：

   ```python
   @dataclass
   class Digest:
       bytes: int
       sha256: str      # 小写 hex
       lines: int       # 按 b"\n" 计数；非空且不以 \n 结尾时最后那截也算一行

   def digest_bytes(data: bytes) -> Digest
   def digest_file(path: Path) -> Digest          # 分块 1 MiB，不许 read() 整个文件
   def prefix_sha256(path: Path, n: int) -> str   # 只读前 n 字节；n 超长抛 ValueError
   def copy_and_digest(fsrc, fdst, chunk=1<<20) -> Digest   # 边拷边算，返回**实际写入**的摘要
   ```

2. `Writer.copy_binary(src, dest) -> Digest | None` 改为：
   `check_source(src)` → 记 `written` → dry-run 直接返回 `None` →
   源 `stat()` → 同目录 `mkstemp` 临时文件 → `copy_and_digest` →
   再 `stat()` 源，`(size, mtime_ns)` 变了 → **重试一次**，仍变则抛
   `SourceChangedWhileCopying`（新异常，放 `hub/digest.py` 或 `hub/writer.py` 均可，
   自己挑一处并说明）→ `flush + fsync` → `os.replace` → 返回 Digest。
   **任何异常都要清掉临时文件**（照 `write_text_atomic` 现成的写法，它已经解决过这个问题）。

**测试**（补进 `tests/hub/test_writer.py`，现有 5 条 copy_binary 测试保留并适配返回值）：

- 返回的 Digest 与 `digest_file(dest)` 相等；
- 目标已存在且是 CRLF 时仍字节级原样（现有测试）；
- 非法编码字节原样（现有测试）；
- 复制过程中源被追加 → 抛 `SourceChangedWhileCopying`，**且 dest 保持旧内容不变**
  （用 monkeypatch 在 `copy_and_digest` 之后改源文件来构造）；
- 中途异常（monkeypatch 让 `copy_and_digest` 抛）→ 临时文件被清掉、dest 旧内容完好；
- dry-run 返回 `None` 且零写入。

---

## T1 `hub/digest.py` 的独立测试

T1a 会把这个模块建起来。本任务只补它自己的单测（不依赖 Writer）：

空文件；不以换行结尾；`\r\n` 文件（行数按 `\n` 算，**不做换行归一**）；
`prefix_sha256(p, n)` 等于同内容前缀文件的 `digest_file().sha256`；`n` 越界抛 `ValueError`；
`copy_and_digest` 的返回值与对目标文件 `digest_file` 一致。

---

## T2 `hub/chats/manifest.py` —— 证据台账

**目标**：读写 `<host>/<tool>/chats/manifest.toml`，一个 artifact 一张表。

```python
def load(chats_dir: Path) -> dict[str, Entry]      # 文件不存在 → {}
def dump(entries: dict[str, Entry]) -> str         # 交给 Writer.write_text 落盘
```

- 表名是 `artifact.<被引号包起来的 rel>`。给 `hub/tomlout.py` 加一个**公开**薄封装
  `quote_key(k)` 并用之（不要复制一份引号逻辑，也不要直接用私有 `_key`）。
- 字段见 spec §4.2 与 `hub/chats/model.py` 的 `Entry`。**注意 `Entry` 要按 spec v2 补齐**：
  `role` / `source_size` / `source_mtime_ns` / `source_ino` / `superseded_by` / `supersedes`。
  （现有 `model.py` 是 v1 版本，字段名 `bytes`/`sha256`/`lines` 保留，
  把 v1 的 `source_mtime_ns` 拆成 `source_size` + `source_mtime_ns` + `source_ino`。）
- `meta` 里的键值平铺进同一张表，键加前缀 `x_`（`dump_toml` 只认 str/bool/int，
  **不支持嵌套表**，遇到别的形状它会抛——那是对的，别绕过）。
- 表按 `rel` 排序输出，**两次 dump 必须字节相同**，否则 manifest 自己会造成"每次都有改动"。

**测试**：往返；rel 含 `/`、`.`、空格、中文时表名引号正确且 `tomllib` 能解析；空 manifest；
`meta` 平铺与还原；两次 dump 字节相同。

---

## T3 `hub/chats/collect.py` —— append-only 状态机（**本计划的承重件**）

```python
def collect_source(source: str, arts: list[Artifact], chats_dir: Path,
                   w: Writer, verify: bool = False) -> SourceReport
```

**四态状态机**（spec §5，逐态都要有测试）：

```
内容相同                       → unchanged   零写入
能证明新内容包含全部旧证据      → grown       覆盖 current
不能证明                       → preserved   旧的存成不可变 revision，新的写进 current
源侧没了                       → gone        一个字节都不动，标 source_gone
```

判据：

1. **快路径**：`(源 size, 源 mtime_ns)` 与 manifest 的 `source_size/source_mtime_ns` 相同
   → 直接判 `unchanged`，**连 sha 都不算**。`verify=True` 时**跳过快路径**，一律重算。
   **验收硬指标：连跑两次 `collect_source`，第二次 `w.written == []`。**
2. **COPY 的增长证明**：新 size > 旧 size 且 `prefix_sha256(新文件, 旧 bytes) == entry.sha256`
   → `grown`，覆盖。
3. **GENERATED 无增长证明**：sha 相同 → `unchanged`；**sha 不同 → 一律 `preserved`**。
   （v1 的"新 lines >= 旧 lines 判增长"**已作废，别实现**——行数相同可能是就地更新，
   行数增加也可能同时删了旧行。理由写进 docstring，`model.py` 里 v1 的那段注释也要改。）
4. **preserved 怎么落盘**：旧的**改名**进 `revisions/<原 rel 打平>.<旧 sha 前 8 位><后缀>`
   （"打平"= 把 `/` 换成 `__`），为它在 manifest 留一条 `superseded_by` 指向 current、
   `source_path` 留空、`source_gone=true`；current 记 `supersedes`。
   **改名要走 Writer —— 新增 `Writer.rename(src, dest)`**：dry-run 闸照旧，
   **dest 已存在时抛，绝不覆盖**。
5. **gone**：manifest 里有、本次 `arts` 里没有 → `source_gone = True`，文件不动。

**其它要求**：

- COPY 落盘走 `Writer.copy_binary`（返回 Digest，**直接用它填 manifest**，不要事后重读）。
- GENERATED 落盘走新增的 `Writer.write_bytes(path, data) -> Digest`
  （与 `write_text` 同形但不做换行/编码处理，dry-run 闸照旧）。
- **manifest 最后写**（spec §6.1 第 5 条）：所有 artifact 处理完才写台账，台账不能领先于事实。
- `imported_at` 用 UTC ISO8601 秒精度。**测试不许断言具体时刻**，只断言存在且可解析。
- dry-run：一个字节不落盘，但 report 内容与真跑一致。

**测试**：四态各一条 + dry-run + 幂等第二次 `w.written == []` + `--verify` 绕过快路径 +
GENERATED sha 变化必留 revision + `Writer.rename` 撞名抛 + manifest 写在最后
（构造一个落盘中途抛错的用例，断言 manifest 没被更新）。

---

## T4 `hub/chats/sources/claude.py` + `codex.py`

**契约**：每个源模块导出

```python
NAME = "claude"
def discover(root: Path) -> list[Artifact]      # root = 该工具的数据根目录
```

**缺源规则（spec §6.3，别搞混）**：`discover` 拿到的 `root` 是**已配置**的路径。
路径不存在 → **抛**（`hub/collect/errors.py` 的 `require_source` 就是干这个的，复用它），
**不许返回 `[]`**——返回 `[]` 会被状态机解释成"这个源的全部会话都消失了"，
把整个源标成 `source_gone`。"未配置"这个合法情况由调用方**根本不调用**来表达。

- **claude**：`root` = `~/.claude`，扫 `projects/*/*.jsonl`。
  `rel = f"sessions/{project_dir}/{stem}.jsonl"`（**带上工程目录**，否则两个工程下的同名
  session 会撞车），`session_id = stem`，`kind=COPY`，`role=transcript`，
  `meta["x_project_dir"] = project_dir`（回溯工程路径的唯一线索）。
- **codex**：`root` = `~/.codex`。扫 `sessions/**/rollout-*.jsonl`
  → `rel = "sessions/" + 相对 sessions/ 的原路径`（**保留 YYYY/MM/DD 分层**，747 个文件不能平铺）；
  再扫 `archived_sessions/rollout-*.jsonl` → `rel = "sessions/archived/<name>"`。
  `session_id` 从文件名 `rollout-<ISO>-<uuid>.jsonl` 取 uuid（取不出就用 stem，别抛）。
- 两者都要 `check_source(root)`。

**测试**：rel/session_id/meta/role 正确；空目录返回 `[]`（目录在但没文件，这是合法的）；
**root 不存在抛**；两个工程目录下同名 session 不撞车；codex 日期分层被保留。

---

## T5 `hub/chats/sources/opencode.py`

- `root` = `~/.local/share/opencode`，库文件 `opencode.db`。
  **只读打开**：`sqlite3.connect(f"file:{db}?mode=ro", uri=True)`。绝不写源库。
- 只读 `session` / `message` / `part` 三张表。**`event` 表（3 万行）是重复事件流，不导出。**
- 导出格式见 spec §4.3：每行一个 JSON，加且只加 `_row`；`data` 列解析后原样内联，
  解析失败则保留字符串并加 `_data_unparsed: true`，**不许丢**。
- **行序必须确定**：session 行最前，然后 message 与 part 按 `(time_created, id)` 升序。
  排序不确定 → 两次导出字节不同 → 幂等当场失效。
- `kind=GENERATED`，`role=transcript`，`payload` = utf-8 字节，`lines` = 行数，
  `rel = f"sessions/{session_id}.jsonl"`。
- 库文件不存在 → **抛**（同 T4 的缺源规则）。

**测试**：`tmp_path` 里用 `sqlite3` 造同构小库，验证行序确定（两次导出字节相同）、
`_row` 标注、`data` 内联、坏 JSON 走 `_data_unparsed`、`event` 表不出现在导出里、
库不存在抛。

---

## T6 `hub/chats/sources/copilot_cli.py` + `copilot_vscode.py`

- **copilot-cli**：`root` = `~/.copilot`，扫 `session-state/<uuid>/`。
  有 `events.jsonl` → `rel = f"sessions/{uuid}/events.jsonl"`，`role=transcript`；
  同目录 `workspace.yaml` 存在也收，`rel = f"sessions/{uuid}/workspace.yaml"`，**`role=auxiliary`**。
  **没有 events.jsonl 的会话目录**（本机实测真有）→ 不产 artifact，但要能让调用方知道
  （`discover` 返回值之外再给一个 `skipped: list[tuple[str,str]]`，或在 Artifact 里
  用 role 表达——**自己挑一种并在 docstring 说明，两边一致即可**）。
  `inuse.*.lock` / `session.db` 不收。
- **copilot-vscode**：`root` = `%APPDATA%/Code/User`（由调用方给绝对路径，
  **模块内不读环境变量**——测试要能指到 tmp）。
  扫 `workspaceStorage/<hash>/chatSessions/*.jsonl` → `rel = f"sessions/{hash}/{name}"`，
  `role=transcript`。
  额外产出一个 **GENERATED + `role=auxiliary`** 的 `workspaces.toml`：
  把每个 `<hash>` 映射到 `workspaceStorage/<hash>/workspace.json` 的 `folder` 或 `workspace`
  值（**两个键都可能，本机两种都有**；都没有就记空串，别抛）。
  没有这张表那串 hash 就是废字符串——**这条别省**。

**测试**：缺 events.jsonl 的处理；`workspace.json` 只有 `folder` / 只有 `workspace` / 都没有
三种情况；workspaces.toml 内容确定且 `tomllib` 能解析；role 标对。

---

## T7 源注册表 + device.toml + SCHEMA 文案

- `hub/chats/sources/__init__.py`：`SOURCES: dict[str, module]` 五个源；
  `discover(name, root)`；未知名字抛。
- `hub/model.py` 的 `ToolSources` 加 `chats: str | None = None`；`hub/vault.py` 的
  `_tool_sources` 读它。
- **不要动 `hub/collect/__init__.py` 的 `preflight`**：chats 源由 `hub chats` 自己预检，
  collect 的预检范围一个字不变（避免"没配 chats 就跑不了 collect"这种连坐）。
- 更新 `hub/schema_md.py` 里 `chats/` 那句「目前是空目录……要等加密层」→ 实际状态：
  原始层已实现、由 `hub chats collect` 维护、**本轮不进 git 且无离机备份**、
  解禁条件是静态加密+回溯脱敏。**不改 vault version**。

**测试**：`ToolSources.chats` 能从 device.toml 读出；`SOURCES` 五个名字齐全；未知源抛。

---

## T8 `hub/chats/parse/` —— 五个源 → 统一事件

```python
@dataclass
class ParsedSession:
    session_id: str
    started_at: int | None; ended_at: int | None      # epoch 毫秒
    cwd: str; repo: str; branch: str; model: str; title: str

@dataclass
class ParsedEvent:
    seq: int
    native_id: str            # 源自带的 id，拿不到就空串
    source_key: str           # 无原生 id 时的稳定键路径，拿不到就空串
    ts: int | None
    role: str; kind: str; tool: str
    text: str
    last_raw_line: int              # 1 起
    replay_upto_line: int | None    # 只有增量日志源用

def parse(path: Path) -> tuple[ParsedSession, list[ParsedEvent]]
```

映射见 spec §8.2。要点：

- **native_id 必须尽量填**（spec §8.1，定位符靠它才稳定）：claude 的 `uuid`、
  codex 的 `payload.id`、opencode 的 `message.id`/`part.id`、copilot-cli 的事件 `id`、
  vscode 的 `requestId`/`responseId`。
- **claude**：`message.content[]` 逐元素展开成多个 event，共享同一个 `last_raw_line`；
  同一行展开的多个 event 用 `source_key = f"{uuid}#c{i}"` 区分。
- **codex**：`payload.type` 分派；`session_meta` 出 session 元信息。
- **opencode**：读 T5 导出的那份 jsonl（`_row` 分派），**不是读库**。
- **copilot-cli**：事件 `type` 前缀分派。
- **copilot-vscode**：**先重放**——`kind:0` 全量快照，`kind:1/2` 是 `{k:[键路径], v:值}` 增量。
  重放出最终 `requests[]` 后展开成 event。每条 event 要同时给出
  `last_raw_line`（最后一次影响它的行）、`replay_upto_line`（重建所需水位）、
  `source_key`（如 `requests[3].response[1]`）。**这是五个源里最绕的一个；
  实现不出来就停下来报告，别糊。**
- 坏行（JSON 解析失败）→ 一条 `kind='meta'` 的 event，`text` 存原始行前 500 字符，**不许跳过**。

**测试**：每源一个小 fixture（真实形状、内容自己编）；断言 role/kind/tool/native_id/行号；
坏行不丢；vscode 重放后 requests 数量与顺序正确，且 `replay_upto_line` 单调不减。

---

## T9 `hub/chats/index.py` —— SQLite + FTS5

- 库落 `~/.hub/chats-index.db`（走 `hub/hubconfig.py` 拿 hub_root，**别自己拼 `Path.home()`**）。
- 表结构照 spec §8 逐字建，含 `session.host` 与 `UNIQUE(host, source, session_id)`。
- `event_fts` 是 external content 表（`content='event', content_rowid='id'`），
  插入/删除 event 时要自己同步 FTS，别忘了。
- **只索引 `role=transcript` 的 artifact；只索引 current，不索引 `revisions/`**（spec §8）。
  auxiliary（`workspaces.toml` / `workspace.yaml`）只用来补 session 的工程信息。
- **增量**：库里该 `(host, source, session_id)` 的 `raw_sha` 与 manifest 的 `sha256` 相同 → 跳过；
  不同或不存在 → 删掉这条 session 的全部 event（连同 FTS 行）后重建。
- `--rebuild`：整库删掉重建。
- 中文按字切是**已知精度折扣**，写进 docstring，不引第三方分词器。

**测试**：建库→索引→计数；同 sha 第二次索引零变化；改了 sha 触发重建且**不留孤儿 event/FTS 行**；
`--rebuild` 后计数一致；FTS 能搜到中文与英文；revisions 与 auxiliary 都没进索引。

---

## T10 `hub/chats/search.py` —— 检索与回原消息

```python
def search(db, query, source=None, project=None, role=None, limit=20) -> list[Hit]
def show(db, vault_root, ref: str, context: int = 0) -> str
```

- `ref = "<source>/<session_id>#<r>"`，`r` 依次尝试 `native_id` → `source_key` → `s<seq>`。
  用 `s<seq>` 命中时，输出里要注明"序号定位，可能漂移"。
- **`show` 按源分流**（spec §9）：
  - 普通 JSONL 源：返回 `last_raw_line` 那一行原始内容（`context=N` 前后各多给 N 行）。
  - **copilot-vscode**：重放到 `replay_upto_line`，取 `source_key` 指向的逻辑消息，
    **返回重建后的原消息**，并附最后写入行号与参与重建的证据行号。
- 原始层文件缺失 → 明确报"证据文件不在"，**不许静默返回空**。

**测试**：往返（search 拿到的 ref 喂 show 能返回含该片段的内容）；vscode 源的 show
返回的是重建后的完整消息而不是单条 delta；ref 格式非法抛；文件缺失的报错路径。

---

## T11 CLI `hub chats`

照现有 `secrets` 那个二级子命令的写法接进 `hub/cli.py`：

```
hub chats collect [--source S]... [--verify] [--dry-run] [--vault V] [--host H]
hub chats index   [--rebuild] [--source S]...
hub chats search  <查询> [--source S] [--project P] [--role R] [--limit N]
hub chats show    <source>/<session_id>#<ref> [--context N]
hub chats status
```

- `collect` 打印每源 new/grown/unchanged/preserved/gone/skipped 计数；
  **preserved 要醒目**（说明源侧发生了重写），但**退出码仍是 0**。
- `status` **必须原样打印 spec §3.2 那三行边界**（`storage: local-only` /
  `off-device backup: none` / `git tracking: blocked`），外加每源会话数、字节数、
  revision 数、最后导入时间、索引新鲜度。
- 退出码：正常 0；有 preserved 也是 0；**已配置的源路径不存在 → 非零，且在任何写入前就停**。

**测试**：`main(["chats","collect","--vault",...,"--dry-run"])` 零写入；参数解析；
缺源的非零退出且零写入；`status` 三行边界在输出里。

---

## T12 不进 git 的双保险

1. 金库根 `.gitignore` 幂等写入（**走 Writer**）：

   ```gitignore
   # 原始对话库：明文，本轮不进 git，且没有任何离机备份。
   # 解禁条件=静态加密+回溯脱敏；届时同步实现另议，不是"删掉这行"就完事。
   */*/chats/
   ```

2. **代码闸**：`hub/backend.py` 的提交路径上，提交前若 `git ls-files` 报出任何匹配
   `*/chats/*` 的**已跟踪**路径 → 抛 `ChatsTracked` 并停止，一个字节都不提交。
   照同文件里 `GitlinkTracked` 那个形状写，报错要给出解法（`git rm --cached -r <路径>`）。

**测试**：临时 git 仓 `git add -f` 一个 chats 文件后调提交路径 → 抛 `ChatsTracked` 且零提交；
正常情况不误伤（`shared/`、`<host>/claude/memory` 照常提交）。

---

## T13 真机验收（**人工闸，子 agent 不许自己跑**）

照 spec §10 逐条：五源全量收 → 再收一遍零新增 → 建索引 + `--rebuild` 计数一致 →
随机 20 条命中 `show` 回原消息（含至少 3 条 vscode 的重放）→ 金库 `git status` 干净且
`git add -f` 被闸拦住 → 崩溃安全（复制中途杀进程，旧证据完好）→
`hub collect` 计时确认没去读 chats。

---

## 派活分配

| 任务 | 派给 | 依赖 |
|---|---|---|
| T1a copy_binary 返工 + `hub/digest.py` | opencode | — |
| T1 digest 单测 | opencode | T1a |
| T2 manifest（含 `tomlout.quote_key`、`Entry` 补字段） | opencode | — |
| T3 collect 状态机（含 `Writer.rename` / `Writer.write_bytes`） | opencode | T1a T2 |
| T4 claude+codex 源 | opencode | — |
| T5 opencode 源 | opencode | — |
| T6 copilot 两个源 | opencode | — |
| T7 注册表 + device.toml + SCHEMA 文案 | opencode | T4 T5 T6 |
| T8 五个解析器 | opencode | T5 |
| T9 索引 | opencode | T8 |
| T10 检索/回原消息 | opencode | T9 |
| T11 CLI | opencode | T3 T9 T10 |
| T12 git 双保险 | opencode | — |
| T13 真机验收 | **人**（Claude 陪跑） | 全部 |
