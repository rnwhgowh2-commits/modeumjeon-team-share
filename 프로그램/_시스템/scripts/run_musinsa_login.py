"""대표 크롤 계정으로 무신사 로그인 마법사 직접 실행.

Flask 거치지 않고 직접 MusinsaScraper.ensure_logged_in 호출.
- 헤드 띄움 (사용자가 reCAPTCHA 등 풀 수 있음)
- 로그인 성공 시 musinsa_<id> 프로필에 쿠키 영구 저장
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lemouton.auth.sourcing_credentials import default_store as creds_store
from lemouton.auth.scrapers.musinsa import MusinsaScraper
from lemouton.sourcing.models_v2 import SourcingAccount
from shared.db import SessionLocal


def main():
    print("=" * 60)
    print("[1] 대표 크롤 계정 조회")
    print("=" * 60)
    s = SessionLocal()
    try:
        default_acc = (s.query(SourcingAccount)
                       .filter_by(source='musinsa', is_default_for_crawl=True)
                       .first())
        if not default_acc:
            print("  ❌ 대표 크롤 계정 없음")
            return 1
        account_key = default_acc.account_key
        print(f"  ✅ account_key={account_key}")
    finally:
        s.close()

    creds = creds_store().load_all().get('musinsa', {}).get(account_key, {})
    actual_id = creds.get('id', account_key)
    pw = creds.get('pw', '')
    if not pw:
        print(f"  ❌ {account_key} 비밀번호 없음")
        return 2

    print(f"  actual_id={actual_id}  has_pw={bool(pw)}")

    print()
    print("=" * 60)
    print("[2] MusinsaScraper.ensure_logged_in 실행")
    print("=" * 60)

    def log(level, msg):
        print(f"  [{level.upper():5s}] {msg}")

    sc = MusinsaScraper(log_callback=log)
    try:
        ok = sc.ensure_logged_in(
            account_id=actual_id,
            account_pw=pw,
            login_method="direct",
            max_retry=2,
            skip_if_logged_in=True,
        )
        print()
        print("=" * 60)
        if ok:
            print(f"  ✅ 로그인 성공 — 쿠키가 musinsa_{actual_id} 프로필에 저장됨")
            return 0
        else:
            print(f"  ❌ 로그인 실패")
            return 3
    finally:
        try:
            sc.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
