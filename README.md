# qcc-lead-pipeline

把「情报邮件」自动转成「可外呼的客户清单」的 Agent Skill。

> 技能名 `lead-pipeline`，仓库名 `qcc-lead-pipeline`（避免与同名销售工具混淆）。

一次跑完四件事：**收信抽企业 → SQLite 去重落库 → 按可得性排队 → 企查查 MCP 批量查号 → 号码清洗出 Excel**。

```
邮箱收信 ──► 抽企业名 ──► leads.db 去重 ──► 待查队列(按可得性排序)
                                                        │
                                        企查查 MCP 查联系方式(按次计费)
                                                        │
                          手机号清洗结果.xlsx ◄── 号码四分流 + 共用号识别
```

## 安装

把本目录放进你的 Agent skill 目录（Claude Code / opencode 等）。注意仓库名和技能名不同，克隆后要重命名成技能名：

```bash
git clone https://github.com/dgfcbbhhv/qcc-lead-pipeline.git ~/.claude/skills/lead-pipeline
```

技能名必须与目录名一致（即 `SKILL.md` frontmatter 里的 `name: lead-pipeline`），否则客户端识别不到。

或直接把目录拷进去即可，无构建步骤。

## 依赖

| 依赖 | 用途 | 必需 |
|---|---|---|
| Python 3.10+ | 跑 `scripts/` | 是 |
| [openpyxl](https://pypi.org/project/openpyxl/) | 出 Excel | 是 |
| `agently-cli` | 读 agent 邮箱 | 收信步骤需要 |
| 企查查 MCP | 查联系方式 | 查号步骤需要 |

```bash
pip install openpyxl
```

## 配置

全部通过环境变量，均可缺省：

| 变量 | 作用 | 缺省 |
|---|---|---|
| `LEAD_HOME` | 数据目录，放 `leads.db` 与产出 Excel | 脚本所在目录 |
| `AGENTLY_CLI` | `agently-cli` 可执行文件完整路径 | `agently-cli`（走 PATH） |
| `LEAD_SENDER` | 情报源发件人，填了只收该发件人 | 空（不限制） |
| `BARK_URL` | 跑完推送结果摘要（仅 `--bark`） | 空（不推送） |

```bash
export LEAD_HOME=~/lead-data
export AGENTLY_CLI=/path/to/agently-cli.cmd   # 非全局安装时必填
export LEAD_SENDER=intel@example.com
```

## 用法

```bash
cd <skill目录>

# 步骤 1：收单（--all 必须带，否则漏掉大部分企业）
python scripts/collect.py --all

# 步骤 2：查手机号 —— 这一步走 MCP，不是脚本
#   从 待查队列_自动.json 头部开始，用 mcp__qcc-company__get_contact_info 逐家查
#   每约一批存一个 qcc_results_batchN.json

# 步骤 3：入库 + 清洗 + 出表
python scripts/db.py
python scripts/clean.py

# 或者一键
python scripts/pipeline.py            # 收单 + 清洗 + 汇总
python scripts/pipeline.py --no-mail  # 跳过收信，只重算
python scripts/pipeline.py --bark     # 结束推送
```

## 关键约束

- **`leads.db` 是权威账本**，记录哪些企业已查过，**禁止删除或重建**。所有去重都依赖它，
  删了会重复烧计费额度。
- 查号**从队列头部开始**（有限公司优先），**队尾的个体工商户直接跳过**（可得性极低）。
- `get_contact_info` **按次计费**。查过的绝不再查。
- 遇到 `MCP error 300008`（积分余额不足）立即停止，已查数据先存盘。

## 产出

| 文件 | 说明 |
|---|---|
| `leads.db` | SQLite 账本，`companies` 表记录查询状态 |
| `待查队列_自动.json` | 按预期可得性从高到低排序 |
| `qcc_results_batchN.json` | MCP 查询结果原始批次 |
| `手机号清洗结果.xlsx` | 3 个 sheet：清洗总表 / 共用号码(疑似代账) / 清洗统计 |
| `clean_results.json` | 清洗后结构化结果，便于追加批次 |

## 目录结构

```
qcc-lead-pipeline/         # 仓库名；安装时目录须为 lead-pipeline（= 技能名）
├── SKILL.md              # 技能主文件（frontmatter + 标准流程）
├── LICENSE               # MIT
├── references/
│   └── pitfalls.md       # 主体类型分层、计费口径、避坑清单、DB Schema
└── scripts/
    ├── collect.py        # 收信 + 抽企业名 + 入库
    ├── db.py             # SQLite 账本：去重、状态、可得性排序
    ├── clean.py          # 号码四分流 → Excel
    └── pipeline.py       # 一键编排
```

## 主体类型分层

联系方式登记情况按主体类型差异极大，这是队列排序的核心依据：

| 主体类型 | 可得性 | 策略 |
|---|---|---|
| 有限公司 | 高 | 优先查 |
| 厂（非个体户） | 中 | 查 |
| 商行/经营部/店 | 低 | 查 |
| **个体工商户** | **极低** | **跳过** |

> 具体权重见 `db.py:pending()`，可按你自己的数据源回填。
> 详见 `references/pitfalls.md`，含计费口径与 7 条避坑清单。

## License

MIT
