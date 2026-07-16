# 平台机制说明书 · Claude Code

> 给 hub 加载器（C 阶段）垫底：Claude Code 的文件布局与加载规则。
> 依据 = 官方文档（code.claude.com/docs，2026-07 抓）+ 本机实物（`~/.claude`）。
> 凡"本机实测"标注的，是这台机（host `2025-bg-016`）上真实存在的路径/文件。

## 0. 家目录与配置文件

家目录 `~/.claude/`（本机 `C:\Users\huawei\.claude`）。关键文件：

| 路径 | 作用 |
|---|---|
| `settings.json` | 用户级设置：`enabledPlugins`、`hooks`、权限等 |
| `.claude.json` | 另一份配置（含 `mcpServers` 等） |
| `skills/` | 个人 skill（见 §1） |
| `plugins/` | 已装插件的运行态：`known_marketplaces.json`、`installed_plugins.json`、`cache/`（可重建、不迁移） |
| `plugins-dev/` | **自己写的插件仓所在目录**（本机约定，同时是 `xu-local` marketplace 的 source） |
| `projects/<编码路径>/memory/` | 按工程存的记忆（见 §4） |
| `CLAUDE.md` | 用户级全局指令（native 加载 + `@import`） |

## 1. Skill

### 放哪、怎么被发现

| 位置 | 名字 | 谁用 |
|---|---|---|
| `~/.claude/skills/<name>/SKILL.md` | `/<name>` | 个人，全项目可用（本机实测：protocol-simulator、reconciling… ） |
| `<project>/.claude/skills/<name>/SKILL.md` | `/<name>` | 单项目 |
| 插件内 `skills/<name>/SKILL.md` | `/<plugin>:<name>` | 随插件分发（带命名空间） |

- 遵循 **Agent Skills 开放标准**（agentskills.io）——同一份 `SKILL.md` 跨工具通用。
- **符号链接：官方支持**——个人/工程位置下的 `<skill-name>` 条目"can be a symlink to a directory elsewhere ... Claude Code follows the symlink and reads SKILL.md from the target"；同一目标多路径可达也只加载一次。→ **可把金库里的 skill 逐个链进 `~/.claude/skills/`，Claude 跟随。**
- **`--add-dir` 加载外部 skill**：`--add-dir <目录>` 里的 `.claude/skills/` **会自动加载**（commands/output-styles 不会，skill 是例外）。
- **实时生效**：`~/.claude/skills/`、工程 `.claude/skills/`、`--add-dir` 的 `.claude/skills/` 下增删改 skill，**当前会话内即时生效**、不用重启（但新建一个之前不存在的顶层 skills 目录要重启才被监视）。
- **自定义命令已并入 skill**：`.claude/commands/deploy.md` 与 `.claude/skills/deploy/SKILL.md` 都产生 `/deploy`，等价。旧 `commands/` 继续可用。
- 目录形态：一个 skill = 一个目录，含 `SKILL.md` + 可选附属文件（`references/`、`scripts/`、`assets/`）。单文件也行（`SKILL.md` 直接放目录根，用 frontmatter `name`）。

### SKILL.md 格式

```markdown
---
description: 一句话（Claude 靠它判断何时用）
disable-model-invocation: true   # 可选：只允许 /手动调用，不自动注入
---
正文（用到时才加载，长参考料平时零成本）。
```

Claude 在标准之上加了扩展：调用控制（`disable-model-invocation`）、子代理执行、动态上下文注入、frontmatter 里直接写 hooks（见 §3）。`$ARGUMENTS` 捕获调用时的入参。

### Skills-directory 插件（介于 skill 与插件之间）

`claude plugin init my-tool` → 在 `~/.claude/skills/my-tool/` 生成 `.claude-plugin/plugin.json` + 起手 `SKILL.md`，**下次会话自动加载为 `my-tool@skills-dir`，无需 marketplace、无需 install**。适合"想要插件结构但只自己用"。

## 2. Plugin

### 结构（`.claude-plugin/plugin.json` + 根级目录）

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json        # 唯一放这里的东西：name/description/version/author…
├── skills/                # <name>/SKILL.md（命名空间 /my-plugin:name）
├── commands/              # 扁平 .md（旧式；新插件用 skills/）
├── agents/                # 子代理定义
├── hooks/hooks.json       # 事件处理器（见 §3）
├── .mcp.json              # MCP 服务器
├── .lsp.json              # LSP 服务器
├── monitors/monitors.json # 后台监视器
├── bin/                   # 启用时加进 Bash PATH 的可执行
└── settings.json          # 启用时应用的默认设置（仅 agent / subagentStatusLine）
```

> **常见错误**：`commands/`/`agents/`/`skills/`/`hooks/` 必须在**插件根**，**不能**放进 `.claude-plugin/`。插件根 = 含 `.claude-plugin/plugin.json` 的那个目录，**永远不是 `~/.claude/`**。

`plugin.json` 关键字段：`name`（唯一标识 + skill 命名空间前缀）、`version`（**设了才按版本更新**；省略且走 git 时用 commit SHA、每次提交算新版）、`description`、`author`（可选）。

### Marketplace 与安装

- **marketplace** = 一个含 `.claude-plugin/marketplace.json` 的仓/目录，列出它提供哪些插件。本机 `xu-local` 的 source 就是 `~/.claude/plugins-dev`（本机实测）。
- 装：`/plugin install`，或 `claude plugin marketplace add <repo/path>` 再装。
- **启用**：装 ≠ 启用；要在 `settings.json` 的 `enabledPlugins` 加 `"<plugin>@<marketplace>": true`，再 `/reload-plugins`。
- 运行态记录：`~/.claude/plugins/known_marketplaces.json`（`installLocation` + 嵌套 `source.path`，两处）、`installed_plugins.json`（`installPath`）。**换机改路径要同时改这几处**（见迁移工具 TODO bug #2）。
- 开发期免装：`claude --plugin-dir ./my-plugin`（可多次；也吃 `.zip`）；改完 `/reload-plugins`。
- 官方两大市场：`claude-plugins-official`（Anthropic 策展，首次交互启动自动注册）、`claude-community`（社区，审核后进）。

## 3. Hooks

### 定义在哪

| 位置 | 范围 | 可分发 |
|---|---|---|
| `~/.claude/settings.json` 的 `hooks` 键 | 全项目（本机） | 否 |
| `<project>/.claude/settings.json` | 单项目 | 是（可提交） |
| 插件 `hooks/hooks.json` | 随插件 | 是 |
| skill/agent frontmatter 的 `hooks:` | 组件生命周期 | 是 |

### 事件（本机 compact-plus 用的是 PreCompact/SessionStart）

会话级 `SessionStart`/`SessionEnd`/`Setup`；每轮 `UserPromptSubmit`/`Stop`；工具级 `PreToolUse`/`PostToolUse`（可拦）；压缩 `PreCompact`/`PostCompact`；还有 `SubagentStart/Stop`、`FileChanged`、`InstructionsLoaded` 等一长串。

### 格式 + 变量

```json
{ "hooks": { "PreToolUse": [ {
  "matcher": "Bash",
  "hooks": [ { "type": "command",
    "command": "${CLAUDE_PLUGIN_ROOT}/scripts/x.py",
    "timeout": 600, "shell": "bash" } ] } ] } }
```

- `type`：`command`/`http`/`mcp_tool`/`prompt`/`agent`。
- `matcher`：工具名（`PreToolUse` 等）或事件专属（`SessionStart` 匹配 `startup`/`resume`/`compact`…）。
- 路径变量：`${CLAUDE_PLUGIN_ROOT}`（插件安装目录）、`${CLAUDE_PROJECT_DIR}`、`${CLAUDE_PLUGIN_DATA}`。

## 4. 记忆（native「auto memory」，可全局重定向）

Claude Code 有 native 的 **auto memory**：Claude 自己积累的笔记，默认按工程存
`~/.claude/projects/<工程绝对路径编码>/memory/`（`<编码>` = 绝对路径 `[^A-Za-z0-9]`→`-`）。
用户的 curating-memory 那套（frontmatter + `MEMORY.md` 索引）就是**建在这套 native 机制之上**。

- 目录含 `MEMORY.md`（索引，每次会话加载**前 200 行 / 25KB**）+ 话题文件（按需读）。**Claude 读也写**这个目录。
- 默认按 git 仓分（worktree 共享一份），**机器本地、不跨机**。
- **关键（本会话核实，推翻旧结论）**：**`settings.json` 的 `autoMemoryDirectory` 可把这个目录整体重定向到任意外部绝对路径**（或 `~/` 开头）。**它读自 User/project/local 任一 scope**——所以在**用户级** `~/.claude/settings.json` 设一次，**本机所有工程的记忆都指向同一个外部目录**。这就是"全局记忆"的 native 解法，不必再往每个工程 seed。
  ```json
  { "autoMemoryDirectory": "~/hub-memory" }
  ```
  工程/local scope 设它要过 workspace 信任对话框（和 hooks 同一道闸）。
- native 的 `CLAUDE.md`（用户级 + 工程级 + `@import`）和 `.claude/rules/`（**支持符号链接**，可把共享规则链进多工程）是**指令**，与上面的"记忆库"是两码事。

> **对 C 的意义（大改）**：Claude 记忆不再是"拷贝/seed"问题，而是"**设一次 `autoMemoryDirectory` 指向共享目录**"的注册问题。但注意——**Claude 会往这个目录写**（auto memory 双向）：它自己重写 `MEMORY.md`、写真实绝对路径、按自己的格式落话题文件。所以**能不能直接指向金库 `shared/memory`** 要掂量：会和 hub 的 `derive.py`（也重算 MEMORY.md）、符号根 lint（Claude 写真实路径会触发）、sensitive 过滤打架。稳妥方案多半是指向一个**本地工作目录**，由 hub 在它与金库之间做格式翻译 + sync 时闸门。留 brainstorming 定。

## 5. 命令速查

```bash
claude plugin init <name>                    # 建 skills-dir 插件
claude plugin marketplace add <repo|path>    # 加市场
claude --plugin-dir ./p                       # 开发期免装加载
/plugin install / /reload-plugins             # 装 / 热重载
claude plugin validate                        # 提交前校验
```

## 6. 对 hub 加载器（C）的启示

- **skill**：**逐个符号链接**金库 skill → `~/.claude/skills/<name>/`（Claude 跟随、实时生效），不必拷贝。opencode 也读 `~/.claude/skills` → 一处链，Claude + opencode 双吃。（`--add-dir` 是另一条路，但那是每次启动的 flag，不如链接"设一次"。）
- **插件**：本机自写插件已在 `plugins-dev` + `xu-local` marketplace，Claude/Codex 共用同一 source。加载器要做的更多是**换机还原** `plugins-dev` 源码 + 重注册 marketplace + 写 `enabledPlugins`，同机近 no-op。改 `settings.json`/`*.json` 务必 **UTF-8 无 BOM**（PowerShell `Set-Content -Encoding utf8` 会加 BOM 撑坏 `/plugin`，见迁移 TODO bug #7）。
- **记忆**：**不必 seed 各项目**——用户级 `settings.json` 设 `autoMemoryDirectory` 指向一个共享目录即可全局生效。但 Claude 会往该目录写（双向），直连金库 `shared/memory` 会和 hub 的 MEMORY.md 重算 / 符号根 lint / sensitive 过滤冲突，多半要经一个本地工作目录 + hub 翻译层。符号根展开仍是 hub 的活。
- **hook**：平台专属（PreCompact/SessionStart 这类），别指望跨到 opencode/Codex 的同名事件——那是能力墙。
