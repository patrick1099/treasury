# hub 引用式密钥 · 设计(spec B)

> 2026-08-10。取代 `2026-07-12-hub-extractor-design.md` §「阶段 B = 加密层」的定位:
> **B 从「加密层」改成「引用层」。** 理由见 §1.3。
>
> **v2.1(2026-08-11)**——v1 有两处不成立(经 codex 评审重写),v2.1 追加人工授权开口。
> 见 §12 修订记录。**动工前先读 §11。**

## 0. 这份 spec 管什么

| | 子项目 | 状态 |
|---|---|---|
| A | 提取器:把本机家当收进金库 | 做完,合进 main |
| **B** | **引用式密钥:本体只存一处,别处只出现引用,执行时注入;Claude Code 原生工具的读取受 guardrail 约束** | **本文** |
| C | 加载器/注册器 skill | Plan 1/2/3 已推进 |

顺序变成 A → C → B。B 排最后不是因为不重要,是因为它要站在 A 的 `guard.py` 和
`secrets_scan.py` 上——那两块已经就位了(见 §8)。

## 1. 动机

### 1.1 原本的 B 卡在哪

旧设计里 B = 加密层,任务是「`chats/` 和 `sensitive` 记忆加密入库,金库里只暴露名字」。
它一直没动工,而被它挡着的东西越积越多:`chats/` 至今是空目录,`sensitive: true` 的记忆
在 `cli.py:49` 被**双重拒绝**(collect 静默跳过 + lint 报错)。

### 1.2 真正的病灶不是「没加密」,是「明文到处跑」

加密只解决**静态存储**。但密钥泄漏的实际路径根本不在金库里,而在:

- **对话正文**——AI 为了用密钥,得先把明文读进上下文,于是 transcript 里就有了。
- **下游副本**——`~/.mineru/config.yaml`、`~/.config/opencode/opencode.json`(实测含明文密钥)、
  ossutil 配置……每个应用都在自己家里存了一份明文。
- **顺手的调试输出**——见 §1.3。

对这三条路径,加密**一点用都没有**:密钥是被合法解密之后泄的。

### 1.3 一次真实事故(2026-08-10,本次会话)

立本 spec 的当天,AI 为了勘察 `~/.claude/secrets/` 的文件结构,自己写了一个
「只打印键名、值一律遮掉」的探测脚本。脚本有三条分支——标题/列表行、`key: value` 行、裸行。
markdown **表格行**(`| accessKeyId | LTAI... |`)命中了第一条分支,**被原样打印**。

结果:阿里云 `accessKeyId` 完整进了 transcript,`accessKeySecret` 泄了 30 位里的前 20 位。

三点值得钉死:

1. **写遮罩的和被遮罩的是同一个 AI,它自己漏了自己的分支。** 「让 AI 小心点别打印明文」
   这个方案在这里当场破产——不是它不想遵守,是它想遵守但写错了。
2. **`secrets_scan.py` 本来能抓到。** 它的 aliyun 模式 `LTAI[A-Za-z0-9]{12,}` 正对这个前缀,
   `_redact()` 只吐前 8 字符。武器就在仓库里,只是那条路径上没人调用它。
3. **闸必须长在 AI 够不着的地方。** 这是 `feedback_constraints_need_code_gates_not_prose`
   的又一次复现,只不过这次犯错的是 AI 自己,不是子 agent。

**本 spec 的第一动机就是让这类事故在结构上不可能发生**,而不是加一条「以后要小心」。

## 2. 范围与威胁模型

### 2.1 威胁模型:防的是会犯错的 AI,不是恶意的 AI

**这条定位决定了后面每一条设计的强度,必须先说清。**

本 spec 防的是 **§1.3 那种事故**:一个**合作的、但会犯错**的 AI——它想遵守约定,
但写错了遮罩、忘了调用扫描、顺手把文件读进了上下文。

它**防不住**:

- 蓄意绕行的 AI。Claude / Codex / opencode 与 `hub secrets` 跑在**同一个 Windows 用户身份下**,
  一个有任意 Bash 和文件编辑能力的 AI,总能找到路。
- 提示注入。同上——注入进来的指令拥有和 AI 一样的能力。

真要对抗这两类,需要**不同的 OS 身份 + ACL + 一个只暴露受限操作的 broker 进程**。
那是另一个量级的工程,本期不做,也不假装做到了。

> **一句话:闸的作用是把泄漏从「随手就会发生」降到「要刻意绕」。别把它当保险箱。**

而且这道闸**有一个用户亲手开的口子**(§6.7):首次录入密钥、以及任何用户明确批准的场合,
AI 可以直接接触明文。开口的授权动作物理上在人手里(弹窗点击 / 终端敲命令),AI 代不了;
但**开口一旦用了,明文就进上下文了**。这是有意接受的代价,不是疏漏。

### 2.2 做

| | 内容 | 归属 |
|---|---|---|
| ① | **引用式密钥库**:统一格式 + `hub://` 引用语法 + 解析器 | 自建(市面无同款,见 §8.2) |
| ② | **注入通道**:执行时把真值注进子进程环境,**双通道**(§5) | **包一层 dotenvx**,不自己写加密 |
| ③ | **AI 读闸**:PreToolUse hook,默认 deny + **人工授权开口**(§6.7) | 抄现成实现 + 复用 `guard.py` |

### 2.3 明确不做(推迟,不是忘了)

- **`chats/` 回溯脱敏**——拿密钥库当字典去搜历史对话。有价值,但它是**兜底网不是保证**:
  抓得到原样出现的,抓不到 base64 过的、URL 编码的、被日志截断的、复制时断行的。
  更要紧的是**顺序**:前向没堵住之前做回溯,是一条永远追不完的尾巴——今天洗干净,
  明天新对话又灌进去一批。**①③ 落地并稳定运行一段时间后再立。**
- **`secrets.age` 单文件后门**——旧 spec §闸 1 留的那个口子。维持**默认关闭、钥匙绝不进金库**
  的原判,本期一行不写。理由没变:`secrets/` 是全部密钥的单一集合,整包进金库 = 所有鸡蛋
  一个篮子,主密钥一泄一次性全崩;而它换机本来就有 `ai-cli-migrate` 点对点通道。
- **多设备同步密钥**——只有一台设备,`sync` 至今未验证,不给未验证的东西加载荷。
- **Codex / opencode 的等价读闸**——见 §6.6。本期只有 Claude Code 一端有闸。

## 3. 引用语法

```
hub://secrets/<item>/<field>
```

例:`hub://secrets/aliyun-oss-picgo/accessKeyId`

- `<item>` = `~/.claude/secrets/` 下的文件名(去掉 `.md`)
- `<field>` = 该文件里的键名

**为什么不用裸 `${ALIYUN_AK}`**:裸变量名跟普通环境变量混在一起,回溯脱敏时分不清哪个是密钥
引用哪个是 `$PATH`;而 `hub://` 自带来源信息、**grep 得出来**,且撞不上任何既有语法。

形状抄的是 1Password 的 `op://vault/item/field`(见 §8.2)——已被验证过的设计,没有理由重新发明。

### 3.1 解析必须严格(fail-closed)

backend **只接受经严格解析的 `<item>/<field>`,绝不接受任意文件路径**。`item` 必须是
secrets 根目录下的**直接普通文件**,以下一律拒绝:

- `.` / `..` / 任何斜杠或反斜杠 / 绝对路径
- 符号链接、junction、reparse point
- 重复的 key、字段名重名

理由跟 `guard.is_denied()` 的双查同源:一个能接受任意路径的 backend,等于给
「AI 拿不到明文」这条不变量开了一个参数化的后门。

## 4. 密钥库格式

### 4.1 现状:三个文件三种格式,机器解析不了

实测 `~/.claude/secrets/` 只有 3 条真密钥,但格式各不相同:

| 文件 | 现在的形状 |
|---|---|
| `aliyun-oss-picgo.md` | markdown 表格 `\| accessKeyId \| <值> \|` |
| `mineru-api.md` | 裸行 JWT(402 字符,前后各一行 ` ``` `) |
| `vscode-marketplace-vsce.md` | `## VSCE_PAT` 标题 + 代码块 |

**基数是 3,不是几十**——这一条直接把「每个应用都要适配」的成本从吓人降到一下午。

### 4.2 目标格式

沿用 hub 已有的 frontmatter 惯例(`hub/frontmatter.py` 的受控 YAML 子集),值区独立:

```markdown
---
name: aliyun-oss-picgo
description: 阿里云 OSS 图床 picgo-imgs1270
metadata:
  type: secret
  rotated: 2026-08-10
---

## fields

accessKeyId = <值>
accessKeySecret = <值>

## notes

（人读的说明、用途、来源、下游副本清单——**不参与解析**）
```

- **`## fields` 段是唯一的机器可读区**,一行一个 `key = value`。段外全是给人看的。
- 复用 `parse_frontmatter()`——它已经处理了引号剥离、布尔严格校验、未识别键原样保留。
- **`notes` 里必须记「下游副本」**(如 mineru 的 `~/.mineru/config.yaml`)。轮换密钥时,
  忘掉下游副本是最常见的失败模式。

### 4.3 迁移

3 个文件手工迁移,一次性。**迁移脚本本身不打印任何值**——§1.3 那次事故就是一个
「只打印结构、不打印值」的脚本漏了一条分支造成的,别重蹈覆辙。

## 5. ② 注入通道:双通道

### 5.1 v1 错在哪(必读)

v1 只有一条 `hub secrets run -- <command>`,并配了一条铁律「注入进程永不写 stdout」,
声称这样 AI 就拿不到明文。

**这条论证不成立。** `<command>` 是 AI 自己写的:

```
hub secrets run -- cmd /c echo %ALIYUN_AK%
```

包装器自己不打印 stdout 毫无意义——**子进程可以打印 stdout、打印 stderr、写文件、发网络请求**。
把密钥放进一个由 AI 任意指定的程序的环境里,在能力上就等于把密钥交给 AI。

### 5.2 双通道

| 通道 | 给谁 | 形态 |
|---|---|---|
| `hub secrets run -- <任意命令>` | **人**,在普通终端里 | 保留完整灵活性 |
| `hub secrets exec <profile> [args]` | **AI** | 只能跑预先声明好的 profile |

**AI 的 PreToolUse 对 `run` 一律 deny**;AI 只能走 `exec`。完整判定见 §6.7.4——
那张表是 hook 的实现规格,**它要按命令串匹配,不是只按文件路径**。

### 5.3 profile 是什么

一份**声明**,不是脚本:

- 绝对可执行文件路径
- 密钥引用 → env 变量名的映射
- 允许的子命令与参数语法
- `shell=False`,**禁止 shell / cmd / PowerShell / Python / Node 等解释器**
- stdout/stderr 经精确遮罩后才返回

ossutil、vsce、mineru 各一个,**共 3 个**。

> **AI 能请求「上传 / 发布 / 提取」,不能请求「拿着这些环境变量执行任意代码」。**

**范围说明(用户 2026-08-11 已确认采纳)**:这一条把 per-app 适配又请了回来——但形态从
「每个应用一套**填充脚本/skill**」降级成「每个应用一段**声明式配置**」,
成本低一个量级,而且是堵 §5.1 那个洞的**必要**代价,不是可选的周全。

### 5.4 `render` 有同一个洞,必须一起堵

v1 的 `hub secrets render --in <tpl> --out <file>` 同样破:**AI 把 `--out` 指向工作区,
再用 Read 读一遍就完了**,而且它还会重新制造 §1.2 想消灭的「下游明文副本」。

改成:**human-only,或由 profile 托管**——固定输出目标、启动目标程序、**退出后删除**,
不提供任意输出路径。

### 5.5 dotenvx 的交接方式(v1 漏了,必须定义)

密钥本体是 markdown,而 dotenvx 吃的是 `.env` / `--env`。这中间的数据路径 spec 必须写死:

- **不能把值放进 argv**(进程列表可见)。
- **不能悄悄生成一个长期存在的明文 `.env` 副本**——那正是本 spec 要消灭的东西。
- 必须明确临时文件策略(位置、权限、生命周期、异常路径下的清理)。
- 必须**禁用或转义 dotenvx 的变量展开与命令替换**,并证明值能**逐字节往返**
  (JWT 有 402 字符、含 `.` 和 `-`;AK secret 含混合大小写——都要有往返测试)。

另:`dotenvx run --redact` **应当开,但它不是安全边界**——官方说明它只做**精确值匹配**,
变形、截断、编码后的值不会被遮掉。这跟 `secrets_scan.py` 的局限同构(§6.4)。

### 5.6 待决:dotenvx 引入 Node 依赖

dotenvx 是 npm 包,而 hub 是纯 Python、且全局约定是「AI 脚本只用 stdlib」。三个选项:

| 选项 | 代价 | 评价 |
|---|---|---|
| **A. 真包 dotenvx** | 引入 Node 依赖;换机要多装一样东西 | **用户已选**。加密强度与维护由上游负责 |
| B. 改包 `age` 二进制 | 单个静态二进制,无运行时依赖;跟旧 spec 的 `secrets.age` 同源 | 形态跟 hub 更合 |
| C. 纯 Python(`cryptography`) | 要建 venv,且自己扛加密实现的责任 | 违反「不自己写加密」 |

**`hub secrets` 的外部契约与 dotenvx 无关**,将来换 B 只动实现不动调用方。
**实现时务必把 dotenvx 调用关在一个模块里**(`hub/secrets_backend.py`),别散到各处。

## 6. ③ AI 读闸

### 6.1 机制,以及一个致命的 fail-open 坑

PreToolUse hook,matcher 必须覆盖 `Read|Edit|Write|Grep|Glob|Bash`——少一个就是一个洞。

**三档判定**(已核实官方语义,2026-08-10):

| 档 | 怎么表达 | 效果 |
|---|---|---|
| **拒绝**(默认) | exit 0 + stdout JSON `permissionDecision: "deny"` | 挡下,`permissionDecisionReason` 回喂给 AI |
| **问人** | 同上,`permissionDecision: "ask"` | **弹给用户点允许/拒绝**——这是 §6.7 那个开口的落点 |
| **崩了** | exit 2 | 阻断,stderr 回喂 |

用 JSON 而不是裸 exit 2 做默认拒绝,是因为它能带 `reason`——告诉 AI「用 `hub://` 引用,
别读明文」,而不是丢一个没有出路的错误。

**坑在这里**:Claude Code 的官方语义是——**JSON 只在 exit 0 时被解析;exit 2 阻断;
exit 1 和其它非零退出码都是「非阻断错误」,工具照常执行。**

所以 hook 里任何一个没接住的异常(JSON 结构不对、路径解析炸了、guard 抛了预期外的错),
Python 默认退 1 → **静默放行**。判定逻辑越严谨,这个坑越致命:它把一个「拦得住」的闸
变成「崩了就放行」。

**要求**:hook 顶层**捕获一切异常并转成 exit 2**,并**专门测试** malformed input 与
guard 抛异常这两条路径。

### 6.2 判定逻辑直接复用 `hub/guard.py`

`guard.is_denied()` 比市面上任何一份教程都狠,而且已经写好了:

- `DENIED_NAMES = {secrets, auth.json, .env}`
- **字面 parts 与 `resolve()` 后的 parts 双查**——市面教程大多只做字面匹配,一条符号链接就绕过去
- `resolve()` 抛 `OSError` 时**闭门当拒绝**

hook 脚本 import 它即可。**不要在 hook 里重写一份判定**,两份实现迟早分叉。

### 6.3 `guard` 与 `secrets_backend` 的分层:它保的是什么,不保什么

`guard.py` 的立身之本是「**提取器永不读取 secrets**」,而 ② 的注入通道**必须读**明文。
v1 的解法是按调用方分层。**这个方向对,但 v1 把它说过头了。**

Python 的模块边界**不是 capability boundary**——任何代码都能 `import secrets_backend`,
AI 也能直接调 CLI。所以这个分层能保住的不变量只有一条,要写准:

> **`collect` 的传递依赖图永远到不了 `secrets_backend`;它的全部本机读取仍经过 guard。**

这是**架构边界**(防误耦合、防未来某次重构把两条路径接通),**不是对抗 AI 的安全边界**。
后者靠 §2.1 的威胁模型定位诚实交代。

落实成代码闸:

- `hub collect` 延迟加载命令模块,运行时不 import `secrets_backend`。
- 建议独立入口 `hub-secrets`(隔离误耦合,不代表 OS 级隔离)。
- **加 AST 架构测试**:`hub.collect.*` 禁止 import `secrets_backend`,违反则**非零退出**。
- `DENIED_NAMES` **不加任何豁免参数**——那会让不变量从「结构上做不到」退化成
  「取决于调用方传了什么」,正是 `feedback_preview_must_share_write_path` 那次事故的形状。

### 6.4 只按路径拦,绝不按内容模式拦

`secrets_scan.py` 的模块注释里钉着一条用学费换的结论:

> 误报率高到不能当闸——实测扫 plugins-dev 的 10 条命中全是误报(`sk-` 撞上 `task-fix3-report`)。
> 阻断只会逼人无脑加白名单,闸就废了。

分工是死的:

- **`guard.py` 按路径 → 硬闸,阻断**
- **`secrets_scan.py` 按内容 → 软提醒,只报告**

§1.3 那次事故的正确防线是**前者**(探测脚本读了 `secrets/` 目录,路径闸拦得住)。

### 6.5 hook 拦不住什么(诚实列清)

- 用户自己粘贴明文进对话
- MCP 工具或别的进程绕开 Claude Code 的工具层读文件
- 已经在上下文里的明文(hook 只管未来的读取)
- **蓄意绕行与提示注入**——见 §2.1,这不在本期威胁模型内

### 6.6 只有 Claude Code 一端有闸

本 spec 只定义了 Claude Code 的 PreToolUse。hub 服务三个工具,但 **Codex 和 opencode
没有等价闸**(本轮未核实它们各自是否具备同类机制)。

因此**标题与验收都不许写成跨工具的「AI 读不到明文」**,准确表述是:
**「Claude Code 原生工具的读取受 guardrail 约束」**。

### 6.7 人工授权开口(break-glass)

**用户 2026-08-11 追加的需求**:首次录入一个陌生的配置或密钥时,以及任何用户明确批准的
时候,允许 AI 直接看到、操作明文。

这是个**必要**的开口,不是妥协——没有它,第一次把一条新密钥存进库这件事本身就做不了
(总得有人把值写进文件)。关键是**别让它把整道闸废掉**。

### 6.7.1 设计原则:授权动作必须物理上在人手里

**绝不能让 AI 自己申请豁免。** 一旦 AI 能通过说一句「我需要读这个」来解锁,它就会为了方便
一直解锁,闸等于不存在——这跟「让 AI 小心点别打印明文」是同一类失败(§1.3)。

所以授权只能来自**人的一次真实动作**。有两个天然满足这一条的落点:

### 6.7.2 落点一:`ask` 弹窗(逐次确认)

hook 返回 `permissionDecision: "ask"`,Claude Code 会**弹给用户点允许或拒绝**。
这个点击动作 AI 代不了,是硬的。

### 6.7.3 落点二:短时效解锁令牌(时间窗)

```
hub secrets unlock --minutes 10        # 只能由人在终端里敲
```

它在 `~/.claude/secrets/.unlock` 写一个带过期时间戳的令牌。**AI 创建不了这个令牌**——
因为写那个目录的操作本身就被 hook 挡着,闭环成立。

**闭环要成立,必须同时满足三条,少一条就漏**:

1. **`hub secrets unlock` 这条命令本身在 AI 的 deny 名单里**(Bash matcher 要按命令串匹配)。
   否则 AI 直接敲一句就自己解锁了,整个开口白设计。
2. **hook 读令牌走裸 `Path.read_text()`,不走 `guard.read_source_text()`。** 后者会
   `check_source()` 命中 `secrets` 黑名单**把自己挡住**——hook 是判定者,不是被判定者。
   这个坑很容易踩,因为 §6.2 刚说过「hook 直接 import guard」。
3. **`.unlock` 不是一条密钥。** `## fields` 解析器与 `hub://` 引用解析必须排除它
   (点开头的文件一律不当 item),否则它会被当成一个可引用的密钥项。

### 6.7.4 判定表

| 场景 | 判定 | 理由 |
|---|---|---|
| 读**已存在**的密钥文件,无令牌 | **deny** | 已经有 `exec <profile>` 通道,没有正当理由去读明文 |
| 读已存在的密钥文件,**令牌有效** | **ask** | 时间窗 + 逐次确认,双闸 |
| **写一个还不存在**的密钥文件 | **ask** | 首次录入。此时明文本来就是用户自己贴进对话的,拦写没有意义;弹窗的价值是让用户看见「要存到哪、存成什么」 |
| 改**已存在**的密钥文件(轮换) | **ask**,且需令牌 | 轮换是正当操作,但要拦住静默覆盖 |
| AI 调 `hub secrets run --` | **deny** | 那是 human-only 通道(§5.2)。AI 走 `exec <profile>` |
| AI 调 `hub secrets render --out` | **deny** | 同上,且它会造下游明文副本(§5.4) |
| AI 调 `hub secrets unlock` | **deny** | **不可放宽**。AI 能自己解锁 = 开口白设计(§6.7.1) |
| AI 调 `hub secrets exec <profile>` | **allow** | 这就是给 AI 的那条通道 |
| 任何路径下 hook 自身出错 | **exit 2** | fail-closed,见 §6.1 |

**这张表就是 hook 的实现规格**——`Bash` 那一路要按命令串匹配 `hub secrets` 的子命令,
不能只按文件路径判。只拦路径不拦命令,前四行有效、后四行全漏。

令牌默认 **10 分钟**,过期自动失效,**不提供「一直开着」的档位**。

### 6.7.5 这个开口的代价(诚实写)

**开口一旦用了,明文就进上下文了,跟 §1.3 那次一模一样。** 时间窗和弹窗能限制
*什么时候*发生,限制不了*发生之后*明文会流去哪。

配套只能是软的,写在这里是为了将来别把它当成硬保证:

- 批准后读到的明文**只用于当次操作**,不回显、不写进任何持久文件。
- 录入完成后立刻改用 `hub://` 引用,正文里不留值。
- 事后用 `secrets_scan` 扫一遍——**但它只是辅助信号**(§9)。

**这三条都是约定,不是闸。** 本 spec 不假装它们是。

## 7. `sensitive` 语义:维持原判,不改

### 7.1 v1 想改,改错了

v1 打算把 `sensitive: true` 从「不入库」改成「入库前必须过引用化检查」。**撤回。**

spec 自己那句话已经给出了正确答案:「引用替换后,这条记忆就不再敏感了。」
那它就该老老实实写成**不敏感**:

```yaml
sensitive: false
secret_refs: true    # 可选:记录它含 hub:// 引用
---
sensitive: true      # 保持原义:原始 / 未完成引用化 → 绝不入库
```

`secret_refs` 作为附加元数据白送——`frontmatter.py` 已经**原样保留未识别键**
(`extra` / `extra_metadata`),不需要改解析器,也不需要动 boolean 契约。

### 7.2 翻转语义会牵动的远不止 `cli.py:49`

- **`collect/memory.py` 会删掉金库里的旧副本。**(已核实)`_scan()` 跳过 sensitive →
  它不进 `mems` → `_diff()` 的 `have - names` 把它算成「源端已删」→ `collect_memory`
  第 92 行 `w.unlink()`。**一条已在金库里的记忆,只要被标上 `sensitive: true`,
  下一次 collect 就会把金库那份删掉。** 迁移期任何「标了但还没引用化完」的中间状态都踩这个雷。
- **`_lint()` 仍会拒绝它**——只改 collect 会出现「collect 已写入、之后 sync 才拒绝」的半迁移状态。
- **C 侧没有第二道敏感过滤**:`memview.py` 照常建视图,`memread.py` 直接返回正文。
- **`promote.promote_memory` 没有引用化复验。**
- **SCHEMA 明写「不入库」,金库仍是 `version = 3`。** 同一版本下静默翻转语义,
  会让新旧 hub 对同一个文件作出**相反判断**。

**采用 §7.1 的方案,以上五条一条都不用碰,SCHEMA 也不用动。** 这是它比 v1 干净的全部理由。

### 7.3 迁移流程

1. `sensitive: true` 继续留在源端,**不进金库**。
2. 由**有权读取密钥库的可信校验进程**检查:所有 `hub://` 引用都存在;已登记的真实密钥值
   没有原样残留。**只输出文件名、字段名、通过/失败,绝不输出值。**
3. 校验通过后,把正文引用化,并**原子地**把 `sensitive` 改成 `false`。
4. 再走 collect `--dry-run` → collect → sync。
5. **金库里若出现历史 `sensitive: true`,当作不变量已被破坏并停止处理**,不自动提升、不静默改写。

**当前实际迁移对象:0 条。** 已核实——`~/.claude/projects/*/memory`、设备备份区、
`shared/memory` 三处,frontmatter 里 `sensitive: true` 的记忆数量都是 0
(全文 grep 到的 52 处命中全是正文/对话里提到这个字符串)。所以这套流程是**给未来钉规则**,
不是眼下有活要干。

## 8. 复用清单

### 8.1 仓库里已有的(直接用)

| 组件 | 行数 | 用在哪 |
|---|---|---|
| `hub/guard.py` | 84 | ③ 的判定逻辑,hook 直接 import |
| `hub/secrets_scan.py` | 63 | 引用化后的**验收扫描**(注意 §9 的局限) |
| `hub/frontmatter.py` | 74 | ① 密钥库格式的解析器;未识别键原样保留 → `secret_refs` 白送 |
| `hub/writer.py` | 55 | 唯一写入口 + `--dry-run` 闸长在写方法里面 |
| 现有 hook 范式 | — | `SessionStart` 已挂 `ai_room.hooks.claude_session_start`;compact-plus / xu-skills 带 `hooks.json` |

### 8.2 市面同款(扫描日期 2026-08-10)

| 我们的块 | 同款 | 结论 |
|---|---|---|
| ①② 引用 + 注入 | 1Password CLI(`op://` + `op run` + `op inject`) | **一比一同款**。不用是因为订阅制 + 依赖桌面 app,与「金库 = 文件 + git」的形态不合。**语法形状照抄** |
| ② 加密存储 | dotenvx / SOPS + age | 选 dotenvx(§5.6) |
| ③ AI 读闸 | nopeek / file-guard / failproof ai | 红海,抄 matcher 清单与 exit 2 契约 |
| ① 接金库体系 | **没搜到** | 市面没人做,因为没人有这套金库。这是唯一必须自建的部分 |

值得一读:[两个 Claude 实例互相攻防 .env 打了五轮](https://medium.com/@jason.croucher/i-tried-to-stop-claude-from-reading-my-env-it-took-five-rounds-078d8e291cb4)
——记录的是这道闸**已知的绕过路径**。

## 9. 验收

1. `~/.claude/secrets/` 3 个文件迁到新格式,`## fields` 段可被解析器读出,
   **值逐字节往返**(JWT 402 字符、含 `.`/`-`;AK secret 混合大小写)。
2. `hub secrets exec <profile>` 能让 ossutil / vsce / mineru 三条真实工作流跑通,
   **且全程 stdout/stderr 里不出现任何真值**。
3. `hub secrets exec` **不能**执行 shell / cmd / PowerShell / Python / Node;
   `hub secrets run` 与 `render` 被 AI 的 PreToolUse 拦下(§5.2 / §5.4)。
4. hook:`Read` / `Bash type` / `Grep` 指向 `~/.claude/secrets/` 全部被 **deny** 挡下,
   **符号链接绕行也挡得住**(单独测,这是 `guard.py` 双查的价值);
   **malformed input 与 guard 抛异常时必须 exit 2,不许 fail-open**(§6.1,单独测)。
5. 人工授权开口(§6.7):**AI 创建不了解锁令牌**(写 `secrets/` 被自己的闸挡住,单独测);
   **AI 调 `hub secrets unlock` 被 deny**(命令串匹配,单独测——这条漏了开口就白设计);
   令牌**过期后自动回到 deny**(测时间边界);写一个**不存在**的密钥文件走 `ask` 而非 deny;
   没有「一直开着」的档位。
   另测:hook 读 `.unlock` 时**没有把自己挡住**(§6.7.3 第 2 条),
   且 `.unlock` **不被当成一条可引用的密钥**(第 3 条)。
6. AST 架构测试:`hub.collect.*` 不 import `secrets_backend`,违反则非零退出(§6.3)。
7. 无长期明文 `.env` 副本残留;异常路径下临时文件也被清理(§5.5)。
8. 全量回归绿(63 个测试文件的 TDD 标准照旧,每个新模块配测试)。

**关于扫描的诚实声明**:`secrets_scan.scan_tree()` 只有 5 个已知前缀模式,
且对读取失败、含 NUL、非 UTF-8 的文件**静默跳过**。所以「0 命中」
**只能证明「已扫描的部分没有命中已知模式」,不能证明正文里没有密钥**。
它是验收的**辅助信号**,不是通过条件。

## 10. 已知开口

- **§5.6 的 Node 依赖**——已选 A,动工前值得再确认一次。
- **§6.7 的开口是软性收尾**——「批准后不回显、不落盘」这三条是约定不是闸。将来若要硬化,
  方向是 PostToolUse 事后扫 + 写闸,但两者都会带来 §6.4 那条误报率问题,没有便宜解法。
- **§6.6 只有 Claude Code 一端有闸**;Codex / opencode 未定义,也未核实现状。
- **§2.1 的威胁模型**——不防蓄意绕行与提示注入。要防需要不同 OS 身份 + broker,是另一个量级。
- **回溯脱敏 `chats/`** 与 **`secrets.age` 后门**——本期明确不做(§2.3),不是遗漏。
- **2026-08-10 泄露的那对阿里云 AK 未轮换**——用户已知情并决定「做完再说」。
  它是本 spec 的动机样本,轮换时正好走一遍新流程。

## 11. 动工须知(给下一个接手的人/会话)

**本节存在的理由**:下面这些事只发生在立 spec 的那次对话里,不写下来就没了。

### 11.1 下一步是立 plan,不是直接写代码

本仓的流程是 `docs/specs/` → `docs/plans/` → `.superpowers/sdd/` 台账 → TDD。
A 和 C 阶段都是这么走的(见 `docs/plans/` 里那几份)。**B 现在只有 spec,没有 plan。**

不要换成别的工作流(如 vibe-flow)——换流程会让台账断层。

### 11.2 实施顺序

**① 密钥库 → ② 注入通道 → ③ 读闸与开口。** 顺序不能反:

- ① 是地基,②③ 都要读它的格式。
- ③ 必须在 ② **之后**——先把 `exec <profile>` 通道建好,再落闸。反过来做,
  中间那段时间里 AI 既读不到明文、又没有替代通道,日常工作会直接卡死。

### 11.3 派活建议

| 块 | 派不派 opencode | 理由 |
|---|---|---|
| ①② | **派** | 格式解析、env 注入、模板渲染,测试契约明确,判断成分低 |
| ③ + §6.7 开口 | **不派,自己写** | 闸写错是**零痕迹失效**:测试全绿、exit 0、看不出来。且它的难点是「有没有漏一条路径」,正是子 agent 最容易漏的那类 |

### 11.4 派 opencode 时必须写死写入方式(否则会静默毁文件)

**本仓的 `.py` 被 Esafenet DRM 加密。** 非白名单进程写入**不是失败,是写进去且不加密**——
文件从密文变成明文躺在盘上,而账面上毫无痕迹:exit 0、测试全绿、`git diff` 干净。

派任务时必须在 prompt 里写死:

- **读**用 `cmd /c type`(git-bash 的 `cat`/`head`/`sed` 读到的是乱码)
- **写必须走 python**(`Path.write_text` / `write_bytes`)
- **禁止** PowerShell 的 `Set-Content` / `Copy-Item`,**也禁止 opencode 自己的 Write/Edit 工具**

**不明说就等于没说**——实测 opencode 和 codex 在互不相干的会话里**都**自己挑了 PowerShell 落盘。
补救:用 python 原样读写一遍即可(`p.write_bytes(p.read_bytes())`),内容一字节不变。
验证要用**非白名单进程**看头字节(`[System.IO.File]::ReadAllBytes($p)[0..7]`),
出现 `e0 a8 91 e7 d8 f2 05 ac` 才是加密态。

### 11.5 工作量

**约 3 个工作日**,含测试(本仓 63 个测试文件的 TDD 标准照旧,每个新模块配测试)。

拆开看:① 半天;② 1 天(含 §5.5 的 dotenvx 交接与往返测试);③ + 开口 1~1.5 天
(大半花在边界测试:符号链接绕行、malformed input fail-closed、令牌过期、AI 造不出令牌)。

### 11.6 codex 评审原文在哪

`.ai-room/ledger.md`(**被 gitignore 挡着,不进仓库**)。结论已摘进 §12,原文含更多细节。
要追问同一个 codex 会话:

```
ai-room resume --to codex --session 019feba8-5db6-74e1-a8ea-8a59659d2946 --cwd C:\Users\huawei\ai-cli-migrate
```

## 12. 修订记录

**v2.1(2026-08-11)**——用户拍板两件事:

1. **profile 通道确认采纳**(§5.3)。AI 继续能替用户跑 ossutil / vsce / mineru,
   但只能经预先声明的 profile,拿不到密钥值。per-app 从「脚本」降为「声明」,3 个。
2. **追加人工授权开口**(§6.7)。首次录入陌生配置/密钥、以及任何用户明确批准的场合,
   AI 可直接接触明文。落点是 hook 的 `permissionDecision: "ask"`(弹窗点击 AI 代不了)
   + 短时效解锁令牌(`hub secrets unlock`,AI 创建不了,因为写 `secrets/` 被自己的闸挡着)。
   顺带核实到 hook 的第三档 `ask` 确实存在(官方文档,2026-08-10),
   这一档 v2 完全没用上——v2 只有 deny 和 exit 2 两档。

**v2(2026-08-10,codex 评审后)**——v1 有两处不成立,已重写:

1. **§5.2 的「注入进程永不写 stdout」是自欺欺人。** `run -- <任意命令>` 里的命令由 AI 指定,
   包装器不打印毫无意义,子进程想怎么泄就怎么泄。→ 改双通道 + profile(§5.1–5.4)。
2. **§7.1 翻转 `sensitive` 语义会踩五个雷**,其中「collect 会删掉金库旧副本」已核实成立。
   → 撤回,改用 `sensitive: false` + `secret_refs: true`,SCHEMA 一行不动(§7)。

同轮补入的新事实:

- **Claude Code hook 只有 exit 2 阻断,exit 1 是非阻断** → hook 必须捕获一切异常转 exit 2,
  否则判定逻辑一崩就是静默放行(§6.1)。
- **模块边界不是 capability boundary** → §6.3 的不变量重新表述,并加 AST 架构测试。
- **dotenvx 的交接方式 v1 完全没写**(markdown → `.env` 的数据路径、临时文件、变量展开)(§5.5)。
- **`render --out` 有和 `run` 一样的洞**(§5.4)。
- **`dotenvx --redact` 只做精确值匹配**,不是安全边界(§5.5)。
- **`secrets_scan` 的「0 命中」不能作为通过条件**(§9)。
- **威胁模型必须前置声明**(§2.1)——原文含糊地暗示「AI 拿不到明文」,做不到。
