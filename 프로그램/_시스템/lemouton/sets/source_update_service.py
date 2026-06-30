"""[구성 레이어] 소싱처 업데이트 — 연동 옵션의 모델 단위로 등록 소싱처 URL 재크롤.

각 SetProduct.model_code(중복 제거)마다 crawl_bundle_registered_urls 를 호출.
HTTP 소싱처(ssf·ssg·ss_lemouton·smartstore)는 서버 즉시 크롤,
브라우저 소싱처(무신사·롯데온)는 no_crawler 로 집계 → need_extension 안내.
재크롤은 하드리셋+finalize 포함(기존 '전체 크롤'과 동일 경로) — 매트릭스 가격/재고가
이 한 번으로 갱신된다(폴백 금지 정책 유지).
"""
from __future__ import annotations


def update_set_sources(session, *, set_id, crawlers=None, crawl_fn=None):
    """구성에 연동된 옵션들의 소싱처 URL을 모델 단위로 재크롤한다.

    crawl_fn: DI용. 기본은 crawl_bundle_registered_urls. (테스트는 페이크 주입.)
    Returns: {ok, models:[{model_code,total,ok,error,no_crawler,per_source}],
              totals:{total,ok,error,no_crawler}, per_source:{key:{ok,error,no_crawler}},
              need_extension:bool}
    """
    from lemouton.sets.models import ProductSet
    if crawl_fn is None:
        from lemouton.sources.service import crawl_bundle_registered_urls
        crawl_fn = crawl_bundle_registered_urls
    if crawlers is None:
        from lemouton.sourcing.crawlers import build_crawlers
        crawlers = build_crawlers()

    ps = session.get(ProductSet, set_id)
    if ps is None:
        return {"ok": False, "error": "구성을 찾을 수 없어요."}

    # 다품: 각 SetProduct 의 model_code 합집합(정렬·중복 제거)
    seen = set()
    model_codes = []
    for sp in sorted(ps.products, key=lambda p: ((p.sort_order or 0), p.id)):
        mc = sp.model_code
        if mc and mc not in seen:
            seen.add(mc)
            model_codes.append(mc)

    totals = {"total": 0, "ok": 0, "error": 0, "no_crawler": 0}
    per_source: dict[str, dict] = {}
    models = []
    for mc in model_codes:
        r = crawl_fn(session, model_code=mc, crawlers=crawlers) or {}
        row = {"model_code": mc}
        for k in ("total", "ok", "error", "no_crawler"):
            v = int(r.get(k) or 0)
            row[k] = v
            totals[k] += v
        ps_map = r.get("per_source") or {}
        row["per_source"] = ps_map
        for sk, d in ps_map.items():
            agg = per_source.setdefault(sk, {"ok": 0, "error": 0, "no_crawler": 0})
            for kk in ("ok", "error", "no_crawler"):
                agg[kk] += int((d or {}).get(kk) or 0)
        models.append(row)

    return {
        "ok": True,
        "models": models,
        "totals": totals,
        "per_source": per_source,
        "need_extension": totals["no_crawler"] > 0,
    }
