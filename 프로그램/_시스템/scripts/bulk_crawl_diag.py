# -*- coding: utf-8 -*-
"""저장 매칭 진단 — 메이트(옵션 풍부) 1개 크롤→저장 + 단독 모델 0건 원인 분석."""
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
from lemouton.sourcing.models import Model, Option
from lemouton.templates.models import PriceTrackHistory
from lemouton.sourcing.bulk_crawl import crawl_and_save_model


def opt_summary(code):
    s = SessionLocal()
    try:
        opts = s.query(Option).filter_by(model_code=code).all()
        sample = [(o.color_code, o.size_code) for o in opts[:6]]
        return len(opts), sample
    finally:
        s.close()


def find_mate():
    s = SessionLocal()
    try:
        for m in s.query(Model).all():
            u = getattr(m, "url_lemouton", None)
            if u and "product_no=130" in u:
                return m.model_code
        return None
    finally:
        s.close()


def main():
    mate = find_mate()
    print(f"메이트 모음전: {mate}")
    if mate:
        n, sample = opt_summary(mate)
        print(f"  우리 Option {n}개, 샘플(color_code/size_code): {sample}")
        s = SessionLocal()
        before = s.query(PriceTrackHistory).count(); s.close()
        res = crawl_and_save_model(mate)
        s = SessionLocal()
        after = s.query(PriceTrackHistory).count(); s.close()
        print(f"  크롤·저장 결과: {res}")
        print(f"  PriceTrackHistory 증가: {after - before} (현재 {after})")

    # 단독 모델 하나 진단
    s = SessionLocal()
    try:
        dan = s.query(Model).filter(Model.model_code.like("단독_%")).first()
        code = dan.model_code if dan else None
    finally:
        s.close()
    if code:
        n, sample = opt_summary(code)
        print(f"\n단독 모델 {code}: 우리 Option {n}개, 샘플: {sample}")


if __name__ == "__main__":
    main()
