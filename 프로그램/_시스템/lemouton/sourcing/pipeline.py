"""[A] 메인 오케스트레이터.

흐름:
  1. 박스히어로 records → 옵션별 boxhero_stock 머지 (매칭 실패 시 큐 적재)
  2. 모델 마스터 순회 → 5개 소싱처 URL이 있으면 그 사이트 크롤링
  3. 크롤 결과를 매처에 통과 → 표준 SKU로 매핑 (실패 시 큐 적재)
  4. canonical_sku 별로 sources/boxhero_stock 데이터 집약
"""
from collections import defaultdict
from sqlalchemy.orm import Session

from .master import find_option_by_boxhero_sku, list_models
from .matcher import try_match_canonical
from .discovery_queue import enqueue


SOURCE_URL_FIELD = {
    "lemouton": "url_lemouton",
    "musinsa": "url_musinsa",
    "ssf": "url_ssf",
    "lotteon": "url_lotteon",
    "ss_lemouton": "url_ss_lemouton",
}


def run_pipeline(
    session: Session,
    *,
    crawlers: dict,           # {source_name: AbstractCrawler}
    boxhero_records: list[dict],
    progress_kind: str = 'crawl',   # [2026-06-03] 진행 위젯 슬롯 — 스케줄러는 'auto'
) -> dict[str, dict]:
    """전체 [A] 파이프라인 실행.
    반환: { canonical_sku: aggregated_dict }
    """
    aggregated: dict[str, dict] = defaultdict(lambda: {
        "boxhero_stock": 0,
        "boxhero_purchase_price": None,
        "sources": [],
    })

    # 1. 박스히어로 records → boxhero_stock
    for rec in boxhero_records:
        opt = find_option_by_boxhero_sku(session, rec["sku"])
        if opt is None:
            mr = try_match_canonical(
                session,
                brand=rec.get("brand") or "르무통",
                model_name_raw=rec.get("model_name") or "",
                color_text=rec.get("color_text") or "",
                size_text=rec.get("size") or "",
            )
            if mr.canonical_sku is None:
                enqueue(
                    session,
                    source="boxhero",
                    raw_text=f"{rec.get('name','')} / {rec.get('size','')}",
                    suggested_model_code=mr.suggested_model_code,
                    suggested_color_code=mr.suggested_color_code,
                    suggested_size_code=mr.suggested_size_code,
                    confidence=mr.confidence,
                )
                continue
            sku = mr.canonical_sku
        else:
            sku = opt.canonical_sku

        aggregated[sku]["boxhero_stock"] += rec.get("quantity", 0)
        aggregated[sku]["boxhero_purchase_price"] = rec.get("purchase_price")

    # 2. 5개 소싱처 크롤
    # v27 진행 widget — 사이트별 tick 콜백
    def _tick(current_label: str, *, delta: int = 0):
        try:
            from webapp.progress_state import progress_tick
            progress_tick(progress_kind, current=current_label, delta=delta)
        except Exception:
            pass

    for model in list_models(session, brand="르무통"):
        for source_name, url_field in SOURCE_URL_FIELD.items():
            url = getattr(model, url_field, None)
            if not url:
                continue
            crawler = crawlers.get(source_name)
            if crawler is None:
                continue
            _tick(f'{model.model_code} @ {source_name}')
            try:
                cr = crawler.fetch(url)
            except Exception:
                # 크롤링 실패 시 알림은 [E]에서. pipeline은 계속.
                _tick(f'{model.model_code} @ {source_name} (실패)', delta=1)
                continue
            _tick(f'{model.model_code} @ {source_name} ✓', delta=1)

            # 무신사처럼 단일 색상 페이지에서 color_text 가 비는 경우 product_name 마지막 단어로 폴백
            # (예: 무신사 product_name="메이트 블랙" → 색상="블랙")
            fallback_color = ""
            name_parts = (cr.product_name_raw or "").split()
            if len(name_parts) >= 2:
                fallback_color = name_parts[-1]

            for opt_data in cr.options:
                color_text = opt_data.get("color_text") or fallback_color
                mr = try_match_canonical(
                    session,
                    brand=model.brand,
                    model_name_raw=model.model_name_raw,
                    color_text=color_text,
                    size_text=opt_data.get("size_text", ""),
                )
                if mr.canonical_sku is None:
                    enqueue(
                        session,
                        source=source_name,
                        raw_text=f"{cr.product_name_raw} / "
                                 f"{opt_data.get('color_text')} / {opt_data.get('size_text')}",
                        suggested_model_code=mr.suggested_model_code or model.model_code,
                        suggested_color_code=mr.suggested_color_code,
                        suggested_size_code=mr.suggested_size_code,
                        confidence=mr.confidence,
                    )
                    continue

                aggregated[mr.canonical_sku]["sources"].append({
                    "name": source_name,
                    "stock": opt_data.get("stock", 0),
                    "price": opt_data.get("price", 0),
                })

    return dict(aggregated)
