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
    # source_id 는 보통 정수(DB SourcingSource.id)지만, 카탈로그 소싱처(예: 롯데아이몰)는
    #   문자열 키('key:lotteimall') — 정수 템플릿/오버라이드가 없다. int() 로 터지지 않게
    #   정수 변환 가능한 것만 IN 조회 대상에 넣는다(문자열 키는 어차피 DB 매칭 없음).
    sids = set()
    for it in items:
        sid = it.get('source_id')
        if sid is None:
            continue
        try:
            sids.add(int(sid))
        except (TypeError, ValueError):
            pass
    sids = list(sids)
    link_by = {}
    if skus and sids:
        for l in (session.query(OptionSourceUrl)
                  .filter(OptionSourceUrl.canonical_sku.in_(skus),
                          OptionSourceUrl.source_id.in_(sids)).all()):
            link_by[(l.canonical_sku, l.source_id)] = l
    sp_by_norm = {}
    sp_by_id = {}  # [2026-06-22] source_product_id 직읽기용 (연결분열 우회)
    for sp in (session.query(SourceProduct)
               .filter(SourceProduct.deleted_at.is_(None)).all()):
        sp_by_id[sp.id] = sp
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
    return {'link_by': link_by, 'sp_by_norm': sp_by_norm, 'sp_by_id': sp_by_id,
            'tpl_by_src': tpl_by_src, 'ovr_by': ovr_by, 'prefs': prefs}


def compute_breakdown(session, *, sku: str, source_id: int, sale_price: float,
                       bundle_code: str = None, _cache: dict = None,
                       source_product_id: int = None):
    """_cache: bulk 호출 시 N+1 제거용 사전 로드 인덱스(_build_breakdown_cache).
    None 이면(단일 호출) 기존처럼 매번 쿼리.
    source_product_id: 매트릭스가 아는 옵션-소싱처의 SourceProduct id. 주어지면 동적혜택을
      그 상품에서 '직읽기'(연결분열 우회). OptionSourceUrl·option_source_links 가 비어도
      (예: SSG 단일상품) 정확한 dynamic_benefits 를 읽는다."""
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
    # ★ 2026-07-04 — 무신사 상품쿠폰 선택 결과(영수증 투명성용). 무신사 블록 밖(함수 끝)에서
    #   참조하므로 여기서 top-level 초기화 → NameError 방지. 무신사 외 소싱처는 항상 None 유지.
    _coupon_pick = None
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
                # [perf 2026-06-12] 단일 호출(=FX 셀 클릭)도 전체 source_products 를
                #   fetch+파이썬 normalize 하던 것을 경로 prefix 로 좁힌다. normalize_url 은
                #   '?' 뒤 추적 파라미터만 제거하고 scheme://host/path 는 보존하므로, 물음표
                #   앞 prefix 로 DB에서 거른 소수 후보만 normalize 비교하면 결과 byte-identical.
                #   원격 Supabase 에서 전체 테이블 fetch(수백행×RTT) → 1~수 행으로 축소.
                _base = (link.product_url or '').split('?', 1)[0]
                _q = (session.query(SourceProduct)
                      .filter(SourceProduct.deleted_at.is_(None)))
                if _base:
                    _q = _q.filter(SourceProduct.url.startswith(_base, autoescape=True))
                sp = next((s for s in _q.all() if _nu(s.url) == target_norm), None)
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

    # ★ 2026-06-22 — source_product_id 직읽기 (연결분열 우회, 마지막 폴백).
    #   위 OptionSourceUrl·option_source_links 가 모두 비어 동적혜택을 못 찾은 경우
    #   (예: SSG 단일상품 — 옵션별 option_source_links 미생성), 매트릭스가 아는 정확한
    #   SourceProduct id 로 직접 읽는다(저장은 됐는데 못 읽던 SSG MONEY 사고 수정).
    #   기존 경로가 채운 소싱처(무신사·SSF 등)는 not _dynamic_benefits 가드로 안 탐 → 무회귀.
    #   site 검증으로 오상품(같은 URL 다른 site) 방지.
    if source_product_id and not _dynamic_benefits:
        try:
            from lemouton.sources.models import SourceProduct as _SP
            import json as _json
            _sp = (_cache.get('sp_by_id') or {}).get(int(source_product_id)) if _cache is not None else None
            if _sp is None:
                _sp = session.get(_SP, int(source_product_id))
            if (_sp is not None and getattr(_sp, 'deleted_at', None) is None
                    and (_site_for is None or getattr(_sp, 'site', None) == _site_for)):
                if _sp.dynamic_benefits_json:
                    try:
                        _dynamic_benefits = _json.loads(_sp.dynamic_benefits_json) or {}
                    except (ValueError, TypeError):
                        _dynamic_benefits = {}
                if not _card_issuer and _sp.auto_card_discount_json:
                    try:
                        _card_issuer = (_json.loads(_sp.auto_card_discount_json) or {}).get('issuer')
                        if _card_issuer:
                            _card_enabled = resolve_card_enabled(
                                session, canonical_sku=sku, source_id=source_id,
                                bundle_code=bundle_code,
                                _prefs=(_cache['prefs'] if _cache is not None else None))
                    except (ValueError, TypeError):
                        pass
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
    # ★ 2026-06-11 스냅샷 모델 — 옵션 override(자기 복사본) 우선.
    # ★ 2026-06-22 부분 스냅샷 버그 수정 — 기존엔 'override 1건이라도 있으면 템플릿 전체 무시'
    #   였다. 그래서 매트릭스에서 혜택 1개만 수정(=override 1행 생성)하면 소싱처 템플릿의
    #   나머지 혜택(리뷰적립·현대카드 등)이 통째로 드롭돼 라이브에서 '소싱처별 혜택 누락'이
    #   발생했다(르무통 SKU-HU61O8ZW 실증). → '이름 기준 병합'으로 변경: override 가 같은
    #   이름의 템플릿을 덮고, override 가 안 덮은 템플릿 혜택은 그대로 유지(혜택 묵음 손실 방지).
    #   완전 스냅샷(전 항목 override)·미스냅샷(override 0건)은 동작 동일(byte-identical).
    #   독립성보다 데이터 무결성(혜택 누락=금전손실) 우선 — 사용자 정책.
    effective = []
    _ovr_names = set()
    for ovr in ovr_items:
        effective.append(('ovr_new', ovr))
        _ovr_names.add((ovr.benefit_name or '').strip())
    for tpl in tpl_items:
        if (tpl.benefit_name or '').strip() not in _ovr_names:
            effective.append(('tpl', tpl))

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
    # ★ 2026-06-06 — SSF 기프트포인트는 '항상' 노출 (정률 10%).
    #   크롤에 기프트포인트(gift_point_amount)가 있으면 활성, 없으면 비활성 placeholder.
    #   (사용자 요구: "크롤링 시 있으면 10% 활성화, 없으면 비활성화")
    if _site_for == 'ssf':
        _gp_present = bool((_dynamic_benefits or {}).get('gift_point_amount'))
        effective.append(('dyn', _DynBenefit(
            name='기프트포인트 (멤버십 한정)',
            btype='rate', value=0.10,
            enabled=_gp_present,
        )))
    if _dynamic_benefits:
        # SSF 멤버십포인트 (사이트 노출 적립률 — 변동값)
        _pr = _dynamic_benefits.get('point_rate')
        if _pr and isinstance(_pr, (int, float)) and _pr > 0:
            effective.append(('dyn', _DynBenefit(
                name='멤버십포인트 (사이트 적립)',
                btype='rate', value=float(_pr),
            )))
        # (SSF 기프트포인트는 위 _site_for=='ssf' 블록에서 항상 처리 — 여기서 중복 주입 X)
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
        # ─────────────────────────────────────────────────────────────
        # ★ 2026-06-25 — 현대H몰 (hmall.com) 동적 혜택
        # ─────────────────────────────────────────────────────────────
        #   ⚠️ 혜택은 hmall 클라이언트 렌더 → 확장 navGrab(post-JS DOM)에서만 채워짐.
        #   - H.Point 적립(정액) → accrue(상시, 적립=매입가 차감으로 반영)
        #   - 카드 즉시할인(정액) → 조건부(특정 카드) 기본 비활성, 사용자 토글
        _hp = _dynamic_benefits.get('hmall_point_amount')
        if _hp and isinstance(_hp, (int, float)) and _hp > 0:
            effective.append(('dyn', _DynBenefit(
                name='H.Point 적립', btype='amount', value=float(_hp),
                enabled=True,
            )))
        _hcd = _dynamic_benefits.get('hmall_card_discount')
        if _hcd and isinstance(_hcd, (int, float)) and _hcd > 0:
            _hc_label = _dynamic_benefits.get('hmall_card_label') or '카드'
            effective.append(('dyn', _DynBenefit(
                name=f'{_hc_label} 즉시할인', btype='amount', value=float(_hcd),
                enabled=False,  # 조건부(특정 카드) — 사용자 토글
            )))
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
        # 상품쿠폰 — product_coupon_list 있으면 쿠폰별 키워드 필터+최고 선택, 없으면 기존 단일값(하위호환)
        _pcl = _dynamic_benefits.get('product_coupon_list')
        _coupon_val = float(_dynamic_benefits.get('coupon_amount') or 0)
        # _coupon_pick 은 함수 top-level 에서 이미 None 초기화됨(NameError 방지) — 여기선 값만 대입.
        if _pcl:
            from lemouton.pricing.benefit_gate import pick_best_coupon as _pbc
            from lemouton.sourcing.models_pricing import SourceRegistry as _SR0
            from lemouton.sourcing import crawl_guide as _cg0
            _cg0_key = f'__cg_{source_id}'
            if _cache is not None and _cg0_key in _cache:
                _g0 = _cache[_cg0_key]
            else:
                _sr0 = session.query(_SR0).filter_by(id=source_id).first()
                _g0 = _cg0.loads(_sr0.crawl_guide if _sr0 else None)
                if _cache is not None:
                    _cache[_cg0_key] = _g0
            _cb0 = next((b for b in ((_g0.get('pricing') or {}).get('benefits') or [])
                         if (b.get('name') or '').replace(' ', '') == '상품쿠폰'), {})
            _coupon_pick = _pbc(_pcl, _cb0, _g0.get('exclude_keywords') or [])
            _coupon_val = float(_coupon_pick['amount']) if _coupon_pick else 0.0
        effective.append(('dyn', _Inj('상품쿠폰', _coupon_val, enabled=bool(_coupon_val))))
        effective.append(('dyn', _Inj('등급할인', float(_dynamic_benefits.get('grade_discount_amount') or 0), enabled=bool(_dynamic_benefits.get('grade_discount_amount')))))
        effective.append(('dyn', _Inj('등급적립', float(_dynamic_benefits.get('grade_reward_amount') or 0), enabled=bool(_dynamic_benefits.get('grade_reward_amount')))))
        effective.append(('dyn', _Inj('무신사머니 결제 적립', float(_dynamic_benefits.get('money_reward_amount') or 0), enabled=bool(_dynamic_benefits.get('money_reward_amount')))))

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

    # ★ 2026-06-12 — 롯데온·SSG 현대카드 2.73% 결제할인 (청구할인 fallback / 직전 잔액 기준).
    #   사용자 명세: "롯데 청구할인 미적용 시, 결제 혜택으로 결제 금액 기준 현대카드(2.73%) 적용.
    #   SSG도 마찬가지로 청구할인 없으면 현대카드 2.73% 자동 (단 SSG는 네이버페이 적용 안됨)".
    #   - 결제 택1(legacy pick-best, _is_payment '카드'/'청구할인' 매칭): 청구할인·추가카드 할인·
    #     SSG 카드혜택가 등 다른 '카드' 결제할인이 enabled 면 차감 큰 쪽이 자동 우선 → 현대카드 자동
    #     비활성(택1). 다른 카드 혜택이 없으면(기본값) 현대카드만 남아 적용 = "청구할인 없을 시 현대카드".
    #   - 롯데오너스/SSG MONEY 적립(위 dynamic 블록에서 먼저 append, '적립'은 우선순위상 앞) '뒤'에
    #     차감 = '직전 잔액 기준 2.73%' (사용자 Q3 확정).
    #   - 네이버페이는 롯데온 템플릿(이름에 '네이버' → 택1 제외)만 앞단 동시 적용. SSG는 네이버페이
    #     템플릿·주입이 없어 자동 미적용(사용자 요구 충족).
    if _site_for in ('lotteon', 'ssg'):
        effective.append(('dyn', _DynBenefit(
            name='현대카드 2.73% (청구할인 fallback)',
            btype='rate', value=0.0273,
            enabled=True,
        )))

    # ★ 2026-06-23 — 무신사 조건부 혜택 키워드 게이트 (Task 1b-3).
    #   status='conditional' 가이드 혜택만 대상. always·하드코딩 항목은 절대 불변.
    #   benefit_lines 가 없으면 완전 no-op → 배포 안전.
    if _site_for == 'musinsa':
        _lines = (_dynamic_benefits or {}).get('_benefit_lines') or []
        if _lines:
            import logging as _logging
            _gate_logger = _logging.getLogger(__name__)
            try:
                from lemouton.sourcing.models_pricing import SourceRegistry as _SR
                from lemouton.sourcing import crawl_guide as _cg
                from lemouton.pricing.benefit_gate import gated_off_names as _gated_off

                # ── 가이드 로드 (캐시 우선, 단일 호출 시 매 번 쿼리) ──
                _cg_key = f'__cg_{source_id}'
                if _cache is not None and _cg_key in _cache:
                    _guide_parsed = _cache[_cg_key]
                else:
                    _src_reg = session.query(_SR).filter_by(id=source_id).first()
                    _guide_parsed = _cg.loads(_src_reg.crawl_guide if _src_reg else None)
                    if _cache is not None:
                        _cache[_cg_key] = _guide_parsed

                _guide_benefits = (_guide_parsed.get('pricing') or {}).get('benefits') or []
                _excl_kws = _guide_parsed.get('exclude_keywords') or []

                # ── 게이트 실행 ──
                _off = _gated_off(_guide_benefits, _lines, _excl_kws)

                # ── effective 항목 비활성화 (catalog 이름 매칭) ──
                _gated_names = {(b.get('name') or '') for b in _guide_benefits
                                if (b.get('status') or '') == 'conditional'}
                for _k2, _it2 in effective:
                    _bname = (_it2.benefit_name or '')
                    if _bname in _off:
                        _it2.enabled = False
                # 이름이 effective 에 없는 conditional 혜택 → 조용한 실패 방지 경고
                _eff_names = {(_it2.benefit_name or '') for _k2, _it2 in effective}
                for _cname in _gated_names:
                    if _cname not in _eff_names:
                        _gate_logger.warning(
                            '[benefit-gate] conditional 혜택 "%s" 이(가) effective 목록에 없음 '
                            '(source_id=%s, sku=%s) — 가이드·템플릿 이름 불일치 의심',
                            _cname, source_id, sku,
                        )
            except Exception as _ge:
                import logging as _log2
                _log2.getLogger(__name__).warning(
                    '[benefit-gate] 무신사 키워드 게이트 오류 (non-fatal, 가격 변경 없음): %s', _ge)

    # ★ 카테고리 정렬 + 결제 택1 + 누적 차감 → 순수 계산 함수로 위임 (M1 추출, 2026-06-08)
    from lemouton.pricing.final_price import compute_final_price
    _result = compute_final_price(
        sale_price, effective,
        card_enabled=_card_enabled, card_issuer=_card_issuer,
        base_override=_base_override,
    )
    # ★ 2026-07-04 — 계산식 영수증 투명성: 무신사 상품쿠폰 적용/제외 내역 노출.
    if isinstance(_result, dict) and _coupon_pick:
        _result['coupon_decision'] = {
            'used': _coupon_pick.get('name'),
            'used_amount': _coupon_pick.get('amount'),
            'excluded': [{'name': e.get('name'), 'amount': e.get('amount'), 'reason': e.get('reason')}
                         for e in (_coupon_pick.get('excluded') or [])],
        }
    return _result


@bp.get('/breakdown/<sku>/<int:source_id>')
def get_breakdown(sku: str, source_id: int):
    try:
        sale_price = float(request.args.get('sale_price', 0))
    except ValueError:
        return _err('sale_price 숫자 형식 오류')
    try:
        _spid = int(request.args.get('source_product_id')) if request.args.get('source_product_id') else None
    except (ValueError, TypeError):
        _spid = None
    s = SessionLocal()
    try:
        out = compute_breakdown(s, sku=sku, source_id=source_id, sale_price=sale_price,
                                source_product_id=_spid)
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
            # [2026-06-22] 후보별 키 — 같은 (sku, source_id)에 URL 여러개(단품/모음전 등)면
            #   sale_price 가 달라 final_price 도 다르다. 클라가 보낸 key(예: sku|sid|salePrice)로
            #   결과를 키잉해 덮어쓰기를 막는다(없으면 구방식 sku|sid 하위호환). 완전한 '최종매입가 최저' 선택용.
            key = it.get('key') or f"{sku}|{sid}"
            try:
                out[key] = compute_breakdown(s, sku=sku, source_id=int(sid),
                                             sale_price=sp, _cache=cache,
                                             source_product_id=it.get('source_product_id'))
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


# ════════════════════════════════════════════
#  2026-06-11 — 모음전 한정 값 수정 + 기본값 초기화
#   매트릭스 ✎ 인라인 수정이 소싱처 공통 템플릿을 직접 바꾸던 동작을
#   '이 모음전 전체에만' override 로 적용하도록 분리. ↺ 초기화는 그 override 를
#   깨끗이 삭제해 소싱처 공통값+크롤값(=원래 계산값)으로 복귀.
# ════════════════════════════════════════════
def _bundle_skus(session, bundle_code: str) -> list:
    from webapp.routes.api_benefits_crud import _options_by_bundle_code
    return [o['sku'] for o in _options_by_bundle_code(session, bundle_code)]


def snapshot_bundle_from_templates(session, bundle_code: str, source_ids=None) -> dict:
    """모음전 옵션들에 소싱처 기본셋팅(SourceBenefitTemplate)을 standalone override 로 복제.

    스냅샷 모델의 단일 헬퍼 — 생성 훅 / 초기화(reset) / 따라쓰기(apply-to-all) 공용.
    각 (옵션 sku, source) 의 기존 override 를 삭제 후, 그 source 템플릿을 그대로 복제
    (value/type/enabled/category/apply_mode/pay_method/channel/sort_order, template_id=NULL).
    → 엔진 게이트가 'override 있으면 템플릿 무시' 이므로, 복제 직후 그 옵션은 현재 기본값으로 고정.
    idempotent (재실행 = 삭제 후 재복제). 커밋은 호출자 책임.
    spec: docs/superpowers/specs/2026-06-11-혜택-스냅샷-모델-design.md
    """
    skus = _bundle_skus(session, bundle_code)
    if not skus:
        return {'options': 0, 'sources': 0, 'created': 0}
    q = session.query(SourceBenefitTemplate)
    if source_ids:
        q = q.filter(SourceBenefitTemplate.source_id.in_(list(source_ids)))
    tpls_by_src: dict = {}
    for t in q.all():
        tpls_by_src.setdefault(t.source_id, []).append(t)
    created = 0
    for src_id, tpls in tpls_by_src.items():
        tpls_sorted = sorted(tpls, key=lambda x: ((x.sort_order or 0), x.id))
        for sku in skus:
            (session.query(OptionBenefitOverride)
             .filter_by(canonical_sku=sku, source_id=src_id)
             .delete(synchronize_session=False))
            for i, t in enumerate(tpls_sorted):
                session.add(OptionBenefitOverride(
                    canonical_sku=sku, source_id=src_id, template_id=None,
                    benefit_name=t.benefit_name, benefit_type=t.benefit_type,
                    value=t.value, category=t.category, apply_mode=t.apply_mode,
                    pay_method=t.pay_method, channel=t.channel,
                    enabled=t.enabled, sort_order=i,
                ))
                created += 1
    return {'options': len(skus), 'sources': len(tpls_by_src), 'created': created}


def sync_templates_from_crawl_guide(session, source_id: int, guide: dict) -> int:
    """크롤가이드 혜택 카드(값 입력된 것) → SourceBenefitTemplate upsert (기본셋팅 연결).

    설계(2026-06-13): 크롤가이드 detail 페이지의 혜택 '값' 입력칸을 소싱처 기본셋팅으로
    흘려보낸다. 안전 규칙:
      - 값(value)이 입력된 혜택만 반영. 빈 값(=크롤로 매번 긁는 등급할인 등)은 건드리지 않음
        → 0원/잘못된 고정값 덮어쓰기·이중차감 방지.
      - 방식 '옵션(개월)'(무이자 할부)은 차감 혜택이 아니므로 제외.
      - 이름(benefit_name) 기준 upsert. 크롤가이드에 없는 기존 템플릿은 삭제하지 않음(데이터 보존).
      - rate(정률/적립%)는 사람이 넣은 % 를 소수로 변환(15 → 0.15). amount(정액/고정액)는 그대로.
      - 기존 행 update 시 category/pay_method/channel 은 보존(운영센터에서 세팅한 태그 클로버 방지).
    반환: 반영된 혜택 개수.
    """
    benefits = ((guide.get('pricing') or {}).get('benefits')) or []
    existing = {t.benefit_name: t for t in
                session.query(SourceBenefitTemplate)
                .filter_by(source_id=source_id).all()}
    n = 0
    for i, b in enumerate(benefits):
        v = b.get('value')
        if v is None:
            continue
        method = b.get('method') or ''
        if '개월' in method:
            continue
        name = (b.get('name') or '').strip()
        if not name:
            continue
        is_rate = ('%' in method)
        btype = 'rate' if is_rate else 'amount'
        try:
            val = float(v) / 100.0 if is_rate else float(v)
        except (TypeError, ValueError):
            continue
        apply_mode = b.get('apply')
        enabled = (b.get('status') != 'planned')
        t = existing.get(name)
        if t is not None:
            t.benefit_type = btype
            t.value = val
            if apply_mode:
                t.apply_mode = apply_mode
            t.enabled = enabled
            t.sort_order = i
        else:
            session.add(SourceBenefitTemplate(
                source_id=source_id, benefit_name=name,
                benefit_type=btype, value=val,
                apply_mode=apply_mode, enabled=enabled, sort_order=i,
            ))
        n += 1
    return n


def _upsert_value_for_skus(s, source_id, skus, nm, bt, val):
    """주어진 sku 목록에 (source_id, benefit_name) override 값 upsert.

    소싱처 공통 템플릿(같은 이름)이 있으면 template_id 연결 + 태그 복사
    (set-value-bundle 와 동일 로직을 공유 — DRY).
    """
    tpl = (s.query(SourceBenefitTemplate)
           .filter_by(source_id=source_id, benefit_name=nm).first())
    tpl_id = tpl.id if tpl else None
    # ★ 성능: 기존행을 sku별 N쿼리 대신 IN 1쿼리로, 신규는 벌크 insert.
    existing_rows = (s.query(OptionBenefitOverride)
                     .filter(OptionBenefitOverride.source_id == source_id,
                             OptionBenefitOverride.benefit_name == nm,
                             OptionBenefitOverride.canonical_sku.in_(skus)).all())
    by_sku = {r.canonical_sku: r for r in existing_rows}
    new_objs = []
    affected = 0
    for sku in skus:
        existing = by_sku.get(sku)
        if existing:
            existing.benefit_type = bt
            existing.value = val
            existing.enabled = 1
            if tpl_id and not existing.template_id:
                existing.template_id = tpl_id
            if tpl is not None:
                existing.category = tpl.category
                existing.apply_mode = tpl.apply_mode
                existing.pay_method = tpl.pay_method
                existing.channel = tpl.channel
        else:
            new_objs.append(OptionBenefitOverride(
                canonical_sku=sku, source_id=source_id,
                template_id=tpl_id, benefit_name=nm,
                benefit_type=bt, value=val,
                category=(tpl.category if tpl else None),
                apply_mode=(tpl.apply_mode if tpl else None),
                pay_method=(tpl.pay_method if tpl else None),
                channel=(tpl.channel if tpl else None),
                enabled=1, sort_order=999,
            ))
        affected += 1
    if new_objs:
        s.bulk_save_objects(new_objs)
    return affected


@bp.post('/overrides/set-value-scoped')
def set_value_scoped():
    """scope 인지 값 수정 — option/select/bundle/bundle_all_src/source.

    payload: {source_id, benefit_name, benefit_type, value, scope,
              canonical_sku?, bundle_code?, skus?[], source_ids?[]}
    - source scope: SourceBenefitTemplate.value 직접 수정 (소싱처 전 모음전 반영).
    - 그 외: 대상 옵션들에 override upsert (_upsert_value_for_skus).
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    bt = data.get('benefit_type', 'rate')
    if bt not in ('rate', 'amount'):
        return _err('benefit_type 은 rate 또는 amount')
    try:
        val = float(data.get('value'))
    except (TypeError, ValueError):
        return _err('value 숫자 필수')
    if val < 0:
        return _err('value >= 0 필수')
    scope = data.get('scope', 'bundle')
    bundle_code = (data.get('bundle_code') or '').strip() or None
    canonical_sku = (data.get('canonical_sku') or '').strip() or None
    skus_in = data.get('skus') or []
    skus_in = [str(x).strip() for x in skus_in if str(x).strip()] if isinstance(skus_in, list) else []
    source_ids_in = data.get('source_ids') or []
    try:
        source_ids_in = [int(x) for x in source_ids_in] if isinstance(source_ids_in, list) else []
    except (TypeError, ValueError):
        source_ids_in = []

    s = SessionLocal()
    try:
        from webapp.routes.api_benefits_crud import _options_by_bundle_code
        if scope == 'source':
            tpl = (s.query(SourceBenefitTemplate)
                   .filter_by(source_id=source_id, benefit_name=nm).first())
            if not tpl:
                return _err('source scope: 해당 소싱처 공통 템플릿 없음')
            tpl.benefit_type = bt
            tpl.value = val
            s.commit()
            return _ok(scope='source', affected='template')

        if scope == 'option':
            skus = [canonical_sku] if canonical_sku else []
        elif scope == 'select':
            skus = skus_in
        elif scope in ('bundle', 'bundle_all_src'):
            if not bundle_code:
                return _err('bundle 계열 scope 는 bundle_code 필수')
            skus = [o['sku'] for o in _options_by_bundle_code(s, bundle_code, active_only=True)]
        else:
            return _err('scope 미허용')
        if not skus:
            return _err(f'대상 옵션 0건 (scope={scope})')

        if scope == 'bundle_all_src':
            if not source_ids_in:
                return _err('bundle_all_src 는 source_ids[] 필수')
            total = sum(_upsert_value_for_skus(s, sid, skus, nm, bt, val) for sid in source_ids_in)
        else:
            total = _upsert_value_for_skus(s, source_id, skus, nm, bt, val)
        s.commit()
        return _ok(scope=scope, affected=total)
    finally:
        s.close()


@bp.post('/overrides/set-value-bundle')
def set_value_bundle():
    """모음전(bundle_code) 전 옵션에 혜택 값을 적용 — 소싱처 공통 템플릿은 보존.

    payload: {source_id, bundle_code, benefit_name, benefit_type, value}
    동작:
      - bundle_code 의 모든 옵션에 (source_id, sku, benefit_name) override 를 upsert.
      - 같은 이름의 소싱처 템플릿이 있으면 template_id 로 연결 + 태그(category/apply_mode/
        pay_method/channel) 복사 → 엔진이 템플릿을 이 override 로 대체(결제경로 계산 보존).
      - 매트릭스 ✎ 인라인 수정의 새 저장 경로('이 모음전만' 반영).
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    bt = data.get('benefit_type', 'rate')
    if bt not in ('rate', 'amount'):
        return _err('benefit_type 은 rate 또는 amount')
    try:
        val = float(data.get('value'))
    except (TypeError, ValueError):
        return _err('value 숫자 필수')
    if val < 0:
        return _err('value >= 0 필수')
    bundle_code = (data.get('bundle_code') or '').strip() or None
    if not bundle_code:
        return _err('bundle_code 필수')

    s = SessionLocal()
    try:
        target_skus = _bundle_skus(s, bundle_code)
        if not target_skus:
            return _err('대상 옵션 0건 (bundle_code 확인)')
        # ★ 스냅샷 모델 — 이 (모음전, 소싱처)가 아직 스냅샷 안 됐으면(override 0건) 먼저
        #   현재 기본값 전체를 복사(고정)한 뒤 이 수정을 얹는다. = '첫 수정 시 고정'.
        already = (s.query(OptionBenefitOverride)
                   .filter(OptionBenefitOverride.source_id == source_id,
                           OptionBenefitOverride.canonical_sku.in_(target_skus))
                   .first())
        snapped = 0
        if not already:
            snapped = snapshot_bundle_from_templates(
                s, bundle_code, source_ids=[source_id]).get('created', 0)
            s.flush()
        affected = _upsert_value_for_skus(s, source_id, target_skus, nm, bt, val)
        s.commit()
        return _ok(affected=affected, scope='bundle', snapshotted=snapped)
    finally:
        s.close()


@bp.post('/overrides/reset-bundle')
def reset_bundle():
    """모음전(bundle_code) 초기화 — 이 모음전을 '현재 소싱처 기본값'으로 다시 복사(A3-1).

    payload: {source_id, bundle_code}   (benefit_name 은 무시 — 소싱처 단위 전체 초기화)
    스냅샷 모델: 그 (bundle, source) 의 기존 override 를 지우고 현재 SourceBenefitTemplate 을
    standalone override 로 재복제 → 소싱처 기본값이 바뀌었어도 '현재 기본값'으로 통일.
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    bundle_code = (data.get('bundle_code') or '').strip() or None
    if not bundle_code:
        return _err('bundle_code 필수')
    s = SessionLocal()
    try:
        if not _bundle_skus(s, bundle_code):
            return _err('대상 옵션 0건 (bundle_code 확인)')
        r = snapshot_bundle_from_templates(s, bundle_code, source_ids=[source_id])
        s.commit()
        return _ok(scope='bundle', **r)
    finally:
        s.close()


@bp.get('/diff/<bundle_code>/<int:source_id>')
def bundle_diff(bundle_code: str, source_id: int):
    """이 모음전(bundle_code)이 현재 소싱처 기본값(SourceBenefitTemplate)과 다른지 판정 (A3-1 배너).

    모음전 옵션의 override 값(스냅샷) ↔ 현재 템플릿 값을 이름으로 비교.
    returns {differs: bool, count: int, items: [{name, current, default, type}]}
    옵션마다 값이 같다고 가정(✎ 수정이 모음전 전체 적용) → 첫 옵션 기준 비교.
    """
    s = SessionLocal()
    try:
        skus = _bundle_skus(s, bundle_code)
        if not skus:
            return _ok(differs=False, count=0, items=[])
        tpls = {t.benefit_name: t for t in (s.query(SourceBenefitTemplate)
                .filter_by(source_id=source_id).all())}
        ovrs = {o.benefit_name: o for o in (s.query(OptionBenefitOverride)
                .filter_by(canonical_sku=skus[0], source_id=source_id).all())}
        items = []
        for nm, t in tpls.items():
            o = ovrs.get(nm)
            cur = float(o.value) if o is not None else float(t.value)
            dft = float(t.value)
            if abs(cur - dft) > 1e-9 or (o is not None and bool(o.enabled) != bool(t.enabled)):
                items.append({'name': nm, 'current': cur, 'default': dft,
                              'type': t.benefit_type})
        return _ok(differs=bool(items), count=len(items), items=items)
    finally:
        s.close()


@bp.post('/templates/<int:source_id>/apply-to-all')
def apply_to_all_bundles(source_id: int):
    """소싱처 기본값을 '모든 모음전'에 따라쓰기 (B1, 2중 잠금) — 전 모음전 덮어쓰기.

    payload: {confirm: true}  (UI 2중 잠금 통과 표시)
    전 모음전 옵션의 (이 source) override 를 현재 템플릿으로 재복제. 비가역.
    """
    data = request.get_json(silent=True) or {}
    if not data.get('confirm'):
        return _err('confirm=true 필수 (2중 잠금)')
    s = SessionLocal()
    try:
        from lemouton.sourcing.models import Model
        codes = [c[0] for c in s.query(Model.model_code).all() if c[0]]
        bundles = 0
        created = 0
        for code in codes:
            r = snapshot_bundle_from_templates(s, code, source_ids=[source_id])
            if r['options']:
                bundles += 1
                created += r['created']
        s.commit()
        return _ok(scope='all', bundles=bundles, created=created)
    finally:
        s.close()


@bp.post('/delete-scoped')
def delete_scoped():
    """혜택을 범위(scope)별로 삭제 — 해당 옵션 / 이 모음전 전체 / 소싱처 전체.

    payload: {
      source_id: int,
      benefit_name: str,            # 매칭 기준 (필수)
      scope: 'option'|'bundle'|'source',
      canonical_sku?: str,          # option scope
      bundle_code?: str,            # bundle scope (model_code/group_code)
      template_id?: int,            # source scope 에서 템플릿도 삭제
    }
    동작:
      - 매칭되는 OptionBenefitOverride 행 삭제 (scope 에 해당하는 옵션들).
      - source scope: 같은 이름 SourceBenefitTemplate 도 삭제.
      - option/bundle scope 인데 소싱처 공통 템플릿이 존재하면, 대상 옵션에
        '비활성(enabled=0) override' 를 만들어 그 범위에서만 안 보이게 처리
        (템플릿은 소싱처 전체 공유라 행 자체는 못 지움 — 토글 OFF 와 동일 패턴).
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    scope = data.get('scope')
    if scope not in ('option', 'bundle', 'source', 'select', 'bundle_all_src'):
        return _err("scope 는 option|bundle|source|select|bundle_all_src")
    canonical_sku = (data.get('canonical_sku') or '').strip() or None
    bundle_code = (data.get('bundle_code') or '').strip() or None
    template_id = data.get('template_id')
    skus_in = data.get('skus') or []
    skus_in = [str(x).strip() for x in skus_in if str(x).strip()] if isinstance(skus_in, list) else []
    source_ids_in = data.get('source_ids') or []
    try:
        source_ids_in = [int(x) for x in source_ids_in] if isinstance(source_ids_in, list) else []
    except (TypeError, ValueError):
        source_ids_in = []

    s = SessionLocal()
    try:
        # ── bundle_all_src: 단일 source_id 가정을 벗어나므로 별도 처리 후 early-return ──
        if scope == 'bundle_all_src':
            from webapp.routes.api_benefits_crud import _options_by_bundle_code
            if not source_ids_in or not bundle_code:
                return _err('bundle_all_src 는 source_ids[]·bundle_code 필수')
            base = [o['sku'] for o in _options_by_bundle_code(s, bundle_code)]
            if not base:
                return _err('bundle_all_src 대상 옵션 0건 (bundle_code 확인)')
            # ★ 성능: 행마다 delete 금지 — source 별 벌크 DELETE 1회
            total_del = 0
            for sid in source_ids_in:
                total_del += (s.query(OptionBenefitOverride)
                              .filter(OptionBenefitOverride.source_id == sid,
                                      OptionBenefitOverride.benefit_name == nm,
                                      OptionBenefitOverride.canonical_sku.in_(base))
                              .delete(synchronize_session=False))
            s.commit()
            return _ok(scope='bundle_all_src', deleted_overrides=total_del,
                       affected=len(base) * len(source_ids_in))
        # ── 대상 옵션 sku 결정 ──
        target_skus = None  # None = 전체(source scope)
        if scope == 'option':
            if not canonical_sku:
                return _err('option scope 는 canonical_sku 필수')
            target_skus = [canonical_sku]
        elif scope == 'select':
            if not skus_in:
                return _err('select scope 는 skus[] 필수')
            target_skus = skus_in
        elif scope == 'bundle':
            from webapp.routes.api_benefits_crud import _options_by_bundle_code
            if not bundle_code:
                return _err('bundle scope 는 bundle_code 필수')
            target_skus = [o['sku'] for o in _options_by_bundle_code(s, bundle_code)]
            if not target_skus:
                return _err('bundle scope 대상 옵션 0건 (bundle_code 확인)')

        # ── ① 매칭 override 삭제 ──
        q = s.query(OptionBenefitOverride).filter_by(source_id=source_id, benefit_name=nm)
        if target_skus is not None:
            q = q.filter(OptionBenefitOverride.canonical_sku.in_(target_skus))
        rows = q.all()
        deleted_ovr = len(rows)
        for r in rows:
            s.delete(r)
        s.flush()  # 삭제 반영 (③ 의 중복 체크 정확성)

        # ── ② 소싱처 전체: 템플릿도 삭제 ──
        deleted_tpl = 0
        if scope == 'source':
            tpls = (s.query(SourceBenefitTemplate)
                    .filter_by(source_id=source_id, benefit_name=nm).all())
            if not tpls and template_id:
                tpl = s.get(SourceBenefitTemplate, template_id)
                if tpl:
                    tpls = [tpl]
            for t in tpls:
                s.delete(t)
                deleted_tpl += 1

        # ── ③ option/bundle scope + 소싱처 공통 템플릿 존재 → 비활성 override 로 숨김 ──
        disabled = 0
        if scope in ('option', 'bundle', 'select'):
            tpl = (s.query(SourceBenefitTemplate)
                   .filter_by(source_id=source_id, benefit_name=nm).first())
            if tpl:
                for sku in target_skus:
                    has = (s.query(OptionBenefitOverride)
                           .filter_by(source_id=source_id, canonical_sku=sku, benefit_name=nm)
                           .first())
                    if not has:
                        s.add(OptionBenefitOverride(
                            canonical_sku=sku, source_id=source_id,
                            template_id=tpl.id, benefit_name=nm,
                            benefit_type=tpl.benefit_type, value=tpl.value,
                            enabled=0, sort_order=999,
                        ))
                        disabled += 1

        s.commit()
        return _ok(
            scope=scope,
            deleted_overrides=deleted_ovr,
            deleted_templates=deleted_tpl,
            hidden_via_disabled=disabled,
            affected=(len(target_skus) if target_skus is not None else 'all'),
        )
    finally:
        s.close()
