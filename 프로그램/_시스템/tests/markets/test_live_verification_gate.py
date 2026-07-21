# -*- coding: utf-8 -*-
"""라이브 검증 게이트 — 검증된 마켓만 자동 공개.

배경: 옥션·G마켓은 주문조회 코드가 다 있는데도 `SUPPORTED` 에서 빠져 있어
화면에 안 나왔다. 잠금을 푸는 유일한 방법이 '개발자가 코드 고쳐 배포'였다.
이제 사장님이 판매처관리에서 「🧪 라이브 검증」을 눌러 실주문을 대조하면
재배포 없이 열린다.

절대 규칙 — 한 계정이라도 미검증이면 그 마켓은 열리지 않는다.
그 가게 주문만 통째로 빠진 채 '전체 주문'처럼 보이는 게 가장 위험하다
(과거 11번가 같은 키 사고와 같은 계열: 조용한 누락 = 발송 사고).
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import shared.db as shared_db
from lemouton.markets import order_export as oe
from lemouton.sourcing.models_v2 import UploadAccount

NOW = _dt.datetime(2026, 7, 20, 12, 0, 0)


@pytest.fixture
def db(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    UploadAccount.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    # order_export 는 호출 시점에 `from shared.db import SessionLocal` → 속성 패치로 충분.
    monkeypatch.setattr(shared_db, "SessionLocal", Session)
    return Session


def _add(Session, market, name, prefix, verified_at=None, active=True):
    s = Session()
    try:
        s.add(UploadAccount(account_key=f"{name}_{market}", display_name=name,
                            market=market, env_prefix=prefix, is_active=active,
                            live_verified_at=verified_at))
        s.commit()
    finally:
        s.close()


def test_계정이_없으면_열리지_않는다(db):
    assert "auction" not in oe.supported_markets()


def test_계정은_있는데_미검증이면_열리지_않는다(db):
    _add(db, "auction", "가게A", "AUCTION_MAIN")
    assert "auction" not in oe.supported_markets()


def test_활성계정_전부_검증되면_열린다(db):
    _add(db, "auction", "가게A", "AUCTION_MAIN", verified_at=NOW)
    _add(db, "auction", "가게B", "AUCTION_2", verified_at=NOW)
    assert "auction" in oe.supported_markets()


def test_한_계정이라도_미검증이면_마켓_전체가_잠긴다(db):
    """가장 중요한 규칙 — 부분 공개는 그 가게 주문이 통째로 빠지는 사고."""
    _add(db, "auction", "가게A", "AUCTION_MAIN", verified_at=NOW)
    _add(db, "auction", "가게B", "AUCTION_2")          # 미검증
    assert "auction" not in oe.supported_markets()


def test_비활성_계정은_판정에서_제외된다(db):
    _add(db, "auction", "가게A", "AUCTION_MAIN", verified_at=NOW)
    _add(db, "auction", "쓰던가게", "AUCTION_2", active=False)   # 미검증이지만 비활성
    assert "auction" in oe.supported_markets()


def test_마켓끼리_섞이지_않는다(db):
    _add(db, "auction", "가게A", "AUCTION_MAIN", verified_at=NOW)
    _add(db, "gmarket", "가게A", "GMARKET_MAIN")      # G마켓은 미검증
    got = oe.supported_markets()
    assert "auction" in got and "gmarket" not in got


def test_기존_4개_마켓은_검증과_무관하게_항상_열려있다(db):
    """이미 라이브 검증이 끝난 마켓 — 이번 변경으로 닫히면 안 된다(회귀 방지)."""
    assert {"smartstore", "lotteon", "coupang", "eleven11"} <= oe.supported_markets()


def test_검증되지_않은_마켓_조회는_거부된다(db):
    _add(db, "auction", "가게A", "AUCTION_MAIN")      # 미검증
    with pytest.raises(ValueError):
        oe.order_rows("auction", days=1)


def test_송장전송_개방은_라이브검증과_무관한_별도_결정이다(db):
    """송장전송(쓰기)은 2026-07-21 사장님 지시로 **명시 배선**해 열었다 — 조회 검증이
    자동으로 연 것이 아니다. 실제 발송은 여전히 MOUM_LIVE_INVOICE 게이트(기본 OFF) 뒤.
    이 테스트는 '검증 기록이 없어도 SUPPORTED_SEND 는 정적'임을 고정한다
    (검증 여부에 따라 흔들리면 안 된다 — 쓰기 동작의 개방은 코드 리뷰를 거친 결정이어야)."""
    from lemouton.markets import invoice_send
    assert "auction" in invoice_send.SUPPORTED_SEND
    assert "gmarket" in invoice_send.SUPPORTED_SEND
    # 검증 기록을 지워도(=이 테스트 DB엔 아무 계정도 없음) 값이 변하지 않는 정적 집합이다.
    assert isinstance(invoice_send.SUPPORTED_SEND, set)


def test_DB가_없어도_터지지_않고_기본값을_준다(monkeypatch):
    """개발기·테스트에서 DB 미연결이어도 기존 4개는 동작해야 한다."""
    def _boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(shared_db, "SessionLocal", _boom)
    assert oe.supported_markets() == set(oe.SUPPORTED)
