# 交接：hub 原始对话库（chats）—— 11/13 任务已落地，未提交（2026-08-14）

> 冷启动读这一份就够。要细节再翻
> `docs/specs/2026-08-14-hub-chats-raw-store.md`（**v2**，权威设计）
> 和 `docs/plans/2026-08-14-hub-chats-raw-store.md`（**v2**，含每个任务的执行记录与派活方式的实测结论）。

## 一句话现状

**五个平台的对话已经能收进金库并建成可检索的索引，代码 2090 行 + 测试 1730 行，
`pytest tests/hub` 725 passed / 3 skipped。** 但**一行都还没提交**，
而且**还没在真机上跑过一次**——`hub chats` 这个命令入口（T11）还没写，
所以现在没有任何办法从命令行用它。剩下的活见「三个开口项」。

## 题目从哪来（别把它当"备份对话"做）

来自用户 Obsidian 里的 `AI 记忆、知识笔记与 Skill 演化系统实施基线.md` 的**阶段1：原始对话库**：

> 完成统一事件模型、只读导入、幂等、全文搜索、敏感 Scope 和原文定位。
> 重复导入零新增；随机抽取的结论能够返回原消息。

基线文档 §三.1 把它定成「唯一原始证据库」：所有记忆、摘要、知识点、接续包和 Skill 候选
都必须能通过 `source/session/message/tool` **返回原文**；派生系统损坏可以重建，原始记录不能被摘要代替。

**所以这一层不做摘要、不做提炼、不改写正文。** 后面那些（疑惑提炼、知识笔记、建链）是基线的
阶段 3/4，另立，别混进来。

用户 2026-08-14 当面给的优先级：**跨平台统一检索 > 蒸馏记忆的素材 > 别丢**。
第三项**本轮只做到一半**，见下面「诚实边界」。

## 用户拍过的板（别再自行改）

1. **本轮明文对话只落本机，不进 git。** 解禁条件是静态加密 + 回溯脱敏，都不在本轮。
2. 五个源全收：Claude Code / Codex / opencode / Copilot CLI / Copilot VS Code。

## 诚实边界（**最容易被写漂亮的地方**）

- **本轮没有任何离机备份。** chats 被 `.gitignore` 排除，所以它只是"位于金库目录里的
  本机证据"。删仓库、重新 clone、`git clean -fdx`、磁盘坏都会让它一起没。
  **不许在任何文档、命令输出、提交信息里把它说成"换机照它还原"。**
  `hub chats status`（T11 待写）必须原样打印这三行：

      storage:            local-only
      off-device backup:  none
      git tracking:       blocked

- **不许承诺"将来解除 gitignore 就能同步"。** 静态加密会让增量文件失去 git delta 优势，
  一个逐日变化的几百 MB 目录会迅速撑爆 git 历史。将来的离机方案更可能是不可变分块 /
  对象存储 / 专门的备份协议。目录布局可以原样保留，**同步实现不能预先承诺**。
- 中文检索有一处如实记下的代价：英文**前缀**匹配没了（`calib` 匹配不到 `calibrate`），
  那是 unicode61 本来的行为；要前缀用 FTS5 自带的 `calib*` 语法。

## 本机五个源的实测形态（2026-08-14 勘探，别凭想象重推）

| source | 落盘形态 | 实测量 |
|---|---|---|
| claude | `~/.claude/projects/<编码工程路径>/*.jsonl` | 97 会话 / 117 MB |
| codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` + `archived_sessions/` | 747+17 / 678 MB |
| opencode | `~/.local/share/opencode/opencode.db`（**SQLite，没有文件可拷**） | 103 会话 / 2171 消息 / 8703 part |
| copilot-cli | `~/.copilot/session-state/<uuid>/events.jsonl` | 2 会话（其中 1 个根本没有 events.jsonl） |
| copilot-vscode | `%APPDATA%/Code/User/workspaceStorage/<hash>/chatSessions/*.jsonl`（**增量日志**） | 105 文件 / 26 MB / 40 工作区 |

合计约 **820 MB**，每天在长。金库现在 69 MB。

## 架构（两层，职责不能混）

```
原始层  <vault>/<host>/<tool>/chats/     append-only，字节级原样，绝不删
   │                                      ← 唯一事实源，坏了没得重建
   │  hub chats index
   ▼
派生层  ~/.hub/chats-index.db             SQLite + FTS5，本机运行态
                                          ← 随时可以删了重建，不进金库
```

**`hub chats collect` 是独立命令，不并进 `hub collect`。** 四条理由任何一条单独成立：
镜像语义（源没了就删）与 append-only（源没了必须留）方向相反；量级差两个数量级；
`collect` 结尾的 `scan_tree` 会逐文件 `read_bytes` 整个 `<host>/`；git 归属不同。

## 文件地图

```
hub/digest.py                     99   流式摘要 + copy_and_digest（边拷边算）
hub/chats/
    model.py                      91   共享接口：Artifact / Entry / SourceReport
    paths.py                      47   chats_dir 边界断言（容器经链接逃出金库就抛）
    manifest.py                   68   manifest.toml 读写（表名走 tomlout.quote_key）
    collect.py                   203   **append-only 四态状态机（承重件）**
    gitignore.py                  37   金库根 .gitignore 幂等写入
    index.py                     357   SQLite + FTS5 索引 + fts_text（中文逐字切分）
    sources/  (6 文件, 380)            五个源的发现器 + 注册表
    parse/    (7 文件, 782)            五个源 → 统一事件模型
tests/hub/test_chats_*.py       1730   11 个测试文件
```

改动到的既有文件：`hub/writer.py`（+copy_binary/rename/write_bytes）、
`hub/secrets_scan.py`（+skip_dirs）、`hub/collect/__init__.py`（scan_tree 跳过 chats）、
`hub/backend.py`（+ChatsTracked 闸）、`hub/model.py` + `hub/vault.py`（+ToolSources.chats）、
`hub/tomlout.py`（+quote_key）、`hub/schema_md.py`（§12 chats 文案改成实际状态）。

## 设计里几条不许动的东西

1. **append-only 四态**：`unchanged` 零写入 / `grown` 覆盖 / `preserved` 旧的存进
   `revisions/` 再写新的 / `gone` 一个字节不动只标 `source_gone`。
   源侧没了的**金库里必须留着**——那是这一层存在的全部理由。
2. **COPY 有增长证明（前缀 sha），GENERATED 没有。** opencode 导出的是数据库快照，
   没有前缀单调性（message 的 data 会就地更新），所以它 **sha 一变就一律留 revision**。
   v1 曾用「新 lines >= 旧 lines」判增长，**那条已作废**（行数相同可能是就地更新，
   行数增加也可能同时删了旧行），别再实现回去。
3. **快路径只是"快速未变提示"，不是内容等价证明。** `(源 size, mtime_ns)` 相同就跳过，
   `--verify` 是它的对冲。
4. **索引只收 `role=transcript` 的 current**，不收 `revisions/`、不收 auxiliary
   （`workspaces.toml` / `workspace.yaml`）。
5. **定位符不许只用 `seq`**（派生序号会漂移）：优先源原生 id，其次 `source_key`，
   最后才 `s<seq>` 且要注明"可能漂移"。

## 踩过的坑，按"最容易再犯"排序

**① 中文检索原本是坏的，而且坏得不声不响。** spec 原写"`unicode61` 按字切、短语查询仍可用"
——**错的**。实测（本机 3.50.4）它把**连续 CJK 合并成一个 token**：整串
「超声波流量计标定阈值怎么调」是一个词，「标定」「阈值」「超声波」**一个都搜不到**。
实测过的三条路：

    方案                  标定  阈值  超声波  流量计标定  threshold  calib
    unicode61 原样         ✗    ✗     ✗      ✗          ✓         ✗
    trigram                ✗    ✗     ✓      ✓          ✓         ✓
    unicode61 + 逐字切分    ✓    ✓     ✓      ✓          ✓         ✗

选了第三条。trigram 救得了三字以上但**二字词搜不到**，而中文二字词最常用。
**查询侧必须 import `index.fts_text`，不许自己再写一份**——索引切了查询没切，
中文永远零命中**而且不报错**。

**② 那个 FTS 孤儿删不掉，`integrity-check` 还报通过。** FTS 列存的是切分后的文本，
与 content 表里的 `event.text` 不是同一个串，所以普通 `DELETE FROM event_fts` 会去 content 表
取原文重新分词来抵消——抵消的是**错的 token**。实测后果：孤儿**搜得到、指向已删除的 event**。
必须走 FTS5 的 `'delete'` 命令并把当初索引进去的那份文本原样喂回去。

**③ `copy_binary` 原来直接以 `wb` 打开目标。** 复制中途失败/断电就把**不可重建的唯一副本**
截断了；而且"先 hash 源、再 copy"两步之间源还在被追加，台账记的 sha 不是落盘字节。
现在是：同目录临时文件 → 边拷边算 → 拷贝前后各 stat 一次源（变了重试一次，仍变抛
`SourceChangedWhileCopying`）→ fsync → `os.replace` → **manifest 最后写**。

**④ 快路径看不见"金库里那份没了"。** 它只比**源**的 stat，金库那份被误删/被同步工具清掉/
磁盘坏，它一概看不见，台账继续记着"有"、每次收集继续报 unchanged。
现在 `_vault_copy_ok()` 日常做一次 `exists()`，`--verify` 才比对金库那份的 sha，
对不上就照源重写并报进 `restored` 态。

**⑤ 闸的失败方向。** `tracked_chats` 原来按子串 `"/chats/" in l` 判（漏掉顶层 `chats/foo`，
git ls-files 给的路径没有前导斜杠），且 `git ls-files` 失败时返回 `[]`——那会被读成
"证明了里面没有对话"。现在按**路径组件**判，失败**抛**。

**⑥ 只跑针对性测试会漏。** T12 往 `publish()` 加了 `tracked_chats`，
而 `test_backend_retry.py` 的 `_install()` 只给 `tracked_gitlinks` 打了桩——两道闸
**都不走 `_run`**，假 git 拦不住，`GitBackend(Path("x"))` 那个不存在的 cwd 直接
`NotADirectoryError`。**每件活收口前跑一次全量 `pytest tests/hub`。**

## 派活方式的实测结论（下一个人照抄，别再交学费）

- **这台机器上不能并行派 opencode。** 六件独立任务同时派，五件在 320–430s 全部 idle 超时
  且**零落盘**，无一例外卡在「开始用 python 读文件」那一步（Esafenet 每次读都要解密，
  六个实例互相饿死）。单独跑的每一次都跑满并交付。**串行，一次一件。**
- **必须给它"落盘配方"**，否则它会把大半时间烧在跟转义搏斗上（heredoc 炸、`write_text`
  把 CRLF 翻倍成 `\r\r\n`）。同一个 session：没配方那轮 495 秒只产出 9 行，给了配方直接
  干完两个文件。配方＝**内容先用它自己顺手的方式写到仓外临时目录，再用一行
  `dst.write_bytes(src.read_bytes())` 搬进仓**。仓内写入仍然只走 python，规矩没破。
- **回执报 `timeout` 不等于活没干。** opencode 干完会静默挂着，被 300s 沉默预算判超时。
  判断有没有进展**看文件落没落盘**，别看回执。被掐了用 `ai-room resume --session <id>`
  续接，**不要重发**（重发＝把已计费的那一轮再买一次）。
- **prompt 不能经 bash。** 正文里的反引号会被双引号内的命令替换执行，整条 ask 静默不发出
  （好在这种情况没计费）。写进文件、用 python 直接传 argv。
- **加密态怎么验**：动手前 `esafenet-baseline.ps1 snapshot`，干完 `check -Fix`
  （在金库 `shared/scripts/`）。**注意它只判"原来加密、现在明文"，新建文件不在基线里**，
  得单独用 PowerShell 查头字节 `e0 a8 91 e7 d8 f2 05 ac`。本轮全部文件查过，无一脱密。

## 三个开口项

### ① T11：`hub chats` 命令入口（**没有它，这套东西从命令行用不了**）

计划 T11 那一节写死了命令面。要点：`collect` 打印每源 new/grown/unchanged/preserved/
gone/**restored**/skipped 计数，preserved 要醒目但退出码仍是 0；
`status` **必须原样打印上面「诚实边界」那三行**；已配置的源路径不存在 → 非零且在任何写入前停。

### ② T10：`search` / `show`（检索与回原消息）

计划 T10 那一节。两条不许妥协：查询侧 **import `index.fts_text`**；
`show` **按源分流**——普通 JSONL 返回 `last_raw_line` 那一行原始内容，
**copilot-vscode 必须重放到 `replay_upto_line` 并返回重建后的原消息**，
否则只能宣称"回到某条 delta"，基线那条"随机抽取的结论能返回原消息"过不了。

VS Code 的重放语义是从**官方源码**扒出来的，以它为准（spec 只写了前三种，漏了第四种）：
`kind:0` 全量快照 / `kind:1` 设值 / `kind:2` push（先把数组截到 `i` 再 append）/
**`kind:3` 删除键**；另外 response 数组也可能被 `kind:1` 整个替换。

### ③ T1 + T13：digest 单测 与 **真机验收**

- T1 是给 `hub/digest.py` 补独立单测（它现在只被 writer 的测试间接覆盖）。
  这件有一个可续接的 opencode session：`ses_000eccbefffermnvMSH8EpgcVs`。
- **T13 是人工闸，子 agent 不许自己跑。** 照 spec §10 逐条：五源全量收一遍 → 再收一遍
  **零新增** → 建索引 + `--rebuild` 计数一致 → 随机 20 条命中 `show` 回原消息
  （含至少 3 条 vscode 的重放）→ 金库 `git status` 干净且 `git add -f` 被 `ChatsTracked` 拦住
  → 崩溃安全（复制中途杀进程，旧证据完好）→ `hub collect` 计时确认没去读 chats。

## 恢复入口

1. 读本文件 + spec v2 的 §5（状态机）、§8（索引与定位符）、§12（v1→v2 改了什么）。
2. **动手前先看「诚实边界」那一节**，那几句话是用户拍过板的，不是修辞。
3. 派活前读计划的 Global Constraints（Esafenet 写入路径、commit 不许带 AI 名字、
   本仓个人项目**照常写注释**）——逐字抄进 prompt，不明说就等于没说。
4. **本轮全部改动尚未提交**，`git status` 里 12 个改动文件 + 15 个新文件/目录。
   提交身份 `patrick1099`（本仓 `git config --local` 已定），
   **任何 AI 的名字都不许进 commit**。
