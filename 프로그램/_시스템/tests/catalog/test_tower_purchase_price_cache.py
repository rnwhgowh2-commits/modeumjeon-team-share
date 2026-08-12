# -*- coding: utf-8 -*-
"""🔴 재발 감시 — 실매입가를 저장하면 상품관리 「판매 이력」이 **즉시** 바뀐다.

## 무엇이 났었나 (라이브 실측 2026-08-06 — 추측 아님)

주문 내역에서 실매입가 50,000 을 저장한 **직후** 판매 이력을 열면
`realized:null, pp_missing:27`(옛 값)이 나왔다. 같은 순간 `days=29` 로 물으면
캐시 키가 달라 새로 계산돼 `realized:60545, realized_basis:1` 로 정상이었다.
→ 계산은 맞았고 **300초 서버 캐시만 낡아** 있었다. 돈 화면이라 사장님은
「저장이 안 됐나?」로 읽는다(그래서 이 시험이 있다).

## 여기서 못 박는 네 가지

1. 저장 직후 **같은 기간**을 물어도 새 값이 나온다 (이번 버그 그 자리)
2. 더망고 매입 엑셀 업로드 뒤에도 마찬가지다
3. 매입가를 **지운** 뒤에도 즉시 반영된다 (지움은 `updated_at` 을 안 올린다 — 함정)
4. **워커가 둘이어도** 통한다 (캐시는 프로세스 메모리 → 저장을 못 받은 워커도 알아채야)

4번이 핵심이다. 저장을 받은 워커만 캐시를 비우면, 라이브(워커 2개)에서는
새로고침할 때마다 값이 왔다갔다 하는 **더 나쁜 그림**이 된다.
"""
import io
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _fresh_caches():
    """시험끼리 캐시를 물려주지 않는다."""
    from webapp.routes import bundles_tower as T
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None
    yield
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None


@pytest.fixture
def sold():
    """상품 1 + 옵션 1 + 세트 채널(주문→SKU 매칭용) + 판매 주문 2건.

    주문 → SKU 매칭은 `price_diff` 가 SetChannel⋈SetChannelOption 으로 하므로
    실제로 만들어 둔다(매칭 규칙을 시험이 흉내 내지 않는다).
    주문 행에 `_line_uid` 를 심는다 — 더망고 엑셀 경로(`order_store.load`)가
    그 값으로 주문 줄을 잡는다.
    """
    from datetime import date

    import app as appmod                     # noqa: F401 — 모델 등록 + 테이블 생성
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.markets.models_purchase import OrderLinePurchase
    from lemouton.orders.fulfillment import SETTLE_FIELD
    from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8]
    code = f'캐시테스트_{tag}'
    sku = f'SKU-PPC{tag[:5].upper()}'
    # 상품명에 5자리 이상 숫자가 있어야 더망고 매칭의 「상품코드」가 생긴다
    pname = f'캐시테스트상품 {10000 + int(tag[:4], 16) % 80000}'
    uid_paid = f'ppc-paid-{tag}'
    uid_bare = f'ppc-bare-{tag}'
    order_paid = f'PPC{tag}A'
    order_bare = f'PPC{tag}B'

    s = SessionLocal()
    made = {}
    try:
        s.add(Model(model_code=code, model_name_raw=code, model_name_display=code,
                    brand='르무통', display_no=f'M20260806-{tag[:6]}'))
        s.add(Option(canonical_sku=sku, model_code=code,
                     color_code='블랙', size_code='250'))
        s.flush()
        pset = ProductSet(model_code=code, name=f'세트-{code}')
        s.add(pset)
        s.flush()
        ch = SetChannel(set_id=pset.id, market='smartstore', account_key='default',
                        market_product_id=f'SS-{tag}', status='linked')
        s.add(ch)
        s.flush()
        s.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku,
                               market_option_id=f'VI-{tag}', status='matched'))
        made = {'set_id': pset.id, 'ch_id': ch.id}

        today = date.today().isoformat()
        base = {'판매처': '스마트스토어', '상품명': pname, '옵션': '블랙 250',
                '_pd_market_option_id': f'VI-{tag}', '쇼핑몰별칭': '계정1'}
        for uid, no, settle in ((uid_paid, order_paid, 90000),
                                (uid_bare, order_bare, 70000)):
            row = dict(base, 오픈마켓주문번호=no, 수량='1', 상품금액='100000',
                       주문상태='배송완료', 주문일=f'{today} 10:00',
                       _line_uid=uid)
            row[SETTLE_FIELD] = str(settle)
            s.add(MarketOrderLine(line_uid=uid, market='smartstore', order_no=no,
                                  order_date=f'{today} 10:00', status='배송완료',
                                  account='계정1', row=row))
        s.commit()
        yield {'code': code, 'sku': sku, 'name': pname,
               'uid_paid': uid_paid, 'uid_bare': uid_bare,
               'order_paid': order_paid, 'order_bare': order_bare}
    finally:
        s.rollback()
        s.query(OrderLinePurchase).filter(
            OrderLinePurchase.line_uid.in_([uid_paid, uid_bare])).delete(
                synchronize_session=False)
        s.query(MarketOrderLine).filter(
            MarketOrderLine.line_uid.in_([uid_paid, uid_bare])).delete(
                synchronize_session=False)
        if made:
            s.query(SetChannelOption).filter(
                SetChannelOption.channel_id == made['ch_id']).delete()
            s.query(SetChannel).filter(SetChannel.id == made['ch_id']).delete()
            s.query(ProductSet).filter(ProductSet.id == made['set_id']).delete()
        s.query(Option).filter(Option.model_code == code).delete()
        s.query(Model).filter(Model.model_code == code).delete()
        s.commit()
        s.close()


def _sales(client, code, days=60):
    """🔴 `fresh=1` 을 **안** 붙인다 — 캐시를 타는 길이라야 이 버그를 본다."""
    return client.get(
        f'/bundles/api/tower/{code}/sales?days={days}').get_json()


# ── ① 저장 직후 — 같은 기간에 새 값 ────────────────────────────────────────

def test_매입가_저장_직후_같은_기간_조회에_새_값이_나온다(client, sold):
    """이번 버그 그 자리. 같은 days 를 두 번 물어도 두 번째가 새 값이라야 한다."""
    code = sold['code']
    before = _sales(client, code)['total']
    assert before['realized'] is None, '아직 매입가가 없으니 「확인 불가」'
    assert before['pp_missing'] == 2

    r = client.post('/orders/api/purchase-price',
                    json={'line_uid': sold['uid_paid'], 'price': 60000})
    assert r.get_json()['ok'], r.get_json()

    after = _sales(client, code)['total']
    assert after['realized'] == 30000, (
        '저장 직후인데 옛 값이 나왔다 — 판매 이력 캐시(300초)가 안 비워졌다. '
        f'실제: {after}')
    assert after['realized_basis'] == 1
    assert after['purchase'] == 60000
    assert after['pp_missing'] == 1


def test_저장_요청이_이_워커의_캐시를_즉시_비운다(client, sold):
    """빠른 길(같은 워커) 자체를 못 박는다 — 조회를 기다리지 않고 그 자리에서 비운다."""
    from webapp.routes import bundles_tower as T
    code = sold['code']
    _sales(client, code)
    with T._cache_lock:
        assert 60 in T._sales_cache, '먼저 캐시가 차 있어야 시험이 성립한다'

    client.post('/orders/api/purchase-price',
                json={'line_uid': sold['uid_paid'], 'price': 60000})
    with T._cache_lock:
        assert not T._sales_cache, (
            '저장을 받고도 이 워커 캐시가 남아 있다 — 무효화 호출이 빠졌다')


def test_기간_키가_여러_개라도_전부_비워진다(client, sold):
    """🔴 라이브에서 days=30 만 낡고 days=29 는 멀쩡했다 — 기간별로 키가 갈린다."""
    code = sold['code']
    for d in (7, 30, 60):
        assert _sales(client, code, days=d)['total']['realized'] is None

    client.post('/orders/api/purchase-price',
                json={'line_uid': sold['uid_paid'], 'price': 60000})

    for d in (7, 30, 60):
        t = _sales(client, code, days=d)['total']
        assert t['realized'] == 30000, f'days={d} 만 옛 값으로 남았다: {t}'


# ── ② 더망고 매입 엑셀 ─────────────────────────────────────────────────────

def _mango_xlsx(rows) -> bytes:
    """더망고 매입 엑셀 최소본 — `buy_parser.parse_buy` 의 필수 칸만 채운다."""
    import pandas as pd
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()


def test_엑셀_업로드_뒤에도_즉시_반영된다(client, sold):
    """엑셀은 한 번에 여러 줄이 바뀐다 — 그래서 통째로 버린다."""
    from datetime import date
    code = sold['code']
    assert _sales(client, code)['total']['realized'] is None

    data = _mango_xlsx([{
        '마켓주문일자': date.today().isoformat(), '마켓명': '스마트스토어',
        '마켓주문번호': sold['order_paid'], '수령인명': '홍길동',
        '마켓상품명': sold['name'], '옵션1': '블랙 250', '구매정보': '',
        '구매가격': 60000,
    }])
    r = client.post('/orders/api/purchase-price/upload-mango',
                    data={'file': (io.BytesIO(data), '매입.xlsx')},
                    content_type='multipart/form-data')
    j = r.get_json()
    assert j['ok'], j
    assert j['saved'] == 1, f'엑셀이 주문 줄에 안 붙었다 — 시험 전제가 깨졌다: {j}'

    t = _sales(client, code)['total']
    assert t['realized'] == 30000, f'엑셀 업로드 뒤에도 옛 값이 나왔다: {t}'
    assert t['realized_basis'] == 1


# ── ③ 삭제(0 저장) ─────────────────────────────────────────────────────────

def test_매입가를_지우면_즉시_사라진다(client, sold):
    """🔴 지움은 `updated_at` 을 안 올린다 — 「마지막 변경 시각」만 보면 못 잡는다.

    그래서 도장에 **행 수**가 같이 들어간다. 이 시험이 그 반쪽을 지킨다.
    """
    code = sold['code']
    client.post('/orders/api/purchase-price',
                json={'line_uid': sold['uid_paid'], 'price': 60000})
    assert _sales(client, code)['total']['realized'] == 30000

    r = client.post('/orders/api/purchase-price',
                    json={'line_uid': sold['uid_paid'], 'price': 0})
    j = r.get_json()
    assert j['ok'] and j['deleted'] is True, j

    t = _sales(client, code)['total']
    assert t['realized'] is None, f'지웠는데 실현 마진이 남아 있다: {t}'
    assert t['purchase'] == 0
    assert t['pp_missing'] == 2


def test_도장은_지움도_잡는다(sold):
    """도장 자체를 눈으로 확인 — 저장·수정·삭제가 **모두** 도장을 바꾼다."""
    from shared.db import SessionLocal
    from lemouton.markets import purchase_price as PP
    from webapp.routes import bundles_tower as T

    s = SessionLocal()
    try:
        st0 = T.purchase_stamp(s)
        PP.upsert(s, line_uid=sold['uid_paid'], price=60000,
                  source=PP.SOURCE_MANUAL)
        st1 = T.purchase_stamp(s)
        assert st1 != st0, '신규 저장이 도장을 안 바꿨다'
        PP.upsert(s, line_uid=sold['uid_paid'], price=61000,
                  source=PP.SOURCE_MANUAL)
        st2 = T.purchase_stamp(s)
        assert st2 != st1, '값 수정이 도장을 안 바꿨다'
        PP.delete(s, sold['uid_paid'])
        st3 = T.purchase_stamp(s)
        assert st3 != st2, '삭제가 도장을 안 바꿨다 — 행 수를 안 세고 있다'
        assert st3 == st0, '되돌리면 도장도 되돌아온다'
    finally:
        s.close()


# ── ④ 워커가 둘일 때 ───────────────────────────────────────────────────────

def test_저장을_못_받은_워커도_새_값을_준다(client, sold):
    """🔴 라이브 워커 2개. 캐시는 프로세스 메모리라 저장 알림은 **한 워커만** 받는다.

    저장을 못 받은 워커 B 를 흉내 낸다 — 저장 전에 뜬 캐시를 그대로 되돌려 놓고
    조회한다. 그래도 새 값이 나와야 한다(DB 도장으로 스스로 알아채기 때문).
    안 그러면 새로고침마다 값이 왔다갔다 하는, 낡은 것보다 나쁜 그림이 된다.
    """
    from webapp.routes import bundles_tower as T
    code = sold['code']

    # 워커 A·B 가 똑같이 옛 집계를 들고 있는 상태
    assert _sales(client, code)['total']['realized'] is None
    with T._cache_lock:
        worker_b = dict(T._sales_cache)
    assert worker_b, '시험 전제 — 캐시가 차 있어야 한다'

    # 저장은 워커 A 가 받는다
    r = client.post('/orders/api/purchase-price',
                    json={'line_uid': sold['uid_paid'], 'price': 60000})
    assert r.get_json()['ok']

    # 이제 우리는 워커 B — 그 호출을 못 받았으니 옛 캐시가 그대로다
    with T._cache_lock:
        T._sales_cache.clear()
        T._sales_cache.update(worker_b)
        assert 60 in T._sales_cache

    t = _sales(client, code)['total']
    assert t['realized'] == 30000, (
        '저장을 못 받은 워커가 옛 값을 그대로 줬다 — 무효화가 프로세스 안에만 있다. '
        f'실제: {t}')
    assert t['pp_missing'] == 1


def test_매입가가_안_바뀌면_다시_계산하지_않는다(client, sold):
    """도장을 넣었다고 캐시가 무력화되면 안 된다 — 안 바뀌었으면 그대로 쓴다."""
    from webapp.routes import bundles_tower as T
    code = sold['code']
    _sales(client, code)
    with T._cache_lock:
        ts_first = T._sales_cache[60][0]

    _sales(client, code)
    with T._cache_lock:
        assert T._sales_cache[60][0] == ts_first, (
            '아무것도 안 바뀌었는데 다시 계산했다 — 목록이 매번 느려진다')


# ── 겉 목록 가격 캐시(price_index)는 매입가와 무관하다 ─────────────────────

def test_가격열_캐시는_매입가와_무관해서_안_건드린다(client, sold):
    """겉 목록의 매입→판매·마진 열(`price_index`)은 `order_line_purchases` 를 안 읽는다.

    그 열의 원천은 소싱처 크롤값(최종매입가)과 정책 판매가다 — 실매입가를
    적어도 값이 안 변한다. 그래서 저장 때 **일부러 안 비운다**(비우면 목록 한 판을
    쓸데없이 다시 계산해 「매우 느려」진다. 그 이유로 TTL 을 60→300 초로 올린 자리다).

    「최근 30일 판매」 열(수량·매출)은 `sales_index` 를 쓰므로 이미 같이 갱신된다 —
    매출·수량 자체는 매입가와 무관하지만 한 캐시라 따로 둘 이유가 없다.
    """
    from webapp.routes import bundles_tower as T
    assert client.get('/bundles').status_code == 200
    with T._cache_lock:
        assert T._price_cache is not None
        price_ts = T._price_cache[0]

    client.post('/orders/api/purchase-price',
                json={'line_uid': sold['uid_paid'], 'price': 60000})
    with T._cache_lock:
        assert T._price_cache is not None, '가격 열 캐시를 같이 버리면 안 된다'
        assert T._price_cache[0] == price_ts
