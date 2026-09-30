# -*- coding: utf-8 -*-
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))
BASE = _os.environ.get("LEAD_HOME") or HERE
"""邮件自动收单：拉 agent 邮箱 -> 抽取企业名 -> 与去重库比对 -> 新企业入 pending。

用法:
    python collect.py            # 只扫描收件箱情报邮件
    python collect.py --all      # 连同附件名一起抽取（慢，但更全）
"""
import subprocess, json, os, re, sys, argparse
sys.path.insert(0, HERE)
import db

CLI = _os.environ.get('AGENTLY_CLI') or 'agently-cli'
SENDER = _os.environ.get('LEAD_SENDER', '')   # 填情报源发件人可过滤噪音，留空则不限制
TAG = '【情报速递】'


def run(args, timeout=120):
    """调 agently-cli，容错解析 JSON（输出尾部有 tip 行）"""
    p = subprocess.run([CLI] + args, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout,
                       shell=True)
    raw = (p.stdout or '').strip()
    if not raw:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw)
        return obj
    except Exception:
        return None


def list_msgs(limit=50, cursor=None):
    # 实测：--limit 超过 50 会返回空列表，上限就是 50
    limit = min(int(limit), 50)
    args = ['message', '+list', '--dir', 'inbox', '--limit', str(limit)]
    if cursor:
        args += ['--cursor', cursor]
    r = run(args)
    if not r or not r.get('ok'):
        return [], ''
    d = r['data']['data']
    cur = r['data'].get('pagination', {}).get('next_cursor', '')
    return d, cur


def read_msg(mid):
    r = run(['message', '+read', '--id', mid], timeout=180)
    return r['data'] if r and r.get('ok') else None


def names_from_subject(subj):
    """【情报速递】 XX市xx有限公司  ->  ['XX市xx有限公司']"""
    s = (subj or '').strip()
    if TAG not in s:
        return []
    s = s.split(TAG, 1)[1]
    s = re.sub(r'^[\s:：\-—]+', '', s)
    s = re.sub(r'（?第?\d+/?\d*期?）?$', '', s).strip()   # 去掉 "（1）" 之类
    s = re.sub(r'\(\d+\)$', '', s).strip()
    return [s] if s else []


def names_from_attachments(detail):
    """附件名形如 '【情报速递】 XX市xx有限公司.eml'"""
    out = []
    if not detail:
        return out
    for a in (detail.get('attachments') or []):
        fn = a.get('filename') or a.get('name') or ''
        out += names_from_subject(fn)
    return out


def is_company(n):
    """过滤人名条目（2-4 字纯中文姓名 这类）"""
    if len(n) < 5:
        return False
    if re.fullmatch(r'[\u4e00-\u9fa5]{2,4}', n):   # 纯 2-4 字中文 = 人名
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='同时解析附件名')
    args = ap.parse_args()

    seen, cursor, page = [], '', 0
    while page < 50:
        msgs, cursor = list_msgs(50, cursor)
        seen += msgs
        page += 1
        if not cursor or not msgs:
            break
    print(f'收件箱邮件: {len(seen)} 封')

    raw_names = []
    for m in seen:
        subj = m.get('subject', '')
        frm = (m.get('from') or {}).get('email', '')
        if SENDER and frm != SENDER and TAG not in subj:
            continue
        raw_names += names_from_subject(subj)
        if args.all and m.get('has_attachments'):
            raw_names += names_from_attachments(read_msg(m['message_id']))

    # 规范化 + 过滤
    names = []
    for n in raw_names:
        n = db.normalize(n)
        if n and is_company(n):
            names.append(n)
    uniq = sorted(set(names))
    print(f'抽取主体: {len(raw_names)} 条 -> 去重后 {len(uniq)} 家')

    con = db.connect()
    new, dup = [], 0
    for n in uniq:
        qn = db.query_name_of(n)
        row = con.execute(
            "SELECT status FROM companies WHERE query_name=?", (qn,)).fetchone()
        if row:
            dup += 1
        else:
            db.upsert(con, n, status='pending', source='邮箱自动收单')
            new.append(n)
    con.commit()

    keep, skip = db.pending(con)
    total = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    print(f'新增入库: {len(new)} 家 | 库中已有: {dup} 家')
    print(f'库总量: {total} | 待查建议查: {len(keep)} | 建议跳过: {len(skip)}')

    out = os.path.join(BASE, '待查队列_自动.json')
    json.dump([r[1] for r in keep] + [r[1] for r in skip],
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'待查队列已更新 -> {out}')
    if new:
        print('\n新增企业前 20 家:')
        for n in new[:20]:
            print('  +', n)
    con.close()


if __name__ == '__main__':
    main()
