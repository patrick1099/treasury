# 设计：hub C 阶段 —— 注册器 + 薄适配器 + 状态检查器

- 日期：2026-07-16 起草；2026-07-17 v4 校准（见 §9）；**2026-07-20 v5 校准**（见 §10）
- 状态：Plan 1（skill 活链）、**Plan 2（memory 视图）均已实现并合并本地 main**；**v5 校准完成**（shared 稳态活源 +
  通用 induction + Plan 3 插件），**待进 writing-plans 产出 Plan 3**
- 关联：[NEEDS](../NEEDS.md)、[平台机制说明书](../平台机制/README.md)、`hub/schema_md.py`（契约正文生成器，写出金库根的 `SCHEMA.md`）
- 修订史：v1 拷贝式加载器 → v2 补闭环/契约 → v3 剪掉 copy 兜底配套复杂度 → v4 memory 视图落地 + scope 契约升 v2 +
  Plan 1 边界加固（§9）→ **v5 shared 稳态活源 + 通用 induction + Plan 3 插件（§10）**

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
| **copy 兜底模式** | skill **符号链接跟随**已由三家官方文档证实（机制层，见 §1）；Windows 目录 junction 跟随性**已冒烟通过**（Plan 1 Task 0 + Plan 2 真机，见 §7）。**link-only：建链失败就明确报错**，不静默拷贝（拷贝会既不备份也不回源，反违背"一处真源"）。 |
| **`hub-managed.toml`（第二份契约）** | 它只为支撑 copy 的路径跳过而存在。link-only 下 **A 只需"realpath 落进 `shared/` 就跳过"**，不需要清单。A↔C 契约维持只有 `SCHEMA.md` 一份。 |
| **通用 `hub reconcile`** | link-only 下工具改的就是共享源那**同一个物理文件**，不存在"副本 drift"，无差异可 reconcile。memory 的冲突由 `promote`（§5.4）处理。 |
| **独立 `hub bootstrap`** | 见 §4，并入 `register`。 |
| **hooks 跨平台分发、opencode 插件适配** | 按 NEEDS 本就次级/能力墙，**降出 v1**。 |

> **Windows 前提（link-only 的唯一真风险）**：Windows 建**符号链接**要管理员/开发者模式，但建**目录 junction**
> （`mklink /J`）**不需要**。skill 是目录 → **v1 用 junction**。实现前的**头号冒烟测试**：本机各工具是否**跟随 junction**。
> **门槛（NEEDS v1 首要 = Claude + Codex）**：这两家都跟随 = link-only 成立、进实现；哪家不跟随再具体议、不预先造 copy。
> **opencode 只记录、不阻断**（NEEDS 里是次级/未来）。

## 3. 内容闭环（shared 现在是空的）

> **v5 更新**：本节标题的"shared 现在是空的"已部分过时。**当前**：`shared/memory` 已由 Plan 2 提升填充；
> **插件仍在 `~/.claude/plugins-dev`，尚未迁入**（迁移是 Plan 3 的 §10.2 P8，未执行）。**P8 成功后** `shared/plugins`
> 才成为稳态活源、`plugins-dev` 退役。v5 的目标稳态见 **§10**；下面的闭环图仍适用于 memory/skill。

金库 `shared/` 起初为 0（**现 `shared/memory` 已由 Plan 2 提升填充；插件待 §10.2 P8 迁入**），其余内容仍在设备备份区。完整闭环：

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

### 5.2 plugin —— shared 稳态活源 + 每插件 market-of-one（v5 重写，取代旧模型）

> **v5 作废**：旧 §5.2"活源=外部 `plugins-dev`、不存在 `shared/plugins`"整体作废。稳态活源现为金库内
> `shared/plugins/<name>/`。完整契约 + 执行细节见 **§10**；此处只留与 §5.1/5.3/5.4 并列的概览。

- **活源** = `hub-vault/shared/plugins/<name>/`，每个仍是独立 git 仓（自己的 remote/history），改/commit/push
  都从这里发生。父仓跟踪其源码文件、**排除嵌套 `.git`**（通用 induction 原语，§10.1 C4）。`~/.claude/plugins-dev`
  **退役**（仅一次性迁移源）。
- **每插件 market-of-one**：平台 marketplace 描述归各插件仓自维护，身份稳定 `<name>@<name>`（目录/manifest/市场/
  平台清单名全等 `<name>`，硬预检）。
- **hub 平台文件零直写（平台变化全走官方 CLI）；hub 自有状态用原子 Writer**：`register` 注册市场 + 装 + 启用；
  `refresh` 按 cachebuster 四态重装（**用户拥有 bump，refresh 不写插件仓**）。绝不直写 cache/`installed_plugins.json`/
  `known_marketplaces.json`/`config.toml`（台账 + induction 事务记录等 hub 自有状态走 Writer，见 §10.2 P3/P6）。
- **启用态**归 `<host>/device.toml` 的 `[plugins.<tool>] enabled` 允许列表（设备×平台维度）。
- **换机 clone/恢复**（灾备快照、缺失仓 rehydrate、目录冲突）→ **Plan 3.2**，v1 不做；register 遇缺失仓报
  `needs restore` 失败/降级、绝不自动 clone。
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

1. ~~**junction 跟随性**~~ —— **已关闭**：Plan 1 Task 0 用户手动冒烟通过（Claude + Codex 跟随，opencode 非阻断），
   Plan 2 真机再确认 Claude 跟随 `~/.claude/skills`/`~/.agents/skills` 下 hub-memory junction（status `[ok]` + 新会话加载）。
2. **多机 sync 真机验证** —— 只有一台机，从未真跑（**当前唯一未验证项**）。

## 8. 安全与诚实边界

- guard 密钥闸、单 `Writer`、dry-run 全程复用。
- `opencode.json` 等配置可能含明文密钥（本机实测有）→ 归 guard，不进金库明文区。register 改用户文件
  （CLAUDE.md/AGENTS.md 受管块、opencode.json）一律先备份、幂等、保留用户内容。
- **真机验证进度**：Claude/Codex junction 冒烟已通过（Task 0，用户手动）；opencode 因
  `~/.config/opencode` EEXIST 非阻断跳过；临时 junction 已清。
  - **2026-07-20 Plan 2 真机 smoke 全绿**（host 2025-bg-016，金库 `~/hub-vault`）：migrate-schema→v2 →
    promote-memory --all（49 条）→ register → refresh → status --check 全 [ok]；register + 两次 refresh
    三次视图哈希一致（**幂等**）；CLAUDE.md 块外内容保留、旧相对 `@hub/memory-index.md` 换成新绝对
    `@…/.hub/views/claude/MEMORY.md`；`$hub-memory` 正文读取通过；**受管块绝对路径 `@import` 已真机确认被
    Claude 加载**（新会话内联视图、列出条目与 scope）；未 opt-in 的带密钥默认路径 opencode.json 全程
    sha/字节/mtime 三者未变。
  - 仍未验证：`autoMemoryDirectory` 读写、多机 sync。实现前/中要真机确认。

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

- **触发（2026-07-20 用户定稿）**：register/refresh **仅当 `device.toml` 显式设了 `OPENCODE_CONFIG`** 才接 opencode——**绝不**因默认路径 `~/.config/opencode/opencode.json`（含明文密钥）恰好存在就去写它。未显式接入的设备，opencode 完全不碰（不写、不进 `status --check`）。
- **路径**：`opencode_config_path(dev)` 仍解析 `OPENCODE_CONFIG`（缺省 `~/.config/opencode/opencode.json`）作为路径解析器，但只有上面的触发条件成立时才被调用。
- **JSONC/解析失败**：能严格 `json.loads` → 手术式加 `instructions[]`（按串去重、保留其余键）+ 原子替换；遇注释/尾逗号/解析失败 → **拒改**，打印要手工添加的完整 instructions 条目。**保留未知键，但不声称保留原格式**（`json.dumps` 会重排版）。opencode 是次级目标，拒改不阻断主链路。
- **备份**：**不复制整份密钥文件**；写**最小回滚日志**到 `~/.hub/backups/`（配置路径 / 改前文件哈希 / 原 `instructions` 是缺失还是具体值 / 本次加入的条目），明确不进金库、不进 collect。原子写解截断，最小日志解语义回滚。

### 9.7 原子性与承诺（点名区分两种失败）

- Writer 新增 `write_text_atomic`（同目录 temp + flush/fsync + `os.replace`，UTF-8 无 BOM，沿用原换行）；视图/受管块/配置写都走它。**现有 A 阶段 `write_text` 不动**（缩小改动面）。
- 承诺精确：**全量预检错误 → 零写入**；**单文件写 → 不截断**（原子替换）；**跨文件提交期 I/O 故障 → 可能部分完成、不回滚，重跑 register/refresh 幂等收敛**。加"第 N 次写失败"故障注入测试。不做全量 staging。

### 9.8 sync/refresh 边界（拆清 v3 措辞）

- `sync`（A）**只动金库**（pull/lint/derive/commit/push），**绝不写工具地盘**。成功后若 `shared/` 变了，**打印提示**运行 `hub refresh`；另提供显式 `sync --refresh` 串联。
- `refresh`（C）保持**显式**：在 shared 变化后重算视图 + 受管块 + opencode 条目。skill 是活链不用刷。
  **v5 追加**：`refresh` 还负责**插件的 cachebuster 感知重装**（每插件×平台读 HEAD sha + version 对台账四态，
  只经平台 CLI、不写插件仓，见 §10.2 P5）。memory 视图重算与插件重装是 `refresh` 的两块职责。

### 9.9 status 闭合

`hub status` 增 `--check` 模式：查 bundled hub-memory skill 链 / `~/.hub/config.toml` 存在且一致 / 三份视图文件 / 活动受管块良构 / opencode 条目 / **新鲜度**（记录生成时 `shared/memory` 哈希，比对当前）；不健康返回**非零**。

### 9.10 文档收尾

- 本 Plan：`hub/schema_md.py` scope 章节升 v2、`hub/README.md` 记录 memory 视图与新命令。
- 同事复查遗留（Plan 1 的）：README 第 97 行"金库以外"→"备份区以外"、第 122 行 status 标 A/C；本 spec §8 的"junction 未真机验证"更新为 Claude/Codex 冒烟已通过、opencode 因 `~/.config/opencode` EEXIST 非阻断跳过。

## 10. v5 校准（2026-07-20）—— shared 稳态活源 + 通用 induction + Plan 3 插件

第三轮 brainstorming 定稿。**根基纠正**：`hub-vault/shared/` 不是"快照/备份"，而是所有"项目无关、每机都同步"
的 AI 基础设施的**唯一稳态活源**——改/commit/push 都从 shared 下的真实仓发生，register/refresh 只让各平台
**指向或加载 shared**。这**整体作废** §5.2 旧模型与 §2/§3 里"不存在 shared/plugins""shared 现在是空的"的措辞。
A 阶段的 `<host>/plugins.toml` + 插件快照**降级为迁移/恢复输入**，不再是稳态真源。

**C0 vault version 2→3（破坏性契约变更）**：布局、真源、manifest 都变了，不能再叫 version 2。定死：
- `vault.toml` **version 2→3**；`hub/schema_md.py` 生成器同步写 v3 契约正文（含 shared/ 三分跟踪、通用 induction、
  `shared/plugins/manifest.toml`）到金库根 `SCHEMA.md`。
- `scaffold_vault` 新建库写 **v3**；`migrate-schema` 支持 **2→3**（P8 迁移负责本机 v2→v3）。
- **老版本命令遇 v3 应拒绝**（明确报"金库版本高于本 hub 所知，请升级 hub"），**绝不按旧插件模型静默运行**。
- SCHEMA 改动影响面大 → schema_md.py 的具体改法列为 Plan 3 的**契约任务**，本 spec 只定契约内容、不在此顺手改生成器。

### 10.1 shared/ 稳态契约（SCHEMA 级，通用；MCP/hook 复用）

- **C1** `shared/` 每机都同步这份公共真源；**同步 ≠ 每项都加载进每工具**（memory 仍按 scope 过滤，插件受平台
  兼容约束——见 device 启用列表）。
- **C2** 布局按用途，**形态不统一**：`shared/memory/<slug>.md`（文件）、`shared/{skills,plugins,mcp,hooks}/<name>/`
  （目录）。**`shared/chats/` 保留但不纳入本轮**（不删、不改）。
- **C3** 三分跟踪：**父仓（hub-vault）跟踪产物源码文件** / **排除嵌套 `.git/`**（每个 `<name>` 可选是独立仓） /
  **密钥/token/auth 永不进 shared，留本机私密区**。
- **C4 通用 induction 原语**（已实测坐实）：把带 `.git` 的产物**首次**纳入父仓跟踪。**崩溃协议顺序（严格）**：
  0. **进任何新 induction 前，先恢复未完成事务**：读事务记录，把上次中断留在暂存区的 `.git` 贴回原位、验证、清记录；
  1. **先原子落盘事务记录**（`{原路径, 暂存路径, 状态}`，`os.replace` 原子写）——**在移动 `.git` 之前**，否则崩在
     "已移出、无记录"就无从恢复；
  2. 把 `<name>/.git`（**文件或目录**皆可）移到**父仓工作树外**的暂存区；
  3. `git add <name>`（此时无 `.git`，git 把文件存成 blob 而非 gitlink）；
  4. **校验索引中 `<name>` 下无任何 `160000`（gitlink）项**——判据是"**无 160000**"，**不是"全为 100644"**
     （可执行文件是 `100755`、仓内符号链接是 `120000`，都合法）；有 160000 → 中止、恢复、报错；
  5. **finally 把 `.git` 移回原位并验证**（在 `git add` **后**、父仓 commit **前**）；
  6. **`.git` 恢复并验证成功后，才删事务记录**（早删=崩溃后无从恢复）；
  7. 父仓稍后正常 commit。
  - **为什么必须"移出"而非 gitignore**：**已初始化、有 HEAD 的嵌套仓会被父仓当作 gitlink（160000）**；`.gitignore`
    只让父仓不**遍历**嵌套仓内文件，**不会**把它从 gitlink 变成跟踪源码（实测：忽略 `.git/` 后仍记 160000）。
  - 后果：新机 clone 父仓只得**文件、无嵌套 `.git`** → 产物是文件不是仓 → 恢复要 rehydrate（§10.3/Plan 3.2）。
- **C5 containment 铁律**：**目录型产物** `shared/{skills,plugins,mcp,hooks}/<name>` 必须是**真实、位于金库内**的
  目录；symlink/junction/坏链逃逸一律**拒绝、零副作用**（复用 Plan 2 无条件 realpath 守卫，防 induction 通用化重开
  容器逃逸）。（`shared/memory/<slug>.md` 是**文件**，同样要求 realpath 落在金库内，只是不作"目录"要求。）
- **C6 manifest（按需，非每类型都有；父仓跟踪）**：**需要清单的类型各自定义 manifest**——memory 就**没有**
  （靠文件本身 + frontmatter）。本轮**只定义 `shared/plugins/manifest.toml`**。plugins 字段：`name` 必填；
  `repository` 元数据可选；**声明为独立仓才要 `remote`**，`sha` 仍可选；**`platforms = [...]`** 声明该插件面向哪些
  平台（见 P2/P3）。其它需要清单的类型复用机制、字段留各自 plan。
- **C7 rehydrate 消歧**：`.git` **缺失** → 允许按 manifest **新建 git 元数据 + 设置 remote**（这就是 rehydrate）；
  `.git` **已存在** → live remote/HEAD 与 manifest 不一致**只报 drift、不自动改 remote/不 checkout**。
  **manifest 是真源，live git 是被校验对象。**
- **C8 交付结构**：本次产物 = **本契约（§10.1，通用）** + **Plan 3（§10.2，仅插件）**。MCP/hook 复用同套机制但
  各自单独 plan、不进 Plan 3 实现；`shared/mcp` 只在契约里占位、实现另议。

### 10.2 Plan 3 —— 插件 register/refresh/status（仅插件）

**首要价值靶子（单机可真机闭环）= refresh/cachebuster**。验收：改插件 → 显式 bump+commit → `hub refresh` →
Claude/Codex 加载新版 → 再 refresh 幂等、插件仓干净、无无关改动。

- **P1 活源与市场源**：市场源**直指** `<vault>/shared/plugins/<name>`（marketplace 描述在插件仓内、条目相对路径）；
  跨机绝对路径由 `register` 按本机 `device.toml` VAULT **重建**（不照抄旧绝对路径），不设 junction 中间层。
  注意：直指 shared **≠** 原地跑源码——install 仍复制进平台 cache，故 refresh 照样调官方命令。
- **P2 每插件 market-of-one，身份 `<name>@<name>`。**
  - **平台适配的权威来源 = manifest 的 `platforms`**（不做隐式"探测"）。本机实查：现有 6 仓**只有 `.claude-plugin`**，
    **无任何 `.codex-plugin/plugin.json` 或 Codex 原生市场文件**。
  - **Codex v1 决定：走 Claude marketplace 兼容**——**2026-07-20 隔离 spike 实测**（临时 `CODEX_HOME`，未碰真
    `~/.codex`）：现 Codex CLI 能 `plugin marketplace add` + `plugin add` 一个**只含 `.claude-plugin`** 的
    market-of-one，`plugin list` 读 `.claude-plugin/marketplace.json`、安装版本取自 `.claude-plugin/plugin.json`
    （缓存落 `.../0.1.0/`），状态 `installed, enabled`。故 **v1 不要求补 `.codex-plugin`**；补 Codex 原生描述是作者
    将来选项、不进 v1——**作为显式决定写死，不留实现者静默兜底**。（注：A 快照里的 `cjt@codex` 是过时态，本机
    `codex plugin list` 现为空，不作证据。）
  - **Codex 兼容模式的 version source = `.claude-plugin/plugin.json`**（Codex 无原生清单）——P2 身份校验、P5 version
    读取在 Codex 下**都读这份**。
  - **身份一致性硬预检**（任何 CLI 前，**只校验 `platforms` 声明的平台**）：`shared/plugins/<name>` 目录名
    = `manifest.toml` 条目 name = marketplace 名 = marketplace 内 plugin 名 = **该平台读取的 plugin 清单** name
    （Claude=`.claude-plugin/plugin.json`；**Codex 兼容模式=同一份 `.claude-plugin/plugin.json`**），**全等 `<name>`**；
    任一不等 → 预检失败、零副作用（否则 `<name>@<name>` 不是稳定身份）。
- **P3 平台变化全走官方 CLI；hub 不直接写平台文件，但 hub 自有状态仍用原子 Writer**（澄清：**不是"插件功能零
  Writer"**——`~/.hub/plugin-state.toml`（P6）与 induction 事务记录（C4）是 hub 自有状态，走 `Writer.write_text_atomic`）：
  - **平台侧（只经 CLI）**：Claude `claude plugin marketplace add/remove`、`claude plugin install/enable/disable
    <name>@<name> --scope user`；Codex `codex plugin marketplace add/remove`、`codex plugin add/remove <name>@<name>`
    （**Codex 无 enable/disable**，只 add/remove）。**绝不**直写 cache / `installed_plugins.json` /
    `known_marketplaces.json` / Codex `config.toml`。
  - **`--dry-run` 统一走同一 planner/executor 闸**（不手工拼另一套预览）：打印两类计划——① hub 自有状态由 Writer
    将写的字段（Writer 的 dry-run 字节预览）；② 将对平台执行的完整 CLI 命令（不跑）。
  - CLI 缺失 / 版本不认子命令 → **全量预检期失败**（动任何命令 / 写任何状态前）。执行期部分失败：**不伪原子**、
    报清「成功 / 未执行 / 失败」、幂等重跑收敛。
- **P4 启用态 = `<host>/device.toml` 的 `[plugins.<tool>] enabled` 允许列表**（设备×平台维度；manifest **不含**
  enabled；未列出默认不启用）：
  ```toml
  [plugins.claude]
  enabled = ["cjt", "xu-skills", "true-north"]
  [plugins.codex]
  enabled = ["cjt", "xu-skills"]
  ```
  `register` **分平台**收敛：
  - **Claude**：列表内 → 确保 `install` + `enable`；列表外**已装** → `disable`；列表外未装 → 保持未装。
  - **Codex**：列表内 → 确保 `add`；列表外**已装** → `remove`（Codex 的 enabled 列表即"期望安装集合"，
    无"已装但禁用"态）。
  - 市场：register 注册全部适配本平台的 market-of-one（**幂等**：source 已正确则跳；**source 不符 = `source-moved`
    → 按 P8 锁定的平台行为换源**：Codex `marketplace remove`+`add`、Claude `marketplace add` 直接覆盖）。
- **P5 refresh（cachebuster 感知，主路径；用户拥有 bump，refresh 不写插件仓；不改变启用/安装策略）**。**先读该平台
  实际已安装集合**（只读），refresh **只处理已安装的插件**——**未安装的一律跳过、绝不安装**（装/启用收敛只属 register）。
  对每个**已安装**插件 × 平台，读 `shared/plugins/<name>` 的 HEAD sha + **该平台** plugin 清单的 `version`
  （Claude=`.claude-plugin/plugin.json`；**Codex 兼容模式同读 `.claude-plugin/plugin.json`**，见 P2），对比 hub 台账（P6）：

  | 情形 | 动作 |
  |---|---|
  | **未安装** | **跳过**（refresh 不安装；装/启用归 register） |
  | 已安装但**无台账** | 首次重读 + **建立基线**（不新增安装） |
  | **SHA 未变** | **no-op**（幂等） |
  | **SHA 变 & version 变** | CLI 重装（见下命令）+ 更新**该平台**台账 |
  | **SHA 变 & version 未变** | **预检失败**：`需 bump <name>(<tool>)：源码已变但 manifest 版本未升，先 bump+commit 再 refresh`；非零退出，绝不用旧缓存 |
  | **仓 dirty（有未提交改动）** | **预检失败**：`仓 <name> 未提交，先提交你的 bump` |

  **重装命令（2026-07-20 隔离 spike 实测锁定）**：
  - **Codex**：`codex plugin add <name>@<name>`（重加即重装到新版；实测 bump 后 add → 缓存落新版本目录）。
  - **Claude**：**必须 `claude plugin uninstall <name>@<name>` + `claude plugin install <name>@<name> --scope user`**
    ——实测 `install` 单用对已装插件是 **no-op（不升级）**，`marketplace update` 也**不**升级已装版本；uninstall+install
    才读**实时 source** 装到新版（无需先 `marketplace update`）。

- **P6 plugin-state 台账**：`~/.hub/plugin-state.toml`，**本机运行态、不进金库**（金库 manifest = 权威清单，两者
  不同职）。**按"插件 × 平台"记录**——Claude/Codex 的清单、版本、刷新成功态可能不同，一个平台刷新失败**不冒充**
  另一平台成功；**只在对应平台 CLI 成功后**写该平台条目：
  ```toml
  [plugins.foo.claude]
  sha = "..."
  version = "..."
  [plugins.foo.codex]
  sha = "..."
  version = "..."
  ```
- **P7 status（只读）**：状态集——
  - `unregistered`（**仅指 market-of-one 市场缺失/未注册**——**不含**"允许列表内插件缺失"，那属 `enable-drift`；
    允许列表**外且未安装**是**健康态 `ok`**，不报）；
  - `source-moved`（市场已注册但 source 指向旧路径，非本机 `<vault>/shared/plugins/<name>`——覆盖跨机/迁移后旧路径）；
  - `enable-drift`（device.toml desired enabled 与平台实际启用/安装集合不一致）；
  - `stale`（已安装、SHA 变但版本未 bump）；
  - `dirty`（插件仓有未提交改动）；
  - `no-baseline`（已安装但台账无该平台条目）；
  - `missing-source`（仓不在 `shared/plugins`，needs restore）；
  - `drift`（**仅当 manifest 声明独立仓 + remote** 时，live remote/HEAD 与 manifest 不一致）；
  - `ok`。
  只读平台 `plugin list` + 台账 + manifest，**绝不写**；漂移只报，`register`/`refresh` 才收敛。
  **注意**：manifest **没有钉 SHA** 时，**不能拿 HEAD 对 manifest 报 drift**——此时 freshness 只能**和本机台账比**
  （台账 sha vs 当前 HEAD），manifest 只校验 name/remote 一致性。
- **P8 一次性迁移/induction（Plan 3 首批任务，用 C4 通用原语）**：把现有 6 仓从 `~/.claude/plugins-dev` induction
  进 `shared/plugins/<name>`（含各自 `.git`）；给 **true-north 补 market-of-one**（另 5 个已自带 `"source":"."`）；
  从**当前平台态生成 `device.toml` 的 enabled 列表**（compact-plus 自然留 Claude disabled）。**迁移含两种不同的身份/源
  变化，别混为一谈**：
  - **`@xu-local` 插件（身份变）**：`<name>@xu-local` → `<name>@<name>`。**先立新身份装稳，再退役旧 `@xu-local`**
    （切换期不 disappear）。
  - **`cjt` 类（身份不变、只换 source 路径）**：本机实查 `cjt` 市场已注册、身份已是 `cjt@cjt`，但 source 仍指
    `~/.claude/plugins-dev/cjt`。**这不是"立新退旧"**——身份没变，只是 source 从 plugins-dev 换到
    `<vault>/shared/plugins/cjt`。同名市场换源**行为已 spike 锁定（2026-07-20 隔离实测）**：
    - **Codex**：`plugin marketplace add` 对**已注册同名**市场**报错拒绝**（`already added from a different source;
      remove it before adding`）→ 迁移必须 **`marketplace remove` + `marketplace add` + `plugin add` 重装**。
    - **Claude**：`plugin marketplace add` 对同名**直接接受、重指新 source**（覆盖）→ 迁移 **`marketplace add` 换源
      + `uninstall` + `install` 重装**（两平台不对称，迁移器分平台处理）。

> **spike 已完成（2026-07-20 隔离实测，findings 已并入 P2/P5/P8）**：Codex 兼容（只 `.claude-plugin` 可注册安装、
> version 取 `.claude-plugin/plugin.json`）、两平台重装命令、两平台同名换源行为——**全部锁定，计划无条件占位**。
> 遗留边缘（只记录、不在 v1 处理）：compact-plus 含 **hook**，Codex 有 `trusted_hash` 信任闸（内容变要重信任），
> hooks 本就降出 v1。

### 10.3 明确后移 Plan 3.2（v1 不做）

换机 **clone@sha 恢复**、**灾备快照兜底**、**同名目录冲突退出**、`.git` 缺失时的 **rehydrate 全链**。输入契约
（manifest 的 remote/可选 sha、A 快照）**保留**，只是实现推迟。
