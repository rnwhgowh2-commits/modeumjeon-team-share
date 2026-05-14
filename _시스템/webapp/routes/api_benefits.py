"""소싱처별 동적 혜택 API + 계산 엔진 (v8 A1+B1+C4 — 2026-05-11).

엔드포인트:
  GET    /api/source-benefits/templates                — 모든 사이트 템플릿
  GET    /api/source-benefits/templates/<source_id>    — 한 사이트 템플릿
  POST   /api/source-benefits/templates/<source_id>    — 항목 추가
  PUT    /api/source-benefits/templates/<id>           — 항목 수정
  DELETE /api/source-benefits/templates/<id>           — 항목 삭제
  POST   /api/source-benefits/templates/<source_id>/save-all — 일괄 저장

  GET    /api/source-benefits/overrides/<sku>/<source_id>   — 옵션 override
  POST   /api/source-benefits/overrides/<sku>/<source_id>   — 추가
  PUT    /api/source-benefits/overrides/<id>                — 수정
  DELETE /api/source-benefits/overrides/<id>                — 삭제
  POST   /api/source-benefits/overrides/<sku>/<source_id>/save-all — 일괄 저장

  GET    /api/source-benefits/breakdown/<sku>/<source_id>?sale_price=N
            — 누적 차감 계산식 (template + override 머지)

설계:
  • 템플릿 = 사이트 default. 옵션 override 없을 때 적용
  • Override = 같은 (sku, source_id) 에 항목 있으면 우선 (template_id=NULL 이면 단독 신규)
  • 계산식: 판매가 → enabled 항목 순서대로 누적 차감 (rate: 베이스 × value / amount: 고정 차감)
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate, OptionBenefitOverride
from lemouton.sources.models import CardDiscountUserPref


bp = Blueprint('api_benefits', __name__, url_prefix='/api/source-benefits')


# ─── 팀공유 모드: admin 전용 (혜택·쿠폰 = 매출 영향, 회색지대 → admin). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _ok(**kw):
    return jsonify({'ok': True, **kw})


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


def _item_dict(it, kind='tpl'):
    return {
        'id': it.id,
        'source_id': it.source_id,
        'benefit_name': it.benefit_name,
        'benefit_type': it.benefit_type,
        'value': float(it.value or 0),
        'enabled': bool(it.enabled),
        'sort_order': it.sort_order or 0,
        **({'template_id': it.template_id, 'canonical_sku': it.canonical_sku}
           if kind == 'ovr' else {}),
    }


# ─────────── 템플릿 ───────────
@bp.get('/templates')
def list_all_templates():
    s = SessionLocal()
    try:
        items = (s.query(SourceBenefitTemplate)
                 .order_by(SourceBenefitTemplate.source_id,
                           SourceBenefitTemplate.sort_order,
                           SourceBenefitTemplate.id)
                 .all())
        out = {}
        for it in items:
            out.setdefault(it.source_id, []).append(_item_dict(it))
        return _ok(by_source=out)
    finally:
        s.close()


@bp.get('/templates/<int:source_id>')
def list_source_template(source_id: int):
    s = SessionLocal()
    try:
        items = (s.query(SourceBenefitTemplate)
                 .filter_by(source_id=source_id)
                 .order_by(SourceBenefitTemplate.sort_order, SourceBenefitTemplate.id)
                 .all())
        return _ok(items=[_item_dict(it) for it in items])
    finally:
        s.close()


@bp.post('/templates/<int:source_id>')
def add_template_item(source_id: int):
    data = request.get_json(silent=True) or {}
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    t = data.get('benefit_type', 'rate')
    if t not in ('rate', 'amount'):
        return _err('benefit_type 은 rate 또는 amount')
    s = SessionLocal()
    try:
        # sort_order 자동 = 마지막 + 1
        last = (s.query(SourceBenefitTemplate)
                .filter_by(source_id=source_id)
                .order_by(SourceBenefitTemplate.sort_order.desc())
                .first())
        next_order = (last.sort_order + 1) if last else 0
        item = SourceBenefitTemplate(
            source_id=source_id,
            benefit_name=nm,
            benefit_type=t,
            value=float(data.get('value') or 0),
            enabled=bool(data.get('enabled', True)),
            sort_order=int(data.get('sort_order', next_order)),
        )
        s.add(item)
        s.commit()
        return _ok(item=_item_dict(item))
    finally:
        s.close()


@bp.put('/templates/<int:item_id>')
def update_template_item(item_id: int):
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        it = s.get(SourceBenefitTemplate, item_id)
        if not it:
            return _err('항목 없음', 404)
        if 'benefit_name' in data:
            it.benefit_name = (data['benefit_name'] or '').strip()
        if 'benefit_type' in data and data['benefit_type'] in ('rate', 'amount'):
            it.benefit_type = data['benefit_type']
        if 'value' in data:
            it.value = float(data['value'] or 0)
        if 'enabled' in data:
            it.enabled = bool(data['enabled'])
        if 'sort_order' in data:
            it.sort_order = int(data['sort_order'])
        s.commit()
        return _ok(item=_item_dict(it))
    finally:
        s.close()


@bp.delete('/templates/<int:item_id>')
def delete_template_item(item_id: int):
    s = SessionLocal()
    try:
        it = s.get(SourceBenefitTemplate, item_id)
        if not it:
            return _err('항목 없음', 404)
        s.delete(it)
        s.commit()
        return _ok(deleted=item_id)
    finally:
        s.close()


@bp.post('/templates/<int:source_id>/save-all')
def save_all_template(source_id: int):
    """전체 항목 일괄 저장 (UI 의 [💾 저장] 버튼).

    payload: {items: [{id?, benefit_name, benefit_type, value, enabled, sort_order}, ...]}
    기존 항목 중 payload 에 없는 id 는 삭제. id 없으면 신규 추가.
    """
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    s = SessionLocal()
    try:
        existing = {it.id: it for it in (s.query(SourceBenefitTemplate)
                                          .filter_by(source_id=source_id).all())}
        keep_ids = set()
        for idx, raw in enumerate(items):
            nm = (raw.get('benefit_name') or '').strip()
            if not nm:
                continue
            t = raw.get('benefit_type', 'rate')
            if t not in ('rate', 'amount'):
                t = 'rate'
            v = float(raw.get('value') or 0)
            en = bool(raw.get('enabled', True))
            so = int(raw.get('sort_order', idx))
            rid = raw.get('id')
            if rid and rid in existing:
                it = existing[rid]
                it.benefit_name = nm
                it.benefit_type = t
                it.value = v
                it.enabled = en
                it.sort_order = so
                keep_ids.add(rid)
            else:
                it = SourceBenefitTemplate(
                    source_id=source_id, benefit_name=nm, benefit_type=t,
                    value=v, enabled=en, sort_order=so,
                )
                s.add(it)
                s.flush()
                keep_ids.add(it.id)
        # 삭제
        for rid, it in existing.items():
            if rid not in keep_ids:
                s.delete(it)
        s.commit()
        # 갱신된 list 반환
        items_out = (s.query(SourceBenefitTemplate)
                     .filter_by(source_id=source_id)
                     .order_by(SourceBenefitTemplate.sort_order, SourceBenefitTemplate.id)
                     .all())
        return _ok(items=[_item_dict(it) for it in items_out])
    finally:
        s.close()


# ─────────── Override ───────────
@bp.get('/overrides/<sku>/<int:source_id>')
def list_overrides(sku: str, source_id: int):
    s = SessionLocal()
    try:
        items = (s.query(OptionBenefitOverride)
                 .filter_by(canonical_sku=sku, source_id=source_id)
                 .order_by(OptionBenefitOverride.sort_order, OptionBenefitOverride.id)
                 .all())
        return _ok(items=[_item_dict(it, 'ovr') for it in items])
    finally:
        s.close()


@bp.post('/overrides/<sku>/<int:source_id>')
def add_override(sku: str, source_id: int):
    data = request.get_json(silent=True) or {}
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    s = SessionLocal()
    try:
        last = (s.query(OptionBenefitOverride)
                .filter_by(canonical_sku=sku, source_id=source_id)
                .order_by(OptionBenefitOverride.sort_order.desc()).first())
        next_order = (last.sort_order + 1) if last else 0
        item = OptionBenefitOverride(
            canonical_sku=sku, source_id=source_id,
            template_id=data.get('template_id'),
            benefit_name=nm,
            benefit_type=data.get('benefit_type', 'rate'),
            value=float(data.get('value') or 0),
            enabled=bool(data.get('enabled', True)),
            sort_order=int(data.get('sort_order', next_order)),
        )
        s.add(item)
        s.commit()
        return _ok(item=_item_dict(item, 'ovr'))
    finally:
        s.close()


@bp.put('/overrides/<int:item_id>')
def update_override(item_id: int):
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        it = s.get(OptionBenefitOverride, item_id)
        if not it:
            return _err('override 없음', 404)
        for fld in ('benefit_name', 'benefit_type', 'value', 'enabled', 'sort_order'):
            if fld in data:
                v = data[fld]
                if fld == 'value':
                    v = float(v or 0)
                elif fld == 'enabled':
                    v = bool(v)
                elif fld == 'sort_order':
                    v = int(v)
                setattr(it, fld, v)
        s.commit()
        return _ok(item=_item_dict(it, 'ovr'))
    finally:
        s.close()


@bp.delete('/overrides/<int:item_id>')
def delete_override(item_id: int):
    s = SessionLocal()
    try:
        it = s.get(OptionBenefitOverride, item_id)
        if not it:
            return _err('override 없음', 404)
        s.delete(it)
        s.commit()
        return _ok(deleted=item_id)
    finally:
        s.close()


@bp.post('/overrides/<sku>/<int:source_id>/save-all')
def save_all_overrides(sku: str, source_id: int):
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    s = SessionLocal()
    try:
        existing = {it.id: it for it in (s.query(OptionBenefitOverride)
                                          .filter_by(canonical_sku=sku, source_id=source_id).all())}
        keep_ids = set()
        for idx, raw in enumerate(items):
            nm = (raw.get('benefit_name') or '').strip()
            if not nm:
                continue
            t = raw.get('benefit_type', 'rate')
            if t not in ('rate', 'amount'):
                t = 'rate'
            v = float(raw.get('value') or 0)
            en = bool(raw.get('enabled', True))
            so = int(raw.get('sort_order', idx))
            rid = raw.get('id')
            tpl_id = raw.get('template_id')
            if rid and rid in existing:
                it = existing[rid]
                it.benefit_name = nm
                it.benefit_type = t
                it.value = v
                it.enabled = en
                it.sort_order = so
                it.template_id = tpl_id
                keep_ids.add(rid)
            else:
                it = OptionBenefitOverride(
                    canonical_sku=sku, source_id=source_id,
                    template_id=tpl_id, benefit_name=nm, benefit_type=t,
                    value=v, enabled=en, sort_order=so,
                )
                s.add(it)
                s.flush()
                keep_ids.add(it.id)
        for rid, it in existing.items():
            if rid not in keep_ids:
                s.delete(it)
        s.commit()
        items_out = (s.query(OptionBenefitOverride)
                     .filter_by(canonical_sku=sku, source_id=source_id)
                     .order_by(OptionBenefitOverride.sort_order, OptionBenefitOverride.id)
                     .all())
        return _ok(items=[_item_dict(it, 'ovr') for it in items_out])
    finally:
        s.close()


# ─────────── 계산 엔진 (누적 차감) ───────────
def compute_breakdown(session, *, sku: str, source_id: int, sale_price: float,
                       bundle_code: str = None):
    """누적 차감 계산.

    1. SourceBenefitTemplate (사이트 default) 조회
    2. OptionBenefitOverride (옵션 override) 조회 — 우선 적용
    3. enabled 항목만 누적 차감
    4. ★ 2026-05-13 — 카드 미반영 토글 (CardDiscountUserPref) 자동 반영:
       card_enabled=False 면 benefit_name 안에 카드 issuer (예: '현대카드') 가
       포함된 항목들의 enabled 강제 False (UI 토글과 무관).
    """
    # ── 카드 미반영 토글 lookup ───────────────────────────────
    # SourceProduct.auto_card_discount_json 의 issuer 와 resolve_card_enabled.
    _card_enabled = True
    _card_issuer = None
    try:
        from lemouton.sources.models import SourceProduct
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        # 옵션의 sku 와 source_id 로 product_url → SourceProduct lookup
        link = (session.query(OptionSourceUrl)
                .filter_by(canonical_sku=sku, source_id=source_id)
                .first())
        if link and link.product_url:
            from lemouton.sources.service import normalize_url as _nu
            target_norm = _nu(link.product_url)
            sps = (session.query(SourceProduct)
                   .filter(SourceProduct.deleted_at.is_(None))
                   .all())
            sp = next((s for s in sps if _nu(s.url) == target_norm), None)
            if sp and sp.auto_card_discount_json:
                import json as _json
                try:
                    acd = _json.loads(sp.auto_card_discount_json)
                    _card_issuer = (acd or {}).get('issuer')
                except (ValueError, TypeError):
                    pass
            if _card_issuer:
                _card_enabled = resolve_card_enabled(
                    session,
                    canonical_sku=sku, source_id=source_id, bundle_code=bundle_code,
                )
    except Exception:
        pass
    tpl_items = (session.query(SourceBenefitTemplate)
                 .filter_by(source_id=source_id)
                 .order_by(SourceBenefitTemplate.sort_order, SourceBenefitTemplate.id)
                 .all())
    ovr_items = (session.query(OptionBenefitOverride)
                 .filter_by(canonical_sku=sku, source_id=source_id)
                 .order_by(OptionBenefitOverride.sort_order, OptionBenefitOverride.id)
                 .all())
    # 매칭: ovr 의 template_id 가 매핑된 tpl 은 ovr 로 대체
    ovr_by_tpl = {ovr.template_id: ovr for ovr in ovr_items if ovr.template_id}
    ovr_standalone = [ovr for ovr in ovr_items if not ovr.template_id]
    # 적용 순서: tpl 순서 (ovr 대체) → ovr 단독 추가
    effective = []
    for tpl in tpl_items:
        if tpl.id in ovr_by_tpl:
            effective.append(('ovr', ovr_by_tpl[tpl.id]))
        else:
            effective.append(('tpl', tpl))
    for ovr in ovr_standalone:
        effective.append(('ovr_new', ovr))
    # ★ 2026-05-14 — 카테고리 계산 순서 강제:
    #   1) 정액 (amount)  먼저 차감
    #   2) % 적립금       (rate + benefit_name 에 '적립' 포함) — 정액 차감 후 베이스 기준
    #   3) % 추가 할인    (rate, 그 외)                       — 적립금까지 차감 후 베이스 기준
    #   적립금은 미래에 또 사용될 자산이므로 카드·할인 % 의 베이스에서도 미리 빼고 본다.
    #   Python 정렬은 stable → 같은 카테고리 내 원래 sort_order 유지.
    def _benefit_priority(it):
        if (it.benefit_type or 'rate') == 'amount':
            return 0
        if '적립' in (it.benefit_name or ''):
            return 1
        return 2
    effective.sort(key=lambda x: _benefit_priority(x[1]))
    # 누적 차감
    base = float(sale_price)
    steps = []
    items_used = []
    for kind, it in effective:
        # ★ 카드 미반영 토글 적용 — issuer 가 benefit_name 안 포함 + card_enabled=False
        #    → 그 항목 자동 비활성화 (캐시백·카드할인 카테고리).
        _by_card_off = (
            (not _card_enabled) and _card_issuer
            and (_card_issuer in (it.benefit_name or ''))
        )
        is_effective_enabled = bool(it.enabled) and not _by_card_off
        items_used.append({
            'kind': kind,  # 'tpl' / 'ovr' / 'ovr_new'
            'id': it.id,
            'name': it.benefit_name,
            'type': it.benefit_type,
            'value': float(it.value or 0),
            'enabled': is_effective_enabled,
            'disabled_by_card_off': _by_card_off,
        })
        if not is_effective_enabled:
            continue
        if it.benefit_type == 'rate':
            deduct = int(base * (it.value or 0))
        else:  # amount
            deduct = int(it.value or 0)
        deduct = min(deduct, int(base))  # 음수 방지
        base = max(base - deduct, 0)
        steps.append({
            'name': it.benefit_name,
            'type': it.benefit_type,
            'value': float(it.value or 0),
            'deduct': deduct,
            'base_after': int(base),
        })
    return {
        'sale_price': float(sale_price),
        'final_price': int(base),
        'steps': steps,
        'items_used': items_used,
    }


@bp.get('/breakdown/<sku>/<int:source_id>')
def get_breakdown(sku: str, source_id: int):
    try:
        sale_price = float(request.args.get('sale_price', 0))
    except ValueError:
        return _err('sale_price 숫자 형식 오류')
    s = SessionLocal()
    try:
        out = compute_breakdown(s, sku=sku, source_id=source_id, sale_price=sale_price)
        return _ok(**out)
    finally:
        s.close()


@bp.post('/breakdowns')
def bulk_breakdowns():
    """일괄 계산. payload: {items: [{sku, source_id, sale_price}, ...]}.

    Returns: {results: {[sku+'|'+source_id]: {final_price, steps, ...}}}
    매트릭스 일괄 fetch 용 — 셀별 1회 호출 대신 1번에 N건.
    """
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    s = SessionLocal()
    try:
        out = {}
        for it in items:
            sku = it.get('sku')
            sid = it.get('source_id')
            sp = float(it.get('sale_price') or 0)
            if not sku or sid is None or sp <= 0:
                continue
            key = f"{sku}|{sid}"
            try:
                out[key] = compute_breakdown(s, sku=sku, source_id=int(sid), sale_price=sp)
            except Exception as e:
                out[key] = {'error': str(e)}
        return _ok(results=out)
    finally:
        s.close()


# ════════════════════════════════════════════
#  카드 미반영 토글 (시안 A1)
# ════════════════════════════════════════════
def resolve_card_enabled(session, *, canonical_sku: str, source_id: int,
                          bundle_code: str = None) -> bool:
    """카드 적용 여부 우선순위 조회: option > bundle > global > default ON."""
    row = (session.query(CardDiscountUserPref)
           .filter_by(scope='option', canonical_sku=canonical_sku, source_id=source_id)
           .first())
    if row:
        return bool(row.enabled)
    if bundle_code:
        row = (session.query(CardDiscountUserPref)
               .filter_by(scope='bundle', bundle_code=bundle_code, source_id=source_id)
               .first())
        if row:
            return bool(row.enabled)
    row = (session.query(CardDiscountUserPref)
           .filter_by(scope='global', source_id=source_id)
           .first())
    if row:
        return bool(row.enabled)
    return True  # default ON (사용자가 카드 보유)


@bp.post('/card-toggle')
def card_toggle():
    """카드 미반영 토글 저장 (시안 A1).

    payload: {
      scope: 'option' | 'bundle' | 'global',
      canonical_sku?: str   (scope='option')
      bundle_code?: str     (scope='bundle')
      source_id: int        (모든 scope)
      enabled: bool         (False = OFF = 카드 미보유)
    }
    """
    data = request.get_json(silent=True) or {}
    scope = (data.get('scope') or '').strip()
    if scope not in ('option', 'bundle', 'global'):
        return _err('scope 는 option | bundle | global')
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    enabled = 1 if data.get('enabled') else 0
    sku = (data.get('canonical_sku') or '').strip() or None
    bundle_code = (data.get('bundle_code') or '').strip() or None
    if scope == 'option' and not sku:
        return _err("scope='option' 시 canonical_sku 필수")
    if scope == 'bundle' and not bundle_code:
        return _err("scope='bundle' 시 bundle_code 필수")

    s = SessionLocal()
    try:
        # 멱등 upsert
        q = s.query(CardDiscountUserPref).filter_by(scope=scope, source_id=source_id)
        if scope == 'option':
            q = q.filter_by(canonical_sku=sku)
        elif scope == 'bundle':
            q = q.filter_by(bundle_code=bundle_code)
        existing = q.first()
        if existing:
            existing.enabled = enabled
        else:
            s.add(CardDiscountUserPref(
                scope=scope, source_id=source_id,
                canonical_sku=sku, bundle_code=bundle_code,
                enabled=enabled,
            ))
        s.commit()
        return _ok(scope=scope, source_id=source_id, enabled=bool(enabled))
    finally:
        s.close()


# ════════════════════════════════════════════
#  2026-05-13 — 혜택 N개 옵션 일괄 토글 (시안 v6-3 모달용)
# ════════════════════════════════════════════
@bp.post('/overrides/bulk-toggle')
def bulk_toggle_benefit():
    """N 옵션에 동일 혜택 enabled 일괄 변경.

    payload: {
      source_id: int,
      skus: [str, ...],         # 적용 대상 옵션 sku 리스트
      template_id?: int,        # 템플릿 매칭 (tpl 항목) — 없으면 benefit_name 매칭
      benefit_name: str,        # 필수 (매칭 + 새 override 생성에 사용)
      benefit_type?: str,       # 새 생성 시 'rate' | 'amount' (기본 'rate')
      value?: float,            # 새 생성 시 값
      enabled: bool             # True | False
    }
    각 sku 에 대해:
      - 매칭되는 override 있으면 enabled 변경
      - 없으면 새 override 생성 (template_id + benefit_name + enabled)
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    skus = data.get('skus') or []
    if not isinstance(skus, list) or not skus:
        return _err('skus 리스트 필수')
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    tpl_id = data.get('template_id')
    en = bool(data.get('enabled', True))
    t = data.get('benefit_type', 'rate')
    val = float(data.get('value') or 0)

    s = SessionLocal()
    try:
        affected = 0
        for sku in skus:
            # 매칭: 같은 source_id + 같은 sku + (template_id 매칭 OR benefit_name 매칭)
            q = (s.query(OptionBenefitOverride)
                 .filter_by(canonical_sku=sku, source_id=source_id))
            if tpl_id:
                existing = q.filter_by(template_id=tpl_id).first()
            else:
                existing = q.filter_by(benefit_name=nm).first()
            if existing:
                existing.enabled = en
            else:
                last = (s.query(OptionBenefitOverride)
                        .filter_by(canonical_sku=sku, source_id=source_id)
                        .order_by(OptionBenefitOverride.sort_order.desc()).first())
                next_order = (last.sort_order + 1) if last else 0
                s.add(OptionBenefitOverride(
                    canonical_sku=sku, source_id=source_id,
                    template_id=tpl_id, benefit_name=nm,
                    benefit_type=t, value=val,
                    enabled=en, sort_order=next_order,
                ))
            affected += 1
        s.commit()
        return _ok(affected=affected, skus=skus)
    finally:
        s.close()


@bp.post('/overrides/bulk-bundle/<int:source_id>')
def add_override_to_bundle(source_id: int):
    """모음전 단위 일괄 override — 그 모음전의 모든 옵션에 같은 혜택 추가.

    payload: {
      skus: ['sku1', 'sku2', ...],
      benefit_name, benefit_type, value, enabled
    }
    """
    data = request.get_json(silent=True) or {}
    skus = data.get('skus') or []
    nm = (data.get('benefit_name') or '').strip()
    if not nm or not skus:
        return _err('skus 와 benefit_name 필수')
    t = data.get('benefit_type', 'rate')
    if t not in ('rate', 'amount'):
        return _err('benefit_type 은 rate 또는 amount')
    val = float(data.get('value') or 0)
    en = bool(data.get('enabled', True))
    s = SessionLocal()
    try:
        added = 0
        for sku in skus:
            last = (s.query(OptionBenefitOverride)
                    .filter_by(canonical_sku=sku, source_id=source_id)
                    .order_by(OptionBenefitOverride.sort_order.desc()).first())
            next_order = (last.sort_order + 1) if last else 0
            it = OptionBenefitOverride(
                canonical_sku=sku, source_id=source_id,
                template_id=None,  # bundle override = 단독 신규
                benefit_name=nm, benefit_type=t,
                value=val, enabled=en, sort_order=next_order,
            )
            s.add(it)
            added += 1
        s.commit()
        return _ok(added=added, skus=skus)
    finally:
        s.close()
