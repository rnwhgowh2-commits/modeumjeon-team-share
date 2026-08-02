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


@bp.post('/api/policies/<int:pid>/apply-sets')
def api_apply_sets(pid: int):
    """{set_ids:[...]} — 고른 **벌**들에 이 정책을 붙인다(「한 상품에 여러 정책」).

    상품 단위(`/apply`)와 나란히 둔다 — 벌이 하나뿐인 상품은 여전히 상품 단위로 붙인다.
    """
    from lemouton.policy.bundles import attach_to_sets
    from lemouton.policy.service import PolicyError
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        n = attach_to_sets(s, policy_id=pid, set_ids=list(p.get('set_ids') or []))
        s.commit()
        return jsonify({'ok': True, 'applied': n})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책] 벌 적용 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/bundles/<path:model_code>/add-bundle')
def api_add_bundle(model_code: str):
    """{policy_id, copy_from, name} — 이 상품에 **벌을 하나 더** 만든다.

    🔴 이 상품이 마켓에 **한 번 더 올라간다**. 옵션은 기본으로 지금 벌과 똑같이 베낀다
      (안 베끼면 빈 벌이라 못 올라간다).
    """
    from lemouton.policy.bundles import add_bundle
    from lemouton.policy.service import PolicyError
    p = request.get_json(silent=True) or {}
    pid = p.get('policy_id')
    if not isinstance(pid, int):
        return jsonify({'ok': False, 'error': '붙일 정책을 골라 주세요.'}), 400
    s = SessionLocal()
    try:
        got = add_bundle(s, model_code=model_code, policy_id=pid,
                         copy_from_set_id=p.get('copy_from') or None,
                         name=(p.get('name') or '').strip())
        s.commit()
        msg = f"「{got['name']}」 벌을 만들었습니다."
        if got['copied_options']:
            msg += f" 옵션 {got['copied_options']}개를 그대로 가져왔습니다."
        else:
            msg += ' 담을 옵션은 아직 없습니다 — 구성에서 골라 주세요.'
        return jsonify({'ok': True, 'message': msg, **got})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책] 벌 만들기 실패')
        return jsonify({'ok': False, 'error': f'만들지 못했어요: {e}'}), 500
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
    """정책을 붙일 상품 목록 — 지금 붙어 있는 정책도 같이.

    query: ?q=찾을말 &brand=브랜드 (brand=__none__ = 브랜드 없는 상품만)
    brands = 브랜드별 상품 수 (걸러내기 단추용). **거른 뒤가 아니라 전체 기준**이라
    단추를 눌러도 개수가 안 흔들린다.
    """
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.sourcing.models import Model
    kw = (request.args.get('q') or '').strip().lower()
    want_brand = (request.args.get('brand') or '').strip()
    s = SessionLocal()
    try:
        names = dict(s.query(MarketPolicy.id, MarketPolicy.name).all())
        linked = dict(s.query(BundlePolicyLink.model_code, BundlePolicyLink.policy_id).all())
        rows, counts, total = [], {}, 0
        # [2026-08-02] 이름으로도 찾게 한다 — 사장님은 번호가 아니라 「메이트」로 찾는다.
        #   찾는 칸만 넓힌 것이라 번호·브랜드로 찾던 결과는 그대로 나온다.
        for code, disp, brand, nm in s.query(Model.model_code, Model.display_no, Model.brand,
                                             Model.model_name_display) \
                                      .order_by(Model.created_at.desc()):
            total += 1
            counts[brand or ''] = counts.get(brand or '', 0) + 1
            if want_brand == '__none__' and brand:
                continue
            if want_brand and want_brand != '__none__' and brand != want_brand:
                continue
            if kw and kw not in (code + ' ' + (disp or '') + ' ' + (brand or '')
                                 + ' ' + (nm or '')).lower():
                continue
            if len(rows) < 300:
                rows.append({'model_code': code, 'no': disp, 'brand': brand, 'name': nm,
                             'policy': names.get(linked.get(code))})
        # [2026-08-02] 「한 상품에 여러 정책」 — 벌(구성)을 같이 실어 준다.
        #   벌이 2개 이상인 상품만 화면에서 펼쳐진다. 벌 1개·0개는 오늘 그대로.
        from lemouton.policy.bundles import bundles_of
        by_code = bundles_of(s, [r['model_code'] for r in rows])
        for r in rows:
            r['bundles'] = by_code.get(r['model_code'], [])
    finally:
        s.close()
    # 많은 순 → 이름 순, 브랜드 없는 것은 맨 뒤(만들다 만 것이 위를 차지하면 안 된다)
    named = sorted(((b, n) for b, n in counts.items() if b), key=lambda x: (-x[1], x[0]))
    if counts.get(''):
        named.append(('', counts['']))
    return jsonify({'ok': True, 'rows': rows, 'total': total,
                    'brands': [{'name': b, 'count': n} for b, n in named]})


@bp.route('/policies/apply')
def policy_apply_page():
    """「상품 정책 적용」 — 노션 하위탭 ②.

    왼쪽에서 상품을 고르고 오른쪽에서 정책을 골라 한 번에 붙인다(그룹핑).
    🔴 정책은 **하나만** 고른다 — 지금 상품 하나에 정책 하나라, 여러 개를 고르게
      하면 거짓 기능이 된다(「한 상품에 여러 정책」은 모상품번호 체계가 나온 뒤).
    """
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import applied_count, brand_counts, readiness
    s = SessionLocal()
    try:
        policies = []
        for p in s.query(MarketPolicy).filter(MarketPolicy.deleted_at.is_(None)) \
                  .order_by(MarketPolicy.is_default.desc(), MarketPolicy.name):
            rd = readiness(s, p.id)
            policies.append({
                'id': p.id, 'name': p.name, 'brand': p.brand or '',
                'is_default': bool(p.is_default),
                'applied': applied_count(s, p.id),
                'ready': [m for m, v in rd.items() if v['price_ready']],
            })
        pbrands = brand_counts(s)
    finally:
        s.close()
    return render_template('policy/apply.html', active='policy_apply',
                           policies=policies, pbrands=pbrands)


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


@bp.get('/api/bundles/<path:model_code>/policy-result')
def api_bundle_policy_result(model_code: str):
    """상품 상세 「정책 정보」 탭 — 붙은 정책 목록 + 고른 정책의 마켓별 결과(H1).

    query: ?policy=<id> (생략하면 붙어 있는 정책)
    🔴 계산은 preview.result_by_market 이 한다 — 여기서 산식을 다시 쓰면 갈린다.
    """
    from lemouton.policy.bundles import bundles_of
    from lemouton.policy.fields import MARKETS
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.policy.preview import result_by_market
    from lemouton.policy.service import enabled_markets
    want = request.args.get('policy')
    s = SessionLocal()
    try:
        # [2026-08-02] 벌이 2개 이상이면 **나란히 놓고** 보여 준다(F1).
        #   벌이 1개·0개면 예전 그대로 — 화면이 안 바뀐다.
        # 🔴 정책이 붙었는지로 거르지 않는다. 벌이 2개인데 하나만 정책이 있으면
        #   나머지 벌이 화면에서 아예 사라져, 사장님이 「벌이 하나뿐」으로 오해한다
        #   (라이브 르무통_메이트 가 정확히 그 상태였다 — 벌 2개·정책 0개).
        bl = bundles_of(s, [model_code]).get(model_code, [])
        if len(bl) >= 2:
            cols, per = [], {}
            for b in bl:
                cols.append({'set_id': b['set_id'], 'name': b['name'],
                             'policy_id': b['policy_id'], 'policy': b['policy']})
                rows_ = []
                if b.get('policy_id'):
                    rows_ = (result_by_market(s, model_code=model_code,
                                              policy_id=b['policy_id'])
                             .get('rows') or [])
                by_market = {r['market']: r for r in rows_}
                for mk, label in MARKETS:
                    per.setdefault(mk, {'market': mk, 'label': label, 'cells': []})
                    r = by_market.get(mk)
                    if r is None:
                        # 정책이 없는 벌 — 값을 지어내지 않고 이유를 적는다
                        per[mk]['cells'].append({
                            'set_id': b['set_id'], 'price': None, 'margin': None,
                            'margin_rate': None, 'ready': False,
                            'reason': '이 벌에 정책이 없습니다 — 먼저 붙여 주세요.'})
                        continue
                    per[mk]['cells'].append({
                        'set_id': b['set_id'], 'price': r.get('price'),
                        'margin': r.get('margin'), 'margin_rate': r.get('margin_rate'),
                        'ready': r.get('ready'), 'reason': r.get('reason') or ''})
            return jsonify({'ok': True, 'mode': 'compare',
                            'bundles': cols, 'markets': list(per.values()),
                            'policies': [], 'rows': []})

        link = s.get(BundlePolicyLink, model_code)
        attached = []
        # 벌이 딱 하나면 그 벌의 정책이 이긴다(상품 정책은 되받기용 바탕값)
        if len(bl) == 1:
            p = s.get(MarketPolicy, bl[0]['policy_id'])
            if p is not None and p.deleted_at is None:
                attached.append({'id': p.id, 'name': p.name,
                                 'markets': enabled_markets(s, p)})
        if not attached and link is not None:
            p = s.get(MarketPolicy, link.policy_id)
            if p is not None and p.deleted_at is None:
                attached.append({'id': p.id, 'name': p.name,
                                 'markets': enabled_markets(s, p)})
        if not attached:
            return jsonify({'ok': True, 'policies': [], 'rows': [],
                            'reason': '이 상품에 붙은 정책이 없습니다 — '
                                      '「🧩 상품 정책 적용」에서 먼저 붙여 주세요.'})
        pid = int(want) if (want or '').isdigit() else attached[0]['id']
        if pid not in {a['id'] for a in attached}:
            pid = attached[0]['id']
        out = result_by_market(s, model_code=model_code, policy_id=pid)
        out['policies'] = attached
        out['policy_id'] = pid
        return jsonify(out)
    except Exception as e:      # noqa: BLE001
        _log.exception('[정책] 상품 결과 계산 실패 model=%s', model_code)
        return jsonify({'ok': False, 'error': f'계산하지 못했어요: {e}'}), 500
    finally:
        s.close()


# ════════════════════════════════════════════════════════════════════════
#  가격 템플릿 → 정책 옮기기 (대조 먼저, 통과해야 옮긴다)
# ════════════════════════════════════════════════════════════════════════

def _parity_rows():
    """지금 가격 템플릿 전부를 **임시 메모리 DB 에서** 옮겨 보고 값만 비교한다.

    🔴 라이브에는 한 글자도 쓰지 않는다 — 템플릿 값을 읽어다 임시 DB 에서만 돌린다.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base
    from lemouton.policy import models as _pm            # noqa: F401 — 표 등록
    from lemouton.policy.migrate_from_template import compare_prices, migrate_template
    from lemouton.templates.models import PriceTemplate

    live = SessionLocal()
    try:
        cols = [c.name for c in PriceTemplate.__table__.columns]
        rows = [{c: getattr(t, c) for c in cols}
                for t in live.scalars(select(PriceTemplate).order_by(PriceTemplate.id))]
    finally:
        live.close()

    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    out = []
    try:
        for row in rows:
            t = PriceTemplate(**row)
            s.add(t)
            s.flush()
            got = migrate_template(s, tpl=t)
            res = compare_prices(s, tpl=t, policy_id=got['policy_id'])
            out.append({
                'id': row['id'], 'name': t.name,
                'ok': bool(res['ok']), 'checked': res['checked'],
                'markets': len(got.get('markets') or {}),
                'diffs': [
                    {'market': r['market'], 'side': r['side'], 'purchase': r['purchase'],
                     'template': r['template'], 'policy': r['policy']}
                    for r in res['rows'][:12]
                ],
                'diff_count': len(res['rows']),
            })
    finally:
        s.close()
    return out


@bp.get('/api/policies/price-parity')
def api_price_parity():
    """「옮기면 가격이 그대로인가」 — 읽기만 한다."""
    try:
        rows = _parity_rows()
    except Exception as e:      # noqa: BLE001
        _log.exception('[정책] 가격 대조 실패')
        return jsonify({'ok': False, 'error': f'대조하지 못했어요: {e}'}), 500
    return jsonify({'ok': True, 'rows': rows,
                    'all_same': all(r['ok'] for r in rows) if rows else False})


@bp.post('/api/policies/migrate-template')
def api_migrate_template():
    """{template_id} — 그 가격 템플릿을 정책으로 옮긴다.

    🔴 **대조를 통과한 템플릿만** 옮긴다. 값이 달라지는 상태로 옮기면
      그 가격이 그대로 마켓에 나간다.
    """
    from lemouton.policy.migrate_from_template import (attach_to_template_users,
                                                       migrate_template)
    from lemouton.policy.service import PolicyError
    from lemouton.templates.models import PriceTemplate
    tid = (request.get_json(silent=True) or {}).get('template_id')
    if not isinstance(tid, int):
        return jsonify({'ok': False, 'error': '어느 가격 템플릿을 옮길지 골라 주세요.'}), 400

    try:
        checked = {r['id']: r for r in _parity_rows()}
    except Exception as e:      # noqa: BLE001
        _log.exception('[정책] 옮기기 전 대조 실패')
        return jsonify({'ok': False, 'error': f'대조하지 못했어요: {e}'}), 500
    row = checked.get(tid)
    if row is None:
        return jsonify({'ok': False, 'error': '없는 가격 템플릿이에요.'}), 404
    if not row['ok']:
        return jsonify({'ok': False,
                        'error': f"옮기면 가격이 {row['diff_count']}곳 달라집니다 — "
                                 f"그대로 옮길 수 없어요. 먼저 확인이 필요합니다."}), 400

    s = SessionLocal()
    try:
        tpl = s.get(PriceTemplate, tid)
        if tpl is None:
            return jsonify({'ok': False, 'error': '없는 가격 템플릿이에요.'}), 404
        got = migrate_template(s, tpl=tpl)

        # 옮기기만 하면 정책은 **아무 상품에도 안 붙어** 아직 아무 일도 안 한다.
        # 그 템플릿을 쓰던 상품에 그대로 붙여야 정책이 실제로 가격을 정한다.
        # 🔴 같은 템플릿을 쓰던 상품에만 붙인다 — 값이 같으니 가격이 안 바뀐다.
        att = {'attached': 0, 'skipped': 0}
        if (request.get_json(silent=True) or {}).get('attach'):
            att = attach_to_template_users(s, template_id=tid,
                                           policy_id=got['policy_id'])
        s.commit()
        msg = f"「{got['name']}」 로 옮겼습니다 — 가격은 그대로입니다."
        if att['attached']:
            msg += f" 이 템플릿을 쓰던 상품 {att['attached']}개에 붙였습니다."
        if att['skipped']:
            msg += f" (다른 정책이 이미 붙은 {att['skipped']}개는 그대로 뒀습니다.)"
        return jsonify({'ok': True, 'policy_id': got['policy_id'], 'name': got['name'],
                        'markets': got['markets'], 'attached': att['attached'],
                        'skipped': att['skipped'], 'message': msg})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책] 옮기기 실패')
        return jsonify({'ok': False, 'error': f'옮기지 못했어요: {e}'}), 500
    finally:
        s.close()
