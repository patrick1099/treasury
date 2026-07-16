# 平台机制说明书 · opencode

> 给 hub 加载器（C 阶段）垫底：opencode 的文件布局与加载规则。
> 依据 = 官方文档（opencode.ai/docs，2026-07 抓）+ 本机实物 `~/.config/opencode/opencode.json`。
> **一句话定性**：opencode 对 Claude 生态**天生友好**——原生读 `~/.claude/skills` 和 `~/.claude/CLAUDE.md`。skill 几乎零成本共享；插件是另一套（JS 进程内）；**没有独立记忆库**。

## 0. 家目录与配置

全局 `~/.config/opencode/`（本机实测存在，含 `opencode.json` + `node_modules/`——npm 插件用 Bun 装在这）。

配置合并优先级（后者覆盖前者的反向，第一个匹配的赢）：
1. 远端 `.well-known/opencode`
2. **全局 `~/.config/opencode/opencode.json`**
3. `OPENCODE_CONFIG` 环境变量指定的自定义路径
4. **工程 `opencode.json`**（工程根）
5. 受管设置（系统级）

`opencode.json` 主要键（本机实测用到 `mcp` / `model` / `provider`）：`model`/`small_model`、`provider`、`mcp`、`plugin`、`agent`、`command`、`instructions`、`permission`、`lsp`、`tools`、`autoupdate`…
TUI 单独 `~/.config/opencode/tui.json`。

> ⚠ 本机 `opencode.json` 的 `mcp.*.environment` 和 `provider.*.options.apiKey` **含明文密钥**。加载器/备份**绝不能**把这份原样进金库明文区——落 hub guard 的密钥闸范畴，按 secrets 处理。

## 1. Skill —— 与 Claude 无缝

opencode **按顺序**搜这些目录（第一个匹配赢）：

**工程级**（从 cwd 向上走到 git worktree）：
- `.opencode/skills/<name>/SKILL.md`
- `.claude/skills/<name>/SKILL.md`
- `.agents/skills/<name>/SKILL.md`

**全局级**：
- `~/.config/opencode/skills/<name>/SKILL.md`
- **`~/.claude/skills/<name>/SKILL.md`** ← 直接读 Claude 的个人 skill
- `~/.agents/skills/<name>/SKILL.md`

SKILL.md frontmatter：`name`（必填，1–64 字，小写字母数字连字符）、`description`（必填，1–1024 字）、`license`/`compatibility`/`metadata`（可选）。是标准 Agent Skills 那套。

> **对 C 的意义**：skill 只要装进 `~/.claude/skills/`，**Claude 和 opencode 同时吃**，opencode 侧零额外动作。这是三平台里 skill 分发最省事的一环。

## 2. Plugin —— JS 进程内，另一套

**与 Claude/Codex 完全不同**：opencode 插件是 **JavaScript/TypeScript 模块**，导出插件函数，进程内跑，靠**事件回调**扩展，不是"打包一堆 skill/命令"。

- 放哪：工程 `.opencode/plugins/`、全局 `~/.config/opencode/plugins/`（启动自动加载）；或 npm 包写进 `opencode.json` 的 `"plugin"` 数组（启动用 Bun 装，缓存在 `~/.cache/opencode/node_modules/`）。
- 插件 API：函数收 `{ project, client, $, directory, worktree }`，返回一个 hooks 对象。
- 可挂的事件：`command.executed`、`file.edited`/`file.watcher.updated`、`tool.execute.before`/`after`、`session.created`/`session.compacted`/`session.idle`/`session.status`，以及 message/permission/lsp/server/shell/tui/installation 各类。

```js
export const MyPlugin = async ({ project, $ }) => ({
  event: async ({ event }) => {
    if (event.type === "session.created") { /* ... */ }
  },
});
```

> **对 C 的意义**：Claude/Codex 的插件（`plugin.json` + skills/hooks）**无法直接搬到 opencode**——形态根本不同。opencode 想要等价"插件级"能力得**另写 JS**。这是平台能力墙的一堵：**插件不可跨到 opencode**，只有插件**里的 skill** 能通过 `~/.claude/skills` 共享。

## 3. Hooks —— 就是插件事件，无独立 hooks.json

opencode **没有** Claude/Codex 那种 `hooks/hooks.json`。要在生命周期点做事，就是写 §2 的 JS 插件、挂对应事件（如 `session.created` ≈ SessionStart，`session.compacted` ≈ PreCompact 之后）。

> 之前 spike 实测：把 Claude 的 `hooks.json` 经 rulesync 生成到 opencode，`preCompact` 被丢、只剩 `session.created`——正因为 opencode 只有它自己那套事件、且是 JS 回调而非命令行 hook。**平台专属命令行 hook 到 opencode 得手工翻译成 JS 事件，且事件不一一对应。**

## 4. 记忆 / 指令 —— 只有 AGENTS.md，无记忆库

opencode **没有独立"记忆库"**，持久上下文全靠指令文件。加载优先级（每类第一个匹配赢）：
1. 工程 `AGENTS.md` 或 `CLAUDE.md`（从 cwd 向上找）
2. 全局 `~/.config/opencode/AGENTS.md`
3. **`~/.claude/CLAUDE.md`**（Claude Code 兼容，legacy）

`opencode.json` 的 `instructions` 数组可再引入别的规则文件（支持本地路径、glob、远端 URL），与 AGENTS.md 合并。`/init` 会扫仓库生成/更新 `AGENTS.md`。

> **对 C 的意义**：hub 的**记忆无处可去**——opencode 没有记忆库。要让 opencode"知道"金库里的知识，唯一路子是把（挑选过的）内容写进某个 `AGENTS.md`（全局或工程）。这和 Codex 一样：**记忆在 Claude 里是记忆库，到了 Codex/opencode 只能降级成指令文本**，或干脆不给。v1 建议：opencode 侧先只共享 skill，记忆是否落 AGENTS.md 留到后面单独定。

## 5. 其它（agent / command / mcp）

- 自定义 agent：`opencode.json` 的 `"agent"` 内联，或 `~/.config/opencode/agents/*.md`、`.opencode/agents/`。
- 自定义命令：`"command"` 内联，或 `~/.config/opencode/commands/`、`.opencode/commands/`。
- MCP：`opencode.json` 的 `"mcp"` 键（本机实测用了两个火山引擎 MCP，local 型 uvx 起）。

## 6. 对 hub 加载器（C）的启示（汇总）

| 类型 | opencode 侧怎么装 | 跨平台性 |
|---|---|---|
| **skill** | 装进 `~/.claude/skills/` 即被 opencode 原生读到 | ✅ 与 Claude 共享，零额外动作 |
| **插件** | 不可搬（JS 进程内是另一套）；只有插件**内的 skill** 能经 skill 目录共享 | ❌ 插件本体是能力墙 |
| **hook** | 无 hooks.json；要手写 JS 事件插件，事件不一一对应 | ❌ 命令行 hook 跨不过来 |
| **记忆** | 无记忆库；只能降级写进某个 `AGENTS.md`，或不给 | ⚠ 降级或跳过 |
| **配置** | `opencode.json` 含明文密钥 → 按 secrets 处理，不进金库明文区 | 🔒 |
