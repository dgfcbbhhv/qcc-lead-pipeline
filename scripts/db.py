# -*- coding: utf-8 -*-
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))
BASE = _os.environ.get("LEAD_HOME") or HERE
"""企业去重库：记录已查企业，避免重复消耗企查查积分。
主键逻辑：优先用统一社会信用代码，没有则用规范化后的企业名。
"""
import sqlite3, os, re, json, glob

DB = _os.path.join(BASE, 'leads.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    query_name    TEXT NOT NULL UNIQUE,
    credit_code   TEXT,
    kind          TEXT,
    status        TEXT DEFAULT 'pending',
    mobile_count  INTEGER DEFAULT 0,
    land_count    INTEGER DEFAULT 0,
    source        TEXT,
    queried_at    TEXT,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_code   ON companies(credit_code);
"""

def kind_of(name):
    if '（个体工商户）' in name or '(个体工商户)' in name:
        return '个体工商户'
    if '有限公司' in name or '股份有限公司' in name:
        return '有限公司'
    if re.search(r'(商行|经营部|商店|店)$', name):
        return '商行/经营部/店'
    if re.search(r'(厂|加工厂)$', name):
        return '厂'
    return '其他'

def normalize(name):
    """邮件标题/文件名 -> 规范化企业名"""
    n = re.sub(r'\.eml$', '', name, flags=re.I)
    n = re.sub(r'^【[^】]*】\s*', '', n)
    n = re.sub(r'\(\d+\)$', '', n)
    return n.strip()

def query_name_of(name):
    """企查查要求全角括号"""
    return name.replace('(', '（').replace(')', '）')

def connect():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    return con

def upsert(con, name, kind=None, status='pending', source=None,
           credit_code=None, mobile_count=0, land_count=0, queried_at=None, note=None):
    qn = query_name_of(name)
    con.execute("""
        INSERT INTO companies (name, query_name, credit_code, kind, status,
                               mobile_count, land_count, source, queried_at, note)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(query_name) DO UPDATE SET
            credit_code  = COALESCE(excluded.credit_code, companies.credit_code),
            kind         = COALESCE(excluded.kind, companies.kind),
            status       = excluded.status,
            mobile_count = excluded.mobile_count,
            land_count   = excluded.land_count,
            queried_at   = COALESCE(excluded.queried_at, companies.queried_at),
            note         = COALESCE(excluded.note, companies.note)
    """, (name, qn, credit_code, kind or kind_of(name), status,
          mobile_count, land_count, source, queried_at, note))

def is_queried(con, name):
    qn = query_name_of(name)
    row = con.execute(
        "SELECT status FROM companies WHERE query_name=?", (qn,)).fetchone()
    return row is not None and row[0] != 'pending'

def pending(con, min_rate=0.25):
    """取待查企业，按预期命中率从高到低

    RATE 是各主体类型的相对权重（不是精确统计值），用于排序和"值不值得查"的
    分档。数值可按你自己的数据源调校：跑一批之后用
        SELECT kind, COUNT(*), SUM(mobile_count>0) FROM companies
        WHERE status='queried' GROUP BY kind;
    算出真实命中率后回填即可。保持相对大小关系即可，不必精确。
    """
    RATE = {'有限公司': 0.75, '厂': 0.55, '其他': 0.30,
            '商行/经营部/店': 0.25, '个体工商户': 0.05}
    rows = con.execute(
        "SELECT name, query_name, kind FROM companies WHERE status='pending'").fetchall()
    keep = [r for r in rows if RATE.get(r[2], 0.3) >= min_rate]
    skip = [r for r in rows if RATE.get(r[2], 0.3) < min_rate]
    keep.sort(key=lambda r: -RATE.get(r[2], 0.3))
    return keep, skip

if __name__ == '__main__':
    con = connect()
    # 1) 已查数据入库
    done = {}
    for bf in glob.glob(os.path.join(BASE, 'qcc_results_all.json')):
        done.update(json.load(open(bf, encoding='utf-8')))
    for bf in sorted(glob.glob(os.path.join(BASE, 'qcc_results_batch*.json'))):
        done.update(json.load(open(bf, encoding='utf-8')))
    import datetime
    today = datetime.date.today().isoformat()
    for name, r in done.items():
        mob = sum(1 for m in r.get('mobile', []) if re.fullmatch(r'1\d{10}', m))
        upsert(con, name, status='queried', source='已查',
               mobile_count=mob, land_count=len(r.get('landline', [])),
               queried_at=today, note=r.get('note', ''))
    # 2) 待查队列入库
    todo_path = os.path.join(BASE, '待查队列_自动.json')
    if not os.path.exists(todo_path):
        todo_path = os.path.join(BASE, '待查队列_优先级.json')
    for n in json.load(open(todo_path, encoding='utf-8')):
        upsert(con, n, status='pending', source='邮箱新增')
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    q = con.execute("SELECT COUNT(*) FROM companies WHERE status='queried'").fetchone()[0]
    keep, skip = pending(con)
    print(f'入库总数: {total}')
    print(f'已查: {q} | 待查: {total - q}')
    print(f'待查中建议查: {len(keep)} | 建议跳过(个体户): {len(skip)}')
    con.close()
