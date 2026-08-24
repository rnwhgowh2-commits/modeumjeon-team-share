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


# ══ [Phase 2] 마켓별 허용 키 — 오타를 조용히 삼키지 않는다 ═══════════════════

from lemouton.policy.account_settings import (           # noqa: E402
    MARKET_EXTRA_KEYS, UnknownSettingKey, allowed_keys, set_extra,
)

_MARKETS = ('smartstore', 'coupang', 'auction', 'gmarket', 'eleven11', 'lotteon')


def test_허용키_목록이_6마켓_전부_있다():
    for m in _MARKETS:
        assert allowed_keys(m), f'{m} 허용키가 비었다'


def test_옥션과_G마켓은_같은_칸을_쓴다():
    """ESM 공용 — 갈라 두면 한쪽만 저장되는 사고가 난다."""
    assert MARKET_EXTRA_KEYS['auction'] == MARKET_EXTRA_KEYS['gmarket']


def test_그_마켓_칸이면_저장된다(db):
    acc = _account(db)
    set_extra(db, acc.id, 'coupang', {'discountRate': 10})
    db.commit()
    assert value_of(db, acc.id, 'discountRate') == 10


def test_그_마켓에_없는_칸은_저장을_거부한다(db):
    """🔴 오타 난 키가 조용히 저장되면 「왜 안 먹지」로 한참 헤맨다."""
    acc = _account(db)
    with pytest.raises(UnknownSettingKey, match='쿠팡'):
        set_extra(db, acc.id, 'coupang', {'owhpNo': '123'})   # 롯데ON 칸이다


def test_거부_문구에_어느_칸이_문제인지_나온다(db):
    acc = _account(db)
    with pytest.raises(UnknownSettingKey, match='retrunFee'):
        set_extra(db, acc.id, 'coupang', {'retrunFee': 5000})  # 오타


def test_JSON_칸이_실제로_저장된다(db):
    """🔴 SQLAlchemy 는 JSON 을 제자리에서 고치면 못 알아챈다 — 조용한 저장 실패."""
    acc = _account(db)
    set_extra(db, acc.id, 'lotteon', {'owhpNo': 'OW1'})
    db.commit()
    set_extra(db, acc.id, 'lotteon', {'rtrpNo': 'RT2'})
    db.commit()
    db.expire_all()

    got = db.query(MarketAccountSetting).filter_by(upload_account_id=acc.id).one()
    assert got.extra == {'owhpNo': 'OW1', 'rtrpNo': 'RT2'}   # 먼저 넣은 것도 남아 있다


def test_자격증명은_허용키에_없다():
    """🔴 시크릿 단일 원천은 .env — DB 이중 저장 금지가 이 저장소 규칙이다."""
    secretish = {'apiKey', 'apiSecret', 'secretKey', 'accessKey',
                 'clientSecret', 'clientId', 'vendorId', 'apiKeyProd'}
    for m in _MARKETS:
        assert not (allowed_keys(m) & secretish), f'{m} 에 자격증명 칸이 섞였다'


def test_재고_기본값은_허용키에_없다():
    """🔴 「재고는 소싱처 실제 재고로만」 — 삼바의 999 기본값을 들이면 안 된다."""
    for m in _MARKETS:
        assert 'stockQuantity' not in allowed_keys(m)


def test_쿠팡_출고지반품지는_허용키에_없다():
    """이미 coupang_vendor_settings 가 갖고 있다 — 두 벌이면 어느 쪽이 나갔는지 못 쫓는다."""
    assert 'outboundShippingPlaceCode' not in allowed_keys('coupang')
    assert 'returnCenterCode' not in allowed_keys('coupang')


def test_롯데온_행사제외_5칸이_있다():
    """마켓이 우리 마진을 깎는 행사에서 빠지는 스위치 — 금전 직결."""
    for k in ('ownerDiscountExclude', 'unitCouponExclude', 'deliveryCouponExclude',
              'cmPcsExclude', 'pcsExclude'):
        assert k in allowed_keys('lotteon')


def test_ESM_출고지는_주소가_아니라_번호다():
    """정책의 「출하지 주소」 자유입력으로는 대체할 수 없다 — 미리 등록해 둔 번호다."""
    for k in ('shippingPlaceNo', 'returnPlaceNo', 'dispatchPolicyNo'):
        assert k in allowed_keys('auction')


def test_공용칸은_전부_빈값을_받는다():
    """🔴 [2026-08-24 실서버에서 잡음] 이 표는 처음에 NOT NULL 로 배포됐다.

    나중에 「안 정함=빈 값」으로 규칙을 바꿨지만, 이미 만들어진 표의 제약은
    `create_all` 이 안 고친다. 그래서 실서버에서만 설정 행이 **아예 안 만들어졌고**
    기본 배송비 5,000/10,000 이 안 들어갔다. 시험은 매번 새 표를 만들어 통과했다.

    여기서는 모델 정의가 다시 NOT NULL 로 돌아가는 것을 막는다.
    실제 표의 제약 해제는 `shared/db.py` 의 마이그레이션이 맡는다.
    """
    from lemouton.policy.models import MarketAccountSetting

    공용칸 = ('as_phone', 'as_message', 'return_fee', 'exchange_fee',
              'jeju_fee', 'island_fee', 'tax_type', 'origin_default',
              'stock_default', 'promotion_message')
    막힌칸 = [c for c in 공용칸
              if not MarketAccountSetting.__table__.columns[c].nullable]
    assert not 막힌칸, (
        f'{막힌칸} 이 빈 값을 못 받는다 — 「안 정함」과 「0원」을 구분할 수 없게 된다')


def test_옛_표의_NOT_NULL_을_푸는_마이그레이션이_있다():
    """실서버(PostgreSQL)에 이미 만들어진 표의 제약을 푸는 코드가 살아 있나."""
    import pathlib

    소스 = (pathlib.Path(__file__).resolve().parents[2] / 'shared' / 'db.py').read_text(
        encoding='utf-8')
    assert 'market_account_settings' in 소스 and 'DROP NOT NULL' in 소스, (
        '옛 표의 NOT NULL 을 푸는 마이그레이션이 사라졌다 — '
        '배포된 서버에서 설정 행이 안 만들어진다')


def test_옛_표를_고치면서_자료를_잃지_않는다(tmp_path):
    """🔴 [2026-08-24 실측] 첫 시도는 표를 먼저 밀어내고 새로 지었는데,

    새 표 짓기가 실패해서(FK 대상 표가 다른 메타데이터에 있어 못 찾았다)
    원본이 `__old` 라는 이름으로 뜬 채 남고 **화면에서는 자료가 사라져 보였다**.
    그래서 순서를 뒤집었다 — 새 표를 먼저 짓고 마지막에 원본을 지운다.

    여기서는 「옛 표(NOT NULL) → 고친 뒤에도 행이 그대로」를 실제 DB 로 확인한다.
    """
    import sqlalchemy as sa
    from sqlalchemy import inspect, text

    import shared.db as D

    db = tmp_path / 'old.db'
    eng = sa.create_engine(f'sqlite:///{db}')
    with eng.begin() as c:
        c.execute(text('CREATE TABLE upload_accounts (id INTEGER PRIMARY KEY)'))
        c.execute(text('''CREATE TABLE market_account_settings (
            id INTEGER NOT NULL PRIMARY KEY, upload_account_id INTEGER NOT NULL UNIQUE,
            as_phone VARCHAR(32) NOT NULL, as_message TEXT NOT NULL,
            return_fee INTEGER NOT NULL, exchange_fee INTEGER NOT NULL,
            jeju_fee INTEGER NOT NULL, island_fee INTEGER NOT NULL,
            tax_type VARCHAR(16) NOT NULL, origin_default VARCHAR(64) NOT NULL,
            stock_default INTEGER NOT NULL, promotion_message VARCHAR(200) NOT NULL,
            extra JSON, updated_at DATETIME,
            FOREIGN KEY(upload_account_id) REFERENCES upload_accounts (id))'''))
        c.execute(text("INSERT INTO market_account_settings VALUES "
                       "(7,9,'010-1','안내',5000,10000,3000,5000,'T','KR',0,'홍보','{}',NULL)"))

    원래 = D.engine
    try:
        D.engine = eng
        D._apply_lightweight_migrations()
    finally:
        D.engine = 원래

    with eng.connect() as c:
        막힌칸 = [x['name'] for x in inspect(c).get_columns('market_account_settings')
                 if not x['nullable']]
        assert 막힌칸 == ['id', 'upload_account_id'], f'제약이 안 풀렸다: {막힌칸}'

        행 = c.execute(text('SELECT upload_account_id, as_phone, return_fee, jeju_fee '
                            'FROM market_account_settings')).fetchall()
        assert 행 == [(9, '010-1', 5000, 3000)], f'자료가 바뀌었다: {행}'

        찌꺼기 = [r[0] for r in c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'market_account_settings%'"))]
        assert 찌꺼기 == ['market_account_settings'], f'찌꺼기 표가 남았다: {찌꺼기}'

        # 이제 「안 정함」을 실제로 넣을 수 있어야 한다
        c.execute(text('INSERT INTO market_account_settings (upload_account_id) VALUES (99)'))
        c.commit()
        assert c.execute(text('SELECT as_phone, jeju_fee FROM market_account_settings '
                              'WHERE upload_account_id=99')).fetchone() == (None, None)
    eng.dispose()
