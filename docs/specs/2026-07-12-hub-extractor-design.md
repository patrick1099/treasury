# hub 提取器 · 设计(spec A)

> 2026-07-12。取代 `2026-07-09-shared-data-layer-mvp-design.md` 里的落地(materialize)部分,金库结构与后端分层继续沿用。

## 0. 这份 spec 管什么

hub 拆成三个独立子项目,本文只写 **A**:

| | 子项目 | 状态 |
|---|---|---|
| **A** | **提取器**:Python 把本机各工具的家当收进金库 | **本文** |
| B | 加密层:chats 与敏感内容加密入库,只暴露名字 | 待立 spec |
| C | 加载器 skill × N:在各工具里跑,读金库、装进自己脑子 | 待立 spec |

顺序 A → C → B。A 是地基:金库格式定下来,C 才有东西可读。

## 1. 转向的理由

原设计里 Python 既负责**收**(collect)也负责**发**(materialize:替 Claude 写记忆索引、替 Codex 写 `AGENTS.md`、替工程写 `CLAUDE.md`)。这个"发"的部分错了,而且是**结构性**地错:

它要求 Python 代码知道**每个工具怎么消费记忆**。2026-07-12 的落地验证里,这个假设当场破产——设计假定 Codex 从 `~/.codex/memories/` 读散装 md,于是往那儿写了 47 个文件。实际上那个目录当时并不存在(Codex 的 memories 特性默认关闭),而且就算开了,官方文档明写它是**生成态**:"视这些文件为生成状态……不要依赖手工编辑作为主要控制方式"。写进去等于污染 Codex 自己的流水线。

**每加一个工具,Python 就要猜一次它的内部约定,而猜错的代价是往用户真实机器上写垃圾。**

新的分工把这个知识赶出 Python:

> **Python 只负责把东西收集到一起(填金库);每个工具配一把自己的 skill,由用户在该工具里运行,skill 读金库、自己决定装什么、怎么装。**

最懂 Claude 怎么吃记忆的是 Claude,最懂 Codex 的是 Codex。让它们自己干。

## 2. 架构

```
      提取(Python,只进不出)                          加载(skill,在各工具里跑)

~/.claude/  projects/*/memory  skills/  ┐                           ┌→ Claude 的记忆 / skill 目录
            plugins-dev/  settings.json ├→ [hub collect] → 金库 →   │
~/.codex/   skills/  config.toml        ┘                  ⇅ git    ├→ Codex 的 hub/memory + AGENTS.md
            AGENTS.md                                      NAS      │
                                                                    └→ (以后的 Cursor / Gemini CLI…)
                                                                                ↑
                                                                       读金库的 SCHEMA.md
```

**铁律:提取器只写金库,不写任何工具的地盘。**

唯一的例外是 `bootstrap`(见 §6),它要在新机上打破鸡生蛋——那时候 skill 还在金库里,得先有人把它装进工具。除此之外,Python 对工具目录**只读**。

这条铁律顺带把上次的事故类型消灭了:提取器**唯一有权写的地方是金库,而金库是 git 仓**,误操作 `git checkout` 就回来。靶子被撤掉了,不是多加了一道防线。

**A 与 C 的唯一接口是金库根的 `SCHEMA.md`** —— 目录含义、frontmatter 格式、名单格式全写在里面。skill 读它,不读 Python 源码。以后加新工具只写一把新 skill,**Python 一行不动**。

## 3. 金库结构

```
hub-vault/
├─ vault.toml                    版本号
├─ SCHEMA.md                     契约(A↔C 唯一接口)
├─ MEMORY.md                     全库记忆索引(派生:名字 — 摘要 — 归属)
├─ lint-exempt.txt               裸路径检查的白名单
│
├─ 2025-bg-016/                  ┃ 备份区:这台机的原始数据,原样、不加工
│   ├─ device.toml               本机档案:class / projects / 各工具源路径
│   ├─ claude/                       ~/.claude 的备份
│   │   ├─ memory/                   记忆(著作物)
│   │   ├─ skills/                   散装 skill 源码快照
│   │   ├─ plugins/                  **自己写的**插件源码快照 + plugins.toml
│   │   ├─ hooks/                    hook 脚本 + 注册声明
│   │   ├─ CLAUDE.md
│   │   └─ chats/                    占位(阶段 B)
│   └─ codex/                        ~/.codex 的备份
│       ├─ skills/                   散装 skill 源码快照
│       ├─ plugins.toml              插件/市场声明(本机的三个插件全是第三方,故无源码)
│       ├─ hooks/
│       ├─ AGENTS.md
│       └─ chats/                    占位(阶段 B)
│
└─ shared/                       ┃ 共享区:跨设备/跨工具的精选,按类型分(工具无关)
    ├─ memory/                       记忆的唯一真源
    ├─ skills/
    ├─ plugins/
    ├─ hooks/
    └─ chats/                        占位(阶段 B)
```

**两个区的语义不同,别混:**

- **备份区 = "别丢"**。这台机现在**实际有什么**,原样躺在这。换机照它还原。按工具分文件夹,因为原始数据本来就是工具形状的(Claude 的 skill 装 `~/.claude/skills/`,Codex 的装 `~/.codex/skills/`)。
- **共享区 = "到处都要有"**。你**挑出来**要在所有设备、所有工具里都出现的东西。按类型分,不按工具分——两个工具都吃 skill、都有插件系统,再按工具切就是同一把 skill 存两份。

**谁写哪一区:**

| 区 | 写者 | 性质 |
|---|---|---|
| 备份区 `<设备>/` | **Python 提取器** | 机械搬运,不做判断 |
| 共享区 `shared/` | **skill(C 阶段)** | 判断题:什么值得共享 |
| 工具地盘 | **skill(C 阶段)** | 判断题:什么该进我的脑子 |

提取器**只动 `<本机>/`**,别的设备的文件夹碰都不碰,`shared/` 一个字不写(只读它来算索引)。两台机各写各的,git 零冲突。

### 不备份的东西(明确列出,免得以后疑惑)

| 东西 | 为什么不收 |
|---|---|
| `~/.claude/secrets/`、`~/.codex/auth.json` | 密钥总库。见 §5 硬闸 1 |
| `~/.codex/memories/` | **生成态**。官方明说别手改;格式不公开、不保证稳定;而且会触发自我复制回环(见下) |
| `plugins/cache`、`plugins/data`(两边共 65 MB) | 第三方市场插件。别人的代码,市场在就能重装;里面是 LSP 二进制,换台 Mac 就是废的;每次更新都变,git 里会不停堆 delta |
| `memories_*.sqlite`、`logs_*.sqlite`(72 MB) | Codex 的内部流水线/日志,不是给外部读写的 |
| gitignored / untracked 文件 | 见 §5 硬闸 2 |

**Codex 原生 memories 的自我复制回环**:若开启该特性,Codex 会看见 `AGENTS.md` 里 hub 灌给它的记忆索引 → 后台把它们当"学到的事实"再蒸馏一遍 → 存进 `~/.codex/memories/` → 若 hub 收进备份区并提升进 `shared/` → 又灌回去。**记忆会自我复制。** 从根上断掉:不收。记忆的真源只有一处——hub 金库。

## 4. 提取器的流水线

每条都**幂等、全量重写**:跑一百遍结果一样。

| 源 | 手法 | 落点 |
|---|---|---|
| **记忆** | 读 md + 校验 frontmatter | `<机>/claude/memory/` |
| **散装 skill** | 整目录拷贝 | `<机>/claude/skills/`、`<机>/codex/skills/` |
| **自己写的插件** | `git archive HEAD` 快照 | `<机>/claude/plugins/<名>/` |
| **第三方插件** | 抄声明(市场 + 插件名 + 启用状态) | `<机>/*/plugins.toml` |
| **hooks** | 拷脚本 + 从 `settings.json` / `config.toml` 抄注册声明 | `<机>/*/hooks/` |

### 4.1 插件:按"是不是你的产出"分,不按工具分

- **你写的**(`~/.claude/plugins-dev/` 六个仓:cjt / keil2clangd / xinao-csb-skills / xu-skills / true-north / compact-plus)→ **源码快照**。唯一副本风险:GitHub 没了就真没了。
- **第三方**(superpowers / gmail / github / clangd-lsp…)→ **抄声明**。

快照用 `git archive HEAD`,不是 `cp -r`。理由:

1. **只含 git 跟踪的文件** —— `.git`、`node_modules`、构建产物、`.env` 自动出不去。实测六个仓的快照加起来 **~1 MB**(原样拷是 22 MB)。
2. **不产生嵌套仓** —— 把带 `.git` 的目录原样拷进另一个 git 仓,外层会把它记成一个 gitlink 空壳,新机 clone 下来是**空目录**。你以为备份了,其实没有。这是必须避开的经典坑。

旁边配 `plugins.toml`,记 **remote + commit sha + 启用状态**。于是两条恢复路径都通:GitHub 活着就 clone 真仓(带历史),GitHub 没了就从 NAS 快照恢复(无历史,代码全在)。sha 一比还能看出金库快照跟 `plugins-dev` 漂移了没有。

Codex 本机那三个插件(superpowers / gmail / github)**恰好全是第三方**,所以它只有 `plugins.toml` 没有源码目录——这是**结果**,不是双标。它的三把散装 skill 照样拷源码。

### 4.2 记忆:镜像语义

`collect` 对 `<本机>/claude/memory/` 做**镜像同步**:本机删了一条,金库里本机那份也删。别的设备的文件夹**碰都不碰**——本机的 collect 凭什么删别人写的东西。

删之前**列出清单等确认**;`--yes` 才无人值守。

> **未来方向(本版不做)**:墓碑(tombstone)——本机删除时留一个 `<名>.deleted` 标记,别的设备同步时看得见、可选择跟进。眼下只有一台设备,YAGNI。但 `SCHEMA.md` 里给标记文件预留命名,免得以后加进来要改格式。

### 4.3 派生目录

`skills/` `plugins/` `hooks/` 声明为**派生目录**,提取器每次全量重写。

这把用户那条"金库只拉取同步、不在里面开发"的约定从**自觉**升级成**机制**:金库那份改了也白改,下次 collect 直接覆盖。**真源永远在 `plugins-dev` / `~/.claude/skills`**,不会出现"哪份才是真的"的悬案。

### 4.4 索引

`MEMORY.md`:扫全库记忆,生成 `名字 — 摘要 — 归属设备`。派生物,每次重算。

C 阶段的 skill 靠它决定读哪几条正文,**不用把全文塞进上下文**(47 条全文 85 KB,索引 7.3 KB)。这是照抄 Claude 原生记忆的做法:上下文里常驻索引,正文躺在磁盘、用到才读。

## 5. 安全闸

### 三道硬闸(确定性,不靠自觉)

| 闸 | 拦什么 | 阶段 A | 阶段 B |
|---|---|---|---|
| 1 | `~/.claude/secrets/`、`~/.codex/auth.json` | 永不提取 | **仍不提取** |
| 2 | gitignored / untracked 文件 | 不收(`git archive` 天然做到) | 仍不收 |
| 3 | `sensitive: true` 的记忆、chats | 不收 | **加密入库,只留名字** |

**闸 1 为什么连加密了也不进金库**:`secrets/` 是**全部密钥的单一集合**。整包搬到 NAS 等于把所有鸡蛋装进一个篮子——主密钥一泄,一次性全崩。而它换机时本来就有专门通道(`ai-cli-migrate` 点对点搬),不需要金库掺一脚。风险收益完全不对称。阶段 B 可以留一个可选的 `<机>/secrets.age` 单文件后门,**默认关闭,钥匙绝不进金库**。

**闸 3 是留给 B 的那一格**,对应用户原话:"密钥和对话,只暴露名字,真要用我本地下载下来,然后本地解锁。"阶段 A 里 sensitive 记忆和 chats 一律不收(明文躺 NAS 不可接受)。

### 一道软提醒(启发式,只提醒不阻断)

扫高熵串 / 已知前缀(`sk-` `ghp_` `AKIA` `LTAI` `eyJ…`),命中就在 collect 末尾打一份"疑似密钥清单"。

**不阻断**,因为误报率高到不能当闸:实测扫 `plugins-dev` 的 10 条命中**全是误报**——正则里的 `sk-` 撞上了 `ta`**`sk-`**`fix3-report`。阻断只会逼人无脑加白名单,闸就废了。

**它的真正用途是提醒你打 `sensitive` 标。** 2026-07-12 那两条含密钥的记忆(`reference_oss_picgo_imghost` 的阿里云 OSS 凭据、`reference_mineru_extractor` 的 MinerU token)之所以漏进金库,就是**没人给它们打标**——而它们违反的其实是用户自己定的规矩:密钥该躺在 `~/.claude/secrets/`,记忆里只留指针。

**提取器的工作不是猜哪里有密钥,是把这条约定变成机器强制执行的规则。**

## 6. CLI

| 命令 | 干什么 |
|---|---|
| `collect` | 跑五条流水线,填备份区。`--dry-run` 预览,`--yes` 免确认 |
| `sync` | git pull --rebase + push(NAS) |
| `status` | 各设备有什么、本机跟金库的差异、软提醒清单 |
| `bootstrap` | 换新机:clone 金库 + **把 `hub-*` skill 装进各工具**,然后退场 |

**删掉**:`pull` / `process` / `review` / `accept` / `reject` / `promote`。这些全是判断题,归 C 阶段的 skill。

`bootstrap` 是铁律的唯一例外:新机上还没有 skill(skill 自己也在金库里),这是个鸡生蛋。`bootstrap` 的唯一职责就是打破它——拉金库、把加载器 skill 装进 Claude 和 Codex,然后**退场**。这是 Python 唯一一次被允许写工具地盘,且只写 skill 目录。

## 7. 错误处理

每条都对应一个已经踩过的坑:

1. **frontmatter 解析失败 → 报错,不许静默跳过。** 现在 `collect` 把异常吞了,`project_ai_hub_shared_data_layer` 就是这么悄无声息地漏掉的(它的 frontmatter 用了 YAML 块状列表,解析器不认)。改成:打印文件名 + 原因,**退出码非零**。
2. **`plugins-dev` 有未提交改动 → 警告。** `git archive HEAD` 只打包已提交的东西;工作区里改了没提交的代码**不在快照里**。不警告的话你以为备份了,备份的其实是旧版。
3. **源不存在 → 静默跳过,不是错误。** Codex 的 memories 没开、某台机没装 Claude,都属正常。
4. **镜像删除 → 先列清单等确认。** `--yes` 才无人值守。
5. **`--dry-run` 的闸设在最底层的 `_write` 里**,预览和真写共用同一条代码路径。这条是 2026-07-12 用事故换来的:配置式预览的失败模式是"照真实的写",闸设在写函数里的失败模式是"什么都不写"。不动。

**保留 lint**:记忆正文里的裸绝对路径(`C:/Users/huawei/…`)警告——跨设备会断链,要用 `$CLAUDE_HOME` 这类符号根。`lint-exempt.txt` 白名单保留。

### `scope` 字段归谁

`scope`(`global` / `tool:claude` / `device:work` / `project:xinao`)**继续存在于 frontmatter**,语义写进 `SCHEMA.md`。但**匹配逻辑归 C**——"这条记忆该不该进我的脑子"是加载侧的判断题。

Python 这边只剩**格式校验**(`scope.py` 的 `lint_scope`):同维度 OR、跨维度 AND、缺省维度不限制、`global` 必须独占。**提取器自己从不按 scope 筛选任何东西**——备份区是本机现状的镜像,不做选择。

## 8. 代码变动

**删**
- `materialize.py`(整个)
- `roster.py` 的**逻辑**(格式定义搬进 `SCHEMA.md`,供 skill 实现)
- `tests/hub/test_materialize.py`、roster 相关测试

**改**
- `collect.py` → 拆成包:`collect/memory.py` `skills.py` `plugins.py` `hooks.py`
- `cli.py` → 四个子命令
- `scaffold_vault.py` → 新结构,并生成 `SCHEMA.md`
- `vault.py` → 读新的两区结构

**原样保留**(它们没错,不该连坐)
- `backend.py`(git)、`frontmatter.py`、`links.py`、`scope.py`、`model.py`、`derive.py`、`managed_block.py`

## 9. 测试

扩 `test_collect.py`,覆盖五条流水线 + 五条错误处理:

- `git archive` 快照不含 `.git` / `node_modules` / gitignored 文件
- 带 `.git` 的目录进金库后**不是** gitlink 空壳
- `plugins.toml` 正确抄出 remote / sha / 启用状态
- 记忆镜像:本机删了 → 金库本机那份删;**别的设备的文件夹不动**
- `shared/` 在 collect 前后**逐字节不变**
- frontmatter 坏了 → 非零退出 + 指名道姓,**不静默跳过**
- `plugins-dev` 有未提交改动 → 警告
- 源目录不存在 → 跳过不报错
- `--dry-run` → 金库**零写入**
- 硬闸:`secrets/` 下的文件永不出现在金库里

保留:`test_backend.py` `test_scope.py` `test_frontmatter.py` `test_links.py` `test_vault.py`。

## 10. 一次性迁移(对现有真实金库 `C:\Users\huawei\hub-vault`)

1. 47 条记忆:`2025-bg-016/memory/` → `2025-bg-016/claude/memory/`
2. 建新目录结构,清掉 scaffold 遗留的空目录,写 `SCHEMA.md`
3. `device.toml` 重写:按工具列源路径
4. **两条含密钥的记忆**:`reference_oss_picgo_imghost`(阿里云 OSS 凭据)、`reference_mineru_extractor`(MinerU token)。密钥挪进 `~/.claude/secrets/`,记忆正文改成指针。按用户全局约定,**存之前先确认文件名和用途,并在 `INDEX.md` 补一行**。
5. 重算 `MEMORY.md`

## 11. 开口项(不在本 spec 内)

- **NAS 裸仓 + `sync` 从未验证** —— 眼下只有一台设备,金库只在本机 git。
- **B(加密层)** —— chats 提取被它挡着;`sensitive` 记忆在它做完之前一律不入库。
- **C(加载器 skill)** —— 跨设备人工闸门(`merged.txt` / `rejected.txt` / 提升进 `shared/`)的**格式**由本 spec 的 `SCHEMA.md` 定义,**逻辑**归 C。
