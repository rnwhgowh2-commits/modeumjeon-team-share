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


def sync_templates_from_crawl_guide(session, source_id: int, guide: dict,
                                    create_new: bool = False) -> dict:
    """크롤가이드 혜택 '값' 입력칸 → 소싱처 기본셋팅(SourceBenefitTemplate) 반영 (2026-06-13).

    라이브는 '템플릿 직결' 모드(스냅샷 override 0건)라 이 템플릿이 매입가를 직접 굴린다.
    안전 규칙(언더프라이싱·이중차감 방지):
      - 값(value)이 입력된 혜택만 반영. 빈 값(=크롤 동적)·방식 '옵션(개월)'(무이자할부)은 제외.
      - **update-only 기본**(create_new=False): 이름이 기존 템플릿과 매칭될 때만 값 갱신.
        매칭 안 되면 건너뜀(skipped) → 크롤가이드에 새 이름 넣어도 차감행이 새로 안 생김.
      - rate(정률/적립%)는 % → 소수 변환(15 → 0.15). amount(정액/고정액)는 그대로.
      - 기존 행 update 시 category/pay_method/channel(운영센터 태그)은 보존.
    반환: {'updated': n, 'created': n, 'skipped': [이름...]}.
    """
    benefits = ((guide.get('pricing') or {}).get('benefits')) or []
    existing = {t.benefit_name: t for t in
                session.query(SourceBenefitTemplate)
                .filter_by(source_id=source_id).all()}
    updated, created, skipped = 0, 0, []
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
            updated += 1
        elif create_new:
            session.add(SourceBenefitTemplate(
                source_id=source_id, benefit_name=name,
                benefit_type=btype, value=val,
                apply_mode=apply_mode, enabled=enabled, sort_order=i,
            ))
            created += 1
        else:
            skipped.append(name)
    return {'updated': updated, 'created': created, 'skipped': skipped}


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
    # [perf 2026-06-12] 동적혜택 fallback(option_source_links 경유)을 1회 배치로 묶음.
    #   compute_breakdown 이 캐시가 있어도 item 당 raw SQL 1쿼리 하던 누수(legacy
    #   option_source_urls 빈 번들은 거의 모든 item 이 이 경로 → 300건=300쿼리≈12.5s)를 제거.
    #   동일 JOIN·필터를 sku 전체로 한 번에 → (sku, site) 별 dynamic_benefits_json 리스트.
    dyn_by_sku_site = defaultdict(list)
    if skus:
        from sqlalchemy import text as _sqltext, bindparam as _bindparam
        _dq = _sqltext(
            "SELECT l.canonical_sku, sp.site, sp.dynamic_benefits_json "
            "FROM option_source_links l "
            "JOIN source_options so ON l.source_option_id = so.id "
            "JOIN source_products sp ON so.source_product_id = sp.id "
            "WHERE l.canonical_sku IN :skus "
            "AND so.deleted_at IS NULL AND sp.deleted_at IS NULL "
            "AND sp.dynamic_benefits_json IS NOT NULL"
        ).bindparams(_bindparam('skus', expanding=True))
        for _sku_v, _site_v, _dj in session.execute(_dq, {'skus': skus}).fetchall():
            dyn_by_sku_site[(_sku_v, _site_v)].append(_dj)
    return {'link_by': link_by, 'sp_by_norm': sp_by_norm,
            'tpl_by_src': tpl_by_src, 'ovr_by': ovr_by, 'prefs': prefs,
            'dyn_by_sku_site': dyn_by_sku_site}


def _musinsa_effective_from_crawl(guide_benefits, exclude_keywords, snap):
    """무신사: 이번 크롤 스냅샷(snap)으로 effective 혜택 리스트를 만든다.

    - snap 없음/None → None (미수집 신호; 호출부가 산출불가 처리).
    - gate_benefits(가이드 키워드, snap.lines, excludes)로 on/off 판정.
    - 금액 = 그 혜택에 매칭된 라인(matched_lines)에서 추출한 최대 원-금액(라인이 라벨+금액
      을 함께 보유). 별도 amounts 딕트·키 계약 불필요(라인에서 직접 추출). 폴백 금지.
    - base=표면가 모델: 전부 정액(원) 차감으로 환산(적립=현금성 차감). 표면가 base_override는 호출부가 설정.
    """
    if not isinstance(snap, dict):
        return None
    import re as _re
    from lemouton.pricing.benefit_gate import gate_benefits
    lines = snap.get('lines') or []
    gated = gate_benefits(guide_benefits or [], lines, exclude_keywords or [])
    by_name = {g['name']: g for g in gated}

    def _amt_after_triggers(matched, triggers):
        """혜택 금액 = '트리거 키워드 뒤'의 첫 원-금액(라인별), 라인 간 최대(택1 선택값 대응).

        라인-전체 최대(_max_won)는 결합행에서 오추출한다: 예) '기본 적립등급 적립 3,420원
        후기 적립 2,500원' 한 줄에서 후기적립=후기 적립'뒤'의 2,500 이어야 하는데 전체최대면
        3,420(등급적립)을 잘못 집음. → 트리거 뒤 금액만 본다. '보유'(잔액) 라인은 제외.
        triggers 가 비면(하위호환) 라인 전체 최대.
        """
        trgs = [t for t in (triggers or []) if t]
        best = 0
        for ln in (matched or []):
            if not ln or '보유' in ln:
                continue
            if not trgs:
                for m in _re.findall(r'([\d,]{2,})\s*원', ln):
                    try:
                        v = int(m.replace(',', ''))
                    except ValueError:
                        continue
                    if v > best:
                        best = v
                continue
            for trg in trgs:
                start = 0
                while True:
                    idx = ln.find(trg, start)
                    if idx < 0:
                        break
                    m = _re.search(r'([\d,]{2,})\s*원', ln[idx + len(trg):])
                    if m:
                        try:
                            v = int(m.group(1).replace(',', ''))
                            if v > best:
                                best = v
                        except ValueError:
                            pass
                    start = idx + len(trg)
        return best

    class _Inj:
        def __init__(self, name, btype, value, enabled):
            self.id = -1; self.benefit_name = name; self.benefit_type = btype
            self.value = value; self.enabled = enabled
            self.sort_order = 999; self.template_id = None

    eff = []
    payment_found = False   # 무신사머니 결제적립이 실제로 잡혔는가(현대카드 fallback 판정)
    for b in (guide_benefits or []):
        nm = b.get('name')
        g = by_name.get(nm) or {}
        applied = bool(g.get('applied'))
        # 가이드에 고정값(value)이 있으면 그 값 사용(예: 후기적립 500원 — 사진후기 2,500은 제외).
        #   없으면(value=None) 현재 크롤 라인에서 트리거 뒤 금액 추출.
        fixed = b.get('value')
        if fixed is not None:
            val = float(fixed) if applied else 0.0
        else:
            val = float(_amt_after_triggers(g.get('matched_lines'), b.get('triggers'))) if applied else 0.0
        en = applied and val > 0
        if nm == '결제 적립' and en:
            payment_found = True
        eff.append(('crawl', _Inj(nm, 'amount', val, enabled=en)))
    # ★ 결제수단 적립 fallback (사용자 정의 2026-06-14): 무신사머니 결제적립이 없으면 현대카드 2.73%
    #   를 직전잔액(다른 혜택 차감 후 = 최종매입가 직전)에 적용. rate 라 정액 차감 뒤(마지막) 처리됨.
    #   무신사머니 적립이 있으면 택1로 현대카드 미적용(중복 방지).
    if not payment_found:
        eff.append(('crawl', _Inj('현대카드 2.73% (결제 fallback)', 'rate', 0.0273, enabled=True)))
    return eff


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
            import json as _json
            # [perf 2026-06-12] 캐시가 있으면 배치 프리로드(dyn_by_sku_site)에서 읽어
            #   item 당 raw SQL 1쿼리 제거. 없으면(단일 호출) 기존처럼 즉시 조회.
            if _cache is not None:
                _rows2 = [(_dj,) for _dj
                          in _cache.get('dyn_by_sku_site', {}).get((sku, _site_for), [])]
            else:
                from sqlalchemy import text as _sqltext
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
                # 무신사: 한 SKU가 여러 무신사 SP에 매핑될 수 있다. ① 이번 브라우저 크롤
                #   스냅샷(_crawl, benefits_ok)을 가진 SP 최우선(현재가 기준 — 신모델). ② 동률이면
                #   기존 휴리스틱(표면가 있고 등급적립 최대=모음전 회원가). 그 외 사이트: 첫 non-empty.
                if _site_for == 'musinsa':
                    _cand_crawl = bool((_d2.get('_crawl') or {}).get('benefits_ok'))
                    _best_crawl = bool((_best2.get('_crawl') or {}).get('benefits_ok')) if _best2 else False
                    _take = False
                    if _best2 is None:
                        _take = bool(_d2.get('surface_price') or _cand_crawl)
                    elif _cand_crawl and not _best_crawl:
                        _take = True
                    elif _cand_crawl == _best_crawl and _d2.get('surface_price') and (_d2.get('grade_reward_amount') or 0) > (_best2.get('grade_reward_amount') or 0):
                        _take = True
                    if _take:
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
    # ★ 2026-06-14 — 무신사: 현재 브라우저 크롤 스냅샷(_crawl)만으로 계산.
    #   신선도 게이트 통과 못 하면 산출불가(미수집). 옛 dynamic·템플릿 폴백 금지.
    _base_override = None
    _benefits_status = 'ok'
    if str(source_id) == '3':
        from lemouton.pricing.unified import benefits_fresh
        from lemouton.sourcing.models_pricing import SourceRegistry as _SR
        from lemouton.sourcing import crawl_guide as _cg
        _snap = (_dynamic_benefits or {}).get('_crawl')
        try:
            _last_status = getattr(sp, 'last_status', None)
        except NameError:
            _last_status = None
        if not benefits_fresh(_snap, _last_status):
            _benefits_status = '미수집'
        else:
            _src = session.query(_SR).get(3)
            _guide = _cg.loads(_src.crawl_guide) if _src else {}
            _gb = (_guide.get('pricing') or {}).get('benefits') or []
            _ex = _guide.get('exclude_keywords') or []
            _crawl_eff = _musinsa_effective_from_crawl(_gb, _ex, _snap)
            if _crawl_eff is None:
                _benefits_status = '미수집'
            else:
                effective = _crawl_eff  # 템플릿/오버라이드 무시 — 크롤만 (폴백 금지)
                _base_override = float((_dynamic_benefits or {}).get('surface_price') or sale_price)

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

    # ★ 카테고리 정렬 + 결제 택1 + 누적 차감 → 순수 계산 함수로 위임 (M1 추출, 2026-06-08)
    from lemouton.pricing.final_price import compute_final_price
    if _benefits_status == '미수집':
        return {
            'final_price': None, 'steps': [], 'items_used': [],
            'benefits_status': '미수집',
            'note': '현재 브라우저 크롤 혜택 없음 — 재크롤 필요(폴백 금지)',
        }
    out = compute_final_price(
        sale_price, effective,
        card_enabled=_card_enabled, card_issuer=_card_issuer,
        base_override=_base_override,
    )
    out['benefits_status'] = 'ok'
    return out


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


# ════════════════════════════════════════════
#  2026-06-11 — 모음전 한정 값 수정 + 기본값 초기화
#   매트릭스 ✎ 인라인 수정이 소싱처 공통 템플릿을 직접 바꾸던 동작을
#   '이 모음전 전체에만' override 로 적용하도록 분리. ↺ 초기화는 그 override 를
#   깨끗이 삭제해 소싱처 공통값+크롤값(=원래 계산값)으로 복귀.
# ════════════════════════════════════════════
def _bundle_skus(session, bundle_code: str) -> list:
    from webapp.routes.api_benefits_crud import _options_by_bundle_code
    return [o['sku'] for o in _options_by_bundle_code(session, bundle_code)]


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
        affected = _upsert_value_for_skus(s, source_id, target_skus, nm, bt, val)
        s.commit()
        return _ok(affected=affected, scope='bundle')
    finally:
        s.close()


@bp.post('/overrides/reset-bundle')
def reset_bundle():
    """모음전(bundle_code) 단위 혜택 초기화 — 이 모음전 옵션들의 해당 override 전부 삭제.

    payload: {source_id, bundle_code, benefit_name}
    동작:
      - delete-scoped 와 달리 '비활성 스텁'을 만들지 않는다.
        대상 옵션들의 (source_id, benefit_name) override 행을 단순 삭제 →
        엔진이 소싱처 공통 템플릿 + 크롤 동적값으로 재계산 = '원래 계산값' 복귀.
    """
    data = request.get_json(silent=True) or {}
    try:
        source_id = int(data.get('source_id'))
    except (TypeError, ValueError):
        return _err('source_id 정수 필수')
    nm = (data.get('benefit_name') or '').strip()
    if not nm:
        return _err('benefit_name 필수')
    bundle_code = (data.get('bundle_code') or '').strip() or None
    if not bundle_code:
        return _err('bundle_code 필수')
    s = SessionLocal()
    try:
        target_skus = _bundle_skus(s, bundle_code)
        if not target_skus:
            return _err('대상 옵션 0건 (bundle_code 확인)')
        rows = (s.query(OptionBenefitOverride)
                .filter(OptionBenefitOverride.source_id == source_id,
                        OptionBenefitOverride.benefit_name == nm,
                        OptionBenefitOverride.canonical_sku.in_(target_skus))
                .all())
        deleted = len(rows)
        for r in rows:
            s.delete(r)
        s.commit()
        return _ok(deleted=deleted, scope='bundle')
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
