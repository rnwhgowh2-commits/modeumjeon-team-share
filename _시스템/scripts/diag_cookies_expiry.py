"""쿠키 만료 시각 + 로그인 관련 키 진단."""
import sqlite3
import datetime
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else r'C:\Temp\musinsa_cookies.db'

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Chrome epoch: 1601-01-01
CHROME_EPOCH = datetime.datetime(1601, 1, 1)
NOW = datetime.datetime.utcnow()

def fmt_exp(usec):
    if not usec or usec == 0:
        return 'session'
    try:
        dt = CHROME_EPOCH + datetime.timedelta(microseconds=usec)
        days_left = (dt - NOW).total_seconds() / 86400
        if days_left < 0:
            return f'EXPIRED ({-days_left:.0f}일 전)'
        return f'{dt.strftime("%Y-%m-%d")} ({days_left:.0f}일 남음)'
    except Exception:
        return f'?({usec})'


cur.execute("""
    SELECT name, host_key, expires_utc, length(value), is_persistent
    FROM cookies
    WHERE host_key LIKE '%musinsa%'
    ORDER BY expires_utc DESC
""")
rows = cur.fetchall()
print(f"총 musinsa 쿠키: {len(rows)}개")
print()
print(f'{"이름":35} {"도메인":35} {"만료":30} {"value len":>10}')
print('-' * 110)
for name, host, exp, vlen, persist in rows[:40]:
    print(f'{name[:34]:35} {host[:34]:35} {fmt_exp(exp):30} {vlen:>10}')

# 로그인 의심 쿠키 (긴 value, member 도메인, JSESSIONID 패턴 등)
print()
print("=== 로그인 후보 쿠키 (member.* 도메인 또는 value 길이 ≥ 30) ===")
for name, host, exp, vlen, persist in rows:
    if 'member' in host.lower() or vlen >= 30:
        print(f'  {name:30} @ {host:30} exp={fmt_exp(exp)} val={vlen}b persist={persist}')

conn.close()
