# -*- coding: utf-8 -*-
"""2층 계정 설정 — 계정마다 하나뿐인 등록 설정.

🔴 이 파일이 지키는 것: **계정 하나에 설정 한 벌**이다. 두 벌이 생기면
   어느 값이 마켓으로 나갔는지 알 수 없다(정책마다 재입력하던 문제를 옮겨오는 꼴).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import MarketAccountSetting
from lemouton.sourcing.models_v2 import UploadAccount


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _account(db, key='르무통_본계_coupang', market='coupang'):
    acc = UploadAccount(account_key=key, display_name=key,
                        market=market, env_prefix=key.upper())
    db.add(acc)
    db.commit()
    return acc


def test_설정을_저장하고_다시_읽는다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(
        upload_account_id=acc.id, as_phone='0507-1234-5678',
        return_fee=5000, exchange_fee=10000, jeju_fee=3000))
    db.commit()

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.as_phone == '0507-1234-5678'
    assert got.return_fee == 5000
    assert got.exchange_fee == 10000
    assert got.jeju_fee == 3000


def test_계정당_한_벌만_허용한다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_phone='1'))
    db.commit()
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_phone='2'))
    with pytest.raises(IntegrityError):
        db.commit()


def test_마켓_전용_칸은_extra_에_담는다(db):
    acc = _account(db, '르무통_옥션', 'auction')
    db.add(MarketAccountSetting(
        upload_account_id=acc.id,
        extra={'shippingPlaceNo': '12345', 'returnPlaceNo': '67890',
               'dispatchPolicyNo': 'DP-1'}))
    db.commit()

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.extra['shippingPlaceNo'] == '12345'
    assert got.extra['dispatchPolicyNo'] == 'DP-1'


def test_안_정한_칸은_비어_있다(db):
    """🔴 기본값을 만들어 내지 않는다 — 가짜 A/S 번호가 실제 판매 상품에 게시되면 안 된다.

    [2026-08-24 사장님 확정으로 갱신] 「안 정함」은 빈 문자열이 아니라 **None** 이다.
    빈 문자열은 「일부러 비워 뒀다」는 뜻이라 뜻이 다르다(아래 전용 시험이 못박는다).
    """
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id))
    db.commit()

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.as_phone is None
    assert got.extra == {}


from lemouton.policy.account_settings import setting_for, value_of


def test_설정이_없으면_None_을_돌려준다(db):
    acc = _account(db)
    assert setting_for(db, acc.id) is None


def test_설정이_있으면_그_행을_돌려준다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_phone='0507-1'))
    db.commit()
    assert setting_for(db, acc.id).as_phone == '0507-1'


def test_공통칸은_컬럼에서_읽는다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, return_fee=5000))
    db.commit()
    assert value_of(db, acc.id, 'return_fee') == 5000


def test_마켓전용칸은_extra_에서_읽는다(db):
    acc = _account(db, '르무통_옥션', 'auction')
    db.add(MarketAccountSetting(upload_account_id=acc.id,
                                extra={'shippingPlaceNo': '12345'}))
    db.commit()
    assert value_of(db, acc.id, 'shippingPlaceNo') == '12345'


def test_없는_칸은_기본값을_돌려준다(db):
    """🔴 「안 정함」과 「0」을 가른다 — 기본값을 안 주면 호출부가 제각각 추측한다."""
    acc = _account(db)
    assert value_of(db, acc.id, 'shippingPlaceNo', default='없음') == '없음'


def test_설정_자체가_없어도_기본값으로_안전하게_돌아온다(db):
    acc = _account(db)
    assert value_of(db, acc.id, 'return_fee', default=0) == 0


# ── [2026-08-24 사장님 확정] 「안 정함」과 「0원」은 다르다 ────────────────────
#   실측으로 잡은 사고 — default=0/nullable=False 로 두면 아직 안 정한 계정과
#   0원이라고 정한 계정이 둘 다 0 으로 읽혔다. 배송비는 금전 직결이라 이 혼동이
#   곧 손실이다. 아래 시험들이 그 구분을 못박는다.

from lemouton.policy.account_settings import is_set
from lemouton.policy.models import DEFAULT_FEES


def test_안_정한_금액은_None_이지_0이_아니다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id))
    db.commit()

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.return_fee is None
    assert got.exchange_fee is None
    assert got.return_fee != 0          # 🔴 0 으로 읽히면 안 된다


def test_0원이라고_정하면_0으로_읽힌다(db):
    """무료 반품(0원)과 미설정은 다른 뜻이다."""
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, return_fee=0))
    db.commit()

    assert value_of(db, acc.id, 'return_fee', default=None) == 0
    assert is_set(db, acc.id, 'return_fee') is True


def test_안_정한_것과_0원을_갈라_읽는다(db):
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id))
    db.commit()
    assert value_of(db, acc.id, 'return_fee', default=None) is None
    assert is_set(db, acc.id, 'return_fee') is False

    row = db.query(MarketAccountSetting).one()
    row.return_fee = 0
    db.commit()
    assert value_of(db, acc.id, 'return_fee', default=None) == 0
    assert is_set(db, acc.id, 'return_fee') is True


def test_일부러_비운_문자열도_정한_것이다(db):
    """🔴 빈 문자열을 「안 정함」으로 되돌리면 이 시험이 깨진다.

    A/S 안내를 일부러 비워 두는 것과 아직 안 쓴 것은 다르다.
    """
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id, as_message=''))
    db.commit()

    assert value_of(db, acc.id, 'as_message', default='기본안내') == ''
    assert is_set(db, acc.id, 'as_message') is True


def test_기본_반품비는_편도_5천_교환은_왕복_1만(db):
    """사장님 확정 기본값 — 새 계정을 만들 때 화면이 이 값을 넣어 준다."""
    assert DEFAULT_FEES['return_fee'] == 5000
    assert DEFAULT_FEES['exchange_fee'] == 10000
    assert DEFAULT_FEES['exchange_fee'] == DEFAULT_FEES['return_fee'] * 2


def test_기본값을_모델이_몰래_채우지_않는다(db):
    """🔴 새 행을 만들었다고 5,000 이 들어가 있으면 「안 정함」이 사라진다."""
    acc = _account(db)
    db.add(MarketAccountSetting(upload_account_id=acc.id))
    db.commit()

    got = db.query(MarketAccountSetting).one()
    assert got.return_fee is None       # DEFAULT_FEES 가 자동으로 안 들어감
