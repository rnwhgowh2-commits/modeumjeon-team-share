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
            # [2026-08-12] 채움·「쓸 수 있음」은 **켠 마켓만** 센다(노션 정책생성 a).
            #   안 켠 마켓을 분모에 두면 100% 가 영영 안 찬다.
            on = enabled_markets(s, p)
            rd = readiness(s, p.id, markets=on)
            items.append({
                'id': p.id, 'name': p.name, 'memo': p.memo, 'brand': p.brand,
                'is_default': bool(p.is_default),
                'applied': applied_count(s, p.id),
                'filled': sum(v['filled'] for v in rd.values()),
                'total': sum(v['total'] for v in rd.values()),
                'ready': [m for m, v in rd.items() if v['price_ready']],
                'markets': on,
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
    from lemouton.policy.service import (
        applied_count, enabled_markets, readiness, values_for,
    )
    from lemouton.policy import fixed_sends as FIXED
    from lemouton.policy import required as REQ
    from lemouton.pricing import fee_defaults
    from lemouton.pricing.unified import default_fee_pct
    # 맨 앞이 「마켓 공통」 — 여기서 채우고 마켓으로 넣는 것이 기본 흐름이다.
    market = (request.args.get('m') or COMMON_KEY).strip()
    if market not in ([COMMON_KEY] + [k for k, _ in MARKETS]):
        market = COMMON_KEY
    s = SessionLocal()
    try:
        p = s.get(MarketPolicy, pid)
        if p is None or p.deleted_at is not None:
            # 🔴 종전엔 「옵션을 찾을 수 없습니다 / 모음전 코드: 정책」이었다 —
            #   정책을 찾다 실패했는데 옵션을 못 찾았다고 하면 딴 데를 뒤지게 된다.
            return render_template('errors/option_not_found.html', active='policies',
                                   what='정책', requested_code='',
                                   sku_label='정책 번호', requested_sku=str(pid)), 404
        items = items_for(market)
        vals = values_for(s, pid, market)
        # ── 항목별 「이 마켓이 요구하는가」 + 「지금 실제로 나가는가」 ──────────
        #   🔴 「마켓 공통」 탭에는 필수 배지를 붙이지 않는다 — 마켓이 정해지지 않아
        #     **어느 마켓 기준인지 말할 수 없다.** 붙이면 그 자체가 근거 없는 단정이다.
        #     배선 표시(전송됨/저장만)는 마켓과 무관하므로 공통 탭에도 그대로 둔다.
        req_map = ({} if market == COMMON_KEY else
                   {it['key']: dict(zip(('state', 'evidence', 'note'),
                                        REQ.status_of(market, it['key'])))
                    for it in items})
        wire_map = {it['key']: dict(zip(('state', 'note'), REQ.wiring_of(it['key'])))
                    for it in items}
        req_sum = (None if market == COMMON_KEY else
                   REQ.summary_for(market, [it['key'] for it in items], vals))
        # ── [2026-08-12 확정 B2] 켠 마켓 / 채움 합계 ────────────────────────────
        #   탭별 숫자는 전 마켓 그대로 두고(꺼 둔 곳도 열어 보면 값이 보여야 한다),
        #   **합계만** 켠 마켓으로 센다.
        _on_markets = enabled_markets(s, p)
        _rd_all = readiness(s, pid)
        _on = [k for k, _lb in MARKETS if k in set(_on_markets)]
        _off = [k for k, _lb in MARKETS if k not in set(_on_markets)]
        _fill_sum = {
            'filled': sum(_rd_all[k]['filled'] for k in _on),
            'total': sum(_rd_all[k]['total'] for k in _on),
            'on': len(_on), 'off': len(_off),
        }
        ctx = {
            'policy': {'id': p.id, 'name': p.name, 'memo': p.memo or '',
                       'is_default': bool(p.is_default), 'brand': p.brand or ''},
            'markets': [(COMMON_KEY, COMMON_LABEL)] + list(MARKETS),
            'market': market,
            # ── [2026-08-12 사장님 확정 B2] 노션 「마켓 활성화 체크한 것만 가공 활성화」 ──
            #   🔴 꺼진 마켓을 목록에서 **빼지 않는다.** 빼면 거기 채워 둔 값을
            #     다시 고칠 길이 사라진다(껐다 켜면 살아나야 한다는 게 사장님 뜻).
            #     흐리게 + 자물쇠로 **위상만 낮춘다.**
            'enabled': set(_on_markets),
            'market_label': dict(MARKETS).get(market, COMMON_LABEL),
            # ── [2026-08-13 확정 A1+B2] 정해져 나가는 값 ──────────────────────
            #   정책 화면에 칸조차 없는데 등록 코드에 박힌 채 마켓으로 나가는 값들.
            #   🔴 「마켓 공통」 탭에는 안 붙인다 — 어느 마켓 얘긴지 정해지지 않았다.
            'fixed': (None if market == COMMON_KEY else FIXED.for_market(market)),
            #   항목별 「정책 ○○ / 실제 ○○」 — 늘 보인다(확정 B2).
            'fixed_by_item': (None if market == COMMON_KEY
                              else FIXED.by_item(market, vals)),
            # ── [2026-08-13 확정 시안 v2 · 2번] 「마켓마다 어떤 값으로 나가는지 보기」 ──
            #   라디오 옆 접힘표. 🔴 마켓을 안 가린다 — 사장님이 「면세」를 고를 때
            #     **여섯 마켓 전부**에 무엇이 나가는지 한 자리에서 봐야 뜻이 있다
            #     (마켓마다 값이 다르고, 롯데온은 아직 모른다).
            'sends_table': {k: FIXED.sends_table(k)
                            for k in FIXED.SENDS_BY_MARKET},
            # 채움 합계 — **켠 마켓만** 센다. 셈을 템플릿에 넣으면 검사가 어려워
            #   여기서 만들어 넘긴다.
            'fill_sum': _fill_sum,
            'is_common': market == COMMON_KEY,
            'common_key': COMMON_KEY,
            'items': items,
            'values': vals,
            # [2026-08-02] 「필수」 표시 — 판정 근거는 마켓 상품등록 API 원문뿐
            #   (사장님 확정). 정본 = lemouton/policy/required.py.
            'req': req_map,
            'wire': wire_map,
            'req_sum': req_sum,
            'stored_only_note': REQ.STORED_ONLY_NOTE,
            'origin': origin_of(s, pid, market),
            'summary': market_summary(s, pid),
            'readiness': _rd_all,
            'applied': applied_count(s, pid),
            # [2026-08-02] 이 마켓의 수수료 기준 — 화면 빈칸에 채워 넣는다.
            #   🔴 숫자를 화면에 적어 두지 않는다. 계산은 `default_fee_rate`,
            #     화면은 이 값으로 **같은 표**를 본다 → 절대 안 갈린다.
            #   「마켓 공통」 탭은 마켓이 정해지지 않아 채우지 않는다(None).
            'fee_default_pct': (None if market == COMMON_KEY
                                else default_fee_pct(market)),
            # 조건부 요율(예: 11번가 「1년 이내 계정」 → 8%). 이름이 비면 체크박스 없음.
            'fee_alt': (None if market == COMMON_KEY else
                        (lambda d: dict(d, alt_pct=fee_defaults.pretty(d.get('alt_pct'))))
                        (fee_defaults.load().get(market) or {})),
            'fee_note': ('' if market == COMMON_KEY
                         else fee_defaults.NOTES.get(market, '')),
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


def _auto_coupon(s, pid: int) -> dict:
    """정책 자동(사장님 확정 **c**) — 쿠팡이면 쿠폰까지 함께 건다.

    🔴 쿠팡엔 즉시할인을 적을 칸이 없다. 쿠폰을 만들어 옵션에 붙여야 값이 깎인다.
      정책만 붙이고 끝내면 「할인을 걸었는데 안 깎인다」가 된다.
    🔴 **즉시할인이 적힌 정책만** 태운다 — 안 그러면 온 상품에 시킨 적 없는
      기본값 100원 쿠폰이 저절로 걸린다.
    🔴 여기서 **직접 걸지 않는다.** 한 상품이 최대 21번 왕복이라 화면이 못 기다린다 →
      대기열에 넣고 스케줄러(1분 틱)가 처리한다.
    🔴 쿠폰이 실패해도 **정책 붙이기는 성공이다** — 여기서 터뜨리면 정책까지 못 붙는다.
    """
    try:
        from lemouton.policy import coupon_service as CS
        out = CS.request_for_policy(s, pid)
        s.commit()
        return out
    except Exception as e:      # noqa: BLE001
        s.rollback()
        _log.exception('[정책] 쿠팡 쿠폰 대기열 넣기 실패 pid=%s', pid)
        return {'ok': False, 'queued': 0,
                'message': f'정책은 붙였지만 쿠팡 쿠폰은 대기열에 못 넣었습니다: {e}'}


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
        return jsonify({'ok': True, 'applied': n, 'coupon': _auto_coupon(s, pid)})
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
    """{set_ids:[...]} — 고른 **구성**들에 이 정책을 붙인다(「한 상품에 여러 정책」).

    상품 단위(`/apply`)와 나란히 둔다 — 구성이 하나뿐인 상품은 여전히 상품 단위로 붙인다.
    """
    from lemouton.policy.bundles import attach_to_sets
    from lemouton.policy.service import PolicyError
    p = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        n = attach_to_sets(s, policy_id=pid, set_ids=list(p.get('set_ids') or []))
        s.commit()
        return jsonify({'ok': True, 'applied': n, 'coupon': _auto_coupon(s, pid)})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책] 구성 적용 실패')
        return jsonify({'ok': False, 'error': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/bundles/<path:model_code>/add-bundle')
def api_add_bundle(model_code: str):
    """{policy_id, copy_from, name} — 이 상품에 **구성을 하나 더** 만든다.

    🔴 이 상품이 마켓에 **한 번 더 올라간다**. 옵션은 기본으로 지금 구성과 똑같이 베낀다
      (안 베끼면 빈 구성이라 못 올라간다).
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
        msg = f"「{got['name']}」 구성을 만들었습니다."
        if got['copied_options']:
            msg += f" 옵션 {got['copied_options']}개를 그대로 가져왔습니다."
        else:
            msg += ' 담을 옵션은 아직 없습니다 — 구성에서 골라 주세요.'
        return jsonify({'ok': True, 'message': msg, **got})
    except PolicyError as e:
        s.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[정책] 구성 만들기 실패')
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
    want_applied = (request.args.get('applied') or '').strip()  # 'yes' | 'no' | ''(전체)
    s = SessionLocal()
    try:
        names = dict(s.query(MarketPolicy.id, MarketPolicy.name).all())
        linked = dict(s.query(BundlePolicyLink.model_code, BundlePolicyLink.policy_id).all())
        # [이슈 #1058] 정책 적용 필터 — 상품(BundlePolicyLink) ∪ 구성(SetPolicyLink)
        #   합집합을 봐야 한다. 상품 단위만 보면 구성으로만 정책이 붙은 상품을
        #   「미적용」으로 잘못 판정한다(bundles_tower.policy_models 와 같은 규칙 재사용).
        from webapp.routes.bundles_tower import policy_models
        all_codes = [c for (c,) in s.query(Model.model_code).all()]
        applied_codes = policy_models(s, all_codes) if want_applied else set()
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
            if want_applied == 'yes' and code not in applied_codes:
                continue
            if want_applied == 'no' and code in applied_codes:
                continue
            if len(rows) < 300:
                rows.append({'model_code': code, 'no': disp, 'brand': brand, 'name': nm,
                             'policy': names.get(linked.get(code))})
        # [2026-08-02] 「한 상품에 여러 정책」 — 구성(ProductSet)을 같이 실어 준다.
        #   구성이 2개 이상인 상품만 화면에서 펼쳐진다. 1개·0개는 오늘 그대로.
        from lemouton.policy.bundles import bundles_of
        by_code = bundles_of(s, [r['model_code'] for r in rows])
        for r in rows:
            r['bundles'] = by_code.get(r['model_code'], [])

        # [이슈 #1058] 옵션매트릭스 — 상품(Model) 하나에 원본 매트릭스 하나(1:1).
        #   없는 상품(아직 매트릭스를 안 만든 것)은 matrix=None(지어내지 않는다).
        from sqlalchemy import func
        from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
        from lemouton.sourcing.models import Option
        page_codes = [r['model_code'] for r in rows]
        matrices = {mo.model_code: mo for mo in
                    s.query(MatrixOption)
                    .filter(MatrixOption.model_code.in_(page_codes),
                            MatrixOption.kind == KIND_ORIGIN,
                            MatrixOption.deleted_at.is_(None)).all()}
        sku_counts = dict(s.query(Option.model_code, func.count(Option.canonical_sku))
                          .filter(Option.model_code.in_(page_codes))
                          .group_by(Option.model_code).all())
        for r in rows:
            mo = matrices.get(r['model_code'])
            r['matrix'] = ({'id': mo.id, 'name': mo.name, 'no': mo.display_no,
                            'sku_count': sku_counts.get(r['model_code'], 0)}
                           if mo else None)

        # [이슈 #1058] 소싱처 연동 — 사이트 라벨 + 마지막 수집 시각. 배치 1쿼리
        #   (300행 목록에서 상품마다 따로 물으면 N+1이 된다 — 소싱처 필터가
        #   276쿼리였던 전례가 있다). URL 상세(재고·가격)는 호버카드가 따로 부른다.
        from lemouton.sources.models import OptionSourceLink, SourceOption, SourceProduct
        from lemouton.sources.site_labels import SITE_LABEL
        from webapp.routes.bundles_tower import _iso
        sku_model = dict(s.query(Option.canonical_sku, Option.model_code)
                         .filter(Option.model_code.in_(page_codes)).all())
        sourcing_by_model = {c: {'connected': set(), 'collected_at': None}
                             for c in page_codes}
        if sku_model:
            for sku, site, fetched in (
                    s.query(OptionSourceLink.canonical_sku, SourceProduct.site,
                            SourceProduct.last_fetched_at)
                    .join(SourceOption,
                          SourceOption.id == OptionSourceLink.source_option_id)
                    .join(SourceProduct,
                          SourceProduct.id == SourceOption.source_product_id)
                    .filter(OptionSourceLink.canonical_sku.in_(list(sku_model)))
                    .all()):
                mc = sku_model.get(sku)
                if not mc:
                    continue
                st = sourcing_by_model[mc]
                st['connected'].add(SITE_LABEL.get(site, site))
                if fetched and (st['collected_at'] is None or fetched > st['collected_at']):
                    st['collected_at'] = fetched
        for r in rows:
            st = sourcing_by_model.get(r['model_code']) \
                or {'connected': set(), 'collected_at': None}
            r['sourcing'] = {'connected': sorted(st['connected']),
                             'collected_at': _iso(st['collected_at'])}

        # [이슈 #1058] 판매처 연동 — 등록 판정은 기존 _registered_markets
        #   (3원천 합집합)를 그대로 재사용(재계산 금지). 수집(동기화) 시각은
        #   MarketRegistration.last_success_at 배치 1쿼리.
        from lemouton.policy.fields import MARKET_LABEL
        from lemouton.uploader.models import MarketRegistration
        from webapp.routes.bundles_tower import _registered_markets
        reg_markets = _registered_markets(s, page_codes)
        last_sync_by_model = {c: None for c in page_codes}
        if sku_model:
            for sku, ts in (s.query(MarketRegistration.canonical_sku,
                                    MarketRegistration.last_success_at)
                            .filter(MarketRegistration.canonical_sku.in_(list(sku_model)),
                                    MarketRegistration.last_success_at.isnot(None))
                            .all()):
                mc = sku_model.get(sku)
                if not mc:
                    continue
                if last_sync_by_model[mc] is None or ts > last_sync_by_model[mc]:
                    last_sync_by_model[mc] = ts
        for r in rows:
            mkts = reg_markets.get(r['model_code']) or set()
            r['selling'] = {'connected': sorted(MARKET_LABEL.get(m, m) for m in mkts),
                            'collected_at': _iso(last_sync_by_model.get(r['model_code']))}
    finally:
        s.close()
    # 많은 순 → 이름 순, 브랜드 없는 것은 맨 뒤(만들다 만 것이 위를 차지하면 안 된다)
    named = sorted(((b, n) for b, n in counts.items() if b), key=lambda x: (-x[1], x[0]))
    if counts.get(''):
        named.append(('', counts['']))
    return jsonify({'ok': True, 'rows': rows, 'total': total,
                    'brands': [{'name': b, 'count': n} for b, n in named]})


@bp.route('/policies/fees')
def fee_defaults_page():
    """마켓별 수수료 기준 — 정책 화면 칸에 채워 넣을 값을 여기서 고친다.

    사장님 확정 2026-08-02 — 「마켓 정책이 언제든 변경될 수 있으니 기본값도 수기로」.
    """
    from lemouton.policy.fields import MARKET_LABEL, MARKETS
    from lemouton.pricing import fee_defaults
    data = fee_defaults.load()
    rows = []
    for key, _label in MARKETS:
        d = data.get(key) or {}
        rows.append({'market': key, 'label': MARKET_LABEL.get(key, key),
                     'base_pct': fee_defaults.pretty(d.get('base_pct')),
                     'alt_label': d.get('alt_label') or '',
                     'alt_pct': fee_defaults.pretty(d.get('alt_pct')),
                     'note': fee_defaults.NOTES.get(key, '')})
    return render_template('policy/fees.html', active='policies', rows=rows)


@bp.post('/api/policies/fee-defaults')
def api_save_fee_defaults():
    """마켓별 수수료 기준 저장. 한 줄이라도 틀리면 **아무것도 안 고친다.**

    🔴 반쯤 저장되면 어떤 마켓이 새 값이고 어떤 게 옛 값인지 알 수 없다 —
      돈이 걸린 표라 전부 되거나 전부 안 되거나여야 한다.
    """
    from lemouton.pricing import fee_defaults
    rows = (request.get_json(silent=True) or {}).get('rows') or []
    if not rows:
        return jsonify({'ok': False, 'error': '저장할 내용이 없어요'}), 400
    s = SessionLocal()
    try:
        for r in rows:
            fee_defaults.save(s, (r.get('market') or '').strip(),
                              base_pct=r.get('base_pct'),
                              alt_label=r.get('alt_label') or '',
                              alt_pct=r.get('alt_pct'))
        s.commit()
        fee_defaults.invalidate()
        return jsonify({'ok': True, 'saved': len(rows), 'rows': fee_defaults.load()})
    except ValueError as e:
        s.rollback()
        fee_defaults.invalidate()
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        fee_defaults.invalidate()
        _log.exception('수수료 기준 저장 실패')
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        s.close()


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
    # [2026-08-12 노션 상품 c-1] `?model=<코드>` 로 들어오면 그 상품을 미리 골라 둔다.
    #   🔴 검색칸도 같이 채운다 — 상품 목록은 300줄 상한이라, 체크만 해 두면
    #      「체크했다는데 목록에 없다」가 된다.
    pick = [c for c in request.args.getlist('model') if c]
    return render_template('policy/apply.html', active='policy_apply',
                           policies=policies, pbrands=pbrands,
                           pick=pick, pick_q=(pick[0] if len(pick) == 1 else ''))


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
        # [2026-08-02] 구성이 2개 이상이면 **나란히 놓고** 보여 준다(F1).
        #   1개·0개면 예전 그대로 — 화면이 안 바뀐다.
        # 🔴 정책이 붙었는지로 거르지 않는다. 구성이 2개인데 하나만 정책이 있으면
        #   나머지 구성이 화면에서 아예 사라져, 사장님이 「구성이 하나뿐」으로 오해한다
        #   (라이브 르무통_메이트 가 정확히 그 상태였다 — 구성 2개·정책 0개).
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
                        # 정책이 없는 구성 — 값을 지어내지 않고 이유를 적는다
                        per[mk]['cells'].append({
                            'set_id': b['set_id'], 'price': None, 'margin': None,
                            'margin_rate': None, 'ready': False,
                            'reason': '이 구성에 정책이 없습니다 — 먼저 붙여 주세요.'})
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
        # 구성이 딱 하나면 그 구성의 정책이 이긴다(상품 정책은 되받기용 바탕값)
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
#  쿠팡 즉시할인쿠폰 — 상품 화면 단추 (사장님 확정 c: 정책 자동 + 단추 둘 다)
# ════════════════════════════════════════════════════════════════════════

@bp.get('/api/bundles/<path:model_code>/coupang-coupon')
def api_coupon_status(model_code: str):
    """지금 이 상품의 쿠폰 상태 — 「아직 / 대기 중 / 걸림 / 실패」를 가른다.

    🔴 「대기열에 넣었다」와 「걸렸다」는 다르다. 화면이 둘을 같은 말로 하면
      사장님은 안 걸린 걸 걸린 줄 안다.
    """
    from lemouton.policy import coupon_service as CS
    from lemouton.policy.coupon_apply import RETRY_MAX_WON
    s = SessionLocal()
    try:
        rows = []
        for ch in CS.channels_of_model(s, model_code):
            rec = CS.record_of(ch)
            queued = bool((ch.api_fields or {}).get(CS.REQUEST_KEY))
            if queued:
                state = 'queued'
            elif rec.get('ok'):
                state = 'applied'
            elif rec:
                state = 'failed'
            else:
                state = 'none'
            rows.append({
                'channel_id': ch.id, 'set_id': ch.set_id,
                'account': ch.account_key, 'state': state,
                'targets': len(CS.targets_for(s, ch)),
                'coupon_id': rec.get('coupon_id'), 'value': rec.get('value'),
                'starts_at': rec.get('starts_at'), 'ends_at': rec.get('ends_at'),
                'tried': rec.get('tried'), 'at': rec.get('at'),
                'message': rec.get('message') or '',
                'failed_items': rec.get('failed_items') or [],
            })
        return jsonify({'ok': True, 'rows': rows, 'max_won': RETRY_MAX_WON})
    except Exception as e:      # noqa: BLE001
        _log.exception('[쿠팡쿠폰] 상태 조회 실패 model=%s', model_code)
        return jsonify({'ok': False, 'error': f'상태를 읽지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.get('/api/policies/<int:pid>/coupon-plan')
def api_coupon_plan(pid: int):
    """확인창(사장님 확정 B5) 자료 — 몇 개가 바뀌고 몇 개는 안 건드리나.

    🔴 저장하기 **전에** 보여 준다. 몇 개가 바뀌는지 모르고 누르면, 정책 하나로
      상품 수십 개의 쿠폰이 한꺼번에 새로 만들어지고 옛 것이 내려간다.
    """
    from lemouton.policy import coupon_service as CS
    s = SessionLocal()
    try:
        return jsonify({'ok': True, **CS.coupon_plan(s, pid)})
    except Exception as e:      # noqa: BLE001
        _log.exception('[쿠팡쿠폰] 확인창 자료 실패 pid=%s', pid)
        return jsonify({'ok': False, 'message': f'불러오지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/policies/<int:pid>/coupon-plan')
def api_coupon_plan_apply(pid: int):
    """확인창에서 **고른 것만** 다시 건다. body: {channel_ids:[…]}"""
    from lemouton.policy import coupon_service as CS
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        out = CS.apply_coupon_plan(s, pid, channel_ids=body.get('channel_ids') or [])
        s.commit()
        return jsonify(out)
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[쿠팡쿠폰] 확인창 실행 실패 pid=%s', pid)
        return jsonify({'ok': False, 'message': f'걸지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/bundles/<path:model_code>/name-override')
def api_name_override(model_code: str):
    """상품명 「정책 / 비정책」 — 이 상품만 다른 이름으로 마켓에 올린다.

    body: {market:'coupang'|'smartstore', value:str}

    🔴 이 칸은 **전송 코드가 이미 읽고 있었는데 적을 화면이 없어 늘 비어 있었다**
      (인수인계 C1 「죽은 자료」). 창구를 여는 것으로 살아난다.
    🔴 **비우면 None 으로 지운다.** 빈 글자를 그대로 두면 마켓에 **빈 상품명**이
      나가 상품 이름이 사라진다 — 「없음」과 「빈 글자」는 다른 것이다.
    🔴 마켓 한도를 넘으면 **보내기 전에** 사람 말로 막는다. 마켓까지 가면
      「유효하지 않습니다」만 돌아와 무엇이 잘못인지 알 수 없다.
    """
    from lemouton.registration.market_limits import name_max_len
    from lemouton.sourcing.models import Model
    COLS = {'coupang': 'coupang_product_name_override',
            'smartstore': 'naver_product_name_override'}
    body = request.get_json(silent=True) or {}
    market = str(body.get('market') or '')
    col = COLS.get(market)
    if not col:
        return jsonify({'ok': False,
                        'message': '상품명을 따로 정할 수 있는 곳은 '
                                   '쿠팡·스마트스토어뿐입니다 — 나머지 마켓엔 '
                                   '그 칸이 아직 없습니다.'}), 400
    value = (body.get('value') or '').strip()
    cap = name_max_len(market)
    if cap and len(value) > cap:
        return jsonify({'ok': False,
                        'message': f'{market} 상품명은 {cap}자까지입니다 '
                                   f'(지금 {len(value)}자).'}), 400
    s = SessionLocal()
    try:
        m = s.get(Model, model_code)
        if m is None:
            return jsonify({'ok': False, 'message': '상품을 찾을 수 없어요.'}), 404
        # 🔴 빈 글자는 None — 그대로 두면 마켓에 빈 상품명이 나간다.
        setattr(m, col, value or None)
        s.commit()
        return jsonify({'ok': True, 'value': value or None,
                        'message': (f'이 상품만 그 이름으로 올립니다.' if value
                                    else '정책이 만든 이름을 따릅니다.')})
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[상품명] 덮어쓰기 실패 model=%s', model_code)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/bundles/<path:model_code>/coupang-coupon/override')
def api_coupon_override(model_code: str):
    """「정책 / 비정책」 스위치 (사장님 확정 A2).

    body: {mode:'policy'|'own', value:int|null}

    🔴 「비정책」으로 돌리면 **정책을 바꿔도 이 상품은 안 따라간다.** 그게 이 스위치의
      전부다 — 상품에 따로 정해 둔 값이 조용히 날아가지 않게 하는 것.
    🔴 값이 10원 단위가 아니면 여기서 **사람 말로** 막는다. 마켓까지 가면
      「입력한 데이터가 유효하지 않습니다」만 돌아와 무엇이 잘못인지 알 수 없다.
    """
    from lemouton.policy import coupon_service as CS
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        chans = CS.channels_of_model(s, model_code)
        if not chans:
            return jsonify({'ok': False,
                            'message': '이 상품은 아직 쿠팡에 연동된 구성이 없습니다.'}), 400
        mode = str(body.get('mode') or 'policy')
        rec = None
        for ch in chans:
            rec = CS.set_override(s, ch, mode=mode, value=body.get('value'))
        return jsonify({'ok': True, 'override': rec,
                        'message': ('이 상품만의 값으로 씁니다 — 정책을 바꿔도 안 따라갑니다.'
                                    if mode == 'own' else '정책 값을 따릅니다.')})
    except ValueError as e:
        s.rollback()
        return jsonify({'ok': False, 'message': str(e)}), 400
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[쿠팡쿠폰] 스위치 저장 실패 model=%s', model_code)
        return jsonify({'ok': False, 'message': f'저장하지 못했어요: {e}'}), 500
    finally:
        s.close()


@bp.post('/api/bundles/<path:model_code>/coupang-coupon')
def api_coupon_apply(model_code: str):
    """단추 — 이 상품에 쿠폰을 걸어 달라고 요청한다(실제 걸기는 1분 틱이 한다).

    🔴 여기서 직접 걸지 않는 이유: 거부되면 300원까지 최대 21번 되풀이하고
      한 번마다 접수 확인을 기다린다 — 몇 분이 걸려 화면이 끊긴다.
    """
    from lemouton.policy import coupon_service as CS
    s = SessionLocal()
    try:
        out = CS.request_for_model(s, model_code, by='단추')
        s.commit()
        return jsonify(out), (200 if out['ok'] else 400)
    except Exception as e:      # noqa: BLE001
        s.rollback(); _log.exception('[쿠팡쿠폰] 요청 실패 model=%s', model_code)
        return jsonify({'ok': False, 'message': f'요청하지 못했어요: {e}'}), 500
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
