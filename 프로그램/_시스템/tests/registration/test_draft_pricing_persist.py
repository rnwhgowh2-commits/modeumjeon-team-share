# -*- coding: utf-8 -*-
"""대량등록 수기 입력 — 「6 매입가·마진」 6칸의 **저장·복원** (Phase 1B M2-저장).

M2 는 6칸을 화면에 만들었지만 ProductDraft 에 컬럼이 없어 미리보기 전용이었다
(화면을 벗어나면 값이 사라졌다). 이 테스트가 지키는 것:

  1) 입력한 값이 실제로 DB 에 저장된다.
  2) 다시 열면 그대로 복원된다.
  3) **빈 값이 기본값으로 채워지지 않는다** — '안 고름'(''·NULL)과 '없음'('none')은
     계산 결과가 다른 별개의 값이다. 뭉개면 사장님이 의도적으로 비운 것인지
     프로그램이 채운 것인지 영영 알 수 없다.
  4) 저장된 값으로 최종매입가·마진이 계산된다 (폼 값 없이 draft_id 만으로).
  5) 마이그레이션이 **컬럼 없는 기존 테이블**에 실제로 붙는다 (create_all 은 안 붙인다).
  6) 결제카드 키가 컬럼 폭 안에 들어간다 — 개발기(SQLite)는 길이를 무시해
     라이브(PostgreSQL)에서만 깨지는 유형이라, 테스트가 유일한 방어선이다.
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _mk_source(templates):
    """SourceRegistry 1건 + 혜택 템플릿 N건 → source_id.

    (tests/registration/test_manual_margin.py 의 동일 헬퍼와 같은 모양)
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing.models import SourceBenefitTemplate
    s = SessionLocal()
    try:
        src = SourceRegistry(name='저장테스트소싱처-' + uuid.uuid4().hex[:8],
                             main_url='https://example.test')
        s.add(src)
        s.commit()
        for i, (nm, bt, val, extra) in enumerate(templates):
            s.add(SourceBenefitTemplate(
                source_id=src.id, benefit_name=nm, benefit_type=bt, value=val,
                enabled=True, sort_order=i, **(extra or {})))
        s.commit()
        return src.id
    finally:
        s.close()


def _create(client, **extra):
    body = {'name': '저장테스트 상품', 'sale_price': 139000}
    body.update(extra)
    r = client.post('/bulk/api/drafts', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['draft_id']


def _get(client, did):
    r = client.get(f'/bulk/api/drafts/{did}')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()['draft']


# ── 1) 저장된다 ───────────────────────────────────────────────────────────────

def test_pricing_inputs_are_persisted_to_db(client):
    """6칸이 ProductDraft 컬럼에 실제로 들어간다 (라우트 응답이 아니라 DB 를 본다)."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    did = _create(client, source_id=sid, surface_price=116900,
                  inflow='cashback', card_key='none', naver_pay='on',
                  cashback_name='OK캐시백')

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).one()
        assert d.pricing_source_id == sid
        assert d.surface_price == 116900
        assert d.pricing_inflow == 'cashback'
        assert d.pricing_card_key == 'none'
        assert d.pricing_naver_pay == 'on'
        assert d.pricing_cashback_name == 'OK캐시백'
    finally:
        s.close()


# ── 2) 다시 열면 복원된다 ─────────────────────────────────────────────────────

def test_reopen_restores_every_pricing_field(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    sent = {'source_id': sid, 'surface_price': 116900, 'inflow': 'naver_via',
            'card_key': 'none', 'naver_pay': 'off', 'cashback_name': 'none'}
    did = _create(client, **sent)
    got = _get(client, did)
    for k, v in sent.items():
        assert got[k] == v, f'{k} 이 복원되지 않았다: {got[k]!r} != {v!r}'


def test_update_then_reopen_keeps_same_row(client):
    """열기 → 수정 → 저장이 **같은 행**을 덮는다 (새 행을 만들면 중복·모순)."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    did = _create(client, source_id=sid, surface_price=100000, inflow='')
    r = client.put(f'/bulk/api/drafts/{did}',
                   json={'surface_price': 116900, 'inflow': 'naver_via'})
    assert r.status_code == 200, r.get_data(as_text=True)
    got = _get(client, did)
    assert got['id'] == did
    assert got['surface_price'] == 116900
    assert got['inflow'] == 'naver_via'
    # 안 보낸 칸은 그대로 남는다 (부분 수정이 나머지를 지우면 안 된다)
    assert got['source_id'] == sid


def test_update_does_not_wipe_unsent_pricing_fields(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    did = _create(client, source_id=sid, surface_price=100000,
                  inflow='cashback', cashback_name='OK캐시백')
    client.put(f'/bulk/api/drafts/{did}', json={'name': '이름만 수정'})
    got = _get(client, did)
    assert got['inflow'] == 'cashback'
    assert got['cashback_name'] == 'OK캐시백'
    assert got['surface_price'] == 100000


# ── 3) 빈 값이 기본값으로 채워지지 않는다 (안 고름 ≠ 없음) ────────────────────

def test_absent_fields_stay_null_not_defaulted(client):
    """아예 안 보낸 칸은 NULL 로 남는다 — ''(소싱처 기본값)로 둔갑하면 안 된다."""
    did = _create(client)   # 6칸 전부 미전송
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).one()
        for col in ('pricing_source_id', 'surface_price', 'pricing_inflow',
                    'pricing_card_key', 'pricing_naver_pay',
                    'pricing_cashback_name'):
            assert getattr(d, col) is None, (
                f'{col} 이 NULL 이 아니다 — 안 고른 칸이 기본값으로 채워졌다')
    finally:
        s.close()
    got = _get(client, did)
    for k in ('source_id', 'surface_price', 'inflow', 'card_key',
              'naver_pay', 'cashback_name'):
        assert got[k] is None, f'{k} 복원값이 null 이 아니다: {got[k]!r}'


def test_empty_string_stays_empty_string(client):
    """''(소싱처 기본값으로 남겨둠)는 ''로 저장된다 — NULL 로도, 'none'으로도 안 바뀐다."""
    did = _create(client, inflow='', card_key='', naver_pay='',
                  cashback_name='')
    got = _get(client, did)
    for k in ('inflow', 'card_key', 'naver_pay', 'cashback_name'):
        assert got[k] == '', f'{k} 가 ''로 유지되지 않았다: {got[k]!r}'


def test_not_chosen_and_explicit_none_are_different_values(client):
    """'안 고름'('')과 '없음'('none')이 서로 다른 값으로 남는다.

    둘을 뭉개면 계산이 갈린다 — ''는 소싱처 혜택을 그대로 쓰고, 'none'은 그 축의
    혜택을 전부 끈다.
    """
    blank = _get(client, _create(client, inflow='', card_key=''))
    none_ = _get(client, _create(client, inflow='none', card_key='none'))
    assert blank['inflow'] == '' and none_['inflow'] == 'none'
    assert blank['card_key'] == '' and none_['card_key'] == 'none'
    assert blank['inflow'] != none_['inflow']


def test_surface_price_zero_is_not_null(client):
    """표면가 0 은 '미입력'이 아니다 — 0 과 NULL 을 구분한다."""
    zero = _get(client, _create(client, surface_price=0))
    absent = _get(client, _create(client))
    assert zero['surface_price'] == 0
    assert absent['surface_price'] is None


def test_bad_choice_is_400_not_silently_stored(client):
    """유효하지 않은 선택지는 400 — 조용히 저장돼 나중에 계산을 깨뜨리면 안 된다."""
    r = client.post('/bulk/api/drafts', json={
        'name': '상품X', 'sale_price': 10000, 'inflow': '아무거나'})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.get_json()['ok'] is False


# ── 4) 저장값으로 계산된다 ────────────────────────────────────────────────────

def test_margin_preview_uses_stored_values_from_draft_id(client):
    """폼 값을 하나도 안 보내고 draft_id 만 줘도 저장값으로 계산된다.

    116,900 − 5,000(리뷰적립) = 111,900 → 네이버페이 1% = −1,119 → 110,781
    → 백원 버림 → 110,700. (엔진이 내는 숫자이고 여기서 산수하지 않는다)
    """
    sid = _mk_source([
        ('리뷰적립', 'amount', 5000, None),
        ('네이버페이 적립', 'rate', 0.01, None),
    ])
    did = _create(client, source_id=sid, surface_price=116900,
                  sale_price=139000, naver_pay='on')

    r = client.post('/bulk/api/margin-preview', json={'draft_id': did})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j['ok'] is True
    assert j['surface_price'] == 116900     # 저장된 표면가를 썼다는 증거
    assert j['final_price'] == 110700
    assert j['sale_price'] == 139000        # 저장된 판매가로 마진을 냈다
    assert j['margin'] == 139000 - 110700

    # 같은 입력을 엔진에 직접 넣은 결과와 일치 (라우트가 엔진을 탄다는 증거)
    from shared.db import SessionLocal
    from lemouton.pricing.final_price import compute_final_price
    from webapp.routes.bulk.margin import build_effective
    s = SessionLocal()
    try:
        eff, _w = build_effective(
            s, source_id=sid, choices={'naver_pay': 'on'})
        assert compute_final_price(116900, eff)['final_price'] == j['final_price']
    finally:
        s.close()


def test_stored_none_turns_the_benefit_off(client):
    """저장된 'none'(없음 명시)이 계산에 실제로 반영된다 — ''와 금액이 달라야 한다."""
    tpls = [('리뷰적립', 'amount', 5000, None),
            ('네이버페이 적립', 'rate', 0.01, None)]
    sid_a = _mk_source(tpls)
    sid_b = _mk_source(tpls)
    off = _create(client, source_id=sid_a, surface_price=116900,
                  sale_price=139000, naver_pay='off')
    on = _create(client, source_id=sid_b, surface_price=116900,
                 sale_price=139000, naver_pay='on')
    j_off = client.post('/bulk/api/margin-preview',
                        json={'draft_id': off}).get_json()
    j_on = client.post('/bulk/api/margin-preview',
                       json={'draft_id': on}).get_json()
    assert j_off['ok'] and j_on['ok']
    assert j_off['final_price'] > j_on['final_price'], (
        '네이버페이 off/on 이 같은 금액이면 저장값이 계산에 안 쓰인 것이다')


def test_form_value_overrides_stored_value(client):
    """화면이 보낸 칸은 방금 고른 값으로 계산한다(미리보기) — 저장값을 덮는다."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    did = _create(client, source_id=sid, surface_price=100000, sale_price=139000)
    j = client.post('/bulk/api/margin-preview',
                    json={'draft_id': did, 'surface_price': 116900}).get_json()
    assert j['ok'] is True
    assert j['surface_price'] == 116900


def test_margin_preview_without_draft_id_still_works(client):
    """draft_id 없이 폼 값만 보내는 기존 경로가 그대로 돈다 (M2 회귀 방지)."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    r = client.post('/bulk/api/margin-preview',
                    json={'source_id': sid, 'surface_price': 116900,
                          'sale_price': 139000})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['ok'] is True


def test_margin_preview_unknown_draft_is_404_not_silent(client):
    """없는 draft_id 는 404 — 조용히 폼 값만으로 돌면 '저장값 반영됨'으로 오해한다."""
    r = client.post('/bulk/api/margin-preview',
                    json={'draft_id': 99999999, 'surface_price': 1000})
    assert r.status_code == 404, r.get_data(as_text=True)
    assert r.get_json()['ok'] is False


# ── 5) 마이그레이션이 컬럼 없는 기존 테이블에 실제로 붙는다 ────────────────────

NEW_COLUMNS = ('pricing_source_id', 'surface_price', 'pricing_inflow',
               'pricing_card_key', 'pricing_naver_pay', 'pricing_cashback_name')


def test_migration_adds_columns_to_existing_table_without_them(tmp_path, monkeypatch):
    """★ 빈 DB 가 아니라 **컬럼 없는 기존 테이블**에서 검증한다.

    Alembic 이 없고 create_all 은 기존 테이블에 컬럼을 추가하지 않는다. 라이브
    (Supabase PostgreSQL)의 product_drafts 는 Phase 1A 로 이미 존재하므로,
    shared/db.py 의 ADD COLUMN 리스트가 **유일한 경로**다. 빈 DB 로 테스트하면
    create_all 이 컬럼을 만들어 버려 마이그레이션이 죽어 있어도 통과한다
    (= 라이브에서만 터지는 조용한 실패). 그래서 여기서는 컬럼을 일부러 뺀
    테이블을 먼저 만들고, 그 위에 마이그레이션을 돌린다.
    """
    from sqlalchemy import create_engine, inspect, text

    db = tmp_path / 'legacy.db'
    engine = create_engine(f'sqlite:///{db}')

    # ① 신규 컬럼이 **없는** 옛 product_drafts 를 손으로 만든다 (라이브 현재 상태 재현)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE product_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin VARCHAR(16) NOT NULL DEFAULT 'bulk',
                source VARCHAR(16) NOT NULL DEFAULT 'manual',
                name VARCHAR(255) NOT NULL,
                sale_price INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'draft',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )"""))
        conn.execute(text(
            "INSERT INTO product_drafts (name, sale_price, created_at, updated_at)"
            " VALUES ('기존행', 39000, '2026-07-18 00:00:00', '2026-07-18 00:00:00')"))

    before = {c['name'] for c in inspect(engine).get_columns('product_drafts')}
    assert not (before & set(NEW_COLUMNS)), '전제 위반: 컬럼이 이미 있으면 검증이 무의미'

    # ② 앱이 부팅할 때와 똑같이 init_db() 를 돌린다.
    #    _apply_lightweight_migrations 는 모듈 전역 engine 을 쓰므로 그걸 갈아끼운다.
    import shared.db as sdb
    monkeypatch.setattr(sdb, 'engine', engine)

    # ②-a 먼저 create_all 만으로는 **안 붙는다**는 것을 확인한다.
    #     (이게 안 깨지면 마이그레이션이 죽어 있어도 이 테스트가 통과해 버린다)
    sdb.Base.metadata.create_all(engine)
    only_create_all = {c['name'] for c in inspect(engine).get_columns('product_drafts')}
    assert not (only_create_all & set(NEW_COLUMNS)), (
        'create_all 이 기존 테이블에 컬럼을 붙였다 — 전제가 바뀌었으니 이 테스트를 다시 짜라')

    # ②-b init_db() = create_all + ADD COLUMN. 여기서 비로소 붙어야 한다.
    sdb.init_db()

    after = {c['name'] for c in inspect(engine).get_columns('product_drafts')}
    missing = [c for c in NEW_COLUMNS if c not in after]
    assert not missing, (
        f'ADD COLUMN 이 안 붙었다 — 라이브(기존 테이블)에서 저장이 깨진다: {missing}')

    # ③ 붙은 컬럼이 기존 행에는 NULL 이어야 한다 (DEFAULT 로 가짜 선택을 만들지 않았다)
    with engine.begin() as conn:
        row = conn.execute(text(
            'SELECT ' + ', '.join(NEW_COLUMNS) + ' FROM product_drafts')).fetchone()
    assert all(v is None for v in row), (
        f'기존 행에 기본값이 채워졌다 — 사장님이 고르지 않은 값이 저장된 셈: {row}')

    # ④ 멱등 — 두 번 돌려도 터지지 않는다
    sdb._apply_lightweight_migrations()
    engine.dispose()


def test_model_declares_the_same_columns_as_migration():
    """모델과 마이그레이션 리스트가 어긋나지 않게 한다.

    fresh DB 는 create_all(모델)이, 기존 DB 는 ADD COLUMN(리스트)이 만든다.
    한쪽만 늘어나면 개발기와 라이브의 스키마가 갈린다.
    """
    import inspect as _pyinspect
    import shared.db as sdb
    from lemouton.registration.models import ProductDraft

    src = _pyinspect.getsource(sdb._apply_lightweight_migrations)
    for col in NEW_COLUMNS:
        assert col in ProductDraft.__table__.columns, f'모델에 {col} 없음'
        assert f'"{col}"' in src, f'shared/db.py 마이그레이션 리스트에 {col} 없음'


# ── 6) 컬럼 폭 가드 ───────────────────────────────────────────────────────────

def test_card_key_column_fits_every_purchase_card_key():
    """모든 결제카드 키가 pricing_card_key 폭 안에 들어가야 한다.

    ■ 개발기에서 절대 안 잡히는 유형
      개발 워크트리는 .env 없이 SQLite 로 뜨는데 SQLite 는 VARCHAR 길이를 강제하지
      않아 조용히 통과한다. 라이브(Supabase PostgreSQL)에서만 저장이 깨진다.
      이 프로젝트에서 실제로 당했다 — 카드 키가 pay_method VARCHAR(16) 을 넘겨
      라이브에서만 실패했다. 그래서 이 테스트가 유일한 방어선이다.

      폭을 넓히는 건 shared/db.py 에 ADD COLUMN 밖에 없어 사실상 불가능하다
      → 넓히는 쪽이 아니라 키를 줄이는 쪽이 답이다.
    """
    from lemouton.registration.models import ProductDraft
    from lemouton.margin import purchase_card_store as PCS

    width = ProductDraft.__table__.columns['pricing_card_key'].type.length
    over = [(key, len(key)) for (key, _lab, _r, _h) in PCS.PURCHASE_CARD_SEED
            if len(key) > width]
    assert not over, (
        f'카드키가 pricing_card_key 폭({width}자)을 초과 — 라이브(PostgreSQL)에서만 '
        f'저장이 깨진다. 키를 줄여라.\n'
        + '\n'.join(f'  - {k!r}: {n}자' for k, n in over))


def test_card_key_column_is_not_narrower_than_purchase_card_key():
    """purchase_cards.key 에 저장 가능한 키는 여기에도 반드시 들어가야 한다."""
    from lemouton.registration.models import ProductDraft
    from lemouton.margin.models import PurchaseCard
    assert (ProductDraft.__table__.columns['pricing_card_key'].type.length
            >= PurchaseCard.__table__.columns['key'].type.length)


def test_cashback_name_column_matches_benefit_name_width():
    """캐시백 항목명은 benefit_name 에서 그대로 온다 — 좁으면 긴 이름이 잘린다."""
    from lemouton.registration.models import ProductDraft
    from lemouton.sourcing.models import SourceBenefitTemplate
    assert (ProductDraft.__table__.columns['pricing_cashback_name'].type.length
            >= SourceBenefitTemplate.__table__.columns['benefit_name'].type.length)


def test_oversized_card_key_is_400_not_truncated(client):
    """폭을 넘는 값은 400 으로 막는다 — 개발기에서 조용히 통과하면 라이브에서 깨진다."""
    from lemouton.registration.models import ProductDraft
    width = ProductDraft.__table__.columns['pricing_card_key'].type.length
    r = client.post('/bulk/api/drafts', json={
        'name': '상품Y', 'sale_price': 10000, 'card_key': 'x' * (width + 1)})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert r.get_json()['ok'] is False
