"""Edge 가 열려있어도 immutable=1 모드로 쿠키 읽기."""
import sqlite3
import datetime
from pathlib import Path

db = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템\data\profiles\musinsa_rnwhgowh\Default\Network\Cookies")
print(f"파일: {db}")
print(f"크기: {db.stat().st_size} bytes")
print(f"수정시각: {datetime.datetime.fromtimestamp(db.stat().st_mtime)}")
print()

import shutil, tempfile, os
# 1) immutable URI 시도
try:
    uri = f"file:/{str(db).replace(chr(92), '/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    print(f"[OK] immutable URI 로 직접 열림")
except Exception as e:
    print(f"[FAIL] immutable URI: {e}")
    # 2) 강제 복사 (Edge 가 락 잡고 있어도 read-share 로 시도)
    tmp = Path(tempfile.gettempdir()) / "musinsa_cookies_snap.db"
    try:
        # FILE_SHARE_READ 모드로 raw open → bytes write
        with open(db, 'rb') as f:
            data = f.read()
        with open(tmp, 'wb') as f:
            f.write(data)
        print(f"[OK] 복사: {tmp} ({tmp.stat().st_size} bytes)")
        conn = sqlite3.connect(str(tmp), timeout=2)
    except Exception as e2:
        print(f"[FAIL] raw 복사: {e2}")
        raise
cur = conn.cursor()

CHROME_EPOCH = datetime.datetime(1601, 1, 1)
NOW = datetime.datetime.utcnow()

def fmt_exp(usec):
    if not usec or usec == 0:
        return "session"
    try:
        dt = CHROME_EPOCH + datetime.timedelta(microseconds=usec)
        days = (dt - NOW).total_seconds() / 86400
        if days < 0:
            return f"EXPIRED ({-days:.0f}일전)"
        return f"{dt.strftime('%Y-%m-%d')} ({days:.0f}일남음)"
    except Exception:
        return f"?({usec})"

cur.execute("""
    SELECT name, host_key, expires_utc, length(value), is_persistent
    FROM cookies
    WHERE host_key LIKE '%musinsa%'
    ORDER BY length(value) DESC
""")
rows = cur.fetchall()
print(f"=== musinsa 쿠키: {len(rows)}개 ===")
for name, host, exp, vlen, persist in rows[:30]:
    print(f"  {name[:30]:30s} @ {host[:35]:35s} val={vlen:4}b  exp={fmt_exp(exp)}")

print()
print("=== 로그인 의심 (member.* 도메인 또는 value >= 30b) ===")
candidates = [(n,h,e,v,p) for n,h,e,v,p in rows if 'member' in h.lower() or v >= 30]
if not candidates:
    print("  ❌ 로그인 후보 0건 → 비로그인 상태")
else:
    for name, host, exp, vlen, persist in candidates:
        print(f"  {name[:30]:30s} @ {host[:40]:40s} val={vlen:4}b  exp={fmt_exp(exp)}  persist={persist}")

conn.close()
