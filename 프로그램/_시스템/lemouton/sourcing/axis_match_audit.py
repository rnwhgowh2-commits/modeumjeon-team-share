# -*- coding: utf-8 -*-
"""3단계 착수 전 점검 — 판정기를 바꾸면 **화면 값이 어떻게 달라지나**.

설계: docs/사전점검_옵션URL매핑_설계.md §15-D, §16 3단계

왜 필요한가
  매트릭스를 새 판정기(axis_match)로 바꾸면 값이 바뀐다. 「변경 0건」이 나오지 않는다 —
  그동안 부분일치로 **잘못 붙어 있던 값이 떨어져 나가기** 때문이다. 그 목록을 먼저
  뽑아 사장님이 보신 뒤에 바꾼다. 확인 없이 넘어가면 「멀쩡하던 값이 사라졌다」가 된다.

무엇을 하나 (읽기 전용 — DB 에 아무것도 쓰지 않는다)
  옵션 × 소싱처상품 마다 옛 판정과 새 판정을 **둘 다** 돌려 결과를 비교한다.
    lost    : 옛=붙음, 새=안 붙음   → 값이 사라질 칸 (대개 그동안 남의 색이던 것)
    gained  : 옛=안 붙음, 새=붙음   → 값이 새로 생길 칸 (BLACK·검정·7US 되찾기)
    changed : 둘 다 붙었는데 **다른 소싱처 옵션** → 값이 바뀔 칸 (가장 위험)

공정한 비교를 위해
  새 판정기는 옛 판정기의 **구조를 그대로 베끼고**(정확일치 우선 → 사이즈만 → 색상 전용),
  「같은 것인가」를 묻는 **비교 방법만** 바꾼다. 그래야 나오는 차이가 순수하게
  「판정 기준 차이」가 된다. (옛: 부분일치 / 새: 정규화+사전+축매핑)
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .axis_match import match_source_option

_DIGITS = re.compile(r"\d+")


def _digits(x) -> str:
    return "".join(c for c in str(x or "") if c.isdigit())


def _cnorm(x) -> str:
    """옛 판정기와 동일한 정규화 (api_pricing._stk_cnorm)."""
    return re.sub(r"[\s()（）\[\]·,/\-_:：]", "", str(x or "")).lower()


# ── 옛 판정 (api_pricing._match_option_so 와 동일 규칙) ──────────────────

def old_match(cands, opt_color, opt_size):
    osz = _digits(opt_size)
    if not osz:
        return None
    oc = _cnorm(opt_color)
    exact, subs, color_only_subs = [], [], []
    size_only = None
    color_only = None
    for so in cands:
        st = (so.size_text or "").strip()
        s_size = _digits(st) or _digits(so.color_text)
        if not s_size:
            if oc:
                sc = _cnorm(so.color_text)
                if sc:
                    if oc == sc:
                        if color_only is None:
                            color_only = so
                    elif oc in sc or sc in oc:
                        color_only_subs.append(so)
            continue
        if s_size != osz:
            continue
        has_color = bool(st) and bool((so.color_text or "").strip())
        if has_color and oc:
            sc = _cnorm(so.color_text)
            if not sc:
                continue
            if oc == sc:
                exact.append(so)
                continue
            if oc in sc or sc in oc:
                subs.append(so)
            continue
        if size_only is None or (size_only.current_stock is None
                                 and so.current_stock is not None):
            size_only = so
    if exact:
        return next((s for s in exact if s.current_stock is not None), exact[0])
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        return None
    if size_only is not None:
        return size_only
    if color_only is not None:
        return color_only
    if len(color_only_subs) == 1:
        return color_only_subs[0]
    return None


# ── 새 판정 — 프로덕션 함수를 그대로 쓴다 (쌍둥이 유지 금지) ─────────────
#   같은 로직을 두 벌 두면 한쪽만 고쳐져 「감사는 통과인데 화면은 다름」이 된다.

def new_match(session: Session, *, source_key: str, cands,
              opt_color, opt_size,
              color_axis: str = "색상", size_axis: str = "사이즈"):
    return match_source_option(session, source_key=source_key, candidates=cands,
                               opt_color=opt_color, opt_size=opt_size,
                               color_axis=color_axis, size_axis=size_axis)


# ── 전수 비교 ───────────────────────────────────────────────────────────

def _axis_names(session: Session, model_code: str, *, rows=None) -> tuple[str, str]:
    """상품의 축 이름 (1축·2축). 없으면 색상/사이즈.

    `rows`: 호출자가 이미 읽어 둔 `BundleOptionStep` 행(step_no 순). 주면 조회를 건너뛴다
      — 주문 표 한 판처럼 상품마다 이 함수를 부르는 자리에서 왕복을 줄이려는 것뿐이고,
      **고르는 규칙은 아래 그대로**다.
    """
    try:
        from .models import BundleOptionStep
        if rows is None:
            rows = (session.query(BundleOptionStep)
                    .filter_by(model_code=model_code)
                    .order_by(BundleOptionStep.step_no).all())
        names = [(r.axis_name or "").strip() for r in rows if (r.axis_name or "").strip()]
        # 🔴 [2026-08-12] 예전엔 `names[0], names[1]` — **몇 번째 축인가**로 골랐다.
        #   그러면 축을 「모델·색상·사이즈」로 짠 순간 색을 「모델」 사전에서 찾게 되어,
        #   손으로 맞춘 것과 「이 소싱처엔 없다」고 정한 것이 **둘 다 무시**된다.
        #   이 값은 `match_source_option` 으로 흘러가 **어느 소싱처 옵션의 가격·재고를
        #   우리 옵션에 붙일지**를 정한다 — 틀리면 남의 색 가격이 붙는다.
        #   저장·축맞추기 화면은 이미 이름 기준(axis_slot)인데 이 읽기 경로만 남아 있었다.
        #   규칙은 lemouton/sourcing/axis_slot.py 한 곳뿐이고 여기서도 그것을 쓴다.
        if names:
            from .axis_slot import COLOR, SIZE, semantic_slots
            slots = semantic_slots(names)
            c = next((names[i] for i, s in enumerate(slots) if s == COLOR), None)
            z = next((names[i] for i, s in enumerate(slots) if s == SIZE), None)
            if c or z:
                return c or "색상", z or "사이즈"
        if len(names) >= 2:
            return names[0], names[1]
        if len(names) == 1:
            return names[0], "사이즈"
    except Exception:
        pass
    return "색상", "사이즈"


def compare_bundle(session: Session, model_code: str) -> dict:
    """상품 하나 — 옛/새 판정 차이. 읽기 전용."""
    from lemouton.sources.models import SourceOption, SourceProduct
    from .models import BundleSourceUrl, Option, OptionSourceUrlLink

    from lemouton.sources.service import normalize_url

    opts = (session.query(Option)
            .filter_by(model_code=model_code)
            .all())
    if not opts:
        return {"model_code": model_code, "checked": 0,
                "lost": [], "gained": [], "changed": []}

    links = (session.query(OptionSourceUrlLink, BundleSourceUrl)
             .join(BundleSourceUrl,
                   OptionSourceUrlLink.bundle_source_url_id == BundleSourceUrl.id)
             .filter(BundleSourceUrl.model_code == model_code)
             .all())
    if not links:
        return {"model_code": model_code, "checked": 0,
                "lost": [], "gained": [], "changed": []}

    urls = {bsu.url for _lk, bsu in links if bsu.url}
    sps = session.query(SourceProduct).filter(SourceProduct.url.in_(list(urls))).all() if urls else []
    sp_by_norm = {normalize_url(sp.url): sp for sp in sps}
    sp_ids = [sp.id for sp in sps]
    so_rows = (session.query(SourceOption)
               .filter(SourceOption.source_product_id.in_(sp_ids),
                       SourceOption.deleted_at.is_(None)).all()) if sp_ids else []
    by_sp: dict[int, list] = {}
    for so in so_rows:
        by_sp.setdefault(so.source_product_id, []).append(so)

    color_axis, size_axis = _axis_names(session, model_code)
    opt_by_sku = {o.canonical_sku: o for o in opts}

    lost, gained, changed = [], [], []
    checked = 0
    for lk, bsu in links:
        o = opt_by_sku.get(lk.option_canonical_sku)
        if o is None or not bsu.url:
            continue
        sp = sp_by_norm.get(normalize_url(bsu.url))
        if sp is None:
            continue
        cands = by_sp.get(sp.id) or []
        if not cands:
            continue
        checked += 1
        a = old_match(cands, o.color_code, o.size_code)
        b = new_match(session, source_key=bsu.source_key, cands=cands,
                      opt_color=o.color_code, opt_size=o.size_code,
                      color_axis=color_axis, size_axis=size_axis)
        if a is b:
            continue
        base = {
            "model_code": model_code, "sku": o.canonical_sku,
            "our": f"{o.color_code} {o.size_code}".strip(),
            "source_key": bsu.source_key, "url_label": bsu.label or "",
        }
        if a is not None and b is None:
            lost.append({**base, "was": f"{a.color_text or ''} {a.size_text or ''}".strip(),
                         "was_price": a.current_price})
        elif a is None and b is not None:
            gained.append({**base, "now": f"{b.color_text or ''} {b.size_text or ''}".strip(),
                           "now_price": b.current_price})
        else:
            changed.append({**base,
                            "was": f"{a.color_text or ''} {a.size_text or ''}".strip(),
                            "was_price": a.current_price,
                            "now": f"{b.color_text or ''} {b.size_text or ''}".strip(),
                            "now_price": b.current_price})
    return {"model_code": model_code, "checked": checked,
            "lost": lost, "gained": gained, "changed": changed}


def compare_all(session: Session, *, limit: int | None = None) -> dict:
    """전 상품 — 판정기 교체 시 달라질 칸 전수. 읽기 전용."""
    from .models import BundleSourceUrl

    codes = [r[0] for r in session.query(BundleSourceUrl.model_code).distinct().all()]
    codes = sorted(c for c in codes if c)
    if limit:
        codes = codes[:limit]
    lost, gained, changed = [], [], []
    checked = 0
    for code in codes:
        try:
            r = compare_bundle(session, code)
        except Exception:
            continue
        checked += r["checked"]
        lost.extend(r["lost"])
        gained.extend(r["gained"])
        changed.extend(r["changed"])
    return {
        "bundles": len(codes),
        "checked": checked,
        "summary": {"lost": len(lost), "gained": len(gained), "changed": len(changed)},
        "lost": lost, "gained": gained, "changed": changed,
    }
