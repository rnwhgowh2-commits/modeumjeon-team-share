"""정책 생성 화면 — 목록 · 편집(마켓 공통 + 마켓 가로탭) · 상품에 적용.

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
    from lemouton.policy.common_sync import market_summary
    from lemouton.policy.fields import MARKET_LABEL
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import (
        applied_count, brand_counts, enabled_markets, readiness,
    )
    want_brand = (request.args.get('brand') or '').strip()
    s = SessionLocal()
    try:
        items = []
        for p in s.query(MarketPolicy).filter(MarketPolicy.deleted_at.is_(None)) \
                  .order_by(MarketPolicy.is_default.desc(), MarketPolicy.created_at.desc()):
            rd = readiness(s, p.id)
            items.append({
                'id': p.id, 'name': p.name, 'memo': p.memo, 'brand': p.brand,
                'is_default': bool(p.is_default),
                'applied': applied_count(s, p.id),
                'filled': sum(v['filled'] for v in rd.values()),
                'total': sum(v['total'] for v in rd.values()),
                'ready': [m for m, v in rd.items() if v['price_ready']],
                'markets': enabled_markets(s, p),
                'summary': market_summary(s, p.id),
            })
        brands = brand_counts(s)
    finally:
        s.close()
    # 「브랜드 없음」은 brand=__none__ 으로 고른다 — 빈 문자열은 「전체」와 못 가른다.
    if want_brand == '__none__':
        items = [it for it in items if not it['brand']]
    elif want_brand:
        items = [it for it in items if it['brand'] == want_brand]
    return render_template('policy/index.html', active='policies', items=items,
                           brands=brands, want_brand=want_brand,
                           market_label=MARKET_LABEL, total=len(items))


@bp.route('/policies/<int:pid>')
def policy_detail(pid: int):
    from lemouton.policy.common_sync import market_summary, origin_of
    from lemouton.policy.fields import COMMON_KEY, COMMON_LABEL, MARKETS, items_for
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import applied_count, readiness, values_for
    # 맨 앞이 「마켓 공통」 — 여기서 채우고 마켓으로 넣는 것이 기본 흐름이다.
    market = (request.args.get('m') or COMMON_KEY).strip()
    if market not in ([COMMON_KEY] + [k for k, _ in MARKETS]):
        market = COMMON_KEY
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None or p.deleted_at is not None:
            return render_template('errors/option_not_found.html', active='policies',
                                   requested_code='정책', requested_sku=str(pid)), 404
        ctx = {
            'policy': {'id': p.id, 'name': p.name, 'memo': p.memo or '',
                       'is_default': bool(p.is_default), 'brand': p.brand or ''},
            'markets': [(COMMON_KEY, COMMON_LABEL)] + list(MARKETS),
            'market': market,
            'is_common': market == COMMON_KEY,
            'common_key': COMMON_KEY,
            'items': items_for(market),
            'values': values_for(s, pid, market),
            'origin': origin_of(s, pid, market),
            'summary': market_summary(s, pid),
            'readiness': readiness(s, pid),
            'applied': applied_count(s, pid),
        }
    finally:
        s.close()
    return render_template('policy/detail.html', active='policies', **ctx)


@bp.get('/api/policies/<int:pid>/preview')
def api_preview(pid: int):
    """「이 정책으로 계산하면」 — 상품 하나를 골라 옵션별 판매가 미리보기.

    🔴 보여주기만 한다. 실제 전송 경로는 부르지 않는다 — 수수료율·마진율이 비어 있는
      동안 계산에 물리면 0%로 계산된 가격이 그대로 마켓에 나간다.

    query: ?m=마켓 &model=모델코드 (model 생략 시 이 정책이 붙은 첫 상품)
    """
    from lemouton.policy.fields import MARKETS
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.policy.preview import preview_for_model
    from lemouton.policy.service import values_for
    market = request.args.get('m') or MARKETS[0][0]
    model_code = (request.args.get('model') or '').strip()
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None or p.deleted_at is not None:
            return jsonify({'ok': False, 'error': '정책을 찾을 수 없어요.'}), 404
        links = [l.model_code for l in s.query(BundlePolicyLink)
                 .filter(BundlePolicyLink.policy_id == pid).all()]
        if not model_code:
            model_code = links[0] if links else ''
        if not model_code:
            return jsonify({'ok': False, 'models': [],
                            'error': '이 정책에 붙은 상품이 없어요 — 먼저 상품을 붙이면 '
                                     '그 상품으로 계산해 보여 드립니다.'})
        out = preview_for_model(s, model_code=model_code,
                                values=values_for(s, pid, market), market=market)
        out['models'] = links
        out['model_code'] = model_code
        return jsonify(out)
    except Exception as e:      # noqa: BLE001
        _log.exception('[정책] 미리보기 실패 pid=%s', pid)
        return jsonify({'ok': False, 'error': f'계산하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies')
def api_create():
    from lemouton.policy.service import PolicyError, create_policy
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        got = create_policy(s, name=p.get('name') or '', memo=p.get('memo') or '',
                            brand=p.get('brand') or '')
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


# ════════════════════════════════════════════════════════════════════════
#  「정책 생성」 화면 — 복사 · 마켓 켜고 끄기 · 공통 넣기/불러오기
# ════════════════════════════════════════════════════════════════════════

def _live(s, pid: int):
    """살아 있는 정책만. 지운 정책에 손대면 안 된다."""
    from lemouton.policy.models import MarketPolicy
    p = s.get(MarketPolicy, pid)
    return p if p is not None and p.deleted_at is None else None


@bp.post('/api/policies/<int:pid>/copy')
def api_copy(pid: int):
    """정책 복사 — 붙은 상품·기본 표시는 따라오지 않는다."""
    from lemouton.policy.copy import copy_policy
    from lemouton.policy.service import PolicyError
    name = (request.get_json(silent=True) or {}).get('name') or ''
    s = SessionLocal()
    try:
        p = _live(s, pid)
        if p is None:
            return jsonify({'ok': False, 'error': '없는 정책이에요.'}), 404
        c = copy_policy(s, policy=p, name=name)
        s.commit()
        return jsonify({'ok': True, 'id': c.id, 'name': c.name})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 복사 실패')
        return jsonify({'ok': False, 'error': f'복사하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/markets')
def api_set_markets(pid: int):
    """내보낼 마켓을 정한다. 빈 목록도 받는다(= 아무 데도 안 나감)."""
    from lemouton.policy.service import PolicyError, set_enabled_markets
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        p = _live(s, pid)
        if p is None:
            return jsonify({'ok': False, 'error': '없는 정책이에요.'}), 404
        got = set_enabled_markets(s, policy=p, markets=body.get('markets') or [])
        s.commit()
        return jsonify({'ok': True, 'markets': got})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 마켓 저장 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/push')
def api_push(pid: int):
    """「마켓 공통」 값을 고른 마켓에 넣는다. 그 마켓이 고쳐 둔 값은 사라진다."""
    from lemouton.policy.common_sync import push_to_markets
    from lemouton.policy.service import PolicyError
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        p = _live(s, pid)
        if p is None:
            return jsonify({'ok': False, 'error': '없는 정책이에요.'}), 404
        n = push_to_markets(s, policy=p, markets=body.get('markets') or [],
                            item_keys=body.get('item_keys'))
        s.commit()
        return jsonify({'ok': True, 'count': n, 'message': f'{n}곳에 넣었습니다.'})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 공통 넣기 실패')
        return jsonify({'ok': False, 'error': f'넣지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/pull')
def api_pull(pid: int):
    """그 마켓이 「마켓 공통」을 불러온다. 전체 또는 항목별."""
    from lemouton.policy.common_sync import pull_from_common
    from lemouton.policy.service import PolicyError
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        p = _live(s, pid)
        if p is None:
            return jsonify({'ok': False, 'error': '없는 정책이에요.'}), 404
        n = pull_from_common(s, policy=p, market=body.get('market') or '',
                             item_keys=body.get('item_keys'))
        s.commit()
        return jsonify({'ok': True, 'count': n,
                        'message': f'{n}개 항목을 불러왔습니다.'})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[policy] 공통 불러오기 실패')
        return jsonify({'ok': False, 'error': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()
