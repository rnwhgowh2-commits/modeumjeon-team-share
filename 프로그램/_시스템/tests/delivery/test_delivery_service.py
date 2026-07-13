import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.delivery.models as M
from lemouton.delivery import service as svc


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _row(uid, **kw):
    base = dict(mango_uid=uid, market_name="롯데ON", market_order_no="C" + uid,
                ordered_at="2026-07-11", recipient="염수경", product_name="백팩",
                option1="ONESIZE", phone="010", invoice_no="", courier="",
                mango_status="해외현지배송중", market_status="특이사항없음", memo="")
    base.update(kw)
    return base


def test_models_create(db):
    o = M.MangoOrder(mango_uid="12039", recipient="이주연", market_name="쿠팡")
    db.add(o)
    db.commit()
    got = db.query(M.MangoOrder).filter_by(mango_uid="12039").one()
    assert got.recipient == "이주연"
    assert got.delivery_method == "미지정"
    assert got.delivery_method_source == "자동"

    sm = M.MangoStatusMap(status_value="해외현지배송중", meaning="해외배송중",
                          default_method="까대기", is_flow_check_target=False)
    db.add(sm)
    db.commit()
    assert db.query(M.MangoStatusMap).filter_by(status_value="해외현지배송중").one().default_method == "까대기"


def test_seed_default_status_map(db):
    svc.seed_default_status_map(db)
    rows = {r.status_value: r for r in db.query(M.MangoStatusMap).all()}
    # 2026-07-12 사용자 워크플로 반영
    assert rows["해외현지배송중"].default_method == "까대기"
    assert rows["현지배송완료"].default_method == "까대기"
    assert rows["현지배송완료"].is_flow_check_target is True   # 까대기 송장입력·발송 = 검사 핵심
    assert rows["배송대기중"].default_method == "직배"
    assert rows["국내배송중"].default_method == "직배"
    assert rows["국내배송중"].is_flow_check_target is True
    assert rows["배송완료"].is_flow_check_target is False       # 도착 완료 = 검사 제외
    assert rows["결제완료"].default_method == "미지정"
    svc.seed_default_status_map(db)  # idempotent
    assert db.query(M.MangoStatusMap).filter_by(status_value="해외현지배송중").count() == 1


def test_reconcile_updates_old_default_but_preserves_edit(db):
    # 옛 기본값(국내배송중=미지정)으로 선삽입 → 재시드가 직배로 갱신
    db.add(M.MangoStatusMap(status_value="국내배송중", meaning="국내배송중",
                            default_method="미지정", is_flow_check_target=True))
    # 사용자가 배송대기중을 손수 '까대기'로 바꿔둔 상태
    db.add(M.MangoStatusMap(status_value="배송대기중", meaning="배송전",
                            default_method="까대기", is_flow_check_target=False))
    db.commit()
    svc.seed_default_status_map(db)
    rows = {r.status_value: r for r in db.query(M.MangoStatusMap).all()}
    assert rows["국내배송중"].default_method == "직배"    # 옛 기본값 → 갱신됨
    assert rows["배송대기중"].default_method == "까대기"  # 사용자 수정 → 보존됨


def test_upsert_autoadds_unknown_status(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("900", mango_status="현지배송완료")])   # 시드에 있음
    svc.upsert_orders(db, [_row("901", mango_status="깜짝새상태")])     # 처음 보는 값
    assert db.query(M.MangoStatusMap).filter_by(status_value="깜짝새상태").count() == 1
    m = db.query(M.MangoStatusMap).filter_by(status_value="깜짝새상태").one()
    assert m.default_method == "미지정" and m.is_flow_check_target is False


def test_upsert_auto_method_from_map(db):
    svc.seed_default_status_map(db)
    res = svc.upsert_orders(db, [_row("100")])
    assert res["inserted"] == 1
    o = db.query(M.MangoOrder).filter_by(mango_uid="100").one()
    assert o.delivery_method == "까대기"       # 해외현지배송중 -> 까대기
    assert o.delivery_method_source == "자동"


def test_upsert_preserves_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("101")])
    o = db.query(M.MangoOrder).filter_by(mango_uid="101").one()
    o.delivery_method = "직배"
    o.delivery_method_source = "수기"
    first = o.first_uploaded_at
    db.commit()
    svc.upsert_orders(db, [_row("101", mango_status="국내배송중")])  # 재업로드
    o2 = db.query(M.MangoOrder).filter_by(mango_uid="101").one()
    assert o2.delivery_method == "직배"
    assert o2.delivery_method_source == "수기"
    assert o2.first_uploaded_at == first
    assert o2.mango_status == "국내배송중"


def test_upsert_replace_stale_keeps_only_current_upload(db):
    # 최신 스냅샷: 이번 업로드에 없는 옛 주문은 삭제. 이어지는 주문은 유지(수기 방식 보존).
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("A1"), _row("A2")], replace_stale=True)
    o = db.query(M.MangoOrder).filter_by(mango_uid="A2").one()   # A2에 수기 지정
    o.delivery_method, o.delivery_method_source = "직배", "수기"
    db.commit()
    # 두 번째 업로드엔 A1 빠짐, A2 유지, A3 신규
    res = svc.upsert_orders(db, [_row("A2", mango_status="국내배송중"), _row("A3")],
                            replace_stale=True)
    uids = {x.mango_uid for x in db.query(M.MangoOrder).all()}
    assert uids == {"A2", "A3"}                     # A1(옛 주문) 삭제됨
    assert res["deleted"] == 1
    a2 = db.query(M.MangoOrder).filter_by(mango_uid="A2").one()
    assert a2.delivery_method == "직배" and a2.delivery_method_source == "수기"  # 수기 보존


def test_memo_kkadaegi_forces_method(db):
    # 간단메모(N열=memo)에 '까대기' 있으면 무조건 배송방식=까대기. 자동/일괄보다 우선.
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("M1", memo="까대기 급함"),          # 메모 까대기 → 까대기
                           _row("M2", memo="직배로", mango_status="국내배송중"),  # 메모 직배 → 직배
                           _row("M3", memo="특이사항없음")])          # 메모 없음 → 자동
    m1 = db.query(M.MangoOrder).filter_by(mango_uid="M1").one()
    m2 = db.query(M.MangoOrder).filter_by(mango_uid="M2").one()
    assert m1.delivery_method == "까대기" and m1.delivery_method_source == "메모"
    assert m2.delivery_method == "직배" and m2.delivery_method_source == "메모"
    # 메모가 일괄보다 우선(전부 직배 일괄이라도 메모 까대기가 이김)
    svc.upsert_orders(db, [_row("M4", memo="까대기")], bulk_method="직배")
    m4 = db.query(M.MangoOrder).filter_by(mango_uid="M4").one()
    assert m4.delivery_method == "까대기" and m4.delivery_method_source == "메모"


def test_memo_does_not_override_manual(db):
    # 수기 지정은 메모보다 우선(사용자가 직접 누른 게 최우선).
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("M5", memo="까대기")])
    o = db.query(M.MangoOrder).filter_by(mango_uid="M5").one()
    o.delivery_method, o.delivery_method_source = "직배", "수기"
    db.commit()
    svc.upsert_orders(db, [_row("M5", memo="까대기")])   # 재업로드해도 수기 유지
    o2 = db.query(M.MangoOrder).filter_by(mango_uid="M5").one()
    assert o2.delivery_method == "직배" and o2.delivery_method_source == "수기"


def test_is_cancel_return_detects_from_market_or_mango_status(db):
    # 미매칭(market_api_status 없음) → 더망고 M열/L열 키워드로 판정.
    class O:
        def __init__(s, m="", l="", api=None):
            s.market_status, s.mango_status, s.market_api_status = m, l, api
    assert svc.is_cancel_return(O(m="취소신청"))
    assert svc.is_cancel_return(O(l="반품/교환/취소완료"))
    assert svc.is_cancel_return(O(m="특이사항없음", l="해외현지배송중")) is False
    assert svc.is_cancel_return(O(m="배송완료")) is False


def test_is_cancel_return_prefers_real_market_status(db):
    # ★실제 마켓상태(API)가 있으면 그게 기준 — 더망고 구분자보다 우선(과분류 교정).
    class O:
        def __init__(s, m="", l="", api=None):
            s.market_status, s.mango_status, s.market_api_status = m, l, api
    # 더망고 L열은 취소완료라 해도, 실제 마켓상태가 배송완료면 취소 아님.
    assert svc.is_cancel_return(O(l="반품/교환/취소완료", api="배송완료")) is False
    assert svc.is_cancel_return(O(l="반품/교환/취소완료", api="구매확정")) is False
    # 실제 마켓상태가 취소완료/회수완료면 취소.
    assert svc.is_cancel_return(O(m="특이사항없음", api="취소완료"))
    assert svc.is_cancel_return(O(api="회수완료"))
    # 미매칭(api 없음)인 쿠팡 취소는 더망고 폴백으로 여전히 취소.
    assert svc.is_cancel_return(O(m="취소신청", api=None))


def test_cancel_type_splits_only_when_unambiguous(db):
    # 마켓상태에 한 종류만 명확하면 그것, 합쳐졌거나 없으면 '그외'.
    class O:
        def __init__(s, m=""):
            s.market_status = m
    assert svc.cancel_type(O("취소신청")) == "취소"
    assert svc.cancel_type(O("반품신청")) == "반품"
    assert svc.cancel_type(O("교환신청")) == "교환"
    assert svc.cancel_type(O("취소/반품/교환 완료")) == "그외"   # 합쳐짐 → 구분 불가
    assert svc.cancel_type(O("특이사항없음")) == "그외"


def test_clear_orders_resets_to_zero(db):
    # 「비우기」 = 더망고 주문 전량 삭제(미실시 0). 상태매핑은 보존.
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("C1"), _row("C2")])
    n = svc.clear_orders(db)
    assert n == 2
    assert db.query(M.MangoOrder).count() == 0
    assert len(db.query(M.MangoStatusMap).all()) > 0   # 상태매핑은 유지


def test_upsert_default_accumulates(db):
    # 기본(replace_stale=False)은 누적 — 부분 업로드가 옛 데이터를 지우지 않는다.
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("B1")])
    svc.upsert_orders(db, [_row("B2")])
    uids = {x.mango_uid for x in db.query(M.MangoOrder).all()}
    assert uids == {"B1", "B2"}


def test_upsert_invoice_history_and_duplicate(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("102", invoice_no="AAA")])
    svc.upsert_orders(db, [_row("102", invoice_no="BBB")])  # 다른 송장 재등장
    o = db.query(M.MangoOrder).filter_by(mango_uid="102").one()
    assert o.invoice_no == "BBB"
    assert len(o.invoice_history) == 2
    assert o.is_duplicate_invoice is True


def test_find_duplicate_invoices(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("200", invoice_no="AAA")])
    svc.upsert_orders(db, [_row("200", invoice_no="BBB")])  # 중복
    svc.upsert_orders(db, [_row("201", invoice_no="CCC")])  # 단일 → 정상
    dups = svc.find_duplicate_invoices(db)
    assert {o.mango_uid for o in dups} == {"200"}


def test_find_flow_missing(db):
    svc.seed_default_status_map(db)
    # 현지배송완료(까대기 송장입력·검사대상) + 송장전송실패 → 배송흐름 없음
    svc.upsert_orders(db, [_row("300", mango_status="현지배송완료",
                                 market_status="송장전송실패", invoice_no="X")])
    # 국내배송중(직배 검사대상) + 정상 송장 → 제외
    svc.upsert_orders(db, [_row("301", mango_status="국내배송중",
                                 market_status="송장전송완료", invoice_no="Y")])
    # 배송완료(도착=검사 제외) + 송장전송실패라도 대상 아님
    svc.upsert_orders(db, [_row("302", mango_status="배송완료",
                                 market_status="송장전송실패", invoice_no="Z")])
    # 결제완료(검사대상 아님) → 제외
    svc.upsert_orders(db, [_row("303", mango_status="결제완료", market_status="특이사항없음")])
    missing = svc.find_flow_missing(db)
    assert {o.mango_uid for o in missing} == {"300"}


def test_apply_bulk_method_skips_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("400"), _row("401")])
    o = db.query(M.MangoOrder).filter_by(mango_uid="401").one()
    o.delivery_method = "직배"
    o.delivery_method_source = "수기"
    db.commit()
    n = svc.apply_bulk_method(db, "까대기")
    assert n == 1
    assert db.query(M.MangoOrder).filter_by(mango_uid="400").one().delivery_method == "까대기"
    assert db.query(M.MangoOrder).filter_by(mango_uid="401").one().delivery_method == "직배"


def test_set_method_manual(db):
    svc.seed_default_status_map(db)
    svc.upsert_orders(db, [_row("500")])
    assert svc.set_method_manual(db, "500", "직배") is True
    o = db.query(M.MangoOrder).filter_by(mango_uid="500").one()
    assert o.delivery_method == "직배"
    assert o.delivery_method_source == "수기"
    assert svc.set_method_manual(db, "nonexist", "직배") is False


# ── v2 마켓 API 연동 ──
from datetime import datetime, timedelta, timezone


def test_market_api_fields(db):
    o = M.MangoOrder(mango_uid="m1")
    o.market_api_status = "배송준비중"
    o.market_api_invoice = "INV1"
    o.market_check_error = None
    db.add(o); db.commit()
    got = db.query(M.MangoOrder).filter_by(mango_uid="m1").one()
    assert got.market_api_status == "배송준비중"
    assert got.market_api_invoice == "INV1"


def _mk(db, uid, **kw):
    o = M.MangoOrder(mango_uid=uid, invoice_history=[])
    for k, v in kw.items():
        setattr(o, k, v)
    db.add(o); db.commit(); return o


def test_find_double_invoice_risk(db):
    _mk(db, "d1", mango_status="해외현지배송중", market_api_invoice="INV", market_check_error=None)
    _mk(db, "d2", mango_status="해외현지배송중", market_api_status="배송중", market_check_error=None)
    _mk(db, "d3", mango_status="해외현지배송중", market_api_invoice="", market_api_status="배송준비중", market_check_error=None)
    _mk(db, "d4", mango_status="해외현지배송중", market_api_invoice="INV", market_check_error="확인불가")
    risk = svc.find_double_invoice_risk(db)
    assert {o.mango_uid for o in risk} == {"d1", "d2"}


def test_find_flow_stalled(db):
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _mk(db, "s1", market_api_invoice="INV", market_api_status="배송준비중",
        invoice_history=[{"invoice": "INV", "at": old}], market_check_error=None)
    _mk(db, "s2", market_api_invoice="INV", market_api_status="배송중",
        invoice_history=[{"invoice": "INV", "at": old}], market_check_error=None)
    _mk(db, "s3", market_api_invoice="INV", market_api_status="배송준비중",
        invoice_history=[{"invoice": "INV", "at": recent}], market_check_error=None)
    _mk(db, "s4", market_api_invoice="INV", market_api_status="배송준비중",
        invoice_history=[{"invoice": "INV", "at": old}], market_check_error="확인불가")
    stalled = svc.find_flow_stalled(db)
    assert {o.mango_uid for o in stalled} == {"s1"}
