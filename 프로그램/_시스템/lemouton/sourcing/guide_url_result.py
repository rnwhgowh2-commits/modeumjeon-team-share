# -*- coding: utf-8 -*-
"""[S5] 예시 주소 「▶ 크롤」 1건의 계산 결과.

설계: docs/superpowers/specs/2026-07-19-소싱처상세-지도흡수-design.md §S5

하는 일 — 확장이 로컬에서 긁어온 raw 결과 1건을, 소싱처 패널 ① 칸의 주소 카드에
보여줄 값(표면 노출가 · 혜택 합계 · 최종 매입가 · 재고)으로 바꾼다.

안 하는 일 — 산수. 최종 매입가는 **전부** ``pricing.final_price.compute_final_price``
가 낸다. 여기서 직접 빼거나 곱하지 않는다(엔진 이중화 = 금액 불일치의 시작).

혜택을 쓸지 말지는 가이드의 **값 출처(value_source)** 로 정한다(crawl_guide.py:506).

    fixed  사장님이 직접 넣은 고정값. 크롤과 무관하게 늘 안다 → 적용한다.
    crawl  상품마다 긁어야 아는 값. 못 긁었으면 **적용하지 않는다**.

두 번째가 핵심이다. 확장은 무신사·롯데온에서만 혜택 라인을 준다
(extension/moum-crawler/background.js:1563). 나머지 소싱처에서 크롤 혜택을
가이드에 적힌 값으로 대신 깎아버리면, **실제로는 못 받은 할인**이 반영된 싼 값이
나와 그 가격에 사입하게 된다 — 손해 매입.

지키는 원칙 (CLAUDE.md 정합성 3대 원칙):
  1. 못 읽은 값은 **0 이 아니라 None**. 0원은 화면에서 '공짜'로 읽혀 금전 사고가 된다.
  2. 폴백 금지 — 가격을 못 읽었으면 대표가로 메우지 않고 '실패'로 표면화한다.
  3. 빠진 혜택이 있으면 benefit_note 로 **이름을 대서** 알린다. 조용히 빼지 않는다.
"""
from __future__ import annotations

from typing import Any

from lemouton.pricing.benefit_gate import gate_benefits
from lemouton.pricing.final_price import compute_final_price

# 재고 센티넬 — 수집기 공통 규약.
#   999 = '있다는 건 알지만 몇 개인지는 모름'
#    -1 = 파싱 실패 = 확인 불가. 999(=있음)로 둔갑시키면 오버셀이 난다.
_STOCK_IN_STOCK_SENTINEL = 999


class _Item:
    """compute_final_price 가 기대하는 혜택 항목 모양(덕 타이핑).

    엔진은 .benefit_name/.benefit_type('rate'|'amount')/.value/.enabled 를 읽는다.
    """

    __slots__ = ("id", "benefit_name", "benefit_type", "value", "enabled",
                 "category", "sort_order", "template_id", "apply_mode")

    def __init__(self, name, btype, value, enabled, sort_order):
        self.id = -1
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = None
        self.sort_order = sort_order
        self.template_id = None
        self.apply_mode = None


def _method_type(method: str) -> "str | None":
    """가이드의 '방식' 표시문자열 → 엔진 타입. 차감 혜택이 아니면 None.

    ★ 규약은 ``sync_templates_from_crawl_guide``(api_benefits.py:1435) 와 **동일**하다.
      한쪽만 바꾸면 같은 혜택이 화면과 업로드에서 다른 금액이 된다.
        · '개월' 포함 → 무이자 할부. 깎아주는 돈이 아니다.
        · '%'   포함 → 정률. 사람이 넣은 % 를 소수로 (10 → 0.10)
        · 그 외      → 정액(원)
    """
    m = method or ""
    if "개월" in m:
        return None
    return "rate" if "%" in m else "amount"


def _to_engine_item(name: str, method: str, value: Any, *,
                    enabled: bool, sort_order: int) -> "_Item | None":
    """혜택 1건 → 엔진 항목. 값이 없거나 차감 혜택이 아니면 None."""
    btype = _method_type(method)
    if btype is None or value is None:
        return None
    try:
        val = float(value) / 100.0 if btype == "rate" else float(value)
    except (TypeError, ValueError):
        return None
    return _Item(name, btype, val, enabled, sort_order)


def _stock_label(stock: Any) -> str:
    """재고 숫자 → 사람이 읽는 한 마디. 모르면 '확인 불가'(있음으로 둔갑 금지)."""
    try:
        n = int(stock)
    except (TypeError, ValueError):
        return "확인 불가"
    if n < 0:
        return "확인 불가"
    if n == 0:
        return "품절"
    if n >= _STOCK_IN_STOCK_SENTINEL:
        return "재고 있음"
    return f"{n}개"


def _failed(now_iso: str, reason: str) -> dict:
    """실패 결과. 금액은 전부 None — 0 으로 채우지 않는다."""
    return {
        "surface_price": None, "benefit_total": None, "final_price": None,
        "stock_label": None, "status": "failed", "crawled_at": now_iso,
        "job_id": None, "error": reason, "benefit_source": None, "benefit_note": "",
    }


def compute_url_result(guide: dict, raw: dict, *, now_iso: str) -> dict:
    """확장이 긁어온 raw 1건 → 주소 카드에 보여줄 계산 결과.

    Args:
        guide:   이 소싱처의 크롤 가이드(validate 된 dict)
        raw:     확장 결과 —
                 {status, price, surface_price?, stock?, benefit_lines?,
                  benefit_amounts?, error?}
        now_iso: 크롤 시각 (호출자가 넣는다 — 이 함수는 시계를 안 본다)

    Returns:
        crawl_guide._clean_url_result 가 받는 모양 + 화면 안내용 benefit_note.
    """
    raw = raw or {}

    # ① 크롤 자체가 실패했나
    if raw.get("status") != "ok":
        return _failed(now_iso, str(raw.get("error") or "").strip()
                       or "크롤에 실패했습니다(사유를 받지 못했습니다)")

    # ② 표면 노출가 — 무신사·롯데온은 surface_price 를 따로 준다.
    #    없으면 price(=최저 옵션가)가 표면가. 둘 다 없으면 폴백하지 않고 실패.
    surface = raw.get("surface_price")
    if surface is None:
        surface = raw.get("price")
    try:
        surface = int(surface)
    except (TypeError, ValueError):
        surface = None
    if surface is None or surface <= 0:
        return _failed(now_iso, "가격을 읽지 못했습니다")

    benefits = ((guide.get("pricing") or {}).get("benefits")) or []
    excludes = guide.get("exclude_keywords") or []
    lines = [x for x in (raw.get("benefit_lines") or []) if isinstance(x, str)]
    amounts = raw.get("benefit_amounts") or {}

    # 긁은 라인이 있으면 저장된 포함/제외 키워드로 혜택별 적용 여부를 판정한다.
    applied_by_name: dict = {}
    if lines:
        applied_by_name = {g["name"]: g["applied"]
                           for g in gate_benefits(benefits, lines, excludes)}

    items: list = []
    used_crawled = False      # 크롤로 값을 알아낸 혜택이 하나라도 있었나
    skipped: list = []        # 못 긁어서 뺀 크롤 혜택 이름

    for i, b in enumerate(benefits):
        name = (b.get("name") or "").strip()
        if not name:
            continue
        method = b.get("method") or ""
        if _method_type(method) is None:
            continue                                   # 할부 등 차감 아님 — 조용히 넘어가도 됨
        is_planned = b.get("status") == "planned"

        if b.get("value_source") == "crawl":
            # 상품마다 긁어야 아는 값 — 라인과 금액이 **둘 다** 있어야 쓴다.
            amt = amounts.get(name) or {}
            amt_val = amt.get("value")
            if not lines or amt_val is None:
                if not is_planned:
                    skipped.append(name)
                continue
            if not applied_by_name.get(name, False):
                continue                               # 게이트에서 제외됨(예: '등급 할인 불가')
            # 금액 타입은 크롤이 알려준 것을 우선하되, 없으면 가이드 방식을 따른다.
            amt_method = "정률(%)" if amt.get("type") == "rate" else "정액(원)"
            it = _to_engine_item(name, amt_method,
                                 amt_val * 100.0 if amt.get("type") == "rate" else amt_val,
                                 enabled=not is_planned, sort_order=i)
            if it is not None:
                items.append(("dyn", it))
                used_crawled = True
        else:
            # 고정값 — 늘 안다. 그대로 적용.
            it = _to_engine_item(name, method, b.get("value"),
                                 enabled=not is_planned, sort_order=i)
            if it is not None:
                items.append(("dyn", it))

    # ③ 산수는 전부 엔진이 한다.
    res = compute_final_price(float(surface), items, base_override=None)
    final = int(res["final_price"])

    note = ""
    if skipped:
        note = ("이번 크롤에서 값을 받지 못해 뺀 혜택: "
                + ", ".join(skipped)
                + ". 실제 매입가는 이보다 쌀 수 있습니다.")
    elif not used_crawled:
        note = "가이드에 적힌 고정 혜택만 반영했습니다."

    return {
        "surface_price": surface,
        "benefit_total": surface - final,
        "final_price": final,
        "stock_label": _stock_label(raw.get("stock")),
        "status": "done",
        "crawled_at": now_iso,
        "job_id": None,
        "error": None,
        "benefit_source": "crawled" if used_crawled else "fixed_only",
        "benefit_note": note,
    }
