# -*- coding: utf-8 -*-
"""[TEST] 정책 배송비·반품비·원산지가 ProductDraft 컬럼 기본값에 막히던 버그.

배경 (2026-08-20 사장님 질문): 「정책에서 배송비·원산지를 기본값으로 정해 두면
실제로 반영되는 거 아니냐」.

버그였던 것: `_apply_shipping`/`_apply_origin`(process_apply.py) 은 `_is_blank(cur)`
로 「아직 안 정함」을 판정해 **빈 칸만** 정책값으로 채운다. 그런데:
  · `webapp/routes/bulk/drafts.py:create_draft()` 는 배송비·반품비를 안 넣으면
    그 자리에서 3000·5000 을 확정값으로 박았다.
  · `origin_area_code` 는 모델 컬럼 기본값('0200037')이 커밋 시점에 채웠다.
결과: 「사람이 3,000원이라 직접 입력함」과 「아무도 안 건드려 기본값이 그대로임」이
`_is_blank` 로는 구분되지 않아, 정책이 다른 값을 정해도 절대 반영되지 않았다.

고친 것: 컬럼 기본값을 없애 NULL(=안 정함)과 사람이 정한 값을 구분하고, 그래도
필요한 「아무도 안 정했을 때의 최종 기본값」은 `process_apply.apply_operational_fallbacks()`
가 정책·사람 값을 다 따진 **컴파일 직전에만** 채운다(`service.prepare_compile_draft`).

★ `tests/registration/test_process_apply_all_items.py` 의 `_draft()` 는
  `SimpleNamespace(delivery_fee=None, ...)` 로 직접 만든 가짜라 이 문제를 가렸다 —
  실제 `ProductDraft` 행이 아니라서 생성 라우트도, 컬럼 기본값도 겪지 않는다.
  여기서는 **실제 생성 라우트로 만든 실제 행**을 써서 재현·고정한다
  (test_process_apply_wiring.py 와 같은 관례: 진짜 Flask client + 진짜 SQLite DB).
"""
import pytest

from lemouton.registration import process_apply as PA

SRC = 'zzpolicyfallback_src'


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("LIVE_REGISTER_ARMED", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def bag():
    """이 파일이 심은 행을 되돌린다(test_process_apply_wiring.py 와 같은 관례)."""
    kept = {'drafts': [], 'policies': []}
    yield kept
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for model, ids in ((ProductDraft, kept['drafts']),
                           (ProcessPolicy, kept['policies'])):
            for rid in ids:
                row = s.query(model).filter_by(id=rid).first()
                if row is not None:
                    s.delete(row)
        s.commit()
    except Exception:      # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _make_policy(bag, *, brand, rules, market=''):
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import (
        attach_source, create_policy, set_rule)
    s = SessionLocal()
    try:
        p = create_policy(s, name=f'폴백테스트정책-{brand}')
        attach_source(s, policy_id=p.id, source_key=SRC, brand=brand)
        for key, cfg in rules.items():
            set_rule(s, policy_id=p.id, item_key=key, config=cfg, market=market)
        s.commit()
        bag['policies'].append(p.id)
        return p.id
    finally:
        s.close()


def _make_draft(client, bag, *, brand, name='재현용 상품', **over):
    """생성 라우트로 실제 행을 만든다 — 배송비 등을 안 주면 라우트가 스스로 채운다.

    화면에서 상품을 새로 만들 때 배송비 칸을 안 건드리는 것과 같은 입력이다.
    """
    body = {'name': name, 'brand': brand, 'sale_price': 39000,
            'stock_quantity': 5, 'notice_type': 'WEAR'}
    body.update(over)
    res = client.post('/bulk/api/drafts', json=body).get_json()
    assert res.get('ok'), res
    did = res['draft_id']
    bag['drafts'].append(did)
    # 생성 라우트는 source_site 를 안 받는다(크롤 전용 칸) — 정책 매칭을 위해 직접 심는다.
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        d.source_site = SRC
        s.commit()
    finally:
        s.close()
    return did


# ── 고친 뒤 전제 — 아무도 안 건드리면 저장값은 NULL 로 비어 있어야 한다 ─────────

def test_생성_라우트는_안_건드린_배송비_반품비를_NULL로_남긴다(client, bag):
    """전제 확인. 이게 실패하면 아래 재현 시험도 의미가 없다.

    ★ 예전엔 여기서 3000·5000 이 확정 저장됐다(그게 버그였다) — 이제는 NULL 이다.
    """
    did = _make_draft(client, bag, brand='폴백브랜드0')
    got = client.get(f'/bulk/api/drafts/{did}').get_json()['draft']
    assert got['delivery_fee'] is None, '배송비를 여전히 확정값으로 박고 있다'
    assert got['return_fee'] is None, '반품비를 여전히 확정값으로 박고 있다'


def test_원산지_컬럼은_이제_기본값을_안_박는다(client, bag):
    did = _make_draft(client, bag, brand='폴백브랜드0b')
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        assert d.origin_area_code is None, '원산지 컬럼이 여전히 기본값을 박고 있다'
    finally:
        s.close()


# ── 핵심 재현·고정 — 정책값이 실제로 반영되는가 ────────────────────────────────

def test_정책_배송비가_이제_컬럼_기본값에_안_막히고_반영된다(client, bag):
    """사장님이 물은 그 시나리오: 정책에서 배송비를 2,500원으로 정하면
    아무도 안 건드린 초안(=예전엔 컬럼 기본값 3,000원)에도 실제로 반영돼야 한다."""
    _make_policy(bag, brand='폴백브랜드1',
                 rules={'shipping': {'fee_mode': 'paid', 'fee_amount': 2500}})
    did = _make_draft(client, bag, brand='폴백브랜드1')   # delivery_fee 안 줌

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import resolve_rules_for_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        rules, notes, collect_words = resolve_rules_for_draft(s, d, '')
        assert 'shipping' in rules, f'정책 규칙을 못 찾았다(시험 설정 오류): {notes}'
        view, applied, skipped = PA.apply_rules(d, rules, market='',
                                                collect_banned_words=collect_words)
        assert view.delivery_fee == 2500, (
            f'정책 배송비(2,500원)가 반영되지 않았습니다 — 여전히 '
            f'{view.delivery_fee}원입니다: '
            f'{[s for s in skipped if s.get("item") == "shipping"]}')
        assert d.delivery_fee is None, '저장값을 건드렸다 — 사본에서만 가공해야 한다'
    finally:
        s.close()


def test_정책_원산지가_이제_컬럼_기본값에_안_막히고_반영된다(client, bag):
    """같은 시나리오를 원산지로: 정책이 '중국'으로 고정하면 아무도 안 건드린
    초안(=예전엔 컬럼 기본값 국내산 '0200037')에도 실제로 반영돼야 한다."""
    _make_policy(bag, brand='폴백브랜드2',
                 rules={'origin': {'mode': 'fixed', 'fixed_value': '중국'}})
    did = _make_draft(client, bag, brand='폴백브랜드2')   # 원산지 칸 자체가 없음

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import resolve_rules_for_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        rules, notes, collect_words = resolve_rules_for_draft(s, d, '')
        assert 'origin' in rules, f'정책 규칙을 못 찾았다(시험 설정 오류): {notes}'
        view, applied, skipped = PA.apply_rules(d, rules, market='',
                                                collect_banned_words=collect_words)
        assert view.origin_area_code == '중국', (
            f'정책 원산지("중국")가 반영되지 않았습니다 — 여전히 '
            f'{view.origin_area_code!r} 입니다: '
            f'{[s for s in skipped if s.get("item") == "origin"]}')
    finally:
        s.close()


def test_사람이_직접_넣은_배송비는_정책이_여전히_안_덮는다(client, bag):
    """회귀 방지 — 이 프로젝트 최상위 규율(사람 값이 규칙보다 우선)은 그대로여야 한다."""
    _make_policy(bag, brand='폴백브랜드1b',
                 rules={'shipping': {'fee_mode': 'paid', 'fee_amount': 2500}})
    did = _make_draft(client, bag, brand='폴백브랜드1b', delivery_fee=3000)  # 사람이 직접 3000 입력

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import resolve_rules_for_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        assert d.delivery_fee == 3000, '사람이 입력한 값이 저장 단계부터 안 지켜졌다'
        rules, notes, collect_words = resolve_rules_for_draft(s, d, '')
        view, applied, skipped = PA.apply_rules(d, rules, market='',
                                                collect_banned_words=collect_words)
        assert view.delivery_fee == 3000, '사람이 직접 넣은 배송비를 정책이 덮었다'
        codes = {sk['code'] for sk in skipped if sk.get('item') == 'shipping'}
        assert 'KEEP_HUMAN_VALUE' in codes
    finally:
        s.close()


# ── 대조군 — 같은 _is_blank() 를 쓰는 A/S 필드는 원래부터 영향이 없다 ──────────

def test_AS_전화번호는_빈문자열_기본값이라_영향받지_않는다(client, bag):
    """`after_service_phone` 컬럼 기본값은 `''`(빈 문자열)이다 — `_is_blank('')` 가
    참이라 정책값이 원래도 정상적으로 들어갔다. 배송비·원산지와 달리 여기는
    버그가 없었다(대조군) — 이 시험은 그 사실이 이번 수정으로도 안 깨졌는지 고정한다."""
    _make_policy(bag, brand='폴백브랜드3',
                 rules={'shipping': {'fee_mode': 'free', 'as_phone': '010-9999-0000'}})
    did = _make_draft(client, bag, brand='폴백브랜드3')

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.process_policy import resolve_rules_for_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        assert d.after_service_phone == '', 'AS 전화번호 기본값 가정이 바뀌었다'
        rules, notes, collect_words = resolve_rules_for_draft(s, d, '')
        view, applied, skipped = PA.apply_rules(d, rules, market='',
                                                collect_banned_words=collect_words)
        assert view.after_service_phone == '010-9999-0000', (
            'AS 전화번호는 빈 문자열 기본값이라 정책값이 들어가야 하는데 '
            f'안 들어갔다: {view.after_service_phone!r}')
    finally:
        s.close()


# ── 프로그램 최종 기본값 — 정책이 아예 없을 때도 마켓엔 빈 채로 나가면 안 된다 ──

def test_정책이_아예_없으면_컴파일_직전에_프로그램_기본값이_채워진다(client, bag):
    """수기 대량등록은 정책 없이도 흔하다(소싱처×브랜드에 정책을 안 붙인 경우).
    그래도 배송비 없이 마켓에 나가면 0원(무료배송)으로 오해되니, 등록 직전
    (prepare_compile_draft)에 프로그램 기본값(3000·5000·국내산)이 채워져야 한다."""
    did = _make_draft(client, bag, brand='폴백브랜드4')   # source_site 는 심지만 정책은 안 만든다

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.service import prepare_compile_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        assert d.delivery_fee is None, '시험 전제가 깨졌다 — 저장 단계에서 이미 채워졌다'
        compile_draft, info = prepare_compile_draft(s, d, '')
        assert compile_draft.delivery_fee == 3000, info['applied']
        assert compile_draft.return_fee == 5000, info['applied']
        assert compile_draft.origin_area_code == '0200037', info['applied']
        # 저장값은 여전히 안 건드려야 한다.
        assert d.delivery_fee is None, '저장값을 건드렸다'
    finally:
        s.close()


def test_사람이_명시적으로_0원_무료배송을_넣으면_기본값이_안_덮는다(client, bag):
    """🔴 0 은 값이다(무료배송) — 프로그램 기본값 채우기가 0 을 3000 으로 둔갑시키면
    안 된다. `_is_blank` 는 0 을 빈 값으로 안 본다(process_apply.py 774행 근처)."""
    did = _make_draft(client, bag, brand='폴백브랜드5', delivery_fee=0)

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.registration.service import prepare_compile_draft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(id=did).first()
        assert d.delivery_fee == 0
        compile_draft, info = prepare_compile_draft(s, d, '')
        assert compile_draft.delivery_fee == 0, (
            f'명시적 무료배송(0원)이 프로그램 기본값(3000원)으로 둔갑했다: '
            f'{compile_draft.delivery_fee}')
    finally:
        s.close()
