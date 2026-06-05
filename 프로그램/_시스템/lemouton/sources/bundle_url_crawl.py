# -*- coding: utf-8 -*-
"""등록된 소싱처 URL(bundle_source_urls) 전부 크롤 → SourceProduct/SourceOption 저장.

핵심 (사용자 요구 2026-06-04):
  · 한 소싱처에 '모음전 URL'(다색 통합) + '단품 URL'(색상별) 공존 → URL(listing)별로 따로 저장
    (URL 1개 = SourceProduct 1행 → 모음전/단품 가격·재고가 섞이지 않고 보존)
  · 모음전 URL = 크롤러가 옵션(색상×사이즈)을 선택하며 그 옵션의 재고·가격 캡처
  · 단품 URL = 그 색상 페이지 → 라벨('{source}_{색}')에서 색상 보강
  · 크롤 옵션을 우리 Option(canonical_sku)과 매칭 → OptionSourceLink (매트릭스 표시 연동)

저장처: SourceProduct / SourceOption (URL별 + 매트릭스가 읽는 곳).
크롤은 사용자 PC(브라우저)에서 실행. 로그인 필요한 소싱처는 세션 있어야 함.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

# 소싱처별 요청 간 최소 간격(초) — 연속 호출 차단(429) 방지. SSG 가 특히 민감.
SOURCE_DELAY = {"ssg": 3.0, "lotteon": 1.5, "ssf": 1.0, "musinsa": 1.0}
DEFAULT_DELAY = 0.8

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, ColorDict, BundleSourceUrl
from lemouton.sourcing.crawlers import build_crawlers
from lemouton.sources.service import (
    upsert_source_product, upsert_source_option,
    link_model_to_source, link_option_to_source,
)

logger = logging.getLogger(__name__)


def _ns(t: str | None) -> str:
    """공백 제거 + 소문자 (색상 비교용)."""
    return "".join((t or "").split()).lower()


def _digits(t: str | None) -> str:
    return "".join(ch for ch in (t or "") if ch.isdigit())


def _label_color(label: str | None, our_colors_ns: dict[str, str]) -> str | None:
    """라벨 '무신사_블랙' → '블랙' (단품 페이지 색상 보강). 매칭 안 되면 None."""
    if not label or "_" not in label:
        return None
    tail = label.split("_", 1)[1]
    return our_colors_ns.get(_ns(tail))


def _build_matcher(session, model_code: str):
    """우리 Option 매칭기 + 색상 목록 반환."""
    our = session.query(Option).filter_by(model_code=model_code).all()
    # (size_digits) -> list[(color_ns, color_code, canonical_sku)]
    by_size: dict[str, list[tuple]] = {}
    colors_ns: dict[str, str] = {}
    for o in our:
        cc = (o.color_code or "").strip()
        if cc:
            colors_ns[_ns(cc)] = cc
        by_size.setdefault((o.size_code or "").strip(), []).append(
            (_ns(cc), cc, o.canonical_sku)
        )
    cdicts: dict[str, list[str]] = {}
    import json as _json
    for c in session.query(ColorDict).all():
        try:
            cdicts[_ns(c.color_code)] = [_ns(v) for v in _json.loads(c.variants_json or "[]")]
        except Exception:
            pass

    def match(color_text: str | None, size_text: str | None) -> Optional[str]:
        sd = _digits(size_text)
        if not sd:
            return None
        cands = by_size.get(sd)
        if not cands:
            return None
        ct = _ns(color_text)
        if not ct:
            return None
        for color_ns, cc, sku in cands:
            if not color_ns:
                continue
            if color_ns in ct or ct in color_ns:
                return sku
            for v in cdicts.get(color_ns, []):
                if v and v in ct:
                    return sku
        return None

    return match, colors_ns


def crawl_registered_urls(
    model_code: str,
    *,
    sources: Optional[list[str]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """model_code 의 등록 URL(bundle_source_urls) 전부 크롤 → SourceProduct/Option 저장.

    Returns 요약 dict.
    """
    def log(m: str):
        if on_progress:
            try: on_progress(m)
            except Exception: pass

    crawlers = build_crawlers()
    s = SessionLocal()
    try:
        rows = (s.query(BundleSourceUrl)
                .filter_by(model_code=model_code)
                .order_by(BundleSourceUrl.source_key, BundleSourceUrl.sort_order, BundleSourceUrl.id)
                .all())
        if sources:
            rows = [r for r in rows if r.source_key in sources]
        match, our_colors_ns = _build_matcher(s, model_code)
        targets = [(r.source_key, r.url, getattr(r, "label", None)) for r in rows]
    finally:
        s.close()

    summary = {"model": model_code, "total_urls": len(targets), "per_url": [], "errors": []}
    log(f"등록 URL {len(targets)}개 크롤 시작 (model={model_code})")

    for i, (src, url, label) in enumerate(targets, 1):
        rec = {"source": src, "label": label, "url": url,
               "options": 0, "saved": 0, "matched": 0, "error": None, "skipped": None}
        # SSG dealItemView = 딜/기획전 허브(개별 상품 아님, 색상별 단품 itemView 를 링크).
        # 자체 옵션 없음 → 실패가 아니라 '단품으로 커버'로 건너뜀.
        if src == "ssg" and "dealitemview" in url.lower():
            rec["skipped"] = "딜 허브(색상별 단품으로 커버)"
            summary["per_url"].append(rec)
            log(f"[{i}/{len(targets)}] {label or src}: 딜 허브 — 단품으로 커버, 건너뜀")
            continue
        crawler = crawlers.get(src)
        if crawler is None:
            rec["error"] = "no_crawler"
            summary["per_url"].append(rec); summary["errors"].append(rec)
            log(f"[{i}/{len(targets)}] {label or src}: 크롤러 없음")
            continue
        log(f"[{i}/{len(targets)}] {label or src} 크롤 중...")
        time.sleep(SOURCE_DELAY.get(src, DEFAULT_DELAY))  # 페이싱(429 방지)
        result = None
        last_err = None
        for attempt in range(3):
            try:
                result = crawler.fetch(url)
                break
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                transient = any(t in msg for t in
                                ("429", "timeout", "timed out", "too many", "temporarily", "reset"))
                if attempt < 2 and transient:
                    wait = 6 * (attempt + 1)
                    log(f"    재시도 {attempt + 1}/2 ({wait}s 대기) — {type(e).__name__}")
                    time.sleep(wait)
                    continue
                break
        if result is None:
            rec["error"] = f"{type(last_err).__name__}: {last_err}"
            summary["per_url"].append(rec); summary["errors"].append(rec)
            log(f"    실패: {rec['error'][:80]}")
            continue

        opts = getattr(result, "options", []) or []
        rec["options"] = len(opts)
        page_color = _label_color(label, our_colors_ns)  # 단품 색상 보강

        s = SessionLocal()
        try:
            sp = upsert_source_product(
                s, site=src, url=url,
                product_name=getattr(result, "product_name_raw", None),
            )
            link_model_to_source(s, model_code=model_code, source_product_id=sp.id)
            prices = []
            pcns = _ns(page_color) if page_color else None
            color_ns_keys = [k for k in our_colors_ns.keys() if k]

            def _known_color(o):
                cns = _ns(o.get("color_text"))
                if not cns:
                    return False
                return any(k in cns or cns in k for k in color_ns_keys)

            # 단품 URL 처리 분기:
            #  · 멀티색 페이지(무신사형 — 전 색상 + 가비지 노출) → 라벨 색만 필터
            #  · 단일색 페이지(롯데온형 — 색상 표기가 상품명/사이즈라 인식 불가) → 라벨 색 강제
            single_color_page = bool(pcns) and not any(_known_color(o) for o in opts)
            for o in opts:
                raw_color = (o.get("color_text") or "").strip()
                size_text = o.get("size_text") or ""
                if pcns:
                    if single_color_page:
                        color_text = page_color   # 단일색 페이지 → 라벨 색 강제
                        # SSG/롯데온 단일색은 사이즈가 color 필드('사이즈:220mm')에 들어오고
                        # size 가 빈칸인 경우가 있음 → color 필드에서 사이즈 추출
                        if not _digits(size_text):
                            d = _digits(raw_color)
                            if d:
                                size_text = d + "mm"
                    else:
                        cns = _ns(raw_color or page_color)
                        if not (pcns in cns or cns in pcns):
                            continue              # 멀티색 페이지 → 라벨 색만 유지
                        color_text = raw_color or page_color
                else:
                    color_text = raw_color        # 모음전 → 크롤된 색 그대로
                price = o.get("price")
                stock = o.get("stock")
                so = upsert_source_option(
                    s, source_product_id=sp.id,
                    color_text=color_text, size_text=size_text,
                    current_price=price, current_stock=stock,
                )
                rec["saved"] += 1
                if isinstance(price, (int, float)) and price and (stock != 0):
                    prices.append(price)
                sku = match(color_text, size_text)
                if sku:
                    link_option_to_source(s, canonical_sku=sku, source_option_id=so.id)
                    rec["matched"] += 1
            # 상품 단위 요약 (매트릭스 last_price 용)
            sp.last_status = "ok"
            from datetime import datetime, timezone
            sp.last_fetched_at = datetime.now(timezone.utc)
            if prices:
                sp.last_price = min(prices)
            s.commit()
        except Exception as e:
            s.rollback()
            rec["error"] = f"save_failed: {type(e).__name__}: {e}"
            summary["errors"].append(rec)
        finally:
            s.close()

        log(f"    → 옵션 {rec['options']} / 저장 {rec['saved']} / 매칭 {rec['matched']}"
            + (f" / ERR {rec['error'][:60]}" if rec['error'] else ""))
        summary["per_url"].append(rec)

    summary["urls_ok"] = sum(1 for r in summary["per_url"] if not r["error"] and not r.get("skipped"))
    summary["urls_skipped"] = sum(1 for r in summary["per_url"] if r.get("skipped"))
    summary["urls_failed"] = sum(1 for r in summary["per_url"] if r["error"])
    summary["total_saved"] = sum(r["saved"] for r in summary["per_url"])
    summary["total_matched"] = sum(r["matched"] for r in summary["per_url"])
    return summary
