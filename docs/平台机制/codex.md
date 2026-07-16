# 平台机制说明书 · Codex

> 给 hub 加载器（C 阶段）垫底：Codex CLI 的文件布局与加载规则。
> 依据 = Codex 自带的系统 skill 权威参考（`~/.codex/skills/.system/{skill-creator,plugin-creator,skill-installer}/references/`）+ 本机实物 `~/.codex/config.toml`（host `2025-bg-016`，2026-07 抓）。
> **重要**：本文推翻了 hub SCHEMA 里"Codex 无 hook / 插件只有声明"的旧假设——Codex 现已有完整插件 + hooks + marketplace 体系。

## 0. 家目录与配置文件

家目录 `~/.codex/`（`CODEX_HOME`，本机 `C:\Users\huawei\.codex`）。核心是**一份** `config.toml`（不像 Claude 分 settings.json/.claude.json）。本机 `config.toml` 实测含这些节：

| 节 | 作用 |
|---|---|
| 顶层 `model` / `model_reasoning_effort` / `personality` | 模型与行为 |
| `[projects.'<路径>'] trust_level` | 每工程信任级别（`trusted`） |
| `[plugins."<name>@<market>"] enabled` | **插件启用**（见 §2） |
| `[marketplaces.<name>]` | **市场登记**（source_type git/local + source） |
| `[mcp_servers.<name>]` | MCP 服务器 |
| `[features] memories` / `[memories]` | 记忆特性开关（见 §4） |
| `[hooks.state]` | **hook 信任状态**（见 §3） |

## 1. Skill

### 放哪、怎么被发现（本机实测）

扫描顺序（官方 build-skills 文档）：工程 `.agents/skills`（从 cwd 向上到 repo 根）→ **user 级 `$HOME/.agents/skills`** → admin `/etc/codex/skills` → 内置系统 skill。

| 位置 | 说明 |
|---|---|
| **`~/.agents/skills/<name>/`** | **官方 user-level**（跨工具中立，opencode 也读同一处） |
| `~/.codex/skills/<name>/` | 本机实测 Codex 也在这放（skill-installer 装的落这），含用户 skill + `.system/`（带 `.codex-system-skills.marker`） |
| `~/.codex/plugins/cache/<market>/<plugin>/<ver>/skills/<name>/` | 插件自带的 skill |

**符号链接：官方支持**——"Codex supports symlinked skill folders and follows the symlink target"。**但有坑**（GitHub issue #11314）：**整个 `.agents/skills` 目录本身是符号链接时不识别**，必须是**真目录、里面逐个 skill 建链**。（`~/.codex/skills` 是不是官方 user-level 官方文档没提，只提 `~/.agents/skills`；hub 注册优先用 `~/.agents/skills`。）

### 一个 skill 的构成 = SKILL.md + agents/openai.yaml

**与 Claude 的关键差异**：Codex 的 skill 除了标准 `SKILL.md`，还有一份 **`agents/openai.yaml`**（Codex 专属清单，给机器/harness 读，不是给模型读）：

```yaml
interface:
  display_name: "用户可见名"
  short_description: "25–64 字 UI 摘要"
  icon_small: "./assets/small-400px.png"
  brand_color: "#3B82F6"
  default_prompt: "用 $skill-name 来……"   # 必须提到 $skill-name
dependencies:
  tools:
    - type: "mcp"                # 目前只支持 mcp
      value: "github"
      transport: "streamable_http"
      url: "https://api.githubcopilot.com/mcp/"
policy:
  allow_implicit_invocation: true   # false=不自动注入上下文，只能 $skill 显式调
```

> `SKILL.md` 是跨工具通用的那份；`openai.yaml` 是 Codex 的皮肤 + 依赖 + 调用策略。**它是可选的**（官方："Optional: appearance and dependencies"）——**SKILL.md 单独就能在 Codex 跑**，没有 openai.yaml 只是缺 ChatGPT 桌面端 UI 展示 / 隐式调用策略 / MCP 依赖声明。加载器可按需补，不强制。

### 装 skill

系统 skill `skill-installer` 提供 `install-skill-from-github.py` / `list-skills.py`。

## 2. Plugin（本机实测已在用）

### config.toml 里的形态

```toml
[plugins."xu-skills@xu-local"]        # <插件名>@<市场名>
enabled = true

[marketplaces.xu-local]
source_type = "local"
source = '\\?\C:\Users\huawei\.claude\plugins-dev'   # ← 和 Claude 同一个目录！
```

**跨工具关键事实**：本机 Codex 的 `xu-local` / `cjt` marketplace 的 source **直接指向 `~/.claude/plugins-dev`**，即**和 Claude 共用同一份插件源码**。所以自写插件（cjt、keil2clangd、true-north、xinao-csb-skills、xu-skills）已经**一处开发、Claude + Codex 双装**。git 型市场同理（superpowers-dev→obra/superpowers、claude-plugins-official）。

### 原生插件清单 = `.codex-plugin/plugin.json`（与 Claude 不同名）

官方 build-plugins：Codex 插件的清单是 **`.codex-plugin/plugin.json`**（`name`/`version`/`description`/`skills` 路径），
只有 `plugin.json` 放 `.codex-plugin/`，`skills/`、`hooks.json`、`.mcp.json`、`.app.json` 放插件根。
市场文件在 `$REPO/.agents/plugins/marketplace.json` 或 `~/.agents/plugins/marketplace.json`。

> **和 Claude 的区别要记牢**：Claude 是 `.claude-plugin/plugin.json`，Codex 原生是 `.codex-plugin/plugin.json`——
> **两份不同名的清单**。本机那些只有 `.claude-plugin` 的自写插件能在 Codex 出现，是走 marketplace 的**部分兼容**
> （skill 能加载、hook 能注册），**不代表 `.claude-plugin` 是 Codex 的原生入口**。要让自写插件在 Codex 真正"原生"，
> 各插件仓得自己补一份 `.codex-plugin/plugin.json`——**这是插件仓作者的活，不该由 hub 自动合成双清单**。

### 装 / 更新 / 启用命令

```bash
codex plugin marketplace add <path-to-marketplace-root>   # 非默认市场要先加
codex plugin add <plugin>@<market>                        # 装
codex plugin list                                          # 看哪个市场在供这个插件
```

- **默认个人市场**：`~/.agents/plugins/marketplace.json`，**隐式发现**，不用 `marketplace add`。
- **本地开发更新循环**：改完插件要触发重装，靠**cachebuster** 改 manifest 版本：`<base>+codex.<token>`（如 `0.1.0+codex.local-20260519-184516`），跑 `update_plugin_cachebuster.py`（默认用 UTC 时间戳），再 `codex plugin add` 重装，然后**开新线程**才生效。
- 规矩：市场操作走命令，**别手改 `marketplace.json` / `config.toml`**。

## 3. Hooks（新，SCHEMA 旧假设已废）

本机 `config.toml` 实测有：

```toml
[hooks.state]
[hooks.state."xu-skills@xu-local:hooks/hooks.json:session_start:0:0"]
trusted_hash = "sha256:4105d77de8c79edcbcd1ac353cd5a66972210bb06eea62bc036a53ebf4054af1"
```

说明：**Codex 会读插件的 `hooks/hooks.json`**（与 Claude 同一文件），键形如 `<插件>@<市场>:hooks/hooks.json:<event>:<i>:<j>`。已见事件 `session_start`。有一道**信任闸**：每个 hook 存 `trusted_hash`，内容变了要重新信任（防止插件更新后静默跑新代码）。

> 对 C 的意义：Codex ↔ Claude 的**插件 hook 可复用同一份 `hooks/hooks.json`**（至少 session_start）。但**事件集不等同 Claude**——Claude 的 `PreCompact` 在 Codex 未必有同名事件，跨平台 hook 仍受能力墙限制，逐事件核实，别假设一一对应。

## 4. 记忆（Codex 有自己的一套，且**不能喂**）

`config.toml`：`[features] memories = true`、`[memories] generate_memories = true, use_memories = true`。

Codex 的记忆在 `~/.codex/memories/`，是**后台从任务自动蒸馏的生成态**，官方明说"视为生成状态、别手工编辑"。

> **hub 铁律（SCHEMA §2）**：`~/.codex/memories/` **既不收、也不灌**——灌给它 → 它当"学到的事实"再蒸馏 → 又被收回金库 → 回环。**记忆真源只有 hub 金库一处。** 所以 C 阶段**不往 Codex 装记忆**；Codex 的知识靠 `AGENTS.md`（指令）承载，不靠记忆库。

`AGENTS.md`（`~/.codex/AGENTS.md` 用户级 + 工程级）是 Codex 的指令文件，对标 Claude 的 `CLAUDE.md`。

## 5. 对 hub 加载器（C）的启示

- **skill**：装进 **`~/.agents/skills/<name>/`**（官方 user-level，opencode 共读）。**符号链接逐个 skill 建**（别把 `~/.agents/skills` 整个做成链接 → issue #11314 不识别）。`agents/openai.yaml` **可选**，按需补 UI/策略/依赖。
- **插件**：已与 Claude 共用 `plugins-dev` 源 + 各自 marketplace 登记。C 的插件活主要是换机时：还原源码 + `codex plugin marketplace add` + `codex plugin add` + 本地改动靠 cachebuster 重装。别手改 `config.toml` 的 `[plugins]`/`[marketplaces]`，走 `codex plugin` 命令。
- **记忆**：**不装**（自蒸馏回环）。要给 Codex 上下文，走 `AGENTS.md`。
- **hook**：插件 `hooks/hooks.json` 可跨 Claude/Codex 复用，但注意 Codex 的 `trusted_hash` 信任闸（内容变要重信任）+ 事件集差异。
