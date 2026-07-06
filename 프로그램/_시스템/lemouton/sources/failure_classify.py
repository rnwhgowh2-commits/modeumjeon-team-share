"""크롤 실패 사유 → 유형 분류 (순수 함수).

에러 메시지의 키워드로 유형을 판정한다. 근거 = 크롤링 가이드 §5 에러 이력·재고탭
(차단/로그인/파싱·매핑/타임아웃). 어느 유형에도 안 걸리면 '유형 외'(etc) —
유형 외를 계속 줄이며 개선하기 위해 별도로 표기한다.

실제 실패 데이터가 담기는 필드·화면 연결은 후속(P5 실행중/실패 UI).
"""

# 우선순위 순서(위에서부터 먼저 매칭). 키워드는 소문자 비교.
FAILURE_TYPES = {
    "block":   {"label": "차단",       "emoji": "🚫",
                "keywords": ["차단", "waf", "403", "forbidden", "blocked", "captcha", "봇", "bot"]},
    "login":   {"label": "로그인",     "emoji": "🔑",
                "keywords": ["로그인", "login", "회원", "인증", "session", "세션", "401", "unauthorized", "로그아웃"]},
    "parse":   {"label": "옵션 못읽음", "emoji": "🧩",
                "keywords": ["옵션없음", "옵션 없음", "파싱", "parse", "매핑", "미매칭", "no option", "옵션 li"]},
    "network": {"label": "응답 지연",   "emoji": "⏱",
                "keywords": ["타임아웃", "timeout", "timed out", "네트워크", "network", "econn", "refused", "응답 없음", "연결"]},
    "etc":     {"label": "유형 외",     "emoji": "❔", "keywords": []},
}

_ORDER = ["block", "login", "parse", "network"]


def classify_crawl_failure(status, error_message):
    """실패 1건을 유형으로. status가 실패가 아니면 None.

    반환: {"type", "label", "emoji"} 또는 None(실패 아님).
    """
    if status == "ok":
        return None
    msg = (error_message or "").lower()
    for t in _ORDER:
        if any(k.lower() in msg for k in FAILURE_TYPES[t]["keywords"]):
            return {"type": t, "label": FAILURE_TYPES[t]["label"], "emoji": FAILURE_TYPES[t]["emoji"]}
    # 어느 유형에도 안 걸림(메시지 없음 포함) → 유형 외
    return {"type": "etc", "label": FAILURE_TYPES["etc"]["label"], "emoji": FAILURE_TYPES["etc"]["emoji"]}


def _option_scope(colors, sizes, url_type):
    """실패 URL이 덮는 옵션 범위를 짧게. 옵션 없으면 url_type 폴백."""
    if colors:
        if len(colors) == 1:
            c = colors[0]
            if len(sizes) == 1:
                return c + " · " + sizes[0]
            if len(sizes) > 1:
                return c + " · " + sizes[0] + "~" + sizes[-1]
            return c
        return colors[0] + " 외 " + str(len(colors) - 1) + "색"
    return url_type or "옵션 미상"


def list_crawl_failures(session) -> list:
    """last_status='error' 인 활성 URL을 실패 유형별로 묶어 반환(화면 ⑤ 데이터).

    각 item = 소싱처(site·site_label) / 브랜드 / 옵션(색·사이즈) / url_type / url / error
    → B 아코디언(소싱처>브랜드>옵션/url)이 4계층으로 파고든다. 유형 순서 고정.
    """
    from lemouton.sources.models import SourceProduct, SourceOption, ModelSourceLink
    from lemouton.sources.service import normalize_url
    from lemouton.sourcing.models import BundleSourceUrl, Model
    try:
        from lemouton.sourcing.source_registry import get_labels
        labels = get_labels() or {}
    except Exception:
        labels = {}

    # 정규화 URL → {model_codes, url_type}
    url_meta = {}
    for b in session.query(BundleSourceUrl).all():
        n = normalize_url(b.url)
        m = url_meta.setdefault(n, {"model_codes": set(), "url_type": None})
        m["model_codes"].add(b.model_code)
        if b.url_type and not m["url_type"]:
            m["url_type"] = b.url_type
    brand_by_model = {m.model_code: m.brand for m in session.query(Model).all()}
    # SourceProduct → model_code 직접 링크(ModelSourceLink) — URL 정규화 매칭이 어긋나도
    #   브랜드를 찾게 하는 더 확실한 경로.
    msl_by_sp = {}
    for l in session.query(ModelSourceLink).all():
        msl_by_sp.setdefault(l.source_product_id, set()).add(l.model_code)

    rows = (session.query(SourceProduct)
            .filter(SourceProduct.deleted_at.is_(None))
            .filter(SourceProduct.last_status == "error")
            .all())
    groups = {}
    for sp in rows:
        c = classify_crawl_failure("error", sp.last_error_msg)
        meta = url_meta.get(normalize_url(sp.url), {"model_codes": set(), "url_type": None})
        mcs = sorted(set(meta["model_codes"]) | msl_by_sp.get(sp.id, set()))
        brands = sorted({brand_by_model.get(mc) for mc in mcs if brand_by_model.get(mc)})
        opts = (session.query(SourceOption)
                .filter_by(source_product_id=sp.id, deleted_at=None).all())
        colors = sorted({o.color_text for o in opts if o.color_text})
        sizes = sorted({o.size_text for o in opts if o.size_text})
        g = groups.setdefault(c["type"], {"type": c["type"], "label": c["label"],
                                          "emoji": c["emoji"], "count": 0, "items": []})
        g["count"] += 1
        g["items"].append({
            "source_product_id": sp.id,
            "site": sp.site,
            "site_label": labels.get(sp.site, sp.site),
            "brand": brands[0] if brands else None,
            "option_scope": _option_scope(colors, sizes, meta["url_type"]),
            "url_type": meta["url_type"],
            "url": sp.url,
            "error": sp.last_error_msg,
            # 에러 발견 시각 = 마지막 크롤 시점(A안 상대시간). naive UTC ISO.
            "detected_at": sp.last_fetched_at.isoformat() if sp.last_fetched_at else None,
        })
    order = list(FAILURE_TYPES.keys())
    return sorted(groups.values(), key=lambda g: order.index(g["type"]))
