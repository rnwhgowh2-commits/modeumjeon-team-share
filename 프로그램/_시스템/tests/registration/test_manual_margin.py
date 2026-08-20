# -*- coding: utf-8 -*-
"""수기 등록 — 최종매입가·마진 미리보기 (Phase 1B M2).

이 테스트가 지키는 것:
  1) 화면 금액이 **서버 엔진(compute_final_price)** 출력과 같다. 백원 버림까지.
     (JS 가 산수를 다시 짜면 파이썬과 어긋나 화면가 ≠ 업로드가가 된다)
  2) 4개 입력이 override 로 실제 금액을 바꾼다.
  3) 반영할 근거가 없으면 **추정치를 만들지 않고 경고로 드러낸다** (폴백 금지).
  4) 계산 불가 상황에서 0원을 돌려주지 않는다.
  5) 소싱처 템플릿 ORM 행을 변형하지 않는다 (M1-3 공유객체 오염 사고 재발 방지).
"""
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _mk_source(templates):
    """SourceRegistry 1건 + 혜택 템플릿 N건을 만들고 source_id 를 돌려준다.

    templates: [(이름, 'rate'|'amount', 값, {추가 컬럼})]
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing.models import SourceBenefitTemplate
    s = SessionLocal()
    try:
        src = SourceRegistry(name='테스트소싱처-' + uuid.uuid4().hex[:8],
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


def _preview(client, **body):
    r = client.post('/bulk/api/margin-preview', json=body)
    return r, r.get_json()


# ── 1) 엔진과 같은 금액 ───────────────────────────────────────────────────────

def test_preview_equals_engine_including_floor(client):
    """리뷰적립 5,000원(정액) → 네이버페이 1%(잔액 기준) → 백원 버림.

    116,900 − 5,000 = 111,900 → −1,119 = 110,781 → 백원 버림 → 110,700.
    (르무통 공홈 정답 순서와 같은 모양 — 정액 먼저, 정률은 직전 잔액 기준)
    """
    sid = _mk_source([
        ('리뷰적립', 'amount', 5000, None),
        ('네이버페이 적립', 'rate', 0.01, None),
    ])
    r, j = _preview(client, source_id=sid, surface_price=116900, sale_price=139000)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert j['ok'] is True
    assert j['final_price'] == 110700
    assert j['margin'] == 139000 - 110700

    # 같은 입력을 엔진에 직접 넣은 결과와 일치해야 한다 (라우트가 엔진을 탄다는 증거)
    from shared.db import SessionLocal
    from lemouton.pricing.final_price import compute_final_price
    from webapp.routes.bulk.margin import build_effective
    s = SessionLocal()
    try:
        eff, _w = build_effective(s, source_id=sid, choices={})
        assert compute_final_price(116900, eff)['final_price'] == j['final_price']
    finally:
        s.close()


def test_steps_are_receipt_shaped(client):
    """영수증(steps)이 매트릭스 fx 영수증과 같은 계약을 지킨다."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    _r, j = _preview(client, source_id=sid, surface_price=100000)
    assert j['steps'], '차감 단계가 있어야 한다'
    st = j['steps'][0]
    for k in ('name', 'type', 'value', 'deduct', 'base_after'):
        assert k in st, f'steps 계약 위반 — {k} 없음'
    assert st['deduct'] == 5000
    assert st['base_after'] == 95000


# ── 2) 4개 입력이 실제로 금액을 바꾼다 ───────────────────────────────────────

def test_card_choice_injects_accrual(client):
    """결제카드를 고르면 그 카드의 적립율이 차감된다 (PurchaseCard = 단일 진실 원천).

    116,900 −5,000 =111,900 → 네이버페이 1% −1,119 =110,781
      → 롯데프로페셔널 2% −2,215 =108,566 → 백원 버림 → 108,500.
    """
    sid = _mk_source([
        ('리뷰적립', 'amount', 5000, None),
        ('네이버페이 적립', 'rate', 0.01, None),
    ])
    _r, base = _preview(client, source_id=sid, surface_price=116900)
    _r2, withcard = _preview(client, source_id=sid, surface_price=116900,
                             card_key='lotte_prof')
    assert withcard['ok'] is True
    assert withcard['final_price'] == 108500
    assert withcard['final_price'] < base['final_price'], '카드를 골랐는데 매입가가 그대로다'


def test_naver_pay_off_removes_deduction(client):
    """네이버페이 X → 그 적립은 빠진다 (116,900 −5,000 = 111,900)."""
    sid = _mk_source([
        ('리뷰적립', 'amount', 5000, None),
        ('네이버페이 적립', 'rate', 0.01, None),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=116900, naver_pay='off')
    assert j['final_price'] == 111900
    assert not any('네이버' in (st['name'] or '') for st in j['steps'])


def test_inflow_none_turns_off_cashback(client):
    """유입경로 '없음' → 캐시백 항목 비활성."""
    sid = _mk_source([
        ('OK캐시백 적립', 'rate', 0.025, {'apply_mode': 'cashback'}),
    ])
    _r, on = _preview(client, source_id=sid, surface_price=100000, inflow='cashback')
    _r2, off = _preview(client, source_id=sid, surface_price=100000, inflow='none')
    assert on['final_price'] < off['final_price']
    assert off['final_price'] == 100000


def test_cashback_site_pick_is_exclusive(client):
    """캐시백사이트를 고르면 그것만 적용된다 (택1)."""
    sid = _mk_source([
        ('OK캐시백 3%', 'rate', 0.03, {'apply_mode': 'cashback'}),
        ('OK캐시백 1%', 'rate', 0.01, {'apply_mode': 'cashback'}),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=100000,
                     inflow='cashback', cashback_name='OK캐시백 1%')
    names = [st['name'] for st in j['steps']]
    assert 'OK캐시백 1%' in names
    assert 'OK캐시백 3%' not in names


def test_card_none_disables_card_benefits(client):
    """'카드 없음' → 카드 혜택 전부 비활성."""
    sid = _mk_source([
        ('삼성카드 청구할인', 'rate', 0.07, {'apply_mode': 'payment',
                                             'pay_method': 'samsung_select'}),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=100000, card_key='none')
    assert j['final_price'] == 100000
    assert j['steps'] == []


def test_card_billed_discount_and_accrual_both_apply(client):
    """카드 1장 = 적립율 + 청구할인 **둘 다** 차감 (사용자 확정 모델)."""
    sid = _mk_source([
        ('삼성카드 청구할인', 'rate', 0.07, {'apply_mode': 'payment',
                                             'pay_method': 'samsung_select'}),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=100000,
                     card_key='samsung_select')
    names = ' '.join(st['name'] for st in j['steps'])
    assert '청구할인' in names, '청구할인이 빠졌다'
    assert '적립' in names, '카드 적립율이 빠졌다'


# ── 3) 근거 없으면 지어내지 않는다 ───────────────────────────────────────────

def test_naver_pay_on_without_item_warns_and_does_not_invent(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    _r, j = _preview(client, source_id=sid, surface_price=100000, naver_pay='on')
    assert j['final_price'] == 95000, '없는 적립율을 지어내면 안 된다'
    assert any('네이버페이' in w for w in j['warnings']), j['warnings']


def test_cashback_inflow_without_item_warns(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    _r, j = _preview(client, source_id=sid, surface_price=100000, inflow='cashback')
    assert j['final_price'] == 95000
    assert any('캐시백' in w for w in j['warnings']), j['warnings']


def test_cashback_not_swallowed_by_card_path(client):
    """캐시백은 카드와 **별개 축** — 카드 청구할인이 있어도 함께 차감된다.

    라이브 검증에서 잡힌 회귀: 카드 미선택(소싱처 기본값)일 때 OK캐시백이 결제
    택1 경로로 묶여 통째로 사라졌다(매입가 101,900 vs 99,400 = 2,500원 과대).
    """
    sid = _mk_source([
        ('OK캐시백 적립', 'rate', 0.025, {'apply_mode': 'cashback'}),
        ('삼성카드 청구할인', 'rate', 0.07, {'apply_mode': 'payment',
                                             'pay_method': 'samsung_select'}),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=100000)
    names = ' '.join(st['name'] for st in j['steps'])
    assert '캐시백' in names, '캐시백이 카드 경로에 먹혔다'
    assert '청구할인' in names, '청구할인이 빠졌다'


def test_cashback_base_ratio_survives_choice_proxy(client):
    """★ 캐시백 base_ratio(공급가 계수 0.9)가 _Choice 프록시를 **통과**해야 한다.

    [2026-07-22 품질검토 Critical] TaggedProxy 와 같은 클래스의 유실 버그 —
    _Choice.__slots__ 에 base_ratio 가 없으면 수기입력 미리보기에서 캐시백이
    전액 기준으로 계산돼 10% **과다 차감** = 매입가 과소 = 마진 과대 착각 =
    언더프라이싱(이 저장소가 가장 경계하는 방향). 시드행(lotteon OK캐시백
    1.1% × base_ratio 0.9)과 같은 모양으로 라우트 끝까지 태워 못 박는다.

    기대: 100,000 → OK캐시백 int(100,000×0.9×1.1%) = 989 → 99,011 → 백원버림 99,000.
    base_ratio 가 떨어지면 1,100 차감 → 98,900 (100원 과소).
    """
    sid = _mk_source([
        ('OK캐시백', 'rate', 0.011,
         {'apply_mode': 'cashback', 'category': '캐시백', 'base_ratio': 0.9}),
    ])
    _r, j = _preview(client, source_id=sid, surface_price=100000)
    assert j['ok'] is True
    assert [st['name'] for st in j['steps']] == ['OK캐시백']
    st = j['steps'][0]
    assert st['base_ratio'] == pytest.approx(0.9), (
        '_Choice 가 base_ratio 를 떨어뜨렸다 — 캐시백 10% 과다 차감(매입가 과소)')
    assert st['deduct'] == 989
    assert j['final_price'] == 99000


def test_no_benefits_source_warns(client):
    sid = _mk_source([])
    _r, j = _preview(client, source_id=sid, surface_price=100000)
    assert j['final_price'] == 100000
    assert j['warnings'], '혜택 0건이면 그 사실을 알려야 한다'


# ── 4) 계산 불가는 0원이 아니라 에러 ─────────────────────────────────────────

def test_missing_surface_price_is_error_not_zero(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    r, j = _preview(client, source_id=sid)
    assert r.status_code == 400
    assert j['ok'] is False
    assert 'final_price' not in j


def test_missing_source_is_error(client):
    r, j = _preview(client, surface_price=100000)
    assert r.status_code == 400
    assert j['ok'] is False


def test_unknown_card_key_is_error_not_silent(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    r, j = _preview(client, source_id=sid, surface_price=100000,
                    card_key='존재하지않는카드')
    assert r.status_code == 400
    assert j['ok'] is False


def test_bad_number_is_400_not_500(client):
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    r, _j = _preview(client, source_id=sid, surface_price='abc')
    assert r.status_code == 400, r.get_data(as_text=True)


def test_margin_none_when_sale_price_missing(client):
    """판매가 미입력 → 마진은 0 이 아니라 None (0 은 '마진 0원'이라는 뜻 있는 값)."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    _r, j = _preview(client, source_id=sid, surface_price=100000)
    assert j['margin'] is None
    assert j['sale_price'] is None


def test_negative_margin_is_surfaced(client):
    """역마진은 숨기지 않는다 — 음수 그대로 내려온다(화면은 빨강)."""
    sid = _mk_source([('리뷰적립', 'amount', 5000, None)])
    _r, j = _preview(client, source_id=sid, surface_price=100000, sale_price=90000)
    assert j['margin'] == 90000 - 95000
    assert j['margin'] < 0


# ── 5) 공유 ORM 객체 불변 (M1-3 사고 재발 방지) ─────────────────────────────

def test_templates_are_not_mutated(client):
    """override 로 항목을 꺼도 DB 의 템플릿 enabled 는 True 로 남아야 한다."""
    sid = _mk_source([
        ('네이버페이 적립', 'rate', 0.01, None),
        ('삼성카드 청구할인', 'rate', 0.07, {'apply_mode': 'payment',
                                             'pay_method': 'samsung_select'}),
    ])
    _preview(client, source_id=sid, surface_price=100000,
             naver_pay='off', card_key='none')
    from shared.db import SessionLocal
    from lemouton.sourcing.models import SourceBenefitTemplate
    s = SessionLocal()
    try:
        rows = s.query(SourceBenefitTemplate).filter_by(source_id=sid).all()
        assert rows and all(r.enabled is True for r in rows), \
            '템플릿 ORM 행이 변형됐다 — 다른 계산까지 오염된다'
    finally:
        s.close()


# ── 화면 ─────────────────────────────────────────────────────────────────────

def test_manual_page_has_margin_inputs(client):
    html = client.get('/bulk/?tab=manual').get_data(as_text=True)
    for f in ('pr_source_id', 'pr_surface_price', 'pr_inflow', 'pr_card_key',
              'pr_naver_pay', 'pr_cashback_name'):
        assert f'name="bd_{f}"' in html, f'입력칸 없음: {f}'
    assert 'id="bmg-final"' in html
    assert 'id="bmg-margin"' in html


def test_margin_meta_lists_sources_and_cards(client):
    sid = _mk_source([('OK캐시백 적립', 'rate', 0.025, {'apply_mode': 'cashback'})])
    j = client.get(f'/bulk/api/margin-meta?source_id={sid}').get_json()
    assert j['ok'] is True
    assert any(x['id'] == sid for x in j['sources'])
    assert any(c['key'] == 'nexon_hyundai' for c in j['cards']), '카드 마스터가 비었다'
    assert [c['name'] for c in j['cashback_items']] == ['OK캐시백 적립']
