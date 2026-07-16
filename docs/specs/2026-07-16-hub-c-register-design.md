# 设计：hub C 阶段 —— 注册器 + 薄适配器 + 状态检查器

- 日期：2026-07-16（**v3，cut-scope 剪枝版**）
- 状态：待批准进 writing-plans（brainstorming 产出，未进实现）
- 关联：[NEEDS](../NEEDS.md)、[平台机制说明书](../平台机制/README.md)、金库 `SCHEMA.md`
- 修订史：v1 拷贝式加载器 → v2 补闭环/契约 → **v3 剪掉 copy 兜底带来的配套复杂度**

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
- **本会话未真机验证**：junction 跟随、`autoMemoryDirectory` 读写、受管块 @import 效果、多机 sync。实现前/中要真机确认。
