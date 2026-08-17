# 交接：protocol-simulator 规划成型 + 两处卡点（2026-08-17）

> 冷启动读这一份 + `treasury-vault/shared/plugins/xinao-csb-skills/skills/protocol-simulator/ROADMAP.md` 就够。
> 本轮**一行功能代码都没写**，产出只有规划文档和两处诊断。别以为有实现可以接着跑。

## 一句话现状

ROADMAP spec 写完了，A~F 六条轨道齐备，插件 bump 到 **0.4.2**，两个仓都**已本地提交**。
**但收尾的两步都卡住了，且都不是代码问题**：GitHub 推不上去；`hub sync` 被一道**未提交的新闸**拦下。

## 提交状态

| 仓 | 提交 | 推送 |
|---|---|---|
| `treasury-vault/shared/plugins/xinao-csb-skills`（子仓） | `cd7ddbb` + plugin.json bump 0.4.2 | ❌ 未推 |
| `treasury-vault`（金库） | `2d7dd0d` | ❌ 未推 |
| `treasury`（hub 本体） | 本轮**没提交**，只加了本文件 | — |

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

## 二、两处卡点（下一个人要处理的）

### 卡点一：GitHub 推不上去

```
fatal: unable to access 'https://github.com/patrick1099/xinao-csb-skills.git/':
Empty reply from server
```

重试一次直接挂到超时。提交在本地是安全的，网络通了 `git push` 两个仓即可。

**注意** `hub/backend.py:112` 那段既有注释的结论：金库是私有仓，每次 git 操作多吃一轮
401 挑战，在抖动的代理节点上单次失败率约 1/6，**"不是路由规则的问题，别去改 Clash"**。

### 卡点二：`hub sync` 被一道未提交的新闸拦下

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

#### 建议修法（**未执行**，等用户拍板）

```bash
cd ~/treasury-vault
git rm --cached "2025-bg-016/chats/.gitkeep" "2025-bg-016/claude/chats/.gitkeep" \
                "2025-bg-016/codex/chats/.gitkeep" "shared/chats/.gitkeep"
```

删 `.gitkeep` 是安全的：`hub/scaffold_vault.py:6-8` 里 `chats` 由 scaffold 自己建，不靠 git 保留。

**外加把 `_BLOCK` 的模式放宽到覆盖两种深度**（`*/chats/` + `*/*/chats/`，或直接 `chats/`），
否则第一层永远漏掉一半。

**比在闸里给 `.gitkeep` 开例外正确**——开例外只是让闸闭嘴，两层范围对不上的问题还在。

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

- **`~/treasury` 那 11 个文件的在制品我一个字没动**，`hub/chats/` 那一整套也没动。
  它不是我的活，闸的去留和 `_BLOCK` 模式怎么改由作者定。
- **同目录下还有一份未跟踪的 `docs/handoff/2026-08-14-hub-chats-handoff.md`**，是写 chats
  那套的会话留下的，比本文权威得多（含 spec / plan 指针、五个源的实测形态、完整文件地图）。
  **动 hub chats 之前先读它。** 它自己的「诚实边界」一节写明：本轮无任何离机备份，
  不许在任何文档或提交信息里把 chats 说成"换机照它还原"。
- **ROADMAP 是规划不是设计。** E2 的 describe DTO 到底长什么样、字段角色标记怎么编码、
  operation 轴在 JSON 里的具体键名——**全都没定**。谁开工谁定，别把 ROADMAP 当设计文档读。
- **codex 的评审是纯静态只读分析**，没跑过任何代码，它对写布局的描述（参数组 / 门控字节 /
  副作用）来源是读固件，未经真机验证。
- **轨道 A/B 的工作量我没估过。** 只知道 A1 还差 26 个 DID、csb.c 有 2602 行，没有工时判断。
