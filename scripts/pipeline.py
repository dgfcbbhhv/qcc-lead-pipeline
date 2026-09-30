# -*- coding: utf-8 -*-
import os as _os
HERE = _os.path.dirname(_os.path.abspath(__file__))
BASE = _os.environ.get("LEAD_HOME") or HERE
"""一键流水线：收单 -> 待查队列 -> 清洗 -> 出表 -> （可选）Bark 推送

用法:
    python pipeline.py             # 全流程
    python pipeline.py --no-mail   # 跳过收邮件，只用库里现有数据重算
    python pipeline.py --bark      # 结束时推送结果摘要（需环境变量 BARK_URL）
"""
import os, sys, json, subprocess, argparse, urllib.request, urllib.parse, datetime

PY = sys.executable


def step(cmd, desc):
    print(f'\n=== {desc} ===')
    args = cmd if isinstance(cmd, list) else cmd.split()
    p = subprocess.run([PY, _os.path.join(HERE, args[0])] + args[1:], cwd=BASE,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(p.stdout.strip())
    if p.returncode != 0:
        print('[失败]', p.stderr.strip()[:500])
    return p.returncode


def bark(title, body):
    url = os.environ.get('BARK_URL')
    if not url:
        print('[跳过推送] 未设置 BARK_URL')
        return
    try:
        req = urllib.request.urlopen(
            f"{url.rstrip('/')}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}",
            timeout=15)
        print('[推送完成]', req.status)
    except Exception as e:
        print('[推送失败]', e)


def summary():
    import db
    con = db.connect()
    total = con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    q = con.execute("SELECT COUNT(*) FROM companies WHERE status='queried'").fetchone()[0]
    hit = con.execute(
        "SELECT COUNT(*) FROM companies WHERE status='queried' AND mobile_count>0").fetchone()[0]
    keep, skip = db.pending(con)
    con.close()
    return total, q, hit, len(keep), len(skip)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--no-mail', action='store_true')
    ap.add_argument('--bark', action='store_true')
    a = ap.parse_args()

    if not a.no_mail:
        step(['collect.py', '--all'], '1/3 邮箱自动收单')
    step('clean.py', '2/3 号码清洗并出表')

    t, q, hit, keep, skip = summary()
    print('\n=== 3/3 汇总 ===')
    print(f'库总量     : {t}')
    print(f'已查询     : {q}')
    print(f'有手机号   : {hit}  ({hit / q * 100:.0f}%)' if q else '有手机号   : 0')
    print(f'待查建议查 : {keep} | 建议跳过(个体户): {skip}')

    if a.bark:
        bark('客户资料采集完成',
             f'总量{t} 已查{q} 命中{hit} 待查{keep}')

    print('\n产出文件:')
    for f in ['手机号清洗结果.xlsx', '待查队列_自动.json']:
        p = os.path.join(BASE, f)
        if os.path.exists(p):
            print(f'  - {p}  ({datetime.datetime.fromtimestamp(os.path.getmtime(p)):%Y-%m-%d %H:%M})')


if __name__ == '__main__':
    main()
