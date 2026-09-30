# 参考资料：主体类型分层、计费口径与避坑清单

执行细节与经验规律。SKILL.md 只保留操作流程。

> 本文所有数字均为**量级示意**，不来自任何特定数据集。跑过自己的数据后按
> `db.py:pending()` 注释里的 SQL 回填真实命中率。

## 一、按主体类型分层的手机号可得性

不同主体类型的联系方式登记情况差异极大，这是本流水线最重要的排序依据：

| 类型 | 可得性 | 策略 |
|---|---|---|
| 有限公司 | 高 | 优先查 |
| 厂（非个体户） | 中 | 查 |
| 其他 | 中 | 查 |
| 商行/经营部/店 | 低 | 查 |
| **个体工商户** | **极低** | **跳过** |

- 待查队列按此重排，个体工商户排到最末。
- 个体户的投入产出比极低：消耗一次计费查询大概率换不回一个可用号码。
  额度紧张时应整段跳过，而不是查完再判断。
- 根本原因是登记习惯差异：有限公司有对外办公联系方式的动机，个体户没有。

## 二、企查查 MCP 计费口径

| 接口 | 计费 | 说明 |
|---|---|---|
| `get_company_by_query`（实体识别/搜索） | 免费 | 返回企业名 + 统一社会信用代码 |
| `get_contact_info`（联系方式） | **按次计费** | 本流水线的核心接口 |
| `get_shareholder_info`（股东） | 按次计费 | |
| `get_company_profile`（企业画像） | 按次计费 | |

- 余额归零后**连免费的搜索接口也会报 300008**。这是最容易误判为"授权坏了"的坑。
- 排障口诀：先调 `get_company_by_query`。能通 = 连接和授权正常，报错必然是余额；
  不能通才是连接/授权问题。
- 「积分」是服务端返回的原文用词（`MCP error 300008: 当前积分余额不足`），
  充值入口 https://agent.qcc.com/

## 三、数据质量的一般规律

- **邮件正文往往不含联系方式**：这批情报邮件的正文常就是标题本身，附件名才是信息载体。
  手机号通常只能走外部数据源，不要试图从邮件正文里挖。
- **代账公司会污染号码池**：代账机构为多家企业登记联系方式，同一个号码会跨企业重复出现。
  这类号码不能当作企业自有电话外呼。
- **无效号码要剔除**：数据源会返回带无效标记的号码，必须过滤后再统计。
- **真正查不到号的主体占比可观**：新设主体、个体户压根没登记手机号，不是流程出了问题。

## 四、避坑清单

1. **全角括号**：文件名里 `(个体工商户)`、`(地区名)` 是半角，正式名用**全角** `（）`，
   不转换就返回"无匹配项"。
2. **`--limit` 上限 50**：`agently-cli message +list --limit 100` 返回空列表且不报错，
   非常隐蔽。`collect.py` 已 clamp 到 50。
3. **CLI 输出尾部有 tip 行**：直接 `json.load` 报 "Extra data"，必须用
   `json.JSONDecoder().raw_decode()`。
4. **subprocess 调 `.cmd` 要 `shell=True`**（Windows）。
5. **重复来源**：源邮箱导出时同封邮件多次导出会加 `(1)(2)(3)` 后缀，
   `db.normalize()` 已处理，靠 `query_name` UNIQUE 兜底。
6. **情报正文在附件名里**：`collect.py` 必须带 `--all` 才会解析附件，只扫标题会漏掉大部分企业。
7. **部分附件 size=0**（超大附件只有 download_url），不影响，只需要文件名。

## 五、数据库 Schema

```sql
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    query_name    TEXT NOT NULL UNIQUE,   -- 规范化 + 全角括号，去重主键
    credit_code   TEXT,
    kind          TEXT,                   -- 有限公司/厂/商行·经营部·店/个体工商户/其他
    status        TEXT DEFAULT 'pending', -- pending | queried
    mobile_count  INTEGER DEFAULT 0,
    land_count    INTEGER DEFAULT 0,
    source        TEXT,
    queried_at    TEXT,
    note          TEXT
);
```

写入用 `ON CONFLICT(query_name) DO UPDATE`，幂等，重复导入不会破坏已有数据。

## 六、运行环境

| 用途 | 说明 |
|---|---|
| Python | 3.10+，需 `openpyxl` |
| agently-cli | 需在 PATH 中；agent 自带的 managed runtime 里通常不是全局命令，此时用 `AGENTLY_CLI` 指定完整路径 |
| 情报源发件人 | 可选，填进 `LEAD_SENDER` 可过滤噪音 |
| agent 邮箱 | 本流水线的收信入口 |

`agently-cli` 授权失效时 exit code 3，需重新 `agently-cli auth login`
（**必须后台运行**取 device OAuth URL）。
