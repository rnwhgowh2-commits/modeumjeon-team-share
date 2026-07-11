# -*- coding: utf-8 -*-
"""[TEST] 송장 원장 — 한 번 본 송장번호를 영구 보관, 나중에 '확인 불가' 채우기.

배경: 11번가는 구매확정 주문의 송장번호(invcNo)를 어떤 API로도 안 준다. 배송중·배송완료
때 본 번호를 저장해두면, 구매확정으로 넘어가 API가 빼먹어도 우리 저장분으로 채운다.
과거에 이미 구매확정돼 한 번도 못 본 주문은 복구 불가(정직하게 '확인 불가' 유지).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    """이 테스트 전용 인메모리 DB — 공유 DB 를 건드리지 않는다.

    전체 메타데이터(다른 모델의 FK)까지 만들면 미등록 테이블 해석에 실패하므로,
    필요한 invoice_ledger 테이블 하나만 생성한다.
    """
    from lemouton.sourcing.models_v2 import InvoiceLedger
    eng = create_engine("sqlite:///:memory:")
    InvoiceLedger.__table__.create(eng)
    # 프로덕션 SessionLocal 과 동일하게 autoflush=False — s.get 이 미flush 형제를 안 봐
    # 배치 내 중복 PK 가 실제로 재현된다(autoflush=True 면 이 버그가 가려진다).
    s = sessionmaker(bind=eng, autoflush=False, future=True)()
    yield s
    s.close()


def _row(market, order_no, inv, status):
    return {"판매처": market, "오픈마켓주문번호": order_no,
            "송장입력": inv, "주문상태": status}


class TestRemember:
    def test_stores_shipped_rows_with_real_invoice(self, session):
        from lemouton.markets.invoice_ledger import remember
        rows = [_row("11번가", "O1", "9988776655", "배송완료"),
                _row("11번가", "O2", "123", "배송중")]
        remember(rows, session=session)

        from lemouton.sourcing.models_v2 import InvoiceLedger
        got = {r.order_no: r.invoice_no for r in session.query(InvoiceLedger).all()}
        assert got == {"O1": "9988776655", "O2": "123"}

    def test_ignores_empty_and_sentinel_invoices(self, session):
        from lemouton.markets.invoice_ledger import remember
        from lemouton.sourcing.models_v2 import InvoiceLedger
        rows = [_row("11번가", "O1", "확인 불가", "구매확정"),
                _row("11번가", "O2", "송장미입력", "결제완료"),
                _row("11번가", "O3", "", "배송완료")]
        remember(rows, session=session)
        assert session.query(InvoiceLedger).count() == 0    # 저장할 진짜 번호가 없다

    def test_ignores_non_shipped_rows(self, session):
        """발송 전(결제완료·배송준비중)에 어쩌다 번호가 있어도 저장 대상 아님(오염 방지)."""
        from lemouton.markets.invoice_ledger import remember
        from lemouton.sourcing.models_v2 import InvoiceLedger
        remember([_row("쿠팡", "O1", "111", "결제완료")], session=session)
        assert session.query(InvoiceLedger).count() == 0

    def test_upsert_updates_not_duplicates(self, session):
        from lemouton.markets.invoice_ledger import remember
        from lemouton.sourcing.models_v2 import InvoiceLedger
        remember([_row("11번가", "O1", "111", "배송중")], session=session)
        remember([_row("11번가", "O1", "222", "배송완료")], session=session)
        rows = session.query(InvoiceLedger).all()
        assert len(rows) == 1 and rows[0].invoice_no == "222"

    def test_duplicate_key_in_one_batch_does_not_crash(self, session):
        """★ 라이브 버그: 11번가는 한 주문에 상품라인이 여러 개 → 같은 (판매처,주문번호)가
        한 배치에 중복. flush 전이라 s.get 이 형제를 못 봐 중복 PK 로 commit 이 터지면
        배치 전체가 롤백돼 0건 저장된다. 중복은 마지막 값으로 합쳐 1건만 저장해야 한다."""
        from lemouton.markets.invoice_ledger import remember
        from lemouton.sourcing.models_v2 import InvoiceLedger
        rows = [_row("11번가", "ORD1", "111", "배송완료"),   # 상품라인 1
                _row("11번가", "ORD1", "111", "배송완료"),   # 상품라인 2 (같은 송장)
                _row("11번가", "ORD2", "222", "배송완료")]
        saved = remember(rows, session=session)
        stored = {r.order_no: r.invoice_no for r in session.query(InvoiceLedger).all()}
        assert stored == {"ORD1": "111", "ORD2": "222"}   # 터지지 않고 2건
        assert saved >= 2

    def test_same_order_no_different_market_are_separate(self, session):
        from lemouton.markets.invoice_ledger import remember
        from lemouton.sourcing.models_v2 import InvoiceLedger
        remember([_row("11번가", "O1", "111", "배송완료"),
                  _row("쿠팡", "O1", "999", "배송완료")], session=session)
        assert session.query(InvoiceLedger).count() == 2


class TestFillMissing:
    def test_fills_unknown_from_ledger(self, session):
        from lemouton.markets.invoice_ledger import remember, fill_missing
        # 먼저 배송완료 때 저장
        remember([_row("11번가", "O1", "9988776655", "배송완료")], session=session)
        # 나중에 구매확정으로 넘어와 번호가 '확인 불가'
        rows = [_row("11번가", "O1", "확인 불가", "구매확정")]
        n = fill_missing(rows, session=session)
        assert n == 1
        assert rows[0]["송장입력"] == "9988776655"

    def test_leaves_pre_shipment_alone(self, session):
        """발송 전 '송장미입력'은 채우지 않는다(아직 송장 없는 게 맞다)."""
        from lemouton.markets.invoice_ledger import fill_missing
        rows = [_row("11번가", "O1", "송장미입력", "결제완료")]
        fill_missing(rows, session=session)
        assert rows[0]["송장입력"] == "송장미입력"

    def test_unknown_not_in_ledger_stays_unknown(self, session):
        """저장된 적 없는 과거 주문은 정직하게 '확인 불가' 유지(지어내지 않음)."""
        from lemouton.markets.invoice_ledger import fill_missing
        rows = [_row("11번가", "GHOST", "확인 불가", "구매확정")]
        fill_missing(rows, session=session)
        assert rows[0]["송장입력"] == "확인 불가"

    def test_does_not_overwrite_real_number(self, session):
        from lemouton.markets.invoice_ledger import remember, fill_missing
        remember([_row("11번가", "O1", "OLD", "배송완료")], session=session)
        rows = [_row("11번가", "O1", "NEW-FROM-API", "배송완료")]
        fill_missing(rows, session=session)
        assert rows[0]["송장입력"] == "NEW-FROM-API"    # API 실값 우선

    def test_roundtrip_capture_then_fill(self, session):
        """배송완료 조회에서 잡고 → 다음 구매확정 조회에서 채운다(전체 흐름)."""
        from lemouton.markets.invoice_ledger import remember, fill_missing
        # 1차: 배송완료 목록 (번호 있음)
        remember([_row("11번가", "A", "111", "배송완료")], session=session)
        # 2차: 같은 주문이 구매확정으로 (번호 사라짐)
        later = [_row("11번가", "A", "확인 불가", "구매확정")]
        remember(later, session=session)          # 여기선 저장할 진짜 번호 없음(무해)
        fill_missing(later, session=session)
        assert later[0]["송장입력"] == "111"
