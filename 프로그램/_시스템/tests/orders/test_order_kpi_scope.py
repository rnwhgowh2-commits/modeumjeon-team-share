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
# 취소·반품 제외 후 주문금액(2026-08-08 A안 — 매출·할인과 같은 모수)
주문금액_제외후 = 12500 + 43000 + 30000 + 84000                                # = 169,500
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


def test_매출은_마켓부담_할인을_빼지_않는다():
    """매출 = 정가 + 배송비 − **판매자부담** 할인 (사장님 확정 2026-08-13).

    🔴 예전엔 `실결제금액 + 배송비` 를 그대로 매출로 썼다. 그런데 스스·롯데온·11번가는
      실결제에 **마켓이 부담한 할인까지** 빠져 있어 우리 매출이 실제보다 작았다
      (라이브 30일 실측: 롯데온 3,205,562원 과소 · 저장분 옛 달도 2,037,713원).
      마켓이 깎아 준 돈은 마켓이 내주고 우리는 정가대로 정산받으므로 빼면 안 된다.

    🔴 이 검사는 **`_매출기준액` 이 실린 행**으로 물어야 한다. 그 칸이 없는 자료로 물으면
      폴백(옛 규칙)만 타서, 규칙을 되돌려도 초록불이 유지된다(= 아무것도 안 보는 시험).
      아래 롯데온 행은 라이브 실측값이다 — 37,900 − 셀러 1,436 − 롯데 5,744 = 30,720.
    """
    rows = [
        # 마켓 부담이 있는 행 — 실결제(30,720)가 아니라 매출기준액(36,464)을 써야 한다
        {"판매처": "롯데온", "주문상태": "배송준비중", "단가": 37900, "수량": 1,
         "배송비": 0, "실결제금액": 30720, "총주문금액": 37900,
         "_dc_seller": "1436", "_dc_market": "5744", "_매출기준액": 36464},
        # 판매자할인을 모르는 행(11번가 배송중) — 칸이 없으니 옛 기준으로 물러난다
        {"판매처": "11번가", "주문상태": "배송중", "단가": 63100, "수량": 1,
         "배송비": 3000, "실결제금액": 59950, "총주문금액": 63100},
        # 취소완료 — 매출 0 (매출기준액도 0)
        {"판매처": "롯데온", "주문상태": "취소완료", "단가": 50000, "수량": 1,
         "배송비": 2500, "실결제금액": 50000, "_매출기준액": 0},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({
        sales: S.salesOf(rows),
        lo: S.saleBasisOf(rows[0]),
        e11: S.saleBasisOf(rows[1]),
        cancel: S.salesOf([rows[2]])
      }));
    """, json.dumps(rows, ensure_ascii=False))
    assert out["lo"] == 36464, (
        "롯데 부담 5,744 까지 매출에서 뺐다(= 매출 과소): %s" % out["lo"])
    assert out["e11"] == 62950, (
        "판매자할인을 모르는 행이 옛 기준(실결제+배송비)으로 안 물러났다: %s" % out["e11"])
    assert out["cancel"] == 0, "취소완료 행이 매출에 섞였다: %s" % out["cancel"]
    assert out["sales"] == 36464 + 62950, "합계가 행별 매출의 합이 아니다: %s" % out["sales"]


# ── ⑥ 주문금액 · ⑦ 마켓 할인 — 값으로 ───────────────────────────────────────
def test_주문금액은_표의_주문금액_열을_그대로_더한다():
    """카드와 표가 같은 이름이면 같은 값이어야 한다(같은 이름 두 정의 = 모순).

    🔴 2026-08-08 — 모수도 매출·할인과 같아졌다(취소·반품 제외).
    """
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      const a=S.amountSummary(rows);
      console.log(JSON.stringify({
        sum:a.sum, counted:a.counted, blank:a.blank,
        // 취소 행은 이제 빠진다 — 매출·할인과 같은 모수
        cancel_only: S.amountSummary([rows.find(r=>r['주문상태']==='취소완료')]).sum
      }));
    """, json.dumps(ROWS, ensure_ascii=False))
    assert out["sum"] == 주문금액_제외후, "주문금액 값이 어긋남: %s" % out["sum"]
    assert out["sum"] != 옛_단가총합, (
        "옛 계산(`단가` 개당가 총합)으로 되돌아갔다 — 수량·배송비가 통째로 빠진다")
    assert out["blank"] == 주문금액_빈칸 and out["counted"] == 4, (
        "모르는 값을 0 으로 삼키거나 세지 않았다: %s" % out)
    assert out["cancel_only"] == 0, (
        "취소완료 행이 주문금액에 남았다 — 매출·할인과 같은 모수여야 한다")


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


def test_옥션_G마켓도_확인불가에서_풀렸다():
    """🔴 2026-08-12 정정 — 옛 시험은 「두 마켓은 잴 수 없다」를 못 박고 있었다.

    그 결론은 `OrderAmount`·`AcntMoney` 만 보고 낸 오판이었다. **같은 주문조회 응답에**
    `SellerDiscountPrice`(판매자할인)·`DirectDiscountPrice`(사이트 지원)가 따로 있다
    (라이브 실증: 옥션 0/8,980 · G마켓 18/22행 셀러0·마켓47,640).
    실결제가 판매자할인을 뺀 값이 됐으므로 「정가−실결제」가 곧 우리 부담이다.
    """
    행 = [
        {"주문상태": "배송준비중", "판매처": "G마켓", "단가": 40800, "수량": 1, "배송비": 0,
         "실결제금액": 37800, "총주문금액": 40800, "주문금액": 40800, "상품명": "바지",
         "_dc_seller": "3000.0000", "_dc_market": "3910.0000"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      const d=S.discountSummary(JSON.parse(process.argv[2]));
      console.log(JSON.stringify({sum:d.sum, counted:d.counted, esm:d.esmUnknown}));
    """, json.dumps(행, ensure_ascii=False))
    assert out["esm"] == 0, "아직 확인 불가로 뺀다: %s" % out
    assert out["sum"] == 3000 and out["counted"] == 1, (
        "우리 부담 3,000 을 안 센다: %s" % out)


def test_옥션_G마켓에는_더이상_확인불가_문구가_안_붙는다():
    """갈래를 주는 마켓이 됐으니 「확인 불가」를 계속 적으면 그게 거짓말이다."""
    행 = [{"주문상태": "배송준비중", "판매처": "옥션", "단가": 50000, "수량": 1, "배송비": 0,
           "실결제금액": 50000, "총주문금액": 50000, "주문금액": 50000, "상품명": "가방",
           "_dc_seller": "0.0000", "_dc_market": "0.0000"}]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountCaps(S.discountSummary(JSON.parse(process.argv[2])))));
    """, json.dumps(행, ensure_ascii=False))
    assert not [줄 for 줄 in out if "확인 불가" in 줄], (
        "옥션이 아직 확인 불가로 적힌다: %s" % out)


def test_쿠팡_쿠폰은_실결제에_이미_빠져있고_두번_세지_않는다():
    """🔴 이중 계산 방지 — 이 시험이 지키는 사고.

    2026-08-06 사장님 확정으로 쿠팡 `실결제금액`이 판매자부담쿠폰을 **이미 뺀** 값이
    됐다(order_export 의 `_paid_raw - _sdc`). 그 전에는 쿠팡만 실결제가 할인 차감
    **전**이라 `discountSummary` 가 `_cp_seller_dc` 를 따로 더해 줬다.
    그 줄을 안 지우면 쿠팡 할인이 **정확히 두 배**로 잡힌다.
    """
    쿠팡 = [
        # 실결제 = 50,000 − 3,000(판매자부담쿠폰). 행에는 `_cp_seller_dc` 가 그대로 남아 있다
        # (정산 추정이 쓰는 값이라 안 지운다) — 그걸 또 더하면 6,000 이 된다.
        {"주문상태": "배송중", "판매처": "쿠팡", "단가": 50000, "수량": 1,
         "배송비": 0, "실결제금액": 47000, "주문금액": 50000, "_cp_seller_dc": 3000},
        # 쿠폰 없는 쿠팡 주문
        {"주문상태": "배송중", "판매처": "쿠팡", "단가": 20000, "수량": 1,
         "배송비": 0, "실결제금액": 20000, "주문금액": 20000, "_cp_seller_dc": 0},
        # 취소는 쿠폰이 있어도 빠진다(모수는 매출과 같다)
        {"주문상태": "취소완료", "판매처": "쿠팡", "단가": 90000, "수량": 1,
         "배송비": 0, "실결제금액": 83000, "주문금액": 90000, "_cp_seller_dc": 7000},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      const d=S.discountSummary(JSON.parse(process.argv[2]));
      console.log(JSON.stringify({sum:d.sum, counted:d.counted}));
    """, json.dumps(쿠팡, ensure_ascii=False))
    assert out["sum"] == 3000, (
        "쿠팡 할인이 %s — 6,000 이면 `_cp_seller_dc` 를 또 더해 두 번 센 것이다" % out["sum"])
    assert out["counted"] == 2, "취소 행이 섞였거나 정상 행을 놓쳤다: %s" % out


def test_쿠팡도_주문금액_할인_매출이_이어진다():
    """옛 규약에선 쿠팡만 이 항등식이 깨져 카드가 사유를 따로 밝혀야 했다.
    이제 쿠팡 매출에서도 쿠폰이 빠지므로 **전 마켓 한 줄로** 이어진다."""
    쿠팡 = [{"주문상태": "배송중", "판매처": "쿠팡", "단가": 50000, "수량": 1,
             "배송비": 0, "실결제금액": 47000, "주문금액": 50000, "_cp_seller_dc": 3000}]
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({amt:S.amountSummary(rows).sum,
        disc:S.discountSummary(rows).sum, sales:S.salesOf(rows)}));
    """, json.dumps(쿠팡, ensure_ascii=False))
    assert out["amt"] - out["disc"] == out["sales"], (
        "쿠팡에서 주문금액 − 할인 ≠ 매출 (%s − %s ≠ %s)"
        % (out["amt"], out["disc"], out["sales"]))
    # 더 이상 「쿠팡 쿠폰 …」 예외 안내가 붙지 않는다(붙으면 거짓말이 된다)
    caps = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountCaps(S.discountSummary(JSON.parse(process.argv[2])))));
    """, json.dumps(쿠팡, ensure_ascii=False))
    assert not [줄 for 줄 in caps if "쿠팡" in 줄], (
        "쿠폰이 매출에서 빠졌는데 「매출엔 안 빠짐」 안내가 남아 있다: %s" % caps)


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


def test_카드_숫자가_맞는다():
    """할인은 카드에서 빠지고 매출 잔글씨로 갔다(2026-08-08 A안)."""
    cards = _cards()
    값 = {c["l"]: c["v"] for c in cards}
    assert 값["주문"] == "%d건" % len(ROWS)
    assert 값["발송대기"] == "%d건" % 발송대기_수
    assert 값["주문금액"] == "17만", "주문금액 표시가 어긋남: %s" % 값["주문금액"]   # 169,500
    assert 값["매출"] == "15만", "매출 표시가 어긋남: %s" % 값["매출"]          # 149,500
    assert 값["정산예정"] == "14만", "정산예정 표시가 어긋남: %s" % 값["정산예정"]  # 135,500


def test_잔글씨_A안이_카드마다_붙는다():
    cap = {c["l"]: c["cap"] for c in _cards()}
    assert cap["매출"][:3] == ["취소·반품 제외", "교환 정산 포함", "실결제+배송비"], (
        "매출 잔글씨 3줄이 없다: %s" % cap["매출"])
    assert cap["정산예정"][:3] == ["취소·반품 제외", "교환 정산 포함", "배송비 포함"], (
        "정산예정 잔글씨 3줄이 없다: %s" % cap["정산예정"])
    assert cap["주문금액"][:2] == ["단가×수량+옵션+배송비", "취소·반품 제외"], (
        "주문금액 카드가 무엇을 더한 값인지 안 밝힌다: %s" % cap["주문금액"])
    assert cap["주문"] == [] and cap["발송대기"] == [], "건수 카드엔 잔글씨가 없다"


def test_모르는_값은_카드마다_마지막줄로_말한다():
    """0 으로 삼키면 「할인이 늘어난 것」처럼 보인다 — 몇 건인지 화면이 말해야 한다."""
    cap = {c["l"]: c["cap"] for c in _cards()}
    assert len(cap["주문금액"]) == 3 and "1건" in cap["주문금액"][2], (
        "주문금액 빈칸 1건인데 카드가 아무 말도 안 한다: %s" % cap["주문금액"])
    빈칸없음 = [r for r in ROWS if r["주문금액"] != ""]
    cap2 = {c["l"]: c["cap"] for c in _cards(빈칸없음)}
    assert len(cap2["주문금액"]) == 2, "빈칸이 없는데 군더더기 줄이 붙었다: %s" % cap2


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


def test_PC_카드칸은_다섯이고_잔글씨_규칙이_있다():
    글 = _pc()
    m = re.search(r"\.o7 \.kpis\{([^}]*)\}", 글)
    assert m and "repeat(5,1fr)" in m.group(1).replace(" ", ""), \
        "카드 5칸 격자 규칙이 없다: %s" % (m.group(1) if m else None)
    # 좁은 창에서 그대로 두면 카드가 눌려 잔글씨가 넘친다 — 접히는 규칙이 있어야 한다.
    assert re.search(r"@media\(max-width:1480px\)\{\.o7 \.kpis\{grid-template-columns:", 글), \
        "중간 폭(≤1480)에서 접히는 규칙이 없다 — 잔글씨가 카드를 넘친다"
    c = re.search(r"\.o7 \.kpi \.cap\{([^}]*)\}", 글)
    assert c, "잔글씨(.cap) 규칙이 없다 — 3줄이 24px 숫자 크기로 나온다"
    px = re.search(r"font-size:\s*([\d.]+)px", c.group(1))
    assert px and float(px.group(1)) >= 11, "잔글씨가 11px 미만(폰 하한 위반)"
    # 좁은 창에서 5칸이 그대로면 카드가 눌린다 — 접히는 규칙이 있어야 한다
    assert re.search(r"@media\(max-width:768px\)\{\.o7 \.kpis\{grid-template-columns:", 글), \
        "폰 폭(≤768)에서 카드가 접히는 규칙이 없다"


# ── ⑨ A안 — 할인은 카드에서 빼고 매출 밑 한 줄로 (2026-08-08 사장님 확정) ──────
def test_카드는_다시_다섯칸이고_할인은_매출_잔글씨로_간다():
    """🔴 왜 되돌리나 — 「−207만」이 **또 빼는 돈**으로 읽혔다(사장님 지적).

    매출은 이미 할인이 빠진 값이라, 할인을 옆 칸에 따로 세우면 두 번 빼는 것처럼 보인다.
    「마켓 할인 N만 반영됨」으로 **이미 반영됐음**을 말하는 자리로 옮긴다.
    """
    cards = _cards()
    assert [c["l"] for c in cards] == ["주문", "발송대기", "주문금액", "매출", "정산예정"], (
        "카드 구성이 어긋남: %s" % [c["l"] for c in cards])
    매출캡 = [c["cap"] for c in cards if c["l"] == "매출"][0]
    붙은줄 = [줄 for 줄 in 매출캡 if "반영" in 줄]
    assert 붙은줄, "매출 잔글씨에 할인 반영 줄이 없다: %s" % 매출캡
    assert "만" in 붙은줄[0], "할인 금액이 안 적혔다: %s" % 붙은줄


def test_주문금액도_취소_반품을_뺀다():
    """🔴 지금까지 주문금액만 「제외 없음」이라 세 숫자가 안 이어졌다(실측 3658−207≠2485).

    매출·할인과 같은 모수로 맞춘다. 「제외 없음」 잔글씨도 사라져야 한다.
    """
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({
        sum:S.amountSummary(rows).sum,
        cancel_only:S.amountSummary([rows.find(r=>r['주문상태']==='취소완료')]).sum}));
    """, json.dumps(ROWS, ensure_ascii=False))
    남는행합 = 12500 + 43000 + 30000 + 84000          # 취소·반품 뺀 주문금액 열 합
    assert out["sum"] == 남는행합, "주문금액이 아직 취소·반품을 포함한다: %s" % out["sum"]
    assert out["cancel_only"] == 0, "취소완료 행이 주문금액에 남았다"
    cap = {c["l"]: c["cap"] for c in _cards()}["주문금액"]
    assert "제외 없음" not in cap, "잔글씨가 아직 「제외 없음」이라 말한다: %s" % cap
    assert "취소·반품 제외" in cap[0] or "취소·반품 제외" in cap, (
        "무엇을 뺐는지 안 밝힌다: %s" % cap)


def test_마켓별_할인_내역을_돌려준다():
    """호버 창이 쓸 자료 — 판매처별 할인·건수 + 많이 깎인 주문 + 확인 불가 건수."""
    행 = [
        {"주문상태": "배송중", "판매처": "스마트스토어", "단가": 50000, "수량": 1, "배송비": 0,
         "실결제금액": 40000, "주문금액": 50000, "상품명": "코트"},
        {"주문상태": "배송중", "판매처": "스마트스토어", "단가": 20000, "수량": 1, "배송비": 0,
         "실결제금액": 18000, "주문금액": 20000, "상품명": "셔츠"},
        {"주문상태": "배송중", "판매처": "롯데온", "단가": 30000, "수량": 1, "배송비": 0,
         "실결제금액": 27000, "주문금액": 30000, "상품명": "바지"},
        {"주문상태": "배송중", "판매처": "11번가", "단가": 90000, "수량": 1, "배송비": 0,
         "실결제금액": 90000, "총주문금액": 90000, "주문금액": 90000, "상품명": "가방"},
        {"주문상태": "취소완료", "판매처": "스마트스토어", "단가": 70000, "수량": 1, "배송비": 0,
         "실결제금액": 60000, "주문금액": 70000, "상품명": "취소된것"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountByMarket(JSON.parse(process.argv[2]))));
    """, json.dumps(행, ensure_ascii=False))
    이름 = [m["market"] for m in out["markets"]]
    assert 이름 == ["스마트스토어", "롯데온"], "할인 많은 순서가 아니거나 마켓이 어긋남: %s" % 이름
    스스 = out["markets"][0]
    assert 스스["sum"] == 12000 and 스스["count"] == 2, 스스
    assert [t["name"] for t in 스스["top"]] == ["코트", "셔츠"], "많이 깎인 순서가 아니다: %s" % 스스
    assert out["esmUnknown"] == 0, "확인 불가 마켓은 이제 없다: %s" % out
    assert out["total"] == 15000, out
    assert not [m for m in out["markets"] if m["market"] == "11번가"], (
        "할인 0 인 마켓이 금액 표에 섞였다")


def test_PC_화면에_호버창_규칙이_배선돼_있다():
    """🔴 `hover-info-card` 규칙 1~5 — 하나라도 빠지면 창이 꺼지거나 잘린다.

    ① 창을 `document.body` 에 붙이고 `position:fixed` (표 스크롤에 안 잘리게)
    ② 마우스가 떠나도 250ms 기다린 뒤 닫기 (창으로 건너가는 도중 안 꺼지게)
    ③ 창에 들어오면 닫기 취소 · ④ 창에서 나가면 다시 예약
    ⑤ 앵커 오른쪽 끝 정렬 · 넘치면 위로 뒤집기 · 스크롤하면 닫기
    """
    글 = _pc()
    본문 = 글[글.index("function _dcShow"):글.index("function _dcShow") + 3000]
    assert "document.body.appendChild" in 글, "① 창을 body 에 안 붙였다(표에 잘린다)"
    assert re.search(r"\.dcpop\{[^}]*position:fixed", 글), "① position:fixed 가 아니다"
    assert "250" in 본문 or "_DC_CLOSE" in 글, "② 닫기 250ms 지연이 없다"
    assert "_dcPop.addEventListener('mouseenter'" in 글.replace('"', "'"),         "③ 창에 들어와도 닫기가 안 멈춘다"
    assert "_dcPop.addEventListener('mouseleave'" in 글.replace('"', "'"),         "④ 창에서 나갈 때 닫기 재예약이 없다"
    assert "innerHeight" in 본문 and "r.top" in 본문, "⑤ 화면 아래에서 위로 뒤집는 처리가 없다"
    assert re.search(r"addEventListener\('scroll',\s*_dcHide", 글.replace('"', "'")),         "스크롤하면 닫아야 한다(fixed 좌표가 낡는다)"


def test_PC_호버창은_공용_자료를_쓴다():
    """마켓별 내역을 화면이 다시 세면 카드 숫자와 갈린다 — 공용 함수 하나만 본다."""
    글 = _pc()
    assert "MOUM_ORDER_SCOPE.discountByMarket" in 글,         "화면이 마켓별 할인을 직접 세고 있다(공용 정의로 넘겨야 한다)"


# ── ⑩ 「누가 깎아 줬나」 — 셀러 : 마켓 부담 (2026-08-08 사장님 요청) ──────────
def test_마켓별_셀러부담율과_할인종류를_돌려준다():
    """🔴 「우리가 낸 할인」과 「마켓이 내준 할인」은 손익이 완전히 다르다.

    지도 확정 필드로 마켓마다 갈래가 온다:
      · 스스   총(_dc_total) − 셀러(_dc_seller) = 마켓  (네이버는 마켓분을 따로 안 준다)
      · 11번가 sellerDscPrc / tmallDscPrc 를 **둘 다** 준다
      · 쿠팡   즉시+다운로드 쿠폰(셀러) / coupangDiscount(쿠팡 부담)
      · 롯데온 sptDcPgmCmsnSum(셀러) / prSfcoShrAmtSum(롯데)
    """
    행 = [
        # 스스 — 카드 금액 10,000(정가−실결제) 중 셀러 6,000 → 우리 60%
        {"주문상태": "배송중", "판매처": "스마트스토어", "단가": 50000, "수량": 1, "배송비": 0,
         "실결제금액": 40000, "총주문금액": 50000, "주문금액": 50000, "상품명": "코트",
         "_dc_seller": 6000, "_dc_total": 10000,
         "_dc_kinds": {"즉시할인": 7000, "상품할인쿠폰": 3000, "복수구매할인": 0}},
        # 쿠팡 — 카드 금액 1,000 이 전액 셀러분 → 우리 100%
        #   (쿠팡지원 3,000 은 우리 실결제에 안 들어오므로 카드에도 없다)
        {"주문상태": "배송중", "판매처": "쿠팡", "단가": 30000, "수량": 1, "배송비": 0,
         "실결제금액": 29000, "총주문금액": 30000, "주문금액": 30000, "상품명": "신발",
         "_dc_seller": 1000, "_dc_market": 3000,
         "_dc_kinds": {"즉시할인쿠폰": 1000, "다운로드쿠폰": 0}},
        # 갈래를 안 주는 행 — 0% 로 적으면 「마켓이 다 냈다」는 거짓말이 된다
        {"주문상태": "배송중", "판매처": "11번가", "단가": 20000, "수량": 1, "배송비": 0,
         "실결제금액": 18000, "총주문금액": 20000, "주문금액": 20000, "상품명": "셔츠"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountByMarket(JSON.parse(process.argv[2]))));
    """, json.dumps(행, ensure_ascii=False))
    m = {x["market"]: x for x in out["markets"]}
    assert m["스마트스토어"]["sellerRate"] == 60, (
        "스스는 총−셀러로 마켓분을 구해야 한다: %s" % m["스마트스토어"])
    assert m["쿠팡"]["sellerRate"] == 100, (
        "쿠팡 카드 금액은 전액 셀러분인데 %s%% 로 나왔다" % m["쿠팡"]["sellerRate"])
    assert m["11번가"]["sellerRate"] is None, (
        "갈래를 모르는데 숫자를 지어냈다 — 0%%면 「마켓이 다 냈다」가 된다: %s" % m["11번가"])
    종류 = [k["name"] for k in m["스마트스토어"]["kindList"]]
    assert 종류 == ["즉시할인", "상품할인쿠폰"], (
        "할인 종류가 금액 큰 순이 아니거나 0원 항목이 섞였다: %s" % 종류)
    assert not m["11번가"]["kindList"], "종류를 모르는데 만들어 냈다"


def test_할인은_옵션추가금까지_넣은_정가로_잰다():
    """🔴 라이브 실측(2026-08-12) — 옵션가를 빼먹어 할인이 음수로 나오던 자리.

    스스 실결제에는 옵션가가 들어 있다. 정가를 `단가×수량`으로만 잡으면
    옵션가가 있는 주문은 할인이 **음수**가 된다(7일 스스 81행 중 16행이 그랬다).
    정가 = `총주문금액`(단가×수량 + 옵션추가금). 그러면 네이버가 준 실제 할인과 맞는다.
    """
    행 = [{"주문상태": "배송중", "판매처": "스마트스토어", "단가": 273000, "수량": 1,
           "옵션추가금": 65000, "배송비": 3000, "실결제금액": 298300,
           "총주문금액": 338000, "주문금액": 341000, "상품명": "옷"}]
    out = _run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({disc:S.discountSummary(rows).sum,
        amt:S.amountSummary(rows).sum, sales:S.salesOf(rows),
        byMk:S.discountByMarket(rows).total}));
    """, json.dumps(행, ensure_ascii=False))
    assert out["disc"] == 39700, (
        "옵션가를 빼먹었다(−25,300 이면 그것) — 네이버 실값은 39,700 이다: %s" % out["disc"])
    assert out["byMk"] == 39700, "판매처별 집계도 같은 정가를 써야 한다: %s" % out["byMk"]
    assert out["amt"] - out["disc"] == out["sales"], (
        "주문금액 − 할인 ≠ 매출: %s" % out)


def test_총주문금액이_없는_옛_저장분도_옵션가를_더한다():
    """옛 저장분엔 `총주문금액`이 없다 — 그때도 단가×수량+옵션추가금으로 만든다."""
    행 = [{"주문상태": "배송중", "판매처": "스마트스토어", "단가": 100000, "수량": 2,
           "옵션추가금": 30000, "배송비": 0, "실결제금액": 200000, "상품명": "옷"}]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify({disc:S.discountSummary(JSON.parse(process.argv[2])).sum}));
    """, json.dumps(행, ensure_ascii=False))
    assert out["disc"] == 30000, "옛 저장분에서 옵션가를 안 더했다: %s" % out["disc"]


def test_부담율은_화면에_뜬_금액_기준이다():
    """🔴 라이브 실측(2026-08-12) — 쿠팡이 「우리 부담 0%」로 떴다. 그 100원은 전액 우리 돈이다.

    마켓마다 `실결제금액`의 뜻이 달라 카드 금액에 담긴 것이 다르다:
      · 스스·11번가·롯데온 — 실결제가 **모든 할인**을 반영 → 카드 금액 = 셀러+마켓
      · 쿠팡             — 실결제가 **셀러 쿠폰만** 반영 → 카드 금액 = 셀러분만
    그래서 부담율을 「셀러/(셀러+마켓)」으로 재면 쿠팡이 0% 로 나온다(마켓분은 카드에 없는데
    분모에 들어가서). 부담율은 **화면에 뜬 그 금액**을 100 으로 놓고 재야 한다.
    """
    행 = [
        # 쿠팡 — 카드 금액 100(=셀러분). 쿠팡지원 50,000 은 우리 매출과 무관.
        {"주문상태": "배송중", "판매처": "쿠팡", "단가": 30000, "수량": 1, "배송비": 0,
         "실결제금액": 29900, "총주문금액": 30000, "주문금액": 30000, "상품명": "신발",
         "_dc_seller": 100, "_dc_market": 50000},
        # 11번가 — 카드 금액 2,000 이 전액 마켓 부담
        {"주문상태": "배송중", "판매처": "11번가", "단가": 20000, "수량": 1, "배송비": 0,
         "실결제금액": 18000, "총주문금액": 20000, "주문금액": 20000, "상품명": "셔츠",
         "_dc_seller": 0, "_dc_market": 2000},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountByMarket(JSON.parse(process.argv[2]))));
    """, json.dumps(행, ensure_ascii=False))
    m = {x["market"]: x for x in out["markets"]}
    assert m["쿠팡"]["sellerRate"] == 100, (
        "쿠팡 카드 금액은 전액 셀러 부담인데 %s%% 로 나왔다" % m["쿠팡"]["sellerRate"])
    assert m["11번가"]["sellerRate"] == 0, (
        "11번가는 전액 마켓 부담이어야 한다: %s" % m["11번가"]["sellerRate"])


def test_주문금액_잔글씨가_옵션추가금을_말한다():
    """설명이 「단가×수량+배송비」면 옵션가가 든 걸 숨기는 거짓 설명이 된다."""
    cap = {c["l"]: c["cap"] for c in _cards()}["주문금액"]
    assert "옵션" in cap[0], "잔글씨가 옵션추가금을 안 밝힌다: %s" % cap


def test_부담율은_얼마나_확인됐는지_같이_말한다():
    """🔴 라이브 실측(2026-08-12) — 11번가가 「우리 0% · 마켓 100%」로 떴는데
    실제로는 109행 중 **19행만** 갈래 값이 왔다(할인 569,904원 중 102,915원만 근거).

    아는 행만으로 비율을 내고 화면이 그걸 **전체인 양** 보여주면, 82%가 근거 없는 몫이
    된다. 얼마나 확인됐는지(knownSum)를 같이 돌려주고 화면이 밝혀야 한다.
    전 마켓 실측 커버리지 — 스스·롯데온·쿠팡 100% · 11번가 18%.
    """
    행 = [
        # 갈래를 아는 행 — 할인 1,000 이 전액 마켓 부담
        {"주문상태": "배송중", "판매처": "11번가", "단가": 10000, "수량": 1, "배송비": 0,
         "실결제금액": 9000, "총주문금액": 10000, "주문금액": 10000, "상품명": "A",
         "_dc_seller": 0, "_dc_market": 1000},
        # 갈래를 모르는 행 — 할인 4,000. 비율 계산에서 빠지지만 **총액엔 들어간다**
        {"주문상태": "배송중", "판매처": "11번가", "단가": 20000, "수량": 1, "배송비": 0,
         "실결제금액": 16000, "총주문금액": 20000, "주문금액": 20000, "상품명": "B"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify(S.discountByMarket(JSON.parse(process.argv[2]))));
    """, json.dumps(행, ensure_ascii=False))
    m = out["markets"][0]
    assert m["sum"] == 5000, "총 할인은 모르는 행까지 더해야 한다: %s" % m["sum"]
    assert m["knownSum"] == 1000, (
        "갈래를 확인한 금액을 안 돌려준다 — 화면이 「얼마나 근거 있나」를 못 말한다: %s" % m)
    assert m["sellerRate"] == 0, "확인된 몫 기준 비율: %s" % m["sellerRate"]


def test_확인_못한_금액이_있으면_창이_그걸_밝힌다():
    """100% 확인된 마켓엔 군더더기를 안 붙인다 — 있을 때만 말한다."""
    부분 = [
        {"주문상태": "배송중", "판매처": "11번가", "단가": 10000, "수량": 1, "배송비": 0,
         "실결제금액": 9000, "총주문금액": 10000, "주문금액": 10000, "상품명": "A",
         "_dc_seller": 0, "_dc_market": 1000},
        {"주문상태": "배송중", "판매처": "11번가", "단가": 20000, "수량": 1, "배송비": 0,
         "실결제금액": 16000, "총주문금액": 20000, "주문금액": 20000, "상품명": "B"},
    ]
    전부 = [부분[0]]
    out = _run(r"""
      const S=require(process.argv[1]);
      const [a,b]=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({부분:S.burdenLine(S.discountByMarket(a).markets[0]),
                                  전부:S.burdenLine(S.discountByMarket(b).markets[0])}));
    """, json.dumps([부분, 전부], ensure_ascii=False))
    assert "확인" in out["부분"] and "4,000" in out["부분"], (
        "확인 못 한 4,000원을 안 밝힌다: %s" % out["부분"])
    assert "확인 불가" not in out["전부"], "전부 확인됐는데 군더더기가 붙었다: %s" % out["전부"]


def test_옥션_G마켓도_이제_할인을_잰다():
    """🔴 「확인 불가」를 푼다 — 두 마켓 다 주문 API 가 갈래를 준다(2026-08-12 라이브 실증).

    실결제가 판매자할인을 뺀 값이 됐으므로 「정가−실결제」가 곧 우리 부담이다.
    마켓이 따로 부담한 몫은 우리 매출과 무관해 카드 금액엔 없다 — 그래서 **금액으로** 밝힌다
    (비율만 쓰면 「마켓이 8,980원 깎아줬다」는 사실이 화면에서 사라진다).
    """
    행 = [
        # 옥션 — 우리 부담 0 · 옥션 부담 8,980 (실결제 = 원금 그대로)
        {"주문상태": "배송완료", "판매처": "옥션", "단가": 112200, "수량": 1, "배송비": 0,
         "실결제금액": 112200, "총주문금액": 112200, "주문금액": 112200, "상품명": "셔츠",
         "_dc_seller": "0.0000", "_dc_market": "8980.0000"},
        # G마켓 — 우리 부담 3,000(실결제에서 빠짐) · G마켓 부담 3,910
        {"주문상태": "배송준비중", "판매처": "G마켓", "단가": 40800, "수량": 1, "배송비": 0,
         "실결제금액": 37800, "총주문금액": 40800, "주문금액": 40800, "상품명": "바지",
         "_dc_seller": "3000.0000", "_dc_market": "3910.0000"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      const d=S.discountByMarket(JSON.parse(process.argv[2]));
      console.log(JSON.stringify({esm:d.esmUnknown, total:d.total,
        m:d.markets.map(x=>({mk:x.market,sum:x.sum,line:S.burdenLine(x)}))}));
    """, json.dumps(행, ensure_ascii=False))
    assert out["esm"] == 0, "옥션·G마켓이 아직 확인 불가로 빠진다: %s" % out["esm"]
    m = {x["mk"]: x for x in out["m"]}
    assert m["G마켓"]["sum"] == 3000, "우리 부담 3,000 이 카드 금액이어야 한다: %s" % m["G마켓"]
    assert m["옥션"]["sum"] == 0, "옥션은 우리 부담이 0 이다: %s" % m["옥션"]
    assert "8,980" in m["옥션"]["line"], (
        "마켓이 따로 부담한 8,980원이 화면에서 사라졌다: %s" % m["옥션"]["line"])
    assert "3,910" in m["G마켓"]["line"], "G마켓 부담 3,910원이 안 보인다: %s" % m["G마켓"]["line"]

def test_우리부담_0원과_모름을_갈라_말한다():
    """🔴 옥션은 SellerDiscountPrice=0 · DirectDiscountPrice=8,980 이 실제로 온다.
    우리가 낸 게 0원인 것과 「누가 냈는지 모른다」는 완전히 다른 말이다.
    옛 문구는 둘 다 「확인 불가」로 뭉개, 아는 사실을 모른다고 화면이 거짓말했다."""
    행 = [
        {"주문상태": "배송완료", "판매처": "옥션", "단가": 112200, "수량": 1, "배송비": 0,
         "실결제금액": 112200, "총주문금액": 112200, "주문금액": 112200, "상품명": "셔츠",
         "_dc_seller": "0.0000", "_dc_market": "8980.0000"},
    ]
    out = _run(r"""
      const S=require(process.argv[1]);
      const d=S.discountByMarket(JSON.parse(process.argv[2]));
      console.log(JSON.stringify({줄: d.markets.map(m=>S.burdenLine(m))}));
    """, json.dumps(행, ensure_ascii=False))
    줄 = out["줄"][0]
    assert "확인 불가" not in 줄, "갈래를 아는데 「확인 불가」로 뭉갬: %s" % 줄
    assert "우리 부담 없음" in 줄, "우리 부담 0원을 안 말함: %s" % 줄
    assert "8,980" in 줄, "마켓이 따로 낸 금액이 사라짐: %s" % 줄
