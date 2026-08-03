# -*- coding: utf-8 -*-
"""매칭 3단 계단 — 우리 축 값과 소싱처 표기가 같은 것인지 판정하는 **단일 판정기**.

설계: docs/사전점검_옵션URL매핑_설계.md §15-C·§15-D, §16 2단계

지금 무엇이 문제인가
  매트릭스가 쓰는 판정은 **부분일치**다(`api_pricing._match_option_so`, `oc in sc or sc in oc`).
  그래서 소싱처 「오프화이트」가 우리 「화이트」에, 「네이비」가 「다크네이비」에 붙어
  **남의 색 가격이 정상처럼 표시**된다. 반대로 「BLACK」·「검정」·「7US」는 사전이 있는데도
  못 붙는다 — 그 사전을 아무도 안 부르기 때문이다.

3단 계단 (이 순서 고정)
  1. **축 매핑(DB)** — 사장님이 고른 것. 무엇보다 우선.       → method='db'
  2. **정규화**      — 소문자 + 공백·`-`·`_`·`.` 제거.        → method='exact'
  3. **내장 사전**   — `shared/sku_format` 색 21종·사이즈 16종. → method='dict'
  안 맞으면 **붙이지 않는다.** 부분일치는 쓰지 않는다.

축 이름을 몰라도 되는 이유
  축 이름은 사장님이 짓는다(색상·사이즈·모델·재질…). 그래서 색 사전과 사이즈 사전을
  **둘 다** 조회하고, 하나라도 같은 그룹이면 맞는 것으로 본다. 두 사전이 서로 다른 답을
  내는 겹침은 실측상 없다(`one`↔`onesize` 도 정규화형이 달라 갈린다).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from shared.sku_format import color_groups, normalize_label, size_groups

from . import axis_alias as _alias


@dataclass
class MatchResult:
    matched: bool
    method: str | None = None      # 'db' | 'exact' | 'dict' | None
    note: str = ""


def _dict_groups(value: str) -> set[str]:
    """색 사전 + 사이즈 사전에서 이 표기가 속한 그룹들. 축 이름을 몰라도 되게 합친다."""
    g: set[str] = set()
    g |= {f"c:{x}" for x in color_groups(value)}
    g |= {f"s:{x}" for x in size_groups(value)}
    return g


def match_one(session: Session, *, source_key: str, axis_name: str,
              our_value: str, source_value: str) -> MatchResult:
    """우리 축 값 하나 ↔ 소싱처 표기 하나. 3단 계단으로 판정한다."""
    our = (our_value or "").strip()
    src = (source_value or "").strip()
    if not our or not src:
        return MatchResult(False, None, "빈 값")

    # 0단 — 「이 소싱처엔 없다」고 **정한** 것이면 어떤 표기와도 안 붙인다.
    #   사전이 틀리게 붙였을 때 사장님이 거부하는 유일한 수단이라 사전보다 앞선다.
    if _alias.is_absent(session, source_key, axis_name, our):
        return MatchResult(False, None, "없음으로 정하셨습니다")

    # 1단 — 사장님이 정한 것이 최우선
    saved = _alias.resolve(session, source_key, axis_name, src)
    if saved is not None:
        if saved == our:
            return MatchResult(True, "db", "맞춰 둔 것")
        # 그 표기는 다른 우리 값이 쓰고 있다 → 이 줄과는 아니다
        return MatchResult(False, None, f"「{saved}」 이(가) 쓰는 표기")

    # 2단 — 모양만 다른 것 (사전 없이 통과)
    n_our, n_src = normalize_label(our), normalize_label(src)
    if n_our and n_our == n_src:
        return MatchResult(True, "exact", "띄어쓰기·대소문자만 다름")

    # 3단 — 내장 사전
    g_our, g_src = _dict_groups(our), _dict_groups(src)
    if g_our and g_src and (g_our & g_src):
        return MatchResult(True, "dict", "사전에 같은 뜻으로 등록됨")

    return MatchResult(False, None, "확실하지 않음 — 붙이지 않음")


_DIGITS = __import__("re").compile(r"\d+")


def match_source_option(session: Session, *, source_key: str, candidates,
                        opt_color, opt_size,
                        color_axis: str = "색상", size_axis: str = "사이즈"):
    """우리 옵션(색·사이즈) ↔ 그 소싱처 상품의 SourceOption 하나를 고른다.

    매트릭스·사전점검이 **같은 답**을 내도록 이 함수 하나만 쓴다.

    옛 판정기(`api_pricing._match_option_so`)의 **구조는 그대로** 두고
    (정확일치 우선 → 사이즈만(단품) → 색상 전용(사이즈 미제공 소싱처)),
    「같은 것인가」를 묻는 방법만 3단 계단으로 바꾼다.
    **부분일치는 쓰지 않는다** — 「오프화이트」가 「화이트」에 붙어 남의 색 가격을
    보여주던 것이 그것이다.
    """
    def same(axis, ours, theirs) -> bool:
        return match_one(session, source_key=source_key, axis_name=axis,
                         our_value=ours, source_value=theirs).matched

    if not (opt_size or "").strip():
        return None
    exact = []
    size_only = None
    color_only = None
    for so in (candidates or []):
        st = (so.size_text or "").strip()
        # 사이즈 원문 — 비었으면 color_text 에 든 숫자(롯데온/SSG 단일색 표기)
        m = _DIGITS.search(so.color_text or "")
        size_src = st if st else ((m.group() + "mm") if m else "")
        if not size_src:
            # 색상 전용 데이터(사이즈 미제공 소싱처) — 색만으로
            if opt_color and (so.color_text or "").strip():
                if color_only is None and same(color_axis, opt_color, so.color_text):
                    color_only = so
            continue
        if not same(size_axis, opt_size, size_src):
            continue
        has_color = bool(st) and bool((so.color_text or "").strip())
        if has_color and opt_color:
            if same(color_axis, opt_color, so.color_text):
                exact.append(so)
            continue                      # 색 불일치 → 붙이지 않는다
        # 크롤 색이 빈 값(단품=단일색) → 사이즈만으로. 중복이면 재고 있는 행 우선.
        if size_only is None or (size_only.current_stock is None
                                 and so.current_stock is not None):
            size_only = so
    if exact:
        return next((x for x in exact if x.current_stock is not None), exact[0])
    if size_only is not None:
        return size_only
    return color_only


def suggest_axis(session: Session, *, source_key: str, axis_name: str,
                 our_values: list[str], source_values: list[str]) -> dict:
    """축 한 개를 통째로 제안한다 — 1층 드롭다운의 초기 상태.

    상태 4가지
      saved  : 이미 맞춰 둔 것 (origin 으로 수기/자동 구분 → 화면 파랑/초록)
      auto   : 이번에 확실히 붙은 것 (아직 저장 전)
      review : 후보가 2개 이상이라 사람이 골라야 함
      none   : 후보 0 — 소싱처에 없거나 사전이 모름

    **한 소싱처 표기를 두 우리 값이 나눠 갖지 않는다.** 겹치면 둘 다 자동 확정하지 않고
    사람에게 보낸다(재고 이중계상 → 초과 판매 차단).
    """
    ours = [str(v).strip() for v in (our_values or []) if str(v).strip()]
    srcs = [str(v).strip() for v in (source_values or []) if str(v).strip()]

    saved_map = _alias.get_map(session, source_key, axis_name)          # 우리값 → 표기
    saved_rows = {r["our_value"]: r for r in _alias.list_aliases(session, source_key, axis_name)}
    absent = _alias.absent_values(session, source_key, axis_name)       # 「없다」고 정한 값
    used_norm = {normalize_label(v) for v in saved_map.values()}

    # 저장된 것에 이미 쓰인 표기는 다른 줄 후보에서 뺀다 (드롭다운 잠금과 같은 기준)
    free_srcs = [v for v in srcs if normalize_label(v) not in used_norm]

    # 1) 우리 값마다 자유 표기 중 맞는 후보 모으기
    cand: dict[str, list[str]] = {}
    for our in ours:
        if our in saved_map or our in absent:
            continue
        hits = [sv for sv in free_srcs
                if match_one(session, source_key=source_key, axis_name=axis_name,
                             our_value=our, source_value=sv).matched]
        cand[our] = hits

    # 2) 한 표기를 노리는 우리 값이 둘 이상이면 자동 확정 금지
    claim: dict[str, list[str]] = {}
    for our, hits in cand.items():
        for sv in hits:
            claim.setdefault(normalize_label(sv), []).append(our)
    contested = {k for k, v in claim.items() if len(v) > 1}

    rows: list[dict] = []
    taken_norm: set[str] = set(used_norm)
    for our in ours:
        if our in absent:
            rows.append({
                "our_value": our, "source_value": None, "status": "absent",
                "method": "db", "origin": "manual", "candidates": [],
            })
            continue
        if our in saved_map:
            r = saved_rows.get(our) or {}
            rows.append({
                "our_value": our, "source_value": saved_map[our],
                "status": "saved", "method": "db",
                "origin": r.get("origin") or "manual", "candidates": [],
            })
            continue

        hits = [sv for sv in cand.get(our, []) if normalize_label(sv) not in taken_norm]
        clean = [sv for sv in hits if normalize_label(sv) not in contested]

        if len(clean) == 1:
            pick = clean[0]
            taken_norm.add(normalize_label(pick))
            m = match_one(session, source_key=source_key, axis_name=axis_name,
                          our_value=our, source_value=pick)
            rows.append({"our_value": our, "source_value": pick, "status": "auto",
                         "method": m.method, "origin": None, "candidates": hits})
        elif hits:
            rows.append({"our_value": our, "source_value": None, "status": "review",
                         "method": None, "origin": None, "candidates": hits})
        else:
            rows.append({"our_value": our, "source_value": None, "status": "none",
                         "method": None, "origin": None,
                         "candidates": [sv for sv in free_srcs
                                        if normalize_label(sv) not in taken_norm]})

    picked_norm = {normalize_label(r["source_value"]) for r in rows if r["source_value"]}
    unused = [sv for sv in srcs if normalize_label(sv) not in picked_norm]

    summary = {k: 0 for k in ("saved", "auto", "review", "none", "absent")}
    for r in rows:
        summary[r["status"]] += 1

    return {"rows": rows, "unused_source_values": unused, "summary": summary}
