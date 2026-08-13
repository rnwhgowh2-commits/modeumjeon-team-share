# -*- coding: utf-8 -*-
"""로켓그로스 회차 진단 — Wing 화면과 **같은 표로** 맞대는 창구.

🔴 왜(2026-08-13 사장님 지적) — *"선정산 받은거 제외안해도돼? 내 생각엔 최종지급액
   합산되어야하는거 아닌지??? 그게 동일한지도 모르겠고"*
   우리는 `받을돈 = 지급액 − 빠른정산` 으로 세는데, 화면 목록의 열 이름은
   **「최종지급액」**이다. 둘이 같은 것인지 **증명된 적이 없다.**
   합계만 비교하면 「우연히 비슷」과 「정말 같음」을 못 가르므로 회차별로 준다.
"""
import datetime as dt
import pathlib

import pytest

import webapp.routes.orders as om


class _Row:
    def __init__(self, sd, ratio, pay, fast, fin, ps="2026-06-01", pe="2026-06-07",
                 sales=0, acc="세소(쿠팡)"):
        self.settlement_date, self.ratio = sd, ratio
        self.payable_amount, self.fast_withdrawn, self.final_amount = pay, fast, fin
        self.period_start, self.period_end, self.sales_amount = ps, pe, sales
        self.account = acc


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _Sess:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a):
        return _Q(self._rows)

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def _patch(monkeypatch, rows):
    monkeypatch.setattr(om, "SessionLocal", lambda: _Sess(rows))


#  사장님 화면(2026-08-13)을 축소한 표 — 지난 회차 2개 + 앞으로 올 회차 1개
#  🔴 오늘을 전역으로 갈아끼우지 않는다 — `datetime.date` 를 바꾸면 다른 코드까지
#    말려든다(이 시험을 쓰다 실제로 겪었다). 확실히 지난 날 / 확실히 올 날로 고른다.
ROWS = [
    _Row("2020-07-20", 70, pay=200000, fast=6210, fin=193790),   # 확실히 지남
    _Row("2020-08-03", 70, pay=800000, fast=90594, fin=709406),  # 확실히 지남
    _Row("2099-08-24", 30, pay=500000, fast=0, fin=500000),      # 확실히 앞으로
]


def test_회차별로_네_숫자를_다_보여준다(client, monkeypatch):
    _patch(monkeypatch, ROWS)
    d = client.get("/orders/diag/rg-rounds").get_json()
    assert d["회차수"] == 3
    r = d["회차별"][0]
    for k in ("정산일", "지급비율", "지급액", "빠른정산_이미받음", "최종지급액", "정산일_지남"):
        assert k in r, k


def test_네_가지_후보_합계를_나란히_준다(client, monkeypatch):
    """🔴 어느 정의가 화면 숫자와 같은지 **눈으로 가르게** 한다 —
    합계 하나만 주면 「우연히 비슷」을 「맞다」로 읽게 된다."""
    _patch(monkeypatch, ROWS)
    t = client.get("/orders/diag/rg-rounds").get_json()["합계"]
    assert t["Σ지급액"] == 1_500_000
    assert t["Σ빠른정산_이미받음"] == 96_804
    assert t["지급액−빠른정산 (지금 우리가 쓰는 값)"] == 1_403_196
    assert t["Σ최종지급액 (화면 목록의 그 열)"] == 1_403_196
    # 노션 규칙 = 오늘 이후 정산일만
    assert t["Σ최종지급액_오늘이후_정산일만 (노션 규칙)"] == 500_000
    assert t["오늘이후_회차수"] == 1


def test_지난_회차와_앞으로_올_회차를_가른다(client, monkeypatch):
    """「이미 받은 회차」를 앞으로 받을 돈에 넣으면 자금계획이 통째로 부푼다."""
    _patch(monkeypatch, ROWS)
    rows = client.get("/orders/diag/rg-rounds").get_json()["회차별"]
    past = [r for r in rows if r["정산일_지남"]]
    future = [r for r in rows if not r["정산일_지남"]]
    assert [r["정산일"] for r in past] == ["2020-07-20", "2020-08-03"]
    assert [r["정산일"] for r in future] == ["2099-08-24"]


def test_회차가_없으면_0으로_속이지_않는다(client, monkeypatch):
    _patch(monkeypatch, [])
    d = client.get("/orders/diag/rg-rounds").get_json()
    assert d["회차수"] == 0
    assert "대조 성공" in d["해석"]        # 정의를 모르면 성공이라 하지 말라고 적혀 있다
