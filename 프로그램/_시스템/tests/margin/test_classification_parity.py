# -*- coding: utf-8 -*-
r"""분류 교차언어 parity 조사 (deferred item I1) — 결과: **parity 불필요 (분기 2)**.

배경
────
코드 리뷰가 "행 분류가 JS·Python 두 곳에 있어 요약 탭이 모순될 수 있다"고 우려했다.
그 우려가 성립하려면 Python 이 JS `classify()` 와 **비교 가능한 버킷**(정상/고마진/
의심손실/계산불가 = 정산·매입 0 기준)으로 각 행을 분류하고, 그 값이 JS 카운트와
**같은 탭에 나란히** 표시되어야 한다. 조사 결과 둘 다 아니다.

조사 결과 (코드 실측)
────────────────────
1) JS 분류 = `webapp/static/margin_rules.js`
   · `classify(r)` : excluded / unfulfilled / loss / uncomputable / highmargin / normal
     - loss         = 정산0 & (블랙스팟 키워드 | 매입>0)     (25~33행)
     - uncomputable = 정산0 & 매입0                         (38~42행)
     - highmargin   = 정산>0 & 매입0                         (34~37행)
     - normal       = 그 외(정산>0 & 매입>0)
   · `summarize(rows)` 가 요약 탭 미니카드(정상/고마진/의심손실/계산불가)를 만든다.

2) Python 분류 = `lemouton/margin/aggregator.py` + `matcher.py`
   · 비교 가능한(정산0 기준) 행 분류기가 **없다**.
   · 존재하는 유일한 행 플래그는 `matcher.py:359` 의 `이상가` :
        이상가 = (구매가격 > 판매가*3 & 판매가>0) | 구매가격 > 500000
     → 이것은 **매입/판매가 배수** 축이다. JS 의 정산0 축(loss/uncomputable/
       highmargin)과 **다른 것을 측정**한다. 서로 대응(parity)시킬 짝이 아니다.
   · `aggregator.py:120~128` 의 정상매출/정상순마진/이상가건수 는 `이상가==False`
     필터로 계산된다. 즉 여기서 "정상" = "이상가 아님"이지, JS 의 "정상"(정산·매입
     모두>0)이 아니다.
   · aggregator 의 card_* 버킷(immediate/sourcing/market/normal/pending/kkadaegi/
     margin, 166~219행)은 블랙스팟 '상세분류' 코드(1-1/1-2/3-1 …) 축으로, 이것도
     JS classify 와 대응 짝이 아니다.

3) 같은 탭에 나란히 표시되는가? — **아니다.**
   · `webapp/static/margin_render.js:37~41` 주석·코드가 명시한다:
       "분류 카운트(정상/고마진/의심손실/계산불가)는 서버 summary 에 없다 → 규칙
        모듈(MR=margin_rules.js)로 matched 행에서 직접 집계."
     요약 탭 미니카드는 **오직 JS `MR.summarize`** 가 만든다.
   · 서버 summary 의 정상매출/정상순마진/정상마진율/이상가건수/정상매입 은
     `webapp/static/*.js` 어디에서도 렌더되지 않는다(grep 0건). 표시되지 않으므로
     JS 카운트와 모순을 일으킬 표면이 존재하지 않는다.

결론
────
비교 가능한 Python 행 분류기가 없고(분기 2), 서버의 정상/이상 값은 UI 에서 JS
카운트와 함께 표시되지도 않는다 → **분류 교차언어 divergence 가 사용자 화면에
표면화될 수 없다.** 따라서 가짜 parity 테스트를 만들지 않는다. 대신 아래 테스트가
(a) JS 가 표시 버킷의 단일 원천임을, (b) 서버 summary 가 JS 표시 버킷 키를 노출하지
않음을, (c) 두 축이 설계상 다른 것을 측정함을 고정(guard)한다. 향후 누군가 Python
쪽에 정산0 기준 표시 버킷을 추가하면 (b) 가 깨져 진짜 parity 테스트가 필요함을 알린다.
"""
import pathlib
import shutil
import subprocess

import pytest

from lemouton.margin import aggregator as A
from lemouton.margin.config import DEFAULT_PRICE_RANGES

MR_JS = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static" / "margin_rules.js"

# JS classify 가 표시하는 4개 버킷 라벨 (요약 탭 미니카드).
JS_DISPLAY_BUCKETS = {"정상", "고마진", "의심손실", "계산불가"}

# 공유 픽스처 6행 — 각 JS 버킷을 최소 1개씩 덮는다.
FIXTURE_ROWS = [
    # (설명, 정산예상금액, 구매가격, 기대 JS classify)
    ("정상",       33000,  21000, "normal"),
    ("고마진",     110000,     0, "highmargin"),
    ("의심손실",       0,  18000, "loss"),
    ("계산불가",       0,      0, "uncomputable"),
    ("정상2",       60000,  41000, "normal"),
    ("의심손실2",       0, 150000, "loss"),
]


def _agg_row(desc, settle, buy):
    """aggregator 가 요구하는 최소 컬럼을 갖춘 matched 행."""
    sale = 50000
    return {
        "주문일": "2026-07-04", "일자": "2026-07-04", "월": "2026-07",
        "마켓": "쿠팡", "브랜드": "테스트", "금액대": "3~5만",
        "상품명": f"상품 {desc}", "상품코드": desc,
        "단가": sale, "판매가": sale, "실결제금액": sale,
        "정산예상금액": settle, "구매가격": buy,
        "순마진": (settle - buy), "마진율": 0.0, "수량_매출": 1,
        # matcher.py:359 이상가 규칙 그대로 재현 (매입/판매가 배수 축)
        "이상가": (buy > sale * 3 and sale > 0) or buy > 500000,
        "매칭타입": "정밀", "간단메모": "",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_is_sole_source_of_display_buckets():
    """JS classify/summarize 가 표시 버킷(정상/고마진/의심손실/계산불가)의 단일 원천."""
    rows_js = [{"정산예상금액": s, "구매가격": b} for _, s, b, _ in FIXTURE_ROWS]
    expected = [exp for *_, exp in FIXTURE_ROWS]
    script = r"""
    const MR = require(process.argv[1]);
    const rows = JSON.parse(process.argv[2]);
    const cls = rows.map(r => MR.classify(r));
    const s = MR.summarize(rows);
    console.log(JSON.stringify({cls, 정상:s.정상, 고마진:s.고마진,
                                의심손실:s.의심손실, 계산불가:s.계산불가}));
    """
    import json
    r = subprocess.run(["node", "-e", script, str(MR_JS), json.dumps(rows_js, ensure_ascii=False)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["cls"] == expected, f"JS classify 결과가 기대와 다름: {out['cls']}"
    # summarize 집계도 픽스처와 일치 (정상2·의심손실2·고마진1·계산불가1)
    assert (out["정상"], out["고마진"], out["의심손실"], out["계산불가"]) == (2, 1, 2, 1)


def test_python_summary_does_not_expose_js_display_buckets():
    """서버 summary 는 JS 표시 버킷 키를 노출하지 않는다 → 같은 탭 모순 표면 없음.

    이 단언이 깨지면(Python 이 정산0 기준 표시 버킷을 summary 에 추가) 진짜
    교차언어 parity 테스트가 필요하다는 신호다.
    """
    rows = [_agg_row(*fx[:3]) for fx in FIXTURE_ROWS]
    out = A.aggregate(rows, DEFAULT_PRICE_RANGES)
    summary_keys = set(out["summary"].keys())
    leaked = JS_DISPLAY_BUCKETS & summary_keys
    assert not leaked, (
        f"서버 summary 가 JS 표시 버킷 키를 노출: {leaked} — "
        "이제 두 분류가 같은 값으로 표시될 수 있으므로 실제 parity 테스트가 필요하다."
    )


def test_python_이상가_and_js_loss_measure_different_axes():
    """Python '이상가'(매입/판매가 배수) 와 JS 'loss'(정산0) 는 다른 축임을 고정.

    의심손실(정산0·매입 소액) 행은 JS 에선 loss 지만 Python 이상가 규칙으론
    '이상가 아님'(정상 집계에 포함)이다 — 두 분류는 대응(parity) 짝이 아니다.
    """
    # 정산0·매입 18000·판매가 50000 → JS: loss / Python 이상가: False
    loss_like = _agg_row("의심손실", 0, 18000)
    assert loss_like["이상가"] is False  # matcher 규칙상 이상가 아님
    out = A.aggregate([loss_like], DEFAULT_PRICE_RANGES)
    # 이상가건수 0 → 이 행은 Python '정상' 집계에 들어간다 (JS 의 '의심손실'과 반대 라벨)
    assert out["summary"]["이상가건수"] == 0
