"""
초기 admin 계정 생성 CLI — 팀공유 모드 부트스트랩.

사용법:
  # 신규 시스템 폴더에서 (.env 의 DATABASE_URL 활성화 후)
  python scripts/create_admin.py --email you@company.com --name "홍길동" --password "강한비번"

  # 인터랙티브 (안전 — 명령 히스토리에 비번 안 남음)
  python scripts/create_admin.py --email you@company.com --name "홍길동"
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 경로 셋업 — 이 스크립트가 _시스템/scripts/ 안에 있다고 가정
SYSTEM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SYSTEM_ROOT))
os.chdir(SYSTEM_ROOT)

# .env 로드
from dotenv import load_dotenv
load_dotenv(SYSTEM_ROOT / ".env", override=True)

# ENVIRONMENT 강제 (auth 모듈 활성화 위해)
os.environ.setdefault("ENVIRONMENT", "team-share-dev")


def main() -> int:
    parser = argparse.ArgumentParser(description="초기 admin 계정 생성")
    parser.add_argument("--email", required=True, help="admin 이메일")
    parser.add_argument("--name", required=True, help="표시 이름")
    parser.add_argument("--password", help="비밀번호 (생략 시 prompt — 안전)")
    parser.add_argument("--role", default="admin", choices=["admin", "member"], help="기본 admin")
    parser.add_argument("--force", action="store_true", help="이미 있는 이메일이면 비번만 reset")
    args = parser.parse_args()

    if not args.password:
        args.password = getpass.getpass("비밀번호: ")
        confirm = getpass.getpass("비밀번호 확인: ")
        if args.password != confirm:
            print("❌ 비밀번호 불일치", file=sys.stderr)
            return 1

    if len(args.password) < 8:
        print("❌ 비밀번호 8자 이상", file=sys.stderr)
        return 1

    # config 로딩 + DB
    from config import Config
    print(f"DB_URL = {Config.DB_URL.split('@')[0] if '@' in Config.DB_URL else Config.DB_URL}@***")
    if not Config.DB_URL.startswith(("postgresql://", "postgres://")):
        print("⚠️  WARNING: DATABASE_URL 이 PostgreSQL 가 아님 (SQLite 폴백). 의도한 거 맞아?")
        ans = input("계속할까요? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            return 1

    # 모델 등록
    import lemouton.sourcing.models  # noqa
    import lemouton.sourcing.models_pricing  # noqa
    import lemouton.pricing.settings  # noqa
    import lemouton.uploader.models  # noqa
    import lemouton.templates.models  # noqa
    import lemouton.inventory.models  # noqa
    import webapp.auth.models  # noqa

    from shared.db import SessionLocal, init_db
    init_db()  # 멱등 — users 테이블 없으면 생성

    from webapp.auth.models import User

    email = args.email.strip().lower()
    with SessionLocal() as s:
        existing = s.query(User).filter_by(email=email).first()
        if existing:
            if not args.force:
                print(f"❌ 이미 가입된 이메일: {email}")
                print(f"   비번 reset 만 원하면 --force 추가")
                return 2
            existing.set_password(args.password)
            existing.role = args.role
            existing.is_active = True
            s.commit()
            print(f"✅ 비번 reset 완료: {email} (role={args.role})")
            return 0

        u = User(email=email, name=args.name.strip(), role=args.role, is_active=True)
        u.set_password(args.password)
        s.add(u)
        s.commit()
        print(f"✅ admin 계정 생성: {email} (id={u.id}, role={args.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
