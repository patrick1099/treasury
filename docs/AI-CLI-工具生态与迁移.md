# AI CLI 工具生态与迁移说明

围绕 **Claude Code** 和 **Codex** 这两个命令行 AI 编程工具，有三类东西在打交道，职责不同、互补不冲突：

| 工具 | 干什么 | 形态 | 数据来源 |
|------|--------|------|----------|
| **ai-cli-migrate**（自建） | **搬运 / 备份 / 换机** 全部个人数据 | Python 标准库 CLI | 原始 `~/.claude`、`~/.codex` |
| **claude-code-log** | **看 / 搜 / 算 token** Claude 会话 | pip 装的 CLI + TUI | `~/.claude/projects/*.jsonl` |
| **codex-trace** | **看 / 搜 / live-tail** Codex 会话 | Tauri 桌面 + Web GUI | `~/.codex/sessions/*.jsonl` |

一句话：**ai-cli-migrate 负责搬数据，另外两个负责读数据。**

---

## 1. ai-cli-migrate（本仓库，迁移/备份）

换电脑时把 Claude Code + Codex 的个人数据整体搬过去的自建工具，纯 Python 标准库，`py -3` 跑。

### 统一入口 `migrate.py`

```
py -3 migrate.py status                                  # 看两者体积
py -3 migrate.py export [--out-dir DIR] [--include-logs] [--no-history] [--only claude|codex]
py -3 migrate.py import [--claude ZIP] [--codex ZIP] [--remap-user OLD NEW]
```

底层是两个可独立使用的子工具：

- **`claude_migrate.py`**（`~/.claude`）：白名单导出 settings / skills / projects（含 memory 全量聊天记录）/ history / plugins 清单 + marketplaces；只抽 `.claude.json` 里的 `mcpServers`；`--remap-user OLD NEW` 改写会话目录名和 jsonl 里的路径。
- **`codex_migrate.py`**（`~/.codex`）：导出 sessions / state / memories / config / skills。**SQLite 用 backup API 做一致性快照**（自动合并 WAL，不拷 `-wal`/`-shm`，Codex 开着也能安全导出）；`logs_*.sqlite`（几百 MB 运行日志）默认不打包，加 `--include-logs` 才带；`--remap-user` 对文本文件做字节替换、对 sqlite 文本列走 `UPDATE...REPLACE`。

### 永不迁凭证

两边的登录凭证一律不打包（Claude 的 `.credentials.json`/oauth、Codex 的 `auth.json`/`.sandbox-secrets`）。**新机导入后各自 `/login` 重新登录。**

### 一键打包（桌面快捷方式）

为换机准备的傻瓜流程，见本仓库 `pack_migration.py` + `打包.bat`：

1. 双击桌面 **「一键打包迁移包」** 快捷方式；
2. 它导出 Claude + Codex（默认范围：含全量聊天记录、不含运行日志、排除凭证），
   把 **工具源码 + 数据 + 迁移说明** 打成一个 `ai-cli-迁移包-日期.zip` 放到桌面；
3. 把这个 zip 拷到新电脑，解压，照里面的 `迁移说明.md` 跑 `migrate.py import` 即可。

> 注意：迁移包内含**全部聊天记录**（可能涉及固件代码、客户信息、密钥等敏感内容）。
> 只在自己可信的设备/介质之间拷贝；**不要**上传到任何公开或第三方服务。

---

## 2. claude-code-log（看 Claude 会话）

把 `~/.claude/projects` 的 JSONL 转成可读 **HTML / Markdown**，并带交互式 TUI。

- GitHub：<https://github.com/daaain/claude-code-log>
- 安装：`pip install claude-code-log` 或 `uvx claude-code-log@latest`
- 常用：
  ```
  claude-code-log --tui                       # TUI 浏览会话列表
  claude-code-log --open-browser              # 处理所有项目并打开浏览器
  claude-code-log transcript.jsonl            # 转单个文件
  claude-code-log /path --from-date "yesterday"
  ```
- 能力：按消息/会话统计 **token 成本**、消息类型过滤、自然语言日期过滤、commit SHA 关联、Markdown 导出（可拿去喂给 LLM 当历史上下文）。

**用途**：长会话复盘、算花了多少 token、把过去对话导成 MD 投喂。

---

## 3. codex-trace（看 Codex 会话）

读 `~/.codex/sessions/` 的 Tauri 桌面 / Web 查看器（**没有 TUI**），三栏布局：会话树 → turn 列表 → 详情。

- GitHub：<https://github.com/PixelPaw-Labs/codex-trace>
- 安装/运行：
  ```
  git clone https://github.com/PixelPaw-Labs/codex-trace.git
  cd codex-trace && ./script/install.sh        # 桌面应用
  # 或 web 模式:
  docker run -p 1422:1422 -v "$HOME/.codex/sessions:/home/app/.codex/sessions:ro" codex-trace
  ```
- 能力：搜索、**SSE live-tail 看正在跑的会话**、工具调用检查（exec/MCP/patch/web search/图片生成）、token 计数、**collaboration chains**（把 orchestrator 和 worker 会话串起来，多 agent 场景有用）。

**用途**：实时看 Codex 正在干啥、多 agent 协作链路追踪、调试工具调用。

---

## ⚠ 名字撞车提醒

这片生态里有好几个名字很像、做的事不同的项目，别装错：

- `claude-code-log`（daaain）= **转换器**（JSONL → HTML/MD）✔ 本文所指
- `claude-code-trace`（delexw）= 另一个 Claude 会话**查看器**，不是同一个
- `codex-trace`（PixelPaw-Labs）= Codex 会话**查看器** ✔ 本文所指
- `codex-trace`（ljw1004）= 抓 VSCode Codex 扩展的**网络 trace**，完全另一回事，别混

---

## 三者怎么配合

```
        ┌─────────────── 日常 ───────────────┐
        │  claude-code-log  →  看 Claude 会话、算 token
        │  codex-trace      →  看 Codex 会话、live-tail
        └────────────────────────────────────┘
                         │
                         │ 换电脑时
                         ▼
        ┌─────────── ai-cli-migrate ──────────┐
        │  双击「一键打包迁移包」              │
        │  → ai-cli-迁移包-日期.zip（到桌面）  │
        │  → 新机解压 → migrate.py import      │
        └─────────────────────────────────────┘
```

查看类工具只读不改、随时可重装；**ai-cli-migrate 是唯一能搬数据、改用户名、做 sqlite 一致性快照、过滤凭证的那个**，换机就靠它。
