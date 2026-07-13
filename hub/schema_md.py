"""SCHEMA.md 的正文。单独一个模块，免得把长文本塞进 scaffold_vault.py。

这份文本是 A(提取器,本仓库,Python)与 C(加载器 skill,另一个项目,非 Python)
之间**唯一**的接口。改动这份文本前，先想一遍:C 阶段的人只读这份文件，读不到
这个仓库的任何一行代码。
"""

SCHEMA_MD = """# 金库 SCHEMA —— hub 与各工具 skill 之间的契约

这份文件是**唯一接口**。加载器 skill(hub-claude / hub-codex / …)读它,不读 Python 源码。
以后加新工具,只写一把新 skill,提取器一行不用改。

## 两个区

    vault/
    ├─ vault.toml  SCHEMA.md  MEMORY.md  lint-exempt.txt
    │
    ├─ <设备名>/                ┃ 备份区:这台机的原始数据,原样、不加工
    │   ├─ device.toml
    │   ├─ claude/  memory/ skills/ plugins/ hooks/ chats/ plugins.toml CLAUDE.md
    │   └─ codex/   skills/ hooks/ chats/ plugins.toml AGENTS.md
    │
    └─ shared/                 ┃ 共享区:跨设备/跨工具的精选,按类型分
        └─ memory/ skills/ plugins/ hooks/ chats/

**备份区 = "别丢"**。换机照它还原。按工具分,因为原始数据本来就是工具形状的。
**共享区 = "到处都要有"**。skill 照它装。按类型分——两个工具都吃 skill、都有插件系统。

## 谁写哪一区

| 区 | 写者 | 性质 |
|---|---|---|
| 备份区 `<设备>/` | **提取器(Python)** | 机械搬运,不做判断。**幂等全量重写** |
| 共享区 `shared/` | **skill** | 判断题:什么值得跨设备/跨工具共享 |
| 工具地盘 | **skill** | 判断题:什么该进我的脑子 |

**提取器只写 `<本机>/`。** 它不碰 `shared/`,不碰别的设备,不写任何工具的地盘。
唯一例外是 `hub bootstrap`(新机上把加载器 skill 装进工具,打破鸡生蛋),且只写 skill 目录。

## 记忆的格式

一条记忆 = 一个 md 文件,带 frontmatter:

```markdown
---
name: <kebab-case 短名，与文件名一致>
description: <一句话摘要——索引里显示的就是它>
metadata:
  type: user | feedback | project | reference
  scope: [global]          # 见下
  portable: true
  sensitive: false         # true = 不入金库（阶段 B 改成加密入库）
---

正文。用 [[其它记忆名]] 互链。
```

**记忆的位置**:备份区在 `<设备>/claude/memory/`(Claude 的著作物);共享区在 `shared/memory/`(工具无关——知识就是知识)。

**`~/.codex/memories/` 不收。** 那是 Codex 后台从任务里自动蒸馏的**生成态**目录,
官方明说"视为生成状态,不要依赖手工编辑"。格式不公开、不保证稳定,而且会触发自我复制回环
(hub 灌给它的记忆 → 它当"学到的事实"再蒸馏 → 又收回金库 → 又灌回去)。
**记忆的真源只有一处:hub 金库。**

## scope

- 同维度 OR,跨维度 AND,缺省的维度不限制。
- `global` 必须单独出现,不可与维度谓词混用。
- 维度:`device:<class>` / `project:<名>` / `tool:<名>`。

**匹配逻辑归 skill**——"这条记忆该不该进我的脑子"是加载侧的判断题。
提取器只做**格式校验**,自己从不按 scope 筛选任何东西(备份区是本机现状的镜像,不做选择)。

## 跨设备的人工闸门(由 skill 实现)

别的设备写的记忆**不会自动进本机**。skill 负责这道闸:

| 文件 | 位置 | 内容 |
|---|---|---|
| `merged.txt` | `<本机>/` | 已接纳的外来记忆,一行一条 `<归属>/<记忆名>` |
| `rejected.txt` | `<本机>/` | 拒绝过的,别再问。一行一条,格式同上 |

- **可见**:`shared/` 里的 + 本机自产的 + `merged.txt` 里列出的。
- **待审**:别的设备的,且不在 `merged.txt` / `rejected.txt` 里。
- skill 应当**先读一遍待审记忆的正文,判断是否适合合并到本机,给出建议**,由用户拍板。
- 用户说"全部去读一遍看看"时,**忽略 `rejected.txt` 重新过**。
- **提升到共享区** = 把 `<设备>/claude/memory/<名>.md` 移到 `shared/memory/<名>.md`。目标已存在同名时**停下来问**,绝不静默覆盖。

## 插件清单 `plugins.toml`

```toml
[repos.<插件名>]        # 只有"你自己写的"插件才有这一节（源码已快照在 plugins/ 下）
remote = "https://github.com/…"
sha = "<40 位>"
dirty = false           # true = 快照里没有工作区未提交的改动

[enabled]               # 第三方 + 自有，全部的启用状态
"superpowers@claude-plugins-official" = true

[marketplaces]
xu-local = "directory:C:\\\\Users\\\\x\\\\.claude\\\\plugins-dev"
```

**第三方插件只抄声明,不拷源码**(别人的代码,市场在就能重装;里面是 LSP 二进制,换台机就是废的)。

## 阶段 B 预留

`chats/` 与 `hooks/` 目前是空目录。

- **chats**:对话归档。要等加密层(阶段 B)——对话正文必定含密钥/公司代码,明文进 NAS 不可接受。
  设计意图:**加密入库,金库里只暴露名字**;要用时本地下载、本地解锁。
- **hooks**:当前 Claude 的 `settings.json` 没有 `hooks` 键(hook 全在插件里),Codex 也没有。
  一旦出现用户级 hook,由声明流水线填充。

## 硬闸(提取器强制,不靠自觉)

1. `~/.claude/secrets/`、`~/.codex/auth.json` —— **永不读取**。私密内容留在 secrets/,记忆里只写指针。
2. gitignored / untracked 文件 —— **不进快照**(用 `git archive`,不用 `cp -r`)。
3. `sensitive: true` 的记忆 —— **不入库**(阶段 B 改成加密入库)。
"""
