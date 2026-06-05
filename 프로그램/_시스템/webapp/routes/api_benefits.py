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
def _build_breakdown_cache(session, items: list) -> dict:
    """[2026-06-05 perf] bulk_breakdowns N+1 제거 — compute_breakdown 이 item 당
    5개씩 하던 쿼리(OptionSourceUrl·SourceProduct 전체·Template·Override·CardPref)를
    여기서 1회씩만 조회해 인덱스로 만든다. (876건×5쿼리×원격RTT ≈ 110초 → 5쿼리)."""
    from collections import defaultdict
    from lemouton.sources.models import SourceProduct
    from lemouton.sourcing.models_pricing import OptionSourceUrl
    from lemouton.sources.service import normalize_url as _nu
    skus = list({it.get('sku') for it in items if it.get('sku')})
    sids = list({int(it.get('source_id')) for it in items
                 if it.get('source_id') is not None})
    link_by = {}
    if skus and sids:
        for l in (session.query(OptionSourceUrl)
                  .filter(OptionSourceUrl.canonical_sku.in_(skus),
                          OptionSourceUrl.source_id.in_(sids)).all()):
            link_by[(l.canonical_sku, l.source_id)] = l
    sp_by_norm = {}
    for sp in (session.query(SourceProduct)
               .filter(SourceProduct.deleted_at.is_(None)).all()):
        if sp.url:
            sp_by_norm[_nu(sp.url)] = sp
    tpl_by_src = defaultdict(list)
    if sids:
        for t in (session.query(SourceBenefitTemplate)
                  .filter(SourceBenefitTemplate.source_id.in_(sids))
                  .order_by(SourceBenefitTemplate.sort_order,
                            SourceBenefitTemplate.id).all()):
            tpl_by_src[t.source_id].append(t)
    ovr_by = defaultdict(list)
    if skus and sids:
        for o in (session.query(OptionBenefitOverride)
                  .filter(OptionBenefitOverride.canonical_sku.in_(skus),
                          OptionBenefitOverride.source_id.in_(sids))
                  .order_by(OptionBenefitOverride.sort_order,
                            OptionBenefitOverride.id).all()):
            ovr_by[(o.canonical_sku, o.source_id)].append(o)
    prefs = []
    if sids:
        prefs = (session.query(CardDiscountUserPref)
                 .filter(CardDiscountUserPref.source_id.in_(sids)).all())
    return {'link_by': link_by, 'sp_by_norm': sp_by_norm,
            'tpl_by_src': tpl_by_src, 'ovr_by': ovr_by, 'prefs': prefs}


def compute_breakdown(session, *, sku: str, source_id: int, sale_price: float,
                       bundle_code: str = None, _cache: dict = None):
    """_cache: bulk 호출 시 N+1 제거용 사전 로드 인덱스(_build_breakdown_cache).
    None 이면(단일 호출) 기존처럼 매번 쿼리."""
    """누적 차감 계산.

    1. SourceBenefitTemplate (사이트 default) 조회
    2. OptionBenefitOverride (옵션 override) 조회 — 우선 적용
    3. enabled 항목만 누적 차감
    4. ★ 2026-05-13 — 카드 미반영 토글 (CardDiscountUserPref) 자동 반영:
       card_enabled=False 면 benefit_name 안에 카드 issuer (예: '현대카드') 가
       포함된 항목들의 enabled 강제 False (UI 토글과 무관).
    """
    # ── 카드 미반영 토글 + 동적 혜택 lookup ───────────────────────────────
    # SourceProduct.auto_card_discount_json + dynamic_benefits_json 모두 가져옴.
    _card_enabled = True
    _card_issuer = None
    _dynamic_benefits = {}
    try:
        from lemouton.sources.models import SourceProduct
        from lemouton.sourcing.models_pricing import OptionSourceUrl
        # 옵션의 sku 와 source_id 로 product_url → SourceProduct lookup
        if _cache is not None:
            link = _cache['link_by'].get((sku, source_id))
        else:
            link = (session.query(OptionSourceUrl)
                    .filter_by(canonical_sku=sku, source_id=source_id)
                    .first())
        if link and link.product_url:
            from lemouton.sources.service import normalize_url as _nu
            target_norm = _nu(link.product_url)
            if _cache is not None:
                sp = _cache['sp_by_norm'].get(target_norm)
            else:
                sps = (session.query(SourceProduct)
                       .filter(SourceProduct.deleted_at.is_(None))
                       .all())
                sp = next((s for s in sps if _nu(s.url) == target_norm), None)
            if sp:
                import json as _json
                if sp.auto_card_discount_json:
                    try:
                        acd = _json.loads(sp.auto_card_discount_json)
                        _card_issuer = (acd or {}).get('issuer')
                    except (ValueError, TypeError):
                        pass
                if sp.dynamic_benefits_json:
                    try:
                        _dynamic_benefits = _json.loads(sp.dynamic_benefits_json) or {}
                    except (ValueError, TypeError):
                        _dynamic_benefits = {}
            if _card_issuer:
                _card_enabled = resolve_card_enabled(
                    session,
                    canonical_sku=sku, source_id=source_id, bundle_code=bundle_code,
                    _prefs=(_cache['prefs'] if _cache is not None else None),
                )
    except Exception:
        pass

    # ★ 2026-06-05 — 전 소싱처 보강 조회: OptionSourceUrl 미연결(모음전/단품 매칭) 옵션은
    #   option_source_links → SourceProduct.dynamic_benefits_json 에서 동적 혜택(무신사 등급적립·
    #   무신사머니, SSF 멤버십포인트·기프트포인트, SSG MONEY, 롯데오너스 등)을 읽는다.
    #   SourceProduct 레벨이라 relogin(옵션레벨)에 안 덮인다. source_id→site 매핑(source_registry 기준).
    _SITE_BY_SRC = {1: 'lemouton', 2: 'ss_lemouton', 3: 'musinsa', 4: 'ssf', 5: 'lotteon', 6: 'ssg'}
    try:
        _site_for = _SITE_BY_SRC.get(int(source_id))
    except (TypeError, ValueError):
        _site_for = None
    if _site_for and not _dynamic_benefits:
        try:
            from sqlalchemy import text as _sqltext
            import json as _json
            _rows2 = session.execute(_sqltext(
                "SELECT sp.dynamic_benefits_json FROM option_source_links l "
                "JOIN source_options so ON l.source_option_id = so.id "
                "JOIN source_products sp ON so.source_product_id = sp.id "
                "WHERE l.canonical_sku = :sku AND sp.site = :site "
                "AND so.deleted_at IS NULL AND sp.deleted_at IS NULL "
                "AND sp.dynamic_benefits_json IS NOT NULL"
            ), {'sku': sku, 'site': _site_for}).fetchall()
            _best2 = None
            for (_dj,) in _rows2:
                try:
                    _d2 = _json.loads(_dj) or {}
                except Exception:
                    continue
                if not _d2:
                    continue
                # 무신사: 표면가 있고 등급적립 금액 최대(모음전 회원가) 채택. 그 외: 첫 non-empty.
                if _site_for == 'musinsa':
                    if _d2.get('surface_price') and (_best2 is None or (_d2.get('grade_reward_amount') or 0) > (_best2.get('grade_reward_amount') or 0)):
                        _best2 = _d2
                elif _best2 is None:
                    _best2 = _d2
            if _best2:
                _dynamic_benefits = _best2
        except Exception:
            pass
    if _cache is not None:
        tpl_items = _cache['tpl_by_src'].get(source_id, [])
    else:
        tpl_items = (session.query(SourceBenefitTemplate)
                     .filter_by(source_id=source_id)
                     .order_by(SourceBenefitTemplate.sort_order, SourceBenefitTemplate.id)
                     .all())
    if _cache is not None:
        ovr_items = _cache['ovr_by'].get((sku, source_id), [])
    else:
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

    # ★ 2026-05-15 — SourceProduct.dynamic_benefits_json 에서 동적 혜택 차감 항목 추가.
    #   옵션 dict 의 사이트 특화 동적 키들 (point_rate / ssg_money_rate / card_benefit_price
    #   / money_active 등) 을 dummy item 으로 effective 에 박는다. 정액 → %적립금 → %할인
    #   카테고리 정렬 룰이 자동 적용됨.
    class _DynBenefit:
        """compute_breakdown 의 effective 리스트에 들어가는 동적 dummy 항목."""
        def __init__(self, *, name, btype, value, enabled=True):
            self.id = -1
            self.benefit_name = name
            self.benefit_type = btype
            self.value = value
            self.enabled = enabled
            self.sort_order = 999  # 같은 카테고리 내 마지막
            self.template_id = None
    if _dynamic_benefits:
        # SSF 멤버십포인트 (사이트 노출 적립률 — 변동값)
        _pr = _dynamic_benefits.get('point_rate')
        if _pr and isinstance(_pr, (int, float)) and _pr > 0:
            effective.append(('dyn', _DynBenefit(
                name='멤버십포인트 (사이트 적립)',
                btype='rate', value=float(_pr),
            )))
        # SSF 기프트포인트 (정액, 멤버십 한정) — 사용자 무료 보유분 多 → 활성 기본.
        _gpa = _dynamic_benefits.get('gift_point_amount')
        if _gpa and isinstance(_gpa, (int, float)) and _gpa > 0:
            effective.append(('dyn', _DynBenefit(
                name='기프트포인트 (멤버십 한정)',
                btype='amount', value=float(_gpa),
                enabled=True,
            )))
        # SSG MONEY 별도 적립 (already_applied=False 일 때만 차감 — 중복 매입 방지)
        # 사용자 명세 (2026-05-15) 3 케이스:
        #   (1) 무조건 X% 적립 → 항상 활성 (매입가 반영)
        #   (2) 구매혜택의 'SSG MONEY 결제시 X% 적립' (충전결제) → rate >= 3% 일 때만 활성
        #       (현대카드 결제가 더 유리하므로 3% 미만은 매입가 반영 안 함)
        #   (3) '적립 or 즉시할인' → already_applied=True 처리됨 (아래 if 가 자동 skip)
        _smr = _dynamic_benefits.get('ssg_money_rate')
        _sma = _dynamic_benefits.get('ssg_money_already_applied')
        _smt = _dynamic_benefits.get('ssg_money_text') or ''
        if _smr and not _sma:
            _rate = float(_smr) / 100 if float(_smr) > 1 else float(_smr)
            _is_charge = ('충전' in _smt)  # 케이스 (2) 판정
            _ssgm_enabled = (not _is_charge) or (_rate >= 0.03)
            _ssgm_name = (
                f'SSG MONEY 충전결제 적립 ({_rate*100:g}% — 3% 미만 / 비활성)'
                if (_is_charge and not _ssgm_enabled)
                else ('SSG MONEY 충전결제 적립' if _is_charge else 'SSG MONEY 적립')
            )
            effective.append(('dyn', _DynBenefit(
                name=_ssgm_name,
                btype='rate', value=_rate,
                enabled=_ssgm_enabled,
            )))
        # SSG 카드혜택가 (조건부 정액) — 2026-05-15 패치:
        #   기존: enabled=False (조건 충족 여부 사용자 결정 / 표시만)
        #   신규: card_benefit_condition 에서 "X만원 이상" 정규식 추출 → sale_price 비교.
        #         조건 충족 시 자동 enabled=True. 예: "5만원 이상 결제 시 98,767원".
        _cbp = _dynamic_benefits.get('card_benefit_price')
        _cbp_active = False  # 활성화됐으면 현대카드 fallback 비활성 룰 트리거
        if _cbp and isinstance(_cbp, (int, float)) and _cbp > 0:
            # 매트릭스 베이스 (sale_price) - card_benefit_price = 정액 차감
            _amount = float(sale_price) - float(_cbp)
            if _amount > 0:
                # 조건 자동 추출: "X만원 이상" / "X,000원 이상" / "X원 이상"
                _cond = (_dynamic_benefits.get('card_benefit_condition') or '')
                _min_order = 0
                import re as _re_cond
                m_man = _re_cond.search(r'(\d+)\s*만\s*원\s*이상', _cond)
                if m_man:
                    try:
                        _min_order = int(m_man.group(1)) * 10000
                    except ValueError:
                        pass
                if _min_order == 0:
                    m_won = _re_cond.search(r'([0-9][0-9,]*)\s*원\s*이상', _cond)
                    if m_won:
                        try:
                            _min_order = int(m_won.group(1).replace(',', ''))
                        except ValueError:
                            pass
                # min_order 추출 실패 시 보수적으로 5만원 fallback (SSG 표준)
                if _min_order == 0:
                    _min_order = 50000
                _cbp_active = (float(sale_price) >= _min_order)
                _label = '카드혜택가 (조건 충족)' if _cbp_active else '카드혜택가 (조건 미충족 / 표시만)'
                effective.append(('dyn', _DynBenefit(
                    name=_label,
                    btype='amount', value=_amount,
                    enabled=_cbp_active,
                )))
        # SSG 상품쿠폰 (X% / 정액 + 최소 구매금액 조건) — 2026-05-15
        # 사용자 명세 (2026-05-15 재수정): "자동활성 안돼. 베이스금액에서 차감해야해."
        #   → enabled=False 기본 (사용자가 매트릭스 토글로 매번 활성. "다운로드 1일이내
        #     사용" 조건이라 매번 받아야 함). 활성 시에만 베이스 × rate 차감.
        # 이름에 '쿠폰' 포함 → 카테고리 정렬 룰에 의해 '%할인' 그룹으로 분류.
        _pcr = _dynamic_benefits.get('product_coupon_rate')
        _pca = _dynamic_benefits.get('product_coupon_amount')
        _pcmin = _dynamic_benefits.get('product_coupon_min_order') or 0
        _pclabel = _dynamic_benefits.get('product_coupon_label') or ''
        if _pcr and isinstance(_pcr, (int, float)) and _pcr > 0:
            _rate = float(_pcr) / 100 if float(_pcr) > 1 else float(_pcr)
            _nm = f"상품쿠폰 {int(_rate*100)}% ({int(_pcmin/10000)}만원 이상)" if _pcmin else f"상품쿠폰 {int(_rate*100)}%"
            if _pclabel:
                _nm = f"{_nm} — {_pclabel}"
            effective.append(('dyn', _DynBenefit(
                name=_nm,
                btype='rate', value=_rate,
                enabled=False,  # 사용자 토글로 결정 (자동 활성 X)
            )))
        elif _pca and isinstance(_pca, (int, float)) and _pca > 0:
            _nm = f"상품쿠폰 {int(_pca):,}원 ({int(_pcmin/10000)}만원 이상)" if _pcmin else f"상품쿠폰 {int(_pca):,}원"
            if _pclabel:
                _nm = f"{_nm} — {_pclabel}"
            effective.append(('dyn', _DynBenefit(
                name=_nm,
                btype='amount', value=float(_pca),
                enabled=False,  # 사용자 토글로 결정
            )))
        # 무신사머니 활성 시 → 현대카드 fallback 비활성 (중복 차감 방지)
        # money_active=True 면 effective 내 '현대카드 (무신사머니 fallback)' 항목 비활성화
        _ma = _dynamic_benefits.get('money_active')
        if _ma is True:
            # 기존 template/ovr 중 이름에 '무신사머니 fallback' 또는 'fallback' 포함 항목 비활성
            for kind, it in effective:
                nm = (it.benefit_name or '')
                if 'fallback' in nm.lower() or '무신사머니 fallback' in nm:
                    it.enabled = False
        # SSG 카드혜택가 활성 시 → 현대카드 (카드혜택가 fallback) 비활성 — 2026-05-15
        # 무신사머니 fallback 비활성 패턴과 동일. _cbp_active=True 면 effective 내
        # '카드혜택가 fallback' 이름 포함 항목 자동 비활성 (이중 차감 방지).
        if _cbp_active:
            for kind, it in effective:
                nm = (it.benefit_name or '')
                if '카드혜택가 fallback' in nm:
                    it.enabled = False
        # ─────────────────────────────────────────────────────────────
        # ★ 2026-05-15 — 롯데홈쇼핑 (lotteimall) 동적 혜택 (point_rewards)
        # ─────────────────────────────────────────────────────────────
        # 크롤러가 lPointObj 에서 추출한 dict:
        #   {label, default_point, club_point, review_label, review_default, review_club}
        # 사용자 명세 (2026-05-15):
        #   - 구매적립 L.POINT (L.CLUB)  → 정액 +633원 (사이트 노출 그대로)
        #   - 리뷰 적립 → 제외 (spec ⑤ 롯데홈쇼핑 룰)
        # 시드 src=6 의 '구매적립 L.POINT' 0.5% rate 시드와 중복 방지: 기존 시드 중
        # 이름에 '구매적립 L.POINT' 포함 항목은 enabled=False (dyn 으로 override).
        _pr_obj = _dynamic_benefits.get('point_rewards')
        if isinstance(_pr_obj, dict):
            _club_point = int(_pr_obj.get('club_point') or 0)
            _default_point = int(_pr_obj.get('default_point') or 0)
            _lpoint_value = _club_point if _club_point > 0 else _default_point

            if _lpoint_value > 0:
                for kind, it in effective:
                    nm = (it.benefit_name or '')
                    if 'L.POINT' in nm or '구매적립' in nm or 'LPOINT' in nm.upper():
                        it.enabled = False
                _name = '구매적립 L.POINT (L.CLUB)' if _club_point > 0 else '구매적립 L.POINT (일반)'
                effective.append(('dyn', _DynBenefit(
                    name=_name,
                    btype='amount',
                    value=float(_lpoint_value),
                    enabled=True,
                )))
        # ─────────────────────────────────────────────────────────────
        # ★ 2026-05-15 — 롯데온 (lotteon.com) 동적 혜택
        # ─────────────────────────────────────────────────────────────
        # 사용자 스크린샷 명세 ([150만족 판매] 메이트 발 편한 메리노울 운동화 르무통):
        #   - 롯데오너스 1% 회원할인 → 사용자 회원 가입 상태라 자동 활성 (enabled=True)
        #     · pbf addition API ownersFavor.ownersDcCnts/ownersHighLight 에서 추출
        #     · 산식: base × rate (이름에 '할인' 포함 → %할인 그룹 자동 분류)
        #   - 스토어찜 쿠폰 -6,000원 → 비활성 기본 (사용자 토글로 활성, "받기" 조건)
        #     · pbf favor API STORE_COUPON 그룹 / prKndCd=CPN_SLR_CPN
        #     · 산식: 정액 차감 (SSG 8% 상품쿠폰과 같은 패턴)
        _lmd = _dynamic_benefits.get('lotte_member_discount_rate')
        if _lmd and isinstance(_lmd, (int, float)) and _lmd > 0:
            _label = _dynamic_benefits.get('lotte_member_discount_label') or f'롯데오너스 할인 {_lmd*100:g}%'
            effective.append(('dyn', _DynBenefit(
                name=_label, btype='rate', value=float(_lmd),
                enabled=True,  # 회원 가입 상태 가정
            )))
        _sjc = _dynamic_benefits.get('store_jjim_coupon_amount')
        if _sjc and isinstance(_sjc, (int, float)) and _sjc > 0:
            _label = _dynamic_benefits.get('store_jjim_coupon_label') or f'스토어찜 쿠폰 -{int(_sjc):,}원'
            effective.append(('dyn', _DynBenefit(
                name=_label, btype='amount', value=float(_sjc),
                enabled=False,  # 사용자 토글로 결정 (받기 조건)
            )))
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
    # ★ 2026-06-05 — 무신사 옵션 breakdown 금액 항목 주입 (시안 v3: 표면가 base + 등급적립·무신사머니).
    #   _dynamic_benefits(SourceProduct, option_source_links 조회)의 금액을 항목으로 차감 → 매입가 정확.
    _base_override = None
    if str(source_id) == '3' and _dynamic_benefits.get('surface_price'):
        class _Inj:
            def __init__(self, name, value, enabled=True):
                self.id = -1; self.benefit_name = name; self.benefit_type = 'amount'
                self.value = value; self.enabled = enabled
                self.sort_order = 999; self.template_id = None
        _base_override = float(_dynamic_benefits.get('surface_price') or 0)
        effective.append(('dyn', _Inj('상품쿠폰', float(_dynamic_benefits.get('coupon_amount') or 0), enabled=bool(_dynamic_benefits.get('coupon_amount')))))
        effective.append(('dyn', _Inj('등급할인', float(_dynamic_benefits.get('grade_discount_amount') or 0), enabled=bool(_dynamic_benefits.get('grade_discount_amount')))))
        effective.append(('dyn', _Inj('등급적립', float(_dynamic_benefits.get('grade_reward_amount') or 0), enabled=bool(_dynamic_benefits.get('grade_reward_amount')))))
        effective.append(('dyn', _Inj('무신사머니 결제 적립', float(_dynamic_benefits.get('money_reward_amount') or 0), enabled=bool(_dynamic_benefits.get('money_reward_amount')))))

    effective.sort(key=lambda x: _benefit_priority(x[1]))

    # ★ 2026-06-05 — '무신사머니 fallback' 이중 차감 차단 (사용자 정책).
    #   무신사 크롤 베이스(sale_price)는 '회원가' = 무신사머니 적립이 이미 반영된 값이다.
    #   '현대카드 (무신사머니 fallback)' 은 무신사머니와 택1(상호배타) — 그 위에서 또 차감하면 이중.
    #   → money_active=False (무신사머니 명시 비활성) 일 때만 fallback 적용, 그 외(플래그 없음/True)는
    #     비활성. 안전 방향(원가 과소 → 언더프라이싱 방지). 기존 _dynamic_benefits 가드 밖이라
    #     dynamic_benefits 가 비어 있어도 항상 동작한다. 이름에 '무신사머니 fallback' 포함 항목만 대상.
    _ma_flag = _dynamic_benefits.get('money_active') if _dynamic_benefits else None
    if _ma_flag is not False:
        for _k, _it in effective:
            if '무신사머니 fallback' in (_it.benefit_name or ''):
                _it.enabled = False

    # ★ 2026-06-05 — 결제 수단 택1 (결제수단 자체가 배타: 카드/머니/페이 중 1개로 결제).
    #   ⚠️ 네이버페이는 제외 — 네이버페이는 '카드 결제와 동시'(네이버페이로 현대카드 결제 →
    #      네이버 적립 1% + 카드 캐시백 2.73% 둘 다)이므로 택1이 아니라 항상 누적. (사용자 정책 2026-06-05)
    #   enabled 인 (네이버 제외) 결제 수단이 2개 이상이면 차감액 '가장 큰' 1개만 남기고 비활성.
    def _is_payment(nm):
        nm = nm or ''
        if '네이버' in nm:
            return False  # 네이버페이 적립 = 카드와 동시 적용 → 택1 그룹에서 제외(누적 유지)
        return any(t in nm for t in ('카드', '페이', '무신사머니', '청구할인', '캐시백'))
    _pay = [(_k, _it) for (_k, _it) in effective if _it.enabled and _is_payment(_it.benefit_name)]
    if len(_pay) > 1:
        def _approx_deduct(it):
            v = float(it.value or 0)
            return v if (it.benefit_type or 'rate') == 'amount' else float(sale_price) * v
        _best_it = max((it for _k, it in _pay), key=_approx_deduct)
        for _k, _it in _pay:
            if _it is not _best_it:
                _it.enabled = False

    # 누적 차감 (무신사 breakdown 있으면 base = 표면가 override)
    base = float(_base_override if _base_override is not None else sale_price)
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
        'sale_price': float(_base_override if _base_override is not None else sale_price),
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
        cache = _build_breakdown_cache(s, items)  # [perf] 공통 데이터 1회 로드 (N+1 제거)
        out = {}
        for it in items:
            sku = it.get('sku')
            sid = it.get('source_id')
            sp = float(it.get('sale_price') or 0)
            if not sku or sid is None or sp <= 0:
                continue
            key = f"{sku}|{sid}"
            try:
                out[key] = compute_breakdown(s, sku=sku, source_id=int(sid),
                                             sale_price=sp, _cache=cache)
            except Exception as e:
                out[key] = {'error': str(e)}
        return _ok(results=out)
    finally:
        s.close()


# ════════════════════════════════════════════
#  카드 미반영 토글 (시안 A1)
# ════════════════════════════════════════════
def resolve_card_enabled(session, *, canonical_sku: str, source_id: int,
                          bundle_code: str = None, _prefs: list = None) -> bool:
    """카드 적용 여부 우선순위 조회: option > bundle > global > default ON.
    _prefs: bulk 호출 시 사전 로드한 CardDiscountUserPref 리스트(N+1 제거). 인메모리 조회."""
    if _prefs is not None:
        for p in _prefs:
            if p.scope == 'option' and p.canonical_sku == canonical_sku and p.source_id == source_id:
                return bool(p.enabled)
        if bundle_code:
            for p in _prefs:
                if p.scope == 'bundle' and p.bundle_code == bundle_code and p.source_id == source_id:
                    return bool(p.enabled)
        for p in _prefs:
            if p.scope == 'global' and p.source_id == source_id:
                return bool(p.enabled)
        return True
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
