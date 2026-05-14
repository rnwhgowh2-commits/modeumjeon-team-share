"""송장자동화 settings.json → 르무통 sourcing_credentials.json import.

설계:
  · 송장자동화 폴더는 자동 검색 (또는 인자로 지정)
  · 매핑: ssfshop → ssf, musinsa → musinsa, lotteimall → lotteon
  · 각 사이트의 모든 계정을 import (owner 를 account_key 로 사용)
  · 르무통 폴더는 자기완결 — import 후 송장자동화 폴더 의존 X
  · 비밀번호는 코드가 파일 → 파일로만 옮김 (값은 화면 출력 X, 마스킹만)
  · 기존 르무통 자격증명이 있으면 사용자에게 확인 후 덮어쓰기

사용:
  python scripts/import_from_invoice_sender.py
  python scripts/import_from_invoice_sender.py --source-path "C:/path/to/송장자동화/data/settings.json"
  python scripts/import_from_invoice_sender.py --dry-run     # 미리보기만 (실제 저장 X)
  python scripts/import_from_invoice_sender.py --first-only  # 사이트당 첫 계정만
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lemouton.auth.sourcing_credentials import SourcingCredentialsStore  # noqa: E402

# 송장자동화 사이트 키 → 르무통 소싱처 키 (전체 매핑)
SITE_MAP = {
    "musinsa": "musinsa",
    "ssfshop": "ssf",
    "lotteimall": "lotteimall",
    "lotteon": "lotteon",
    "ssg": "ssg",
    "abc": "abc",
    "abcGs": "abcGs",
    "grandstage": "grandstage",
    "gs": "gs",
    "folder": "folder",
    "nike": "nike",
    "oliveyoung": "oliveyoung",
    "gmarket": "gmarket",
    "fashionplus": "fashionplus",
}

# 후보 settings.json 경로 (사용자 머신에서 자동 검색)
CANDIDATE_PATHS = [
    Path("C:/Users/seung/OneDrive/바탕 화면/자동화 프로그램 개발/온라인셀링/송장자동화/data/settings.json"),
    Path("C:/Users/seung/OneDrive/바탕 화면/[안전폴더]송장자동화_backup_20260403_220835_full/송장자동화/기타/data/settings.json"),
]


def find_source() -> Path | None:
    """가장 최근 수정된 settings.json 자동 선택 (실 운용 본체 우선)."""
    candidates = [p for p in CANDIDATE_PATHS if p.exists()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def mask_id(value: str) -> str:
    if not value:
        return "<empty>"
    if "@" in value:
        local, _, domain = value.partition("@")
        if len(local) > 3:
            return f"{local[:2]}***@{domain}"
        return f"{local[0]}***@{domain}"
    if len(value) <= 4:
        return value[0] + "***"
    return f"{value[:2]}***{value[-2:]}"


def main():
    parser = argparse.ArgumentParser(description="송장자동화 자격증명 → 르무통 import")
    parser.add_argument("--source-path", type=Path, help="송장자동화 settings.json 경로")
    parser.add_argument("--dry-run", action="store_true", help="미리보기만 (저장 X)")
    parser.add_argument("--first-only", action="store_true", help="사이트당 첫 계정만")
    parser.add_argument("--target", type=Path,
                        default=ROOT / "data" / "sourcing_credentials.json",
                        help="저장 대상 (기본: 르무통 data/sourcing_credentials.json)")
    args = parser.parse_args()

    src = args.source_path or find_source()
    if not src or not src.exists():
        print("❌ 송장자동화 settings.json 못 찾음")
        print("   --source-path 인자로 직접 지정하세요")
        return 1

    print(f"📂 source: {src}")
    print(f"📂 target: {args.target}")
    print(f"   mode: {'DRY RUN (저장 안 함)' if args.dry_run else '실제 저장'}")
    print(f"   import 범위: {'사이트당 첫 계정만' if args.first_only else '모든 계정'}")
    print()

    try:
        with src.open(encoding="utf-8") as f:
            settings = json.load(f)
    except Exception as e:
        print(f"❌ settings.json 읽기 실패: {e}")
        return 1

    accounts = settings.get("accounts", {})
    if not accounts:
        print("⚠️  settings.json 에 accounts 가 비어있음")
        return 1

    # 매핑 + 추출
    plan: list[dict] = []
    for src_site, lemouton_source in SITE_MAP.items():
        site_accounts = accounts.get(src_site, [])
        if not site_accounts:
            continue
        if args.first_only:
            site_accounts = site_accounts[:1]
        for i, acc in enumerate(site_accounts):
            id_value = (acc.get("id") or "").strip()
            pw_value = acc.get("pw") or ""
            owner = (acc.get("owner") or "").strip() or f"acc_{i+1}"
            login_method = acc.get("login_method", "direct")
            if not id_value or not pw_value:
                continue
            plan.append({
                "lemouton_source": lemouton_source,
                "src_site": src_site,
                "account_key": owner if i == 0 else f"{owner}_{i+1}",
                "id": id_value,
                "pw": pw_value,
                "login_method": login_method,
            })

    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  매핑 결과 (총 {len(plan)} 계정)")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    for item in plan:
        print(f"  {item['src_site']:12} → {item['lemouton_source']:10} | "
              f"{item['account_key']:15} | {mask_id(item['id'])} | {item['login_method']}")
    print()

    if args.dry_run:
        print("⏭ DRY RUN — 실제 저장 안 함")
        return 0

    if not plan:
        print("⚠️  매핑할 계정 없음")
        return 1

    # 기존 르무통 자격증명 백업 안내
    if args.target.exists():
        print("⚠️  기존 sourcing_credentials.json 존재 — 동일 키 덮어쓰기, 다른 키 보존")
        print()

    store = SourcingCredentialsStore(args.target)
    success = 0
    for item in plan:
        try:
            result = store.upsert(
                source=item["lemouton_source"],
                account_key=item["account_key"],
                id_value=item["id"],
                pw_value=item["pw"],
                login_method=item["login_method"],
            )
            print(f"  ✅ {item['lemouton_source']:10} / {item['account_key']:15} = {result['id_masked']}")
            success += 1
        except ValueError as e:
            print(f"  ❌ {item['lemouton_source']} / {item['account_key']}: {e}")

    print()
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  완료: {success}/{len(plan)} 계정 → {args.target}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()
    print("다음 단계:")
    print("  1) http://127.0.0.1:5052/accounts/sourcing → '회원 추가' 버튼")
    print("  2) 등록된 자격증명 확인 (마스킹된 ID 표시)")
    print("  3) (Phase 2-C 활성화 후) '자동 로그인' 버튼 → Playwright 창 → storage_state 저장")

    return 0


if __name__ == "__main__":
    sys.exit(main())
