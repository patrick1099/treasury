# hub 记忆分层改造 — 实施 plan

> 设计依据：`Obsidian Vault/Agent记忆方案/hub 记忆分层改造方案.md`（2026-08-27）。
> 本文是那份方案的**可执行拆解**，不重复论证，只写「改哪个函数、哪条测试会红、验收看哪个数字」。
> 日期：2026-08-31。**v3** = v2（经 codex 评审并复核事实，记录见 §10）+ 用户提出的归档/回收维度（§3.5）。

---

## 0. 边界（先划清，避免越界）

**不碰 OpenViking。** 用户仍在测试中，本 plan 不读写它的配置、不改插件开关、不搬它的数据。方案 §10/§11 那条线独立走。

**因此 hub 的目标是「唯一确定性、全量索引注入端」**，不是「唯一注入端」——OpenViking 的实验性召回通道保持独立存在，两者不在同一层。

**不动方案第 3 步（`ctx:` 情境维度）和第 4 步（chats 接续）。** 它们依赖尚未收口的前提，且第 3 步要改的 `parse_scope` 正被 dsh 那摊占着（见 §6）。

**68 条记忆正文一个字不改。**

---

## 1. 现状复核（2026-08-31）

### 1.1 hub 视图

| 视图 | 字节 |
|---|---|
| `~/.hub/views/claude/MEMORY.md` | **18 758**（**67** 条，非 68——有 1 条被 scope 筛掉） |
| `~/.hub/views/codex/MEMORY.md` | 18 081 |
| `~/.hub/views/dsh/MEMORY.md` | 17 809 |
| `~/.hub/views/opencode/MEMORY.md` | 17 819 |

`shared/memory` 共 68 个 `.md`，claude 视图 67 条。**分组计数必须在 scope 过滤后按工具动态算**，不能把 18+45+5 写成固定断言。

### 1.2 平台自带记忆：Claude 侧还开着，Codex 侧已经关了

**Claude Code 原生 auto-memory 仍在写**，且只有本仓这一个目录有内容：

```
C--Users-huawei-Desktop-Projects-20260820-Kunlun----/memory/
  MEMORY.md                             1 195 B   ← 每场无条件注入
  edit-tool-destroys-gb2312.md
  kunlun-comm-errcode-blocker.md
  kunlun-display-arch-review.md
  kunlun-keil-batch-build-pitfalls.md
  node-is-esafenet-whitelisted.md
  openviking-eval-pending.md
  subagent-new-file-lands-plaintext.md   （7 条正文合计 18 389 B，按需读）
```

另外 4 个 project 目录只有空的 `MEMORY.md`。

**Codex 原生记忆功能已经是关的。** `~/.codex/config.toml` 里 `[features] memories = false`（已实测确认），`[memories]` 段的 `generate_memories` / `use_memories` 同为 false。磁盘上那 3.1 MB 是**关闭前生成的存量**，不是仍在长的东西：

| 文件 | 字节 |
|---|---|
| `memory_summary.md` | 31 371 |
| `MEMORY.md` | 432 028 |
| `raw_memories.md` | 520 302 |
| `memories_1.sqlite` | 2 252 800 |

所以阶段 D 在 Codex 侧是**验证已关闭**，不是「准备关闭」。

---

## 2. 阶段 A：渲染层瘦身（方案第 0 步）

### 改什么

`hub/memview.py:100 render_view_file` 一个函数。现在每条三行：

```python
rows = [f"- [{e.name}](<{_abs_posix(e.source)}>)\n  — {e.description}\n  — scope: `{' '.join(e.scope)}`"
        for e in entries]
```

改成单行 `- {name} — {description}`。

### 为什么安全

- **路径没人用**：`hub/memread.py:12 read_memory` 是按名在视图里查，命中后从内存里的 `MemoryViewEntry.source` 取路径，跟渲染文本无关。
- **现成的反例**：`render_codex_block`（memview.py:112）本来就不输出路径，Codex 侧一直正常。
- **scope 行不产生行为差异**：视图本身已经是筛过的结果。

### 连带要改（**其中一条是真的会断**）

1. `hub/skills/hub-memory/SKILL.md` 第 8~9 行写着索引「只给了 name / 一句话 description / scope」——scope 没了，这句要同步改。
2. **`hub/inventory.py:71 _view_has_memory` 一定会断**（已核实，不再是待核实点）：

```python
return f"[{name}]" in text or f"`{name}`" in text
```

它靠 markdown 链接的方括号或反引号定界找名字。阶段 A 把 `- [name](<path>)` 变成 `- name — desc`，两个定界符都没了，**所有记忆都会被判成「视图中无此条」**，inventory 的 memory 健康度全线误报 conflict/stale。

**修法：改 inventory 的解析，按行首 `- ` 之后到首个 ` — ` 之前取 name 做精确比对。不要为了迁就它给名字补反引号**——那会把 A 的产物从约 11 411 涨到约 11 545 字节，为一个解析 bug 付永久体积。

3. `hub/inventory.py:94 _view_hash_state` 找不到 `shared_hash:` 行时 `return "ok"` ——应该返回 `stale` 或 `malformed`。缺失哈希被判成健康，是这个检查器唯一的兜底洞。顺手修。

### 会红的测试

`tests/hub/test_memview_render.py`：

- `test_view_file_has_absolute_angle_bracket_links` — 断言的正是要删的东西，改成断言「不含 `](<`」。
- `test_view_file_uses_forward_slashes` — 同上，删或改。
- `test_view_file_empty_has_placeholder` / `test_view_file_embeds_shared_hash` — 不受影响。

### 验收

```
claude 视图 18 758 → ≤ 11 500 B（实测投影约 11 411，余量约 89 B）
且不得靠保留旧定界符达成
pytest tests/hub 全绿
hub status --check 仍判新鲜
```

---

## 3. 阶段 B：L0 折叠 + 归档维度（方案第 1、2 步，合并做，并把第 2 步扩成生命周期）

### 为什么合并

两步都要读新的 `metadata` 键、都要改同一个渲染函数、都要进 `shared_hash`。分两次等于把同一处改两遍。

### 3.1 数据面：group / archived **升成一等字段**（v1 的判断被推翻）

新增 `metadata.group`（自由字符串）和 `metadata.archived`（ISO 日期），**加进 `_KNOWN_META`，做成 `Memory` 的正式字段**。

> **v2 用的是 `status: retired`，v3 改成 `archived: <日期>`。** 起因是发现「退役的插件墓碑」和「做完的待办」在渲染上是同一件事——都是「不再影响当前行动」，没必要占两个状态值；而**归档时间**是真正需要的信息（多久了、什么时候可以清）。一个日期键同时表达状态和时间，比 `status` + `archived_at` 两个键省。为什么归档写在 description 里，不占状态维度。详见 §3.5。

> **v1 我写的是「留在 extra_metadata 里搭车」，理由是升级会让 collect 重排 68 个文件的 frontmatter、产生 68 个 diff。这个理由是错的**：视图渲染走 `load_shared_memories`，**根本不调用 `dump_memory`**；而 `dump_memory` 只要对 `None` 值不输出，没写这两个键的文件就一个字节都不会变。代价是想象出来的，换来的却是真实的弱类型风险。

具体：

```python
group: str | None = None
archived: str | None = None    # ISO 日期 YYYY-MM-DD；有值即归档
```

- `dump_memory` 值为 `None` 时不输出该行 → 68 个文件零 diff。
- `load_memory` 落**强校验**：group 必须是非空单行字符串；archived 必须是严格 `YYYY-MM-DD`。写成 `true`、写成 `2026/08/31`、写成随手一句话，一律 `FrontmatterError` 炸响，**绝不静默按活跃处理**。这正是 `_require_bool`（frontmatter.py:145）那段注释在讲的同一类事故——标志位判反了，而且哪儿都不报错。

`MemoryViewEntry`（memview.py:19）随之加 `group` / `archived` 两个字段，在 `entries_for_tool` 构造时带上。

### 3.2 渲染面

```
# 共享记忆索引 — claude

## 工作约束（N）           ← 展开：name + description
- feedback_no_ai_coauthor_in_commits — 全平台硬性禁令……

## 其余（M）               ← 按 group 折叠，只列名
- 固件约束（改协议/参数/编译前查）(16): project_gas_meter_overview · …
- 个人工具链(15): reference_img2md_script · …

## 已归档（K）             ← archived 有值，只列名
- reference_true_north_plugin · project_code_jump_tags_070 · …
```

**展开判据不是 `type`，`type` 是内容类别不是注入优先级。** 真正的判据是：

| 判据 | 归宿 |
|---|---|
| 不需要任务触发、**开始行动前就必须约束行为** | 展开 |
| 名字和组名已能说清「什么时候该读它」 | 折叠 |
| 只有历史价值、不再影响当前行动 | 归档（§3.5） |
| 高后果但不是 feedback 的少数例外 | **显式 override** |

所以第一版除 group/archived 外**再加一个正交键 `metadata.index: expanded`**：默认仍是 feedback 展开、其余折叠，但任何一条都能被显式提到展开层。没有它，将来发现例外只能靠改 `type`（语义污染）或往代码里塞名字白名单（更糟）。

已知的例外候选：`project_param_scaling`、`project_debug_branch_never_push`、`project_note`、`reference_esafenet_baseline_gate` —— 都是 project/reference，但都属于「动手之前就必须知道，否则会静默弄坏东西」。

**组名要写成触发条件，不是纯名词**：「固件约束（改协议/参数/编译前查）」比「固件与项目」有召回价值。但要认清一点——**改组名不能解决所有遗漏**，有些条目就是需要 description，那就用 `index: expanded`，别硬折。

### 3.3 必须同步改 `shared_hash`，并**加版本前缀**

`hub/memview.py:88` 现在只哈希 `name / description / body / scope`。

哈希输入扩为：**格式版本号 + name + type + description + body + scope + group + archived + index**（将来新增任何影响渲染的键都要进）。输出形如 `v3:<digest>`。

- **不进哈希 = 静默失效**：改了 group 而 `status --check` 仍判新鲜，视图不重算。
- **版本前缀的用途是「正确失效 + 可诊断」，不是避免 stale**。阶段 A 改行格式 bump 一次，阶段 B 改分层规则再 bump 一次；每次升级后先判 stale，跑完 `hub refresh` 才 fresh。旧视图在新规则下本来就不该被信任。

**顺带补一个洞**：`hub/status_report.py:73` 对 Codex 受管块只检查块是否良构，不检查内容是不是当前版本。四个 view 写完、写 AGENTS.md 时失败，状态仍会误报全绿。→ 把 hash 也写进 Codex 受管块并参与检查。

### 3.4 抽一个共享的分类函数

磁盘视图、Codex block、`memory-explain`、`inventory` 四处都要判「这条展开还是折叠、属于哪组」。**先抽一个结构化分类函数让四方共用**，不要把 feedback/group/archived/index 的判定复制四遍——那是下一次改规则时四处不同步的种子。

### 3.5 归档与回收：金库缺的是生命周期，不是又一个分类

**这是本 plan 里唯一一个「新增能力」，其余都是把已有的东西改小。**

#### 病灶

`shared/memory` 里 16 条 `project` 记忆，**正好一半是有生命周期的进度指针，不是长期约束**：

| 长期约束（不会过期） | 进度指针 / 待办（做完就该退场） |
|---|---|
| `project_alarm_enable_convention`、`project_c_coding_standard`、`project_csb_board_split`、`project_gas_meter_overview`、`project_param_scaling`、`project_debug_branch_never_push`、`project_note`、`project_ABCD_task_docs` | `project_cli_ai_spec`、`project_code_jump_tags_070`、`project_obsidian_template_pipeline`、`project_protocol_simulator`、`project_sample_encrypt_tool_todo`、`project_tech_manual_verification`、`project_vibe_apps_stack_tradeoffs`、`project_ai_hub_shared_data_layer` |

**活证据**：`project_code_jump_tags_070` 的 description 第一句就是「0.7.x 全部 shipped」——它已经是完成态，却还挂在 L0 顶层，每场会话无条件注入。

**这跟方案 §10.7 批评 OpenViking 的是同一个病**：「过期结论不会自动退场，检索时历史记录和当前判断混在同一个池子，这是设计问题，与数据量无关。」hub 的金库有一模一样的洞，只是 68 条还压得住，200 条就压不住了。

#### 明确否掉的方案：不要用 `type` 表达生命周期

不新增 `type: archived` 这类值。`type` 是**内容类别**（user/feedback/project/reference），生命周期是**正交维度**——把状态塞进 type，就是 codex 在 §3.2 指出的那个错误（「type 是内容类别不是注入优先级」）的翻版，而且会让一条记忆从 project 变成 archived 之后，再也说不清它原本是什么。

#### 机制

`metadata.archived: 2026-08-31`。缺省 = 活跃。有值 = 归档，值本身就是归档日期。

**归档 ≠ 删除。** 正文一个字不动，仍在金库、仍进 git、仍能 `hub memory-read` 按名读到。变的只有一件事：**从 L0 的浏览路径上撤下来**，只在「已归档（K）」那组里留个名字。

**判定权在人，不在代码。** 自动判「这条做完了」必然误判——`project_protocol_simulator` 的 description 也写着一堆已完成项，但它同时挂着开口项。所以只做巡检，不做自动归档：

```
hub memory-audit --vault <金库> --host <主机>
```

列出三类候选，**只列不改**（跟 `promote-memory` 同样是人工闸门）：

1. **疑似完成**：`type: project` 且 description 命中完成态词（shipped / 已完成 / 已落地 / 全部 / 已闭环）却没有 archived；
2. **久未更新**：金库是 git 仓，用 `git log -1 --format=%cI -- shared/memory/<name>.md` 取最后修改时间，超过阈值（默认 90 天）的 project 条目；
3. **归档已久**：archived 距今超过阈值（默认 180 天）——提示可以彻底清出金库，或搬进 `hub/chats` 那层。

真正执行归档的是另一条命令（或手改 frontmatter 后 `hub refresh`），审阅那一步不许省。

#### 但这只是止血，根治在方案第 4 步

**那 8 条进度指针本来就不该住在金库。** 金库的定位是「跨设备共享 + 人工闸门 + 长期资产」；「某个项目现在做到哪了、下一步是什么」属于**会话接续层**——也就是方案第 4 步要接的 `hub/chats`（`session` / `event` 两张表，已经有 `cwd` 列）。

它们现在挤在金库，是因为接续层没做，只能借住。所以：

- **归档维度现在就做**（成本极低，一个键 + 一条巡检命令），它治的是症状；
- **第 4 步做完之后**，进度指针整体搬去接续层，金库只留长期资产，归档维度退化成纯墓碑用途；
- **不要因为要根治就不止血**——第 4 步不在本 plan 范围内，而 `code_jump_tags_070` 这种已完成条目今天就在浪费每一场会话的注入预算。

### 验收

```
四个视图 ≤ 6 144 B
pytest tests/hub 全绿
没写 group/archived/index 的记忆：有确定 fallback、不消失、不报错
（注意：它们的渲染结果**不可能**与阶段 A 逐字节一致——见 §7 的修正）
```

---

## 4. 阶段 C：`hub memory-explain`

方案 §5 定性为「不是锦上添花」——没有它，过滤系统很快没人敢信，然后退回全 `global`，整套改造白做。

```
hub memory-explain --vault <金库> --host <主机> [--tool claude]
```

输出：每条记忆判定为哪一组 → 展开 / 折叠 / 已归档 / 被 scope 筛掉 → 命中哪条规则（type / group / archived / index）→ **每一段的字节数**。

三条硬要求：

1. **必须解释 scope miss。** `entries_for_tool` 会先把 scope 不匹配的丢掉，直接基于它的输出做 explain，就永远回答不了「这条为什么没出现」——而那正是这个命令存在的理由。要从 `load_shared_memories` 的全量出发，把「被 scope 筛掉」也作为一种判定结果输出。
2. **字节数对实际渲染字符串算** `len(text.encode("utf-8"))`，不许另写估算公式（两套算法必然分叉）。
3. **`--tool` 省略时的语义在 plan 里写死**：解释全部四个工具（不是猜当前工具）。

**同批还要出 `hub memory-audit`**（设计见 §3.5）：列归档候选，只列不改。它和 `memory-explain` 共用 §3.4 那个分类函数。

两条都按 CLI-AI 规范落（`--json` 信封 / `--format json` / 退出码 0·1·2 / `--ai-help`），跟 `memory-read` 同形。

**跟阶段 B 同批做。**

### 连带

- 更新 `hub --ai-help` 的 Quick Reference / Command Reference / 只读副作用说明。
- 补 JSON 信封 + 退出码的契约测试。
- **`hub/schema_md.py:68` 的 `SCHEMA_MD` 仍宣称 hub 只判断旧那几个字段** —— group/archived/index 一旦影响行为，schema 生成源和契约测试必须同步改，否则文档在撒谎。

---

## 5. 阶段 D：平台原生记忆收口

**铁律不变：不删任何原生记忆库。** 只做两件事：停止新增 + 把该留的走人工闸门 promote 进金库。原生库原地留着，将来要回查还在。3.1 MB 对磁盘没有实际意义，删掉损失的是考古和回滚能力。

### 5.1 Claude 侧（**这边才是真的要动**）

开关（codex 给的官方文档出处，落地时先实测确认再写死）：

- 项目设置 `autoMemoryEnabled: false`
- 或全局环境变量 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`

禁用后既不创建也不加载 auto-memory。

**顺序：先 promote，再关。** 反过来的话，没进金库的条目就只能靠手工翻目录找回。

本仓 7 条分两堆：

- **走 `promote-memory` 进金库**（可复用经验）：`edit-tool-destroys-gb2312`、`subagent-new-file-lands-plaintext`、`kunlun-keil-batch-build-pitfalls`、`node-is-esafenet-whitelisted`
- **留原地**（项目态，昆仑这摊结束就过期）：`kunlun-comm-errcode-blocker`、`kunlun-display-arch-review`、`openviking-eval-pending`

### 5.2 Codex 侧：只是验证

`memories = false` 已经在配置里。本阶段做的是**确认它确实没在注入**，以及确认存量库不再增长。**一个字节都不删。**

### 5.3 验收（不能只看字节数）

| 项 | 口径 |
|---|---|
| 不注入 | 新开一场会话，上下文里不出现原生记忆内容 |
| canary | 放一个可识别标记：hub 通道出现一次，原生通道零次 |
| 不再生成 | 连续若干场会话后，原生库的 mtime / git 状态不再变化 |
| 没删东西 | 原生库文件数、字节数**不减少** |
| 入库合规 | 金库新增条目全部经 `promote-memory` |

---

## 6. 开工前的障碍（比方案 §7 写的时候更糟）

`~/treasury` 当前 `git status`：**12 个改动 + 10 个未跟踪**，四摊活压在一起：

```
 M hub/cli.py  M hub/memwire.py  M hub/model.py  M hub/scope.py
 M hub/status_report.py  M hub/vault.py  M hub/opencode_skills.py
?? hub/inventory.py  ?? hub/toggle_ops.py  ?? hub/dsh_ops.py  ?? hub/device_toml.py
?? hub_gui/  ?? dsh-claude-plugin-loader/
```

`model.py` 和 `memwire.py` **正在被改**，而阶段 B 要改的正是 `model.py`（加两个字段）；`inventory.py` 更是本 plan 里必须修的文件却还没提交。

**先定基线，二选一：**

- (a) 把 dsh + inventory + toggle 那摊收口提交，在干净树上做记忆改造；
- (b) 从当前 HEAD 拉 worktree 并行，最后合。

**(a) 更省事**——阶段 B 要动 `model.py`，跟未提交那批直接重叠，并行必撞。

其余两条照旧：

- **Esafenet**：`~/treasury` 是个人项目但透明加密按扩展名全机生效，`.py` 照样是密文。写入只走 Claude Code 工具或 python，**禁 PowerShell 的 `Set-Content` / `Copy-Item`**（那不是失败，是写进去且不加密，exit 0、测试全绿、git diff 干净）。派子 agent 时逐字写进任务描述。个人项目**照常写注释**，hub 现有注释很厚，风格要跟上。
- **提交身份**：本仓 `git config --local` 已定 `patrick1099`。任何 AI 的名字不许进 commit。

---

## 7. 验收（逐条可执行）

| 项 | 命令 / 口径 |
|---|---|
| 阶段 A 体积 | `wc -c ~/.hub/views/claude/MEMORY.md` ≤ 11 500，且不靠保留旧定界符达成 |
| 阶段 A 不误报 | `hub inventory`（或其调用方）的 memory 健康度全绿——`_view_has_memory` 已改新解析 |
| 阶段 B 体积 | 四个视图全部 ≤ 6 144 |
| 测试 | `pytest tests/hub` 全绿（基线以定基线那一刻的数为准） |
| 记忆不变 | `git -C ~/treasury-vault status --short shared/memory` 为空 |
| 新鲜度 | 每次 bump 哈希版本后先判 stale，跑 `hub refresh` 后转 fresh |
| 向后兼容 | **缺省字段有确定 fallback、条目不消失、不报错**（v1 写的「与阶段 A 完全一致」是错的：没写 group 的非 feedback 条目在 B 之后必然从 name+description 变成只剩 name，这正是 B 的目的） |
| 可解释 | `hub memory-explain` 的预测形状 == 新开一场会话实际看到的索引；且能解释 scope miss |
| 归档 | 归档一条后：它从 L0 展开层消失、进「已归档」组，但 `hub memory-read` 仍读得到、正文一字未改、git 里只有 frontmatter 一行 diff |
| 巡检 | `hub memory-audit` 只列不改——跑完 `git -C ~/treasury-vault status` 必须为空 |
| 阶段 D | 见 §5.3 五条 |

---

## 8. 执行顺序

```
定基线(§6) → A(渲染瘦身 + 修 inventory 两处) → 提交
           → B(一等字段 + 折叠 + 归档维度 + 哈希版本化 + 抽分类函数) + C(memory-explain + memory-audit) → 提交
           → D(Claude 侧 promote → 关开关；Codex 侧验证)
```

A 可以立刻做完并提交，它不依赖任何未决问题。

---

## 9. 仍然开着的问题

- `metadata.index: expanded` 的例外清单，第一版放哪几条（§3.2 列了 4 个候选，需要过一遍全部 67 条才能定）。
- 组名的最终切法——要写成触发条件，具体几组、叫什么，等 A 做完看着真实数据定。
- **归档组在 L0 里留名字还是只留计数。** plan 现在写的是「只列名」，更省的做法是只留一行「已归档（K）· 用 `hub memory-audit --archived` 查看」，代价是名字从浏览路径上彻底消失。等真实归档条数上来再定。
- **首批归档谁**。§3.5 那 8 条进度指针里，`project_code_jump_tags_070`（已 shipped）是明确的；其余几条都还挂着开口项，要一条条看，不能按 description 里的完成态词一刀切。
- **`hub memory-audit` 的两个阈值**（久未更新 90 天 / 归档已久 180 天）是拍的，跑一轮真实数据再定。

---

## 10. 评审记录（codex，2026-08-31，read-only）

| # | v1 的判断 | 评审结论 | 处置 |
|---|---|---|---|
| 一 | group/status（后改名 archived）留 `extra_metadata` 搭车，怕 68 个 diff | **推翻**：渲染路径不调 `dump_memory`；dump 对 None 不输出就零 diff。为想象的代价换真实的弱类型风险 | 采纳，改一等字段 + 强校验（§3.1） |
| 二 | 哈希扩容一次性吃下 stale | 部分修正：stale 直接吃，但**版本前缀要加**，用途是正确失效和可诊断 | 采纳（§3.3） |
| 三 | feedback 展开 / 其余折叠 | 体积没问题（估 18 条约 3002 B + 名字约 1669 B，6 KB 可达）；但 **type 是内容类别不是注入优先级**，需要正交 override | 采纳，加 `metadata.index`（§3.2） |
| 四 | 不删原生库、只停新增 | 不过头，首轮就该这样。但 **Codex 侧早已 `memories = false`**，D 在那边是验证不是关闭 | 采纳，已实测确认配置（§1.2、§5.2） |

评审另外抓到的，全部已并入正文：

- **`inventory._view_has_memory` 阶段 A 必断**（我列为「待核实」，核实结果：确实会断，靠 `[name]` / 反引号定界）
- `_view_hash_state` 找不到哈希时返回 `ok`，是个兜底洞
- `status_report.py` 对 Codex 块只验良构不验版本
- `memory-explain` 若基于 `entries_for_tool` 就解释不了 scope miss
- 字节数必须对真实渲染串算，不许另写估算式
- `schema_md.py` 的 SCHEMA_MD 仍宣称只判旧字段
- 四处判定要抽共享分类函数
- **claude 视图实际 67 条不是 68**，计数必须 scope 过滤后动态算
- A 的实测投影约 11 411 B，离 11 500 只剩约 89 B 余量
- Claude 侧开关确有其物：`autoMemoryEnabled: false` / `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- plan 自相矛盾：§3 的向后兼容口径 vs §7 的「与 A 完全一致」

我自己复核过的三条事实：`[features] memories = false` 属实；claude 视图 67 条 / shared 68 个文件属实；`_view_has_memory` 的定界符匹配属实。
