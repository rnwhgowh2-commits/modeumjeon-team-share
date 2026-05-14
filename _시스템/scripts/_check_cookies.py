# -*- coding: utf-8 -*-
"""잠긴 Chrome Cookies SQLite 를 immutable read-only 모드로 검사."""
import sys
import io
import sqlite3
import urllib.parse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

src = Path("data/profiles/smartstore_SMARTSTORE_MAIN/Default/Network/Cookies").resolve()
uri_path = str(src).replace("\\", "/")
uri = "file:/" + urllib.parse.quote(uri_path) + "?mode=ro&immutable=1"
print(f"URI: {uri[:140]}")
try:
    con = sqlite3.connect(uri, uri=True, timeout=2)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM cookies")
    total = cur.fetchone()[0]
    print(f"total cookies: {total}")
    cur.execute(
        "SELECT host_key, name, expires_utc, is_persistent FROM cookies "
        "WHERE host_key LIKE '%naver%' OR host_key LIKE '%commerce%' OR host_key LIKE '%smartstore%' "
        "ORDER BY host_key, name"
    )
    rows = cur.fetchall()
    print(f"naver/commerce/smartstore: {len(rows)}")
    for h, n, e, p in rows:
        print(f"  {h:40} | {n:25} | persist={p} | exp={'session' if e==0 else int((e - 11644473600000000)/1000000)}")
    print()
    cur.execute(
        "SELECT host_key, name FROM cookies WHERE "
        "  (host_key LIKE '%naver.com' AND name IN ('NID_AUT','NID_SES','NID_JKL','NID_EOR','NID_PSI')) "
        "  OR (host_key LIKE '%sell.smartstore.naver.com' AND is_persistent = 1) "
        "  OR (host_key LIKE '%.commerce.naver.com' AND is_persistent = 1 AND name NOT IN ('NEONB'))"
    )
    auth = cur.fetchall()
    print(f"=== 인증 쿠키 검출: {len(auth)}개 ===")
    for h, n in auth:
        print(f"  {h} | {n}")
except Exception as e:
    print(f"ERR: {type(e).__name__}: {e}")
