# -*- coding: utf-8 -*-
"""ESM 클레임·입금확인중 주문 조회 — 주문조회(RequestOrders)가 안 주는 것들.

공식문서 원문: "클레임(취소, 반품, 교환, 미수령신고) 주문은 조회되지 않습니다"(etapi/67).
그래서 옥션·G마켓만 취소·반품 주문이 통째로 빠진 채 집계됐다.

★ API 마다 규약이 제각각이라 여기서 못 박는다(하나만 틀려도 조용히 0건이 된다):
  · 취소조회만 G마켓 = 3  (주문조회·반품·교환은 2)
  · 파라미터 대소문자: 취소/반품/교환 = SiteType / 입금확인중 = siteType
  · 조회기간: 클레임 7일 · 입금확인중 31일 (주문조회 31/180일과 다름)
  · ResultCode 가 0(int) 또는 "success"(str) 로 섞여 내려온다
  · 반품·교환은 '전체' 값이 없어 상태별로 순회해야 한다
"""
import datetime as _dt

import pytest

from shared.platforms.esm import claims as mod

UNTIL = _dt.datetime(2026, 7, 20, 12, 0)
SINCE = UNTIL - _dt.timedelta(days=7)


class FakeClient:
    """호출 본문을 기록하고 미리 준 응답을 돌려준다."""

    def __init__(self, responses=None):
        self.calls = []               # [(path, body)]
        self._responses = responses or {}

    def post(self, path, body, **kw):
        self.calls.append((path, dict(body)))
        r = self._responses.get(path)
        if callable(r):
            return r(body)
        return r if r is not None else {"ResultCode": 0, "Data": []}

    def bodies(self, path):
        return [b for p, b in self.calls if p == path]


# ── 사이트 코드: 취소만 G마켓 = 3 ──────────────────────────────────────────

def test_취소조회는_G마켓이_3이다():
    """가장 위험한 함정 — 2로 보내면 조용히 0건이 온다."""
    assert mod.site_code("gmarket", "cancels") == 3
    assert mod.site_code("auction", "cancels") == 1


def test_반품_교환_입금확인중은_G마켓이_2다():
    for api in ("returns", "exchanges", "pre_orders"):
        assert mod.site_code("gmarket", api) == 2, api
        assert mod.site_code("auction", api) == 1, api


# ── 조회 기간 분할 ────────────────────────────────────────────────────────

def test_클레임은_7일씩_쪼개_조회한다():
    cli = FakeClient()
    since = UNTIL - _dt.timedelta(days=20)
    list(mod.iter_cancels("auction", since, UNTIL, client=cli))
    for b in cli.bodies(mod.PATHS["cancels"]):
        d0 = _dt.datetime.strptime(b["StartDate"], "%Y-%m-%d")
        d1 = _dt.datetime.strptime(b["EndDate"], "%Y-%m-%d")
        assert (d1 - d0).days <= 7


def test_입금확인중은_31일씩_쪼갠다():
    cli = FakeClient()
    since = UNTIL - _dt.timedelta(days=90)
    list(mod.iter_pre_orders("auction", since, UNTIL, client=cli))
    bodies = cli.bodies(mod.PATHS["pre_orders"])
    assert bodies, "호출이 없다"
    for b in bodies:
        d0 = _dt.datetime.strptime(b["requestDateFrom"], "%Y-%m-%d %H:%M")
        d1 = _dt.datetime.strptime(b["requestDateTo"], "%Y-%m-%d %H:%M")
        assert (d1 - d0).days <= 31


# ── 파라미터 이름·상태 순회 ────────────────────────────────────────────────

def test_취소는_상태_전체값_0_한번만_조회한다():
    """CancelStatus 는 0=전체를 지원한다 — 상태별 6회 호출은 낭비(5초/1회)."""
    cli = FakeClient()
    list(mod.iter_cancels("auction", SINCE, UNTIL, client=cli))
    bodies = cli.bodies(mod.PATHS["cancels"])
    assert len(bodies) == 1
    assert bodies[0]["CancelStatus"] == 0
    assert bodies[0]["SiteType"] == 1
    assert bodies[0]["Type"] == 2          # 2 = 신청일 기준


def test_반품은_전체값이_없어_상태별로_순회한다():
    cli = FakeClient()
    list(mod.iter_returns("auction", SINCE, UNTIL, client=cli))
    got = sorted(b["ReturnStatus"] for b in cli.bodies(mod.PATHS["returns"]))
    assert got == [1, 2, 3, 4, 5, 6]


def test_교환도_상태별로_순회한다():
    cli = FakeClient()
    list(mod.iter_exchanges("auction", SINCE, UNTIL, client=cli))
    got = sorted(b["ExchangeStatus"] for b in cli.bodies(mod.PATHS["exchanges"]))
    assert got == [1, 2, 3, 4, 5]


def test_입금확인중은_소문자_siteType_을_쓴다():
    cli = FakeClient()
    list(mod.iter_pre_orders("gmarket", SINCE, UNTIL, client=cli))
    b = cli.bodies(mod.PATHS["pre_orders"])[0]
    assert "siteType" in b and "SiteType" not in b
    assert b["siteType"] == 2


# ── 응답 해석 ─────────────────────────────────────────────────────────────

def test_ResultCode_는_0과_success_를_모두_성공으로_본다():
    for ok in (0, "0", "success", "Success", None):
        cli = FakeClient({mod.PATHS["cancels"]: {"ResultCode": ok,
                                                 "Data": [{"OrderNo": 1}]}})
        assert len(list(mod.iter_cancels("auction", SINCE, UNTIL, client=cli))) == 1


def test_실패코드는_사유와_함께_예외로_올린다():
    """조용히 0건 반환하면 '취소 주문 없음'으로 둔갑한다."""
    cli = FakeClient({mod.PATHS["cancels"]: {"ResultCode": 9, "Message": "권한 없음"}})
    with pytest.raises(RuntimeError, match="권한 없음"):
        list(mod.iter_cancels("auction", SINCE, UNTIL, client=cli))


def test_데이터없음_1100_은_정상_빈결과다():
    """미수령 조회는 건이 없으면 1100 을 준다 — 오류가 아니다."""
    cli = FakeClient({mod.PATHS["uncollected"]: {"ResultCode": 1100,
                                                 "Message": "데이터가 없습니다"}})
    assert list(mod.iter_uncollected("auction", SINCE, UNTIL, client=cli)) == []


def test_같은_주문번호는_한_번만_나온다():
    """상태별 순회 중 같은 주문이 여러 상태에 걸쳐 잡힐 수 있다."""
    cli = FakeClient({mod.PATHS["returns"]:
                      {"ResultCode": 0, "Data": [{"OrderNo": 777}]}})
    got = list(mod.iter_returns("auction", SINCE, UNTIL, client=cli))
    assert len(got) == 1


def test_클레임행에는_어떤_클레임인지_표시된다():
    """주문내역에서 취소/반품/교환을 구분해야 한다."""
    cli = FakeClient({mod.PATHS["cancels"]:
                      {"ResultCode": 0, "Data": [{"OrderNo": 1, "CancelStatus": 3}]}})
    row = list(mod.iter_cancels("auction", SINCE, UNTIL, client=cli))[0]
    assert row["_claim_kind"] == "cancel"


def test_ESM_마켓이_아니면_거부한다():
    with pytest.raises(ValueError):
        list(mod.iter_cancels("coupang", SINCE, UNTIL, client=FakeClient()))


def test_미수령은_30일씩_쪼개고_OrderNo_자리를_채운다():
    """문서상 OrderNo 는 필수(Y) — 신고일 기준 조회에서도 0 을 보낸다.
    기간 상한은 30일(초과 시 에러 3000)."""
    cli = FakeClient()
    since = UNTIL - _dt.timedelta(days=70)
    list(mod.iter_uncollected("auction", since, UNTIL, client=cli))
    bodies = cli.bodies(mod.PATHS["uncollected"])
    assert bodies
    for b in bodies:
        assert b["OrderNo"] == 0
        assert b["SearchType"] == 1
        d0 = _dt.datetime.strptime(b["StartDate"], "%Y-%m-%d")
        d1 = _dt.datetime.strptime(b["EndDate"], "%Y-%m-%d")
        assert (d1 - d0).days <= 30
