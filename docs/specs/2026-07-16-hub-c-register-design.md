# 设计：hub C 阶段 —— 注册器 + 薄适配器 + 状态检查器

- 日期：2026-07-16 起草；**2026-07-17 v4 校准**（见 §9）
- 状态：v4 校准完成，待进 writing-plans 产出 Plan 2（memory 视图）；Plan 1（skill 活链）已实现并合并本地 main
- 关联：[NEEDS](../NEEDS.md)、[平台机制说明书](../平台机制/README.md)、`hub/schema_md.py`（契约正文，仓库无独立受版本控制的 SCHEMA.md）
- 修订史：v1 拷贝式加载器 → v2 补闭环/契约 → v3 剪掉 copy 兜底配套复杂度 → **v4 memory 视图落地决定 + scope 契约升 v2 + Plan 1 边界加固（§9）**

## 1. 目标与定位

首要需求（NEEDS）：**我一个人、多台机器、同时用 Claude / Codex（将来 opencode），一处放的东西各工具都能
发现并用，本地改一处到处新，改动能回源。** 次级：别人从市场装。

**C = 注册器 + 薄适配器 + 状态检查器。** 能活链的活链、一处真源；每机注册一次薄入口。

### 已核实的机制底座（官方文档为据，见说明书）

- **skill 可活链**：Claude 跟随 `~/.claude/skills/` 下 skill 符号链接（实时生效）；opencode 原生读
  `~/.claude/skills` + `~/.agents/skills`；Codex 读 `~/.agents/skills`、支持 skill **文件夹**符号链接
  （**目录本身不能是链接**，issue #11314）；`openai.yaml` 可选。
- **memory 可指外部**：Claude `autoMemoryDirectory`（user/project/local/policy，project/local 需信任）、
  opencode `instructions[]`、Codex `AGENTS.md`。
- **plugin 只半共用**：注册外部本地 marketplace 但从缓存加载，改源要刷新/重装。Claude 清单 `.claude-plugin/plugin.json`，
  **Codex 原生清单 `.codex-plugin/plugin.json`（不同名）**；opencode 插件是 JS 另一套。

## 2. v3 剪枝决定（相对 v2 砍掉的东西）

| 砍掉 | 理由 |
|---|---|
| **copy 兜底模式** | skill **符号链接跟随**已由三家官方文档证实（机制层，见 §1）；剩下的**只有** Windows 目录 junction 跟随性这一条待冒烟实测（§2 前提块）。**link-only：建链失败就明确报错**，不静默拷贝（拷贝会既不备份也不回源，反违背"一处真源"）。 |
| **`hub-managed.toml`（第二份契约）** | 它只为支撑 copy 的路径跳过而存在。link-only 下 **A 只需"realpath 落进 `shared/` 就跳过"**，不需要清单。A↔C 契约维持只有 `SCHEMA.md` 一份。 |
| **通用 `hub reconcile`** | link-only 下工具改的就是共享源那**同一个物理文件**，不存在"副本 drift"，无差异可 reconcile。memory 的冲突由 `promote`（§5.4）处理。 |
| **独立 `hub bootstrap`** | 见 §4，并入 `register`。 |
| **hooks 跨平台分发、opencode 插件适配** | 按 NEEDS 本就次级/能力墙，**降出 v1**。 |

> **Windows 前提（link-only 的唯一真风险）**：Windows 建**符号链接**要管理员/开发者模式，但建**目录 junction**
> （`mklink /J`）**不需要**。skill 是目录 → **v1 用 junction**。实现前的**头号冒烟测试**：本机各工具是否**跟随 junction**。
> **门槛（NEEDS v1 首要 = Claude + Codex）**：这两家都跟随 = link-only 成立、进实现；哪家不跟随再具体议、不预先造 copy。
> **opencode 只记录、不阻断**（NEEDS 里是次级/未来）。

## 3. 内容闭环（shared 现在是空的）

金库 `shared/` 现为 0，内容全在设备备份区。完整闭环：

```
   本机工具产出 ──A collect──▶ <设备>备份区 ──hub promote(人工挑,复制)──▶ shared/
                                                                        │
   各平台 ◀── hub register(建链/写指针/注册市场) ◀────────────────────────┘
```

**skill/hook 脚本**：活链，工具里改 = 改共享源，回源即时、无副本。
**memory**：不活链，走"collect → promote → 只读视图"（§5.4）。

## 4. 命令（C 新增 + A 既有）

| 命令 | 归属 | 作用 |
|---|---|---|
| `hub promote` | C（新） | 设备备份区 → `shared/`：选择 → 校验 → **复制**；同名不同内容**立即停下问**，绝不移入/静默覆盖。**首次**用它把现有 Claude/Codex skill + memory 提升进 shared |
| `hub register` | C（新） | 每机一次、幂等：**安装 hub 自带的 `hub-memory` skill** + 逐个建 skill junction + 写 memory 视图与受管块指针 + 注册插件市场/启用。**吸收原 bootstrap** |
| `hub refresh` | C（新） | 刷新缓存型插件（Claude 重装 / Codex cachebuster）+ 重算 memory 视图。skill 是活链不用刷 |
| `hub status` | **合并成一个** | 金库 git 状态 + A 数据源状态 + C 链接/注册/缓存/hook 脚本哈希状态 |
| `hub collect` | A（小改） | 提取本机 → 备份区；**新增：realpath 落进 `shared/` 就跳过**（§6） |
| `hub sync` | A（旧） | 不变 |
| ~~`hub bootstrap`~~ | 废/别名 | 并入 `register`；保留成兼容别名即可（见 §4.1） |

### 4.1 register 吸收 bootstrap（修 v2 生命周期跑不通）

v2 的问题：原 `bootstrap` 要求 `shared/skills/` 里已有 `hub-*` 加载器，但 shared 是空的、也没有那个 skill → 新机跑不通。

**修法**：`hub-memory` skill **随 hub 包一起发**（在 `hub/skills/hub-memory/`），不依赖金库里预先存在。`hub register`
一次完成：装 `hub-memory` skill、建 skill junction、写 memory 视图 + 受管块、注册插件。**没有鸡生蛋**（hub 在的机器上
这把 skill 就在），bootstrap 不再需要。

**新机生命周期**：
```
git clone 金库 → hub-scaffold <金库> <本机名> → 编辑 device.toml 填真实路径
→ hub register → hub status
```
（`hub promote` 是内容创作动作，在产出内容那台机做，非换机固定步骤。）

## 5. 四条流水线

### 5.1 skill —— link-only 活链

- **opencode**：零动作（原生读 `~/.claude/skills` + `~/.agents/skills`）。
- **Claude**：`register` 在 `~/.claude/skills/<n>` 逐个建 junction → `$VAULT/shared/skills/<n>`。
- **Codex**：`register` 在 `~/.agents/skills/<n>` 逐个建 junction（**`~/.agents/skills` 本身是真目录**）。`openai.yaml` 可选。
- **建链失败**（如平台不跟随 junction）→ **明确报错并指名**，不静默拷贝。由 §2 的冒烟测试提前暴露。
- A 侧：realpath 落进 `shared/` → 跳过，不重复备份（§6）。

### 5.2 plugin —— 各仓自持平台清单，C 只恢复/注册/启用/刷新

- 活源 = 各自独立 git 仓 `plugins-dev`。**不存在 `shared/plugins`**，不套单一共享源。
- **平台清单归插件仓自己维护**：Claude 用 `.claude-plugin/plugin.json`，要 Codex 原生就再加 `.codex-plugin/plugin.json`。
  **hub 不自动合成双清单**——那是插件作者（你）的活。
- hub 存：仓库声明 + SHA + 灾备快照（A 已做）。**C v1**：换机 clone/恢复 → 注册市场（Claude `enabledPlugins`；
  Codex `codex plugin add`）→ 启用 → `hub refresh` 刷新缓存。改 `settings.json`/`*.json` 走 Writer + 先备份、**UTF-8 无 BOM**。
- opencode 插件本体搬不过去；其**内的 skill** 走 §5.1。**opencode 插件适配 v1 不做。**

### 5.3 hook —— v1 降级

逻辑脚本可共放 `shared/hooks/`（与 SCHEMA 命名一致），但**跨平台 hook 注册 v1 不做**（事件不一一对应、能力墙）。
`hub status` 仍报告 `shared/hooks/` 脚本哈希漂移，供以后接。compact-plus 这类保持 Claude-only。

### 5.4 memory —— 上行收集提升，下行只读视图（落点已定死）

**上行**：`autoMemoryDirectory` → 本地工作目录 → `A collect` → `<设备>/claude/memory/` → `hub promote` 人工审 → `shared/memory/`。
**绝不**把 `autoMemoryDirectory` 直连 `shared/memory`。

**下行——生成 shared-only、按 scope 过滤的只读视图**：

- **落点（定死，不留实现期）**：**`~/.hub/views/<tool>/MEMORY.md`**。本机派生物，**不进金库、A 不收集**（从源头断环）。
- **内容**：只取 `shared/memory/`（已人工闸门），按本机 `device.toml` 的 `class`/`projects` + 目标 `tool` 做 scope 过滤；
  **绝不纳入设备区未审记忆**。符号根在此展开成真实路径。
- **谁写/刷新**：`hub register` 首建、`hub sync`/`refresh` 在 shared 变化后重算。
- **各平台指针（`register` 维护"受管块"，幂等、保留用户原有内容）**：
  - **Claude**：`~/.claude/CLAUDE.md` 里一段 `# hub:begin … # hub:end` 受管块，内含 `@~/.hub/views/claude/MEMORY.md`。
  - **Codex**：`~/.codex/AGENTS.md` 同样的 `hub:begin/end` 受管块，指 `~/.hub/views/codex/MEMORY.md` + `hub-memory` skill。
  - **opencode**：`opencode.json` 的 `instructions[]` 幂等加入 `~/.hub/views/opencode/MEMORY.md`（JSON 数组增改，非文本块）。
- 正文按需读由 `hub-memory` skill 负责（读金库、展开符号根）。**薄索引自动加载 + skill 读正文，两者同用。**

## 6. A 的配套改动（极小）

**只加一条**：collect 提取每项前解析 realpath，**落进 `shared/` 就跳过**（堵住
`shared/skills → junction 进 skills 目录 → A 再提取 → 设备区` 的环）。加**遍历链接的循环防御**。其余提取行为不变。

- 不需要 `hub-managed.toml`（link-only 下 realpath 规则自足）。
- 测试：realpath∈shared 跳过 + 未受管照旧 + 环防御 + junction/symlink 各形态。

## 7. 待定（已很少）

1. **junction 跟随性** —— 实现前冒烟测试（§2）。**门槛只认 Claude + Codex**（都跟随才进实现）；opencode 只记录、不阻断。
2. **多机 sync 真机验证** —— 只有一台机，从未真跑。

## 8. 安全与诚实边界

- guard 密钥闸、单 `Writer`、dry-run 全程复用。
- `opencode.json` 等配置可能含明文密钥（本机实测有）→ 归 guard，不进金库明文区。register 改用户文件
  （CLAUDE.md/AGENTS.md 受管块、opencode.json）一律先备份、幂等、保留用户内容。
- **本会话未真机验证**：Claude/Codex junction 冒烟已通过（Task 0，用户手动）；opencode 因
  `~/.config/opencode` EEXIST 非阻断跳过；临时 junction 已清。仍未验证：`autoMemoryDirectory`
  读写、多机 sync。实现前/中要真机确认。

## 9. v4 校准（2026-07-17，进 Plan 2 前定稿）

两轮 brainstorming 校准的结论。**Plan 2 = memory 视图下行**，但前置一个 **Task 0 = Plan 1 边界加固**，先于任何 memory 功能。

### 9.0 Task 0 —— Plan 1 边界加固（先做）

Plan 1 合并后同事复查查出两个代码边界洞，必须先补：

1. **`shared/skills` 容器逃逸**：`promote_skill` 只查叶子 `shared/skills/<name>` 是不是链接，没查容器 `shared/skills` 本身。若 `vault/shared/skills → 金库外`，promote 会落盘到金库外、register 会枚举金库外目录建链、status 还报 `ok`。抽 `shared_skills_dir(vault_root)`：断言 `realpath(shared/skills) == realpath(vault_root)/shared/skills`（允许 `vault_root` 整体经链接访问），**且**枚举出的每个 `<name>` 解析后仍落在 `shared/skills` 内（register/status 用 `iterdir` 把 `<name>` 当源，会跟随链接）。promote/register/status 三处共用。
2. **工具 `skills` 容器是链接时假成功**：register 预检只查叶子 `target_dir/<name>`，不查容器 `~/.claude/skills`、`~/.agents/skills` 本身。若容器整个是 junction/symlink/文件/坏链，`make_dir_link` 照样在里面建链、report `ok`——违反"容器必须真目录、只有 `<name>` 可 junction"（Codex issue #11314）。register 预检每个目标容器：不存在→允许 Writer 建真目录；真目录→放行；symlink/junction/文件/坏链→`RegisterConflict` 且**零写入**；status 不报 `ok`。

测试须证：金库外/工具外**零写入**、`Writer.written == []`、status 不出假 `ok`。

### 9.1 scope 契约升 v2（A↔C 接口，改 `hub/schema_md.py`）

**语法**：`global` / `class:<名>` / `project:<名>` / `tool:<claude|codex|opencode>`。

**语义**（相对现契约的**破坏性**变化，故升版本）：
- `global` / `class:` / `project:` 同属**设备订阅维度**，维度内 **OR**；`tool:` 是独立维度，维度内 **OR**；两维之间 **AND**；某维度无标签 = 该维度匹配全部。
- `global` **必须独占**（不与任何标签混用，混则非法）。`[tool:claude]` 本身即"所有设备、仅 Claude"，无需也不许写 `[global, tool:claude]`。
- **相对 v1 的翻转**：现契约里 `device:` 与 `project:` 是**两个不同维度→AND**；v2 把 `class`（原 `device`，改名对齐 `device.toml` 的 `class` 数组）与 `project` 收进**同一设备维度→OR**。
- `project:xinao` 是**设备订阅条件**（本机 `device.toml` 的 `projects` 含 `xinao` 才纳入），**不是**"仅在 xinao 工程会话可见"——视图是**用户级全局视图**。
- **异常即停**：未知前缀 / 空值 / 未知 tool / 空 scope → 校验错误；覆盖任何视图/配置前**全量预检**，报出记忆文件名 + 非法标签，本次 register/refresh 失败、旧产物原封不动（挡 `projet:xinao` 手误让记忆静默蒸发）。

**匹配器归位**：`scope.py` 的旧 docstring "匹配不在这里，因为 C 不是 Python" 已作废（v3 把 register/refresh 做成 hub CLI 命令，C 就是 Python）。新增 `scope_matches(dims, device_classes, device_projects, tool)`，修正 docstring。

**版本迁移**：`vault.toml` `version` 1→2。新增 `hub migrate-schema --to 2`：先扫全部 scope，**全为 `global` 才升版本**；遇旧 `device:` 谓词 / 任何非 global 数据 → 列清单**拒绝**，要用户手工迁移后重试。`hub-scaffold` 只负责新库（写 `version = 2`），**不是**迁移工具。

### 9.2 promote_memory（`hub/promote.py`）

- 接口：`hub promote-memory --vault <v> --host <h> --name <slug>` 或 `--all`；`--name`/`--all` **互斥必选其一**。无 `--tool`（记忆上游恒为 `<host>/claude/memory/`）、无 `--scope`、无 `--force`。
- 冲突七态：目标不存在→复制；普通文件内容相同→no-op（算已提升）；文件内容不同→`PromoteMemoryConflict`；目标是目录/symlink/junction/坏链→冲突；源 frontmatter/scope 非法→校验失败；`shared/memory` 或源路径链接逃逸→校验失败；源不存在→`FileNotFoundError`。
- `--all` = 批量 promote，**非 mirror**（绝不删源端已无的）；全量预检（枚举→校验→分类 copy/no-op/conflict→任一失败零写入报全清单→全过才复制）；`--dry-run` 同预检只打印。

### 9.3 视图渲染核心（新 `hub/memview.py`）

单次扫描+过滤+校验产出一批 `MemoryViewEntry`（name/description/scope/绝对源路径），再分渲染成三种产物，**同一批数据、绝不各扫各的**：
- **视图文件** `~/.hub/views/<tool>/MEMORY.md`：薄索引，绝对源路径，Markdown 目标用 `<...>`（空格安全）、`/` 分隔。**只把金库相对地址变本机绝对地址，不展开正文符号根、不碰 canonical。**
- **Codex `AGENTS.md` 受管块**：**内联紧凑索引**（仅 name/description/scope，无绝对路径），加一句"正文用 `$hub-memory` skill 按名读"。Codex 无 `@import`，靠内联达成自动发现；`~/.codex/AGENTS.md` 仅 Codex 读、无跨工具泄漏。
- **opencode `instructions[]`**：加视图路径（见 §9.6）。

空结果保留产物 + 占位（"当前设备/该工具无匹配共享记忆"），避免旧索引残留。

### 9.4 hub-memory skill（新 `hub/skills/hub-memory/`，随 hub 包发）

- 构成：`SKILL.md` + `scripts/read_memory.py`（stdlib，`py -3`）。可执行入口 = CLI `hub memory-read --tool <claude|codex|opencode> --name <n>`；脚本只做**稳定启动包装**，核心逻辑唯一落在 hub 模块/CLI。
- 定位金库/hub：register 写 `~/.hub/config.toml`（`vault=` / `host=` / `hub_root=`）；memory-read 缺 `--vault` 时读它；脚本靠 `hub_root` 在非仓库 cwd 下找到 hub。
- **按过滤后视图查名**：memory-read 只解析在**本机该 `--tool` 视图里**的名字（拒读越 scope 记忆），读 canonical → `resolve_symbols`（内存展开）→ 打正文，不写第二份、不改 shared。
- 安装：junction `hub/skills/hub-memory` → `~/.claude/skills/hub-memory` + `~/.agents/skills/hub-memory`（link-only，源是 hub 包）。同名冲突→`RegisterConflict` 不覆盖。升级：junction 到包，`git pull` 即更新。
- **交付/新机闭环**：hub 靠 **clone `ai-cli-migrate`** 交付（`hub/skills/` 在仓库里）。`migrate.py` 迁的是各工具**数据**、不是 hub 本体，故 hub/ **不纳入** migrate.py。新机：clone 仓库 → `hub-scaffold` → 填 `device.toml` → `register`（链 hub-memory + 写 config.toml）。

### 9.5 受管块编辑器（新 `hub/textblock.py`，避开已废名 `managed_block.py`）

- 通用 `<!-- hub:begin -->…<!-- hub:end -->`：无标记→追加；一对合法→只换块内、保留块外用户文本；重复/缺半边/错序/嵌套→校验失败、任何视图和配置都不写。标题写"自动生成，勿手改"。
- 接线：Claude `~/.claude/CLAUDE.md` 放 `@<claude 视图绝对路径>`（**指针不内联**——opencode 也读 `~/.claude/CLAUDE.md`，内联会把 claude-scope 内容泄漏进 opencode；放路径行则 opencode 只见一个它忽略的字符串）；Codex 见 §9.3 内联；opencode 见 §9.6。
- **Codex override**：register 探测**活动的非空** `~/.codex/AGENTS.override.md`——存在则块写进 override（写进被遮蔽的 AGENTS.md 无效），否则写 AGENTS.md。仅碰用户级。真机确认。

### 9.6 opencode 配置写入（含明文密钥，走 guard 范畴）

- **路径**：优先 `device.toml` 的 `OPENCODE_CONFIG`，缺省 `~/.config/opencode/opencode.json`。
- **JSONC/解析失败**：能严格 `json.loads` → 手术式加 `instructions[]`（按串去重、保留其余键）+ 原子替换；遇注释/尾逗号/解析失败 → **拒改**，打印要手工添加的完整 instructions 条目。**保留未知键，但不声称保留原格式**（`json.dumps` 会重排版）。opencode 是次级目标，拒改不阻断主链路。
- **备份**：**不复制整份密钥文件**；写**最小回滚日志**到 `~/.hub/backups/`（配置路径 / 改前文件哈希 / 原 `instructions` 是缺失还是具体值 / 本次加入的条目），明确不进金库、不进 collect。原子写解截断，最小日志解语义回滚。

### 9.7 原子性与承诺（点名区分两种失败）

- Writer 新增 `write_text_atomic`（同目录 temp + flush/fsync + `os.replace`，UTF-8 无 BOM，沿用原换行）；视图/受管块/配置写都走它。**现有 A 阶段 `write_text` 不动**（缩小改动面）。
- 承诺精确：**全量预检错误 → 零写入**；**单文件写 → 不截断**（原子替换）；**跨文件提交期 I/O 故障 → 可能部分完成、不回滚，重跑 register/refresh 幂等收敛**。加"第 N 次写失败"故障注入测试。不做全量 staging。

### 9.8 sync/refresh 边界（拆清 v3 措辞）

- `sync`（A）**只动金库**（pull/lint/derive/commit/push），**绝不写工具地盘**。成功后若 `shared/` 变了，**打印提示**运行 `hub refresh`；另提供显式 `sync --refresh` 串联。
- `refresh`（C）保持**显式**：在 shared 变化后重算视图 + 受管块 + opencode 条目。skill 是活链不用刷。

### 9.9 status 闭合

`hub status` 增 `--check` 模式：查 bundled hub-memory skill 链 / `~/.hub/config.toml` 存在且一致 / 三份视图文件 / 活动受管块良构 / opencode 条目 / **新鲜度**（记录生成时 `shared/memory` 哈希，比对当前）；不健康返回**非零**。

### 9.10 文档收尾

- 本 Plan：`hub/schema_md.py` scope 章节升 v2、`hub/README.md` 记录 memory 视图与新命令。
- 同事复查遗留（Plan 1 的）：README 第 97 行"金库以外"→"备份区以外"、第 122 行 status 标 A/C；本 spec §8 的"junction 未真机验证"更新为 Claude/Codex 冒烟已通过、opencode 因 `~/.config/opencode` EEXIST 非阻断跳过。
