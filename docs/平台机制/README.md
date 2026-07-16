# 平台机制说明书

hub 加载器（C 阶段）动代码前的地基：三个平台各自的文件布局与加载规则，**先摸清机制、有依据、再开干**。

- [Claude Code](./claude-code.md)
- [Codex](./codex.md)
- [opencode](./opencode.md)

依据 = 官方文档（2026-07 抓）+ 本机实物（host `2025-bg-016`）。凡"本机实测"是这台机上真实路径。

## 跨平台对照表

| | Claude Code | Codex | opencode |
|---|---|---|---|
| **家目录** | `~/.claude/` | `~/.codex/`（`CODEX_HOME`） | `~/.config/opencode/` |
| **配置** | `settings.json` + `.claude.json` | 单份 `config.toml` | `opencode.json`（+ `tui.json`） |
| **skill 目录** | `~/.claude/skills/<n>/`（**跟随符号链接**；`--add-dir` 也加载） | **官方 `~/.agents/skills/<n>/`**（+ 可选 `agents/openai.yaml`）；本机也用 `~/.codex/skills/` | `~/.config/opencode/skills/` + 原生读 `~/.claude/skills/` **和 `~/.agents/skills/`** |
| **skill 标准** | Agent Skills（+扩展） | Agent Skills（+openai.yaml 皮肤/依赖/策略） | Agent Skills |
| **插件形态** | `.claude-plugin/plugin.json` + 根级 skills/hooks/agents/mcp… | **原生 `.codex-plugin/plugin.json`** + 根级 skills/hooks.json/.mcp.json（**与 Claude 的清单不同名**；`.claude-plugin` 仅经 marketplace 部分兼容） | **JS/TS 进程内模块**（完全不同） |
| **插件启用** | `settings.json` 的 `enabledPlugins` | `config.toml` 的 `[plugins."x@market"]` | `opencode.json` 的 `"plugin"` 数组 / 目录自动加载 |
| **市场** | `marketplace.json`；`/plugin`、`claude plugin` | `[marketplaces.*]`；`codex plugin add`，cachebuster 重装 | 无市场；npm 包 / 本地 JS |
| **hooks** | `settings.json` + 插件 `hooks/hooks.json`，事件多，`${CLAUDE_PLUGIN_ROOT}` | **读同款 `hooks/hooks.json`** + `[hooks.state]` 信任哈希；事件集较少 | 无 hooks.json；JS 插件挂事件（session.created 等） |
| **记忆** | 按工程 `projects/<p>/memory/` + `MEMORY.md`（自动加载）；**`autoMemoryDirectory`（user/project/local/policy，project/local 需信任）可整体重定向到外部一份** | `~/.codex/memories/` **自蒸馏、不可喂** | **无记忆库**，靠 `instructions[]` 引外部 |
| **指令(rules)** | `CLAUDE.md`（用户+工程+`@import`） | `AGENTS.md` | `AGENTS.md` + `instructions[]`；也读 `~/.claude/CLAUDE.md` |

## 三条大启示（决定 C 怎么设计）

1. **skill 是三家最通的，且能"活链"**。Claude **跟随** `~/.claude/skills/` 下的符号链接（实时生效）；opencode 原生读 `~/.claude/skills` 和 `~/.agents/skills`；Codex 读 `~/.agents/skills` 且支持 skill 文件夹符号链接（**但 `~/.agents/skills` 目录本身别做成链接**，issue #11314）。`openai.yaml` **可选**。→ 逐个 skill 链一次，三家实时共享。

2. **插件已跑通一半，但 opencode 是墙**。Claude 与 Codex **共用 `~/.claude/plugins-dev` 作 marketplace 源**（本机 `config.toml` 实测），自写插件已双装；换机靠各自 `plugin add` + 市场注册。**opencode 插件是 JS 进程内另一套，本体搬不过去**——只有插件**内的 skill** 能经 skill 目录共享。

3. **记忆是唯一没有跨平台"记忆库"的，正是 C 的内核——但各家都有"指向外部一份"的口子**：
   - **Claude**：`settings.json` 的 **`autoMemoryDirectory`（User 级，接受外部绝对路径）**把记忆目录整体重定向到共享目录，一次设置全项目生效，**不必 seed**。注意 Claude 会**双向读写**该目录（自己重算 MEMORY.md、写真实路径），直连金库会和 hub 的 MEMORY.md 重算 / 符号根 lint / sensitive 过滤打架 → 多半经一个本地工作目录 + hub 翻译层。
   - **opencode**：`opencode.json` 的 **`instructions[]`** 可直接引用外部文件/glob/URL → 指向共享索引即可，正文按需读。
   - **Codex**：自蒸馏记忆**不碰**；靠一个薄 `hub-memory` skill + 全局 `AGENTS.md` 指针按需读金库。

4. **能力墙（做不了，别硬凑）**：平台专属命令行 hook（Claude `PreCompact`/`SessionStart`）跨不到 opencode（只有 JS 事件、不一一对应）；Codex 事件集也不等同 Claude。compact-plus 这类 hook 插件保持 Claude-only。

5. **安全**：opencode `opencode.json`、Codex/Claude 各配置里可能含明文密钥（本机 opencode 实测有火山引擎 key）→ 一律走 hub guard 密钥闸，不进金库明文区。
