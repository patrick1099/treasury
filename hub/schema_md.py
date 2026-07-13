"""SCHEMA.md 的正文。单独一个模块，免得把长文本塞进 scaffold_vault.py。

这份文本是 A(提取器,本仓库,Python)与 C(加载器 skill,另一个项目,非 Python)
之间**唯一**的接口。改动这份文本前，先想一遍:C 阶段的人只读这份文件，读不到
这个仓库的任何一行代码。凡是他需要知道的,都得写在这儿——写不清楚的地方,
他就只能猜,而猜错会静默地毁掉用户的记忆。
"""

SCHEMA_MD = """# 金库 SCHEMA —— hub 与各工具 skill 之间的契约

这份文件是**唯一接口**。加载器 skill(hub-claude / hub-codex / …)读它,不读 Python 源码。
以后加新工具,只写一把新 skill,提取器一行不用改。

读这份文件的是 C 阶段(加载器)的作者:**你看不到提取器的代码,也问不到人。**
凡是你需要知道的都应该写在这里;写不清楚的地方就是本文件的 bug,回来补。

## 0. 两个角色

| 谁 | 是什么 | 写哪儿 |
|---|---|---|
| **提取器** | Python(`hub`),机械搬运,不做判断 | **只写 `<本机>/`**,外加金库根的派生文件 `MEMORY.md` |
| **加载器 skill** | 你要写的东西,全是判断题 | `shared/`、各工具地盘、`<本机>/merged.txt` `rejected.txt` |

**提取器不碰 `shared/`,不碰别的设备,不写任何工具的地盘。**
唯一例外是 `hub bootstrap`(新机上把加载器 skill 装进工具,打破"skill 自己也在金库里"
这个鸡生蛋),且只写各工具的 `skills/` 目录。

## 1. 两个区

    vault/
    ├─ vault.toml        金库格式版本(version = 1)。以后改布局靠它做迁移判断
    ├─ SCHEMA.md         就是本文件
    ├─ MEMORY.md         全部记忆的索引(派生物,勿手改——见 §5)
    ├─ lint-exempt.txt   裸路径检查的豁免名单(见 §4)
    │
    ├─ <设备名>/          ┃ 备份区:这台机的原始数据,原样、不加工
    │   ├─ device.toml   本机档案(见 §3)
    │   ├─ merged.txt    ┓ 跨设备人工闸门,由 skill 维护(见 §7)
    │   ├─ rejected.txt  ┛
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ plugins.toml CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    │
    └─ shared/           ┃ 共享区:跨设备/跨工具的精选,按类型分
        └─ memory/ skills/ plugins/ hooks/ chats/

**备份区 = "别丢"**。换机照它还原。**按工具分**,因为原始数据本来就是工具形状的。

**共享区 = "到处都要有"**。skill 照它装。**按类型分,且工具无关**——`shared/` 里
**没有** `claude/` / `codex/` 子目录。两个工具都吃 skill、都有插件系统;知识就是知识。

**`<设备名>` = `socket.gethostname().lower()`**(**全小写**)。加载器靠它回答"这些顶层
文件夹里哪个是我"。认错了后果很实:`merged.txt` 会写进一个不存在的设备目录,而且
**本机自产的记忆会全部被当成"别的设备来的、待审"**,永远审不完。

## 2. 记忆

一条记忆 = 一个 `.md` 文件,**文件名必须是 `<name>.md`**(与 frontmatter 里的 `name` 一致)。

```markdown
---
name: my-note
description: 一句话摘要——MEMORY.md 索引里显示的就是它
metadata:
  type: user | feedback | project | reference
  scope: [global]
  portable: true
  sensitive: false
---

正文。用 [[其它记忆名]] 互链。跨设备的路径写符号根,别写绝对路径(见 §4)。
```

### frontmatter 是 YAML 的一个**受控子集**,不是完整 YAML

提取器自带一个小解析器(不依赖 PyYAML)。**它不剥引号。** 你按标准 YAML 的习惯写
`name: "my-note"`,提取器拿到的 `name` 就是**带引号的那 9 个字符**,随后会去写一个
文件名里带引号的文件(NTFS 上非法);`scope: ["global"]` 会被解析成 `['"global"']`,
scope 校验判它非法,`hub sync` 直接停住。

**只准用这些**:

| 允许 | 写法 |
|---|---|
| 不带引号的纯标量 | `name: my-note` |
| 布尔(**小写**) | `portable: true` / `sensitive: false` |
| 行内列表 | `scope: [global]` / `scope: [device:work, tool:claude]` |
| 块状列表 | `scope:` 换行,下面 `  - device:work` |
| **一层**嵌套(只有 `metadata:` 用到) | 见上例 |

**不准用**:引号、锚点/别名、多行标量(`|` / `>`)、两层以上嵌套、行内注释。
越界不会被静默吞掉——提取器抛错并**点名是哪个文件**。

### scope

- 同维度 **OR**,跨维度 **AND**,没写的维度**不限制**。
- `global` **必须单独出现**,不可与维度谓词混用(混了就是非法,`hub sync` 会停)。
- 维度只有三个:`device:<class>` / `project:<名>` / `tool:<名>`。

`device:<class>` 里的 `<class>` 对的是 **`device.toml` 的 `class` 数组**(见 §3),
**不是设备名**。那是你能拿到 class 的唯一地方——读不到 `device.toml`,你就判不了
`device:` scope,多半会把它当 global 放行,于是**公司机器的记忆漏到家里的机器上**,
而 scope 存在的全部意义就是防这个。

**匹配逻辑归 skill。** "这条记忆该不该进我的脑子"是加载侧的判断题。提取器只做**格式校验**,
自己从不按 scope 筛掉任何东西(备份区是本机现状的镜像,不做选择)。

### `~/.codex/memories/` 不收

那是 Codex 后台从任务里自动蒸馏的**生成态**目录,官方明说"视为生成状态,不要依赖手工编辑"。
格式不公开、不保证稳定,而且会触发**自我复制回环**(hub 灌给它的记忆 → 它当"学到的事实"
再蒸馏一遍 → 又被收回金库 → 又灌回去)。**记忆的真源只有一处:hub 金库。**

## 3. `device.toml`(每台设备一份,在 `<设备名>/device.toml`)

加载器**必须**读它:`class` 是判 `device:` scope 的唯一依据,`[paths]` 是符号根的符号表。

```toml
class = ["work"]              # 本机的类别。device:<class> 谓词对的就是这里
projects = []                 # 本机在做的工程编码。project:<名> 谓词对这里

[paths]                       # 符号表:符号根 → 本机的真实绝对路径(见 §4)
VAULT = "C:/Users/x/hub-vault"
CLAUDE_HOME = "C:/Users/x/.claude"
CODEX_HOME = "C:/Users/x/.codex"

[sources.claude]              # 提取器去哪儿收东西。缺项 = 本机没那个源,不是错误
memory = ["C:/Users/x/.claude/projects/<工程编码>/memory"]   # 可以多个
skills = "C:/Users/x/.claude/skills"
plugin_repos = "C:/Users/x/.claude/plugins-dev"   # 自己写的插件仓所在目录
settings = "C:/Users/x/.claude/settings.json"
agents = "C:/Users/x/.claude/CLAUDE.md"

[sources.codex]
skills = "C:/Users/x/.codex/skills"
settings = "C:/Users/x/.codex/config.toml"
agents = "C:/Users/x/.codex/AGENTS.md"
```

`[sources.*]` 是**提取器**的输入,加载器一般不用管;`class` / `projects` / `[paths]`
是**加载器**要用的。

## 4. 符号根:记忆正文里**不许出现绝对路径**

同一条记忆要在多台机器上用,而 `C:\\\\Users\\\\huawei\\\\...` 换台机就是死链。所以正文里
一律写**符号根**,由加载器在装进工具时展开成本机真实路径:

    $VAULT/shared/memory/x.md   →   C:/Users/x/hub-vault/shared/memory/x.md
    $CLAUDE_HOME/skills/foo     →   C:/Users/x/.claude/skills/foo

- 符号形如 `$大写符号名`,后面可跟 `/子路径`。符号表 = `device.toml` 的 `[paths]`。
- 表里没有的符号**原样留着**(不瞎猜),加载器应当把它报出来。
- **展开是加载器的活。** 提取器只搬运,不展开。

**提取器带一道 lint**:`hub sync` 会扫所有记忆正文,**发现绝对路径就拒绝 sync**。
所以加载器如果把展开后的绝对路径写回了 `shared/` 里的记忆,用户下一次 `hub sync`
就会失败在一个他没听说过的检查上。**写回金库的正文必须是符号形式。**

`lint-exempt.txt`(金库根)是这道检查的**逃生舱**:一行一个记忆 `name`,列进去的记忆
跳过裸路径检查。用于那种正文里的绝对路径纯属信息性备注("装在哪 / 笔记在哪")、
根本不是跨设备链接、也没有符号根可映射的记忆。`#` 开头是注释,空行忽略。
**豁免只放行"裸路径"这一项——scope 非法与 sensitive 泄漏照样硬拦。**

## 5. `MEMORY.md`(金库根,派生物)

全部记忆的索引。**它存在的理由**:让加载器读一份索引就能决定该读哪几条正文,而不必
把全部正文塞进上下文(实测 47 条正文 85 KB,索引 7.3 KB)。

格式,一行一条:

    - [<name>](<相对金库根的路径>) — <description>

按 `(归属, name)` 排序;`归属` 是 `shared` 或某个设备名。首行是一句"自动生成,勿手改"的注释。

**每次 `hub collect` 和 `hub sync` 都整份重算、整份重写。** 手改必被覆盖——要改内容,
去改记忆文件自己的 frontmatter。

## 6. 同一个名字同时出现在两个区

**这是正常的,不是错。** 一条记忆被提升进 `shared/` 之后,它在 `~/.claude` 里还在,
所以下一次 `collect` 又会把它镜像进 `<本机>/claude/memory/`。于是两个区各有一份。

就像一个文件既在你的笔记本上、又在云盘里:**备份区 = "这台机有啥",共享区 = "大家都该有啥"**,
两者不矛盾。索引里会照实列两行(各带自己的归属)。

真正会咬人的只有一件事:**两份会分岔**——你把 `shared/` 那份改好了,而 `<本机>/` 那份
还是从 `~/.claude` 镜像回来的旧内容。规矩:

> **同名冲突时,`shared/` 那份是权威。**

删除的方向是反的,而且**故意**如此:你在工具里删掉一条记忆,下次 `collect` 会把
`<本机>/claude/memory/` 里那份一起删掉,但 **`shared/` 那份纹丝不动**(提取器永不写
`shared/`)。所以"在本地删掉"**不等于**"从共享区撤回"——撤回是 skill 的活。

## 7. 跨设备的人工闸门(由 skill 实现)

别的设备写的记忆**不会自动进本机**。skill 负责这道闸:

| 文件 | 位置 | 内容 |
|---|---|---|
| `merged.txt` | `<本机>/` | 已接纳的外来记忆,一行一条 `<归属>/<记忆名>` |
| `rejected.txt` | `<本机>/` | 拒绝过的,别再问。一行一条,格式同上 |

- **可见**:`shared/` 里的 + 本机自产的 + `merged.txt` 里列出的。
- **待审**:别的设备的,且不在 `merged.txt` / `rejected.txt` 里。
- skill 应当**先读一遍待审记忆的正文,判断是否适合合并到本机,给出建议**,由用户拍板。
- 用户说"全部去读一遍看看"时,**忽略 `rejected.txt` 重新过**。
- **提升到共享区** = 把记忆**复制**一份到 `shared/memory/<名>.md`。目标已存在同名时
  **停下来问**,绝不静默覆盖。(是"复制"不是"移动"——见 §6:源文件还在工具里,
  下次 collect 照样把它镜像回备份区,"移动"是做不到的。)

这两个文件在 `<本机>/` 根下,**提取器不会动它们**(它只重写 `<本机>/<工具>/` 里面的东西,
见 §9)。放心写。

## 8. 插件清单 `plugins.toml`(`<设备>/claude/` 和 `<设备>/codex/` 下各一份)

```toml
[repos.<插件名>]        # 只有"你自己写的"插件才有这节(源码已快照在同级 plugins/ 下)
remote = "https://github.com/…"   # 没有 origin 时是空串 ""
sha = "<40 位>"                    # 快照取的就是这个 commit
dirty = false                     # true = 源仓工作区当时有未提交改动;快照取的是 HEAD,
                                  #        所以那些改动**没有**进快照

[enabled]               # 第三方 + 自有,全部的启用状态
"superpowers@claude-plugins-official" = true

[marketplaces]
xu-local = "directory:C:\\\\Users\\\\x\\\\.claude\\\\plugins-dev"

[hooks]                 # 见下——目前基本不会出现
```

**第三方插件只抄声明,不拷源码**(别人的代码,市场还在就能重装;里面是 LSP 二进制,
换台 Mac 就是废的)。

**`[hooks]` 的现状必须说清楚**:它抄的是 `settings.json` / `config.toml` 里的 `hooks` 键。
当前 Claude 的用户级 `settings.json` **没有** `hooks` 键(hook 全在插件里),Codex 也没有,
所以这张表通常根本不出现。**而且提取器现在也写不了它**:内置的 TOML 写出器只支持
字符串/布尔/整数,而 Claude 的 `hooks` 值是嵌套的字典套列表——真出现一个用户级 hook,
`hub collect` 会**抛错**(点名是哪个键、什么类型),而不是静默写出一坨垃圾。
这是有意的:**宁可响,不可错**。要支持 hook,得先给写出器补嵌套表——**那还没做**。

## 9. 提取器的重写粒度(别把东西放进会被整个铲掉的地方)

"备份区由提取器全量重写"这句话**粒度很要紧**,照字面理解会让你把闸门文件放错地方。
实际行为:

| 路径 | 行为 |
|---|---|
| `<设备>/<工具>/skills/` | **整个目录铲掉重建**。别往里放手写的东西 |
| `<设备>/claude/plugins/<仓名>/` | **每个仓的目录铲掉重建** |
| `<设备>/claude/memory/*.md` | **镜像**:本机源里有的写进来;源里没了的**从金库删掉** |
| `<设备>/<工具>/plugins.toml`、`CLAUDE.md`、`AGENTS.md` | 单个文件覆盖写 |
| **`<设备>/` 自己** | **从不 rmtree**。所以 `device.toml` / `merged.txt` / `rejected.txt` 安全 |
| `shared/` | **提取器从不写** |

一句话:**别往 `<设备>/<工具>/skills/` 或 `plugins/` 里塞任何手写文件**——下次 collect
就没了,而且不会报错。要放东西,放 `<设备>/` 根下(闸门文件那一层)或 `shared/`。

## 10. 删除、冲突、多设备、传输

- **删除**:在工具里删掉一条记忆 → 下次 `collect` 把 `<本机>/claude/memory/` 里那份也删掉
  (会先列出来让用户确认;`--yes` 跳过确认)。**注意**:一条你从别的设备合并过来、
  又写进了本机 `~/.claude` 的记忆,如果用户在工具里删了它,它同样会从本机备份区消失。
  `shared/` 那份不受影响。
- **同名冲突**:见 §6——`shared/` 优先。
- **多设备**:金库是一个 **git 仓**。别的设备的数据**只有在你 pull 之后本地才存在**。
  加载器要自己决定要不要先 pull。提取器的 `hub sync` 会做 pull/push,但它不是加载器的
  一部分,别指望它替你拉。
- **零冲突从哪来**:每台设备只写自己那个文件夹,两台机器永远碰不到同一个文件,所以
  git 合并天然不冲突。**这个性质是靠"提取器只写 `<本机>/`"维持的**——加载器如果去写
  别的设备的目录,它就没了。

## 11. 硬闸(提取器强制,不靠自觉)

**1. 密钥路径永不读取。** 路径里**任何一层**目录名/文件名命中 `secrets` / `auth.json` / `.env`
(**大小写不敏感**,按**路径组件整体**比对而不是子串——所以 `secretsanta.md` 是放行的),
并且**字面路径**和**解析后的真实路径**两边都查(符号链接 / junction 指过去也挡得住)。

命中后的行为分两种,你都得知道:

- 提取器**直接读**的源(记忆文件、`settings.json`、`CLAUDE.md`、skill 目录、插件仓)
  → **抛错中止**。
- 拷贝/解包**一整棵树**时,树**里面**命中的条目 → **静默跳过,同级的兄弟照拷**。
  后果:一个自带 `.env` 的 skill,备份里就是**没有**那个 `.env`,还原之后它是缺的。
  这是有意的取舍(宁可缺,不可漏),但你得知道备份**不是逐字节完整**的。

私密内容留在 `~/.claude/secrets/`,记忆里**只写指针**。

**2. 快照只收 git 跟踪的文件——但这只对 git 仓成立。**
skill 目录 / 插件仓**是 git 仓**时,用 `git archive HEAD` 打包:gitignored 和 untracked 的
文件天然进不去(顺带解决"把带 `.git` 的目录拷进外层 git 仓会变成 gitlink 空壳、clone
下来是空目录"这个更阴的问题)。
**不是 git 仓**时(散装 skill——恰恰是"唯一副本"风险最高的那种),退化成整棵目录拷贝:
**除了硬闸 1 挡掉的条目,里面什么都会被拷进去**,包括构建产物和临时文件。

**3. `sensitive: true` 的记忆不入库。** 提取器跳过它,并在报告里列出**名字**(只列名字,
不列内容)。等阶段 B(加密层)做完之后改成加密入库。

## 12. 阶段 B 预留

`chats/` 与 `hooks/` 目前是空目录。

- **chats**:对话归档。要等加密层——对话正文必定含密钥/公司代码,明文进 NAS 不可接受。
  设计意图:**加密入库,金库里只暴露名字**;要用时本地下载、本地解锁。
- **hooks**:见 §8——先得给 TOML 写出器补嵌套表。
"""
