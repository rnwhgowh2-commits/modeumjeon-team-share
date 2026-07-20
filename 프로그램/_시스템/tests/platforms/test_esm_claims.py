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

def test_클레임은_6일씩_쪼개_조회한다():
    cli = FakeClient()
    since = UNTIL - _dt.timedelta(days=20)
    list(mod.iter_cancels("auction", since, UNTIL, client=cli))
    for b in cli.bodies(mod.PATHS["cancels"]):
        d0 = _dt.datetime.strptime(b["StartDate"], "%Y-%m-%d")
        d1 = _dt.datetime.strptime(b["EndDate"], "%Y-%m-%d")
        # "7일 이하"인데 정확히 7일도 거부당한다(라이브 실측) → 6일 이하로 쪼갠다.
        assert (d1 - d0).days <= 6


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
    # 상태는 0(전체) 하나만 — 구간 수만큼만 호출된다(상태별 6회가 아님).
    assert {b["CancelStatus"] for b in bodies} == {0}
    assert bodies[0]["SiteType"] == 1
    assert bodies[0]["Type"] == 2          # 2 = 신청일 기준


def test_반품은_전체값이_없어_상태별로_순회한다():
    cli = FakeClient()
    list(mod.iter_returns("auction", SINCE, UNTIL, client=cli))
    got = {b["ReturnStatus"] for b in cli.bodies(mod.PATHS["returns"])}
    assert got == {1, 2, 3, 4, 5, 6}


def test_교환도_상태별로_순회한다():
    cli = FakeClient()
    list(mod.iter_exchanges("auction", SINCE, UNTIL, client=cli))
    got = {b["ExchangeStatus"] for b in cli.bodies(mod.PATHS["exchanges"])}
    assert got == {1, 2, 3, 4, 5}


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


# ── 주문번호 상세 조회: 문서 한 가지 모양으로 단정하지 않고 재시도 ──────────────

class _OrdClient:
    def __init__(self, hit_on=None, rows=None):
        self._cfg = {"paths": {"orders": "/O"}}
        self.hit_on, self.rows, self.bodies = hit_on, rows or [], []

    def post(self, path, body, **kw):
        self.bodies.append(dict(body))
        has_date = "requestDateFrom" in body
        kind = ("주문번호만" if not has_date
                else ("결제일+기간" if body.get("requestDateType") == 2 else "주문일+기간"))
        ok = (kind == self.hit_on)
        return {"ResultCode": 0,
                "Data": {"RequestOrders": self.rows if ok else []}}


def test_주문번호만_보내야_되는_경우도_잡아낸다():
    """문서상 기간이 필수지만 실제로는 기간을 빼야 나오는 경우가 있다."""
    from shared.platforms.esm.orders import fetch_by_order_no
    cli = _OrdClient(hit_on="주문번호만", rows=[{"OrderNo": 7, "GoodsName": "상품"}])
    row, why = fetch_by_order_no("auction", 7, client=cli)
    assert why is None and row["GoodsName"] == "상품"
    assert row["_detail_via"] == "주문번호만"


def test_첫_모양이_되면_뒤는_부르지_않는다():
    """되는 걸 찾으면 즉시 멈춘다 — 불필요한 호출은 제한만 갉아먹는다."""
    from shared.platforms.esm.orders import fetch_by_order_no
    cli = _OrdClient(hit_on="주문일+기간", rows=[{"OrderNo": 7}])
    fetch_by_order_no("auction", 7, client=cli)
    assert len(cli.bodies) == 1


def test_전부_실패하면_시도한_모양들을_사유로_남긴다():
    from shared.platforms.esm.orders import fetch_by_order_no
    cli = _OrdClient(hit_on=None)
    row, why = fetch_by_order_no("auction", 7, client=cli)
    assert row is None
    for label in ("주문일+기간", "주문번호만", "결제일+기간"):
        assert label in why


def test_상품명_보강은_products_시그니처를_지킨다(monkeypatch):
    """resolve_goods_no/get_goods_detail 은 market 인자를 받지 않는다.
    라이브에서 TypeError 로 조용히 실패했던 회귀 방지."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    seen = {}

    def _resolve(site_goods_no, *, client):
        seen["site"] = site_goods_no
        return "G100"

    def _detail(goods_no, *, client):
        seen["goods"] = goods_no
        return {"goodsName": "나이키 러너"}

    monkeypatch.setattr(pm, "resolve_goods_no", _resolve)
    monkeypatch.setattr(pm, "get_goods_detail", _detail)
    name, why = om.fill_from_product("auction", "S1", client=object())
    assert (name, why) == ("나이키 러너", None)
    assert seen == {"site": "S1", "goods": "G100"}


def test_상품번호가_없으면_사유를_돌려준다():
    from shared.platforms.esm.orders import fill_from_product
    name, why = fill_from_product("auction", None, client=object())
    assert name is None and "상품번호 없음" in why


def test_상품명은_itemBasicInfo_중첩구조에서_꺼낸다(monkeypatch):
    """상품 상세조회의 상품명은 itemBasicInfo>goodsName>kor 다(지도 기준).
    주문조회의 평평한 GoodsName 과 달라 라이브에서 '상품명 없음'이 났던 회귀 방지."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: "G1")
    monkeypatch.setattr(pm, "get_goods_detail", lambda g, *, client: {
        "isEditableGoodsName": True,
        "itemBasicInfo": {"goodsName": {"kor": "나이키 레볼루션 7",
                                        "promotion": "무료배송"}},
    })
    assert om.fill_from_product("auction", "S1", client=object()) == ("나이키 레볼루션 7", None)


def test_국문이_없으면_프로모션명이라도_쓴다(monkeypatch):
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: "G1")
    monkeypatch.setattr(pm, "get_goods_detail", lambda g, *, client: {
        "itemBasicInfo": {"goodsName": {"promotionIac": "옥션 단독 특가"}}})
    assert om.fill_from_product("auction", "S1", client=object())[0] == "옥션 단독 특가"


def test_상품명을_못_찾으면_응답키를_사유에_싣는다(monkeypatch):
    """'상품명 없음'만 보면 다음에 뭘 볼지 알 수 없다."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: "G1")
    monkeypatch.setattr(pm, "get_goods_detail", lambda g, *, client: {"zzz": 1, "yyy": 2})
    name, why = om.fill_from_product("auction", "S1", client=object())
    assert name is None and "zzz" in why


def test_마스터상품번호가_있으면_변환하지_않는다(monkeypatch):
    """클레임 응답은 GoodsNo(마스터번호)를 함께 준다. 그걸 두고 SiteGoodsNo 를
    변환하려다 실패하면, 폴백이 사이트번호를 그대로 goodsNo 로 넘겨 404 가 난다
    (라이브 F575628540 사례)."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    called = []
    monkeypatch.setattr(pm, "resolve_goods_no",
                        lambda s, *, client: called.append(s) or "WRONG")
    monkeypatch.setattr(pm, "get_goods_detail",
                        lambda g, *, client: {"itemBasicInfo": {"goodsName": {"kor": f"상품{g}"}}})
    name, why = om.fill_from_product("auction", "F575628540", client=object(),
                                     goods_no="G123")
    assert (name, why) == ("상품G123", None)
    assert called == []                    # 변환 API 를 아예 안 부른다


def test_마스터번호가_없으면_사이트번호를_변환한다(monkeypatch):
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: "G9")
    monkeypatch.setattr(pm, "get_goods_detail",
                        lambda g, *, client: {"itemBasicInfo": {"goodsName": {"kor": f"상품{g}"}}})
    assert om.fill_from_product("auction", "S1", client=object())[0] == "상품G9"


def test_변환이_실패하면_404_대신_진짜_사유를_말한다(monkeypatch):
    """resolve_goods_no 는 매핑 실패 시 입력을 그대로 돌려준다(폴백).
    그걸 성공으로 착각해 상세조회하면 404 가 나고, 화면엔 원인 대신 URL 이 뜬다."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: s)   # 변환 안 됨
    called = []
    monkeypatch.setattr(pm, "get_goods_detail",
                        lambda g, *, client: called.append(g) or {})
    name, why = om.fill_from_product("auction", "F575628540", client=object())
    assert name is None
    assert "F575628540" in why and "마켓 상품 조회에 없습니다" in why
    assert called == []            # 될 리 없는 상세조회를 부르지 않는다


def test_GoodsNo가_0이면_변환경로를_탄다(monkeypatch):
    """클레임 응답의 GoodsNo 는 값이 0 으로 온다(문서대로). 0 을 상품번호로 쓰면 안 된다."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm
    monkeypatch.setattr(pm, "resolve_goods_no", lambda s, *, client: "G7")
    monkeypatch.setattr(pm, "get_goods_detail",
                        lambda g, *, client: {"itemBasicInfo": {"goodsName": {"kor": f"상품{g}"}}})
    assert om.fill_from_product("auction", "S1", client=object(), goods_no=0)[0] == "상품G7"


# ── 조용한 잘림 방지 ──────────────────────────────────────────────────────
#  클레임 조회는 페이징도 없고 응답에 TotalCount 도 없다(라이브 확인).
#  마켓이 상한을 걸어 잘라도 알 방법이 없으므로, 의심되면 기간을 쪼개 다시 받는다.

class _TruncClient:
    """구간당 최대 cap 건만 돌려주는(=잘리는) 마켓 흉내."""

    def __init__(self, per_day, cap):
        self.per_day, self.cap, self.calls = per_day, cap, 0

    def post(self, path, body, **kw):
        self.calls += 1
        d0 = _dt.datetime.strptime(body["StartDate"], "%Y-%m-%d")
        d1 = _dt.datetime.strptime(body["EndDate"], "%Y-%m-%d")
        days = max(1, (d1 - d0).days)
        # 이 구간에 '실제로' 있는 주문 — 날짜별로 고유 번호 부여
        real = [{"OrderNo": d0.toordinal() * 1000 + i}
                for i in range(days * self.per_day)]
        return {"ResultCode": 0, "Data": real[:self.cap]}   # ★ cap 에서 잘린다


def test_잘린_것으로_의심되면_기간을_쪼개_다시_받는다():
    """한 구간에 60건이 있는데 마켓이 50건만 준다 → 쪼개서 60건을 다 받아야 한다."""
    cli = _TruncClient(per_day=10, cap=50)
    until = _dt.datetime(2026, 7, 20)
    got = list(mod.iter_cancels("auction", until - _dt.timedelta(days=6), until, client=cli))
    assert len(got) == 60, f"{len(got)}건 — 잘린 채로 넘어갔다"


def test_적게_오면_쪼개지_않는다():
    """건수가 적으면 추가 호출은 낭비다(5초/1회 제한)."""
    cli = _TruncClient(per_day=1, cap=50)
    until = _dt.datetime(2026, 7, 20)
    list(mod.iter_cancels("auction", until - _dt.timedelta(days=6), until, client=cli))
    assert cli.calls == 1


def test_무한분할하지_않는다():
    """하루치도 상한을 넘으면 더는 쪼갤 수 없다 — 받은 만큼 쓰되 멈춘다."""
    cli = _TruncClient(per_day=500, cap=50)
    until = _dt.datetime(2026, 7, 20)
    got = list(mod.iter_cancels("auction", until - _dt.timedelta(days=1), until, client=cli))
    assert got and cli.calls < 40        # 폭주하지 않는다


def test_마켓이_밝힌_사유를_그대로_올린다(monkeypatch):
    """마켓은 400 과 함께 이유를 적어 보낸다(예: "삭제된 상품 입니다.").
    raise_for_status 가 본문을 버려서 그동안 "404" 로만 보였다."""
    from shared.platforms.esm import orders as om
    from shared.platforms.esm import products as pm

    def _boom(s, *, client):
        raise RuntimeError("삭제된 상품 입니다.")

    monkeypatch.setattr(pm, "resolve_goods_no", _boom)
    name, why = om.fill_from_product("auction", "F575628540", client=object())
    assert name is None and "삭제된 상품" in why
