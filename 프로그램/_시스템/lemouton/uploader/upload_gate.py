# -*- coding: utf-8 -*-
"""[Phase 1B M3-1] 업로드 게이트 — 올릴지 말지 **판정만** 한다.

이 모듈은 순수 함수다. DB 도, 네트워크도, 마켓 API 도 건드리지 않는다.
실제 전송 배선은 M3-2 소관이다.

■ 이 게이트가 존재하는 이유
  소싱처 가격·재고가 바뀌면 가능한 빨리 마켓에 반영해야 한다.
    · 우리 가격이 낮으면 → 역마진(팔수록 손해)
    · 우리 가격이 높으면 → 경쟁력 상실(안 팔림)
    · 품절인데 안 내리면 → 남들 다 품절이라 **주문이 우리한테만 몰린다**.
      이행 못 하고 CS 가 터진다. 재고 반영 지연은 가격 지연보다 더 아프다.

■ 왜 스킵하나 (아껴서가 아니다)
  재고 10→3 같은 "어차피 팔 수 있음" 구간의 업로드가 큐를 채우면, 정작 급한
  **가격 변동·품절(P0)** 이 뒤로 밀린다. 스킵은 비용 절감이 아니라 **P0 지연을
  막기 위한 우선순위 방어**다. 그래서 스킵 판정도 반드시 사유와 함께 반환한다 —
  아무것도 반환하지 않으면 '조용한 실패'와 구분되지 않는다.

■ 왜 가격이 항상 이기나
  재고 스킵 규칙은 **가격이 안 바뀐 경우에만** 적용한다. "재고 5→3이라 스킵"
  하다가 같이 바뀐 가격을 못 올리면 그게 곧 역마진이다.

■ 크롤 실패 = '확인불가' (폴백 금지)
  값을 못 가져왔으면 추정가·0원·직전값으로 채우지 않는다. 그 축은 **기존 값을
  그대로 유지**한다. 그리고 실패를 '변동 없음'으로 세지 않는다
  (:attr:`GateDecision.counts_as_no_change` = False) — 실패를 안정으로 오독하면
  자동화 엔진의 크롤 계수(no_change_streak)가 잘못 내려가 점점 덜 크롤하게 된다.

재고 센티넬은 집 관례 그대로 (lemouton/sources/lap_report.py:43):
    None = 미크롤 / -1 = 확인불가 / 0 = 품절 / 999 = 있음(상한 미상)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# 재고 '확인불가' 센티넬. 크롤러(musinsa.py:77, ssg.py:183)와 같은 값.
STOCK_UNKNOWN = -1

# '넉넉함' 경계. 이 이상이면 재고만 움직여도 굳이 안 올린다(사용자 확정 규약).
PLENTY = 3

PRIORITIES = ("P0", "P1", "P2")


@dataclass(frozen=True)
class GateDecision:
    """게이트 판정 결과. **스킵도 이 객체로 말한다** (조용한 실패 금지)."""

    should_upload: bool
    priority: str                 # 'P0' 급함 | 'P1' 중요 | 'P2' 안 급함(스킵)
    reason_code: str              # 기계용 고정 코드 (분기·집계용)
    reason: str                   # 사람이 읽는 한 문장

    price_changed: bool = False
    stock_changed: bool = False

    # 각 축을 이번 크롤에서 실제로 알아냈나. False = 확인불가 → 그 축은 기존 값 유지.
    price_known: bool = True
    stock_known: bool = True

    # 역마진 가드에 걸려 보류됐나. True 면 should_upload=False 이고
    # '판매중지 후보'로 사람에게 보여야 한다.
    held_for_margin: bool = False
    needs_sale_stop: bool = False

    # "변동 없음" 으로 집계해도 되는가. 크롤 실패는 False —
    # 실패를 안정으로 세면 크롤 주기가 잘못 늘어난다.
    counts_as_no_change: bool = False

    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def skipped(self) -> bool:
        return not self.should_upload

    def to_dict(self) -> dict:
        """PriceSnapshot 적재·API 응답용 평면 dict."""
        return {
            "action": ("upload" if self.should_upload
                       else ("hold" if self.held_for_margin else "skip")),
            "should_upload": self.should_upload,
            "priority": self.priority,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "price_changed": self.price_changed,
            "stock_changed": self.stock_changed,
            "price_known": self.price_known,
            "stock_known": self.stock_known,
            "held_for_margin": self.held_for_margin,
            "needs_sale_stop": self.needs_sale_stop,
            "counts_as_no_change": self.counts_as_no_change,
            "warnings": list(self.warnings),
        }


def _known_stock(v) -> bool:
    """재고 값이 '실제로 아는 숫자'인가. None(미크롤)·-1(확인불가)은 모른다."""
    if v is None:
        return False
    try:
        return int(v) > STOCK_UNKNOWN
    except (TypeError, ValueError):
        return False


def _won(v) -> str:
    try:
        return f"{int(v):,}원"
    except (TypeError, ValueError):
        return "확인불가"


def _stock_word(v) -> str:
    """재고 숫자 → 사람 말. lap_report._stock_word 와 같은 어휘를 쓴다."""
    if v is None:
        return "미크롤"
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    if n < 0:
        return "확인불가"
    if n == 0:
        return "품절"
    if n >= 999:
        return "있음"
    return f"{n}개"


def decide_upload(
    *,
    prev_price=None,
    prev_stock=None,
    new_price=None,
    new_stock=None,
    margin_amount=None,
    min_margin_amount: int = 0,
) -> GateDecision:
    """직전 스냅샷 vs 새 크롤 결과 → 올릴지 말지.

    Args:
        prev_price: 직전 스냅샷의 가격. **마켓에 실제로 올렸던 값**을 넣는다
            (upload_price). 스냅샷이 없으면(첫 업로드) None.
        prev_stock: 직전 스냅샷의 재고. None=없음/미크롤, -1=확인불가.
        new_price: 이번에 계산된 업로드 예정가. **None = 크롤/계산 실패(확인불가)**.
            0 은 '0원'이라는 실제 값이지 실패가 아니다 — 구분해서 넣어야 한다.
        new_stock: 이번 크롤 재고. None=못 읽음, -1=확인불가, 0=품절.
        margin_amount: 이번 업로드가로 팔았을 때 남는 마진(원). 모르면 None
            → 가드를 적용하지 않는다(모르는 걸 '미달'로 단정하지 않는다).
        min_margin_amount: 이 값 **미만**이면 보류. 기본 0 = 사실상 꺼짐.

    Returns:
        GateDecision — 스킵이어도 사유가 들어 있다.

    비교 대상이 '업로드가'인 이유: 마켓에 실제로 나가는 숫자가 안 바뀌면 보낼 게
    없다. 최종매입가만 미세하게 움직이고 업로드가가 그대로인 경우까지 P0 로 태우면
    큐가 막혀 진짜 P0 가 밀린다. 다만 매입가 변동은 마진을 바꾸므로, 호출자는
    그런 경우에도 ``margin_amount`` 를 갱신해 넘겨야 한다 — 아래 역마진 가드는
    가격 변동 여부와 무관하게 항상 검사한다.
    """
    price_known = new_price is not None
    stock_known = _known_stock(new_stock)
    warnings: list[str] = []

    prev_stock_known = _known_stock(prev_stock)

    # ── 각 축의 변동 판정 ───────────────────────────────────────────────────
    # 모르는 축은 '안 바뀜'이 아니라 '판정 불가'다. 아래에서 절대 변동으로 세지 않는다.
    price_changed = bool(price_known and prev_price is not None
                         and int(new_price) != int(prev_price))
    stock_changed = bool(stock_known and prev_stock_known
                         and int(new_stock) != int(prev_stock))

    if not price_known:
        warnings.append("가격 확인불가 — 기존 가격을 그대로 둡니다(추정가 금지).")
    if not stock_known:
        warnings.append("재고 확인불가 — 기존 재고를 그대로 둡니다(999 폴백 금지).")

    # ── 0) 크롤이 양쪽 다 실패 ─────────────────────────────────────────────
    #   올릴 근거가 하나도 없다. 그러나 '변동 없음'으로 세지 않는다.
    if not price_known and not stock_known:
        return GateDecision(
            should_upload=False, priority="P2",
            reason_code="crawl_failed",
            reason="크롤 실패(확인불가) — 기존 값 유지. 변동 없음으로 세지 않습니다.",
            price_known=False, stock_known=False,
            counts_as_no_change=False,
            warnings=tuple(warnings),
        )

    # ── 1) 첫 업로드 (기준선 없음) ─────────────────────────────────────────
    #   uploader/changes.py:detect_change 와 같은 규약 — 이전 기록이 없으면 변동.
    if prev_price is None and not prev_stock_known:
        return _apply_margin_guard(
            GateDecision(
                should_upload=True, priority="P0",
                reason_code="first_upload",
                reason="직전 스냅샷 없음 — 기준선을 만들기 위해 올립니다.",
                price_changed=price_known, stock_changed=stock_known,
                price_known=price_known, stock_known=stock_known,
                warnings=tuple(warnings),
            ),
            new_stock=new_stock, stock_known=stock_known,
            margin_amount=margin_amount, min_margin_amount=min_margin_amount,
        )

    # ── 2) 가격 변동 = 무조건 업로드 (재고 조건 무관) ───────────────────────
    #   ★ 이 분기가 재고 규칙보다 반드시 위에 있어야 한다. 아래로 내려가면
    #     "재고 5→3이라 스킵" 하면서 같이 바뀐 가격을 못 올린다 = 역마진 사고.
    if price_changed:
        return _apply_margin_guard(
            GateDecision(
                should_upload=True, priority="P0",
                reason_code="price_change",
                reason=f"가격 변동 {_won(prev_price)}→{_won(new_price)} — 가격은 재고와 무관하게 즉시 반영.",
                price_changed=True, stock_changed=stock_changed,
                price_known=price_known, stock_known=stock_known,
                warnings=tuple(warnings),
            ),
            new_stock=new_stock, stock_known=stock_known,
            margin_amount=margin_amount, min_margin_amount=min_margin_amount,
        )

    # ── 3) 가격은 그대로. 여기부터 재고 규칙 ────────────────────────────────
    if not stock_known:
        # 가격은 읽었는데 안 바뀌었고, 재고는 확인불가 → 올릴 게 없다.
        # 단, 크롤이 반쪽 실패했으므로 '변동 없음'으로 세지 않는다.
        return GateDecision(
            should_upload=False, priority="P2",
            reason_code="stock_unknown",
            reason="재고 확인불가 — 기존 재고 유지. 변동 없음으로 세지 않습니다.",
            price_changed=False, stock_changed=False,
            price_known=price_known, stock_known=False,
            counts_as_no_change=False,
            warnings=tuple(warnings),
        )

    ns = int(new_stock)

    # 이전 재고를 모르면(첫 재고 관측·직전이 확인불가) 기준선이 없다 → 올려서 맞춘다.
    if not prev_stock_known:
        return _apply_margin_guard(
            GateDecision(
                should_upload=True, priority="P1",
                reason_code="prev_stock_unknown",
                reason=f"직전 재고 기준선 없음(={_stock_word(prev_stock)}) — 현재 {_stock_word(ns)} 로 맞춥니다.",
                price_changed=False, stock_changed=False,
                price_known=price_known, stock_known=True,
                warnings=tuple(warnings),
            ),
            new_stock=ns, stock_known=True,
            margin_amount=margin_amount, min_margin_amount=min_margin_amount,
        )

    ps = int(prev_stock)

    # 3-a) 가격도 재고도 그대로 → 보낼 게 없다. 이게 유일한 '진짜 무변동'이다.
    #      (재고 0→0 도 여기서 걸린다. 이미 올려둔 품절을 다시 올리는 건 큐 낭비다.)
    if ns == ps:
        return GateDecision(
            should_upload=False, priority="P2",
            reason_code="no_change",
            reason=f"가격·재고 모두 그대로({_won(new_price)} / {_stock_word(ns)}) — 보낼 값이 없습니다.",
            price_changed=False, stock_changed=False,
            price_known=price_known, stock_known=True,
            counts_as_no_change=True,
            warnings=tuple(warnings),
        )

    # 3-b) 품절 = P0. 재고 반영이 늦으면 주문이 우리한테만 몰린다.
    if ns == 0:
        decision = GateDecision(
            should_upload=True, priority="P0",
            reason_code="sold_out",
            reason=f"품절({_stock_word(ps)}→품절) — 즉시 내려야 오버셀·CS 를 막습니다.",
            price_changed=False, stock_changed=True,
            price_known=price_known, stock_known=True,
            warnings=tuple(warnings),
        )
    # 3-c) 재입고 = P1. 팔 수 있는데 안 파는 상태를 빨리 푼다.
    elif ps == 0 and ns >= 1:
        decision = GateDecision(
            should_upload=True, priority="P1",
            reason_code="restock",
            reason=f"재입고(품절→{_stock_word(ns)}) — 판매 재개.",
            price_changed=False, stock_changed=True,
            price_known=price_known, stock_known=True,
            warnings=tuple(warnings),
        )
    # 3-d) 품절임박 = P1. 넉넉하던 게 2개 이하로 떨어짐.
    elif ps >= PLENTY and ns <= PLENTY - 1:
        decision = GateDecision(
            should_upload=True, priority="P1",
            reason_code="low_stock",
            reason=f"품절임박({_stock_word(ps)}→{_stock_word(ns)}) — 곧 품절이라 미리 맞춥니다.",
            price_changed=False, stock_changed=True,
            price_known=price_known, stock_known=True,
            warnings=tuple(warnings),
        )
    # 3-e) 넉넉→넉넉 = 스킵. ★큐를 아끼려는 게 아니라 P0 를 밀리지 않게 하려는 것.
    elif ps >= PLENTY and ns >= PLENTY:
        return GateDecision(
            should_upload=False, priority="P2",
            reason_code="plenty_to_plenty",
            reason=(f"재고 {_stock_word(ps)}→{_stock_word(ns)} — 둘 다 {PLENTY}개 이상이라 "
                    f"판매에 영향이 없습니다. 급한 가격·품절(P0)을 먼저 보내려고 건너뜁니다."),
            price_changed=False, stock_changed=True,
            price_known=price_known, stock_known=True,
            counts_as_no_change=False,   # 재고는 실제로 바뀌었다 — 무변동이 아니다
            warnings=tuple(warnings),
        )
    # 3-f) 나머지 = 2개 이하 주의구간 안의 변동(1→2, 2→1 등). 오차 하나가 오버셀이라 올린다.
    else:
        decision = GateDecision(
            should_upload=True, priority="P1",
            reason_code="low_stock_band",
            reason=f"주의구간 변동({_stock_word(ps)}→{_stock_word(ns)}) — {PLENTY}개 미만이라 오차 하나가 오버셀입니다.",
            price_changed=False, stock_changed=True,
            price_known=price_known, stock_known=True,
            warnings=tuple(warnings),
        )

    return _apply_margin_guard(
        decision, new_stock=ns, stock_known=True,
        margin_amount=margin_amount, min_margin_amount=min_margin_amount,
    )


def _apply_margin_guard(decision: GateDecision, *, new_stock, stock_known: bool,
                        margin_amount, min_margin_amount: int) -> GateDecision:
    """역마진 가드 — 마진금액(원)이 임계 미만이면 업로드를 보류하고 경고한다.

    ★ 품절(재고 0) 업로드는 막지 않는다.
      품절 반영은 '파는 행위'가 아니라 '판매를 멈추는 행위'다. 마진이 나쁘다는
      이유로 품절 반영까지 막으면, 팔면 안 되는 상품이 마켓에 재고 있는 채로
      남아 주문이 들어온다 — 가드가 정확히 막으려던 손실을 가드가 만들어낸다.

    margin_amount 가 None(모름) 이면 아무 판정도 하지 않는다. 모르는 값을
    '미달'로 단정해 멀쩡한 P0 를 막는 것도, 0 으로 채워 통과시키는 것도 둘 다 사고다.
    """
    if not decision.should_upload:
        return decision
    if margin_amount is None:
        return decision
    try:
        margin = int(margin_amount)
        floor = int(min_margin_amount or 0)
    except (TypeError, ValueError):
        return decision
    if margin >= floor:
        return decision

    # 품절 반영은 통과시킨다 (위 docstring 참고). 다만 경고는 남긴다.
    if stock_known and int(new_stock) == 0:
        return replace(
            decision,
            needs_sale_stop=True,
            warnings=decision.warnings + (
                f"마진 {margin:,}원 < 기준 {floor:,}원이지만 품절 반영이라 그대로 내립니다.",),
        )

    return replace(
        decision,
        should_upload=False,
        held_for_margin=True,
        needs_sale_stop=True,
        reason_code="margin_below_min",
        reason=(f"마진 {margin:,}원 < 기준 {floor:,}원 — 올리면 손해라 보류합니다. "
                f"(원래 사유: {decision.reason})"),
        counts_as_no_change=False,
        warnings=decision.warnings + (
            f"역마진 경고 — 마진 {margin:,}원(기준 {floor:,}원). 판매중지 후보입니다.",),
    )
