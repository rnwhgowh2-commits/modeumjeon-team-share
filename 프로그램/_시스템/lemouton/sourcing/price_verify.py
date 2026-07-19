"""소싱처별 최종매입가 검증 — 3층 대조 판정 (순수 로직).

배경(2026-07-19): 가격 오류 6건 중 3건이 코드 검증으로 안 잡히고 라이브 화면
대조에서만 드러났다. ①③만 비교하면 "숫자가 다르다"만 알고 어디서 틀렸는지 모른다.
롯데아이몰 건이 정확히 그랬다 — 표면가 자리에 카드할인 먹은 값이 들어가 있었는데
최종매입가만 비교했으면 원인을 못 찾았다.

    ① 소싱처 실제 페이지   ← 정답지 (사람이 눈으로 본 값)
          ↕ 여기서 갈리면 → 크롤 파싱 문제  (LAYER_CRAWL)
    ② 우리가 수집한 데이터  ← 표면가 · 혜택 항목들
          ↕ 여기서 갈리면 → 계산 로직 문제  (LAYER_CALC)
    ③ 우리 계산 결과       ← 최종매입가 (fx영수증)

★ 철칙 — '확인불가'를 '일치'로 뭉개지 않는다. 크롤 실패를 "문제없음"으로 세면
  그게 곧 조용한 실패(silent failure)다. 값이 없으면 폴백·추정 없이 UNKNOWN.

이 모듈은 순수 함수만 담는다(DB·네트워크 없음). ③ 계산은 기존 엔진
webapp.routes.api_benefits.compute_breakdown 이 하고, 여기는 그 결과를 받아 판정만 한다.
"""

# ── 판정 3값 ──────────────────────────────────────────────────────────
VERDICT_MATCH = "match"        # 일치
VERDICT_MISMATCH = "mismatch"  # 불일치 (갈린 층 명시)
VERDICT_UNKNOWN = "unknown"    # 확인불가 (← 절대 일치로 뭉개지 않음)

VERDICT_LABEL = {
    VERDICT_MATCH: "일치",
    VERDICT_MISMATCH: "불일치",
    VERDICT_UNKNOWN: "확인불가",
}

# ── 갈린 층 ───────────────────────────────────────────────────────────
LAYER_CRAWL = "crawl"  # ①↔② 표면가가 갈림 → 크롤 파싱 문제
LAYER_CALC = "calc"    # ②↔③ 혜택이 갈림   → 계산/설정 문제

LAYER_LABEL = {
    LAYER_CRAWL: "①↔② 표면가 (크롤 파싱 문제)",
    LAYER_CALC: "②↔③ 혜택 (계산·설정 문제)",
}


def _norm_name(name) -> str:
    """혜택명 비교용 정규화 — 공백 제거 + 소문자.

    사람이 '무신사 머니' 로 적고 엔진이 '무신사머니' 를 쓰는 정도의 표기 흔들림만
    흡수한다. 그 이상 추측 매칭(부분일치 등)은 하지 않는다 — 엉뚱한 항목끼리
    맞춰놓고 '일치' 라고 보고하면 그게 조용한 실패다.
    """
    return "".join(str(name or "").split()).lower()


def _as_int(v):
    """숫자로 못 읽으면 None. 0 은 유효한 값이므로 살린다(폴백 금지)."""
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════
#  ①↔② 표면가 대조
# ══════════════════════════════════════════════════════════════════════
def judge_surface(human_surface, ours_surface) -> dict:
    """사람이 본 표면가 vs 우리가 수집한 표면가.

    갈리면 크롤 파싱 문제다 — 페이지의 '어느 숫자' 를 표면가로 집었는지가 틀린 것.
    (롯데아이몰: 카드할인이 이미 먹은 '최대할인가' 를 표면가로 집었던 사고)
    """
    h = _as_int(human_surface)
    o = _as_int(ours_surface)
    if h is None:
        return {"verdict": VERDICT_UNKNOWN, "human": None, "ours": o, "diff": None,
                "reason": "사람이 본 표면가가 입력되지 않았습니다."}
    if o is None:
        return {"verdict": VERDICT_UNKNOWN, "human": h, "ours": None, "diff": None,
                "reason": "우리가 수집한 표면가가 없습니다(크롤 데이터 없음)."}
    if h == o:
        return {"verdict": VERDICT_MATCH, "human": h, "ours": o, "diff": 0,
                "reason": "표면가가 같습니다."}
    return {"verdict": VERDICT_MISMATCH, "human": h, "ours": o, "diff": o - h,
            "reason": f"표면가가 다릅니다. 페이지 {h:,}원 / 우리 수집 {o:,}원 "
                      f"(차이 {o - h:+,}원). 크롤이 페이지의 다른 숫자를 집고 있을 수 있습니다."}


# ══════════════════════════════════════════════════════════════════════
#  ②↔③ 혜택 대조
# ══════════════════════════════════════════════════════════════════════
def judge_benefits(human_benefits, engine_steps, benefits_complete=False) -> dict:
    """사람이 본 혜택 항목별 금액 vs 엔진이 실제로 차감한 항목(steps).

    human_benefits: [{'name': str, 'amount': number}, ...]  — 선택 입력
    engine_steps:   compute_breakdown 결과의 'steps'
                    [{'name','type','value','deduct','base_after'}, ...]
                    None = 계산 실패 → 확인불가
    benefits_complete: 사람이 "혜택을 빠짐없이 다 적었다" 고 선언했는지.
        True 면 '엔진에만 있는 항목' 도 불일치로 센다(= 우리가 없는 혜택을 넣고 있다).
        False 면 참고 정보로만 남긴다 — 사람이 일부만 적었을 수 있으므로
        추측으로 불일치를 만들지 않는다.

    금액 비교는 정확히 일치(tolerance 0). 1원 오차도 삼키지 않는다 —
    반올림 노이즈처럼 보이는 차이가 실제 계산 버그였던 전례가 있다.
    """
    if engine_steps is None:
        return {"verdict": VERDICT_UNKNOWN, "items": [], "extra_in_engine": [],
                "reason": "우리 계산 결과가 없습니다(계산 실패)."}

    human_list = []
    for b in (human_benefits or []):
        if not isinstance(b, dict):
            continue
        nm = str(b.get("name") or "").strip()
        amt = _as_int(b.get("amount"))
        if not nm or amt is None:
            continue
        human_list.append({"name": nm, "amount": amt})

    if not human_list:
        return {"verdict": VERDICT_UNKNOWN, "items": [], "extra_in_engine": [],
                "reason": "사람이 본 혜택 금액이 입력되지 않았습니다. "
                          "이 층은 확인불가입니다(일치로 치지 않습니다)."}

    by_norm = {}
    for st in (engine_steps or []):
        if not isinstance(st, dict):
            continue
        by_norm.setdefault(_norm_name(st.get("name")), st)

    items = []
    matched_norms = set()
    mismatch = False
    for hb in human_list:
        key = _norm_name(hb["name"])
        st = by_norm.get(key)
        if st is None:
            mismatch = True
            items.append({"name": hb["name"], "human": hb["amount"], "ours": None,
                          "status": "missing",
                          "reason": "페이지에는 있는데 우리 계산에서 빠졌습니다."})
            continue
        matched_norms.add(key)
        ours = _as_int(st.get("deduct"))
        if ours is None:
            mismatch = True
            items.append({"name": hb["name"], "human": hb["amount"], "ours": None,
                          "status": "no_amount",
                          "reason": "우리 계산의 차감 금액을 읽지 못했습니다."})
        elif ours == hb["amount"]:
            items.append({"name": hb["name"], "human": hb["amount"], "ours": ours,
                          "status": "match", "reason": "금액이 같습니다."})
        else:
            mismatch = True
            items.append({"name": hb["name"], "human": hb["amount"], "ours": ours,
                          "status": "amount_diff",
                          "reason": f"금액이 다릅니다. 페이지 {hb['amount']:,}원 / "
                                    f"우리 계산 {ours:,}원 (차이 {ours - hb['amount']:+,}원)."})

    extra = []
    for st in (engine_steps or []):
        if not isinstance(st, dict):
            continue
        key = _norm_name(st.get("name"))
        if key in matched_norms:
            continue
        extra.append({"name": st.get("name"), "ours": _as_int(st.get("deduct"))})
    if extra and benefits_complete:
        mismatch = True

    if mismatch:
        bits = [i["reason"] for i in items if i["status"] != "match"]
        if extra and benefits_complete:
            bits.append("페이지에 없는 혜택을 우리가 차감하고 있습니다: "
                        + ", ".join(str(e["name"]) for e in extra))
        return {"verdict": VERDICT_MISMATCH, "items": items, "extra_in_engine": extra,
                "reason": " / ".join(bits)}

    reason = "입력한 혜택 항목이 모두 우리 계산과 같습니다."
    if extra:
        reason += (f" (참고: 우리 계산에만 있는 항목 {len(extra)}건 — "
                   "'혜택을 빠짐없이 입력' 을 켜지 않아 불일치로 세지 않았습니다.)")
    return {"verdict": VERDICT_MATCH, "items": items, "extra_in_engine": extra,
            "reason": reason}


# ══════════════════════════════════════════════════════════════════════
#  종합 판정
# ══════════════════════════════════════════════════════════════════════
def judge(*, human_surface, ours_surface, human_benefits=None,
          engine_steps=None, engine_final_price=None,
          benefits_complete=False) -> dict:
    """3층 대조 종합 판정.

    반환:
      verdict          — match / mismatch / unknown
      diverged_layers  — 갈린 층 키 목록 (crawl / calc)
      layers           — 층별 상세 {crawl: {...}, calc: {...}}
      summary          — 사람이 읽을 한 줄 요약

    ★ 우선순위: 불일치가 하나라도 있으면 불일치. 없고 확인불가가 있으면 확인불가.
      둘 다 없어야 비로소 일치. (확인불가 → 일치 승격 금지)
    """
    crawl = judge_surface(human_surface, ours_surface)
    calc = judge_benefits(human_benefits, engine_steps, benefits_complete=benefits_complete)

    layers = {LAYER_CRAWL: crawl, LAYER_CALC: calc}
    diverged = [k for k, v in ((LAYER_CRAWL, crawl), (LAYER_CALC, calc))
                if v["verdict"] == VERDICT_MISMATCH]
    unknown = [k for k, v in ((LAYER_CRAWL, crawl), (LAYER_CALC, calc))
               if v["verdict"] == VERDICT_UNKNOWN]

    if diverged:
        verdict = VERDICT_MISMATCH
        summary = "불일치 — " + " · ".join(LAYER_LABEL[k] for k in diverged)
    elif unknown:
        verdict = VERDICT_UNKNOWN
        summary = "확인불가 — " + " · ".join(LAYER_LABEL[k] for k in unknown)
    else:
        verdict = VERDICT_MATCH
        summary = "일치 — 표면가·혜택 모두 우리 데이터와 같습니다."

    return {
        "verdict": verdict,
        "verdict_label": VERDICT_LABEL[verdict],
        "diverged_layers": diverged,
        "unknown_layers": unknown,
        "layers": layers,
        "summary": summary,
        "engine_final_price": _as_int(engine_final_price),
    }


# ══════════════════════════════════════════════════════════════════════
#  엑셀 내보내기 — 기존 관례(openpyxl · 순수 helper 가 bytes 반환) 준수
#  참고: lemouton/markets/order_export.py rows_to_xlsx
# ══════════════════════════════════════════════════════════════════════
ALL_COLUMNS = [
    "검증일시", "검증자", "소싱처", "상품URL", "SKU",
    "① 페이지 표면가", "② 우리 표면가", "표면가 판정", "표면가 차이",
    "혜택 판정", "혜택 상세",
    "③ 최종매입가", "종합 판정", "갈린 층", "메모",
]
DEFAULT_COLUMNS = list(ALL_COLUMNS)


def resolve_columns(columns=None) -> list:
    """사용자 지정 열(순서 유지)을 유효 열로 필터. 비면 기본 전체."""
    if not columns:
        return list(DEFAULT_COLUMNS)
    seen, out = set(), []
    for c in columns:
        c = (c or "").strip()
        if c in ALL_COLUMNS and c not in seen:
            seen.add(c)
            out.append(c)
    return out or list(DEFAULT_COLUMNS)


def rows_to_xlsx(rows: list, columns=None) -> bytes:
    """행(dict) → xlsx 바이트. 열 이름이 곧 행 dict 의 키."""
    import io
    import openpyxl
    cols = resolve_columns(columns)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "최종매입가 검증"
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
