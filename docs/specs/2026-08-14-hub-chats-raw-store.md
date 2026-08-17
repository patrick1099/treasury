# hub 原始对话库设计（chats）v2

> **v2（2026-08-14）**：经 codex 评审后重写。v1 有四处判据不成立，逐条记在 §12「评审改了什么」，
> 别照 v1 的记忆实现。
>
> 题目来自 `Obsidian Vault/AI 记忆、知识笔记与 Skill 演化系统实施基线.md` 的**阶段1：原始对话库**：
> 「完成统一事件模型、只读导入、幂等、全文搜索、敏感 Scope 和原文定位。
> 重复导入零新增；随机抽取的结论能够返回原消息。」
>
> 本 spec 只做阶段1。阶段2（项目接续）、阶段3（疑惑提炼）、阶段4（建链）都不在这里，
> 但事件模型要能撑住它们的读取需求。

## 1. 它解决什么

用户要三件事，优先级由用户 2026-08-14 当面给出：

1. **跨平台统一检索/回顾** —— 一处搜到「我当初在哪个平台怎么解决过 X」；
2. **蒸馏记忆/知识笔记的素材** —— 派生层的原料；
3. **别丢** —— 见 §3.2 的诚实边界，**本轮只做到一半**。

基线文档 §三.1 把它定成「唯一原始证据库」：所有记忆、摘要、知识点、接续包和 Skill 候选
都必须能通过 `source/session/message/tool` 标识**返回原文**。派生系统损坏可以重建，
原始记录不能被摘要代替。

**因此本层不做摘要、不做提炼、不改写正文。** 它只干两件事：把原始证据搬到一个不会被工具
清理掉的地方，然后建一个可随时重建的索引让人搜得到、回得去。

## 2. 本机五个源的实测形态（2026-08-14 勘探）

| source | 落盘形态 | 实测量 | 关键字段 |
|---|---|---|---|
| `claude` | `~/.claude/projects/<编码工程路径>/<sessionId>.jsonl` | 97 会话 / 117 MB | 每行带 `cwd` `gitBranch` `sessionId` `uuid` `parentUuid` `timestamp`；`type` ∈ user/assistant/attachment/mode/permission-mode/ai-title/last-prompt/file-history-* |
| `codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`（+ `archived_sessions/`） | 747+17 会话 / 678 MB | 每行 `{timestamp,type,payload}`；`session_meta.payload` 带 `cwd` `git.{branch,commit_hash,repository_url}`；`response_item.payload` 带 `id` `role` `content` |
| `opencode` | `~/.local/share/opencode/opencode.db`（SQLite） | 103 会话 / 2171 消息 / 8703 part | `session`(directory/title/model/agent/time_*) + `message`(id/role/data) + `part`(id/message_id/data，type ∈ text/reasoning/tool/step-*/file/patch) |
| `copilot-cli` | `~/.copilot/session-state/<uuid>/events.jsonl` | 2 会话，1 个有 events.jsonl | `{id,parentId,timestamp,type,data}`；`session.start.data.context` 带 `cwd` `gitRoot` `branch` |
| `copilot-vscode` | `%APPDATA%/Code/User/workspaceStorage/<hash>/chatSessions/<id>.jsonl` | 105 文件 / 26 MB / 40 工作区 | **增量日志**：`kind:0` 全量快照，`kind:1/2` 是 `{k:[键路径], v:值}` 增量。工程路径在同级 `workspace.json` 的 `folder`/`workspace` |

合计约 **820 MB**，每天在长。

三条由实测得出、决定了设计的事：

- **opencode 没有文件可拷**（旧的 `storage/` 已基本空掉，正文全在 SQLite）。所以「原样复制」
  对它不成立，必须导出。导出的是**原字段的原始行**，不是我们翻译过的模型——否则「原始证据库」
  这个承诺就破了。
- **copilot-vscode 是增量日志**，一行看不出一条消息。这条性质贯穿整个设计（见 §5.5、§8.3、§9）。
- **`event` 表（30703 行）是 opencode 的事件流，与 message/part 重复**，不导出。

## 3. 两层，职责不能混

```
原始层  <vault>/<host>/<tool>/chats/     append-only，字节级原样，绝不删
   │                                      ← 唯一事实源，坏了没得重建
   │  hub chats index
   ▼
派生层  ~/.hub/chats-index.db             SQLite + FTS5，本机运行态
                                          ← 随时可以删了重建，不进金库
```

**派生层里的每一条都必须能指回原始层。** 这是基线文档 §三.1 的硬要求，
也是本设计里唯一不许妥协的不变量。注意「指回原始层」对增量日志源不等于「指回某一行」，
见 §8.3。

### 3.1 为什么原始层放金库而不是 `~/.hub/`

`~/.hub/` 在现有架构里的语义是**派生、可重建、本机运行态**；原始对话恰恰**不可重建**
——工具会自己清理（Codex 的 `archived_sessions/`、VS Code 的工作区回收），清掉就真没了。
放进 `~/.hub/` 会把生命周期语义弄反。

SCHEMA 早就为它留了位置：备份区 `<host>/<tool>/chats/`，且按工具分——原始数据本来就是
工具形状的。本设计只是把这个一直空着的目录填上。

### 3.2 诚实边界：本轮**没有**离机备份

本轮 chats 被 `.gitignore` 排除（§7），所以它现在只是**"位于金库目录里的本机证据"**，
不是备份。删仓库、重新 clone、`git clean -fdx`、磁盘坏了，它都会一起没。

**不许在任何文档、命令输出或提交信息里把它说成"换机照它还原"。**
`hub chats status` 必须原样打印这三行，让人一眼看到边界：

```text
storage:            local-only
off-device backup:  none
git tracking:       blocked
```

同样，**不许承诺"将来解禁只需改一行 `.gitignore`"**。静态加密会让增量文件失去 git delta
优势，一个持续变化的 800 MB 目录会迅速撑爆 git 历史。将来的离机方案更可能是不可变分块 /
对象存储 / 专门的备份协议。**现在这套目录布局可以原样保留，但同步实现不能预先承诺。**

### 3.3 为什么不并进 `collect`

`hub chats collect` 是**独立命令**，不进 `collect` 的 `run_all`。四条理由，任何一条单独成立：

1. **语义相反**。`collect` 是镜像：源里没了的，金库里也删。原始证据库是 append-only：
   **源里没了的，金库里必须留着**——那正是它存在的理由。
2. **量级**。collect 现在处理 MB 级；chats 是 GB 级且逐日增长。
3. **`scan_tree` 会被拖死**。`collect.run_all` 结尾对整个 `<host>/` 逐文件 `read_bytes`。
4. **git 归属不同**。collect 的产物要进 git；chats 本轮明确不进。

**架构测试钉的是行为，不是"不许认识这个路径"**：collect 为了跳过扫描**必须**引用
`*/chats`（现有代码已经如此）。要钉死的三条是——collect 不得调用 chats 的发现/导入/写入
流程；不得写、删、重建任何 chats 内容；`scan_tree` 必须跳过 chats。

## 4. 原始层的布局

```
<host>/claude/chats/
    manifest.toml
    sessions/<project_dir>/<sessionId>.jsonl
<host>/codex/chats/
    manifest.toml
    sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl     沿用源的日期分层，747 个文件不能平铺
    sessions/archived/rollout-*.jsonl
<host>/opencode/chats/
    manifest.toml
    sessions/<sessionId>.jsonl                    从 SQLite 导出的原始行
<host>/copilot-cli/chats/
    manifest.toml
    sessions/<uuid>/events.jsonl
    sessions/<uuid>/workspace.yaml                role=auxiliary
<host>/copilot-vscode/chats/
    manifest.toml
    workspaces.toml                               role=auxiliary，<hash> → folder URI
    sessions/<hash>/<sessionId>.jsonl
共用：
    revisions/<原 rel 打平>.<旧sha前8位><后缀>    被取代的旧证据（§5.4）
```

`copilot-cli` 与 `copilot-vscode` 是**两个 tool 目录**，不是一个。它们确实是两套独立的存储、
两套格式、两个产品形态，合并只会制造一个不存在的东西。

### 4.1 artifact 的两种 role

- **`transcript`**：对话正文。索引层为它建 session + event。
- **`auxiliary`**：辅助证据（`workspaces.toml`、`workspace.yaml`）。同样进 manifest、同样
  append-only，但**不建 session、不产 event**，只在索引 session 元信息时被读来补工程路径。

没有这条区分，索引层会为一张 hash 映射表建一个不存在的"会话"。

### 4.2 manifest.toml

每个 artifact 一条，记的是**证据的身份**，不是它的内容：

```toml
[artifact."sessions/6a96cdd6-….jsonl"]
source_path = "C:/Users/huawei/.claude/projects/C--…/6a96cdd6-….jsonl"
role = "transcript"
kind = "copy"
bytes = 1234567
sha256 = "…"                # 强身份：金库里这份**实际落盘字节**的摘要
lines = 184
source_size = 1234567       # 快路径用：上次见到的源 stat
source_mtime_ns = 1786…
source_ino = 0              # 0 = 本平台/文件系统没给，别当它是 0 号 inode
imported_at = "2026-08-14T12:00:00Z"
session_id = "6a96cdd6-…"
source_gone = false         # 源被工具清理掉了，金库这份继续留着
superseded_by = ""          # 本条是旧证据时，指向取代它的 current
supersedes = ""             # 本条是 current 时，指向被它取代的 revision
```

**时间范围（首末消息时间）故意不在这里**——那要解析正文才知道，而 COPY 型 artifact 单次
收集不该为了两个显示字段去解析几百 MB。它归索引层（索引本来就要逐行解析）。

### 4.3 opencode 的导出格式

一个 session 一个 jsonl，行的形状**照抄库里的行**，只加一个 `_row` 标明来自哪张表：

```jsonl
{"_row":"session","id":"…","directory":"…","title":"…","model":"…","time_created":…}
{"_row":"message","id":"…","session_id":"…","time_created":…,"data":{…原样…}}
{"_row":"part","id":"…","message_id":"…","session_id":"…","time_created":…,"data":{…原样…}}
```

`data` 列在库里是 JSON 字符串，**解析后原样嵌入**；解析失败则原样保留字符串并加
`_data_unparsed: true`，**不许丢**。

行序：session 行在前，其余按 `(time_created, id)` 升序。**排序必须确定**，
否则同样的库导出两次得到不同字节，幂等当场失效。

## 5. Append-only：一个状态机，两种"增长证明"

每个 artifact 每次收集只可能落到四个状态之一：

```
内容相同                       → unchanged   零写入
能证明新内容包含全部旧证据      → grown       覆盖 current
不能证明                       → preserved   旧的存成不可变 revision，新的写进 current
源侧没了                       → gone        一个字节都不动，标 source_gone
```

**"能不能证明"按源的性质分，这不是设计缺陷，是不同源能给出的证明强度本来就不同。**

### 5.1 强身份 vs 快路径

- **强身份永远是 `(bytes, sha256)`**，且这个 sha 指的是**金库里实际落盘的那份字节**（§6.1）。
- **日常快路径**：`(source_size, source_mtime_ns)` 与 manifest 相同 → 跳过重新验证，判 `unchanged`。
  它只是**"快速未变提示"**，不是内容等价证明。678 MB 每次全 hash 不可接受，这是有意识买下的风险。
- stat 变了才重新 hash；hash 相同仍是 `unchanged`，但要把新 stat 写回 manifest（否则每次白算）。
- **`hub chats collect --verify`**：忽略快路径，全量重算。这是快路径的对冲，必须提供。
- 也记 `source_ino`（拿得到的话）帮助发现"文件被整个替换"，但它**证明不了原地内容没改**。

**不存在"既不读内容、又能严格识别同长度同 mtime 的原地重写"的判据。** 抽样首尾 hash 只降低
概率、不是证明，因此不做——不值得拿它冒充正确性。

### 5.2 COPY 的增长证明：前缀 sha

新 size > 旧 size，且 `sha256(新文件前 旧size 字节) == manifest.sha256` → 证明是纯追加 → `grown`。
文件型源（claude / codex / copilot-*）的 jsonl 本来就是 append 出来的，这个证明成立。

### 5.3 GENERATED 没有增长证明（v1 的行数判据已作废）

opencode 的导出是数据库快照，**没有前缀单调性**：一条 message 的 `data` 在会话进行中会被
就地更新。

**v1 曾用「新 lines >= 旧 lines」判增长——这条不成立，已删除**：
行数相同可能是就地更新；行数增加也可能同时删了旧行、加了新行。照它覆盖，会把已经采集到的
旧值弄丢，而"旧证据不丢"正是本层存在的理由。

**v2 规则**：GENERATED 的 sha 不同 → **一律走 preserved**（旧快照存成不可变 revision，
新的写进 current）。opencode 只有 103 个会话、总量远小于 Codex，先保证证据正确，
版本噪音是可以承受的代价。

将来真要优化，正确做法是按 `(_row, id)` 建旧行映射：只有**所有旧 key 仍存在、且对应行的
规范化字节完全相同**才算 grown；任一已有行变了仍要留 revision。不在 v1 做。

### 5.4 preserved 怎么落盘

旧的那份**改名**进 `revisions/`，命名 `<原 rel 打平>.<旧 sha 前 8 位><原后缀>`，
manifest 里为它留一条 `superseded_by` 指向 current 的 Entry（`source_path` 留空、
`source_gone = true`），current 记 `supersedes`。**改名走 Writer 的原语，dest 已存在时抛，
绝不覆盖。**

`preserved` 是需要人看一眼的事件（说明源侧发生了重写/压缩），CLI 要醒目打印，但**不是错误**，
退出码仍是 0。

### 5.5 源消失

manifest 里有、本次发现里没有 → `source_gone = True`，文件一个字节不动。
这与 `collect` 的镜像语义最根本的分歧，也是本层的全部意义。

## 6. 硬闸

### 6.1 `Writer.copy_binary`：原子 + 边拷边算

**这一条是评审逮出来的真 bug，不是加分项。**

现有实现直接以 `wb` 打开目标：一旦复制中途失败/断电，**旧证据已经被截断**——而它可能是
唯一副本。另外"先 hash 源、再 copy"之间源文件还在被工具追加，manifest 记下的 sha 可能
根本不是落盘的那些字节。

契约改成：

1. 同目录临时文件（`tempfile.mkstemp`，唯一名）；
2. **边拷边算** sha256 / bytes / lines —— 算的是**实际写进去的字节**，不是事后重读；
3. 拷贝前后各 `stat()` 源一次，`(size, mtime_ns)` 变了说明源在被追加 → 重试一次，仍变则报告；
4. `flush + fsync + os.replace` 原子替换；
5. **manifest 最后写**——它是台账，不能领先于事实。

`copy_binary` 返回实际写入内容的摘要（dry-run 返回 `None`）。任何异常都要清掉临时文件。

不这么改，"唯一事实源、不可重建"这句话和实际写入原语是冲突的。

### 6.2 `check_source` 覆盖每个被读的源

每个源根、每个被拷的文件都过 `hub.guard.check_source`。闸长在原语里，失败方向是
"什么都不写"。

### 6.3 缺源：未配置合法，配了不在就停

- **未配置**（device.toml 里没这一项）→ 合法，跳过这个源，不是错误。
- **配了但路径不存在** → **在任何 manifest 更新之前失败**，绝不解释成"这个源的全部会话都消失了"
  （那会让 §5.5 把整个源标成 `source_gone`）。这条是 hub 已经用一次金库被清空换来的教训。

### 6.4 `scan_tree` 跳过 chats

`collect.run_all` 传 `skip_dirs=<host>/*/chats`。已实现。

## 7. 明文与 git（用户 2026-08-14 决定：本轮只落本机，不进 git）

原始对话必然含明文密钥（引用层只管从今往后，旧 transcript 一个字管不着）和公司源码。
金库是私有仓，但 **git 的每个历史版本永久留存**，事后删文件不等于删历史。

- 金库根 `.gitignore`：`*/*/chats/`。
- **`hub sync` 加一道代码闸**：提交前若发现 chats 路径被 git 跟踪，抛 `ChatsTracked` 并停止
  ——与既有 `GitlinkTracked` 同一个形状。只靠 `.gitignore` 不够：它哪天被改坏、或某个文件
  早被 `git add -f` 过，失败方向就是「800 MB 明文静默推上 GitHub」，不可撤销。
- `~/.hub/chats-index.db` 是本机运行态，本来就不进金库。

## 8. 派生层：统一事件模型

`~/.hub/chats-index.db`，SQLite（本机 3.50.4，**FTS5 实测可用**）。

```sql
CREATE TABLE session(
  id INTEGER PRIMARY KEY,
  host TEXT NOT NULL,
  source TEXT NOT NULL,            -- claude / codex / opencode / copilot-cli / copilot-vscode
  session_id TEXT NOT NULL,
  started_at INTEGER, ended_at INTEGER,
  cwd TEXT, repo TEXT, branch TEXT,
  model TEXT, title TEXT,
  raw_path TEXT NOT NULL,          -- 相对金库根
  raw_sha TEXT NOT NULL,           -- 索引建在哪个版本上
  event_count INTEGER,
  UNIQUE(host, source, session_id));

CREATE TABLE event(
  id INTEGER PRIMARY KEY,
  session INTEGER NOT NULL REFERENCES session(id),
  seq INTEGER NOT NULL,            -- 会话内序号，仅用于排序与显示
  native_id TEXT,                  -- 源自带的 message/part/event id（定位符优先用它）
  source_key TEXT,                 -- 无原生 id 时的稳定键路径（见 §8.3）
  ts INTEGER,
  role TEXT,                       -- user / assistant / system / tool
  kind TEXT,                       -- text / reasoning / tool_call / tool_result / meta / attachment
  tool TEXT,
  text TEXT,
  last_raw_line INTEGER NOT NULL,  -- 最后一次影响这条内容的原始行（1 起）
  replay_upto_line INTEGER,        -- 增量日志源：重建这条内容所需的日志水位
  UNIQUE(session, seq));

CREATE VIRTUAL TABLE event_fts USING fts5(
  text, content='event', content_rowid='id', tokenize='unicode61');
```

**索引只收 `current`，不收 `revisions/`。** 理由：revision 是被取代的旧快照，索引它们会让
同一段话出现多条重复命中。revision 仍在 manifest 里可见、可用 `chats show --file` 直接打开。
这条与 `UNIQUE(host, source, session_id)` 是配套的，两者一起改或一起不改。

**只索引 `role=transcript` 的 artifact。** auxiliary 只用来补 session 的工程信息。

中文分词：`unicode61` 对中文按字切，短语搜索靠 FTS5 phrase query 仍可用；不引第三方分词器
（stdlib-only）。这是已知的精度折扣，记在这里，别当 bug 报。

### 8.1 定位符必须稳定

**`seq` 是派生序号，不能单独当定位符**：重放规则一变、插入一条 meta、源被重写，它就漂移了。
基线文档要的是 `source/session/message/tool` 身份。

定位符形如 `<source>/<session_id>#<ref>`，`ref` 按优先级取：

1. `native_id` —— 源自带的 id（claude 的 `uuid`、codex 的 `payload.id`、opencode 的
   `message.id`/`part.id`、copilot-cli 的事件 `id`、vscode 的 `requestId`/`responseId`）；
2. 拿不到原生 id 时用 `source_key`（稳定键路径）；
3. 都没有才回落 `s<seq>`，且这种情况要在 `show` 的输出里注明"序号定位，可能漂移"。

### 8.2 五个源怎么映射到这个模型

| source | role 从哪来 | kind 判定 | ts |
|---|---|---|---|
| claude | `type`（user/assistant）；`message.role` 兜底 | `message.content[].type`：text / thinking→reasoning / tool_use→tool_call / tool_result | `timestamp` ISO8601 |
| codex | `payload.role` | `payload.type`：message / reasoning / function_call→tool_call / function_call_output→tool_result | 行首 `timestamp` |
| opencode | `message.data.role` | `part.data.type`：text / reasoning / tool→按 `data.state` 拆 call/result / patch / file | `time_created` 毫秒 |
| copilot-cli | 事件 `type` 前缀（`user.` / `assistant.` / `system.`） | `type` 后缀 | `timestamp` |
| copilot-vscode | 重放后 `requests[].message`=user、`.response[]`=assistant | response 元素的 `kind` | `timestamp` / `responseTimestamp` |

**统一模型不吞掉源的差异**：映射不上的一律进 `kind='meta'`、`text` 存该行的紧凑 JSON，
行号照记。宁可当 meta 进索引，也不要丢掉一行——丢了就再也回不去了。
JSON 解析失败的坏行同样进 meta，存原始行前 500 字符。

### 8.3 增量日志源（copilot-vscode）的定位语义

**"最后一次写入该内容的那一行"只能当导航提示，不能当原文定位。** 一条 assistant 消息可能由
`kind:0` 快照加多个不连续 delta 拼成，打开最后一行既看不到完整消息、也未必含搜索命中的片段。

所以对它分三个字段：

- `last_raw_line`：最后一次影响这个逻辑节点的行——**只用于"打开证据附近"**；
- `replay_upto_line`：重建这条消息所需的日志水位；
- `source_key`：`requests[i]` / `response[j]` 这类稳定键路径，兼作无原生 id 时的定位 ref。

`show` 的行为**按源区分**（§9）。否则只能宣称"回到某条 delta"，不能宣称"返回原消息"
——那样 §10 的第 2 条验收过不了。

## 9. 命令面

```
hub chats collect [--source S]... [--verify] [--dry-run] [--vault V] [--host H]
hub chats index   [--rebuild] [--source S]...
hub chats search  <查询> [--source S] [--project P] [--role R] [--limit N]
hub chats show    <source>/<session_id>#<ref> [--context N]
hub chats status
```

`show` 的语义按源分：

- **普通 JSONL 源**：返回 `last_raw_line` 那一行的原始内容（`--context N` 前后各多给 N 行）。
- **copilot-vscode**：重放到 `replay_upto_line`，取出 `source_key` 指向的逻辑消息，
  **返回重建后的原消息**，并附上最后写入行号与参与重建的证据行号。

原始层文件缺失（金库被搬走等）→ 明确报"证据文件不在"，**不许静默返回空**。

`status` 打印 §3.2 那三行边界，外加每源会话数、字节数、revision 数、最后导入时间、
索引新鲜度（多少 entry 的 sha 与索引不符）。

## 10. 阶段1 验收（照基线文档抄）

1. **重复导入零新增**：连跑两次 `chats collect`，第二次 `Writer.written == []`。
2. **原文定位**：随机抽 20 条 `search` 命中，`show` 都能返回**完整的原消息**（vscode 走重放），
   且内容与命中片段吻合。
3. **五个源全覆盖**：真机各出至少一个会话进索引。
4. **索引可重建**：`--rebuild` 后 session/event 计数与重建前一致。
5. **零泄漏**：`git status` 在金库里看不到任何 chats 路径；人为 `git add -f` 一个 chats 文件后
   `hub sync` 被 `ChatsTracked` 拦住。
6. **崩溃安全**：复制中途杀掉进程，金库里那份旧证据**完好无损**（临时文件被清或残留，
   但 current 不是半截文件）。

## 11. 明确不做

- 不做摘要、不做疑惑提炼、不做知识笔记（基线文档的阶段3，另立）。
- 不做跨设备同步；**本轮没有任何离机备份**（§3.2）。
- 不做回溯脱敏（它是 chats 进 git 的前置条件，不是本层的职责）。
- 不引第三方依赖：中文分词、embedding、向量检索一律不在本层。
- 不改 SCHEMA 的版本号：chats 目录 SCHEMA 早就写着，本设计是把它填上，不是改契约。
- 不加 `raw_root` 配置——将来真要换存储位置时再谈，现在加是无谓扩展。

## 12. 评审改了什么（v1 → v2）

codex 2026-08-14 评审，五个自审点里两点被否、外加四个实现前 blocker。逐条：

| v1 的说法 | v2 |
|---|---|
| 原始层放金库＝「别丢、换机照它还原」 | **假承诺**。gitignore 掉的东西没有任何离机备份 → §3.2 诚实边界 + status 三行 |
| 「将来解禁只需改一行 gitignore」 | **假承诺**。加密后增量文件失去 git delta，800 MB 逐日变化会撑爆 git 历史 → 不预先承诺同步实现 |
| 幂等强判据是 `(bytes,sha256)`，但 T3 又写成 `(size,mtime)` 直接确认未变 | **自相矛盾**。统一为：强身份 sha、快路径 stat、`--verify` 对冲 |
| `copy_binary` 直接 `wb` 打开目标 | **真 bug**：中断即截断唯一副本；先 hash 后 copy 之间源仍在长 → §6.1 原子写 + 边拷边算 |
| GENERATED 用「新 lines >= 旧 lines」判增长 | **不成立**：行数相同可能就地更新，行数增加可能同时删旧行 → sha 不同一律留 revision |
| vscode 的 `raw_line` = 最后写入行，`show` 逐行返回 | **不成立**：一条消息由快照+多个 delta 拼成 → 三字段拆分 + `show` 按源分流重放 |
| 定位符 `<source>/<session>#<seq>` | **会漂移** → 优先原生 id，其次 source_key，最后才 seq |
| 索引遍历每个 manifest entry 建 session | 与 revision、与 `workspaces.toml` 都冲突 → 只索引 current + 只索引 `role=transcript` |
| 「`hub/collect/` 不得引用 chats 路径」 | **自相矛盾**（现有代码正靠引用它来跳过）→ 改钉行为三条 |
| root 不存在返回 `[]` vs 配了不存在要非零 | **前后矛盾** → 未配置合法、配了不在则在任何写入前停 |
