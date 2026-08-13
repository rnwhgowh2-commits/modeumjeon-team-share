# -*- coding: utf-8 -*-
"""주문상태는 **뒤로 못 간다** — 롯데온 3,179만원이 화면 밖으로 새던 원인.

🔴 라이브 실측(2026-08-13, 저장분 전수):

    마켓        상태 바뀐 적 있음   **뒤로 감**
    롯데온            1,335       **510줄 31,790,892원**
    쿠팡                179            0
    스마트스토어         175            0
    11번가              175            0
    G마켓                40            0
    옥션                   5            0

  롯데온만 뒤로 간다. 내역 — 배송완료→출고지시 324 · 출고지시→상품준비 185 · 발송완료→출고지시 1.

🔴 원인은 이미 코드 주석에 적혀 있었다(`order_ingest.refresh_stale_delivered`):
   *"롯데온 단건 조회는 같은 상품라인을 **단계별 여러 행**으로 주고, 나중에 처리된 행이
     상태를 덮어써 시간이 거꾸로 흐른다."*
   그런데 막는 코드는 없었다. 그래서 그 함수를 껐어도(도장 있는 건 117줄뿐) 나머지
   **393줄은 평상시 적재에서 계속 되돌아간다** — 오늘도 새로 되돌아갔다.

🔴 되돌아가면 돈이 화면에서 사라진다 — 부류 판정(`settle_plan._SHIPPED_MARKERS`)이
   「출고지시·상품준비」를 모르므로 그 줄은 「대상 아님」으로 조용히 빠진다.

🔴 **클레임은 뒤로 가는 게 아니다.** 반품·취소·교환은 진행 단계와 **다른 축**이라
   막으면 안 된다 — 막으면 반품된 주문이 영영 배송완료로 남는다.
"""
import pytest

from lemouton.markets import order_store as OS


class _Obj:
    def __init__(self, status="", prev="", at=None):
        self.status, self.status_prev, self.status_at = status, prev, at


# ── ① 사다리 판정 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("old,new", [
    ("배송완료", "출고지시"),        # 라이브 324줄
    ("출고지시", "상품준비"),        # 라이브 185줄
    ("발송완료", "출고지시"),        # 라이브 1줄
    ("구매확정", "배송완료"),
])
def test_뒤로_가는_것은_막는다(old, new):
    assert OS._status_regressed(old, new) is True


@pytest.mark.parametrize("old,new", [
    ("상품준비", "출고지시"), ("출고지시", "배송완료"),
    ("배송완료", "구매확정"), ("결제완료", "상품준비"),
])
def test_앞으로_가는_것은_안_막는다(old, new):
    assert OS._status_regressed(old, new) is False


@pytest.mark.parametrize("new", ["반품요청", "취소완료", "교환요청", "반품완료",
                                 "회수지시", "취소요청"])
def test_클레임은_막지_않는다(new):
    """🔴 막으면 반품된 주문이 영영 배송완료로 남는다 — 버그보다 나쁜 막이가 된다."""
    assert OS._status_regressed("배송완료", new) is False


def test_모르는_낱말은_막지_않는다():
    """사다리에 없는 말은 판단하지 않는다 — 모르면서 막으면 조용히 갱신이 멈춘다."""
    assert OS._status_regressed("배송완료", "무슨상태") is False
    assert OS._status_regressed("무슨상태", "출고지시") is False


def test_빈_값은_막지_않는다():
    assert OS._status_regressed("", "출고지시") is False
    assert OS._status_regressed("배송완료", "") is False


# ── ② 실제로 안 쓴다 ────────────────────────────────────────────────────────

def test_뒤로_가는_상태는_저장되지_않는다():
    o = _Obj(status="배송완료")
    assert OS._apply_status(o, "출고지시") is False
    assert o.status == "배송완료", "되돌아간 상태가 저장됐다"
    assert o.status_prev == "", "도장도 찍히면 안 된다"


def test_앞으로_가는_상태는_저장된다():
    o = _Obj(status="출고지시")
    assert OS._apply_status(o, "배송완료") is True
    assert o.status == "배송완료"
    assert o.status_prev == "출고지시"
    assert o.status_at is not None


def test_클레임은_저장된다():
    o = _Obj(status="배송완료")
    assert OS._apply_status(o, "반품요청") is True
    assert o.status == "반품요청"


def test_같은_상태면_도장을_안_찍는다():
    """기존 동작 보존 — 조회할 때마다 「방금 바뀜」이 되면 안 된다."""
    o = _Obj(status="배송완료", prev="출고지시")
    assert OS._apply_status(o, "배송완료") is False
    assert o.status_prev == "출고지시"


# ── ③ 조용히 넘기지 않는다 ──────────────────────────────────────────────────

def test_막은_횟수를_세어_알린다():
    """🔴 조용히 안 쓰면 「왜 상태가 안 바뀌지」를 아무도 못 찾는다."""
    import inspect
    src = inspect.getsource(OS.save)
    assert "status_regress_blocked" in src, "막은 것을 세지 않는다"


# ── ④ 쓰는 곳이 둘 다 지킨다 ────────────────────────────────────────────────

#  🔴 아래 두 시험은 **실제로 돌려서** 본다. 글자만 세면 안 된다 —
#    처음엔 `src.count("_apply_status(") >= 2` 로 썼는데, 반환값을 무시하고 바로
#    `line.status = st_new` 로 덮는 뮤테이션이 **그대로 통과했다**. 세는 시험은
#    「불렀나」만 알지 「말을 들었나」는 모른다.

@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _row(uid="lotteon|L1", **kw):
    from lemouton.markets import line_uid as L
    r = {L.FIELD: uid, "판매처": "롯데온", "오픈마켓주문번호": "L1",
         "주문일": "2026-07-01 10:00:00", "주문상태": "배송완료",
         "상품명": "티셔츠", "단가": 10000, "수량": 1}
    r.update(kw)
    return r


def test_주문_갱신_경로가_되돌아가는_값을_안_쓴다(session):
    """롯데온이 같은 라인을 단계별 여러 행으로 줄 때 나중 행이 앞선 상태를 덮던 그 자리."""
    OS.save([_row()], session=session)
    st = OS.save([_row(주문상태="출고지시")], session=session)
    rows = OS.load(session=session)
    assert rows[0]["주문상태"] == "배송완료", "되돌아간 상태가 저장됐다"
    assert st["status_regress_blocked"] == 1, "막았으면 세어서 알려야 한다"


def test_클레임_행_경로도_되돌아가는_값을_안_쓴다(session):
    """🔴 이 경로를 안 막으면 다른 쪽으로 그대로 되돌아간다.

    재고 조정에서 똑같이 겪었다 — 쓰는 곳 세 곳 중 하나만 고쳐 하루에 네 번 뒤집혔다.
    """
    OS.save([_row()], session=session)
    st = OS.save([_row(_kind="change", _change_date="2026-07-02",
                       주문상태="출고지시", 주문상태원본="11")], session=session)
    rows = OS.load(session=session)
    assert rows[0]["주문상태"] == "배송완료", "클레임 행이 원 주문 상태를 되돌렸다"
    assert st["status_regress_blocked"] == 1


def test_클레임_행이_반품은_제대로_반영한다(session):
    """막이가 반품까지 막으면 버그보다 나쁘다 — 반품된 주문이 영영 배송완료로 남는다."""
    OS.save([_row()], session=session)
    st = OS.save([_row(_kind="change", _change_date="2026-07-02",
                       주문상태="반품요청", 주문상태원본="UC")], session=session)
    rows = OS.load(session=session)
    assert rows[0]["주문상태"] == "반품요청"
    assert st["status_regress_blocked"] == 0


def test_앞으로_가는_것은_그대로_저장된다(session):
    OS.save([_row(주문상태="출고지시")], session=session)
    st = OS.save([_row(주문상태="배송완료")], session=session)
    assert OS.load(session=session)[0]["주문상태"] == "배송완료"
    assert st["status_regress_blocked"] == 0


def test_상태만_안_쓰고_나머지_값은_갱신한다(session):
    """🔴 막이가 다른 값까지 얼리면 정산액·송장이 영영 안 들어온다."""
    OS.save([_row()], session=session)
    OS.save([_row(주문상태="출고지시", 송장입력="1234567890")], session=session)
    r = OS.load(session=session)[0]
    assert r["주문상태"] == "배송완료"
    assert r["송장입력"] == "1234567890", "상태를 막으면서 다른 값까지 막았다"


def test_옛_경로가_안_남아_있다():
    """`_stamp_status` 가 남아 있으면 새 코드가 그리로 새어 나간다."""
    assert not hasattr(OS, "_stamp_status")
