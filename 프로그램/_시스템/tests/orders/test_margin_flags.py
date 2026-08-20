# -*- coding: utf-8 -*-
"""주문 내역 가로 탭 2단계 — 옮긴 판정이 **원본과 같은 답**을 내는가.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §6.1.

🔴 이 파일의 핵심은 ①번 **대조 시험**이다. `lemouton/orders/margin_flags.py` 는
   마진 계산기의 규칙을 옮긴 것이라, 원본(JS)을 Node 로 **실제로 돌려** 같은 입력에
   같은 분류가 나오는지 맞춰 본다. 베껴 쓴 상수를 다시 베껴 확인하는 자체 시험이
   아니다 — 원본이 바뀌면 여기서 깨진다.

   · 원본 ①  `webapp/static/margin_rules.js`            (모듈 — 그대로 require)
   · 원본 ②  `webapp/templates/orders/margin_embed.html` (템플릿 — 함수 원문을 떼어 실행)

나머지 ②~⑤ 는 2단계가 지켜야 할 약속이다:
   ② 매입가를 모르면 이상마진이 아니다(「매입가 미입력」으로 간다)
   ③ 예상가로 판정한 건수는 따로 센다
   ④ 탭 건수 집계
   ⑤ 탭 전환이 서버 재조회를 유발하지 않는다(프런트 — Node 하네스 위임)
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from lemouton.orders import margin_flags as MF

ROOT = pathlib.Path(__file__).resolve().parents[2]
MR_JS = ROOT / "webapp" / "static" / "margin_rules.js"
EMBED = ROOT / "webapp" / "templates" / "orders" / "margin_embed.html"
NO_REFETCH = ROOT / "tests" / "js" / "test_orders_margin_tabs_no_refetch.mjs"

_HAS_NODE = shutil.which("node") is not None


# ══════════════════════════════════════════════════════════════════
#  ① 대조 — 원본 JS 를 Node 로 돌려 같은 입력 → 같은 분류인지
# ══════════════════════════════════════════════════════════════════

# 원본과 이식본을 같이 태울 입력. 경계값(40% · 5,000원 · 매입 3배 · 500,000원)과
# 「쉼표 섞인 문자열 · 빈칸 · None」처럼 실제 표에서 오는 지저분한 값을 일부러 넣는다.
PARITY_ROWS = [
    # 정산0 + 매입有 → 손실(블랙스팟)
    {"정산예상금액": 0, "구매가격": 50000, "단가": 60000, "수량_매출": 1},
    # 정산有 + 매입0 → 고마진
    {"정산예상금액": 70000, "구매가격": 0, "단가": 80000, "수량_매출": 1},
    # 평범
    {"정산예상금액": 70000, "구매가격": 50000, "단가": 80000, "수량_매출": 1,
     "실결제금액": 80000, "배송비": 3000},
    # 정산0 + 매입0 → 계산 불가
    {"정산예상금액": 0, "구매가격": 0, "단가": 0, "수량_매출": 1},
    # 키워드 블랙스팟(메모) — 정산0
    {"정산예상금액": 0, "구매가격": 0, "간단메모": "블랙 처리건", "단가": 10000, "수량_매출": 1},
    # 키워드 블랙스팟(더망고 상태) — 정산0
    {"정산예상금액": 0, "구매가격": 0, "더망고주문상태 (사용자 연동)": "오류입고",
     "단가": 10000, "수량_매출": 1},
    # 키워드가 있어도 정산이 잡혔으면 손실 아님
    {"정산예상금액": 90000, "구매가격": 50000, "간단메모": "블랙", "단가": 100000, "수량_매출": 1},
    # 수기 제외
    {"정산예상금액": 0, "구매가격": 50000, "_excluded": True, "단가": 60000, "수량_매출": 1},
    # 주문미이행 + 매입흔적 없음
    {"정산예상금액": 0, "구매가격": 50000, "_주문미이행": True, "단가": 60000, "수량_매출": 1},
    # 주문미이행 + 매입흔적 있음 → 일반 분류
    {"정산예상금액": 0, "구매가격": 50000, "_주문미이행": True, "_매입흔적": True,
     "단가": 60000, "수량_매출": 1},
    # 고마진 경계 — 마진율 정확히 40% · 순마진 정확히 5,000원 (포함되어야 함)
    {"정산예상금액": 9000, "구매가격": 4000, "단가": 12500, "수량_매출": 1},
    # 고마진 경계 바로 아래 — 순마진 4,999원
    {"정산예상금액": 8999, "구매가격": 4000, "단가": 12500, "수량_매출": 1},
    # 마진율 기준이 실결제+배송비로 바뀌는 경우
    {"정산예상금액": 30000, "구매가격": 10000, "단가": 100, "수량_매출": 1,
     "실결제금액": 40000, "배송비": 3000},
    # 이상가 — 매입가가 판매가의 3배 초과
    {"정산예상금액": 10000, "구매가격": 40000, "단가": 10000, "수량_매출": 1},
    # 이상가 — 매입가 500,000원 초과
    {"정산예상금액": 900000, "구매가격": 600000, "단가": 1000000, "수량_매출": 1},
    # 이상가 경계 — 정확히 500,000원(초과 아님)
    {"정산예상금액": 900000, "구매가격": 500000, "단가": 1000000, "수량_매출": 1},
    # 쉼표 섞인 문자열 / 빈칸 / None — 표에서 실제로 이렇게 온다
    {"정산예상금액": "70,000", "구매가격": "50,000", "단가": "80,000", "수량_매출": "1"},
    {"정산예상금액": "", "구매가격": "", "단가": "", "수량_매출": ""},
    {"정산예상금액": None, "구매가격": None, "단가": None, "수량_매출": None},
    # 수량 2벌
    {"정산예상금액": 140000, "구매가격": 100000, "단가": 80000, "수량_매출": 2},
    # 마이너스 마진(고마진 아님) → 이상마진
    {"정산예상금액": 30000, "구매가격": 45000, "단가": 50000, "수량_매출": 1,
     "실결제금액": 50000, "배송비": 0},
]

_NODE_SCRIPT = r"""
// ⚠️ 원본이 기대하는 최소 환경을 **require 보다 먼저** 깐다.
//   `node -e` 의 최상단 const 는 전역 렉시컬 바인딩이라, 나중에 선언하면
//   margin_rules.js 안의 `typeof window` 가 TDZ 로 터진다(실측).
//   임계값은 margin_embed.html:1735 의 기본값 그대로.
globalThis.window = { userSettings: { highMarginRate: 40, highMarginAmount: 5000,
                                      saleEff1: 1000, marginEff1: 100 } };
const fs = require('fs');
// `node -e` 는 스크립트 뒤 인자가 argv[1] 부터다(선례: tests/margin/test_margin_rules_js.py).
const MR = require(process.argv[1]);
const SRC = fs.readFileSync(process.argv[2], 'utf8');
const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

/** margin_embed.html 에서 함수 원문을 중괄호 짝으로 떼어 온다(베껴 쓰기 금지). */
function extract(name) {
  const m = new RegExp('^\\s*function\\s+' + name + '\\s*\\(', 'm').exec(SRC);
  if (!m) throw new Error(name + '() 이(가) margin_embed.html 에 없습니다');
  let i = SRC.indexOf('{', m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j += 1) {
    if (SRC[j] === '{') depth += 1;
    else if (SRC[j] === '}') { depth -= 1; if (depth === 0) return SRC.slice(m.index, j + 1); }
  }
  throw new Error(name + '() 중괄호 짝이 안 맞습니다');
}

eval(extract('isHighMargin'));
eval(extract('isAbnormalMarginRow'));
eval(extract('recomputeRow'));
// renderAbnormalBanner 의 거르개(화면 「이상마진 N건」) — 원문에서 조건만 뽑아 쓴다.
const bannerSrc = extract('renderAbnormalBanner');
if (!/_excluded/.test(bannerSrc) || !/이상가/.test(bannerSrc))
  throw new Error('renderAbnormalBanner 의 거르개가 바뀌었습니다 — 대조 시험을 고치세요');
function bannerKeeps(r) {
  if (r['_주문미이행'] && !r['_매입흔적']) return false;
  return !r._excluded && !r['이상가'] && isAbnormalMarginRow(r);
}

const out = rows.map(function (r) {
  recomputeRow(r);
  return {
    cls: MR.classify(r), loss: MR.isLossRow(r), high: MR.isHighMarginRow(r),
    unc: MR.isMarginUncomputable(r), kw: MR.isKeywordBlackspot(r),
    margin: MR.rowMargin(r), abn: isAbnormalMarginRow(r), banner: bannerKeeps(r),
    net: r['순마진'], rate: r['마진율'], sale: r['판매가'], bad: !!r['이상가'],
  };
});
console.log(JSON.stringify(out));
"""


def _python_side(rows) -> list:
    out = []
    for src in rows:
        r = dict(src)
        MF.recompute_row(r)
        out.append({
            "cls": MF.classify(r), "loss": MF.is_loss_row(r),
            "high": MF.is_high_margin_row(r), "unc": MF.is_margin_uncomputable(r),
            "kw": MF.is_keyword_blackspot(r), "margin": MF.row_margin(r),
            "abn": MF.is_abnormal_margin_row(r),
            "banner": bool(MF.abnormal_margin_rows([r])),
            "net": r["순마진"], "rate": r["마진율"], "sale": r["판매가"],
            "bad": bool(r["이상가"]),
        })
    return out


@pytest.mark.skipif(not _HAS_NODE,
                    reason="node 가 없어 원본 JS 대조를 못 돌렸습니다 "
                           "(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).")
def test_옮긴_판정이_원본_JS_와_같은_결과를_낸다(tmp_path):
    """① 대조 — 원본(margin_rules.js + margin_embed.html)을 Node 로 실제 실행해 맞춘다."""
    payload = tmp_path / "rows.json"
    payload.write_text(json.dumps(PARITY_ROWS, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(
        ["node", "-e", _NODE_SCRIPT, str(MR_JS), str(EMBED), str(payload)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, f"원본 JS 실행 실패:\n{r.stdout}\n{r.stderr}"
    original = json.loads(r.stdout.strip().splitlines()[-1])
    ported = _python_side(PARITY_ROWS)

    assert len(original) == len(ported) == len(PARITY_ROWS)
    diffs = []
    for i, (a, b) in enumerate(zip(original, ported)):
        for k in a:
            av, bv = a[k], b[k]
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                same = abs(float(av) - float(bv)) < 1e-9
            else:
                same = av == bv
            if not same:
                diffs.append(f"  행{i} {k}: 원본={av!r} 이식={bv!r}  ← {PARITY_ROWS[i]}")
    assert not diffs, ("옮긴 판정이 원본과 갈렸습니다 — 임계값을 새로 정하지 말고 "
                       "원본을 따라 고치세요:\n" + "\n".join(diffs))


def test_대조_대상_원본_파일이_실제로_있다():
    """node 가 없어 스킵되더라도 원본이 증발한 것은 알아야 한다."""
    assert MR_JS.exists(), MR_JS
    assert EMBED.exists(), EMBED


def test_임계값을_새로_정하지_않았다():
    """이식본의 상수가 원본 문자열과 그대로 맞는지(값을 지어내지 않았다는 증거)."""
    embed = EMBED.read_text(encoding="utf-8")
    assert f"highMarginRate:{MF.HIGH_MARGIN_RATE}" in embed
    assert f"highMarginAmount:{MF.HIGH_MARGIN_AMOUNT}" in embed
    assert f"매입가 > 500000" in embed and MF.ABNORMAL_PRICE_ABS == 500000
    mr = MR_JS.read_text(encoding="utf-8")
    for kw in MF.BLACKSPOT_MEMO_KW + MF.BLACKSPOT_MANGO_KW:
        assert f"'{kw}'" in mr


# ══════════════════════════════════════════════════════════════════
#  ② 매입가를 모르면 이상마진이 아니다 → 「매입가 미입력」으로
# ══════════════════════════════════════════════════════════════════

def _order(uid="u1", **kw):
    row = {"_line_uid": uid, "정산예정금(배송비포함)": 30000, "단가": 50000,
           "수량": 1, "실결제금액": 50000, "배송비": 0, "주문상태": "배송완료"}
    row.update(kw)
    return row


def test_매입가를_모르면_이상마진이_아니라_미입력이다():
    """🔴 추측 금지 — 매입가가 「확인 불가」면 판정 자체를 안 한다."""
    f = MF.flag_order_row(_order(), {"price": None, "tier": None})
    assert f["nopp"] is True, "실매입가가 없으니 「매입가 미입력」 탭에 들어가야 한다"
    assert f["judged"] is False
    assert f["abnormal"] is False and f["blackspot"] is False
    assert "매입가" in f["reason"]


def test_정산예정금을_못_읽으면_블랙스팟으로_둔갑하지_않는다():
    """🔴 0 으로 채우면 멀쩡한 주문이 「돈 못 받음」이 된다."""
    f = MF.flag_order_row(_order(**{"정산예정금(배송비포함)": ""}),
                          {"price": 20000, "tier": "real"})
    assert f["judged"] is False and f["blackspot"] is False
    assert "정산예정금" in f["reason"]


def test_취소_반품은_판정에서_뺀다():
    f = MF.flag_order_row(_order(주문상태="취소완료", **{"정산예정금(배송비포함)": 0}),
                          {"price": 30000, "tier": "real"})
    assert f["judged"] is False and f["blackspot"] is False
    # 「취소철회」는 되돌린 클레임이라 살아 있다(order_claim_scope.js 규칙 그대로)
    alive = MF.flag_order_row(_order(주문상태="취소철회"), {"price": 20000, "tier": "real"})
    assert alive["judged"] is True


def test_실매입가가_있으면_미입력이_아니다():
    f = MF.flag_order_row(_order(), {"price": 20000, "tier": "real"})
    assert f["nopp"] is False and f["basis"] == "real" and f["judged"] is True


def test_예상가만_있으면_값이_있어도_미입력이다():
    """설계서 §4 — 예상가는 실매입가가 아니다. 「채워야 할 것」에 남는다."""
    f = MF.flag_order_row(_order(), {"price": 20000, "tier": "estimate"})
    assert f["nopp"] is True and f["basis"] == "estimate" and f["judged"] is True


def test_블랙스팟은_정산0에_매입만_있는_줄이다():
    f = MF.flag_order_row(_order(**{"정산예정금(배송비포함)": 0}),
                          {"price": 45000, "tier": "real"})
    assert f["blackspot"] is True
    # 매입가가 없으면(확인 불가) 블랙스팟이라 말하지 않는다
    g = MF.flag_order_row(_order(**{"정산예정금(배송비포함)": 0}),
                          {"price": None, "tier": None})
    assert g["blackspot"] is False


# ══════════════════════════════════════════════════════════════════
#  ③ 예상가 기반 건수를 따로 센다 (설계서 §4)
# ══════════════════════════════════════════════════════════════════

def test_예상가_기반_건수를_실적과_섞지_않는다():
    rows = [_order("real-loss", **{"정산예정금(배송비포함)": 0}),
            _order("est-loss", **{"정산예정금(배송비포함)": 0}),
            _order("est-loss2", **{"정산예정금(배송비포함)": 0})]
    prices = {"real-loss": {"price": 40000, "tier": "real"},
              "est-loss": {"price": 40000, "tier": "estimate"},
              "est-loss2": {"price": 40000, "tier": "estimate"}}
    s = MF.summarize_tabs(rows, prices)
    assert s["abnormal"] == 3, "셋 다 마이너스라 이상마진이다"
    assert s["abnormal_estimate"] == 2, "그중 둘은 예상가로 판정한 것 — 따로 센다"
    assert s["abnormal_real"] == 1
    assert s["blackspot"] == 3 and s["blackspot_estimate"] == 2
    assert s["nopp"] == 2, "예상가 두 줄은 실매입가가 없으니 미입력이다"


def test_사입가는_예상가로_세지_않는다():
    """§4 — 사입가(stock)는 실측 이동평균이라 「예상」 표를 달지 않는다."""
    rows = [_order("s1", **{"정산예정금(배송비포함)": 0})]
    s = MF.summarize_tabs(rows, {"s1": {"price": 40000, "tier": "stock"}})
    assert s["abnormal"] == 1 and s["abnormal_estimate"] == 0
    assert s["nopp"] == 1, "그래도 실매입가는 아니라 미입력에는 남는다"


# ══════════════════════════════════════════════════════════════════
#  ④ 탭 건수 집계
# ══════════════════════════════════════════════════════════════════

def test_탭_건수_집계():
    rows = [
        _order("ok", **{"정산예정금(배송비포함)": 30000}),          # 평범
        _order("loss", **{"정산예정금(배송비포함)": 0}),            # 블랙스팟(=이상마진)
        _order("high", **{"정산예정금(배송비포함)": 30000}),        # 고마진(매입 0 취급 불가 → 아래에서 처리)
        _order("nopp", **{"정산예정금(배송비포함)": 30000}),        # 매입가 확인 불가
        _order("cancel", 주문상태="취소완료", **{"정산예정금(배송비포함)": 0}),
    ]
    prices = {
        "ok": {"price": 20000, "tier": "real"},
        "loss": {"price": 45000, "tier": "real"},
        "high": {"price": 100, "tier": "real"},     # 마진율 59.8% · 순마진 29,900 → 고마진
        "nopp": {"price": None, "tier": None},
        "cancel": {"price": 30000, "tier": "real"},
    }
    s = MF.summarize_tabs(rows, prices)
    assert s["total"] == 5
    assert s["blackspot"] == 1                      # loss 하나
    assert s["abnormal"] == 2                       # loss(마이너스) + high(고마진)
    assert s["nopp"] == 1                           # nopp 하나 (나머지는 실매입가)
    assert s["unjudged"] == 2                       # nopp(매입가 없음) + cancel(취소)


def test_flag_rows_는_line_uid_없는_줄을_버린다():
    """🔴 주문번호로 묶으면 다품목 주문이 서로를 덮는다 — 열쇠는 line_uid 뿐."""
    out = MF.flag_rows([{"정산예정금(배송비포함)": 0}], {})
    assert out == {}


# ══════════════════════════════════════════════════════════════════
#  ⑤ 탭 전환이 서버 재조회를 유발하지 않는다 (프런트)
# ══════════════════════════════════════════════════════════════════

def test_탭_전환_무재조회_고정_파일이_실제로_있다():
    assert NO_REFETCH.exists(), NO_REFETCH


@pytest.mark.skipif(not _HAS_NODE,
                    reason="node 가 없어 탭 전환 배선을 못 돌렸습니다 "
                           "(설치하면 자동으로 돕니다 — 조용히 통과시키지 않습니다).")
def test_탭을_눌러도_서버를_다시_부르지_않는다():
    r = subprocess.run(["node", str(NO_REFETCH)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, f"탭 전환 배선 고정 실패:\n{r.stdout}\n{r.stderr}"


# ══════════════════════════════════════════════════════════════════
#  마진 계산기는 손대지 않았다 (사장님 규칙 1)
# ══════════════════════════════════════════════════════════════════

def test_마진_계산기_규칙_원본은_읽기만_한다():
    """이식본이 원본을 import·수정하지 않고, 규칙은 한 곳(margin_flags)에만 있다."""
    src = (ROOT / "lemouton" / "orders" / "margin_flags.py").read_text(encoding="utf-8")
    assert "margin_rules.js" in src, "어디서 옮겨 왔는지 파일에 적혀 있어야 한다"
    assert "margin_embed.html" in src
    orders_route = (ROOT / "webapp" / "routes" / "orders.py").read_text(encoding="utf-8")
    # 라우트가 임계값을 다시 쓰지 않았는지 — 판정은 margin_flags 호출만
    assert "margin_flags" in orders_route
    for banned in ("highMarginRate", "500000", "40 <=", "정산예상금액"):
        assert banned not in orders_route, \
            f"주문 라우트가 판정을 다시 구현했습니다({banned}) — margin_flags 로 옮기세요"
