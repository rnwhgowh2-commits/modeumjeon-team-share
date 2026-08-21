# -*- coding: utf-8 -*-
"""클린 최종 크롤 — 테스트 중복 스냅샷 제거 후 메이트 1회 크롤→저장 + 색상 커버리지 검증."""
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
import config  # noqa
from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option
import lemouton.sources.models  # noqa
from lemouton.templates.models import PriceTrackHistory
from lemouton.sourcing.bulk_crawl import crawl_and_save_model, SOURCE_URL_FIELD


def main():
    s = SessionLocal()
    try:
        before = s.query(PriceTrackHistory).count()
        print(f"크롤 전 PriceTrackHistory: {before}행 (기존 누적 유지)")
        mate = None
        for m in s.query(Model).all():
            if getattr(m, "url_lemouton", None) and "product_no=130" in m.url_lemouton:
                mate = m.model_code; break
    finally:
        s.close()
    print(f"대상: {mate}")
    res = crawl_and_save_model(mate)
    print("소싱처별 결과:")
    for src, r in res.items():
        if src.startswith("_"): continue
        print(f"  {src}: 크롤 {r.get('options')}개 → 저장 {r.get('saved')}개  ok={r.get('ok')} err={r.get('error')}")

    # 색상 커버리지 검증
    s = SessionLocal()
    try:
        total = s.query(PriceTrackHistory).count()
        # 우리 색상별로 저장된 행 수 (canonical_sku → Option.color_code)
        from sqlalchemy import func
        opts = {o.canonical_sku: o for o in s.query(Option).filter_by(model_code=mate).all()}
        per_color = {}
        per_source = {}
        for pth in s.query(PriceTrackHistory).all():
            o = opts.get(pth.canonical_sku)
            cc = (o.color_code if o else "?")
            per_color[cc] = per_color.get(cc, 0) + 1
            per_source[pth.source] = per_source.get(pth.source, 0) + 1
        print(f"\n총 저장 {total}행")
        print(f"소싱처별: {per_source}")
        print(f"색상별: {dict(sorted(per_color.items()))}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
