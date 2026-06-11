"""혜택 추가 폼 (v6 D2-A) CRUD API — 4 scope 분기 (option/color/bundle/source).

엔드포인트:
  POST   /api/benefits/crud           — 혜택 추가 (scope 에 따라 분기)
  GET    /api/benefits/crud/preview   — 추가 전 영향 옵션 수 미리보기

설계:
  - scope='source' → SourceBenefitTemplate 1건 INSERT (해당 source_id 모든 모음전 default)
  - scope='bundle' → bundle_id 의 모든 option canonical_sku → OptionBenefitOverride N건
  - scope='color'  → bundle_id 의 같은 color option → OptionBenefitOverride N건
  - scope='option' → 단일 canonical_sku → OptionBenefitOverride 1건

기존 api_benefits.py 와 분리 (충돌 0, 단일 책임). url prefix 도 다름.

✅ 기존 코드 안 건드림 — 단일 추가만.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate, OptionBenefitOverride


bp = Blueprint('api_benefits_crud', __name__, url_prefix='/api/benefits/crud')


# ─── 팀공유 모드: admin 전용 (혜택 = 매출 영향) ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


def _ok(**kw):
    return jsonify({'ok': True, **kw})


def _err(msg, status=400):
    return jsonify({'ok': False, 'error': msg}), status


# ─── helper: bundle 의 옵션 list 가져오기 ────────────────────
def _bundle_options(session, bundle_id: int, color_filter: str | None = None) -> list[dict]:
    """bundle_id 의 옵션 (canonical_sku, color) 리스트.

    color_filter 지정 시 같은 컬러만 반환 (scope='color' 케이스).
    """
    # DB 계층: bundle_sets (top) → bundle_products → bundle_options.canonical_sku ↔ options.canonical_sku
    # 'bundle_id' 라 부르는 건 실제 bundle_sets.id (= bundle_set_id)
    from sqlalchemy import text
    sql = """
        SELECT DISTINCT o.canonical_sku, o.color_display
          FROM options o
          JOIN bundle_options bo ON bo.canonical_sku = o.canonical_sku
          JOIN bundle_products bp ON bp.id = bo.bundle_product_id
         WHERE bp.bundle_set_id = :bid
           AND o.canonical_sku IS NOT NULL
    """
    params = {'bid': bundle_id}
    if color_filter:
        sql += " AND o.color_display = :color"
        params['color'] = color_filter
    rows = session.execute(text(sql), params).fetchall()
    return [{'sku': r[0], 'color': r[1]} for r in rows if r[0]]


def _option_color(session, canonical_sku: str) -> str | None:
    """주어진 sku 의 color_display 반환 (scope='color' 시 동일 컬러 lookup 용)."""
    from sqlalchemy import text
    row = session.execute(
        text("SELECT color_display FROM options WHERE canonical_sku = :sku LIMIT 1"),
        {'sku': canonical_sku}
    ).first()
    return row[0] if row else None


def _option_bundle_id(session, canonical_sku: str) -> int | None:
    """주어진 sku 가 속한 bundle_set_id 반환.

    bundle_options.canonical_sku → bundle_products.bundle_set_id 추적.
    """
    from sqlalchemy import text
    row = session.execute(
        text("""
            SELECT bp.bundle_set_id
              FROM bundle_options bo
              JOIN bundle_products bp ON bp.id = bo.bundle_product_id
             WHERE bo.canonical_sku = :sku
             LIMIT 1
        """),
        {'sku': canonical_sku}
    ).first()
    return int(row[0]) if row else None


def _options_by_bundle_code(session, code: str, color_filter: str | None = None) -> list[dict]:
    """모음전 코드(model_code 또는 group_code) → 소속 옵션 (canonical_sku, color).

    실제 옵션↔모음전 매핑은 Option.model_code 기반 (매트릭스 bundles.bundle_edit 와 동일).
    bundle_options 정션 테이블은 미사용/빈 상태라 여기선 쓰지 않는다.
    """
    from lemouton.sourcing.models import Model, Option, BundleGroup
    m = session.query(Model).filter_by(model_code=code).first()
    if m:
        q = session.query(Option).filter_by(model_code=code)
    else:
        grp = session.query(BundleGroup).filter_by(group_code=code).first()
        if not grp or not grp.models:
            return []
        codes = [mm.model_code for mm in grp.models]
        q = session.query(Option).filter(Option.model_code.in_(codes))
    out = []
    for o in q.all():
        if not o.canonical_sku:
            continue
        color = getattr(o, 'color_display', None)
        if color_filter and color != color_filter:
            continue
        out.append({'sku': o.canonical_sku, 'color': color})
    return out


# ─── POST /api/benefits/crud — 혜택 추가 (scope 분기) ────────
@bp.post('')
@bp.post('/')
def add_benefit():
    """혜택 추가 — payload 의 scope 에 따라 분기.

    payload:
      {
        "name": "멤버십 추가 적립",
        "benefit_type": "rate" | "amount",
        "value": 0.05 (rate=소수) | 5000 (amount=원),
        "scope": "option" | "color" | "bundle" | "source",
        "source_id": 3,
        "canonical_sku": "르무통-다크네이비-250" (option/color/bundle 시 필수),
        "bundle_id": 42 (bundle 시 필수, 미명시 시 sku 로부터 lookup)
      }

    응답:
      {ok:true, scope:"...", applied_count:N, ids:[...]}
    """
    data = request.get_json(silent=True) or {}

    # ─── 입력 검증 ──────────────────────────────────────
    name = (data.get('name') or '').strip()
    benefit_type = data.get('benefit_type')
    value = data.get('value')
    scope = data.get('scope')
    source_id = data.get('source_id')

    if not name:
        return _err('name 필수')
    if benefit_type not in ('rate', 'amount'):
        return _err(f"benefit_type 'rate'|'amount' 만 허용 (받음: {benefit_type})")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return _err(f"value 숫자 필수 (받음: {value})")
    if value <= 0:
        return _err('value > 0 필수')
    if scope not in ('option', 'color', 'bundle', 'source', 'select', 'bundle_all_src'):
        return _err(f"scope 미허용 (받음: {scope})")
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return _err(f"source_id 정수 필수 (받음: {source_id})")

    # 표시 카테고리 (정액/정률/결제/캐시백/기타) — 미지정·미허용 시 None(휴리스틱 자동분류)
    _ALLOWED_CATS = ('정액', '정률', '결제', '캐시백', '기타')
    category = (data.get('category') or '').strip() or None
    if category not in _ALLOWED_CATS:
        category = None

    canonical_sku = (data.get('canonical_sku') or '').strip() or None
    bundle_code = (data.get('bundle_code') or '').strip() or None
    # 신규 scope 용 — 선택 옵션 목록(select) / 대상 소싱처 목록(bundle_all_src)
    skus_in = data.get('skus') or []
    if not isinstance(skus_in, list):
        skus_in = []
    skus_in = [str(x).strip() for x in skus_in if str(x).strip()]
    source_ids_in = data.get('source_ids') or []
    if not isinstance(source_ids_in, list):
        source_ids_in = []
    try:
        source_ids_in = [int(x) for x in source_ids_in]
    except (TypeError, ValueError):
        source_ids_in = []
    bundle_id = data.get('bundle_id')
    if bundle_id:
        try:
            bundle_id = int(bundle_id)
        except (TypeError, ValueError):
            bundle_id = None

    # ─── DB 트랜잭션 ────────────────────────────────────
    session = SessionLocal()
    try:
        inserted_ids = []
        applied_skus = []

        if scope == 'source':
            # ★ 1건만 INSERT (전 source 적용)
            tpl = SourceBenefitTemplate(
                source_id=source_id,
                benefit_name=name,
                benefit_type=benefit_type,
                value=value,
                category=category,
                enabled=1,
                sort_order=999,
            )
            session.add(tpl)
            session.flush()
            inserted_ids.append(tpl.id)
            session.commit()
            return _ok(scope='source', applied_count=1, ids=inserted_ids, table='source_benefit_templates')

        # ── option / color / bundle: OptionBenefitOverride N건 ──
        target_skus = []

        if scope == 'option':
            if not canonical_sku:
                return _err('option scope 는 canonical_sku 필수')
            target_skus = [canonical_sku]

        elif scope == 'color':
            if not canonical_sku:
                return _err('color scope 는 canonical_sku 필수 (컬러 lookup 기준)')
            color = _option_color(session, canonical_sku)
            if not color:
                return _err(f'sku "{canonical_sku}" 의 color_text 찾지 못함')
            # ① 모음전 코드 기반 (실제 매핑 = Option.model_code) — 우선
            if bundle_code:
                target_skus = [o['sku'] for o in _options_by_bundle_code(session, bundle_code, color_filter=color)]
            # ② 코드 없거나 0건 → 레거시 bundle_options 정션 경로 (구 데이터 호환)
            if not target_skus:
                if not bundle_id:
                    bundle_id = _option_bundle_id(session, canonical_sku)
                if bundle_id:
                    target_skus = [o['sku'] for o in _bundle_options(session, bundle_id, color_filter=color)]
            if not target_skus:
                return _err(f'color scope 적용 대상 옵션 0건 (color={color}, bundle_code={bundle_code})')

        elif scope == 'select':
            # 옵션 매트릭스 직접 선택 — 프런트가 켠(ON) sku 목록
            if not skus_in:
                return _err('select scope 는 skus[] 필수 (최소 1개)')
            target_skus = skus_in

        elif scope == 'bundle_all_src':
            # 해당 모음전 모든 옵션 × 모든 소싱처 열 → (sku × source_id) 다중.
            # 공통 루프(단일 source_id)를 우회하고 분기 안에서 즉시 처리.
            if not source_ids_in:
                return _err('bundle_all_src scope 는 source_ids[] 필수')
            if not bundle_code:
                return _err('bundle_all_src 대상 옵션 0건 (bundle_code 필수)')
            base = [o['sku'] for o in _options_by_bundle_code(session, bundle_code)]
            if not base:
                return _err('bundle_all_src 대상 옵션 0건 (bundle_code 확인)')
            inserted = 0
            for sid in source_ids_in:
                for sku in base:
                    ov = OptionBenefitOverride(
                        canonical_sku=sku, source_id=sid, template_id=None,
                        benefit_name=name, benefit_type=benefit_type, value=value,
                        category=category, enabled=1, sort_order=999,
                    )
                    session.add(ov)
                    session.flush()
                    inserted_ids.append(ov.id)
                    inserted += 1
            session.commit()
            return _ok(scope='bundle_all_src', applied_count=inserted,
                       ids=inserted_ids[:10], table='option_benefit_overrides')

        elif scope == 'bundle':
            # ① 모음전 코드 기반 (실제 매핑 = Option.model_code) — 우선
            if bundle_code:
                target_skus = [o['sku'] for o in _options_by_bundle_code(session, bundle_code)]
            # ② 코드 없거나 0건 → 레거시 bundle_options 정션 경로 (구 데이터 호환)
            if not target_skus:
                if not bundle_id and canonical_sku:
                    bundle_id = _option_bundle_id(session, canonical_sku)
                if bundle_id:
                    target_skus = [o['sku'] for o in _bundle_options(session, bundle_id)]
            if not target_skus:
                return _err('bundle scope 적용 대상 옵션 0건 (bundle_code 또는 canonical_sku 확인)')

        if not target_skus:
            return _err(f'적용 대상 옵션 0건 (scope={scope})')

        # ── 일괄 INSERT ─────────────────────────────────
        for sku in target_skus:
            ov = OptionBenefitOverride(
                canonical_sku=sku,
                source_id=source_id,
                template_id=None,  # 단독 신규 (template 기반 X)
                benefit_name=name,
                benefit_type=benefit_type,
                value=value,
                category=category,
                enabled=1,
                sort_order=999,
            )
            session.add(ov)
            session.flush()
            inserted_ids.append(ov.id)
            applied_skus.append(sku)

        session.commit()
        return _ok(
            scope=scope,
            applied_count=len(target_skus),
            ids=inserted_ids,
            applied_skus=applied_skus[:10],  # 상위 10개만 응답 (response 크기 제한)
            table='option_benefit_overrides',
        )

    except Exception as e:
        session.rollback()
        import logging
        logging.getLogger(__name__).exception("[api_benefits_crud] 저장 실패")
        return _err(f"DB 저장 실패: {type(e).__name__}: {e}", status=500)
    finally:
        session.close()


# ─── GET /api/benefits/crud/preview — 영향 옵션 수 미리보기 ──
@bp.get('/preview')
def preview_impact():
    """폼 입력 전 영향 옵션 수 미리보기 (sku 옆 카운트).

    query: ?sku=...&bundle_id=...
    응답: {ok:true, counts:{option:1, color:5, bundle:40, source:'다수'}}
    """
    sku = (request.args.get('sku') or '').strip()
    bundle_id = request.args.get('bundle_id')
    if bundle_id:
        try:
            bundle_id = int(bundle_id)
        except (TypeError, ValueError):
            bundle_id = None

    if not sku and not bundle_id:
        return _err('sku 또는 bundle_id 필수')

    session = SessionLocal()
    try:
        # bundle_id 미명시 시 sku 에서 lookup
        if not bundle_id and sku:
            bundle_id = _option_bundle_id(session, sku)
        color = _option_color(session, sku) if sku else None

        bundle_opts = _bundle_options(session, bundle_id) if bundle_id else []
        color_opts = _bundle_options(session, bundle_id, color_filter=color) if (bundle_id and color) else []

        return _ok(counts={
            'option': 1,
            'color': len(color_opts),
            'bundle': len(bundle_opts),
            'source': '다수',
        }, color=color)
    except Exception as e:
        return _err(f"preview 실패: {type(e).__name__}: {e}", status=500)
    finally:
        session.close()
