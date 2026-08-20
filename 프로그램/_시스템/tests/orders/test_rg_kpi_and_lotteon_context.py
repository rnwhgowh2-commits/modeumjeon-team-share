# -*- coding: utf-8 -*-
"""화면 「로켓그로스」 숫자와 롯데온 가져오기 창구 — 라이브 실패 2건에서 나온 것.

🔴 ① 화면 KPI 가 **옛 계산 그대로**였다(2026-08-13 사장님 스크린샷)
   화면 9,508,138 「지급액 27,319,558 − 빠른정산 17,811,420 · 22회차」
   확정된 정답 7,818,202 (Σ최종지급액 · 정산일 오늘 이후~한 달)
   대조 엔진만 고치고 **사장님이 실제로 보는 숫자**를 안 고쳐, 틀린 값이
   「앞으로 받을 돈」 총액에 그대로 얹혀 있었다.

🔴 ② 롯데온 단추가 **`trNo not found`** 로 실패했다
   확장이 셀러오피스 화면에서 판매자ID 를 긁게 해 뒀는데, 화면 구조에 기대는 방식이라
   못 찾았다. 그 번호는 **계정 설정에 이미 있다** — 서버가 주면 된다.
"""
import pathlib

import pytest

import webapp.routes.orders as om


@pytest.fixture
def client():
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


# ── ① 화면 KPI ───────────────────────────────────────────────────────────────

def test_화면_로켓그로스는_한달창_최종지급액을_쓴다(monkeypatch):
    """🔴 대조 엔진과 **같은 규칙**이어야 한다 — 둘이 갈리면 화면만 틀린다."""
    src = pathlib.Path(om.__file__).read_text(encoding="utf-8")
    i = src.index("kpi['rocket_growth']")
    blk = src[i - 400:i + 200]
    assert "ahead_summary" in blk or "앞으로받을돈" in blk, (
        "화면 KPI 가 아직 옛 `받을돈`(지급액 − 빠른정산)을 쓴다 — "
        "이미 받은 회차까지 세어 사장님 화면이 부푼다")


def test_총액도_같은_값을_쓴다():
    """카드와 총액이 갈리면 「앞으로 받을 돈」이 카드 합과 안 맞는다."""
    src = pathlib.Path(om.__file__).read_text(encoding="utf-8")
    i = src.index("kpi['net_uncollected']")
    blk = src[i - 300:i + 200]
    assert "_rg_ahead" in blk, "총액이 카드와 다른 값을 더한다"


def test_화면_카드_문구가_옛_공식을_안_보여준다():
    """「지급액 − 빠른정산」이라 적혀 있으면 사장님이 옛 규칙으로 읽는다."""
    tpl = (pathlib.Path(om.__file__).parents[1] / "templates" / "orders"
           / "index.html").read_text(encoding="utf-8")
    i = tpl.index("로켓그로스</div>")
    blk = tpl[i:i + 700]
    assert "지급액 '+fmt(rg.지급액)" not in blk
    assert "앞으로 들어올 회차" in blk
    assert "이미 받은 회차" in blk        # 숫자가 줄어든 이유를 화면이 말한다


# ── ② 롯데온 trNo · 최근 내역 ────────────────────────────────────────────────

def test_창구가_계정에서_trNo_를_준다(client, monkeypatch):
    monkeypatch.setattr(om._oe, "_active_accounts",
                        lambda mk: [("LO1_", "브랜드박스(롯데온)")])
    monkeypatch.setattr(om._oe, "_account_client",
                        lambda mk, p: type("C", (), {"_cfg": {"tr_no": "LO10161082"}})())
    monkeypatch.setattr("lemouton.margin.lotteon_paid.summary",
                        lambda **kw: {"날짜수": 3, "지급확정": 2, "지급합": 517515,
                                      "최근완료일": "2026-08-03"})
    d = client.get("/orders/lotteon-paid/context").get_json()
    assert d["계정"] == [{"계정": "브랜드박스(롯데온)", "trNo": "LO10161082"}]


def test_최근_가져온_내역을_같이_준다(client, monkeypatch):
    """🔴 사장님 지적 — 눌러도 「언제·얼마나」를 모르면 된 건지 확인할 수 없다."""
    monkeypatch.setattr(om._oe, "_active_accounts", lambda mk: [])
    monkeypatch.setattr("lemouton.margin.lotteon_paid.summary",
                        lambda **kw: {"날짜수": 3, "지급확정": 2, "지급합": 517515,
                                      "최근완료일": "2026-08-03"})
    d = client.get("/orders/lotteon-paid/context").get_json()
    assert d["최근가져온내역"]["지급합"] == 517515
    assert d["최근가져온내역"]["최근완료일"] == "2026-08-03"


def test_계정을_못_읽어도_내역은_준다(client, monkeypatch):
    """한쪽이 막혀도 다른 쪽은 보여준다 — 사유는 숨기지 않는다."""
    def boom(mk):
        raise RuntimeError("no config")
    monkeypatch.setattr(om._oe, "_active_accounts", boom)
    monkeypatch.setattr("lemouton.margin.lotteon_paid.summary",
                        lambda **kw: {"날짜수": 0, "지급확정": 0, "지급합": 0,
                                      "최근완료일": ""})
    d = client.get("/orders/lotteon-paid/context").get_json()
    assert d["ok"] is True and d["오류"]


def test_단추가_서버에서_받은_trNo_를_실어_보낸다():
    """화면에서 긁다 실패한 그 값을 서버가 준다 — 그걸 안 실으면 또 `trNo not found`."""
    tpl = (pathlib.Path(om.__file__).parents[1] / "templates" / "orders"
           / "index.html").read_text(encoding="utf-8")
    i = tpl.index("$('#spn-lo-btn')")
    blk = tpl[i:i + 4000]
    assert "/orders/lotteon-paid/context" in blk
    assert "trNo:accs[0].trNo" in blk.replace(" ", "")
    assert "spn-lo-hist" in tpl              # 최근 내역 자리
