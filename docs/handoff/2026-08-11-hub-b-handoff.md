# 交接：hub B 阶段收口 + 三个开口项（2026-08-11）

> 冷启动读这一份就够。要细节再往 `docs/specs/2026-08-10-hub-secret-reference-design.md`（v2.2）
> 和 `docs/plans/2026-08-11-hub-b-secret-reference.md`（含每个任务的**实施修正**与**执行记录**）里翻。

## 一句话现状

**B 的引用层与注入通道做完并真机验过了**，621 passed / 3 skipped。
**但 B 的原始目标——密钥加密后存进金库、多机共享、防泄露——一个字没做。**
先读下面这节再往下看，否则会以为 B 收口了。

## 目标校准（2026-08-11 晚，用户当面澄清）

`2026-08-10` 那版 spec 把 B 从「加密层」改写成「引用层」，理由写的是
"加密只管静态存储，管不住合法解密后的泄漏"。**那句话本身没错，但它偷换了题目。**
用户要防的从来不是"AI 读到本机明文"，而是**金库同步出去被别人拿到**。

用户原话（2026-08-11）：

> 我就是想做加密，这种引用式密钥。专门就是为了存 hub 里，多机共享防泄露用的。

以及关于 `guard.py` 里"secrets 永不进金库"那条注释：

> 我之前说的永远不进 hub 只是懒得做了。如果能加密进 hub，这份密钥就复用性很强了。

**执行方（我）的漏**：读了那份 spec 就直接往下写 plan 和代码，对 dotenvx、启动链、
闸的实现挑了六处毛病，**唯独没回头对一遍 `NEEDS.md` 里"B 到底要解决什么"**。
改了 NEEDS 两次也没发现它和用户要的对不上。**下一个人动 B 之前，先拿本节和 NEEDS 对齐，
别再照着改写过的题目往下做。**

### 引用替换那部分**是用户要的，不是顺带**

用户同日澄清：`hub://` 引用替换是**为「未来把历史对话存进金库」提前部署的**——
对话一旦进金库，里面出现过的任何明文密钥就跟着进去了。

所以这三件事是**同一个目标的三个面**，都不是白做：

| 做的东西 | 对应的泄漏路径 |
|---|---|
| 别处只写 `hub://` 引用 | 记忆 / skill / 配置里的明文随金库同步出去 |
| PreToolUse 读闸 | **AI 读一次明文 → 明文进 transcript → transcript 进金库** |
| `secrets exec` 注入通道 | 堵上前两条之后，AI 仍然得能干活，否则闸会被摘掉 |

> 我在对话里一度把读闸判成"为错的威胁模型做的、约三分之一白干"。**那个判断是错的，已收回。**
> 读闸正是"明文不进 transcript"这条链上的承重件。真正还没做的只有**静态加密**那一段。

## B 交付了什么

密钥本体只存 `~/.claude/secrets/<item>.md` 的 `## fields` 段；别处一律只写引用
`hub://secrets/<item>/<field>`；要用就走注入通道，不自己开文件。

| 命令 | 给谁 | 说明 |
|---|---|---|
| `py -3 -m hub.cli secrets exec <profile> [args]` | **AI** | 只能跑 `~/.hub/secrets-profiles.toml` 里声明好的 profile |
| `py -3 -m hub.cli secrets run --profile <p> -- <任意命令>` | 人 | 真实终端里，stdio 直通不遮罩 |
| `py -3 -m hub.cli secrets render --profile <p>` | 人 | `KEY=value` 打到终端，**故意没有 `--out`** |
| `py -3 -m hub.cli secrets unlock --minutes N` | 人 | 要在控制台键入确认短语 `unlock secrets` |

三个 profile 已配好并端到端验过：`ossutil`（单段原生 exe）、`vsce`（`node.exe` + 绝对入口脚本）、
`mineru`（单段原生 exe，env 名 `MINERU_TOKEN`，从二进制字符串里核实的）。

Claude Code 侧 `PreToolUse` 闸已挂进 `~/.claude/settings.json`
（改动前备份在同目录 `settings.json.bak-2026-08-11`）。

### 文件地图

```
hub/secrets_store.py       严格解析器：item 名把关（check_item_name 是唯一判据）+ `## fields` 段
hub/secrets_backend.py     **唯一读明文的一层**，绕开 guard 是有意的；将来换加密只动这里
hub/secrets_profile.py     profile 声明 + 固定启动链校验 + 尾参语法校验
hub/secrets_run.py         局部 env 注入 + 四条路径遮罩（成功/非零/超时/解码失败）
hub/secrets_unlock.py      解锁令牌，承重闸是读 CONIN$
hub/secrets_cli.py         双通道：run/render 进程内自守，exec 放行
hub/hooks/secrets_guard.py PreToolUse 闸
tests/hub/test_secrets_*.py
tests/hub/test_arch_secrets_isolation.py   AST：collect 永远到不了密钥层
~/.hub/secrets-profiles.toml               运行态，不进金库（全是本机绝对路径）
~/.claude/secrets/.bak-2026-08-11/         迁移前原样备份，确认无误后可删
```

今天的提交：`9ed4bd1 561a5db 0207119 99943ad 824d8fd a418545 13f13e5 153ed96 663c4f9 a0dca2c a556097`
（前置的 spec+plan 是 `32e4216`）。

## 今天踩的坑，按"最容易再犯"排序

**① hook 的 stdin/stdout 必须走 UTF-8 字节。** 闸一挂上，第一条带中文的 Write 就被自己
拦死了：`json.load(sys.stdin)` 在 Windows 上按 locale（cp936）解码，而 Claude Code 送的是
UTF-8。顶层 fail-closed 把 JSONDecodeError 变成 exit 2 —— **每一条带中文的工具调用都被拦**。
对称的一半更阴：判定理由是中文，走 `sys.stdout` 文本流在 cp936 下可能
`UnicodeEncodeError` → 退 **1** → 那是**非阻断**，闸从"拦得住"变成"崩了就放行"。

> **23 条单测一条都没抓住**，因为测试用 `subprocess(text=True)`，父子两头同一个 locale，
> 两边自洽。**凡是测跨进程协议的地方，一律喂原始字节。**

**② 用 `is_denied` 扫命令串时，`hub://secrets/…` 会被判成命中**——它的字面 parts 里就有一个
`secrets`。拦的正是本项目要推广的引用写法。修法是扫描前摘掉带 scheme 的 token。
`oss://`、`https://` 都不命中，只有 `hub://secrets/…` 踩雷，非常隐蔽。

**③ 备份目录的名字要真的落在闸里。** 我一开始把 `~/.claude/secrets/` 备份到
`~/.claude/secrets-bak-…`——那个名字不等于 `secrets`，`guard.is_denied` 判不出来，
等于把全部明文复制到了闸外面。已挪进 `secrets/.bak-2026-08-11/`（点开头，
`iter_items` 不会当成密钥）。

**④ plan 里六处照字面实现不出来**，三处是 opencode 撞出来的、三处是我写闸时发现的。
逐条记在 plan 各任务的「实施修正」小节里。**派 opencode 时"照抄落盘、如实报失败、不许自己改"
这条指令是有效的**——它三次都照做了，没有一次擅自改设计。

## 三个开口项

### ① 加密进金库 —— **这是 B 的正题，不是加分项**（今天聊了一半，**没定**）

见上面"目标校准"。`guard.py` 里"secrets 永不进金库"那条注释**是当时懒得做，不是原则**，
别把它当不变量引用。加密进金库之后，换机 = clone 金库 + 一个主密钥，
不用再点对点搬 `~/.claude`。

已经想清楚的部分：

- **`guard` 一个字都不用改。** 金库里放的是 `secrets.age` 这一个加密产物，路径与
  `~/.claude/secrets/` 无关。硬闸继续禁止提取器碰明文目录，只有一个专门命令
  （走 `secrets_backend`，本来就是唯一被允许读明文的那层）生产它。
  "密钥永不以明文进金库"这条不变量原样保留。
- **换装线已经留好**：`secrets_backend` 是唯一读明文层，把 read → decrypt 换进去，
  runner / policy / CLI 一行不动。
- **加密后端建议用 `age.exe` 当外部二进制**。Python 标准库**没有对称加密**（无 AES/ChaCha），
  而 hub 是 stdlib-only。调外部 exe 正好复用刚建好的"固定启动链 + 绝对路径 + `shell=False`"，
  既不引 Python 依赖，也不自己实现密码学。

**卡在这一个决定上：主密钥托管走口令派生（scrypt）还是 age 身份文件？**
口令派生才是真正零携带、才对得上"复用性强"；身份文件更强但那个文件还得搬，
等于把"换机要搬东西"挪了个位置。用户说"算了，今天不搞了"，**没拍板**。

配套还没定的两条：本机还留不留明文工作副本（留 = 加密只保护金库那一份，不防本机；
不留 = 每次 exec 都要解密，得配合 `unlock` 令牌做会话内缓存）；以及解锁粒度。

> **一条必须先说清楚的硬事实**：`secrets.age` 进 git 之后，**每个历史版本永久留存**。
> 哪天口令泄漏，攻击者拿到仓库就能解开**所有历史版本**，包括早就轮换掉的密钥。
> 所以口令必须一次就选够强，而且"轮换密钥"不等于"历史安全"。

### ② 两份下游明文副本（**已定位，等用户决定清不清**）

- `~/.ossutilconfig` —— `accessKeyID` / `accessKeySecret`
- `~/.mineru/config.yaml` —— `token`

两条都已写进对应密钥文件的 `## notes`。env 注入通道已经证明可行，所以这两份可以清掉
（ossutil 那份留 `region`/`endpoint` 即可）。**没擅自动**，因为会影响用户现在直接敲
`ossutil` 的习惯和 img2md 脚本。

**这件事排在 ①（加密）之前更合理**：金库那一份加密了、本机三份明文躺着，加密就只是心理安慰。

### ②′ 历史对话进金库之前，得先把已有的明文清掉

用户要把历史对话存进金库（这正是引用层提前部署的原因，见"目标校准"）。
但引用层只管**从今往后**——**已经躺在旧 transcript 里的明文，它一个字也管不着**。
所以在把 `chats/` 放进金库之前，至少要先解决：

- **回溯脱敏**：旧对话里出现过的密钥值得扫一遍。spec §2.3 把这件事划在 B 之外，
  现在它变成 `chats/` 入库的**前置条件**了。注意 `hub/secrets_scan.py` 的既有结论——
  它误报率高到不能当闸，只能当**辅助信号**，不能拿它的 0 命中当"干净"的证据。
- **那把泄露的阿里云 AK 至今未轮换**（用户早前决定"AK 不管了，做完再说"）。
  对话入库会把它的暴露面再放大一层。
- **加密与 git 历史的相互作用**（见 ① 里那条硬事实）：`chats/` 和 `secrets.age` 一旦进 git，
  **每个历史版本永久留存**，事后删文件不等于删历史。

### ②″ "多机共享"还卡在一件比加密更靠前的事上

`docs/NEEDS.md` 的"诚实边界"写着：**金库只有本机 git，没有任何远端，多机 sync 从没真跑过**
（只有一台设备）。所以加密做完也只拿到"能安全同步"这一半，**"同步"那一半本身还不存在**——
它卡在 C 阶段和一个远端上。定优先级时别把这两件事混成一件。

### ③ C 阶段（**项目最大的开口，本来就是首要需求**）

见 `docs/NEEDS.md`：把金库装回工具、本地一处改到处新、跨设备人工闸门、符号根展开。
一行代码都没开始。`docs/plans/2026-07-16/17/20-hub-c-*.md` 是三份已立的 plan。

## 诚实边界（别让这套东西显得比实际强）

- 它约束的是 **Claude Code 原生工具的读取**。**Codex / opencode 没有等价闸。**
- 不防蓄意绕行、不防提示注入、管不住已经进了上下文的明文。
- `run`/`render`/`unlock` 的承重闸在**各自进程里**（`stdout.isatty()`，unlock 还要读 `CONIN$`）；
  hook 的命令串匹配只是**提示层**——`hub` 不在 PATH 上，写法枚举不完。
- 输出遮罩只做**精确值匹配**，不是安全边界；把密钥放进子进程环境**也不是隔离**。
- 闸认的是 `guard.DENIED_NAMES`（`secrets` / `auth.json` / `.env`），**全机生效**——
  别的项目里读 `.env` 也会被拒。这是设计，不是误伤。
- 泄漏的阿里云 AK 至今**未轮换**（用户早前决定"AK 不管了，做完再说"）。
- `test_symlink_bypass_blocked` 因为本机没有建符号链接的权限，**一直是 skipped，没真跑过**。

## 恢复入口

1. 读本文件，**"目标校准"那一节必读**——spec 的题目和用户要的不是一回事。
2. 要动加密（这是 B 的正题）→ 读 spec §5.6（当初撤回 dotenvx、留换装线的理由）
   + 本文件开口项 ①。**先跟用户把主密钥托管那一条定了再写 spec**；
   spec 不是打补丁，是把 B 的题目改回"加密层"，引用层与注入通道作为它的组成部分保留。
3. 要动 C → 读 `docs/NEEDS.md` 的"三个阶段"和"需求四组"，那里写着为什么 C 才是首要需求。
4. 动手前的固定约束（提交身份 `patrick1099`、Esafenet 写入必须走 python、
   派 opencode 的 prompt 三条）都在 plan 的 **Global Constraints** 和**派活分配**两节，
   逐字抄即可。
