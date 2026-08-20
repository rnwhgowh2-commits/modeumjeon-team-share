# -*- coding: utf-8 -*-
"""실패 계정 「다시 시도」 — fresh 재조회가 90초 캐시를 건너뛰는지.

배경: 계정 조회 실패 사유(warnings)는 결과와 함께 캐시에 저장된다(적중 때 경고가
사라지면 조용한 실패라서). 그래서 사용자가 원인(키·IP)을 고친 직후 재조회해도
90초 동안 실패본이 그대로 나온다. fresh=True 는 캐시 '읽기'만 건너뛰어 실조회를
강제하고, 결과는 다시 캐시에 저장한다 — 이후 일반 조회가 실패본 대신 재시도
결과를 받게.
"""
import pytest

import lemouton.markets.order_export as oe


@pytest.fixture(autouse=True)
def _reset_caches():
    """L1(인메모리) + L2(DB) 둘 다 비운다 — 테스트 간 오염 방지."""
    oe.clear_cache()
    yield
    oe.clear_cache()


def _fake_rows(mk):
    return [{"주문일": "2026-07-22 00:00:00", "판매처": mk, "상품명": "X"}]


def test_fresh는_캐시를_건너뛰고_실조회한다(monkeypatch):
    """실패본이 캐시에 남아 있어도 fresh 재조회는 실조회로 최신 결과를 받는다."""
    n = {"fetch": 0}
    broken = {"on": True}                 # True = 세소 계정 조회 실패 상태

    def _order_rows(mk, warnings=None, **kw):
        n["fetch"] += 1
        if broken["on"] and warnings is not None:
            warnings.append(f"[{mk}·세소] 주문을 불러오지 못했어요.")
        return _fake_rows(mk)

    monkeypatch.setattr(oe, "order_rows", _order_rows)

    w1 = []
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w1)
    assert n["fetch"] == 1 and w1                     # 실패 경고가 캐시에 담김

    broken["on"] = False                              # 사용자가 키·IP 를 고침
    w2 = []
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w2)
    assert n["fetch"] == 1 and w2, "일반 재조회는 TTL 안이라 실패본 캐시를 받는다(전제 확인)"

    w3 = []
    rows = oe.combined_order_rows(["coupang"], days=7, use_cache=True,
                                  warnings=w3, fresh=True)
    assert n["fetch"] == 2, "fresh 는 L1·L2 캐시를 읽지 않고 실조회해야 한다"
    assert not w3, "고쳐진 뒤의 fresh 재조회에는 실패 경고가 없어야 한다"
    assert len(rows) == 1


def test_fresh_결과가_캐시에_저장돼_다음_일반조회가_받는다(monkeypatch):
    """fresh 가 캐시 쓰기까지 건너뛰면, 다음 일반 조회가 옛 실패본을 되살린다 — 금지."""
    n = {"fetch": 0}
    broken = {"on": True}

    def _order_rows(mk, warnings=None, **kw):
        n["fetch"] += 1
        if broken["on"] and warnings is not None:
            warnings.append(f"[{mk}·세소] 주문을 불러오지 못했어요.")
        return _fake_rows(mk)

    monkeypatch.setattr(oe, "order_rows", _order_rows)

    w1 = []
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w1)  # 실패본 캐시
    broken["on"] = False
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=[], fresh=True)
    assert n["fetch"] == 2

    w3 = []
    rows = oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=w3)
    assert n["fetch"] == 2, "fresh 직후 일반 조회는 방금 캐시된 fresh 결과를 받아야(재조회 금지)"
    assert not w3, "fresh 가 덮어쓴 캐시에 옛 실패 경고가 남아 있으면 안 된다"
    assert len(rows) == 1


def test_fresh_아니면_기존_캐시동작_그대로(monkeypatch):
    """회귀 — fresh 미지정 일반 조회 2회는 실조회 1회(캐시 적중)."""
    n = {"fetch": 0}

    def _order_rows(mk, warnings=None, **kw):
        n["fetch"] += 1
        return _fake_rows(mk)

    monkeypatch.setattr(oe, "order_rows", _order_rows)
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=[])
    oe.combined_order_rows(["coupang"], days=7, use_cache=True, warnings=[])
    assert n["fetch"] == 1


def test_preview_json_fresh_파라미터_배선(monkeypatch):
    """preview.json?fresh=1 이 new_order_rows(fresh=True) 로 전달되는지."""
    import pathlib
    from flask import Flask
    from webapp.routes import orders as om

    got = {"fresh": None}

    def _fake_new(markets, **kw):
        got["fresh"] = kw.get("fresh")
        return []

    monkeypatch.setattr(om._oe, "new_order_rows", _fake_new)

    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    client = app.test_client()

    assert client.get("/orders/preview.json?markets=coupang&days=7&fresh=1").status_code == 200
    assert got["fresh"] is True

    assert client.get("/orders/preview.json?markets=coupang&days=7").status_code == 200
    assert got["fresh"] is False


def test_주문화면_실패배너에_다시시도_배선이_있다():
    """템플릿 회귀 — 재시도 링크·fresh 배선·재조회 함수가 화면에 존재."""
    import pathlib
    from webapp.routes import orders as om
    html = (pathlib.Path(om.__file__).parents[1] / "templates" / "orders"
            / "index.html").read_text(encoding="utf-8")
    assert 'data-remk=' in html           # 실패 줄의 「다시 시도」 링크
    assert "fresh?'&fresh=1':''" in html  # fresh 재조회 파라미터
    assert "retryMk=function(mk)" in html  # 마켓 단위 강제 재조회 함수
