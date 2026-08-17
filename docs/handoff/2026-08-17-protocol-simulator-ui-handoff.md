# 交接：protocol-simulator 规划成型 + 两处卡点（2026-08-17）

> 冷启动读这一份 + `treasury-vault/shared/plugins/xinao-csb-skills/skills/protocol-simulator/ROADMAP.md` 就够。
> 本轮**一行功能代码都没写**，产出只有规划文档和两处诊断。别以为有实现可以接着跑。

## 一句话现状

ROADMAP spec 写完了，A~F 六条轨道齐备，插件 bump 到 **0.4.2**。
本轮一度卡在两处（GitHub 推不上去、`hub sync` 被闸拦死），**两处都已解决并推送**，
`hub sync` 恢复正常。下面「二、两处卡点」保留完整诊断，因为其中一处是真缺陷、
修法值得留档。

## 提交状态（全部已推送）

| 仓 | 提交 |
|---|---|
| `treasury-vault/shared/plugins/xinao-csb-skills`（子仓） | `cd7ddbb` → `23a874d`，plugin.json bump 0.4.2 |
| `treasury-vault`（金库） | `2d7dd0d` → `96292ce` → `3845764`（hub sync 自动提交） |
| `treasury`（hub 本体） | `b3d6ffb`（本文件）→ `e927e15`（gitignore 范围修复） |

⚠️ `cd7ddbb` / `2d7dd0d` 两条被系统时钟倒签成 2026-08-14，见「三、坑 1」。未改写历史。

---

## 一、本轮定下来的三件事

全部已写进 ROADMAP §4，这里只给结论和「为什么」，细节去看原文。

### 1. 协议模型缺一根轴（ROADMAP §4.1 / E0）

用户说「本地协议这块得做拆分」但说不清拆什么。**答案是：拆 direction 和 operation。**

现模型只有 `down→request` / `up→response`。但固件 ctrl 字节还编了一个独立的操作维度
（本仓 `Code/App/Code/app/DebugUart/DebugUartUser.h:89`）：

```c
WX_CMD_DATA_READ     = 0x01,   //读数据
WX_CMD_DATA_WRITE    = 0x04,   //写数据
WX_CMD_DATA_OPT      = 0x05,   //主动上报或业务操作
WX_CMD_DATA_CONTINUE = 0x02    //多帧续传
```

`ctrl & 0x80` 是上下行，`ctrl & 0x0F` 是操作。`framer.py:167` 只按方向给 `0x01`/`0x81`。

**所以 wx 命令 JSON 里「写方向是个 `remaining_bytes` 字节袋」不是字段漏录，是模型少了一维。**
不加轴，写字段无处安放，自动生成写表单这条路根本走不通。

处理方式：**一 DID 仍是一份 JSON**，在文件内部按 read/write/opt/continue 划分。物理拆多文件会造成命令码注册冲突。

### 2. 自动识别只有一层需要「猜」（ROADMAP §4.2 / F2）

用户要「收到原始数据就尝试解析，再把数据与实际内容对应列出来」。拆成两半：

- **F1 字节↔内容对照表 —— 几乎免费。** `kernel/core/types.py:7` 的 `FieldValue` 已经带
  `offset` / `consumed_bytes` / `raw_bytes` / `display_value`。数据全在，只差一个视图。
- **F2 自动识别 —— 就是原来 deferred 的 C4（Phase 1.6b）。** 用户主动要了，解除 deferred。

**关键判断：识别分四层，只有「哪份协议」那一层有歧义**（`xinao-jisheng/v3` 与
`xinao-langfang/v2` 同为 `xinao_remote`、命令码完全相同）。帧格式靠帧头+校验确定，
命令码在帧头里确定，字段解码已有。

**所以原来那句顾虑「会把工具从执行器变推断器」是可以化解的**：把推断限制在第 2 层、
且强制输出候选而非断言，工具性质不变。这条别再重新纠结一遍。

### 3. GUI 一律先做模块 demo（ROADMAP §4.3）

用户原话：「我怕你一口气做完变成大粪了。」

demo 阶梯 D1（只读对照表）→ D2（describe 出口）→ D3（自动识别）→ D4（写表单，最危险，最后）。

**两条硬约束，第二条才是防大粪的真正机制：**

1. demo 的产出是**结论不是代码**，代码允许全部丢弃，验收标准是「问题答没答上」。
2. **demo 绝不许自己实现协议逻辑，只能调 kernel。** 一旦某个 demo 图省事在界面侧自己算了
   长度、拼了字节、判了 CRC，就长出一套影子实现；四个 demo 合并时面对的是四套各自漂移的
   协议逻辑——**那才是「大粪」的实际成因**。判据：demo 目录出现任何字节拼装 / 校验计算 /
   偏移推算即违规退回。

GUI 技术栈**故意未定**，到 D1 真正开工时再定，届时先加载 `vibe-apps` skill。不要提前选型。

---

## 二、两处卡点（**均已解决**，保留诊断供留档）

### 卡点一：GitHub 推不上去 ✅ 已解决（等网络恢复后重推即可）

```
fatal: unable to access 'https://github.com/patrick1099/xinao-csb-skills.git/':
Empty reply from server
```

重试一次直接挂到超时。提交在本地是安全的，网络通了 `git push` 两个仓即可。

**注意** `hub/backend.py:112` 那段既有注释的结论：金库是私有仓，每次 git 操作多吃一轮
401 挑战，在抖动的代理节点上单次失败率约 1/6，**"不是路由规则的问题，别去改 Clash"**。

### 卡点二：`hub sync` 被 chats 闸拦死 ✅ 已解决

报错：

```
hub.backend.ChatsTracked: 金库索引里出现原始对话库(明文密钥/公司源码,进 git 不可撤销):
  - 2025-bg-016/chats/.gitkeep
  - 2025-bg-016/claude/chats/.gitkeep
  - 2025-bg-016/codex/chats/.gitkeep
  - shared/chats/.gitkeep
```

**根因：这道闸是未提交的在制品。**

```
$ git log --all -S"tracked_chats"
(空)
```

它从没进过任何提交，是 `~/treasury` 工作区里 11 个文件那批未提交改动的一部分
（`secrets_scan` / `writer` / `tomlout` + 测试，属于「加密进金库」那条线，见
`docs/handoff/2026-08-11-hub-b-handoff.md` 的开口项 ①）。

**所以本轮早些时候 sync 能过、后来过不了——因为那时它还不存在。**

**它拦的四个东西全是 0 字节占位符**，那四个 `chats/` 目录在工作区里除了 `.gitkeep`
一个文件都没有。实质零泄漏。

判定逻辑本身没写错：`l.split("/")[:-1]` 取目录组件，按它自己的规格（任何 `chats/`
下的已跟踪路径）命中是正确行为。

**真正的问题是它从没在真金库上跑过。** 配套测试 `tests/hub/test_chats_git_guard.py`
（同样未跟踪）只用 `tmp_path` 造合成仓，**没有覆盖 `.gitkeep` 场景**。撞上真库里这四个
存量占位符是它的第一次真实运行。

#### 顺带查出的真缺陷：两层防线的作用范围对不上

设计是两层的，`hub/chats/gitignore.py` 的模块 docstring 讲得很清楚：

> `.gitignore` 只是"建议"。它哪天被改坏、或某个文件早被 `git add -f` 强行加进索引，
> 失败方向就是 800 MB 明文对话静默推上 GitHub ⋯⋯ 所以这道规则是"拦住"的第一层；
> `backend.py` 那道闸是"拦不住时"的第二层、最后一层。

**第一层写好了，但从没在真金库上跑过**（整个特性都还没提交），所以此刻
`grep -n "chats" ~/treasury-vault/.gitignore` 无输出。这部分是「未执行」，不是「没设计」。

**真缺陷在这里：** 第一层的模式是

```python
_BLOCK = (... "*/*/chats/\n")
```

gitignore 里 `*` 不跨 `/`，所以 `*/*/chats/` **只匹配两级深度**：

| 目录 | 深度 | `*/*/chats/` | 代码闸 `tracked_chats` |
|---|---|---|---|
| `2025-bg-016/claude/chats/` | 2 | ✅ 匹配 | ✅ 命中 |
| `2025-bg-016/codex/chats/` | 2 | ✅ 匹配 | ✅ 命中 |
| `2025-bg-016/chats/` | 1 | ❌ **漏** | ✅ 命中 |
| `shared/chats/` | 1 | ❌ **漏** | ✅ 命中 |

**代码闸按路径组件判、任意深度都抓；`.gitignore` 只覆盖两级。四个里第一层漏掉两个。**

而 `hub/scaffold_vault.py:6-8` 恰恰在**两种深度上都建 chats 目录**（`_SHARED_DIRS` →
`shared/chats`，`_CLAUDE_DIRS`/`_CODEX_DIRS` → `<host>/<tool>/chats`）。

失败方向仍是安全的（第一层漏掉的会被第二层拦成硬死锁，不是泄漏），但后果是：
真往 `shared/chats/` 放个文件，`git add -A` 会收进索引，然后**每一次 `hub sync` 都被
永久拦死**，必须人工 `git rm --cached` 才能解。

#### 实际修法（**已执行**，2026-08-17）

用户批准后按两步做的，顺序不能反——**先写 `.gitignore` 再解除跟踪**，否则 `publish()`
里的 `git add -A` 会立刻把它们加回来（`test_rm_cached_rescues_and_publish_then_succeeds`
正是记这一点的）。

1. **放宽第一层的范围**（`treasury` `e927e15`）：`_BLOCK` 的 `*/*/chats/` 改成 `chats/`
   ——不带前导斜杠 + 带尾部斜杠 = 任意深度的同名目录，**与代码闸 `tracked_chats` 同范围**。
   模块 docstring 里补了为什么。
2. **补回归测试**：新增 `test_gitignore_covers_every_depth_the_code_gate_catches`，
   同时覆盖一级（`shared/chats/`、`win/chats/`）和二级（`win/claude/chats/`）。
   **原有 5 条用例全是二级深度，所以整个缺陷漏了过去。**
3. **走真实代码路径落到金库**：调 `ensure_chats_ignored(vault, Writer())` 生成 `.gitignore`，
   没有手写那三行——预演与真实执行共用同一条写路径。
4. `git rm --cached` 四个 `.gitkeep`。文件仍在盘上（解除跟踪 ≠ 删文件，已逐个确认）。

验证：

- 新测试在**旧模式下如期失败**（`shared/chats/notes.jsonl 漏出第一层`）、新模式下通过
  ——一个只会通过的测试不算数，专门验了这一步。
- `pytest tests/hub` **726 passed / 3 skipped**（原 725，+1 新测试）。
- `hub sync --refresh` 恢复正常：`memory 视图已重算 {'written': 5}`、`插件: 成功 5 / 失败 0`，
  自动产出金库提交 `3845764`。

**没有选「在闸里给 `.gitkeep` 开例外」这条路**——那只是让闸闭嘴，两层范围对不上的问题还在，
下次换个真文件落进 `shared/chats/` 会原样复发。

---

## 三、三个坑（下次最容易再犯）

### 1. 机器时钟中途被校正，两条提交倒签了 3 天

同一个仓，本轮的提交与 30 秒后的探针提交：

| | 时间戳 |
|---|---|
| 本轮提交 `cd7ddbb` | `2026-08-14 17:12` |
| 探针提交（30 秒后） | `2026-08-17 08:47` |

查过了：无 `GIT_*DATE` 环境变量，`~/.githooks` 全是 `_passthru` 接力壳不动日期，金库
local config 干净，新建空仓提交日期正确。**不是 git 的问题，是系统时钟慢了 3 天后被校正。**

后果：`cd7ddbb` / `2d7dd0d` 两条提交被倒签 3 天。**这套体系（记忆、handoff、spec）
到处按日期定位，写日期前先 `date` 核一下，别照抄上游摘要里的日期。**
ROADMAP 里属于本轮的日期已订正为 08-17；§1~§3 的 2026-08-14 是真实的既有裁定，未动。

### 2. 别采信子 agent 的自述——本轮又中了一次

本轮请 codex 做只读架构评审（`codex exec -s read-only`），结论质量很高、核心判断经复验成立。
**但它自己有两处错：**

1. **漏了 `WX_CMD_DATA_CONTINUE = 0x02`** —— 操作轴是 4 个值不是 3 个。
2. **举 C520 例子时引的是另一个产品的固件**（`20260525-xinao` 仓）。

两处都是逐条复验时抓出来的。`-s read-only` 这个沙箱选项值得保留——它结构性地保证
子 agent 不可能写盘，绕开了 Esafenet 脱密那整类风险。

### 3. 取材必须认准产品线

两个仓都有 `DebugUartUser.c`，但 DID 表不同：

| | DID 数 | 独有 |
|---|---|---|
| `Commercial_Ultrasonic_Modular`（本线，商用超声波） | **31** | `0006` `1006` `1007` `AAF4` |
| `20260525-xinao` | **33** | `0008` `0814` `0815` `F005` `F007` `F008` |

共有 27 个。C518/C519/C520/C525 两边都有，**但布局未必相同**。补 wx 写方向字段时照错仓
取材，就正好犯了 ROADMAP §3 那条「不同产品线该分开」裁定要避免的混线。

---

## 四、诚实边界

- **`hub/chats/` 那一整套在制品，本轮只动了 `gitignore.py` 的 `_BLOCK` 一行 + 它的测试**
  （用户批准后），其余一个字没碰。期间作者把那批在制品提交并推送了（`f554076`→`5be06a4`），
  所以我的修复是叠在正式代码上、不是改别人的未提交工作区。
- **同目录下还有一份未跟踪的 `docs/handoff/2026-08-14-hub-chats-handoff.md`**，是写 chats
  那套的会话留下的，比本文权威得多（含 spec / plan 指针、五个源的实测形态、完整文件地图）。
  **动 hub chats 之前先读它。** 它自己的「诚实边界」一节写明：本轮无任何离机备份，
  不许在任何文档或提交信息里把 chats 说成"换机照它还原"。
- **ROADMAP 是规划不是设计。** E2 的 describe DTO 到底长什么样、字段角色标记怎么编码、
  operation 轴在 JSON 里的具体键名——**全都没定**。谁开工谁定，别把 ROADMAP 当设计文档读。
- **codex 的评审是纯静态只读分析**，没跑过任何代码，它对写布局的描述（参数组 / 门控字节 /
  副作用）来源是读固件，未经真机验证。
- **轨道 A/B 的工作量我没估过。** 只知道 A1 还差 26 个 DID、csb.c 有 2602 行，没有工时判断。
