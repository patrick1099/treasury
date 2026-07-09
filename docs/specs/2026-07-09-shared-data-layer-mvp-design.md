# 跨工具/设备 共享数据层（hub）— MVP 设计

- 日期：2026-07-09
- 状态：设计已定，待写实施计划
- 归属：`ai-cli-migrate` 的演进（hub 吸收 migrate；见 §9）
- 范围：**项目一 · MVP**（规则 + 记忆）。项目二（agent 协作层）明确排队，单独立 spec（见 §10）

---

## 0. 一句话

让 Claude Code、Codex 在多台设备间**共享一份"耐久整理层"（规则 + 记忆）**：换工具、换设备时，新 agent 不再重学项目规则和踩过的坑。底层是一个**离线优先、对等、git 版本化的金库（vault）**，每台设备都是完整处理节点，NAS 只是一个方便的公共 remote。

## 1. 背景与真实痛点

- 现状：`AGENTS.md`（Codex 读）与 `CLAUDE.md`/Claude memory **此刻就在重复**编码同一批规则（CP936 编码、受保护源文件补丁流程、威星 C 规范、Keil）。换个工具就重踩。
- 每个工具的记忆是私有且孤立的：Claude 记忆按工程存在 `~/.claude/projects/<编码路径>/memory/`（**无用户级全局记忆**）；Codex 在 `~/.codex/memories/`（用户级全局）。生命周期、位置、粒度都不同。
- 已有基础：`ai-cli-migrate` 已掌握全部存储位置、会 SQLite 安全快照、会 path/user remap、会动 plugin json。本设计**复用其内脏**。
- 本设计**吸收并取代** `ai-cli-migrate/TODO.md` 里"`_global_memory/` + `memory_seed.py`"旧方案（旧方案只有 `global` 一档，没有设备/链接维度）。

## 2. 已锁定的架构决策（不重开）

1. **分层同步**：耐久层（规则/记忆/skill）版本化共享；对话记录=单向 append 归档（**不在 MVP**）；凭证/cache=**永不出设备**。
2. **三层解耦**（git 只活在最外层，随时可换）：
   ```
   工具落地层 Materializer  —— 写进 ~/.claude、~/.codex、AGENTS.md/CLAUDE.md，完全不知道 git
   金库逻辑层 Vault logic   —— scope 过滤、链接解析、去重、派生索引；只认"金库是一棵有 schema 的目录树"
   同步后端层 Backend       —— 怎么把这棵树取到本机/发回去；3 个动词 acquire / publish / status
   ```
   金库契约 = **一棵有固定 schema 的目录树**。上层逻辑从不调 `git`；换后端=换一个实现类，逻辑层一行不改。
3. **后端**：MVP 实现 **git 后端**（版本历史/回滚/合并全白送）；`mount` 后端（NAS 映射网络盘 + 各设备写自己文件夹 + 定时合并）作为后插选项保留，不在 MVP。
4. **拓扑：离线优先 · 对等树**（不是 NAS 星型）。处理逻辑随工具装在**每台设备**上，在本地 clone 就地跑完；NAS 上不跑任何逻辑，只存 git 裸仓。谁都能当"主机"。断网可无限期本地工作。
5. **MVP 范围 = 规则 + 记忆**。skill 分发紧随（fast-follow，不在 MVP 核心）；plugin 分发 / 对话归档 / 对话沉淀=排队。

## 3. 金库结构（schema）

NAS（或任意 git 主机）上一个 **git 裸仓**，各设备 clone：

```
vault/
├─ rules/                    规则权威源，拆成小主题文件（见 §7 免冲突）
│   ├─ encoding-cp936.md
│   ├─ protected-source-files.md
│   ├─ c-coding-standard.md
│   └─ ...
├─ memory/
│   └─ <slug>.md             一条一事，frontmatter 带 scope + portable
├─ devices/
│   └─ <host>.toml           每台设备档案：class、订阅 project、路径映射表
└─ vault.toml                工具落地目标、scope 分类表、版本
```

`MEMORY.md` **不进金库、不手工维护**——它是派生物，落地时从各 `memory/*.md` 的 frontmatter 自动重生成（见 §7）。

## 4. 数据模型

### 4.1 记忆 frontmatter（在现有格式上加两个字段）

```yaml
---
name: project_encoding_workflow
description: <一行摘要，用于召回相关性判断>
metadata:
  type: project | reference | feedback | user      # 沿用现有
  scope: [global]                                    # 新增：作用域谓词列表，见 §4.3
  portable: true | false                             # 新增：引用设备本地路径? 只在能解析处落地，见 §6
  sensitive: true | false                            # 新增：敏感? 为真则绝不 collect/入金库，见 §6
---
<正文；[[slug]] 链接金库内其他记忆；外部引用用符号根 $VAULT/$SECRETS/$CLAUDE_HOME/…>
```

### 4.2 设备档案 `devices/<host>.toml`

```toml
class    = ["work"]                 # 驱动 device:* 订阅（如公司机=work，家里机=home）
projects = ["xinao", "cjt"]         # 驱动 project:* 订阅

[paths]                             # 符号根 -> 本设备真实路径（复用 remap 机器）
VAULT       = "Z:/vault"
CLAUDE_HOME = "C:/Users/huawei/.claude"
SECRETS     = "C:/Users/huawei/.claude/secrets"
```

### 4.3 scope 分类表（小而封闭）

| scope | 含义 | 落到哪些设备/工具 |
|-------|------|------------------|
| `global` | 人人都要 | 所有设备、所有工具 |
| `device:<class>` | 某类设备专属 | 档案 `class` 含该值的设备（如 `device:work`）|
| `project:<id>` | 某工程专属 | 档案 `projects` 含该 id、或当前打开该工程时 |
| `tool:<claude\|codex>` | 工具专属 | 仅落地给该工具 |

**语义（消除歧义）**：`scope` 是谓词列表，按维度分组——`device:*` / `project:*` / `tool:*` 三个维度，外加特殊令牌 `global`。

- **同维度多值 = OR**：`[device:work, device:home]` = 设备类 ∈ {work, home}。
- **不同维度之间 = AND**：`[project:xinao, tool:claude]` = 「工程==xinao **且** 工具==claude」。→ 故 Claude 专属记忆**不会漏给 Codex**。
- **某维度缺省 = 该维度不限**：只写 `[tool:claude]` = 任意设备、任意工程，但仅 Claude。
- **`global` 必须单独出现**：等价"三维度全不限"；与任何 `device/project/tool` 谓词混用 = **linter 报错**。
- **匹配判定**：目标 =（设备类集合, 当前工程, 工具）。一条记忆落到目标 ⇔ 对 scope 中**出现的每个维度**，目标在该维度的值命中 scope 该维度取值集合之一（缺省维度恒通过）。

## 5. 解决疑惑点①：设备相关性

> "公司电脑的 vscode 编码规范，其他设备用不上，怎么处理？"

→ 给它打 `scope: [device:work]`。每台机的 `devices/<host>.toml` 声明自己的 `class`。`pull`/materialize 时按订阅过滤：家里机档案不含 `work` → **那条根本不落地**。

## 6. 解决疑惑点②：索引链接跨设备

> "记忆可能带索引链接，文件不在 NAS 上，就成了设备专属，怎么办？"

**铁律：记忆正文永不写裸绝对路径**（如 `C:\Users\huawei\...`）。只允许两种引用：
- `[[slug]]` —— 指向金库内其他记忆（现已在用）；
- **符号根** —— 外部资源：`$VAULT/...`、`$SECRETS/INDEX.md`、`$CLAUDE_HOME/...`。

**linter**（`hub process` 的一步）扫出裸绝对路径，逼三选一：
- (a) 该 travel 的 → 把被引文件也收进金库，引用改 `$VAULT/...`；
- (b) 天生设备本地的 → 标 `portable:false` + `scope:[device:<class>]`，只在有那路径的机器落地；
- (c) 其余 → 改写成符号根。

**落地时**，符号根用该设备档案 `[paths]` 表展开成真实路径（**复用 ai-cli-migrate 的 remap 实现**）。某设备未定义某符号根 → 那条**跳过并告警**，不产生断链。

**两个正交的轴（别混）**：
- `portable`：只关乎**路径**。`false` = 引用了设备本地路径；**可进金库**，但仅在能解析出路径的设备落地，别处跳过。
- `sensitive`：只关乎**保密**。`true` = 含凭证/私密，**绝不 collect、绝不进金库**（连 push 都拦），与 `~/.claude/secrets/` 同级对待。

两轴独立：可以 `portable:false` 且 `sensitive:false`（能进金库、只是路径设备相关），也可以 `sensitive:true`（压根不进金库）。§11 的"绝不出金库"专指 `sensitive:true`。

## 7. 免冲突结构（让"每台都能改 + 增量合并"天然无冲突）

git 按**文件**合并，所以让设备之间尽量不碰同一文件：

1. **记忆一条一文件**（现已如此）→ 两台设备各加各的记忆 = 不同文件 = **零冲突**。
2. **规则拆成小主题文件**（§3 `rules/`）→ 并发改同一份的概率骤降。
3. **`MEMORY.md` 派生化**：不手工维护、不进金库、不参与合并；每次 `process` 从各 `memory/*.md` frontmatter **自动重生成**。派生物 → **永不冲突**。（根治当前手工 MEMORY.md 在多设备下必冲突的问题。）

## 8. 命令与数据流

三层后端接口：`acquire`（取最新）/ `publish`（发出改动）/ `status`。git 后端 = pull / commit+push / status。

```
hub collect   扫本机工具目录，捞出新/改的规则与记忆         ┐
hub process   scope 打标 + link linter + 去重 + 重生成索引    ├─ 全程离线，只动本地 clone
              （本地 git commit 积累）                        ┘
hub sync      有网时：acquire(pull)+合并 → publish(push)      ← 唯一需要网络的一步
hub pull      取金库 → scope 过滤 → 符号根解析 → materialize 到本机各工具
hub status    本机 vs 金库差异、将落地什么
hub bootstrap 新机首次落地（被吸收的"迁移"场景，见 §9）
```

### 8.1 collect 源映射与回环防护

**collect 只收「记忆」，不收「规则」**——规则只在金库 `rules/*.md` 里手写。`AGENTS.md`、`CLAUDE.md`、Claude 的 `memory-index.md` 全是**派生物**，**永不 collect**（否则"刚生成又被收回金库"成回环）。

| 工具 | 记忆源（collect 只扫这里） | 规则 |
|------|-----------------------------|------|
| Claude Code | `~/.claude/projects/*/memory/*.md`（**排除** hub 生成的 memory-index 与 `~/.claude/hub/`）| 派生物，不 collect |
| Codex | `~/.codex/memories/*` | 派生物，不 collect |

**managed block vs 原子文件**（别误读）：
- **聚合/派生文件**（`AGENTS.md`、`CLAUDE.md`、`memory-index`）里 hub 负责的内容包在 `<!-- hub:begin -->…<!-- hub:end -->` 之间——materialize 只重写 block 内，block 外用户手写内容绝不碰。
- **单条 `memory/*.md` 是原子文件**——collect/materialize 以**整文件**为单位处理，本身不需要 block。
- `sensitive:true` 的记忆即便出现在源目录也**跳过不收**。

### 8.2 materialize 目标（`pull` 落地到哪）

- **规则** → 金库 `rules/*.md` 合成 `AGENTS.md`（权威单一源）；`CLAUDE.md` 只写 `@AGENTS.md` 导入 + 少量 Claude 专属。（`@import` 在 Windows 比 symlink 稳。）
- **记忆 · Codex**：`~/.codex/memories/` 是**用户级（跨工程可见）**，故只落 `global` / `device:*` / `tool:codex` 记忆；**`project:<id>` 记忆不进 `~/.codex/memories/`**，改写进目标工程 `<root>/AGENTS.md` 的 hub-managed 块（AGENTS.md 目录感知，Codex 仅在该工程读到 → 不跨工程泄漏）。
- **记忆 · Claude**（解决"global 记忆往 Claude 哪落"的开口点）：Claude 无用户级记忆，但 `~/.claude/CLAUDE.md` 每会话必读且支持 `@import`。故：
  - `global` / `device:*` / `tool:claude` 记忆 → 生成一个 bundle `$CLAUDE_HOME/hub/memory-index.md`，并确保 `~/.claude/CLAUDE.md` 含 `@hub/memory-index.md` → 每个 Claude 会话全局可见；
  - `project:<id>` 记忆 → 当本机登记了该工程时（§8.3），落进对应 `~/.claude/projects/<编码路径>/memory/`（编码复用 migrate 的 `encode_project_path`）。

### 8.3 落地目标登记（规则/工程记忆写去哪）

Codex 的 `AGENTS.md` 是**目录/工程感知**的，故 `hub pull` 不能瞎写。落地目标在 `devices/<host>.toml` 显式登记：

```toml
[[targets]]                # 每个已登记工程一条
project = "xinao"
root    = "C:/Users/huawei/Desktop/MyProjects/20260525-xinao/Code"

[[targets]]
project = "cjt"
root    = "C:/Users/huawei/plugins-dev/cjt"
```

`hub pull` 落地范围：
- **用户级**（`global`/`device:*`/`tool:*` 记忆、Codex `~/.codex/memories/`、`~/.claude/CLAUDE.md` 的 memory-index 导入）→ 落一次。
- **每个 target**：写 `<root>/AGENTS.md`（rules 派生 **+ 该工程 `project:<id>` 记忆的 managed 块，供 Codex**）+ `<root>/CLAUDE.md`（`@AGENTS.md` + 该工程 scope 记忆）+ 把 `project:<id>` 记忆落进对应 Claude 工程 memory 目录。
- `hub pull --here`：只对**当前目录**落地（临时用，不改登记表）。

## 9. 与 migrate 的关系（吸收）

- **hub 是产品**；`ai-cli-migrate` 的内脏（存储位置知识、SQLite 安全快照、path/user remap、plugin-json 手术）降级为 hub 的底层工具箱。
- "搬到新电脑" = `hub bootstrap`（首次在一台新 spoke 落地）+ 离线 zip 兜底（NAS 够不到时的传输）。
- **对话的"活态恢复"**（带 remap + mtime 修复 + sqlite 一致性）仍归 migrate 能力，MVP 不涉及，作为 `bootstrap`/离线路径的一部分保留。
- **包结构（现在拍定，不拖到实现期）**：新增 `hub/` 包，把 `claude_migrate.py` / `codex_migrate.py` 的可复用内脏当**库 import**（它们已是模块）。`migrate.py` 作为薄壳保留、向后兼容（等价 `hub migrate`）。`hub bootstrap` 直接调这些库，不重写 migrate 逻辑。即 **hub 包 + migrate 降为其一个子命令/薄入口**。

## 10. 明确不在 MVP（排队）

- **项目二 · agent 协作层**：Codex ↔ Claude Code 经中间层协作（coach/executor、受控通道、阻塞/异步 mailbox）。单独立 spec。注意：Codex 缺异步 mailbox 原语，且其价值今天不写代码即可近似获得（两终端互贴 plan）。
- skill / plugin 分发（fast-follow，紧随 MVP）。
- 对话归档（单向 append 到金库）与对话沉淀（对话→skill、思考→图纸、项目图纸增量更新）。
- `mount` 后端（网络盘 + 定时合并）。

## 11. 错误处理与安全

- 符号根未定义 → 跳过该条 + 告警，不断链、不写坏文件。
- `sensitive:true` → 绝不 collect / 入金库（连 push 都拦）；`portable:false` 且本机无法解析其路径 → 可在金库、但本机跳过落地。两者是不同的轴（§6）。
- **`hub sync` 遇 git 冲突**：立即**停止**，打印冲突文件路径，**禁止 materialize**，提示用户手工解决后 `hub sync --continue` 再继续。不自造合并引擎（理论上冲突仅可能落在 `rules/*` 同文件并发）。
- 落地前对目标文件备份（复用 migrate 的"导入前自动备份"）；managed block **外**的用户内容绝不覆盖。
- Windows 写 JSON/被严格解析的文件用 UTF-8 **无 BOM**（migrate TODO bug #7 教训）。

## 12. 测试策略

- **纯逻辑层可测**（无网络、无真实工具目录）：scope 过滤、link linter、符号根解析、MEMORY.md 重生成、collect 源解析——喂假金库树 + 假设备档案，断言输出。
- **后端接口 mock**：用 fake backend（本地临时目录当"远端"）验证 acquire/publish/status 与 pull/sync 流程，不碰真 NAS。
- **materialize 走临时 HOME**：指向临时目录当 `~/.claude`、`~/.codex`，断言落地文件内容与路径解析。
- 复用 ai-cli-migrate 现有 pytest 骨架。

## 13. 开放问题（实现期决）

1. `hub push` 的"改动分类"：本机新记忆默认 scope 如何推断（交互确认 / 规则推断 / 一律 draft 待人工打标）。
2. 新工程如何进 `[[targets]]` 登记（§8.3 已定结构）：手动填 vs `collect` 时自动侦测并提示。

## 14. 依赖与运行环境

- **纯标准库，无第三方依赖**（沿用个人 AI-python 约定；Windows 用 `py -3`）。
- **TOML 读取用 `tomllib` → 要求 Python ≥ 3.11**。实施计划第一步先确认本机 `py -3` 版本；低于 3.11 则内置一个极小 TOML 子集读取器（或退化用 `.ini`）。只读不写 TOML。
- **YAML frontmatter 限定为极小子集**，自己解析、不引 PyYAML：仅 `key: value`、一层嵌套（`metadata:` 下缩进）、内联列表 `[a, b]`。超出子集 → linter 报错要求收敛；金库内所有记忆 frontmatter 必须落在此子集。
