# -*- coding: utf-8 -*-
"""전체(또는 N개) 모음전 크롤 → 가격/재고 저장 실행 + 검증.

실행:
  python -m scripts.bulk_crawl_run 3      # 3개만 (테스트)
  python -m scripts.bulk_crawl_run        # 전체
"""
from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: F401
from shared.db import SessionLocal
from lemouton.templates.models import PriceTrackHistory
from lemouton.sourcing.bulk_crawl import crawl_and_save_all


def _count_track() -> int:
    s = SessionLocal()
    try:
        return s.query(PriceTrackHistory).count()
    finally:
        s.close()


def main() -> int:
    limit = None
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    before = _count_track()
    print("=" * 64)
    print(f" 전체 크롤→저장 {'(테스트 ' + str(limit) + '개)' if limit else '(전체)'}")
    print(f" 시작 전 PriceTrackHistory 행 수: {before}")
    print("=" * 64)

    summary = crawl_and_save_all(limit=limit, on_progress=print)

    after = _count_track()
    print("\n" + "=" * 64)
    print(" 요약")
    print(f"  모음전 처리: {summary['models_done']}/{summary['models']}")
    print(f"  저장된 가격/재고 행: {summary['total_saved']}  "
          f"(DB 검증: {after - before}개 증가, 현재 {after})")
    print(f"  소싱처별 저장: {summary['per_source_saved']}")
    fails = summary["failures"]
    print(f"  실패/스킵: {len(fails)}건")
    for f in fails[:20]:
        print(f"    - {f['model']} / {f['source']}: {f['error']}")
    if len(fails) > 20:
        print(f"    ... 외 {len(fails) - 20}건")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
