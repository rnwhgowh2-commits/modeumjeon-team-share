# -*- coding: utf-8 -*-
"""전체 모음전 × 소싱처 크롤 → 가격/재고 저장 (배선 완성).

`webapp.routes.api.test_crawl_single` 의 검증된 단일 크롤 저장 로직
(`_save_crawl_to_track`)을 전체 모음전 × 전체 소싱처로 확장한다.

저장 대상: PriceTrackHistory (canonical_sku, source, price, stock) — append 기록.
크롤러 dispatch: test_crawl_single 과 동일 (lemouton/musinsa/ssf/lotteon).

사용:
    from lemouton.sourcing.bulk_crawl import crawl_and_save_all
    summary = crawl_and_save_all(limit=3, on_progress=print)
"""
from __future__ import annotations

import json as _json
import logging
from typing import Callable, Optional

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, ColorDict
# FK 대상 테이블(source_options 등) 메타데이터 등록 — 없으면 PriceTrackHistory 저장 시
# NoReferencedTableError. app.py 도 동일 모듈을 등록한다.
import lemouton.sources.models  # noqa: F401
from lemouton.templates.models import PriceTrackHistory

logger = logging.getLogger(__name__)

# Model.url_* 컬럼 ↔ 소싱처 키 (test_crawl_single 지원 4종)
SOURCE_URL_FIELD = {
    "lemouton": "url_lemouton",
    "musinsa": "url_musinsa",
    "ssf": "url_ssf",
    "lotteon": "url_lotteon",
}


def make_crawler(source: str):
    """소싱처별 크롤러 인스턴스 (test_crawl_single 과 동일)."""
    if source == "lemouton":
        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
        return LemoutonCrawler(prefer_playwright=True)
    if source == "musinsa":
        from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
        return MusinsaCrawler()
    if source == "ssf":
        from lemouton.sourcing.crawlers.ssf import SsfCrawler
        return SsfCrawler()
    if source == "lotteon":
        from lemouton.sourcing.crawlers.lotteon import LotteCrawler
        return LotteCrawler()
    return None


def save_crawl_to_track(s, model_code: str, result) -> int:
    """crawl 결과 → PriceTrackHistory 저장. 색상/사이즈 매칭. 저장 건수 반환.

    (webapp.routes.api._save_crawl_to_track 와 동일 로직 — 웹 의존 제거 위해 복제)
    """
    our_options = s.query(Option).filter_by(model_code=model_code).all()
    if not our_options:
        return 0

    cdicts: dict = {}
    for c in s.query(ColorDict).all():
        try:
            variants = _json.loads(c.variants_json or "[]")
            cdicts[c.color_code.lower()] = [v.lower() for v in variants]
        except Exception:
            pass

    saved = 0
    for raw in (result.options or []):
        c_text = (raw.get("color_text") or "").strip().lower()
        s_text = (raw.get("size_text") or "").strip()
        s_norm = "".join(ch for ch in s_text if ch.isdigit())
        if not s_norm:
            continue

        # 공백 무시 비교 — '올리브그린'(우리) vs '올리브 그린'(무신사) 같은 띄어쓰기 차이 흡수
        c_text_ns = c_text.replace(" ", "")
        matched = None
        for our in our_options:
            if (our.size_code or "").strip() != s_norm:
                continue
            our_color = (our.color_code or "").strip().lower()
            if not our_color:
                continue
            our_color_ns = our_color.replace(" ", "")
            if our_color_ns in c_text_ns or c_text_ns in our_color_ns:
                matched = our
                break
            for variant in cdicts.get(our_color, []):
                v = (variant or "").replace(" ", "")
                if v and v in c_text_ns:
                    matched = our
                    break
            if matched:
                break

        if matched:
            s.add(PriceTrackHistory(
                canonical_sku=matched.canonical_sku,
                source=result.source,
                price=raw.get("price"),
                stock=raw.get("stock"),
            ))
            saved += 1

    if saved:
        s.commit()
    return saved


def crawl_and_save_model(model_code: str, sources: Optional[list[str]] = None) -> dict:
    """모음전 1개 — 보유한 소싱처 URL 전부 크롤 → 저장.

    Returns: {source: {ok, saved, options, error}} 형태의 per-source 결과.
    """
    sources = sources or list(SOURCE_URL_FIELD.keys())
    out: dict[str, dict] = {}
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=model_code).first()
        if not m:
            return {"_error": "model_not_found"}
        for src in sources:
            url = getattr(m, SOURCE_URL_FIELD[src], None)
            if not url:
                continue
            # [2026-06-12] SSG 딜(dealItemView) = 색상별 단품 URL 로 커버되는 허브.
            #   uitemObj 없어 "[SSG] 옵션 추출 실패"로 잡힘(거짓 실패) → 크롤 대상에서 제외.
            #   (전 크롤 경로 공통 정책 — service / bundle_url_crawl 과 동일.)
            if src == 'ssg' and 'dealitemview' in url.lower():
                continue
            crawler = make_crawler(src)
            if crawler is None:
                out[src] = {"ok": False, "saved": 0, "options": 0, "error": "no_crawler"}
                continue
            try:
                result = crawler.fetch(url)
            except Exception as e:
                out[src] = {"ok": False, "saved": 0, "options": 0,
                            "error": f"{type(e).__name__}: {e}"}
                continue
            opts = len(getattr(result, "options", []) or [])
            try:
                saved = save_crawl_to_track(s, model_code, result)
            except Exception as e:
                s.rollback()
                out[src] = {"ok": False, "saved": 0, "options": opts,
                            "error": f"save_failed: {type(e).__name__}: {e}"}
                continue
            out[src] = {"ok": True, "saved": saved, "options": opts, "error": None}
    finally:
        s.close()
    return out


def crawl_and_save_all(
    *,
    limit: Optional[int] = None,
    sources: Optional[list[str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """전체 모음전(또는 limit개) × 소싱처 크롤 → 저장.

    Returns 요약: {models, models_done, total_saved, per_source_saved, failures}
    """
    def log(msg: str):
        if on_progress:
            try: on_progress(msg)
            except Exception: pass

    s = SessionLocal()
    try:
        # 크롤 대상 = 소싱처 URL 이 있고 + 우리 Option(색상/사이즈)이 있는 모음전.
        # (단독 SKU 등 Option 0 개 모델은 매칭·저장 불가 → 크롤 낭비라 제외)
        url_cols = list(SOURCE_URL_FIELD.values())
        opt_codes = {r[0] for r in s.query(Option.model_code).distinct().all()}
        codes = [
            m.model_code
            for m in s.query(Model).order_by(Model.model_code).all()
            if any(getattr(m, col, None) for col in url_cols)
            and m.model_code in opt_codes
        ]
    finally:
        s.close()
    if limit:
        codes = codes[:limit]

    summary = {
        "models": len(codes),
        "models_done": 0,
        "total_saved": 0,
        "per_source_saved": {k: 0 for k in SOURCE_URL_FIELD},
        "failures": [],
    }
    for i, code in enumerate(codes, 1):
        log(f"[{i}/{len(codes)}] {code} 크롤 중...")
        res = crawl_and_save_model(code, sources=sources)
        for src, r in res.items():
            if src.startswith("_"):
                continue
            if r.get("ok"):
                summary["total_saved"] += r["saved"]
                summary["per_source_saved"][src] = summary["per_source_saved"].get(src, 0) + r["saved"]
            else:
                summary["failures"].append({"model": code, "source": src, "error": r.get("error")})
        summary["models_done"] += 1
        done_line = ", ".join(
            f"{src}={r.get('saved') if r.get('ok') else 'X'}"
            for src, r in res.items() if not src.startswith("_")
        )
        log(f"    → {done_line or '(URL 없음)'}")
    return summary
