"""대표 크롤 계정 + 프로필 디렉터리 + 실제 쿠키 진단."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lemouton.auth.sourcing_credentials import default_store as creds_store
from lemouton.auth.profile_store import default_store as profile_store, _safe_key
from lemouton.sourcing.models_v2 import SourcingAccount
from shared.db import SessionLocal


def main():
    print("=" * 60)
    print("[1] 무신사 대표 크롤 계정 (DB 의 SourcingAccount)")
    print("=" * 60)
    s = SessionLocal()
    try:
        default_acc = (s.query(SourcingAccount)
                       .filter_by(source='musinsa', is_default_for_crawl=True)
                       .first())
        if default_acc:
            print(f"  ✅ 대표 계정: account_key={default_acc.account_key}")
            print(f"     display_name: {default_acc.display_name}")
            print(f"     is_active: {default_acc.is_active}")
        else:
            print("  ❌ 대표 크롤 계정 미지정 — /accounts/sourcing 에서 ⭐ 클릭하여 지정")
            return
    finally:
        s.close()

    account_key = default_acc.account_key
    print()
    print("=" * 60)
    print(f"[2] 자격증명 ({account_key}) → actual ID")
    print("=" * 60)
    creds = creds_store().load_all().get('musinsa', {}).get(account_key, {})
    actual_id = creds.get('id', account_key)
    print(f"  account_key: {account_key}")
    print(f"  actual_id (creds 의 id): {actual_id}")
    print(f"  has_pw: {bool(creds.get('pw'))}")

    print()
    print("=" * 60)
    print("[3] ProfileStore 경로 + 쿠키 검사")
    print("=" * 60)
    ps = profile_store()
    prof_path = ps.profiles_root / f"musinsa_{_safe_key(actual_id)}"
    print(f"  프로필 경로: {prof_path}")
    print(f"  존재: {prof_path.exists()}")
    if not prof_path.exists():
        return

    # Cookies 경로 (신구 둘 다 검사)
    cookies_new = prof_path / "Default" / "Network" / "Cookies"
    cookies_old = prof_path / "Default" / "Cookies"
    cookies_db = cookies_new if cookies_new.exists() else cookies_old
    print(f"  Cookies: {cookies_db.relative_to(prof_path)} ({cookies_db.stat().st_size if cookies_db.exists() else 0} bytes)")

    if not cookies_db.exists():
        print("  ❌ Cookies 파일 없음")
        return

    print()
    print("=" * 60)
    print("[4] 실제 쿠키 도메인별 카운트 (top 15)")
    print("=" * 60)
    try:
        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True, timeout=2)
        cur = conn.cursor()
        cur.execute("SELECT host_key, COUNT(*) FROM cookies GROUP BY host_key ORDER BY COUNT(*) DESC LIMIT 15")
        for host, cnt in cur.fetchall():
            mark = ' ★' if 'musinsa' in host.lower() else ''
            print(f"  {host:50} {cnt:4}{mark}")

        print()
        print("[5] musinsa 도메인 쿠키 이름 (전체)")
        cur.execute("SELECT name, host_key FROM cookies WHERE host_key LIKE '%musinsa%' OR host_key LIKE '%mssa%' LIMIT 50")
        rows = cur.fetchall()
        if rows:
            for name, host in rows:
                print(f"  {name:30} @ {host}")
        else:
            print("  ❌ 무신사 도메인 쿠키 0개")

        print()
        print("[6] 매칭 — cookie_checker 가 보는 KEY_COOKIES")
        from lemouton.auth.cookie_checker import SOURCE_KEY_COOKIES
        expected = SOURCE_KEY_COOKIES.get('musinsa', [])
        print(f"  기대 쿠키: {expected}")
        if expected:
            placeholders = ','.join(['?'] * len(expected))
            cur.execute(f"SELECT name FROM cookies WHERE name IN ({placeholders})", expected)
            matched = [r[0] for r in cur.fetchall()]
            print(f"  매칭됨: {matched}")
        conn.close()
    except Exception as e:
        print(f"  ❌ SQLite 오류: {e}")


if __name__ == "__main__":
    main()
