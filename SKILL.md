---
name: lead-pipeline
description: 客户情报邮件自动采集流水线。当用户需要采集企业客户资料、从【情报速递】等情报邮件批量提取企业并查询手机号、生成客户联系清单时，应使用本技能。覆盖：agent 邮箱收信 → 企业名抽取 → SQLite 去重落库 → 按命中率排队 → 企查查 MCP 批量查号 → 号码清洗 → Excel 交付。触发词：情报速递、客户资料、企业手机号、采集流水线、跑一下采集、待查队列、客户线索。
---

# 客户情报采集流水线

## 用途

把「情报邮件」自动转成「可外呼的客户清单」。一次跑完四件事：收信抽企业、去重记账、查手机号、清洗出表。

## 何时使用

- 用户要求采集客户资料 / 查企业手机号 / 跑采集流水线
- 出现【情报速递】类邮件需要处理
- 需要查看或继续待查队列

## 前置条件

环境变量（均可选，缺省时有合理默认）：

| 变量 | 作用 | 缺省 |
|---|---|---|
| `LEAD_HOME` | 数据目录，存放 `leads.db` 与产出 Excel | 脚本所在目录 |
| `AGENTLY_CLI` | `agently-cli` 可执行文件完整路径（managed node 下不是 PATH 命令时必填） | `agently-cli` |
| `LEAD_SENDER` | 情报源发件人，填了只收该发件人的邮件，留空则不限制 | 空 |

```bash
export LEAD_HOME=<你的数据目录>
export AGENTLY_CLI=<managed node 下的 agently-cli.cmd 完整路径>
```

脚本自包含，位于 `scripts/`：**db.py / collect.py / clean.py / pipeline.py**。

## 标准流程

### 步骤 1：收单

```bash
python scripts/collect.py --all
```

`--all` 解析附件名，情报正文就在附件名里，**不带会漏掉 99% 的企业**。
产出 `待查队列_自动.json`，已按命中率从高到低排好序。

### 步骤 2：查手机号（企查查 MCP，按次计费）

从 `待查队列_自动.json` 头部开始，用 `mcp__qcc-company__get_contact_info` 逐家查。

**省额度的四条铁律：**
1. 查之前先确认库里不是 `queried` 状态——**查过的绝不再查**
2. 从队列**头部**开始（有限公司优先）
3. 队列尾部的**个体工商户直接跳过**（命中率极低，详见 `references/pitfalls.md`）
4. 半角括号转全角：`(个体工商户)` → `（个体工商户）`，否则返回"无匹配项"

每约 40 家存一个 `qcc_results_batchN.json`：

```json
{"企业名": {"mobile": ["138..."], "landline": ["0576-..."], "note": "..."}}
```

遇到 `MCP error 300008`（积分余额不足）立即停止，已查数据先存盘。

### 步骤 3：入库、清洗、出表

```bash
python scripts/db.py      # 幂等 upsert，把新结果并进库
python scripts/clean.py   # 号码四分流，出 手机号清洗结果.xlsx
```

一步到位：

```bash
python scripts/pipeline.py          # 收单 + 清洗 + 汇总
python scripts/pipeline.py --no-mail  # 跳过收信，只重算
python scripts/pipeline.py --bark     # 结束推送（需环境变量 BARK_URL）
```

## 核心约束

- **`leads.db` 是权威账本**，记录哪些企业已查过，禁止删除或重建。所有去重依赖它。
- 号码四分流：有效手机号 / 疑似代记账 / 座机 / 无效（剔除）。跨企业重复出现的号码判为代账公司号。
- 邮件正文不含电话，手机号只能走外部数据源。

## 详细参考

命中率分层数据、计费口径、CLI 与企查查的坑、数据库 Schema、环境路径 —— 全部在
**`references/pitfalls.md`**，执行前必读一次。
