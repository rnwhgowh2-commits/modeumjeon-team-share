"""계수 드릴다운 트리 — 소싱처/브랜드/모음전 3기준 파인더 데이터.

각 노드에 {weight, direct} 를 백엔드가 계산(정본). 프론트는 렌더·네비게이션만.
계수 규칙(CrawlWeightRule) + resolve 의미(most-specific-wins: url>model>brand>source>기본1)를 그대로 반영.

- src 기준(5열): 소싱처 → 브랜드 → 모음전 → 옵션 → URL
- brd 기준(4열): 브랜드 → 모음전 → 옵션 → URL(소싱처별)
- mdl 기준(3열): 모음전 → 옵션 → URL(소싱처별)

옵션은 계수 범위(scope)가 아니라 '찾아가는 길'(editable=False). 계수는 결국 URL에 걸림.
"""
from __future__ import annotations

DEFAULT_WEIGHT = 1


def build_weight_tree(session) -> dict:
    from lemouton.sources.models import SourceProduct
    from lemouton.sources.service import normalize_url
    from lemouton.sources.crawl_schedule import (
        list_weight_rules, get_source_concurrency_map,
        default_source_concurrency, source_is_windowless)
    from lemouton.sourcing.models import BundleSourceUrl, Model, Option
    from lemouton.sourcing.source_registry import get_labels

    rules = list_weight_rules(session)  # {source:{}, brand:{}, model:{}, url:{}}
    conc_map = get_source_concurrency_map(session)   # {source_key: 저장된 동시상한}
    try:
        labels = get_labels() or {}
    except Exception:
        labels = {}

    models = {m.model_code: m for m in session.query(Model).all()}
    opts_by_model: dict[str, list] = {}
    for o in (session.query(Option)
              .order_by(Option.sort_order, Option.color_code, Option.size_code).all()):
        opts_by_model.setdefault(o.model_code, []).append(o)

    # 등록 URL(BundleSourceUrl) 정규화 → model_codes
    url_models: dict[str, set] = {}
    for b in session.query(BundleSourceUrl).all():
        url_models.setdefault(normalize_url(b.url), set()).add(b.model_code)

    # 크롤 URL(SourceProduct) — 실제 계수가 걸리는 곳
    sps = (session.query(SourceProduct)
           .filter(SourceProduct.deleted_at.is_(None)).all())
    # (model_code, site) → url 레코드
    url_by_model_site: dict[tuple, list] = {}
    for sp in sps:
        norm = normalize_url(sp.url)
        for mc in sorted(url_models.get(norm, set())):
            url_by_model_site.setdefault((mc, sp.site), []).append(
                {"id": sp.id, "norm": norm, "url": sp.url, "site": sp.site,
                 "model_codes": sorted(url_models.get(norm, set()))})

    def brand_of(mc):
        m = models.get(mc)
        return ((m.brand or "").strip() if m else "") or None

    # ── 계수 계산 헬퍼 (rules 기준) ─────────────────────────────
    def src_w(site):
        d = site in rules["source"]
        return (rules["source"][site] if d else DEFAULT_WEIGHT), d

    def brand_w(brand, parent_w):
        d = brand in rules["brand"]
        return (rules["brand"][brand] if d else parent_w), d

    def model_w(mc, parent_w):
        d = mc in rules["model"]
        return (rules["model"][mc] if d else parent_w), d

    def url_resolved(rec):
        """URL 실제 계수: url>model(max)>brand(max)>source>기본. (resolve_crawl_weight 동일)"""
        if rec["norm"] in rules["url"]:
            return rules["url"][rec["norm"]], True
        mcs = rec["model_codes"]
        mrules = [rules["model"][c] for c in mcs if c in rules["model"]]
        if mrules:
            return max(mrules), False
        brands = {brand_of(c) for c in mcs}
        brules = [rules["brand"][b] for b in brands if b and b in rules["brand"]]
        if brules:
            return max(brules), False
        if rec["site"] in rules["source"]:
            return rules["source"][rec["site"]], False
        return DEFAULT_WEIGHT, False

    def opt_nodes(mc, inherited_w):
        out = []
        for o in opts_by_model.get(mc, []):
            out.append({
                "scope_type": "option", "scope_key": o.canonical_sku,
                "label": (o.color_display or o.color_code or ""),
                "size": (o.size_display or o.size_code or ""),
                "weight": inherited_w, "direct": False, "editable": False,
                "children": [],  # 옵션→URL은 모델 URL로 채운다(mode별)
            })
        return out

    def url_nodes_for(mc, site=None):
        """모델의 URL 노드들. site 지정 시 그 소싱처만, 아니면 소싱처별 전부."""
        recs = []
        if site is not None:
            recs = url_by_model_site.get((mc, site), [])
        else:
            for (m2, s2), lst in url_by_model_site.items():
                if m2 == mc:
                    recs.extend(lst)
        nodes = []
        for rec in recs:
            w, d = url_resolved(rec)
            nodes.append({
                "scope_type": "url", "scope_key": rec["norm"],
                "label": _short_url(rec["url"]), "site": rec["site"],
                "site_label": labels.get(rec["site"], rec["site"]),
                "weight": w, "direct": d, "editable": True,
                "source_product_id": rec["id"], "children": [],
            })
        return nodes

    def src_label(site):
        return labels.get(site, site)

    # ── src 기준(5열): 소싱처 → 브랜드 → 모음전 → 옵션 → URL ──
    src_tree = []
    for site in sorted({sp.site for sp in sps}):
        sw, sd = src_w(site)
        # 이 소싱처에 URL이 있는 모델들
        site_models = sorted({mc for (mc, s2) in url_by_model_site if s2 == site})
        brands_here = sorted({brand_of(mc) or "미지정" for mc in site_models})
        bchildren = []
        for brand in brands_here:
            bkey = None if brand == "미지정" else brand
            bw, bd = brand_w(bkey, sw) if bkey else (sw, False)
            bmodels = [mc for mc in site_models if (brand_of(mc) or "미지정") == brand]
            mchildren = []
            for mc in sorted(bmodels):
                mw, md = model_w(mc, bw)
                ochildren = opt_nodes(mc, mw)
                urls = url_nodes_for(mc, site)
                for on in ochildren:
                    on["children"] = urls
                mchildren.append({
                    "scope_type": "model", "scope_key": mc,
                    "label": (models[mc].model_name_display or models[mc].model_name_raw or mc),
                    "brand": brand_of(mc), "weight": mw, "direct": md,
                    "editable": True, "children": ochildren,
                })
            bchildren.append({
                "scope_type": "brand", "scope_key": bkey or "",
                "label": brand, "weight": bw, "direct": bd,
                "editable": bool(bkey), "children": mchildren,
            })
        src_tree.append({
            "scope_type": "source", "scope_key": site, "label": src_label(site),
            "weight": sw, "direct": sd, "editable": True, "children": bchildren,
            # 소싱처별 동시 상한(저장값 있으면 그것, 없으면 성격 기본) + 창없이 여부.
            "concurrency": conc_map.get(site, default_source_concurrency(site)),
            "conc_direct": site in conc_map,
            "winless": source_is_windowless(site),
        })

    # ── brd 기준(4열): 브랜드 → 모음전 → 옵션 → URL(소싱처별) ──
    brd_tree = []
    all_brands = sorted({brand_of(mc) or "미지정" for mc in models
                         if mc in opts_by_model or any(m2 == mc for (m2, s2) in url_by_model_site)})
    for brand in all_brands:
        bkey = None if brand == "미지정" else brand
        bw, bd = brand_w(bkey, DEFAULT_WEIGHT) if bkey else (DEFAULT_WEIGHT, False)
        bmodels = sorted({mc for mc in models if (brand_of(mc) or "미지정") == brand
                          and any(m2 == mc for (m2, s2) in url_by_model_site)})
        mchildren = []
        for mc in bmodels:
            mw, md = model_w(mc, bw)
            ochildren = opt_nodes(mc, mw)
            urls = url_nodes_for(mc, None)
            for on in ochildren:
                on["children"] = urls
            mchildren.append({
                "scope_type": "model", "scope_key": mc,
                "label": (models[mc].model_name_display or models[mc].model_name_raw or mc),
                "brand": brand_of(mc), "weight": mw, "direct": md,
                "editable": True, "children": ochildren,
            })
        brd_tree.append({
            "scope_type": "brand", "scope_key": bkey or "",
            "label": brand, "weight": bw, "direct": bd,
            "editable": bool(bkey), "children": mchildren,
        })

    # ── mdl 기준(3열): 모음전 → 옵션 → URL(소싱처별) ──
    mdl_tree = []
    for mc in sorted({mc for (mc, s2) in url_by_model_site}):
        bkey = brand_of(mc)
        # 모델 계수 = model_rule or brand_rule or 기본 (소싱처 문맥 없음)
        base = rules["brand"].get(bkey, DEFAULT_WEIGHT) if bkey else DEFAULT_WEIGHT
        mw, md = model_w(mc, base)
        ochildren = opt_nodes(mc, mw)
        urls = url_nodes_for(mc, None)
        for on in ochildren:
            on["children"] = urls
        mdl_tree.append({
            "scope_type": "model", "scope_key": mc,
            "label": (models[mc].model_name_display or models[mc].model_name_raw or mc),
            "brand": bkey, "weight": mw, "direct": md,
            "editable": True, "children": ochildren,
        })

    return {"default_weight": DEFAULT_WEIGHT,
            "src": src_tree, "brd": brd_tree, "mdl": mdl_tree}


def _short_url(url: str) -> str:
    """표시용 짧은 URL — 도메인 뒷부분 위주."""
    u = (url or "").replace("https://", "").replace("http://", "")
    return u[:60]
