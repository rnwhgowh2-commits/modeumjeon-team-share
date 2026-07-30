"""마켓별 정책 화면 — 목록 · 편집(마켓 가로탭) · 상품에 적용.

노션 「상품 가공 (정책 생성 & 정책 적용)」. 규칙은 lemouton/policy/service.py 가 단일 원천.

🔴 값이 비어 있는 정책은 **가격 계산에 물리지 않는다**. 화면이 「아직 못 씀」을 보여준다.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

_log = logging.getLogger(__name__)

bp = Blueprint('policy', __name__)


@bp.route('/policies')
def policy_index():
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import applied_count, readiness
    s = SessionLocal()
    try:
        items = []
        for p in s.query(MarketPolicy).filter(MarketPolicy.deleted_at.is_(None)) \
                  .order_by(MarketPolicy.is_default.desc(), MarketPolicy.created_at.desc()):
            rd = readiness(s, p.id)
            items.append({
                'id': p.id, 'name': p.name, 'memo': p.memo,
                'is_default': bool(p.is_default),
                'applied': applied_count(s, p.id),
                'filled': sum(v['filled'] for v in rd.values()),
                'total': sum(v['total'] for v in rd.values()),
                'ready': [m for m, v in rd.items() if v['price_ready']],
            })
    finally:
        s.close()
    return render_template('policy/index.html', active='policies', items=items)


@bp.route('/policies/<int:pid>')
def policy_detail(pid: int):
    from lemouton.policy.fields import MARKETS, fields_for
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import applied_count, readiness, values_for
    market = request.args.get('m') or MARKETS[0][0]
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None or p.deleted_at is not None:
            return render_template('errors/option_not_found.html', active='policies',
                                   requested_code='정책', requested_sku=str(pid)), 404
        ctx = {
            'policy': {'id': p.id, 'name': p.name, 'memo': p.memo or '',
                       'is_default': bool(p.is_default)},
            'markets': MARKETS, 'market': market,
            'groups': fields_for(market),
            'values': values_for(s, pid, market),
            'readiness': readiness(s, pid),
            'applied': applied_count(s, pid),
        }
    finally:
        s.close()
    return render_template('policy/detail.html', active='policies', **ctx)


@bp.post('/api/policies')
def api_create():
    from lemouton.policy.service import PolicyError, create_policy
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        got = create_policy(s, name=p.get('name') or '', memo=p.get('memo') or '')
        s.commit()
        return jsonify({'ok': True, 'id': got.id, 'name': got.name})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 생성 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/values')
def api_save_values(pid: int):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import PolicyError, readiness, save_values
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        pol = s.get(MarketPolicy, pid)
        if pol is None:
            return jsonify({'ok': False, 'error': '정책을 찾을 수 없어요.'}), 404
        n = save_values(s, policy=pol, market=p.get('market') or '',
                        values=dict(p.get('values') or {}))
        s.commit()
        return jsonify({'ok': True, 'changed': n, 'readiness': readiness(s, pid)})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 값 저장 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/apply')
def api_apply(pid: int):
    """{model_codes:[...]} — 고른 상품들에 이 정책을 붙인다."""
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import PolicyError, apply_to
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        pol = s.get(MarketPolicy, pid)
        if pol is None:
            return jsonify({'ok': False, 'error': '정책을 찾을 수 없어요.'}), 404
        n = apply_to(s, policy=pol, model_codes=list(p.get('model_codes') or []))
        s.commit()
        return jsonify({'ok': True, 'applied': n})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 적용 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/default')
def api_set_default(pid: int):
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import set_default
    s = SessionLocal()
    try:
        pol = s.get(MarketPolicy, pid)
        if pol is None:
            return jsonify({'ok': False, 'error': '정책을 찾을 수 없어요.'}), 404
        set_default(s, policy=pol)
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/delete')
def api_delete(pid: int):
    """정책 지우기 — 붙어 있는 상품이 있으면 막는다(정책 없는 상품이 생기면 안 된다)."""
    from datetime import datetime, timezone
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import applied_count
    s = SessionLocal()
    try:
        pol = s.get(MarketPolicy, pid)
        if pol is None or pol.deleted_at is not None:
            return jsonify({'ok': False, 'error': '정책을 찾을 수 없어요.'}), 404
        n = applied_count(s, pid)
        if n:
            return jsonify({'ok': False,
                            'error': f'상품 {n}개에 붙어 있어요. 먼저 다른 정책으로 바꿔 주세요.'}), 400
        pol.deleted_at = datetime.now(timezone.utc)
        s.commit()
        return jsonify({'ok': True})
    finally:
        s.close()


@bp.get('/api/policies/bundles')
def api_bundles():
    """정책을 붙일 상품 목록 — 지금 붙어 있는 정책도 같이."""
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.sourcing.models import Model
    kw = (request.args.get('q') or '').strip().lower()
    s = SessionLocal()
    try:
        names = dict(s.query(MarketPolicy.id, MarketPolicy.name).all())
        linked = dict(s.query(BundlePolicyLink.model_code, BundlePolicyLink.policy_id).all())
        rows = []
        for code, disp, brand in s.query(Model.model_code, Model.display_no, Model.brand) \
                                  .order_by(Model.created_at.desc()):
            if kw and kw not in (code + ' ' + (disp or '') + ' ' + (brand or '')).lower():
                continue
            rows.append({'model_code': code, 'no': disp, 'brand': brand,
                         'policy': names.get(linked.get(code))})
            if len(rows) >= 300:
                break
    finally:
        s.close()
    return jsonify({'ok': True, 'rows': rows})
