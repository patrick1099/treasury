# hub —— 跨工具/设备共享「规则 + 记忆」数据层

把你的 AI 工具规则和记忆集中存一份 git 版本化的**金库**,按 `设备 / 工程 / 工具`
维度过滤后,自动分发到 Claude Code、Codex 各自该放的位置;反过来也能把本机记忆
收集回金库。离线优先:除 `sync` 外全部本地完成,金库只是一个 git remote(可放 NAS)。

纯标准库,Python ≥ 3.11。所有命令:`py -3 -m hub.cli <子命令> --vault <金库> --host <主机名>`
(`--host` 省略时取本机 hostname 小写)。

---

## 1. 快速开始

```bash
# 1) 建金库骨架 + 本机设备档案模板(--git 顺带 git init)
py -3 -m hub.scaffold_vault  D:/hub-vault  --host mybox  --git

# 2) 编辑 D:/hub-vault/devices/mybox.toml,把标了 TODO 的项填好
#    (class / collect_sources / [[targets]])

# 3) 收集本机记忆入金库
py -3 -m hub.cli collect  --vault D:/hub-vault --host mybox

# 4) 校验 + 重生成索引 + 本地提交(纯离线)
py -3 -m hub.cli process  --vault D:/hub-vault --host mybox

# 5) 落地到各工具位置(会写你真实的 ~/.claude、~/.codex 和各工程目录!)
py -3 -m hub.cli pull     --vault D:/hub-vault --host mybox
```

> ⚠️ `pull` 会按设备档案里的 `[paths]`/`[[targets]]` 写入**真实**位置
> (`~/.claude`、`~/.codex`、各工程根目录)。先在这些路径填好、想清楚再 `pull`。

联网多机同步时用 `sync`(拉取自动合并、真冲突才停、再推送);金库加一个 git remote
(指向 NAS 或任意 git 托管)即可。

---

## 2. 金库结构

```
<金库>/
  vault.toml            # version = 1
  rules/                # 规则,每个 .md 一个主题;拼进各工程 AGENTS.md
    coding.md
    naming.md
  memory/               # 记忆,一条一文件(带 frontmatter);免合并冲突的原子文件
    g_test.md
    p_vlcd.md
  devices/              # 每台机一个档案
    mybox.toml
  MEMORY.md             # 【派生,勿手改】process 从 memory/*.md 重生成的索引
```

- **规则**拆成小主题文件,便于多机各改各的、git 自动合并。
- **记忆**一条一文件(原子),同理。
- **`MEMORY.md`** 是派生物,`process` 会覆盖重写——别手改,也别 collect 它。

---

## 3. 设备档案 `devices/<host>.toml`

```toml
# 本机属于哪些设备类;记忆 scope 里的 device:<class> 据此匹配
class = ["work"]

# 本机参与的工程(信息性)
projects = ["xinao"]

# collect 扫这些目录里的 *.md 记忆收进金库(自动跳过 sensitive 和派生文件)
collect_sources = [
    "C:/Users/me/.claude/projects/<工程编码>/memory",
]

# 符号根:记忆正文里的 $NAME/... 落地时按这里解析(见 §7)
[paths]
VAULT       = "D:/hub-vault"
CLAUDE_HOME = "C:/Users/me/.claude"
CODEX_HOME  = "C:/Users/me/.codex"
# SECRETS   = "C:/Users/me/.claude/secrets"   # 可选

# 每个 target = 一个工程根;pull 往它写 AGENTS.md / CLAUDE.md。可重复多段。
# project 要与记忆 scope 里的 project:<id> 对应。
[[targets]]
project = "xinao"
root    = "C:/work/xinao"

[[targets]]
project = "meterlib"
root    = "C:/work/meterlib"
```

| 键 | 作用 |
|---|---|
| `class` | 本机设备类列表,匹配 `device:<class>` scope |
| `projects` | 信息性;真正落地看 `[[targets]]` |
| `collect_sources` | `collect` 扫描的记忆源目录 |
| `[paths]` | 符号根表;必须含 `VAULT`,通常含 `CLAUDE_HOME`/`CODEX_HOME` |
| `[[targets]]` | 每段一个工程:`project`(与 scope 对应)+ `root`(工程根目录) |

> TOML 陷阱:`class`/`projects`/`collect_sources` 这些**裸键必须写在 `[paths]`/`[[targets]]`
> 之前**,否则会被归进后面那个表里。scaffold 生成的模板已排好序。

---

## 4. 记忆文件格式

```markdown
---
name: p_vlcd
description: xinao 阀控坑
metadata:
  type: project            # project | user | feedback | reference
  scope: [project:xinao]   # 见下方 scope 语义
  portable: true           # false=依赖本机路径,仅能解析路径的设备才落地
  sensitive: false         # true=绝不进金库、绝不落地
---
vlcd_default 别乱改,对账要对齐 xinao。正文引用路径用 $VAULT/... 不要写死绝对路径。
```

**scope 语义**(决定「哪条记忆给哪台机/哪个工具/哪个工程」):

- 维度:`device:<class>`、`project:<id>`、`tool:<claude|codex>`、`global`
- **维度间 AND、同维度多值 OR、缺省维度不限、`global` 必须独占**
- 例:`[device:work, tool:claude]` = 只有 work 机上的 Claude 命中;
  `[project:xinao]` = 只在 xinao 工程命中;`[global]` = 处处命中

---

## 5. 命令一览

| 命令 | 作用 | 联网 |
|---|---|---|
| `collect` | 扫 `collect_sources` 把记忆整文件收进金库(跳过 sensitive/派生) | 否 |
| `process` | lint(scope/裸路径/敏感混入)+ 重生成 `MEMORY.md` + 本地提交 | 否 |
| `pull` | `acquire`(拉取自动合并)+ materialize 到 targets 与用户级 | 拉取需 |
| `sync` | `acquire`(真冲突即停,返回 2)+ lint 闸(失败返回 1)+ 推送 | 是 |
| `status` | 金库 `git status --porcelain` | 否 |
| `bootstrap` | = `pull`(首次落地) | 拉取需 |

---

## 6. 记忆怎么分流(pull 的落地目标)

同一批记忆按 scope 精确落到不同位置:

| 目标位置 | 收哪些记忆 |
|---|---|
| 各 target 的 `AGENTS.md`(managed block) | 全部规则 + 命中该工程的 `project:` 记忆块 |
| 各 target 的 `CLAUDE.md` | 只 `@AGENTS.md`(块外手写内容原样保留) |
| `$CLAUDE_HOME/hub/memory-index.md`(bundle) | 命中本机的 **非工程** 记忆(global/device);`$ROOT` 已解析 |
| `$CLAUDE_HOME/CLAUDE.md` | 加一行 `@hub/memory-index.md` 导入(managed block) |
| `$CLAUDE_HOME/projects/<编码路径>/memory/` | 命中该工程的 `project:` 记忆(Claude 原生工程记忆) |
| `$CODEX_HOME/memories/` | 命中本机的 **非工程** 记忆(整文件) |

`managed block` = `<!-- hub:begin -->…<!-- hub:end -->`,块外你手写的内容永远保留。

---

## 7. 符号根(可移植性)

记忆正文里**不要写死绝对路径**(`process` 的 lint 会拦裸路径),改用符号根:

```
配置见 $VAULT/config/base.md    →  落地时按本机 [paths].VAULT 解析
```

`$VAULT`、`$CLAUDE_HOME`、`$CODEX_HOME`、`$SECRETS` 等取自设备档案 `[paths]`。
未定义的根会被跳过并标注,不会写出坏链接。

---

## 8. 安全不变量

- **敏感隔离**:`sensitive:true` 的记忆有三道闸——`collect` 不收、`process` 的 lint
  拦停、materialize 的 `select_for_target` 排除——**绝不进金库、绝不落地**。
- **离线优先**:`collect`/`process` 全本地(`process` 只本地 commit,不 push);
  只有 `sync` 联网。断网也能干活。
- **对等 merge**:两台机各加不同记忆文件会自动合并;只有改了同一文件同一处才算真冲突,
  `sync` 停下让你手工解决(返回码 2)。

---

## 9. 已知限制(MVP)

- **原子记忆文件**(Codex 用户级、Claude 工程级)落地时**不解析 `$ROOT`**,原样写出;
  只有 Claude `memory-index.md` bundle 会解析。强依赖解析后绝对路径的记忆,暂放 bundle 侧。
- **无陈旧文件清理**:某条记忆 scope 改走后,旧的原子文件会残留在
  `~/.codex/memories/` 或 `~/.claude/projects/.../memory/`(bundle 会整体重写自愈)。
- **collect 同名覆盖**:两个 `collect_sources` 里同 `name` 的记忆,后者静默覆盖前者
  (约定 `name` 全局唯一)。

---

## 10. 多机 / NAS 用法

1. 一台机上 `scaffold_vault` 建库,`git remote add origin <NAS 上的裸仓>`,`sync` 推上去。
2. 其它机 `git clone` 下来,在 `devices/` 里加**本机**的 `<host>.toml`(路径按本机填)。
3. 日常:本机改完记忆/规则 → `process` → `sync`(拉取自动合并 + 推送)→ 各机 `pull` 落地。

每台机都是完整处理节点,NAS 只当 git remote——离线也能 `collect`/`process`,联网再 `sync`。
