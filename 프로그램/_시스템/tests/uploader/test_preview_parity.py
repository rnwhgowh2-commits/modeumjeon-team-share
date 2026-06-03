"""업로드 드라이런 미리보기 ↔ 옵션 매트릭스(표시) 가격 교차검증.

"표시가 = 업로드가" 단일 진실 원천 보장 — 두 경로(preview 모듈 / 매트릭스
엔드포인트)가 per-sku 로 동일한 '적용(우선 공급) 가격'을 내는지 검증한다.
운영 Supabase 데이터(르무통_메이트)에 의존하므로, 데이터 없으면 skip.
"""
import pytest

CODE = '르무통_메이트'


def _matrix_resolved(opt: dict) -> tuple[int, int]:
    """매트릭스 옵션 dict → (ss, cp) 적용 가격 (우선 공급 카드 기준)."""
    side = opt.get('purchase_priority_resolved')
    if side == 'purchase' and opt.get('pur_ss_price') is not None:
        return opt['pur_ss_price'], opt['pur_cp_price']
    return opt['ss_price'], opt['cp_price']


@pytest.fixture(scope='module')
def both_outputs():
    from app import create_app
    from shared.db import SessionLocal
    from webapp.routes.api_pricing import get_option_matrix
    from lemouton.uploader.preview import build_upload_preview

    from sqlalchemy.exc import OperationalError
    try:
        app = create_app()
        with app.test_request_context(f'/api/bundles/{CODE}/option-matrix'):
            resp = get_option_matrix(CODE)
        body = resp[0] if isinstance(resp, tuple) else resp
        mdata = body.get_json() if hasattr(body, 'get_json') else None
        if not mdata or not mdata.get('ok') or not mdata.get('options'):
            pytest.skip('매트릭스 데이터 없음 (운영 DB 미연결 등) — parity 검증 skip')

        s = SessionLocal()
        try:
            preview = build_upload_preview(s, CODE)
        finally:
            s.close()
    except OperationalError:
        pytest.skip('DB 연결 불가 (Supabase 풀 포화 등) — parity 검증 skip')
    if not preview.get('ok') or not preview.get('rows'):
        pytest.skip('preview 데이터 없음 — skip')
    return mdata, preview


def test_sku_set_matches(both_outputs):
    mdata, preview = both_outputs
    m_skus = {o['sku'] for o in mdata['options']}
    p_skus = {r['sku'] for r in preview['rows']}
    assert m_skus == p_skus


def test_resolved_prices_match(both_outputs):
    mdata, preview = both_outputs
    m_by_sku = {o['sku']: o for o in mdata['options']}
    mismatches = []
    for r in preview['rows']:
        m = m_by_sku.get(r['sku'])
        if not m:
            continue
        exp_ss, exp_cp = _matrix_resolved(m)
        if (r['ss_price'], r['cp_price']) != (exp_ss, exp_cp):
            mismatches.append((r['sku'], (r['ss_price'], r['cp_price']), (exp_ss, exp_cp)))
    assert not mismatches, f"표시≠업로드 불일치 {len(mismatches)}건: {mismatches[:5]}"


def test_resolved_side_matches(both_outputs):
    mdata, preview = both_outputs
    m_by_sku = {o['sku']: o for o in mdata['options']}
    for r in preview['rows']:
        m = m_by_sku.get(r['sku'])
        if m:
            assert r['resolved_side'] == m.get('purchase_priority_resolved'), \
                f"{r['sku']} 우선공급 불일치"
