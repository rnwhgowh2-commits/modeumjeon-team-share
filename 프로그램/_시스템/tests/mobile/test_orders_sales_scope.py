# -*- coding: utf-8 -*-
"""폰 주문(/mobile/orders) 매출 — PC 주문내역과 **같은 뜻**인지 값으로 못 박는다.

사장님 확정(2026-08-06): 제외 = 취소·반품 클레임, 교환은 포함(정산이 이뤄진다).

무엇이 문제였나
    폰은 `/취소완료|취소요청/` 만 뺐다 — **반품이 매출에 그대로 섞여** 있었고,
    PC 주문내역은 아무것도 안 뺐다. 같은 이름(매출)의 숫자가 두 답을 냈다.
    이제 두 화면이 `webapp/static/order_claim_scope.js` 하나만 쓴다.

★ 낱말 검사 금지 — 정의는 node 로 **실행해 값으로**, 화면은 **파서로** 본다.
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
TPL = _시스템 / "webapp" / "templates" / "mobile" / "orders.html"

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _tpl():
    return TPL.read_text(encoding="utf-8")


def _html(client):
    r = client.get("/mobile/orders")
    assert r.status_code == 200, f"폰 주문 화면이 안 열린다(status={r.status_code})"
    return r.get_data(as_text=True)


def _node_run(script, *args):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node 없음")
    r = subprocess.run([exe, "-e", script, str(SCOPE_JS)] + list(args),
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ── ① 폰 매출이 취소·반품을 빼고 교환은 남기는가(값) ─────────────────────────
def test_폰_매출은_취소_반품을_빼고_교환은_남긴다():
    rows = [
        {"주문상태": "배송완료", "실결제금액": 10000, "배송비": 2500},
        {"주문상태": "교환완료", "실결제금액": 20000, "배송비": 3000},   # 남는다
        {"주문상태": "교환요청", "실결제금액": 30000, "배송비": 0},      # 남는다
        {"주문상태": "취소철회", "실결제금액": 40000, "배송비": 0},      # 되돌린 취소 = 남는다
        {"주문상태": "취소완료", "실결제금액": 50000, "배송비": 2500},   # 빠진다
        {"주문상태": "취소요청", "실결제금액": 60000, "배송비": 0},      # 빠진다
        {"주문상태": "반품완료", "실결제금액": 70000, "배송비": 3000},   # 빠진다(옛 폰은 셌다)
        {"주문상태": "회수지시", "실결제금액": 80000, "배송비": 0},      # 빠진다
    ]
    # (10000+2500)+(20000+3000)+30000+40000
    정답 = 105500
    옛_폰_값 = 정답 + (70000 + 3000) + 80000        # 반품·회수를 안 뺐을 때
    out = _node_run(r"""
      const S=require(process.argv[1]);
      const rows=JSON.parse(process.argv[2]);
      console.log(JSON.stringify({sales:S.salesOf(rows)}));
    """, json.dumps(rows, ensure_ascii=False))
    assert out["sales"] == 정답, "폰 매출이 어긋남: %s" % out["sales"]
    assert out["sales"] != 옛_폰_값, "반품·회수가 아직 매출에 섞여 있다"


# ── ② 폰 화면 배선 — 자기 정규식을 다시 짓지 않는다 ─────────────────────────
def test_폰이_PC와_같은_정의_파일을_부른다(client):
    글 = _html(client)
    assert re.search(r"<script src=\"/static/order_claim_scope\.js[^\"]*\"></script>", 글), \
        "폰 주문 화면이 공용 정의 파일을 안 부른다"


def test_폰_salesOf_는_공용_함수에_넘긴다():
    글 = _tpl()
    assert re.search(r"function salesOf\(sub\)\{\s*return SCOPE\.salesOf\(sub\);\s*\}", 글), \
        "폰이 매출 산식을 다시 짓고 있다 — 공용 정의로 넘겨야 한다"
    # 마진 판의 모수도 같은 제외를 쓴다(매출은 반품을 빼는데 마진율은 안 빼면 어긋난 화면)
    assert "sub.filter(function(r){return !SCOPE.rowExcluded(r);})" in 글, \
        "마진 판 모수(act)가 매출과 다른 제외를 쓴다"
    # 「취소」 **칸의 수**는 이름 그대로 취소만 센다(반품까지 세면 이름과 다른 수)
    assert "var CANCEL_RE=/취소완료|취소요청/;" in 글, \
        "마진 판 「취소」 칸의 정의가 사라졌다"


# ── ③ 잔글씨(A안·폰 2줄) — 파서로 + 문구 원천과 대조 ────────────────────────
class _Cap(HTMLParser):
    """id 를 가진 잔글씨 칸의 줄 목록(<br> 로 나뉜다)."""

    def __init__(self, 찾을id):
        super().__init__()
        self.찾을id = 찾을id
        self.줄 = None
        self._깊이 = None
        self._층 = 0

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            if self._깊이 is not None:
                self.줄.append("")
            return
        if dict(attrs).get("id") == self.찾을id:
            self.줄 = [""]
            self._깊이 = self._층
        self._층 += 1

    def handle_endtag(self, tag):
        if tag == "br":
            return
        self._층 -= 1
        if self._깊이 is not None and self._층 <= self._깊이:
            self._깊이 = None

    def handle_data(self, data):
        if self._깊이 is not None and data.strip():
            self.줄[-1] += data.strip()


def test_폰_매출카드에_잔글씨_두줄이_있다(client):
    p = _Cap("mo-kpi-sales-c")
    p.feed(_html(client))
    assert p.줄 is not None, "매출 카드에 잔글씨 칸(mo-kpi-sales-c)이 없다"
    assert p.줄 == ["취소·반품 제외", "교환 정산 포함"], \
        "폰 잔글씨 2줄이 어긋남: %s" % p.줄


def test_폰_잔글씨_문구가_공용_정의와_같다(client):
    """화면에 적힌 문구와 정의 파일의 문구가 갈라지면 여기서 잡는다."""
    out = _node_run(r"""
      const S=require(process.argv[1]);
      console.log(JSON.stringify({caps:S.CAPS.salesPhone, pc:S.CAPS.sales}));
    """)
    p = _Cap("mo-kpi-sales-c")
    p.feed(_html(client))
    assert p.줄 == out["caps"], "폰 화면 문구가 공용 정의(CAPS.salesPhone)와 다르다"
    assert out["caps"] == out["pc"][:2], "폰 2줄이 PC 3줄의 앞 두 줄과 달라졌다(두 화면 다른 말)"


# ── ④ 마켓 할인 (2026-08-08 A안) — 칸을 빼고 매출 잔글씨 + 눌러서 내역 ────────
def test_폰에도_할인_칸이_없고_매출_잔글씨로_간다(client):
    """🔴 옆 칸에 「−207만」으로 세웠더니 **또 빼는 돈**으로 읽혔다(사장님 지적).

    매출은 이미 할인이 빠진 값이라, 「N만 반영됨」으로 매출 밑에 적는다.
    PC 와 **같은 함수**(discountHint)가 문구를 만든다 — 한쪽만 고치면 두 화면이 갈린다.
    """
    글 = _tpl()
    본문 = _html(client)
    assert 'id="mo-kpi-disc"' not in 본문, "폰에 아직 마켓 할인 칸이 남아 있다"
    assert "SCOPE.discountHint(dc)" in 글, "매출 잔글씨를 공용 함수가 안 만든다"
    assert "SCOPE.CAPS.salesPhone" in 글, "매출 잔글씨 원천이 공용 정의가 아니다"


def test_폰_할인_내역은_공용_자료를_쓴다(client):
    """폰이 판매처별 할인을 다시 세면 PC 와 숫자가 갈린다."""
    글 = _tpl()
    assert "SCOPE.discountByMarket(sub)" in 글,         "폰이 판매처별 할인을 직접 세고 있다(공용 정의로 넘겨야 한다)"


def test_폰_내역창은_눌러서_열고_바깥을_누르면_닫힌다(client):
    """🔴 폰엔 마우스가 없다 — 호버로 만들면 아예 못 연다.

    창은 `document.body` + `position:fixed` 로 띄우고(카드 overflow 에 안 잘리게),
    화면 아래쪽이면 위로 뒤집는다. 스크롤하면 닫는다(좌표가 낡는다).
    """
    글 = _tpl()
    assert "document.body.appendChild" in 글, "창을 body 에 안 붙였다(카드에 잘린다)"
    assert re.search(r"\.dcpop\{[^}]*position:fixed", 글), "position:fixed 가 아니다"
    assert "_dcPop.contains(e.target)" in 글, "바깥을 눌러도 안 닫힌다"
    assert "innerHeight" in 글 and "r.top-h-7" in 글.replace(" ", ""),         "화면 아래에서 위로 뒤집는 처리가 없다"
    assert re.search(r"addEventListener\('scroll',\s*_dcHide", 글), "스크롤하면 닫아야 한다"


def test_폰_잔글씨는_11px_하한을_지킨다():
    글 = _tpl()
    m = re.search(r"\.mo-kpi \.cap\{([^}]*)\}", 글)
    assert m, "폰 잔글씨(.cap) 규칙이 없다"
    px = re.search(r"font-size:\s*([\d.]+)px", m.group(1))
    assert px and float(px.group(1)) >= 11, "폰 깨알글자 하한(11px) 위반"
