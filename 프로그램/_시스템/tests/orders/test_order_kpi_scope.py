# -*- coding: utf-8 -*-
"""주문 KPI 「무엇을 빼고 무엇을 더하나」 — 값으로 못 박는 시험.

사장님 확정(2026-08-06)
    ① 제외 = 취소·반품 클레임. **교환은 포함**(교환은 정산이 이뤄진다).
    ② 매출     = 제외 후 `실결제금액 + 배송비`
    ③ 정산예정 = 제외 후 `정산예정금(배송비포함)`  ← `정산예정금액`(상품분) 아님
    ④ 주문금액 = 표의 `주문금액` 열 합(제외 없음)  ← 옛 「단가 총합」 아님
    ⑤ 잔글씨(A안) 3줄이 매출·정산예정 카드 밑에 붙는다

사장님 확정(2026-08-06 2차 — 1번)a · 2번)a)
    ⑥ 주문금액 카드는 **표의 `주문금액` 열을 그대로 더한다**(=단가×수량+배송비).
       옛 계산은 `단가` 개당가만 더해 **수량도 배송비도 빠진** 값이었다. 이름이 같은
       열과 값이 달라, 표 합계와 카드가 어긋났다(같은 이름 두 정의 = 모순).
    ⑦ 「마켓 할인」 카드를 주문금액과 매출 **사이**에 넣는다.
       할인 = 제외 후 `단가×수량 − 실결제금액`. 주문금액−매출 차이의 정체가
       마켓 할인(롯데온 제휴할인·스스 즉시할인 등)이라 화면이 직접 말해야 한다.
    ⑧ 모르는 값은 **0 으로 삼키지 않는다** — 주문금액·마켓할인도 정산예정과 똑같이
       「모르는 N건 빠짐」을 잔글씨 마지막 줄로 말한다.

★ 낱말 검사 금지 — 정의(order_claim_scope.js)를 **node 로 실행해 값으로** 본다.
  (낱말이 어딘가 있나로 보면 주석에 속고, 계산을 되돌려도 안 걸린다.)

🔴 이 시험이 지키는 실사고 두 개
    · 취소완료 행은 `정산예정금액`만 0 으로 강제되고 N열은 `0 + 배송비` 라 **배송비가
      남는다**. 안 거르면 취소된 주문의 배송비가 정산예정에 섞인다.
    · 「취소철회·반품철회」는 되돌린 클레임이라 주문이 살아 있고, 「교환*」은 정산이
      이뤄진다 — 빼면 매출이 실제보다 작아진다.
"""
import json
import pathlib
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

_시스템 = pathlib.Path(__file__).resolve().parents[2]
SCOPE_JS = _시스템 / "webapp" / "static" / "order_claim_scope.js"
PC_TPL = _시스템 / "webapp" / "templates" / "orders" / "index.html"

# ── 값 고정판 ────────────────────────────────────────────────────────────────
#   `정산예정금액`(상품분)과 `정산예정금(배송비포함)`을 **다르게** 넣었다 —
#   옛 열로 되돌리면 합계가 달라져 바로 걸린다.
#   🔴 `수량` 2 짜리·`주문금액` 빈칸 행을 일부러 섞었다 — 옛 「단가 총합」으로
#      되돌리면 수량분(20,000)과 배송비(13,000)가 통째로 사라져 값이 달라진다.
ROWS = [
    # 남는 행 -----------------------------------------------------------------
    {"주문상태": "배송완료", "실결제금액": 10000, "배송비": 2500,
     "정산예정금액": 9000, "정산예정금(배송비포함)": 11500,
     "단가": 10000, "수량": 1, "주문금액": 12500},
    # 수량 2 — 옛 계산은 단가 20,000 만 보고 20,000 을 잃었다. 할인 20,000 의 출처.
    {"주문상태": "교환완료", "실결제금액": 20000, "배송비": 3000,
     "정산예정금액": 18000, "정산예정금(배송비포함)": 21000,
     "단가": 20000, "수량": 2, "주문금액": 43000},
    {"주문상태": "교환요청", "실결제금액": 30000, "배송비": 0,
     "정산예정금액": 27000, "정산예정금(배송비포함)": 27000,
     "단가": 30000, "수량": 1, "주문금액": 30000},
    {"주문상태": "취소철회", "실결제금액": 80000, "배송비": 4000,
     "정산예정금액": 72000, "정산예정금(배송비포함)": 76000,
     "단가": 80000, "수량": 1, "주문금액": 84000},
    # 값을 하나도 모르는 행 — 0 으로 삼키지 말고 「모르는 1건」으로 말해야 한다.
    {"주문상태": "배송중", "실결제금액": "", "배송비": 0,
     "정산예정금액": "", "정산예정금(배송비포함)": "",
     "단가": "", "수량": "", "주문금액": ""},
    # 빠지는 행 ---------------------------------------------------------------
    {"주문상태": "취소완료", "실결제금액": 40000, "배송비": 2500,     # N열 = 0+배송비
     "정산예정금액": 0, "정산예정금(배송비포함)": 2500,
     "단가": 40000, "수량": 1, "주문금액": 42500},
    {"주문상태": "취소요청", "실결제금액": 50000, "배송비": 1000,
     "정산예정금액": 45000, "정산예정금(배송비포함)": 46000,
     "단가": 50000, "수량": 1, "주문금액": 51000},
    {"주문상태": "반품완료", "실결제금액": 60000, "배송비": 3000,
     "정산예정금액": 54000, "정산예정금(배송비포함)": 57000,
     "단가": 60000, "수량": 1, "주문금액": 63000},
    {"주문상태": "회수지시", "실결제금액": 70000, "배송비": 0,
     "정산예정금액": 63000, "정산예정금(배송비포함)": 63000,
     "단가": 70000, "수량": 1, "주문금액": 70000},
]
# 남는 행만: (10000+2500)+(20000+3000)+(30000+0)+(80000+4000)+(빈칸 0)
매출_정답 = 149500
# 남는 행의 N열만(빈칸 1건은 건너뜀): 11500+21000+27000+76000
정산예정_정답 = 135500
정산예정_빈칸 = 1
# 옛 열(`정산예정금액`)로 되돌리면 나오는 값 — 이것과 같아지면 되돌아간 것이다.
옛열_합 = 9000 + 18000 + 27000 + 72000        # = 126000
# 주문금액 = 표의 `주문금액` 열 합(제외 없음, 빈칸 1건 건너뜀)
주문금액_정답 = 12500 + 43000 + 30000 + 84000 + 42500 + 51000 + 63000 + 70000  # = 396000
주문금액_빈칸 = 1
# 옛 계산(`단가` 개당가 총합)으로 되돌리면 나오는 값 — 같아지면 되돌아간 것이다.
옛_단가총합 = 10000 + 20000 + 30000 + 80000 + 40000 + 50000 + 60000 + 70000    # = 360000
# 마켓 할인 = 제외 후 (단가×수량 − 실결제금액). 수량 2 행만 20,000 차이가 난다.
할인_정답 = 20000
할인_빈칸 = 1
발송대기_수 = 3                                # 화면(WAIT)이 세어 넘기는 값


def _node():
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node 없음")
    return exe


def _run(script, *args):
    r = subprocess.run([_node(), "-e", script, str(SCOPE_JS)] + list(args),
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_정의_파일이_있다():
    assert SCOPE_JS.exists(), "공용 정의(order_claim_scope.js)가 없다"


# ── ① 제외 정의 — 상태 실값으로 ─────────────────────────────────────────────
def test_취소_반품은_빠지고_교환_철회는_남는다():
    """상태 실값 출처 = order_export `_STATUS_KO` + 11번가 클레임표 + 롯데온 회수 단계."""
    빠져야 = ["취소완료", "취소요청", "취소중", "취소완료(미결제)", "취소완료(직권)",
              "취소완료(송금후)", "반품완료", "반품요청", "반품수거완료", "반품보류",
              "반품완료(직권)", "회수지시", "회수진행", "회수완료", "회수확정",
              # 🔴 단독 「철회」 = 롯데온 odPrgsStepCd 22 = 취소.
              #   마진 모듈(lemouton/margin/sell_source.py:226)이 `"철회": "취소완료"` 로
              #   매핑한다 — 여기서 남기면 롯데온 취소분이 매출·정산예정에 섞인다.
              "철회"]
    남아야 = ["교환완료", "교환요청", "교환수거완료", "교환보류", "교환재발송", "교환철회",
              # 앞 글자가 붙은 철회 = 되돌린 클레임(주문 살아 있음). '반품 철회' 처럼
              # 사이 공백이 있는 실값도 있다(lemouton/margin/config.py:137).
              "취소철회", "반품철회", "반품 철회", "취소철회(구매확정)", "취소철회(배송완료)",
              "결제완료", "배송중", "배송완료", "구매확정",
              "수취완료", "발송완료", "상품준비중", "출고지시", ""]
    out = _run(r"""
      const S=require(process.argv[1]);
      const a=JSON.parse(process.argv[2]), b=JSON.parse(process.argv[3]);
      console.log(JSON.stringify({
        out_a: a.map(s=>S.isExcluded(s)), out_b: b.map(s=>S.isExcluded(s))}));
    """, json.dumps(빠져야, ensure_ascii=False), json.dumps(남아야, ensure_ascii=False))
    걸린것 = [s for s, v in zip(빠져야, out["out_a"]) if not v]
    assert not 걸린것, "취소·반품 부류인데 안 빠진 상태: %s" % 걸린것
    샌것 = [s for s, v in zip(남아야, out["out_b"]) if v]
    assert not 샌것, "교환·철회·정상 주문인데 빠진 상태: %s (교환은 정산이 이뤄진다)" % 샌것


def test_판정은_주문상태_칸만_본다():
    """상품명에 '반품' 글자가 있어도 주문은 살아 있다."""
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify({
        상품명에반품: S.rowExcluded({'주문상태':'배송완료','상품명':'반품교환 세트 3종','옵션':'취소선 무늬'}),
        상태가반품:   S.rowExcluded({'주문상태':'반품완료','상품명':'정상 상품'})
      }));
    """)
    assert out["상품명에반품"] is False, "상품명의 '반품' 글자에 걸렸다 — 주문상태 칸만 봐야 한다"
    assert out["상태가반품"] is True


# ── ② 매출 · ③ 정산예정 — 값으로 ────────────────────────────────────────────
def test_매출과_정산예정이_값으로_맞는다():
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      const st=S.settleSummary(rows);
      console.log(JSON.stringify({
        field: S.SETTLE_FIELD,
        sales: S.salesOf(rows),
        settle: st.sum, counted: st.counted, blank: st.blank,
        // 취소 행 하나만 넣어 보면 배송비가 한 푼도 안 섞여야 한다
        cancel_only: S.settleSummary([rows.find(r=>r['주문상태']==='취소완료')]),
        cancel_only_sales: S.salesOf([rows.find(r=>r['주문상태']==='취소완료')])
      }));
    """, json.dumps(ROWS, ensure_ascii=False))
    assert out["field"] == "정산예정금(배송비포함)", (
        "정산예정이 상품분(`정산예정금액`)을 보고 있다 — 고객배송비가 통째로 빠진다")
    assert out["sales"] == 매출_정답, "매출 값이 어긋남: %s" % out["sales"]
    assert out["settle"] == 정산예정_정답, "정산예정 값이 어긋남: %s" % out["settle"]
    assert out["settle"] != 옛열_합, "옛 열(`정산예정금액`)로 되돌아갔다"
    assert out["blank"] == 정산예정_빈칸 and out["counted"] == 4, (
        "빈칸을 0 으로 삼키거나 세지 않았다 — 몇 건이 빠졌는지 화면이 말해야 한다")
    assert out["cancel_only"]["sum"] == 0 and out["cancel_only"]["counted"] == 0, (
        "취소완료 행의 N열(=0+배송비 2,500)이 정산예정에 섞였다")
    assert out["cancel_only_sales"] == 0, "취소완료 행이 매출에 섞였다"


# ── ⑥ 주문금액 · ⑦ 마켓 할인 — 값으로 ───────────────────────────────────────
def test_주문금액은_표의_주문금액_열을_그대로_더한다():
    """카드와 표가 같은 이름이면 같은 값이어야 한다(같은 이름 두 정의 = 모순)."""
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      const a=S.amountSummary(rows);
      console.log(JSON.stringify({
        sum:a.sum, counted:a.counted, blank:a.blank,
        // 취소 행도 들어가야 한다 — 주문금액은 「제외 없음」이 성격이다
        cancel_only: S.amountSummary([rows.find(r=>r['주문상태']==='취소완료')]).sum
      }));
    """, json.dumps(ROWS, ensure_ascii=False))
    assert out["sum"] == 주문금액_정답, "주문금액 값이 어긋남: %s" % out["sum"]
    assert out["sum"] != 옛_단가총합, (
        "옛 계산(`단가` 개당가 총합)으로 되돌아갔다 — 수량·배송비가 통째로 빠진다")
    assert out["blank"] == 주문금액_빈칸 and out["counted"] == len(ROWS) - 주문금액_빈칸, (
        "모르는 값을 0 으로 삼키거나 세지 않았다: %s" % out)
    assert out["cancel_only"] == 42500, (
        "주문금액에서 취소 행이 빠졌다 — 이 카드는 「제외 없음」이다")


def test_마켓할인은_제외후_정가와_실결제의_차다():
    """주문금액 − 매출 의 정체 = 마켓 할인. 취소·반품은 매출과 같은 모수로 뺀다."""
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      const d=S.discountSummary(rows);
      console.log(JSON.stringify({
        sum:d.sum, counted:d.counted, blank:d.blank,
        cancel_only: S.discountSummary([rows.find(r=>r['주문상태']==='취소완료')]).sum
      }));
    """, json.dumps(ROWS, ensure_ascii=False))
    assert out["sum"] == 할인_정답, "마켓 할인 값이 어긋남: %s" % out["sum"]
    assert out["blank"] == 할인_빈칸 and out["counted"] == 4, (
        "실결제·단가를 모르는 행을 0 으로 삼키거나 세지 않았다: %s" % out)
    assert out["cancel_only"] == 0, "취소완료 행이 마켓 할인에 섞였다"


def test_주문금액_마켓할인_매출이_한_줄로_이어진다():
    """제외 후 기준으로 주문금액 − 할인 = 매출. 세 카드가 안 맞으면 읽을 수 없다."""
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]).filter(r=>!S.rowExcluded(r));
      console.log(JSON.stringify({
        amt:S.amountSummary(rows).sum, disc:S.discountSummary(rows).sum,
        sales:S.salesOf(rows)}));
    """, json.dumps(ROWS, ensure_ascii=False))
    assert out["amt"] - out["disc"] == out["sales"], (
        "주문금액 − 마켓할인 ≠ 매출 (%s − %s ≠ %s)" % (out["amt"], out["disc"], out["sales"]))


# ── ④ 카드 6칸 + ⑤ 잔글씨(A안) — 만들어진 HTML 을 파서로 ────────────────────
class _KpiCards(HTMLParser):
    """kpiHtml() 결과 → [{l, v, cap:[줄,…]}, …]. (낱말 찾기 아님 — 구조를 본다.)"""

    def __init__(self):
        super().__init__()
        self.cards = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":                       # 빈 요소 — 층에 안 쌓는다
            if self._현재() == "cap" and self.cards:
                self.cards[-1]["cap"].append("")
            return
        cls = (dict(attrs).get("class") or "").split()
        kind = None
        if "kpi" in cls:
            self.cards.append({"l": "", "v": "", "cap": []})
            kind = "kpi"
        elif "l" in cls:
            kind = "l"
        elif "v" in cls:
            kind = "v"
        elif "cap" in cls:
            kind = "cap"
            self.cards[-1]["cap"].append("")
        self._stack.append(kind)

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if self._stack:
            self._stack.pop()

    def _현재(self):
        for k in reversed(self._stack):
            if k in ("l", "v", "cap"):
                return k
        return None

    def handle_data(self, data):
        t = data.strip()
        if not t or not self.cards:
            return
        칸 = self._현재()
        if 칸 == "l":
            self.cards[-1]["l"] += t
        elif 칸 == "v":
            self.cards[-1]["v"] += t
        elif 칸 == "cap":
            self.cards[-1]["cap"][-1] += t


def _cards(rows=None, wait=발송대기_수):
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify({html:S.kpiHtml(JSON.parse(process.argv[2]), Number(process.argv[3]))}));
    """, json.dumps(ROWS if rows is None else rows, ensure_ascii=False), str(wait))
    p = _KpiCards()
    p.feed(out["html"])
    return p.cards


def test_카드는_여섯칸이고_숫자가_맞는다():
    """마켓 할인은 주문금액과 매출 **사이** — 세 숫자를 눈으로 이어 읽는 자리다."""
    cards = _cards()
    assert [c["l"] for c in cards] == ["주문", "발송대기", "주문금액",
                                       "마켓 할인", "매출", "정산예정"], (
        "카드 구성·차례가 어긋남: %s" % [c["l"] for c in cards])
    값 = {c["l"]: c["v"] for c in cards}
    assert 값["주문"] == "%d건" % len(ROWS)
    assert 값["발송대기"] == "%d건" % 발송대기_수
    assert 값["주문금액"] == "40만", "주문금액 표시가 어긋남: %s" % 값["주문금액"]   # 396,000
    assert 값["마켓 할인"] == "−2만", "할인은 빼는 값이라 부호가 보여야 한다: %s" % 값["마켓 할인"]
    assert 값["매출"] == "15만", "매출 표시가 어긋남: %s" % 값["매출"]          # 149,500
    assert 값["정산예정"] == "14만", "정산예정 표시가 어긋남: %s" % 값["정산예정"]  # 135,500


def test_할인이_0이면_부호를_안_붙인다():
    """0 앞에 −를 붙이면 「−0만」이라 읽는 사람이 멈칫한다."""
    할인없음 = [r for r in ROWS if r.get("수량") != 2]
    값 = {c["l"]: c["v"] for c in _cards(할인없음)}
    assert 값["마켓 할인"] == "0만", "할인 0 인데 부호가 붙었다: %s" % 값["마켓 할인"]


def test_잔글씨_A안이_카드마다_붙는다():
    cap = {c["l"]: c["cap"] for c in _cards()}
    assert cap["매출"][:3] == ["취소·반품 제외", "교환 정산 포함", "실결제+배송비"], (
        "매출 잔글씨 3줄이 없다: %s" % cap["매출"])
    assert cap["정산예정"][:3] == ["취소·반품 제외", "교환 정산 포함", "배송비 포함"], (
        "정산예정 잔글씨 3줄이 없다: %s" % cap["정산예정"])
    assert cap["주문금액"][:2] == ["단가×수량+배송비", "제외 없음"], (
        "주문금액 카드가 무엇을 더한 값인지 안 밝힌다: %s" % cap["주문금액"])
    assert cap["마켓 할인"][:2] == ["취소·반품 제외", "정가−실결제"], (
        "마켓 할인 카드가 무엇의 차인지 안 밝힌다: %s" % cap["마켓 할인"])
    assert cap["주문"] == [] and cap["발송대기"] == [], "건수 카드엔 잔글씨가 없다"


def test_모르는_값은_카드마다_마지막줄로_말한다():
    """0 으로 삼키면 「할인이 늘어난 것」처럼 보인다 — 몇 건인지 화면이 말해야 한다."""
    cap = {c["l"]: c["cap"] for c in _cards()}
    assert len(cap["주문금액"]) == 3 and "1건" in cap["주문금액"][2], (
        "주문금액 빈칸 1건인데 카드가 아무 말도 안 한다: %s" % cap["주문금액"])
    assert len(cap["마켓 할인"]) == 3 and "1건" in cap["마켓 할인"][2], (
        "마켓 할인 빈칸 1건인데 카드가 아무 말도 안 한다: %s" % cap["마켓 할인"])
    빈칸없음 = [r for r in ROWS if r["주문금액"] != ""]
    cap2 = {c["l"]: c["cap"] for c in _cards(빈칸없음)}
    assert len(cap2["주문금액"]) == 2 and len(cap2["마켓 할인"]) == 2, (
        "빈칸이 없는데 군더더기 줄이 붙었다: %s" % cap2)


def test_정산예정_빈칸은_숨기지_않고_넷째줄로_말한다():
    """모르는 값을 0 으로 삼키지 않는다 — 몇 건이 빠졌는지 카드가 말한다."""
    cap = {c["l"]: c["cap"] for c in _cards()}
    assert len(cap["정산예정"]) == 4 and "1건" in cap["정산예정"][3], (
        "빈칸 1건이 있는데 카드가 아무 말도 안 한다: %s" % cap["정산예정"])
    빈칸없음 = [r for r in ROWS if r["정산예정금(배송비포함)"] != ""]
    cap2 = {c["l"]: c["cap"] for c in _cards(빈칸없음)}
    assert len(cap2["정산예정"]) == 3, "빈칸이 없는데 군더더기 줄이 붙었다"


# ── PC 화면 배선 ─────────────────────────────────────────────────────────────
def _pc():
    return PC_TPL.read_text(encoding="utf-8")


def _renderKPI_본문(글, 주석빼기=False):
    자리 = 글.index("function renderKPI(")
    끝 = 글.index("renderAcctChips();", 자리)
    본문 = 글[자리:끝]
    if 주석빼기:   # 「어떤 열을 더하나」는 **돌아가는 줄**로 본다(설명 주석에 속지 않게)
        본문 = "\n".join(re.sub(r"//.*$", "", 줄) for 줄 in 본문.splitlines())
    return 본문


def test_PC_화면이_공용_정의를_불러_쓴다():
    글 = _pc()
    assert re.search(r"<script src=\"\{\{ url_for\('static', filename='order_claim_scope\.js'\) \}\}\">", 글), \
        "PC 주문내역이 공용 정의 파일을 안 부른다"
    본문 = _renderKPI_본문(글)
    assert "MOUM_ORDER_SCOPE.kpiHtml(fr,wait)" in 본문.replace(" ", ""), \
        "renderKPI 가 공용 kpiHtml 을 안 쓴다"
    assert "정산예정금액" not in _renderKPI_본문(글, 주석빼기=True), (
        "renderKPI 가 아직 상품분(`정산예정금액`)을 더한다 — 배송비가 빠진다")


def test_PC_카드칸은_여섯이고_잔글씨_규칙이_있다():
    글 = _pc()
    m = re.search(r"\.o7 \.kpis\{([^}]*)\}", 글)
    assert m and "repeat(6,1fr)" in m.group(1).replace(" ", ""), \
        "카드 6칸 격자 규칙이 없다: %s" % (m.group(1) if m else None)
    # 6칸을 1180px 까지 그대로 두면 카드 하나가 190px 밑으로 눌려 잔글씨 3줄이 넘친다.
    assert re.search(r"@media\(max-width:1480px\)\{\.o7 \.kpis\{grid-template-columns:", 글), \
        "중간 폭(≤1480)에서 6칸이 접히는 규칙이 없다 — 잔글씨가 카드를 넘친다"
    c = re.search(r"\.o7 \.kpi \.cap\{([^}]*)\}", 글)
    assert c, "잔글씨(.cap) 규칙이 없다 — 3줄이 24px 숫자 크기로 나온다"
    px = re.search(r"font-size:\s*([\d.]+)px", c.group(1))
    assert px and float(px.group(1)) >= 11, "잔글씨가 11px 미만(폰 하한 위반)"
    # 좁은 창에서 5칸이 그대로면 카드가 눌린다 — 접히는 규칙이 있어야 한다
    assert re.search(r"@media\(max-width:768px\)\{\.o7 \.kpis\{grid-template-columns:", 글), \
        "폰 폭(≤768)에서 카드가 접히는 규칙이 없다"
