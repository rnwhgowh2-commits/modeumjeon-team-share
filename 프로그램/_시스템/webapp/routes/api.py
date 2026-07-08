"""[E] T10 — AJAX/JSON 엔드포인트.

UI에서 호출되는 모든 변경/조회 엔드포인트. 자동 등록(SS·쿠팡)은 T14/T15에서 wiring.
"""
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, DiscoveryQueueItem
from lemouton.templates.models import (
    PriceTemplate, ColorTemplate, SizeTemplate, PriceTrackHistory,
)
from lemouton.uploader.models import MarketRegistration

bp = Blueprint('api', __name__, url_prefix='/api')


def _ok(**kw):
    return jsonify({'ok': True, **kw})


def _err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


# ---------- Crawl queue (읽기 전용) ----------

@bp.route('/crawl/queue')
def crawl_queue():
    """[읽기전용] 로컬 크롤러(확장)가 폴링하는 '지금 긁을 URL' 목록 + 실행/정지.

    서버는 목록만 알려줄 뿐 소싱처에 접속하지 않는다(크롤=로컬 원칙).
    """
    from datetime import datetime, timezone
    from lemouton.sources.crawl_schedule import due_crawl_payload
    s = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC
        return jsonify(due_crawl_payload(s, now=now))
    finally:
        s.close()


@bp.route('/crawl/due-bundles')
def crawl_due_bundles():
    """[읽기전용] 로컬 크롤러가 폴링 → 지금 크롤할 모음전 코드 목록.

    서버는 목록만 알려줄 뿐 크롤하지 않는다(크롤=로컬 원칙). 확장이 이 코드를
    기존 `mgrEnqueue({codes})` 큐로 넘겨 검증된 크롤 흐름을 재사용한다.
    """
    from datetime import datetime, timezone
    from lemouton.sources.crawl_schedule import due_bundle_codes
    from lemouton.pricing.settings import get_or_init
    s = SessionLocal()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        enabled = bool(get_or_init(s).crawl_auto_enabled)
        codes = due_bundle_codes(s, now=now)
        return jsonify({"enabled": enabled, "count": len(codes), "codes": codes})
    finally:
        s.close()


@bp.post('/crawl/pass-done')
def crawl_pass_done():
    """확장이 '한 크롤 패스(전체 URL 1회) 완료'를 통보 → 오늘 바퀴 +1 기록 + 카운터 리셋.

    한 바퀴 완료 판정의 authoritative 신호. 서버가 완료를 추측(over-serve 등)하면 가짜 바퀴가
    생기므로, 실제 크롤을 끝낸 쪽(확장 runQueueBG 소진 / 페이지 crawl_log 100%)이 보낸다.
    다탭·재렌더로 여러 번 와도 최근 20초 내 완료가 있으면 무시(디듀프).

    [2026-07-08] 동시 pass-done 원자적 직렬화. 확장(runQueueBG)과 페이지(crawl_log)가 한 바퀴
    완료 순간에 ~100ms 안에 둘 다 쏘면, 아래 '조회 후 삽입'이 비원자적이라 둘 다 "최근 없음"을
    통과해 회차가 2개 박혔다(라이브 확인: 0.0~0.14초 간격 중복쌍 #81/#82·#83/#84 등).
    운영은 gunicorn 3워커(멀티프로세스)라 파이썬 락은 무효 → DB advisory 락으로 프로세스를
    넘어 직렬화한다. 두 번째 요청은 첫 번째가 커밋한 회차를 보고 디듀프 → 회차 정확히 1개.
    SQLite(개발/테스트)는 쓰기가 직렬화돼 이 경합이 없으므로 락을 건너뛴다.
    """
    from lemouton.sources.crawl_schedule import start_new_lap
    from lemouton.sources.models import CrawlLapRun
    from datetime import datetime, timedelta
    from sqlalchemy import text
    s = SessionLocal()
    try:
        now = datetime.utcnow()
        try:
            if s.bind is not None and s.bind.dialect.name == "postgresql":
                s.execute(text("SELECT pg_advisory_xact_lock(4823017)"))
        except Exception:
            pass   # 락 실패해도 기존 20초 디듀프로 동작(최악의 경우만 경합 잔존)
        recent = (s.query(CrawlLapRun)
                  .filter(CrawlLapRun.completed_at >= now - timedelta(seconds=20))
                  .first())
        if recent is not None:
            s.rollback()   # advisory xact 락 해제(삽입 안 함)
            return jsonify({"ok": True, "deduped": True})
        n = start_new_lap(s, now=now)   # record=True → CrawlLapRun 기록 + crawl_lap_count 리셋
        s.commit()   # 삽입 영속 + advisory 락 해제
        return jsonify({"ok": True, "reset": n})
    finally:
        s.close()


@bp.post('/sources/crawl-weight')
def set_source_crawl_weight():
    """URL 계수(1~5) 저장. body: {source_product_id, weight}."""
    from lemouton.sources.crawl_schedule import set_crawl_weight
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        w = set_crawl_weight(s, int(data.get('source_product_id')), data.get('weight'))
        s.commit()
        return jsonify({"ok": True, "weight": w})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    finally:
        s.close()


@bp.get('/crawl/weight-rules')
def crawl_weight_rules():
    """[읽기] 범위별 계수 규칙(화면 트리)."""
    from lemouton.sources.crawl_schedule import list_weight_rules
    s = SessionLocal()
    try:
        return jsonify(list_weight_rules(s))
    finally:
        s.close()


@bp.get('/crawl/weight-tree')
def crawl_weight_tree():
    """[읽기] 계수 드릴다운 트리(소싱처/브랜드/모음전 3기준). 노드별 weight·direct 정본."""
    from lemouton.sources.crawl_weight_tree import build_weight_tree
    s = SessionLocal()
    try:
        return jsonify(build_weight_tree(s))
    finally:
        s.close()


@bp.post('/crawl/weight-rule')
def set_crawl_weight_rule_route():
    """계수 규칙 설정/해제. body {scope_type, scope_key, weight?(없으면 해제)}."""
    from lemouton.sources.crawl_schedule import set_crawl_weight_rule
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        w = set_crawl_weight_rule(s, data.get('scope_type'), data.get('scope_key'),
                                  data.get('weight'))
        s.commit()
        return jsonify({"ok": True, "weight": w})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        s.close()


@bp.get('/upload/account-speed')
def list_account_upload_speed():
    """[읽기] 계정별 업로드 속도 + 마켓 총 스토어 업로드수(화면 ③ 표). 커밋 없음(읽기)."""
    from lemouton.pricing.settings import get_account_policies
    from lemouton.uploader.throttle import market_hourly_total
    s = SessionLocal()
    try:
        pols = get_account_policies(s)
        markets = sorted({p["market"] for p in pols})
        totals = {m: market_hourly_total(s, m) for m in markets}
        return jsonify({"accounts": pols, "market_totals": totals})
    finally:
        s.close()


@bp.post('/upload/account-speed')
def set_account_upload_speed():
    """계정(API) 업로드 속도 저장. body: {account_id, seconds_per_item?, enabled?}."""
    from lemouton.pricing.settings import set_account_policy
    from lemouton.multitenancy.models import MarketAccount
    data = request.get_json(silent=True) or {}
    try:
        acc_id = int(data.get('account_id'))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "account_id 필수(정수)"}), 400
    s = SessionLocal()
    try:
        if s.get(MarketAccount, acc_id) is None:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        r = set_account_policy(s, acc_id,
                               seconds_per_item=data.get('seconds_per_item'),
                               enabled=data.get('enabled'))
        s.commit()
        return jsonify({"ok": True, **r})
    finally:
        s.close()


@bp.get('/crawl/failures')
def crawl_failures():
    """[읽기전용] 크롤 실패 URL을 유형별로 묶어 반환(화면 ⑤ 실패 유형화)."""
    from lemouton.sources.failure_classify import list_crawl_failures
    s = SessionLocal()
    try:
        return jsonify({"groups": list_crawl_failures(s)})
    finally:
        s.close()


# ---------- 옵션별 브랜드 ----------

@bp.get('/options/brands')
def option_brands_list():
    """[읽기] 등록된 브랜드 목록(검색 팔레트 — 없으면 「+새 브랜드」)."""
    from lemouton.sourcing.option_brand import list_brands
    s = SessionLocal()
    try:
        return jsonify({"brands": list_brands(s)})
    finally:
        s.close()


@bp.post('/options/brand')
def set_option_brand_route():
    """옵션 1개 브랜드 저장. body {canonical_sku, brand}. 빈값=미지정(상속)."""
    from lemouton.sourcing.option_brand import set_option_brand
    data = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        brand = set_option_brand(s, data.get('canonical_sku'), data.get('brand'))
        s.commit()
        return jsonify({"ok": True, "brand": brand})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    finally:
        s.close()


@bp.get('/bundles/<path:model_code>/brands')
def bundle_option_brands(model_code):
    """[읽기] 모음전 옵션별 브랜드 + 요약(스마트바 "미지정 N개")."""
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_brand import effective_option_brand, brand_summary
    s = SessionLocal()
    try:
        opts = (s.query(Option)
                .filter(Option.model_code == model_code)
                .order_by(Option.sort_order, Option.canonical_sku).all())
        return jsonify({
            "summary": brand_summary(s, model_code),
            "options": [{
                "canonical_sku": o.canonical_sku,
                "color_display": o.color_display or o.color_code,
                "size_display": o.size_display or o.size_code,
                "brand": o.brand,                            # 자체(미지정=None)
                "effective_brand": effective_option_brand(o),  # 상속 반영
            } for o in opts],
        })
    finally:
        s.close()


@bp.post('/bundles/<path:model_code>/brands/bulk')
def bundle_option_brands_bulk(model_code):
    """옵션 브랜드 일괄 적용. body {brand, mode(all|empty|selected), skus?}."""
    from lemouton.sourcing.option_brand import bulk_apply_brand
    data = request.get_json(silent=True) or {}
    mode = data.get('mode') or 'all'
    if mode not in ('all', 'empty', 'selected'):
        return jsonify({"ok": False, "error": f"mode: {mode}"}), 400
    s = SessionLocal()
    try:
        n = bulk_apply_brand(s, model_code, data.get('brand'),
                             mode=mode, skus=data.get('skus'))
        s.commit()
        return jsonify({"ok": True, "applied": n})
    finally:
        s.close()


# ---------- Bundles ----------

_BUNDLE_FIELDS = ('model_name_display', 'category',
                  'url_lemouton', 'url_musinsa', 'url_ssf',
                  'url_lotteon', 'url_ss_lemouton',
                  'naver_product_id', 'coupang_product_id',
                  'price_template_id', 'color_template_id', 'size_template_id',
                  'market_active_ss', 'market_active_coupang',
                  # v6 Phase 5.6 (2026-05-08) — 마켓별 마진율 오버라이드
                  'external_ss_margin_value_override',
                  'external_coupang_margin_value_override')

_OPTION_FIELDS = ('market_visible_ss', 'market_visible_coupang',
                  'option_ss_price_override', 'option_coupang_price_override',
                  'price_template_id_override',
                  'option_id_lemouton', 'option_id_musinsa', 'option_id_ssf',
                  'option_id_lotteon', 'option_id_ss_lemouton',
                  'naver_option_id', 'coupang_option_id', 'boxhero_sku')


# 번들 url_* → SourceRegistry ID 매핑 (이름 기반 lookup)
_URL_FIELD_TO_SOURCE_NAME = {
    'url_lemouton': '르무통 공홈',
    'url_ss_lemouton': '스스 르무통',
    'url_musinsa': '무신사',
    'url_ssf': 'SSF',
    'url_lotteon': '롯데온',
}

# source_key → 한글 라벨 (진행 위젯 소싱처별 표시용)
_BUILTIN_SOURCE_LABELS = {
    'lemouton': '르무통 공홈',
    'ss_lemouton': '스스 르무통',
    'musinsa': '무신사',
    'ssf': 'SSF',
    'lotteon': '롯데온',
}
_custom_source_labels: dict[str, str] = {}  # 사용자 추가 소싱처 캐시 (key→label)


def _source_label(key) -> str:
    """소싱처 key → 사람이 읽는 라벨. [2026-06-30 단일명부] get_labels(명부) 단일원천.
    이름(껍데기) 수정이 즉시 반영. DB 실패 시 하드코딩 폴백(안전)."""
    if not key:
        return ''
    try:
        from lemouton.sourcing.source_registry import get_labels
        return get_labels().get(key) or _BUILTIN_SOURCE_LABELS.get(key) or str(key).upper()
    except Exception:
        return _BUILTIN_SOURCE_LABELS.get(key, str(key).upper())


def _propagate_bundle_urls_to_options(session, model_code, payload):
    """번들 url_* 필드 → 모든 옵션의 OptionSourceUrl 자동 upsert.

    번들 저장 시 호출. 입력값이 빈 문자열이면 해당 소싱처 URL 매핑 삭제.
    Returns: {'upserted': N, 'deleted': N, 'skipped_no_source': N}
    """
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.models_pricing import (
        OptionSourceUrl, SourceRegistry,
    )

    # 변경된 url_* 필드만 처리 (payload 에 포함된 것만)
    changes = {}
    for url_field, src_name in _URL_FIELD_TO_SOURCE_NAME.items():
        if url_field in payload:
            changes[url_field] = (payload[url_field] or '').strip()
    if not changes:
        return {'upserted': 0, 'deleted': 0, 'skipped_no_source': 0}

    # 옵션 SKU 목록
    sku_list = [o.canonical_sku for o in
                session.query(Option).filter_by(model_code=model_code).all()]
    if not sku_list:
        return {'upserted': 0, 'deleted': 0, 'skipped_no_source': 0}

    # 소싱처 이름 → ID 룩업
    src_by_name = {sr.name: sr.id for sr in session.query(SourceRegistry).all()}

    counts = {'upserted': 0, 'deleted': 0, 'skipped_no_source': 0}
    for url_field, new_url in changes.items():
        src_name = _URL_FIELD_TO_SOURCE_NAME[url_field]
        src_id = src_by_name.get(src_name)
        if src_id is None:
            counts['skipped_no_source'] += 1
            continue

        if new_url:
            # 빈 값 X → 모든 옵션에 upsert (이미 있으면 URL 갱신)
            for sku in sku_list:
                existing = (session.query(OptionSourceUrl)
                            .filter_by(canonical_sku=sku, source_id=src_id)
                            .first())
                if existing:
                    if existing.product_url != new_url:
                        existing.product_url = new_url
                        counts['upserted'] += 1
                else:
                    session.add(OptionSourceUrl(
                        canonical_sku=sku,
                        source_id=src_id,
                        product_url=new_url,
                    ))
                    counts['upserted'] += 1
        else:
            # 빈 값 → 해당 소싱처의 모든 옵션 매핑 삭제
            deleted = (session.query(OptionSourceUrl)
                       .filter(OptionSourceUrl.canonical_sku.in_(sku_list),
                               OptionSourceUrl.source_id == src_id)
                       .delete(synchronize_session=False))
            counts['deleted'] += deleted
    return counts


@bp.post('/bundles/<code>')
def save_bundle(code: str):
    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        before = {f: getattr(m, f, None) for f in _BUNDLE_FIELDS}
        for f in _BUNDLE_FIELDS:
            if f in payload:
                setattr(m, f, payload[f])
        after = {f: getattr(m, f, None) for f in _BUNDLE_FIELDS}
        try:
            from lemouton.audit.service import record_update
            record_update(s, target_table='models', target_id=code,
                          before=before, after=after,
                          actor=payload.get('_actor', 'web_user'))
        except Exception:
            pass
        # ★ 번들 url_* → 옵션 OptionSourceUrl 자동 전파
        propagate_counts = _propagate_bundle_urls_to_options(s, code, payload)
        s.commit()
        return _ok(model_code=m.model_code, propagated=propagate_counts)
    finally:
        s.close()


@bp.post('/bundles/<code>/auto')
def bundle_auto_toggle(code: str):
    """모음전별 자동화 ON/OFF 토글. v6 Phase 3.5 (2026-05-07).

    POST 본문: {"enabled": true|false}
    응답: {"ok": true, "model_code": ..., "auto_enabled": true|false}
    """
    payload = request.get_json(silent=True) or {}
    if 'enabled' not in payload:
        return _err('enabled 필드가 필요합니다.', 400)
    enabled = bool(payload['enabled'])
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        before = {'auto_enabled': bool(m.auto_enabled)}
        m.auto_enabled = enabled
        try:
            from lemouton.audit.service import record_update
            record_update(s, target_table='models', target_id=code,
                          before=before, after={'auto_enabled': enabled},
                          actor=payload.get('_actor', 'web_user'))
        except Exception:
            pass
        s.commit()
        return _ok(model_code=code, auto_enabled=enabled)
    finally:
        s.close()


@bp.post('/bundles/<code>/sync-urls-to-options')
def sync_urls_to_options(code: str):
    """번들의 모든 url_* 를 옵션에 일괄 동기화 (수동 트리거).

    이미 등록된 url_* 모두를 강제 전파 (기존 매핑은 갱신, 빈 값은 삭제 안 함).
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        # 모든 url_* 필드를 payload 처럼 구성 (빈 값은 스킵)
        payload = {}
        for url_field in _URL_FIELD_TO_SOURCE_NAME:
            v = getattr(m, url_field, None)
            if v:  # 빈 값은 동기화에 포함 X (수동 동기화는 추가만)
                payload[url_field] = v
        counts = _propagate_bundle_urls_to_options(s, code, payload)
        s.commit()
        return _ok(propagated=counts)
    finally:
        s.close()


@bp.get('/bundles/<code>/template-suggestions')
def bundle_template_suggestions(code: str):
    """[v2] 옵션 B — 콤보 모달의 추천 칩 데이터.

    모음전에 적용된 색상·사이즈 템플릿의 코드 list 반환.
    """
    from lemouton.templates.models import ColorTemplate, SizeTemplate
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        colors, sizes = [], []
        if m.color_template_id:
            ct = s.query(ColorTemplate).filter_by(id=m.color_template_id).first()
            if ct:
                try: colors = json.loads(ct.color_codes_json or '[]')
                except Exception: colors = []
        if m.size_template_id:
            st = s.query(SizeTemplate).filter_by(id=m.size_template_id).first()
            if st:
                try: sizes = json.loads(st.size_codes_json or '[]')
                except Exception: sizes = []
        return _ok(colors=colors, sizes=sizes)
    finally:
        s.close()


# ---------- [v2] 옵션 매트릭스 개별 CRUD ----------

@bp.post('/bundles/<code>/options')
def options_add(code: str):
    """[v2] 콤보 거치지 않고 옵션 1개 직접 추가.

    Body: {color_code, size_code}
    """
    payload = request.get_json(silent=True) or {}
    color = (payload.get('color_code') or '').strip()
    size = (payload.get('size_code') or '').strip()
    if not color or not size:
        return _err('color_code / size_code 필요해요.', 400)
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        sku = f"{code}-{color}-{size}"
        if s.query(Option).filter_by(canonical_sku=sku).first():
            return _err(f"옵션 '{sku}' 가 이미 존재해요.", 409)
        o = Option(canonical_sku=sku, model_code=code,
                   color_code=color, size_code=size)
        s.add(o)
        try:
            from lemouton.audit.service import record_create
            record_create(s, target_table='options', target_id=sku,
                          state={'color_code': color, 'size_code': size},
                          actor='web_user',
                          reason='옵션 매트릭스에서 직접 추가')
        except Exception:
            pass
        s.commit()
        return _ok(canonical_sku=sku)
    finally:
        s.close()


@bp.post('/bundles/<code>/options/<sku>/delete')
def options_delete(code: str, sku: str):
    """[v2] 옵션 1개만 삭제 (콤보와 무관)."""
    s = SessionLocal()
    try:
        o = s.query(Option).filter_by(canonical_sku=sku, model_code=code).first()
        if o is None:
            return _err('옵션을 찾을 수 없어요.', 404)
        try:
            from lemouton.audit.service import record_delete
            state = {f: getattr(o, f, None) for f in _OPTION_FIELDS}
            record_delete(s, target_table='options', target_id=sku,
                          state=state, actor='web_user',
                          reason='옵션 매트릭스에서 직접 삭제')
        except Exception:
            pass
        # cascade: 자식 행 정리 (etc_source_urls, etc.)
        from sqlalchemy import text
        s.execute(text('PRAGMA foreign_keys=OFF'))
        for tbl in ('etc_source_urls', 'price_track_history',
                    'market_registrations', 'option_source_links',
                    'option_account_registrations'):
            try:
                s.execute(text(f"DELETE FROM {tbl} WHERE canonical_sku = :sku"),
                          {'sku': sku})
            except Exception:
                pass
        s.delete(o)
        s.execute(text('PRAGMA foreign_keys=ON'))
        s.commit()
        return _ok(deleted_sku=sku)
    finally:
        s.close()


@bp.post('/bundles/<code>/options/<sku>/rename')
def options_rename(code: str, sku: str):
    """[v2] 옵션 코드 변경 — canonical_sku cascade rename.

    Body: {new_color, new_size, reason?}
    """
    payload = request.get_json(silent=True) or {}
    new_color = (payload.get('new_color') or '').strip()
    new_size = (payload.get('new_size') or '').strip()
    if not new_color or not new_size:
        return _err('new_color / new_size 필요해요.', 400)
    new_sku = f"{code}-{new_color}-{new_size}"
    if new_sku == sku:
        return _err('변경 사항이 없어요.', 400)
    s = SessionLocal()
    try:
        o = s.query(Option).filter_by(canonical_sku=sku, model_code=code).first()
        if o is None:
            return _err('옵션을 찾을 수 없어요.', 404)
        if s.query(Option).filter_by(canonical_sku=new_sku).first():
            return _err(f"옵션 '{new_sku}' 가 이미 존재해요.", 409)
        from sqlalchemy import text
        # 기존 FK violation baseline
        baseline = set(
            tuple(r) for r in
            s.execute(text('PRAGMA foreign_key_check')).fetchall()
        )
        s.execute(text('PRAGMA foreign_keys=OFF'))
        # cascade canonical_sku 자식들
        for tbl in ('etc_source_urls', 'price_track_history',
                    'market_registrations', 'option_source_links',
                    'option_account_registrations'):
            try:
                s.execute(
                    text(f"UPDATE {tbl} SET canonical_sku=:n WHERE canonical_sku=:o"),
                    {'o': sku, 'n': new_sku},
                )
            except Exception:
                pass
        # 옵션 자체
        s.execute(
            text("UPDATE options SET color_code=:c, size_code=:sz, canonical_sku=:n "
                 "WHERE canonical_sku=:o"),
            {'c': new_color, 'sz': new_size, 'n': new_sku, 'o': sku},
        )
        s.execute(text('PRAGMA foreign_keys=ON'))
        after = set(
            tuple(r) for r in
            s.execute(text('PRAGMA foreign_key_check')).fetchall()
        )
        new_violations = after - baseline
        if new_violations:
            s.rollback()
            return _err(f'cascade FK 위반 (롤백): {sorted(new_violations)}', 500)
        try:
            from lemouton.audit.service import record_update
            record_update(s, target_table='options', target_id=new_sku,
                          before={'canonical_sku': sku, 'color_code': o.color_code,
                                  'size_code': o.size_code},
                          after={'canonical_sku': new_sku, 'color_code': new_color,
                                 'size_code': new_size},
                          actor='web_user', reason=payload.get('reason'))
        except Exception:
            pass
        s.commit()
        return _ok(old_sku=sku, new_sku=new_sku,
                   redirect=f'/bundles/{code}/option/{new_sku}')
    finally:
        s.close()


@bp.post('/bundles/<code>/option/<sku>')
def save_option(code: str, sku: str):
    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        o = s.query(Option).filter_by(canonical_sku=sku, model_code=code).first()
        if o is None:
            return _err('옵션을 찾을 수 없어요.', 404)
        before = {f: getattr(o, f, None) for f in _OPTION_FIELDS}
        for f in _OPTION_FIELDS:
            if f in payload:
                setattr(o, f, payload[f])
        after = {f: getattr(o, f, None) for f in _OPTION_FIELDS}
        try:
            from lemouton.audit.service import record_update
            record_update(s, target_table='options', target_id=sku,
                          before=before, after=after,
                          actor=payload.get('_actor', 'web_user'))
        except Exception:
            pass
        s.commit()
        return _ok(canonical_sku=o.canonical_sku)
    finally:
        s.close()


# [v2] ---------- 모음전 코드 변경 + Dry-run 미리보기 + 옵션×계정 매핑 ----------

@bp.post('/bundles/<code>/rename')
def bundle_rename(code: str):
    """[v2] 모음전 코드 변경 (cascade) — Body: {new_code, reason?}"""
    payload = request.get_json(silent=True) or {}
    new_code = (payload.get('new_code') or '').strip()
    reason = payload.get('reason')
    if not new_code:
        return _err('new_code 가 필요해요.', 400)
    from lemouton.sourcing.rename import rename_model_code
    s = SessionLocal()
    try:
        try:
            result = rename_model_code(s, old_code=code, new_code=new_code,
                                       actor=payload.get('actor', 'web_user'),
                                       reason=reason)
        except ValueError as e:
            return _err(str(e), 400)
        except LookupError as e:
            return _err(str(e), 404)
        except FileExistsError as e:
            return _err(str(e), 409)
        except RuntimeError as e:
            return _err(f'cascade 실패 (롤백됨): {e}', 500)
        s.commit()
        from urllib.parse import quote
        return _ok(
            new_code=new_code,
            redirect=f'/bundles/{quote(new_code)}',
            **{k: v for k, v in result.items()
               if k not in ('old_code', 'new_code', 'cascade_detail',
                            'fk_violations')},
            cascade=result['cascade_detail'],
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/preview-delete')
def bundle_preview_delete(code: str):
    """[v2] Dry-run — 모음전 삭제 영향."""
    from lemouton.audit.service import preview_bundle_delete
    s = SessionLocal()
    try:
        try:
            result = preview_bundle_delete(s, code)
        except LookupError as e:
            return _err(str(e), 404)
        return _ok(**result)
    finally:
        s.close()


@bp.post('/bundles/<code>/preview-price')
def bundle_preview_price(code: str):
    """[v2] Dry-run — 가격 변경 영향."""
    from lemouton.audit.service import preview_price_change
    payload = request.get_json(silent=True) or {}
    new_price = payload.get('new_sale_price')
    if not isinstance(new_price, int) or new_price <= 0:
        return _err('new_sale_price (int) 가 필요해요.', 400)
    s = SessionLocal()
    try:
        try:
            result = preview_price_change(s, model_code=code,
                                          new_sale_price=new_price)
        except LookupError as e:
            return _err(str(e), 404)
        return _ok(**result)
    finally:
        s.close()


@bp.post('/bundles/<code>/register/<market>')
def register_to_market(code: str, market: str):
    """자동 등록 호출 — T14/T15 wrapping 사용.

    Body: {leaf_category_id|display_category_code, image_url, detail_html, ...}
    """
    if market not in ('smartstore', 'coupang'):
        return _err('market은 smartstore/coupang 중 하나여야 해요.', 400)
    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        opts = s.query(Option).filter_by(model_code=code).all()
    finally:
        s.close()

    if market == 'smartstore':
        from lemouton.registration.smartstore import (
            RegistrationInputs, register_bundle_to_smartstore,
        )
        try:
            inputs = RegistrationInputs(
                leaf_category_id=str(payload.get('leaf_category_id', '')),
                image_url=payload.get('image_url', ''),
                detail_html=payload.get('detail_html', '<p>상세</p>'),
                after_service_phone=payload.get('after_service_phone', '02-0000-0000'),
                after_service_guide=payload.get('after_service_guide', '고객센터 문의'),
            )
        except Exception as e:
            return _err(f'입력 오류: {e}', 400)
        if not inputs.leaf_category_id:
            return _err('leaf_category_id가 필요해요.', 400)
        if not inputs.image_url:
            return _err('image_url(Naver CDN)이 필요해요.', 400)
        result = register_bundle_to_smartstore(
            bundle=m, inputs=inputs,
            sale_price=payload.get('sale_price'),
            stock_quantity=int(payload.get('stock_quantity', 100)),
        )
        return jsonify({'ok': result.get('ok', False), **result})

    # coupang
    from lemouton.registration.coupang import (
        CoupangRegistrationInputs, register_bundle_to_coupang,
    )
    try:
        inputs = CoupangRegistrationInputs(
            display_category_code=int(payload.get('display_category_code', 0)),
            brand=payload.get('brand', '르무통'),
            seller_product_name=payload.get('seller_product_name'),
            item_image_url=payload.get('image_url', ''),
            detail_html=payload.get('detail_html', '<p>상세</p>'),
            delivery_charge=int(payload.get('delivery_charge', 3500)),
            return_charge=int(payload.get('return_charge', 5000)),
        )
    except Exception as e:
        return _err(f'입력 오류: {e}', 400)
    if not inputs.display_category_code:
        return _err('display_category_code가 필요해요.', 400)
    result = register_bundle_to_coupang(
        bundle=m, options=opts, inputs=inputs,
        sale_price=payload.get('sale_price'),
    )
    return jsonify({'ok': result.get('ok', False), **result})


@bp.post('/bundles/migrate-from-ss')
def bundle_migrate_from_ss():
    """[v2 Case 3] 스스 originProductNo 1개로 모음전 자동 생성 + 옵션 매트릭스 + 매칭 시작.

    Body: {origin_product_no, model_code, brand?, category?}
    Returns: {ok, model_code, redirect, sync: {auto/fuzzy/failed/matches}}
    """
    payload = request.get_json(silent=True) or {}
    origin_no = (payload.get('origin_product_no') or '').strip()
    code = (payload.get('model_code') or '').strip()
    brand = (payload.get('brand') or '르무통').strip()
    category = (payload.get('category') or '신발').strip()

    if not origin_no:
        return _err('origin_product_no 가 필요해요.', 400)
    if not code:
        return _err('model_code 가 필요해요.', 400)

    s = SessionLocal()
    try:
        # 1) 중복 코드 검사
        if s.query(Model).filter_by(model_code=code).first():
            return _err(f"모음전 코드 '{code}' 가 이미 존재해요.", 409)

        # 2) 스스 API 호출 — 상품 + 옵션 정보 가져오기
        try:
            from shared.platforms.smartstore.get_options import fetch_product_options
            r = fetch_product_options(int(origin_no))
        except Exception as e:
            return _err(f'스스 API 호출 실패: {e}', 500)
        if not r.success:
            return _err(f'스스 API 응답 오류: {r.error}', 502)

        product_name = r.product_name or f'스스 상품 {origin_no}'
        sale_price = r.sale_price

        # 3) 모음전 자동 생성
        m = Model(
            model_code=code,
            model_name_raw=product_name,
            model_name_display=product_name,
            brand=brand,
            category=category,
            naver_product_id=str(origin_no),
        )
        s.add(m)

        # 4) 옵션 매트릭스 자동 생성 (스스 옵션 1개 = 우리 옵션 1개)
        # 색상·사이즈 사전으로 우리 표준 코드로 변환
        from lemouton.sources.option_matcher import (
            _build_color_lookup, _normalize, _extract_size_number,
        )
        color_lookup = _build_color_lookup(s)
        created_options = []
        skipped = []
        for ext in r.options:
            color_raw = ext.name1 or ''
            size_raw = ext.name2 or ''
            # 색상: 사전 lookup → 우리 표준 코드. 없으면 raw 사용
            std_color = color_lookup.get(_normalize(color_raw), color_raw.strip())
            # 사이즈: 숫자 추출. 없으면 raw 사용
            std_size = _extract_size_number(size_raw) or size_raw.strip()
            if not std_color or not std_size:
                skipped.append({'ext_id': ext.option_id, 'reason': 'empty_color_or_size'})
                continue
            sku = f"{code}-{std_color}-{std_size}"
            # 중복 방지
            if any(o.canonical_sku == sku for o in created_options):
                skipped.append({'ext_id': ext.option_id, 'reason': 'duplicate_sku'})
                continue
            o = Option(
                canonical_sku=sku, model_code=code,
                color_code=std_color, size_code=std_size,
                naver_option_id=str(ext.option_id),  # 자동 매칭!
                market_visible_ss=True,
                market_visible_coupang=False,
            )
            s.add(o)
            created_options.append(o)

        # audit
        try:
            from lemouton.audit.service import record_create
            record_create(s, target_table='models', target_id=code,
                          state={'name': product_name, 'brand': brand,
                                 'naver_product_id': origin_no,
                                 'options_count': len(created_options)},
                          actor='web_user',
                          reason=f'스스 마이그레이션 — originProductNo {origin_no}')
        except Exception:
            pass

        s.commit()
        from urllib.parse import quote
        return _ok(
            model_code=code,
            redirect=f'/bundles/{quote(code)}',
            product_name=product_name,
            sale_price=sale_price,
            external_options=len(r.options),
            options_created=len(created_options),
            options_skipped=skipped,
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/sync-ss-options')
def sync_ss_options(code: str):
    """[v2 Case 3] 스마트스토어 API 호출 → 옵션 자동 매칭 결과 반환.

    Body: (없음, originProductNo 는 모음전 DB 에서 가져옴)
    Returns:
      {ok, origin_product_no, product_name, total, auto, fuzzy, failed,
       matches: [{canonical_sku, color_code, size_code, matched_option_id?,
                  matched_external_name?, confidence, candidates[]}]}
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        if not m.naver_product_id:
            return _err('원상품번호 (naver_product_id) 가 비어있어요. §6 에 입력 후 저장하세요.', 400)
        # user_input 양방향 인식 — origin / channel 어느 쪽이든 둘 다 찾아 저장
        try:
            from shared.platforms.smartstore.get_channel_no import resolve_product_ids
            resolved = resolve_product_ids(int(m.naver_product_id))
        except Exception as e:
            return _err(f'스스 API 호출 실패: {e}', 500)
        if not resolved:
            return _err(
                f'상품번호 {m.naver_product_id} 매칭 안 됨 — 셀러센터의 정확한 '
                'originProductNo 또는 채널상품번호인지 확인',
                404,
            )
        origin_no = resolved['origin_product_no']
        channel_no = resolved['channel_product_no']

        # DB 동기화: origin_product_no 와 channel_product_no 둘 다 저장
        # (사용자가 channel 로 입력한 경우 naver_product_id 도 origin 으로 정정)
        if str(origin_no) != (m.naver_product_id or ''):
            m.naver_product_id = str(origin_no)
        if str(channel_no) != (m.naver_channel_product_id or ''):
            m.naver_channel_product_id = str(channel_no)
        s.commit()

        try:
            from shared.platforms.smartstore.get_options import fetch_product_options
            r = fetch_product_options(origin_no)
        except Exception as e:
            return _err(f'옵션 조회 실패: {e}', 500)
        if not r.success:
            return _err(f'스스 API 응답 오류: {r.error}', 502)
        if not r.options:
            return _err('옵션이 0개 — 스스에 옵션 등록 안 된 상품일 수 있어요.', 200)

        from lemouton.sources.option_matcher import match_external_options_to_ours
        matches = match_external_options_to_ours(
            s, model_code=code, external_options=r.options,
        )
        # 카운트
        auto = sum(1 for x in matches if x.confidence == 'auto')
        fuzzy = sum(1 for x in matches if x.confidence == 'fuzzy')
        failed = sum(1 for x in matches if x.confidence == 'failed')
        return _ok(
            origin_product_no=r.origin_product_no,
            product_name=r.product_name,
            sale_price=r.sale_price,
            total=len(matches),
            external_total=len(r.options),
            auto=auto, fuzzy=fuzzy, failed=failed,
            # [Phase 4] 미매칭 수기 정정 — 전체 마켓 옵션 (검색·직접입력용)
            external_options=[{
                'option_id': o.option_id,
                'name': o.display_name or str(o.option_id),
                'stock': o.stock,
            } for o in r.options],
            matches=[{
                'canonical_sku': m.canonical_sku,
                'color_code': m.color_code,
                'size_code': m.size_code,
                'confidence': m.confidence,
                'matched_option_id': m.matched_option_id,
                'matched_external_name': m.matched_external_name,
                'candidates': m.candidates,
                'reason': m.reason,
            } for m in matches],
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/open-ss-edit')
def open_ss_edit(code: str):
    """[E] 모음전 → 스마트스토어 판매자 센터 상품 편집 페이지 자동 진입.

    영구 로그인 세션(persistent_context)을 사용 — 한 번 [🔐 로그인] 한 후로는
    매번 자동 로그인 상태로 페이지가 열린다.

    Flow:
      1. 모음전의 naver_product_id (originProductNo) 조회
      2. bundle_account_registrations 에서 smartstore 계정 찾기 → 없으면 기본 계정 사용
      3. profile 디렉터리 존재 확인 (없으면 "먼저 [🔐 로그인]" 안내)
      4. detached 프로세스로 Playwright 띄움 → /products/v2/{originProductNo} 로 직행
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        if not m.naver_product_id:
            return _err('스마트스토어 원상품번호가 비어있어요. §6 에서 입력 후 저장하세요.', 400)

        from lemouton.sourcing.models_v2 import UploadAccount
        from lemouton.multitenancy.models import BundleAccountRegistration

        reg_acc = (
            s.query(UploadAccount)
            .join(BundleAccountRegistration,
                  BundleAccountRegistration.account_id == UploadAccount.id)
            .filter(BundleAccountRegistration.model_code == code,
                    UploadAccount.market == 'smartstore')
            .first()
        )
        if reg_acc is None:
            reg_acc = (
                s.query(UploadAccount)
                .filter_by(market='smartstore', is_active=True)
                .order_by(UploadAccount.id)
                .first()
            )
        if reg_acc is None:
            return _err('스마트스토어 계정이 없어요. 「판매처 계정」 페이지에서 추가하세요.', 400)

        env_prefix = reg_acc.env_prefix
        display_name = reg_acc.display_name
    finally:
        s.close()

    from lemouton.auth.profile_store import default_store as _profile_store
    store = _profile_store()
    if not store.has_profile('smartstore', env_prefix):
        return _err(
            f"{display_name} 영구 로그인이 안 돼있어요. "
            "「판매처 계정」 페이지의 [🔐 로그인] 버튼으로 1회 로그인 먼저 해주세요.",
            400,
        )

    # 셀러센터 검색 페이지 — channel_product_id 자동 fill 용으로 launcher 에 keyword 전달
    edit_url = "https://sell.smartstore.naver.com/#/products/origin-list"
    search_keyword = m.naver_channel_product_id or m.naver_product_id

    if not m.naver_channel_product_id:
        # channel_product_id 미저장 — 동기화 한번 돌리면 자동 채워짐
        return _err(
            '상품번호 (channelProductNo) 미저장. §6 에서 [동기화 실행] 한번 돌리면 자동 채워져요.',
            400,
        )

    try:
        from lemouton.auth.marketplace_browser import spawn as _spawn_browser
        # auto_click_first_product=True 면 launcher 가 검색 + [수정] 자동
        pid = _spawn_browser(
            source='smartstore', account_key=env_prefix,
            url=edit_url + f"?searchKeyword={search_keyword}",
            auto_click_first_product=True,
        )
    except Exception as e:
        return _err(f'브라우저 스폰 실패: {type(e).__name__}: {e}', 500)

    return _ok(pid=pid, account=display_name, url=edit_url, keyword=search_keyword)


@bp.post('/bundles/<code>/open-coupang-edit')
def open_coupang_edit(code: str):
    """[E] 모음전 → 쿠팡 Wing 상품 검색 페이지 자동 진입.

    영구 로그인 세션(persistent_context) 사용 — 한 번 [🔐 로그인] 한 후로는
    매번 자동 로그인 상태로 페이지가 열린다.

    Flow:
      1. 모음전의 coupang_product_id (sellerProductId) 조회
      2. bundle_account_registrations 에서 coupang 계정 찾기 → 없으면 기본 활성 계정 사용
      3. profile 디렉터리 존재 확인 (없으면 "먼저 [🔐 로그인]" 안내)
      4. detached 프로세스로 Playwright 띄움 → vendor-inventory/list?keyword={id} 진입
    """
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        # [v3] 우선 sellerProductId 사용 (윙 검색 정확) — 없으면 productId fallback
        seller_product_id = (getattr(m, 'coupang_seller_product_id', None)
                             or m.coupang_product_id)
        if not seller_product_id:
            return _err('쿠팡 sellerProductId (또는 productId) 가 비어있어요. §6 에서 등록하세요.', 400)

        from lemouton.sourcing.models_v2 import UploadAccount
        from lemouton.multitenancy.models import BundleAccountRegistration

        reg_acc = (
            s.query(UploadAccount)
            .join(BundleAccountRegistration,
                  BundleAccountRegistration.account_id == UploadAccount.id)
            .filter(BundleAccountRegistration.model_code == code,
                    UploadAccount.market == 'coupang')
            .first()
        )
        if reg_acc is None:
            reg_acc = (
                s.query(UploadAccount)
                .filter_by(market='coupang', is_active=True)
                .order_by(UploadAccount.id)
                .first()
            )
        if reg_acc is None:
            return _err('쿠팡 계정이 없어요. 「판매처 계정」 페이지에서 추가하세요.', 400)

        env_prefix = reg_acc.env_prefix
        display_name = reg_acc.display_name
    finally:
        s.close()

    from lemouton.auth.profile_store import default_store as _profile_store
    store = _profile_store()
    if not store.has_profile('coupang', env_prefix):
        return _err(
            f"{display_name} 영구 로그인이 안 돼있어요. "
            "「판매처 계정」 페이지의 [🔐 로그인] 버튼으로 1회 로그인 먼저 해주세요.",
            400,
        )

    # [v3] Wing 상품수정 직접 URL — vendorInventoryId={sellerProductId}
    edit_url = (
        "https://wing.coupang.com/tenants/seller-web/vendor-inventory/modify"
        f"?vendorInventoryId={seller_product_id}&keyword={seller_product_id}"
    )

    try:
        from lemouton.auth.marketplace_browser import spawn as _spawn_browser
        pid = _spawn_browser(
            source='coupang', account_key=env_prefix,
            url=edit_url,
            auto_click_first_product=False,  # 직접 URL → 자동 클릭 불필요
        )
    except Exception as e:
        return _err(f'브라우저 스폰 실패: {type(e).__name__}: {e}', 500)

    return _ok(pid=pid, account=display_name, url=edit_url, keyword=seller_product_id)


@bp.post('/bundles/<code>/apply-ss-matching')
def apply_ss_matching(code: str):
    """[v2 Case 3] 사용자 confirm 후 매칭 결과 DB 저장.

    Body: {matches: [{canonical_sku, naver_option_id, learn_color_variant?}]}
    """
    payload = request.get_json(silent=True) or {}
    matches = payload.get('matches') or []
    if not isinstance(matches, list) or not matches:
        return _err('matches list 가 비어있어요.', 400)
    s = SessionLocal()
    try:
        from lemouton.sources.option_matcher import apply_matching, auto_learn_color_variant
        result = apply_matching(s, model_code=code, matches=matches)
        # 색상 사전 자동 학습 (옵션)
        learned = 0
        for m in matches:
            std = m.get('learn_color_variant_standard')
            new = m.get('learn_color_variant_new')
            if std and new:
                if auto_learn_color_variant(s, standard_code=std, new_variant=new):
                    learned += 1
        s.commit()
        return _ok(updated=result['updated'], failed=result['failed'],
                   color_dict_learned=learned)
    finally:
        s.close()


@bp.post('/bundles/<code>/sync-cp-options')
def sync_cp_options(code: str):
    """[Phase 4] 쿠팡 API 호출 → 옵션 자동 매칭 결과 반환 (sync-ss-options 쿠팡판)."""
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        spid = getattr(m, 'coupang_seller_product_id', None) or m.coupang_product_id
        if not spid:
            return _err('쿠팡 상품번호가 비어있어요. 마켓 탭에 입력 후 저장하세요.', 400)
        try:
            from shared.platforms.coupang.products import get_product, extract_vendor_items
            detail = get_product(int(spid))
        except Exception as e:
            return _err(f'쿠팡 API 호출 실패: {e}', 500)
        items = extract_vendor_items(detail)
        if not items:
            return _err('쿠팡 옵션이 0개 — 등록 안 된 상품일 수 있어요.', 200)
        from shared.platforms.smartstore.get_options import OptionRow
        ext = [OptionRow(option_id=it['vendor_item_id'],
                         name1=(it.get('color') or ''), name2=(it.get('size') or ''),
                         stock=0) for it in items]
        from lemouton.sources.option_matcher import match_external_options_to_ours
        matches = match_external_options_to_ours(s, model_code=code, external_options=ext)
        auto = sum(1 for x in matches if x.confidence == 'auto')
        fuzzy = sum(1 for x in matches if x.confidence == 'fuzzy')
        failed = sum(1 for x in matches if x.confidence == 'failed')
        return _ok(
            market='coupang',
            product_name=detail.get('sellerProductName') or '쿠팡 상품',
            origin_product_no=spid,
            total=len(matches), external_total=len(items),
            auto=auto, fuzzy=fuzzy, failed=failed,
            external_options=[{
                'option_id': it['vendor_item_id'],
                'name': (f"{it.get('color', '')} / {it.get('size', '')}".strip(' /')
                         or str(it['vendor_item_id'])),
                'stock': 0,
            } for it in items],
            matches=[{
                'canonical_sku': mr.canonical_sku,
                'color_code': mr.color_code,
                'size_code': mr.size_code,
                'confidence': mr.confidence,
                'matched_option_id': mr.matched_option_id,
                'matched_external_name': mr.matched_external_name,
                'candidates': mr.candidates,
                'reason': mr.reason,
            } for mr in matches],
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/apply-cp-matching')
def apply_cp_matching(code: str):
    """[Phase 4] 쿠팡 매칭 결과 DB 저장 (Option.coupang_option_id).

    Body: {matches: [{canonical_sku, coupang_option_id}]}
    """
    payload = request.get_json(silent=True) or {}
    matches = payload.get('matches') or []
    if not isinstance(matches, list) or not matches:
        return _err('matches list 가 비어있어요.', 400)
    s = SessionLocal()
    try:
        from lemouton.sources.option_matcher import apply_matching
        result = apply_matching(s, model_code=code, matches=matches,
                                option_id_field='coupang_option_id')
        s.commit()
        return _ok(updated=result['updated'], failed=result['failed'])
    finally:
        s.close()


@bp.post('/bundles/<code>/upload')
def upload_active_markets(code: str):
    """[v2 안전 가드] 「활성 마켓에 자동 업로드」 버튼 — Case 3 마이그레이션 시 누르지 마세요.

    이 버튼은 본래 즉시 마켓 push 의도였으나 orchestrator 시그니처 불일치로
    현재 직접 호출 막힘. 권장 운영:
      - 자동 사이클: 6시간마다 자동 push (Phase A→B→C→D)
      - 즉시 트리거: 홈 페이지 「▶ 지금 바로 실행」
    """
    return _ok(
        skipped=True,
        message='이 모음전 단독 즉시 업로드는 별도 기능입니다. 6시간 자동 사이클이 곧 동기화하거나, 홈의 「▶ 지금 바로 실행」을 사용하세요.',
        guide_url='/',
    )


# ---------- Templates ----------

@bp.post('/templates/price')
def upsert_price_template():
    payload = request.get_json(silent=True) or {}
    tpl_id = payload.get('id')
    s = SessionLocal()
    try:
        if tpl_id:
            t = s.query(PriceTemplate).filter_by(id=tpl_id).first()
            if t is None:
                return _err('가격 템플릿을 찾을 수 없어요.', 404)
        else:
            t = PriceTemplate(name=payload.get('name', '새 가격 템플릿'))
            s.add(t)
        for f in ('name', 'boxhero_purchase_price', 'winner_premium_price',
                  'guardrail_lower', 'guardrail_upper', 'rounding_unit',
                  # [2026-05-25] 판매가 정책 ('color' / 'cheapest')
                  'pricing_policy',
                  # [2026-05-25 V5] 매입가 산정 우선순위 ('template' / 'avg')
                  'price_source_priority',
                  'ss_normal_price', 'ss_boxhero_sale_price', 'ss_external_sale_price',
                  'ss_fee_rate', 'ss_margin_rate', 'ss_delivery_fee',
                  'ss_return_fee', 'ss_exchange_fee',
                  # [NEW 2026-05-25] 소싱처/사입 분리 책정 모드
                  'ss_mode_sourcing', 'ss_rate_sourcing', 'ss_amount_sourcing',
                  'ss_mode_purchase', 'ss_rate_purchase', 'ss_amount_purchase',
                  'coupang_normal_price', 'coupang_boxhero_sale_price', 'coupang_external_sale_price',
                  'coupang_fee_rate', 'coupang_margin_rate', 'coupang_delivery_fee',
                  'coupang_return_fee', 'coupang_exchange_fee',
                  'coupang_mode_sourcing', 'coupang_rate_sourcing', 'coupang_amount_sourcing',
                  'coupang_mode_purchase', 'coupang_rate_purchase', 'coupang_amount_purchase'):
            if f in payload:
                setattr(t, f, payload[f])
        s.commit()
        return _ok(id=t.id, name=t.name)
    finally:
        s.close()


# ---------- Track ----------

@bp.get('/track/<sku>')
def track_series(sku: str):
    days = int(request.args.get('days', '30'))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    s = SessionLocal()
    try:
        rows = (
            s.query(PriceTrackHistory)
            .filter(PriceTrackHistory.canonical_sku == sku,
                    PriceTrackHistory.captured_at >= cutoff)
            .order_by(PriceTrackHistory.captured_at)
            .all()
        )
        out = [
            {'source': r.source, 'price': r.price, 'stock': r.stock,
             'at': r.captured_at.isoformat()}
            for r in rows
        ]
    finally:
        s.close()
    return _ok(canonical_sku=sku, days=days, points=out)


# ---------- Search ----------

@bp.get('/search/bundles')
def search_bundles():
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    tokens = split_tokens(q)
    s = SessionLocal()
    try:
        query = s.query(Model.model_code, Model.model_name_display, Model.category)
        # ★ 박스히어로식 다중 키워드 AND 교집합
        query = apply_and_filter(
            query, tokens,
            Model.model_code, Model.model_name_raw, Model.model_name_display,
            op='ilike',
        )
        items = [
            {'model_code': r[0], 'name': r[1], 'category': r[2]}
            for r in query.limit(20).all()
        ]
    finally:
        s.close()
    return _ok(q=q, items=items)


@bp.get('/search/templates')
def search_templates():
    from shared.search import split_tokens, apply_and_filter
    kind = request.args.get('type', 'price')
    q = (request.args.get('q') or '').strip()
    tokens = split_tokens(q)
    model = {
        'price': PriceTemplate,
        'color': ColorTemplate,
        'size': SizeTemplate,
    }.get(kind)
    if model is None:
        return _err('type은 price/color/size 중 하나여야 해요.', 400)
    s = SessionLocal()
    try:
        query = s.query(model.id, model.name)
        # ★ 박스히어로식 다중 키워드 AND 교집합
        query = apply_and_filter(query, tokens, model.name, op='ilike')
        items = [{'id': r[0], 'name': r[1]} for r in query.limit(20).all()]
    finally:
        s.close()
    return _ok(type=kind, q=q, items=items)


# ---------- Queue / DLQ actions ----------

@bp.post('/queue/<int:item_id>/resolve')
def queue_resolve(item_id: int):
    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        it = s.query(DiscoveryQueueItem).filter_by(id=item_id).first()
        if it is None:
            return _err('큐 항목을 찾을 수 없어요.', 404)
        it.status = payload.get('status', 'resolved')
        it.resolved_canonical_sku = payload.get('resolved_canonical_sku')
        it.resolved_at = datetime.now(timezone.utc)
        s.commit()
    finally:
        s.close()
    return _ok(id=item_id)


@bp.post('/dlq/<sku>/<market>/retry')
def dlq_retry(sku: str, market: str):
    """단일 실패 항목 재시도. orchestrator 호출."""
    from lemouton.uploader.orchestrator import run_uploader
    try:
        result = run_uploader(canonical_sku=sku, market=market, dry_run=False)
    except TypeError:
        try:
            result = run_uploader(dry_run=False)
        except Exception as e:
            return _err(f'재시도 실패: {e}', 500)
    except Exception as e:
        return _err(f'재시도 실패: {e}', 500)
    return _ok(result=result if isinstance(result, dict) else str(result))


# ---------- Bundle 복제/삭제 ----------

@bp.post('/bundles/<code>/duplicate')
def bundle_duplicate(code: str):
    payload = request.get_json(silent=True) or {}
    new_code = (payload.get('new_code') or '').strip()
    if not new_code:
        return _err('new_code가 필요해요.', 400)
    s = SessionLocal()
    try:
        src = s.query(Model).filter_by(model_code=code).first()
        if src is None:
            return _err('원본 모음전을 찾을 수 없어요.', 404)
        if s.query(Model).filter_by(model_code=new_code).first():
            return _err(f"'{new_code}' 코드는 이미 존재해요.", 409)
        cols = {c.name: getattr(src, c.name) for c in src.__table__.columns
                if c.name not in ('model_code', 'created_at', 'updated_at',
                                  'naver_product_id', 'coupang_product_id')}
        cols['model_code'] = new_code
        new_model = Model(**cols)
        s.add(new_model)
        # 옵션도 복제 (canonical_sku만 새 코드로 prefix)
        for o in s.query(Option).filter_by(model_code=code).all():
            ocols = {c.name: getattr(o, c.name) for c in o.__table__.columns
                     if c.name not in ('canonical_sku', 'model_code',
                                       'created_at', 'updated_at',
                                       'naver_option_id', 'coupang_option_id')}
            ocols['canonical_sku'] = o.canonical_sku.replace(code, new_code, 1) if code in o.canonical_sku \
                                     else f"{new_code}-{o.color_code}-{o.size_code}"
            ocols['model_code'] = new_code
            s.add(Option(**ocols))
        s.commit()
        return _ok(new_code=new_code)
    finally:
        s.close()


@bp.post('/bundles/<code>/delete')
def bundle_delete(code: str):
    """모음전 삭제 — 옵션·자식 행 전부 정리 후 모델 삭제.

    PostgreSQL 은 FK 를 항상 강제하므로, 자식 행(bundle_source_urls,
    bundle_option_steps, *_registrations, source_links 등)을 먼저 지우지 않으면
    models 삭제가 ForeignKeyViolation 으로 막혀 'internal_error' 가 났음.
    inventory_product_delete 와 동일하게 각 DELETE 를 SAVEPOINT 로 격리해
    한 문(테이블 부재 등)이 실패해도 트랜잭션이 abort 되지 않게 한다.
    """
    from sqlalchemy import text, bindparam
    s = SessionLocal()

    def _safe(stmt, params):
        sp = s.begin_nested()
        try:
            s.execute(stmt, params)
            sp.commit()
        except Exception:
            sp.rollback()

    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)

        skus = [r[0] for r in s.execute(
            text("SELECT canonical_sku FROM options WHERE model_code = :c"),
            {"c": code}).fetchall()]

        # 1) 옵션(canonical_sku)을 가리키는 자식 행 정리
        if skus:
            in_skus = lambda: bindparam("skus", expanding=True)
            for tbl, col in (
                ("etc_source_urls", "canonical_sku"),
                ("price_track_history", "canonical_sku"),
                ("market_registrations", "canonical_sku"),
                ("option_source_links", "canonical_sku"),
                ("option_account_registrations", "canonical_sku"),
                ("option_benefit_overrides", "canonical_sku"),
                ("option_source_url_links", "option_canonical_sku"),
            ):
                _safe(text(f"DELETE FROM {tbl} WHERE {col} IN :skus")
                      .bindparams(in_skus()), {"skus": skus})
            # 양방향(옵션이 매핑 양쪽에 올 수 있음) 정리
            _safe(text("DELETE FROM option_product_links "
                       "WHERE option_canonical_sku IN :skus "
                       "OR product_canonical_sku IN :skus")
                  .bindparams(in_skus()), {"skus": skus})
            _safe(text("DELETE FROM option_inventory_links "
                       "WHERE bundle_option_sku IN :skus "
                       "OR inventory_option_sku IN :skus")
                  .bindparams(in_skus()), {"skus": skus})

        # 2) 모델(model_code)을 가리키는 자식 행 정리
        for tbl in ("bundle_account_registrations", "model_source_links",
                    "bundle_source_urls", "bundle_option_steps", "combo_sets"):
            _safe(text(f"DELETE FROM {tbl} WHERE model_code = :c"), {"c": code})

        # 3) 옵션 → 모델 순서로 삭제
        _safe(text("DELETE FROM options WHERE model_code = :c"), {"c": code})
        s.execute(text("DELETE FROM models WHERE model_code = :c"), {"c": code})
        s.commit()
        return _ok(deleted_code=code)
    except Exception as e:
        s.rollback()
        return _err(f'삭제 실패: {e}', 500)
    finally:
        s.close()


# ---------- DLQ 전체 재시도 ----------

@bp.post('/dlq/retry-all')
def dlq_retry_all():
    from lemouton.uploader.orchestrator import run_uploader
    s = SessionLocal()
    try:
        from lemouton.uploader.models import MarketRegistration
        items = s.query(MarketRegistration).filter_by(status='failed').all()
        count = len(items)
    finally:
        s.close()
    try:
        run_uploader(dry_run=False)
    except Exception as e:
        return _err(f'재시도 실패: {e}', 500)
    return _ok(count=count)


# ---------- Templates 보조 (복제/삭제) ----------

@bp.post('/templates/price/<int:tid>/duplicate')
def price_template_duplicate(tid: int):
    s = SessionLocal()
    try:
        src = s.query(PriceTemplate).filter_by(id=tid).first()
        if src is None:
            return _err('템플릿을 찾을 수 없어요.', 404)
        cols = {c.name: getattr(src, c.name) for c in src.__table__.columns
                if c.name not in ('id', 'created_at', 'updated_at')}
        cols['name'] = (src.name or '템플릿') + ' (복제)'
        new = PriceTemplate(**cols)
        s.add(new); s.commit()
        return _ok(id=new.id, name=new.name)
    finally:
        s.close()


@bp.post('/templates/price/<int:tid>/delete')
def price_template_delete(tid: int):
    s = SessionLocal()
    try:
        t = s.query(PriceTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('템플릿을 찾을 수 없어요.', 404)
        # 사용 중인지 확인
        in_use = s.query(Model).filter(
            (Model.price_template_id == tid)
            | (Option.price_template_id_override == tid)
        ).count()
        if in_use:
            return _err(f'사용 중인 템플릿은 삭제할 수 없어요 ({in_use}개 모음전·옵션 적용 중).', 409)
        s.delete(t); s.commit()
        return _ok(deleted_id=tid)
    finally:
        s.close()


# ---------- 가격 템플릿 GET (편집 모달용) ----------

@bp.get('/templates/price/<int:tid>')
def price_template_get(tid: int):
    s = SessionLocal()
    try:
        t = s.query(PriceTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('템플릿을 찾을 수 없어요.', 404)
        return _ok(template={c.name: getattr(t, c.name)
                             for c in t.__table__.columns
                             if c.name not in ('created_at', 'updated_at',
                                               'deleted_at')})
    finally:
        s.close()


@bp.get('/templates/price/product-search')
def price_template_product_search():
    """가격 템플릿용 제품(모델) 검색 → 평균 매입가 자동 불러오기.

    ?q= 검색어 (모델 코드·모델명). 매칭된 모델별로 옵션 boxhero_avg_purchase_price
    평균 (>0 만 집계) 을 100원 단위 반올림해 반환.
    응답: {ok, items:[{model_code, name, brand, avg_purchase_price, option_count}]}
    """
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    if not q:
        return _ok(q=q, items=[])
    s = SessionLocal()
    try:
        query = s.query(Model.model_code, Model.model_name_display, Model.brand)
        query = apply_and_filter(
            query, split_tokens(q),
            Model.model_code, Model.model_name_raw, Model.model_name_display,
            op='ilike',
        )
        items = []
        for code, name, brand in query.limit(20).all():
            prices = [
                p for (p,) in s.query(Option.boxhero_avg_purchase_price)
                .filter(Option.model_code == code).all()
                if p and p > 0
            ]
            avg = round(sum(prices) / len(prices) / 100) * 100 if prices else 0
            items.append({
                'model_code': code,
                'name': name or code,
                'brand': brand or '',
                'avg_purchase_price': avg,
                'option_count': len(prices),
            })
    finally:
        s.close()
    return _ok(q=q, items=items)


# ---------- 색상 템플릿 CRUD ----------

@bp.get('/templates/color/<int:tid>')
def color_template_get(tid: int):
    s = SessionLocal()
    try:
        t = s.query(ColorTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('색상 템플릿을 찾을 수 없어요.', 404)
        codes = []
        try:
            codes = json.loads(t.color_codes_json or '[]')
        except Exception:
            codes = []
        return _ok(template={'id': t.id, 'name': t.name,
                             'color_codes': codes, 'note': t.note})
    finally:
        s.close()


@bp.post('/templates/color')
def color_template_upsert():
    payload = request.get_json(silent=True) or {}
    tpl_id = payload.get('id')
    name = (payload.get('name') or '').strip()
    color_codes = payload.get('color_codes') or []
    if not name and not tpl_id:
        return _err('name 이 필요해요.', 400)
    if not isinstance(color_codes, list):
        return _err('color_codes 는 list 여야 해요.', 400)
    s = SessionLocal()
    try:
        if tpl_id:
            t = s.query(ColorTemplate).filter_by(id=tpl_id).first()
            if t is None:
                return _err('색상 템플릿을 찾을 수 없어요.', 404)
        else:
            t = ColorTemplate(name=name, color_codes_json='[]')
            s.add(t)
        if name:
            t.name = name
        if color_codes is not None:
            t.color_codes_json = json.dumps(color_codes, ensure_ascii=False)
        if 'note' in payload:
            t.note = payload.get('note')
        s.commit()
        return _ok(id=t.id, name=t.name)
    finally:
        s.close()


@bp.post('/templates/color/<int:tid>/duplicate')
def color_template_duplicate(tid: int):
    s = SessionLocal()
    try:
        src = s.query(ColorTemplate).filter_by(id=tid).first()
        if src is None:
            return _err('색상 템플릿을 찾을 수 없어요.', 404)
        new = ColorTemplate(name=(src.name or '색상 템플릿') + ' (복제)',
                            color_codes_json=src.color_codes_json,
                            note=src.note)
        s.add(new); s.commit()
        return _ok(id=new.id, name=new.name)
    finally:
        s.close()


@bp.post('/templates/color/<int:tid>/delete')
def color_template_delete(tid: int):
    s = SessionLocal()
    try:
        t = s.query(ColorTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('색상 템플릿을 찾을 수 없어요.', 404)
        in_use = s.query(Model).filter(Model.color_template_id == tid).count()
        if in_use:
            return _err(f'사용 중인 템플릿은 삭제할 수 없어요 ({in_use}개 모음전 적용 중).', 409)
        s.delete(t); s.commit()
        return _ok(deleted_id=tid)
    finally:
        s.close()


# ---------- 사이즈 템플릿 CRUD ----------

@bp.get('/templates/size/<int:tid>')
def size_template_get(tid: int):
    s = SessionLocal()
    try:
        t = s.query(SizeTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('사이즈 템플릿을 찾을 수 없어요.', 404)
        codes = []
        try:
            codes = json.loads(t.size_codes_json or '[]')
        except Exception:
            codes = []
        return _ok(template={'id': t.id, 'name': t.name,
                             'category': t.category,
                             'size_codes': codes, 'note': t.note})
    finally:
        s.close()


@bp.post('/templates/size')
def size_template_upsert():
    payload = request.get_json(silent=True) or {}
    tpl_id = payload.get('id')
    name = (payload.get('name') or '').strip()
    category = (payload.get('category') or '신발').strip()
    size_codes = payload.get('size_codes') or []
    if not name and not tpl_id:
        return _err('name 이 필요해요.', 400)
    if not isinstance(size_codes, list):
        return _err('size_codes 는 list 여야 해요.', 400)
    s = SessionLocal()
    try:
        if tpl_id:
            t = s.query(SizeTemplate).filter_by(id=tpl_id).first()
            if t is None:
                return _err('사이즈 템플릿을 찾을 수 없어요.', 404)
        else:
            t = SizeTemplate(name=name, category=category,
                             size_codes_json='[]')
            s.add(t)
        if name:
            t.name = name
        if 'category' in payload:
            t.category = payload.get('category')
        if size_codes is not None:
            t.size_codes_json = json.dumps(size_codes, ensure_ascii=False)
        if 'note' in payload:
            t.note = payload.get('note')
        s.commit()
        return _ok(id=t.id, name=t.name)
    finally:
        s.close()


@bp.post('/templates/size/<int:tid>/duplicate')
def size_template_duplicate(tid: int):
    s = SessionLocal()
    try:
        src = s.query(SizeTemplate).filter_by(id=tid).first()
        if src is None:
            return _err('사이즈 템플릿을 찾을 수 없어요.', 404)
        new = SizeTemplate(name=(src.name or '사이즈 템플릿') + ' (복제)',
                           category=src.category,
                           size_codes_json=src.size_codes_json,
                           note=src.note)
        s.add(new); s.commit()
        return _ok(id=new.id, name=new.name)
    finally:
        s.close()


@bp.post('/templates/size/<int:tid>/delete')
def size_template_delete(tid: int):
    s = SessionLocal()
    try:
        t = s.query(SizeTemplate).filter_by(id=tid).first()
        if t is None:
            return _err('사이즈 템플릿을 찾을 수 없어요.', 404)
        in_use = s.query(Model).filter(Model.size_template_id == tid).count()
        if in_use:
            return _err(f'사용 중인 템플릿은 삭제할 수 없어요 ({in_use}개 모음전 적용 중).', 409)
        s.delete(t); s.commit()
        return _ok(deleted_id=tid)
    finally:
        s.close()


# ---------- 색상 사전 (ColorDict) CRUD ----------

@bp.get('/dict/color/<code>')
def color_dict_get(code: str):
    from lemouton.sourcing.models import ColorDict
    s = SessionLocal()
    try:
        c = s.query(ColorDict).filter_by(color_code=code).first()
        if c is None:
            return _err('색상 사전 항목을 찾을 수 없어요.', 404)
        variants = []
        try:
            variants = json.loads(c.variants_json or '[]')
        except Exception:
            variants = []
        return _ok(item={'color_code': c.color_code,
                         'variants': variants, 'note': c.note})
    finally:
        s.close()


@bp.post('/dict/color')
def color_dict_upsert():
    """색상 사전 신규/편집 — Body: {color_code, variants:[...], note?, original_code?}"""
    from lemouton.sourcing.models import ColorDict
    payload = request.get_json(silent=True) or {}
    code = (payload.get('color_code') or '').strip()
    variants = payload.get('variants') or []
    original_code = (payload.get('original_code') or '').strip() or None
    if not code:
        return _err('color_code 가 필요해요.', 400)
    if not isinstance(variants, list):
        return _err('variants 는 list 여야 해요.', 400)
    s = SessionLocal()
    try:
        # 편집 모드 (original_code 있으면 그것 기준)
        target = original_code or code
        existing = s.query(ColorDict).filter_by(color_code=target).first()
        if existing:
            if original_code and original_code != code:
                # 코드 변경 — 새 코드 중복 검사
                if s.query(ColorDict).filter_by(color_code=code).first():
                    return _err(f"'{code}' 가 이미 존재해요.", 409)
                existing.color_code = code
            existing.variants_json = json.dumps(variants, ensure_ascii=False)
            if 'note' in payload:
                existing.note = payload.get('note')
        else:
            c = ColorDict(color_code=code,
                          variants_json=json.dumps(variants, ensure_ascii=False),
                          note=payload.get('note'))
            s.add(c)
        s.commit()
        return _ok(color_code=code)
    finally:
        s.close()


@bp.post('/dict/color/<code>/delete')
def color_dict_delete(code: str):
    from lemouton.sourcing.models import ColorDict
    s = SessionLocal()
    try:
        c = s.query(ColorDict).filter_by(color_code=code).first()
        if c is None:
            return _err('색상 사전 항목을 찾을 수 없어요.', 404)
        s.delete(c); s.commit()
        return _ok(deleted_code=code)
    finally:
        s.close()


# ---------- 색상·사이즈 조합 (ComboSet) + 옵션 자동 생성 ----------

@bp.get('/bundles/<code>/combos/<int:cid>')
def combo_get(code: str, cid: int):
    from lemouton.templates.models import ComboSet
    s = SessionLocal()
    try:
        c = s.query(ComboSet).filter_by(id=cid, model_code=code).first()
        if c is None:
            return _err('조합을 찾을 수 없어요.', 404)
        return _ok(combo={
            'id': c.id, 'name': c.name,
            'colors': json.loads(c.color_codes_json or '[]'),
            'sizes': json.loads(c.size_codes_json or '[]'),
        })
    finally:
        s.close()


def _build_canonical_sku(code: str, color: str, size: str) -> str:
    return f"{code}-{color}-{size}"


@bp.post('/bundles/<code>/combos')
def combo_upsert(code: str):
    """조합 신규/편집 — Body: {id?, name?, colors:[...], sizes:[...]}.

    저장 후 옵션 매트릭스 자동 동기화:
      - color × size cartesian → Option 자동 INSERT (없는 것만)
      - 콤보 삭제 시 옵션 삭제는 별도 endpoint 에서 처리
    """
    from lemouton.templates.models import ComboSet
    payload = request.get_json(silent=True) or {}
    cid = payload.get('id')
    colors = payload.get('colors') or []
    sizes = payload.get('sizes') or []
    name = (payload.get('name') or '').strip()
    if not isinstance(colors, list) or not isinstance(sizes, list):
        return _err('colors/sizes 는 list 여야 해요.', 400)
    if not colors or not sizes:
        return _err('colors 와 sizes 모두 1개 이상 필요해요.', 400)
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        if cid:
            c = s.query(ComboSet).filter_by(id=cid, model_code=code).first()
            if c is None:
                return _err('조합을 찾을 수 없어요.', 404)
        else:
            c = ComboSet(model_code=code, name=name or None,
                         color_codes_json='[]', size_codes_json='[]')
            s.add(c); s.flush()
        c.color_codes_json = json.dumps(colors, ensure_ascii=False)
        c.size_codes_json = json.dumps(sizes, ensure_ascii=False)
        if name:
            c.name = name

        # 옵션 자동 동기화 — color × size cartesian
        existing_skus = {o.canonical_sku for o in
                         s.query(Option).filter_by(model_code=code).all()}
        added = 0
        for color in colors:
            for size in sizes:
                sku = _build_canonical_sku(code, color, size)
                if sku in existing_skus:
                    continue
                opt = Option(canonical_sku=sku, model_code=code,
                             color_code=color, size_code=size)
                s.add(opt); added += 1
        s.commit()
        return _ok(combo_id=c.id, options_created=added)
    finally:
        s.close()


@bp.post('/bundles/<code>/combos/<int:cid>/delete')
def combo_delete(code: str, cid: int):
    """조합 삭제 — 해당 색상·사이즈의 옵션도 함께 정리할지 별도 결정.

    Body: {remove_options: bool}  default false
    """
    from lemouton.templates.models import ComboSet
    payload = request.get_json(silent=True) or {}
    remove_options = bool(payload.get('remove_options', False))
    s = SessionLocal()
    try:
        c = s.query(ComboSet).filter_by(id=cid, model_code=code).first()
        if c is None:
            return _err('조합을 찾을 수 없어요.', 404)
        removed_opts = 0
        if remove_options:
            colors = set(json.loads(c.color_codes_json or '[]'))
            sizes = set(json.loads(c.size_codes_json or '[]'))
            opts = (s.query(Option).filter_by(model_code=code).all())
            for o in opts:
                if o.color_code in colors and o.size_code in sizes:
                    s.delete(o); removed_opts += 1
        s.delete(c); s.commit()
        return _ok(deleted_id=cid, options_removed=removed_opts)
    finally:
        s.close()


# ---------- 박스히어로 동기화 ----------

@bp.post('/boxhero/sync')
def boxhero_sync():
    """박스히어로 API 토큰이 있으면 한 번 가져와 옵션 stock 갱신."""
    import os
    if not os.environ.get('BOXHERO_API_TOKEN'):
        return _err('BOXHERO_API_TOKEN이 .env에 없어요.', 400)
    try:
        from lemouton.sourcing.boxhero_api import fetch_records
        from lemouton.sourcing.boxhero_service import sync_boxhero_to_options
    except ImportError as e:
        return _err(f'박스히어로 모듈 로드 실패: {e}', 500)
    s = SessionLocal()
    try:
        try:
            records = fetch_records()
        except Exception as e:
            return _err(f'API 호출 실패: {e}', 502)
        synced = sync_boxhero_to_options(s, records)
        s.commit()
    finally:
        s.close()
    return _ok(synced=len(synced) if hasattr(synced, '__len__') else 0)


# ---------- 스케줄러 제어 ----------

@bp.post('/scheduler/run-now')
def scheduler_run_now():
    """홈 '지금 바로 실행' — 백그라운드로 full_cycle 트리거."""
    # [크롤=로컬 원칙] 서버 직접 크롤은 기본 OFF — full_cycle Phase A(서버 크롤) 차단.
    from lemouton.sourcing.server_crawl_gate import server_crawl_enabled, DISABLED_MESSAGE
    if not server_crawl_enabled():
        return _ok(triggered=False, server_crawl_disabled=True, message=DISABLED_MESSAGE)
    try:
        from scheduler.main import get_scheduler
        from scheduler.jobs import full_cycle
        sched = get_scheduler()
        if sched.running:
            sched.add_job(full_cycle, id='manual_run',
                          replace_existing=True, max_instances=1)
        else:
            # 스케줄러 미가동 시 동기 실행 (테스트/디버그)
            full_cycle(dry_run=False)
    except Exception as e:
        return _err(f'트리거 실패: {e}', 500)
    return _ok(triggered=True)


@bp.post('/scheduler/pause')
def scheduler_pause():
    try:
        from scheduler.main import get_scheduler
        sched = get_scheduler()
        if not sched.running:
            return _ok(paused=False, note='스케줄러 미가동')
        if sched.state == 2:  # PAUSED
            sched.resume()
            return _ok(paused=False)
        sched.pause()
        return _ok(paused=True)
    except Exception as e:
        return _err(f'토글 실패: {e}', 500)


# ---------- 모음전 단위 즉시 실행 (지금 전체 / 크롤 / 업로드) ----------

@bp.post('/bundles/<code>/test-crawl-single')
def test_crawl_single(code: str):
    """[빠른 path] 단일 소싱처 크롤링 시연 — 정보수집 입증.

    body: {source: 'lemouton'|'musinsa'|'ssf'|'lotteon'} (default: lemouton)
    Returns: {source, product_name, options: [{color, size, price, stock}, ...]}
    """
    payload = request.get_json(silent=True) or {}
    source = payload.get('source', 'lemouton')
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if not m:
            return _err('모음전 없음', 404)
        url_attr = f"url_{source}"
        url = getattr(m, url_attr, None)
        if not url:
            return _err(f'{source} URL 미입력 (§2)', 400)

        # crawler dispatch
        if source == 'lemouton':
            from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
            crawler = LemoutonCrawler(prefer_playwright=True)
        elif source == 'musinsa':
            from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
            crawler = MusinsaCrawler()
        elif source == 'ssf':
            from lemouton.sourcing.crawlers.ssf import SsfCrawler
            crawler = SsfCrawler()
        elif source == 'lotteon':
            from lemouton.sourcing.crawlers.lotteon import LotteCrawler
            crawler = LotteCrawler()
        else:
            return _err(f'unsupported source: {source}', 400)

        try:
            result = crawler.fetch(url)
        except Exception as e:
            return _err(f'crawl 실패: {type(e).__name__}: {e}', 500)

        # 색상 매칭 디버그 + SSF 36개 매트릭스 보강 + PriceTrackHistory 저장
        color_mapping = _build_color_mapping(s, code, result)
        if result.source == 'ssf':
            _augment_ssf_to_full_matrix(s, code, result, color_mapping)
        saved_count = _save_crawl_to_track(s, code, result)

        return _ok(
            source=result.source,
            product_name=result.product_name_raw,
            options_count=len(result.options),
            saved_to_history=saved_count,
            color_mapping=color_mapping,
            options=[{
                'color_text': o.get('color_text'),
                'size_text': o.get('size_text'),
                'price': o.get('price'),
                'stock': o.get('stock'),
            } for o in result.options],
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/recrawl-url')
def recrawl_single_url(code: str):
    """[2026-06-13] 단일 등록 URL 재크롤 — 옵션 모달의 🔄 재크롤 버튼용.

    body: {source_key, url}
    서버사이드 HTTP 크롤러(ssf·ssg·lemouton·smartstore)는 즉시 크롤·저장 후 결과 반환.
    무신사·롯데온은 서버에 브라우저가 없어 status='need_extension' 반환
      → 프론트가 크롬 확장(MoumExt)으로 크롤하게 안내.

    Returns: {ok, crawl_ok, status, price, stock, options_count, product_name, error}
    """
    from lemouton.sources.service import upsert_source_product, fetch_one_source
    from lemouton.sourcing.crawlers import build_crawlers
    payload = request.get_json(silent=True) or {}
    source_key = (payload.get('source_key') or '').strip()
    url = (payload.get('url') or '').strip()
    if not source_key or not url:
        return _err('source_key·url 필요', 400)
    s = SessionLocal()
    try:
        crawlers = build_crawlers()
        sp = upsert_source_product(s, site=source_key, url=url)
        # [2026-06-20 money-safe] SSG 딜(dealItemView)은 자동 대표상품 크롤 금지(광고상품 오긁음).
        #   잔여(이전 대표상품=무관 광고상품) 데이터 정리 + '모델 선택 필요' 표시.
        if 'dealitemview' in (url or '').lower():
            from lemouton.sources.models import SourceOption as _SO
            from datetime import datetime as _dt, timezone as _tz
            _now = _dt.now(_tz.utc)
            sp.product_name = None
            sp.last_price = None
            sp.last_stock = None
            sp.last_status = 'deal_needs_model'
            sp.last_error_msg = '딜 페이지 — 모델 선택으로 단일 itemView URL 지정 필요(자동 대표상품 금지)'
            sp.last_fetched_at = _now
            _n = 0
            for _so in s.query(_SO).filter(_SO.source_product_id == sp.id,
                                           _SO.deleted_at.is_(None)).all():
                _so.deleted_at = _now
                _n += 1
            s.commit()
            return _ok(crawl_ok=False, status='deal_needs_model', options_count=0,
                       product_name=None, cleared_options=_n,
                       error='딜 페이지 — 모델 선택 필요(잔여 데이터 정리됨)')
        r = fetch_one_source(s, source_product_id=sp.id, crawlers=crawlers)
        st = r.get('status')
        if st == 'skipped_no_browser':
            # 서버에 브라우저 없음 — 무신사·롯데온은 크롬 확장으로 크롤해야 함
            s.rollback()
            return _ok(crawl_ok=False, status='need_extension',
                       error='이 소싱처는 로그인 브라우저(크롬 확장)로 크롤합니다')
        s.commit()
        cr = r.get('crawl_result')
        return _ok(
            crawl_ok=(st == 'ok'),
            status=st,
            price=getattr(sp, 'last_price', None),
            stock=getattr(sp, 'last_stock', None),
            options_count=(len(getattr(cr, 'options', []) or []) if cr else 0),
            product_name=(getattr(cr, 'product_name_raw', None) if cr else None),
            error=r.get('error'),
        )
    except Exception as e:
        try:
            s.rollback()
        except Exception:
            pass
        return _err(f'재크롤 실패: {type(e).__name__}: {e}', 500)
    finally:
        s.close()



def _build_color_mapping(s, model_code: str, result) -> dict:
    """소싱처 raw color_text → 우리 color_code 매핑 결과 (사용자 검증용).

    Returns:
        {
            'raw_colors': [...]                    # 소싱처가 노출한 색상명 (중복 제거)
            'our_colors': [...]                    # 우리 매트릭스 색상
            'mapping': [{raw, matched_our, method}, ...]
            'unmatched_raw': [...]
            'unmatched_our': [...]
        }
    """
    import json as _json
    from lemouton.sourcing.models import Option, ColorDict

    our_options = s.query(Option).filter_by(model_code=model_code).all()
    our_colors_set: list[str] = []
    seen: set[str] = set()
    for opt in our_options:
        cc = (opt.color_code or '').strip()
        if cc and cc not in seen:
            seen.add(cc)
            our_colors_set.append(cc)

    cdicts: dict[str, list[str]] = {}
    for c in s.query(ColorDict).all():
        try:
            variants = _json.loads(c.variants_json or '[]')
            cdicts[c.color_code.lower()] = [v.lower() for v in variants]
        except Exception:
            pass

    raw_colors_set: list[str] = []
    seen_r: set[str] = set()
    for raw in (result.options or []):
        rc = (raw.get('color_text') or '').strip()
        if rc and rc not in seen_r:
            seen_r.add(rc)
            raw_colors_set.append(rc)

    mapping: list[dict] = []
    matched_our: set[str] = set()
    for raw in raw_colors_set:
        raw_low = raw.lower()
        raw_ns = raw_low.replace(' ', '')  # 공백 무시 비교
        chosen: str | None = None
        method: str = ''
        # 1단: 직접 부분 매칭 (공백 무시)
        for oc in our_colors_set:
            ol = oc.lower().replace(' ', '')
            if ol in raw_ns or raw_ns in ol:
                chosen = oc
                method = 'direct (부분일치)'
                break
        # 2단: 색상 사전 variants (공백 무시)
        if not chosen:
            for oc in our_colors_set:
                for v in cdicts.get(oc.lower(), []):
                    if v and v.replace(' ', '') in raw_ns:
                        chosen = oc
                        method = f'color_dict variant: "{v}"'
                        break
                if chosen:
                    break
        if chosen:
            matched_our.add(chosen)
        mapping.append({'raw': raw, 'matched_our': chosen, 'method': method})

    unmatched_raw = [m['raw'] for m in mapping if not m['matched_our']]
    unmatched_our = [oc for oc in our_colors_set if oc not in matched_our]

    return {
        'raw_colors': raw_colors_set,
        'our_colors': our_colors_set,
        'mapping': mapping,
        'unmatched_raw': unmatched_raw,
        'unmatched_our': unmatched_our,
    }


def _augment_ssf_to_full_matrix(s, model_code: str, result, color_mapping: dict) -> int:
    """SSF 누락 사이즈 자동 보강 — 우리 36개 매트릭스 전체로 result.options 확장.

    SSF 가 색상별로 일부 사이즈만 노출 (단종/미입고) — 누락 (색,사) 조합에
    같은 색상의 가격 + stock=0 으로 채워 36개 매트릭스 완성.
    """
    from lemouton.sourcing.models import Option

    our_options = s.query(Option).filter_by(model_code=model_code).all()
    if not our_options:
        return 0

    # raw → our_color 역매핑 (사이즈 매칭에 사용)
    raw_to_our: dict[str, str] = {}
    for entry in color_mapping.get('mapping', []):
        if entry['matched_our']:
            raw_to_our[entry['raw']] = entry['matched_our']

    # 같은 색상의 raw 옵션 그루핑 (sale_price 채워 넣을 fallback 후보)
    by_our_color: dict[str, list[dict]] = {}
    existing_keys: set[tuple[str, str]] = set()  # (our_color, size_digits)
    for raw in (result.options or []):
        ct = (raw.get('color_text') or '').strip()
        oc = raw_to_our.get(ct)
        if not oc:
            continue
        by_our_color.setdefault(oc, []).append(raw)
        size_digits = ''.join(ch for ch in (raw.get('size_text') or '') if ch.isdigit())
        if size_digits:
            existing_keys.add((oc, size_digits))

    # 우리 매트릭스 36개 순회 → 누락 보강
    added = 0
    for opt in our_options:
        our_c = (opt.color_code or '').strip()
        our_s = (opt.size_code or '').strip()
        if not our_c or not our_s:
            continue
        if (our_c, our_s) in existing_keys:
            continue
        # 같은 색상의 첫 raw에서 가격 차용
        candidates = by_our_color.get(our_c, [])
        if not candidates:
            continue
        ref = candidates[0]
        # 보강 raw 추가 — color_text 는 raw 그대로 (매칭 시 동일하게 처리됨)
        result.options.append({
            'option_id': f'{our_c}|{our_s}|augmented',
            'color_text': ref.get('color_text'),
            'size_text': f'{our_s}mm',
            'price': ref.get('price'),
            'sale_price': ref.get('sale_price'),
            'stock': 0,  # 단종 — 노출되지 않은 사이즈
            '_augmented': True,
        })
        added += 1
    return added


def _save_crawl_to_track(s, model_code: str, result) -> int:
    """crawl 결과 → PriceTrackHistory 저장. 우리 Option 과 색상/사이즈 매칭. 저장 건수 반환."""
    import json as _json
    from lemouton.sourcing.models import Option, ColorDict
    from lemouton.templates.models import PriceTrackHistory

    our_options = s.query(Option).filter_by(model_code=model_code).all()
    if not our_options:
        return 0

    # 색상 사전: color_code → list of variants (소문자)
    cdicts: dict = {}
    for c in s.query(ColorDict).all():
        try:
            variants = _json.loads(c.variants_json or '[]')
            cdicts[c.color_code.lower()] = [v.lower() for v in variants]
        except Exception:
            pass

    saved = 0
    for raw in (result.options or []):
        c_text = (raw.get('color_text') or '').strip().lower()
        s_text = (raw.get('size_text') or '').strip()
        # 사이즈 정규화: '230mm' / '230 mm' / '230' → '230'
        s_norm = ''.join(ch for ch in s_text if ch.isdigit())
        if not s_norm:
            continue

        # 공백 무시 — '올리브 그린'(소싱처) == '올리브그린'(우리)
        c_text_ns = c_text.replace(' ', '')
        matched = None
        for our in our_options:
            if (our.size_code or '').strip() != s_norm:
                continue
            our_color = (our.color_code or '').strip().lower()
            if not our_color:
                continue
            our_color_ns = our_color.replace(' ', '')
            # 직접 부분 매칭 (양방향, 공백 무시)
            if our_color_ns in c_text_ns or c_text_ns in our_color_ns:
                matched = our
                break
            # 색상 사전 variants 매칭 (공백 무시)
            for variant in cdicts.get(our_color, []):
                v = (variant or '').replace(' ', '')
                if v and v in c_text_ns:
                    matched = our
                    break
            if matched:
                break

        if matched:
            s.add(PriceTrackHistory(
                canonical_sku=matched.canonical_sku,
                source=result.source,
                price=raw.get('price'),
                stock=raw.get('stock'),
            ))
            saved += 1

    if saved:
        s.commit()
    return saved


def _resolve_models_for_code(s, code: str):
    """[v3 시나리오 C] code 가 model_code 또는 group_code 인지 판별 → 대상 Model list 반환."""
    from lemouton.sourcing.models import BundleGroup
    m = s.query(Model).filter_by(model_code=code).first()
    if m:
        # 같은 그룹의 형제 모델들 모두 포함 (1 모음전 N 모델)
        if m.bundle_group_id:
            grp = s.query(BundleGroup).filter_by(id=m.bundle_group_id).first()
            if grp:
                return list(grp.models)
        return [m]
    grp = s.query(BundleGroup).filter_by(group_code=code).first()
    if grp:
        return list(grp.models)
    return []


@bp.get('/bundle-groups')
def list_bundle_groups():
    """[v3] 그룹 목록 + 각 그룹 안 모델 list."""
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        groups = s.query(BundleGroup).filter_by(is_active=True).order_by(BundleGroup.id).all()
        items = []
        for g in groups:
            items.append({
                'id': g.id,
                'group_code': g.group_code,
                'group_name': g.group_name,
                'brand': g.brand,
                'category': g.category,
                'description': g.description,
                'model_count': len(g.models),
                'models': [{'model_code': m.model_code,
                            'model_name_display': m.model_name_display,
                            'naver_product_id': m.naver_product_id} for m in g.models],
            })
        return _ok(items=items)
    finally:
        s.close()


@bp.post('/bundle-groups')
def create_bundle_group():
    """[v3] 그룹 신규 생성 + 모델 매핑.
    Body: {group_code, group_name, brand, category, model_codes: [...]}"""
    from lemouton.sourcing.models import BundleGroup
    payload = request.get_json(silent=True) or {}
    code = (payload.get('group_code') or '').strip()
    name = (payload.get('group_name') or '').strip()
    if not code or not name:
        return _err('group_code 와 group_name 필수', 400)
    s = SessionLocal()
    try:
        if s.query(BundleGroup).filter_by(group_code=code).first():
            return _err(f"group_code '{code}' 이미 존재", 409)
        g = BundleGroup(
            group_code=code, group_name=name,
            brand=payload.get('brand'), category=payload.get('category'),
            description=payload.get('description'),
        )
        s.add(g)
        s.flush()
        # 모델 매핑
        for mc in payload.get('model_codes') or []:
            m = s.query(Model).filter_by(model_code=mc).first()
            if m:
                m.bundle_group_id = g.id
        s.commit()
        return _ok(id=g.id, group_code=g.group_code,
                   model_count=len(payload.get('model_codes') or []))
    finally:
        s.close()


@bp.post('/bundle-groups/<int:gid>/add-model')
def add_model_to_group(gid: int):
    """[v3] 그룹에 기존 Model 추가."""
    from lemouton.sourcing.models import BundleGroup
    payload = request.get_json(silent=True) or {}
    mc = (payload.get('model_code') or '').strip()
    if not mc:
        return _err('model_code 필수', 400)
    s = SessionLocal()
    try:
        g = s.query(BundleGroup).filter_by(id=gid).first()
        if not g:
            return _err('그룹 없음', 404)
        m = s.query(Model).filter_by(model_code=mc).first()
        if not m:
            return _err(f"model_code '{mc}' 없음", 404)
        m.bundle_group_id = gid
        s.commit()
        return _ok(model_code=mc, group_id=gid)
    finally:
        s.close()


@bp.post('/bundle-groups/<int:gid>/remove-model')
def remove_model_from_group(gid: int):
    """[v3] 그룹에서 모델 분리 — 자기 자신 group 으로 복원 (없으면 신규 생성).

    Body: {model_code}
    """
    from lemouton.sourcing.models import BundleGroup
    payload = request.get_json(silent=True) or {}
    mc = (payload.get('model_code') or '').strip()
    if not mc:
        return _err('model_code 필수', 400)
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=mc).first()
        if not m:
            return _err(f"model_code '{mc}' 없음", 404)
        if m.bundle_group_id != gid:
            return _err(f"model '{mc}' 는 group #{gid} 소속 아님", 400)
        # 자기 자신 group_code 로 자동 복원 (모델별 단독 모음전)
        own = s.query(BundleGroup).filter_by(group_code=mc).first()
        if not own:
            own = BundleGroup(group_code=mc, group_name=mc, brand=m.brand,
                              category=m.category)
            s.add(own)
            s.flush()
        m.bundle_group_id = own.id
        s.commit()
        return _ok(model_code=mc, removed_from=gid, restored_to=own.id,
                   restored_group_code=own.group_code)
    finally:
        s.close()


@bp.post('/bundle-groups/<int:gid>/dissolve')
def dissolve_bundle_group(gid: int):
    """[v3] 그룹 해체 — 모든 멤버 모델을 자기 자신 group 으로 복원."""
    from lemouton.sourcing.models import BundleGroup
    s = SessionLocal()
    try:
        g = s.query(BundleGroup).filter_by(id=gid).first()
        if not g:
            return _err('그룹 없음', 404)
        moved = []
        for m in list(g.models):
            own = s.query(BundleGroup).filter_by(group_code=m.model_code).first()
            if not own:
                own = BundleGroup(group_code=m.model_code, group_name=m.model_code,
                                  brand=m.brand, category=m.category)
                s.add(own)
                s.flush()
            m.bundle_group_id = own.id
            moved.append({'model_code': m.model_code, 'restored_to': own.id})
        # 빈 그룹은 비활성화 (삭제 대신)
        g.is_active = False
        s.commit()
        return _ok(group_id=gid, dissolved=True, moved=moved)
    finally:
        s.close()


@bp.get('/bundle-groups/<int:gid>/option-config')
def get_bundle_option_config(gid: int):
    """[v3] 그룹의 마켓별 옵션 축 구성 조회."""
    from lemouton.sourcing.models import BundleGroup
    import json as _json
    s = SessionLocal()
    try:
        g = s.query(BundleGroup).filter_by(id=gid).first()
        if not g:
            return _err('그룹 없음', 404)
        cfg = {}
        if g.option_config_json:
            try:
                cfg = _json.loads(g.option_config_json)
            except Exception:
                cfg = {}
        return _ok(group_id=gid, group_code=g.group_code, option_config=cfg)
    finally:
        s.close()


@bp.post('/bundle-groups/<int:gid>/option-config')
def set_bundle_option_config(gid: int):
    """[v3] 그룹의 마켓별 옵션 축 구성 저장.

    Body: {"option_config": {"smartstore": {"axes": [{"name":"색상","source":"color_code"}, ...]}, "coupang": {...}}}
    검증:
      - 마켓별 axes 1~3개 (스스 최대 3, 쿠팡 최대 3)
      - axis.name 비어있지 않음
      - axis.source ∈ {color_code, size_code, model_code}
    """
    from lemouton.sourcing.models import BundleGroup
    import json as _json
    payload = request.get_json(silent=True) or {}
    cfg = payload.get('option_config') or {}
    valid_sources = {'color_code', 'size_code', 'model_code'}
    valid_markets = {'smartstore', 'coupang'}
    # 검증
    for mk, mk_cfg in cfg.items():
        if mk not in valid_markets:
            return _err(f'알 수 없는 마켓: {mk}', 400)
        axes = (mk_cfg or {}).get('axes') or []
        if not isinstance(axes, list) or not (1 <= len(axes) <= 3):
            return _err(f'{mk} axes 1~3개 필요 (받은 수: {len(axes)})', 400)
        names_seen = set()
        sources_seen = set()
        for i, ax in enumerate(axes):
            name = (ax or {}).get('name', '').strip()
            src = (ax or {}).get('source', '')
            if not name:
                return _err(f'{mk} axis #{i+1} name 비어있음', 400)
            if src not in valid_sources:
                return _err(f'{mk} axis #{i+1} source 잘못됨: {src}', 400)
            if name in names_seen:
                return _err(f'{mk} axis name 중복: {name}', 400)
            if src in sources_seen:
                return _err(f'{mk} axis source 중복: {src}', 400)
            names_seen.add(name); sources_seen.add(src)
    s = SessionLocal()
    try:
        g = s.query(BundleGroup).filter_by(id=gid).first()
        if not g:
            return _err('그룹 없음', 404)
        g.option_config_json = _json.dumps(cfg, ensure_ascii=False)
        s.commit()
        return _ok(group_id=gid, option_config=cfg)
    finally:
        s.close()


@bp.get('/bundle-groups/<int:gid>/option-payload-preview')
def get_option_payload_preview(gid: int):
    """[v3] axes config 로 생성될 마켓별 페이로드 미리보기.

    옵션 데이터(canonical_sku, color_code, size_code, model_code) 를 그룹의 모든 모델에서 모아
    option_axes.build_payloads_for_group 으로 마켓별 페이로드 생성. 신규 등록 전 검증용.
    """
    from lemouton.sourcing.models import BundleGroup
    from lemouton.formatter.option_axes import build_payloads_for_group
    import json as _json
    s = SessionLocal()
    try:
        g = s.query(BundleGroup).filter_by(id=gid).first()
        if not g:
            return _err('그룹 없음', 404)
        cfg = {}
        if g.option_config_json:
            try: cfg = _json.loads(g.option_config_json)
            except Exception: cfg = {}
        # 그룹의 모든 모델 옵션 수집
        model_codes = [m.model_code for m in g.models]
        opts = (s.query(Option)
                .filter(Option.model_code.in_(model_codes))
                .order_by(Option.model_code, Option.sort_order, Option.color_code, Option.size_code)
                .all()) if model_codes else []
        opt_dicts = [{
            'canonical_sku': o.canonical_sku,
            'color_code': o.color_code,
            'size_code': o.size_code,
            'model_code': o.model_code,
        } for o in opts]
        try:
            payloads = build_payloads_for_group(cfg, opt_dicts)
        except Exception as e:
            return _err(f'페이로드 빌드 실패: {e}', 400)
        return _ok(group_id=gid, option_count=len(opt_dicts),
                   option_config=cfg, payloads=payloads)
    finally:
        s.close()


# ═══════ [제품 공유 v1] 신규 모음전 — 재고제품 검색 + 모음전 생성 ═══════

@bp.get('/inventory/options/<path:sku>/stock-detail')
def inventory_option_stock_detail(sku: str):
    """[2026-05-25 UI-4] 옵션 재고 상세 — 옵션 트리 chip 클릭 modal 용.

    응답: {ok, per_location:[{name, qty}], recent_tx:[{created_at, tx_type, qty, memo}]}
    OptionProductLink 로 link 된 product sku 의 InventoryTx 합산.
    """
    from lemouton.inventory.models import InventoryLocation, InventoryTx, OptionProductLink
    from shared.inventory_stock import get_stock_batch
    s = SessionLocal()
    try:
        # 옵션 → product sku 해석 (link 우선, 없으면 자기 자신)
        link = s.query(OptionProductLink).filter_by(option_canonical_sku=sku).first()
        product_sku = link.product_canonical_sku if link else sku

        # 위치별 재고 (get_stock_batch 가 link 자동 해석)
        locs = (s.query(InventoryLocation)
                .filter(InventoryLocation.deleted_at.is_(None))
                .order_by(InventoryLocation.sort_order, InventoryLocation.id).all())
        per_location = []
        for l in locs:
            qty = get_stock_batch(s, [sku], location_id=l.id).get(sku, 0)
            per_location.append({'name': l.name, 'qty': qty})

        # 최근 거래 이력 (product sku 기준 — link 거친)
        txs = (s.query(InventoryTx)
               .filter(InventoryTx.option_canonical_sku == product_sku,
                       InventoryTx.status == 'completed')
               .order_by(InventoryTx.created_at.desc())
               .limit(20).all())
        recent_tx = [{
            'created_at': t.created_at.isoformat() if t.created_at else '',
            'tx_type': t.tx_type or '',
            'qty': int(t.qty or 0),
            'memo': t.memo or '',
        } for t in txs]

        return jsonify({'ok': True, 'per_location': per_location, 'recent_tx': recent_tx})
    finally:
        s.close()


@bp.get('/inventory/products/search')
def inventory_products_search():
    """재고제품 검색 → 모델별 그룹 (트리 아코디언 팝업용).

    ?q= 검색어 (품명·모델·브랜드·색·사이즈·바코드·SKU). 빈 검색이면 전체(상한 1000).
    응답: {ok, groups:[{model_code, brand, count, items:[{product_sku,name,color,size,stock}]}]}
    """
    from lemouton.inventory.models import InventoryProduct
    from shared.inventory_stock import get_stock_batch
    from shared.search import split_tokens, apply_and_filter
    q = (request.args.get('q') or '').strip()
    s = SessionLocal()
    try:
        query = s.query(InventoryProduct)
        query = apply_and_filter(
            query, split_tokens(q),
            InventoryProduct.canonical_sku, InventoryProduct.option_name,
            InventoryProduct.model_code, InventoryProduct.brand,
            InventoryProduct.color_code, InventoryProduct.size_code,
            InventoryProduct.barcode,
            op='ilike',
        )
        rows = (query.order_by(InventoryProduct.model_code,
                               InventoryProduct.color_code,
                               InventoryProduct.size_code)
                .limit(1000).all())
        stock = get_stock_batch(s, [r.canonical_sku for r in rows])
        groups: dict = {}
        for r in rows:
            key = r.model_code or '(미분류)'
            g = groups.setdefault(key, {
                'model_code': key, 'brand': r.brand or '', 'items': [],
            })
            g['items'].append({
                'product_sku': r.canonical_sku,
                'name': r.option_name or r.canonical_sku,
                'color': r.color_code or '',
                'size': r.size_code or '',
                'brand': r.brand or '',
                'barcode': r.barcode or '',
                'stock': stock.get(r.canonical_sku, 0),
            })
        out = []
        for g in groups.values():
            g['count'] = len(g['items'])
            out.append(g)
        return _ok(groups=out, total=len(rows))
    finally:
        s.close()


@bp.post('/inventory/compose-bundle')
def inventory_compose_bundle():
    """선택한 재고제품들로 신규 모음전(Model) + 옵션 생성.

    Body: {model_code, model_name_raw, brand, category, product_skus:[...]}
    각 재고제품 → Option 생성 + OptionProductLink(option→product) 연결 →
    그 재고제품을 쓰는 다른 모음전과 재고 자동 공유.
    """
    from lemouton.inventory.models import InventoryProduct, OptionProductLink
    body = request.get_json(silent=True) or {}
    code = (body.get('model_code') or '').strip()
    name = (body.get('model_name_raw') or '').strip()
    # [2026-07-05] 신규 등록 브랜드 필수화 — '르무통' 자동 채움 제거(기존 데이터는 안 건드림).
    brand = (body.get('brand') or '').strip()
    category = (body.get('category') or '신발').strip()
    product_skus = body.get('product_skus') or []
    if not code or not name:
        return _err('모음전 코드와 모델명을 입력하세요.')
    if not brand:
        return _err('브랜드를 입력하세요.')
    if not isinstance(product_skus, list) or not product_skus:
        return _err('옵션으로 추가할 재고제품을 1개 이상 선택하세요.')
    s = SessionLocal()
    try:
        if s.query(Model).filter_by(model_code=code).first():
            return _err(f"'{code}' 코드는 이미 존재해요.", 409)
        m = Model(model_code=code, model_name_raw=name,
                  model_name_display=name, brand=brand, category=category)
        s.add(m)
        s.flush()
        products = {p.canonical_sku: p for p in s.query(InventoryProduct)
                    .filter(InventoryProduct.canonical_sku.in_(product_skus)).all()}
        created, seen = [], set()
        for psku in product_skus:
            p = products.get(psku)
            if not p:
                continue
            color = (p.color_code or '기본').strip()
            size = (p.size_code or '기본').strip()
            opt_sku = f"{code}-{color}-{size}"
            if opt_sku in seen or s.query(Option).filter_by(canonical_sku=opt_sku).first():
                continue
            seen.add(opt_sku)
            s.add(Option(canonical_sku=opt_sku, model_code=code,
                         color_code=color, color_display=color,
                         size_code=size, size_display=size,
                         barcode=p.barcode))
            s.add(OptionProductLink(option_canonical_sku=opt_sku,
                                    product_canonical_sku=psku))
            created.append(opt_sku)
        if not created:
            s.rollback()
            return _err('생성된 옵션이 없습니다 (재고제품을 찾지 못했거나 중복).', 400)
        s.commit()
        return _ok(model_code=code, option_count=len(created), options=created)
    finally:
        s.close()


# ═══════ ④-A 옵션 → 마켓 계정별 매핑 (external_option_id + 노출 토글) ═══════

@bp.post('/options/<path:sku>/account-mapping')
def option_account_mapping(sku: str):
    """옵션 1건을 특정 마켓 계정과 매핑 (external_option_id + is_visible).

    option_detail.html 의 v2 계정별 옵션 매핑 저장에서 사용.
    Body: {account_id:int, external_option_id:str|null, is_visible:bool}
    """
    from lemouton.multitenancy.service import upsert_option_registration
    body = request.get_json(silent=True) or {}
    try:
        account_id = int(body.get('account_id'))
    except (TypeError, ValueError):
        return _err('account_id 가 필요합니다.')
    external_option_id = body.get('external_option_id')
    if external_option_id is not None:
        external_option_id = (str(external_option_id).strip() or None)
    is_visible = bool(body.get('is_visible', True))
    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err('옵션을 찾을 수 없어요.', 404)
        reg = upsert_option_registration(
            s,
            canonical_sku=sku,
            account_id=account_id,
            external_option_id=external_option_id,
            is_visible=is_visible,
        )
        s.commit()
        return _ok(
            account_id=reg.account_id,
            external_option_id=reg.external_option_id or '',
            is_visible=bool(reg.is_visible),
        )
    finally:
        s.close()


# ═══════ ④ 모음전 편집 — 이미 등록된 옵션에 재고제품 연결 ═══════

@bp.post('/options/<sku>/link-product')
def option_link_product(sku: str):
    """모음전 옵션 1개에 재고제품 1개를 연결 (OptionProductLink 생성/갱신).

    Body: {product_sku} — 연결할 재고제품(InventoryProduct.canonical_sku).
    이미 링크가 있으면 product_canonical_sku 만 교체 (「변경」).
    응답: {ok, linked_product:{product_sku,name,color,size,brand,barcode,stock}}
    """
    from lemouton.inventory.models import InventoryProduct, OptionProductLink
    from shared.inventory_stock import get_stock_by_sku
    body = request.get_json(silent=True) or {}
    product_sku = (body.get('product_sku') or '').strip()
    if not product_sku:
        return _err('연결할 재고제품을 선택하세요.')
    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        if not opt:
            return _err('옵션을 찾을 수 없어요.', 404)
        product = (s.query(InventoryProduct)
                   .filter_by(canonical_sku=product_sku).first())
        if not product:
            return _err('재고제품을 찾을 수 없어요.', 404)
        link = (s.query(OptionProductLink)
                .filter_by(option_canonical_sku=sku).first())
        if link:
            link.product_canonical_sku = product_sku
        else:
            s.add(OptionProductLink(option_canonical_sku=sku,
                                    product_canonical_sku=product_sku))
        s.commit()
        return _ok(linked_product={
            'product_sku': product.canonical_sku,
            'name': product.option_name or product.canonical_sku,
            'color': product.color_code or '',
            'size': product.size_code or '',
            'brand': product.brand or '',
            'barcode': product.barcode or '',
            'stock': get_stock_by_sku(s, product.canonical_sku),
        })
    finally:
        s.close()


@bp.post('/bundles/<code>/price-mode')
def bundle_price_mode(code: str):
    """[가격모드 v3] 모음전(또는 그룹)의 가격·마진 설정 변경.

    Body 필드 (모두 선택, 보낸 것만 갱신):
      - ss_price_mode: 'color_unified' | 'per_option_cheapest'
      - ss_margin_mode: 'rate' | 'amount'
      - ss_margin_rate: 0.0945 (= 9.45%)
    """
    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        models = _resolve_models_for_code(s, code)
        if not models:
            return _err('모음전을 찾을 수 없어요.', 404)
        m = models[0]  # 그룹 안 모든 모델에 동일 설정 적용
        if 'ss_price_mode' in payload:
            v = str(payload['ss_price_mode'])
            if v not in ('color_unified', 'per_option_cheapest'):
                return _err(f"ss_price_mode 값 잘못: {v}", 400)
            for mm in models:
                mm.ss_price_mode = v
        # 마진 모드/율은 적용된 가격 템플릿에 저장
        if 'ss_margin_mode' in payload or 'ss_margin_rate' in payload:
            tpl = s.query(PriceTemplate).filter_by(id=m.price_template_id).first() if m.price_template_id else None
            if tpl is None:
                return _err('가격 템플릿이 적용되지 않은 모음전이에요.', 400)
            if 'ss_margin_mode' in payload:
                v = str(payload['ss_margin_mode'])
                if v not in ('rate', 'amount'):
                    return _err(f"ss_margin_mode 값 잘못: {v}", 400)
                tpl.ss_margin_mode = v
            if 'ss_margin_rate' in payload:
                tpl.ss_margin_rate = float(payload['ss_margin_rate'])
        s.commit()
        return _ok(saved=True, ss_price_mode=m.ss_price_mode)
    finally:
        s.close()


@bp.post('/bundles/<code>/price-apply')
def bundle_price_apply(code: str):
    """[가격모드 v3] 현재 모드·마진율로 옵션별 push 가격 재계산 + 라이브 스마트스토어 push.

    1. ss_price_mode + 자동 가드레일 적용 → 옵션별 push price/stock 산출
    2. option_price_config 갱신
    3. SmartStoreAdapter.batch_update 라이브 PUT
    4. round-trip 검증
    """
    import json as _json
    from pathlib import Path
    from datetime import datetime, timezone
    from lemouton.sourcing.models import Option as _Option
    from lemouton.templates.models import PriceTemplate as _PT

    s = SessionLocal()
    try:
        models = _resolve_models_for_code(s, code)
        if not models:
            return _err('모음전을 찾을 수 없어요.', 404)
        # 1차 시연: 첫 모델 기준 (그룹 단위 multi-model push 는 5단계 후속)
        m = models[0]
        if not m.naver_product_id:
            return _err('스마트스토어 product_id 미등록.', 400)
        tpl = s.query(_PT).filter_by(id=m.price_template_id).first()
        if tpl is None:
            return _err('가격 템플릿 없음.', 400)

        ss_price = tpl.ss_external_sale_price
        fee = tpl.ss_fee_rate
        margin = tpl.ss_margin_rate
        gl = tpl.guardrail_lower
        gu_auto = int(ss_price * (1 - fee - margin))
        rounding = tpl.rounding_unit or 100
        cap = 10
        mode = m.ss_price_mode or 'color_unified'

        # 자동 수집 데이터 로드 (data/*_live_stock.json)
        root = Path(__file__).resolve().parents[2]
        def load(name):
            p = root / 'data' / f'{name}_live_stock.json'
            if not p.exists():
                return {}
            raw = _json.loads(p.read_text(encoding='utf-8'))
            return {tuple(k.split('|')): v for k, v in raw.items()}

        sources = {
            'lemouton': (107709, {}),  # 르무통 본사 — placeholder 처리는 아래
            'musinsa':  (112159, load('musinsa')),
            'ssf':      (116627, load('ssf')),
            'lotteon':  (115430, load('lotteon')),
        }
        # lemouton 자체사이트 라이브 fetch
        try:
            from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
            r = LemoutonCrawler(prefer_playwright=True).fetch(m.url_lemouton)
            def cn(t):
                if '화이트' in t and '블랙' in t: return '블랙화이트'
                if t.count('블랙') >= 2: return '블랙블랙'
                if '다크' in t or '네이비' in t: return '다크네이비'
                if '그레이' in t: return '그레이'
                return t
            lem_data = {}
            for o in r.options:
                c = cn(o.get('color_text','') or '')
                sz = (o.get('size_text','') or '').replace('mm','').strip()
                if sz in ('230','235','240','245','250','255','260','270','280'):
                    lem_data[(c, sz)] = 0 if o.get('stock', 0) == 0 else 999
            sources['lemouton'] = (107709, lem_data)
        except Exception:
            pass

        def round_to(p, u): return int(round(p / u) * u)

        # 옵션별 가격·재고 산출
        push_data = {}
        options = s.query(_Option).filter_by(model_code=code).all()
        for o in options:
            c, sz = o.color_code, o.size_code
            # 가드레일 통과 source 후보
            cand = [(name, price, data.get((c, sz)))
                    for name, (price, data) in sources.items()
                    if data.get((c, sz)) is not None and gl <= price <= gu_auto]
            # 재고 있는 source 만 (stock>0 또는 placeholder>=100)
            in_stock = [x for x in cand if x[2] > 0]
            if not in_stock:
                push_price = ss_price
                push_stock = 0
            else:
                cheapest = min(in_stock, key=lambda x: x[1])
                if mode == 'per_option_cheapest':
                    push_price = round_to(cheapest[1] / (1 - fee - margin), rounding)
                else:
                    push_price = ss_price
                cheap_stock = cheapest[2]
                push_stock = cap if cheap_stock >= 100 else min(cheap_stock, cap)

            if not o.naver_option_id:
                continue
            push_data[int(o.naver_option_id)] = {
                'sku': o.canonical_sku,
                'price': push_price,
                'stock': push_stock,
            }

        # mode A 면 모든 옵션 단일 ss_price. mode B 면 옵션별 cheapest 가격 (현재 데이터로는 다 lemouton 단일).
        # SmartStoreAdapter 의 batch_update 는 sale_price 1개 + option add_price.
        # 모드 A: sale_price=ss_price, 모든 옵션 add_price=0
        # 모드 B: sale_price=min(push_prices), add_price = push_price - sale_price
        if mode == 'per_option_cheapest':
            valid_prices = [d['price'] for d in push_data.values() if d['price'] > 0]
            sale_price = min(valid_prices) if valid_prices else ss_price
            opt_updates = {oid: {'stockQuantity': d['stock'],
                                 'price': max(0, d['price'] - sale_price)}
                           for oid, d in push_data.items()}
        else:
            sale_price = ss_price
            opt_updates = {oid: {'stockQuantity': d['stock'], 'price': 0}
                           for oid, d in push_data.items()}

        # option_price_config 갱신
        from lemouton.templates.models import PriceTemplate  # noqa
        import sqlalchemy as sa
        now = datetime.now(timezone.utc)
        for oid, d in push_data.items():
            row = s.execute(sa.text(
                "SELECT canonical_sku FROM option_price_config WHERE canonical_sku=:sku"
            ), {'sku': d['sku']}).fetchone()
            if row:
                s.execute(sa.text(
                    "UPDATE option_price_config SET manual_stock=:st, manual_ss_price=:p, updated_at=:ts WHERE canonical_sku=:sku"
                ), {'sku': d['sku'], 'st': d['stock'], 'p': d['price'], 'ts': now})
            else:
                s.execute(sa.text(
                    "INSERT INTO option_price_config (canonical_sku, auto_enabled, manual_stock, manual_ss_price, updated_at) VALUES (:sku, 1, :st, :p, :ts)"
                ), {'sku': d['sku'], 'st': d['stock'], 'p': d['price'], 'ts': now})
        s.commit()

        # 라이브 push
        from lemouton.uploader.adapters.smartstore import SmartStoreAdapter
        adapter = SmartStoreAdapter()
        result = adapter.batch_update(
            market_product_id=int(m.naver_product_id),
            sale_price=sale_price,
            option_updates=opt_updates,
        )
        live_pushed = result.success

        # round-trip 검증
        rt_match = 0
        rt_total = len(push_data)
        try:
            from shared.platforms.smartstore.get_options import fetch_product_options
            live = fetch_product_options(int(m.naver_product_id))
            live_by_oid = {o.option_id: o for o in live.options}
            for oid, d in push_data.items():
                cur = live_by_oid.get(oid)
                if cur and cur.stock == d['stock']:
                    rt_match += 1
        except Exception:
            pass

        # last_uploaded_at 갱신
        m.last_uploaded_at = now
        s.commit()

        return _ok(
            options_updated=len(push_data),
            live_pushed=live_pushed,
            roundtrip_match=rt_match,
            roundtrip_total=rt_total,
            mode=mode,
            sale_price=sale_price,
            guardrail_upper=gu_auto,
        )
    finally:
        s.close()


@bp.post('/bundles/<code>/run-now')
def bundle_run_now(code: str):
    """모음전 1건에 대해 phase 지정 즉시 실행 + BundleRun 이력 기록.

    body: {phase: 'full'|'crawl'|'upload'}
    """
    payload = request.get_json(silent=True) or {}
    phase = payload.get('phase', 'full')
    if phase not in ('full', 'crawl', 'upload'):
        return _err("phase는 'full' / 'crawl' / 'upload' 중 하나여야 해요.", 400)

    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
    finally:
        s.close()

    from lemouton.sourcing.run_history import (
        record_start, record_end, summarize_status, SOURCE_KEYS, MARKET_KEYS,
    )
    import time as _time
    import threading
    run_id = record_start(model_code=code, phase=phase, triggered_by='manual')
    started_at = _time.monotonic()

    # v27 시안 ③ — background thread 로 실행 (사용자가 페이지 이동해도 작업 계속)
    from webapp.progress_state import progress_set, progress_finish, progress_tick

    def _do_work():
        details: dict = {}
        error: str | None = None
        status = 'ok'
        crawl_ok = True  # [2026-06-03 안정화] 크롤 성공 여부 — full 실행 시 실패면 업로드 스킵
        try:
            # [크롤=로컬 원칙] 서버 직접 크롤은 기본 OFF — 로컬 확장이 담당(프론트에서 트리거).
            #   서버 크롤 스킵 시 crawl_ok=True 유지 → 'full' 은 업로드(드라이런)로 진행.
            from lemouton.sourcing.server_crawl_gate import server_crawl_enabled
            if phase in ('crawl', 'full') and server_crawl_enabled():
                progress_set('crawl', total=0,
                             label=f'{code} 전체 크롤링', current='소싱처 URL 집계 중...')
                sources_result: dict = {}
                try:
                    # [2026-06-03] 등록 소싱처 URL(bundle_source_urls) 크롤 — SourceProduct
                    #   보장 + fetch + last_price 저장 → 매트릭스 표시 연결. (run_pipeline 의
                    #   model.url_* 단일 컬럼 대신 사용자가 등록한 URL 전부 크롤.)
                    from lemouton.sources.service import crawl_bundle_registered_urls
                    from lemouton.sourcing.crawlers import build_crawlers
                    from shared.db import SessionLocal as SL2

                    # [2026-06-03] URL 1개 크롤할 때마다 진행 위젯 갱신 (소싱처별 N/M·%).
                    def _crawl_progress(done, total, key, src_totals, src_done):
                        breakdown = []
                        for k, t in src_totals.items():
                            d = src_done.get(k, 0)
                            status = 'done' if d >= t else ('wait' if d == 0 else 'run')
                            breakdown.append({'key': k, 'label': _source_label(k),
                                              'total': t, 'done': d, 'status': status})
                        cur = (f"{_source_label(key)} 크롤 중 ({done}/{total} URL)"
                               if key else f"{total}개 URL 크롤 준비...")
                        progress_tick('crawl', done=done, total=total,
                                      current=cur, breakdown=breakdown)

                    s2 = SL2()
                    try:
                        crawlers = build_crawlers()
                        cr = crawl_bundle_registered_urls(
                            s2, model_code=code, crawlers=crawlers,
                            progress_cb=_crawl_progress)
                        # per_source → {ok:bool} 형태로 변환 (이력/표시 호환)
                        sources_result = {
                            k: {'ok': v.get('ok', 0) > 0,
                                'crawled': v.get('ok', 0),
                                'failed': v.get('error', 0),
                                'no_crawler': v.get('no_crawler', 0)}
                            for k, v in (cr.get('per_source') or {}).items()
                        }
                        # 등록 URL 이 있는데 1건도 ok 아니면 크롤 실패 (full 시 업로드 스킵)
                        if cr.get('total', 0) > 0 and cr.get('ok', 0) == 0:
                            crawl_ok = False
                    finally:
                        s2.close()
                except Exception as e:
                    sources_result = {'_error': {'ok': False, 'error': str(e)}}
                    crawl_ok = False
                # (등록 URL 0개면 sources_result 비어도 crawl_ok 유지 — 실패 아님)
                if sources_result and not any(v.get('ok') for v in sources_result.values()):
                    crawl_ok = False
                details['sources'] = sources_result
                progress_finish('crawl')

            # [2026-06-03 안정화] full 실행: 크롤 실패 시 업로드 건너뜀
            #   (실패·미수집 가격으로 마켓에 잘못 올리는 사고 방지 — "크롤 완료 후 업로드" 원칙).
            if phase == 'full' and not crawl_ok:
                progress_set('upload', total=len(MARKET_KEYS), label=f'{code} 업로드', current='크롤 실패 — 건너뜀')
                details['markets'] = {k: {'ok': False, 'error': '크롤링 실패로 업로드 건너뜀'} for k in MARKET_KEYS}
                details['upload_skipped'] = '크롤링 실패 — 업로드 미진행'
                progress_finish('upload')
            elif phase in ('upload', 'full'):
                progress_set('upload', total=len(MARKET_KEYS),
                             label=f'{code} 업로드', current='시작...')
                # [2026-06-03] 업로드 = 드라이런 미리보기 (표시가=업로드가 단일 진실 원천).
                #   기존 run_uploader 직접 호출은 시그니처 불일치로 작동 불가 → 미리보기로 대체.
                #   실제 마켓 PUT 은 자동전송 활성(별도 승인) 전까지 하지 않음.
                markets_result: dict = {}
                try:
                    from lemouton.uploader.preview import build_upload_preview
                    from shared.db import SessionLocal as SLU
                    s3 = SLU()
                    try:
                        pv = build_upload_preview(s3, code)
                    finally:
                        s3.close()
                    if pv.get('ok'):
                        mk = pv.get('markets', {})
                        for name in ('smartstore', 'coupang'):
                            mm = mk.get(name, {})
                            markets_result[name] = {
                                'ok': True, 'dry_run': True,
                                'active': mm.get('active'),
                                'product_id': bool(mm.get('product_id')),
                                'matched': mm.get('matched', 0),
                                'total': mm.get('total', 0),
                            }
                        details['upload_preview'] = {
                            'dry_run': True,
                            'total_options': pv.get('total_options'),
                            'ready_to_upload': pv.get('ready_to_upload'),
                            'missing': pv.get('missing'),
                            'note': pv.get('note'),
                        }
                        progress_tick('upload', done=len(MARKET_KEYS),
                                      current='드라이런 미리보기 완료 (실제 전송 안 함)')
                    else:
                        markets_result = {k: {'ok': False, 'error': pv.get('error', '미리보기 실패')}
                                          for k in MARKET_KEYS}
                except Exception as e:
                    markets_result = {k: {'ok': False, 'error': str(e)} for k in MARKET_KEYS}
                details['markets'] = markets_result
                details['dry_run'] = True
                progress_finish('upload')
        except Exception as e:
            error = str(e)
            status = 'failed'
            try: progress_finish('crawl')
            except Exception: pass
            try: progress_finish('upload')
            except Exception: pass

        details['duration_sec'] = round(_time.monotonic() - started_at, 1)
        if status != 'failed':
            try: status = summarize_status(details)
            except Exception: pass
        try:
            record_end(run_id, status=status, details=details, error=error)
        except Exception:
            pass

    # 백그라운드 thread 로 실행 — 사용자 fetch 끊겨도 작업 계속
    t = threading.Thread(target=_do_work, name=f'bundle-run-{code}-{phase}', daemon=True)
    t.start()
    # 즉시 응답 — 클라이언트는 progress widget 으로 진행 모니터
    return _ok(run_id=run_id, status='running', accepted=True,
               message='백그라운드에서 실행 중 — 우상단 진행 widget 으로 모니터하세요')


@bp.post('/bundles/<code>/options/combo')
def bundle_options_combo(code: str):
    """[Phase 2] 단계형 옵션 — 조합 추가.

    단계 설계 저장 + 조합 옵션 일괄 생성 (이미 있는 옵션은 제외).

    body: {
      "steps": [{"axis_name": str, "values": [str, ...]}],   # 1~3개
      "selected": [[str, ...], ...]   # 선택 — 일부 조합만 (2·3축 매트릭스 선택 생성)
    }
    """
    payload = request.get_json(silent=True) or {}
    steps = payload.get('steps') or []
    selected = payload.get('selected')   # None = 전체 cartesian
    # [2026-05-25 A-2-FIX] prune=True 면 selected 에 없는 기존 옵션 삭제 (모달 = 단일 진실 원천).
    prune = bool(payload.get('prune'))

    if not steps or not isinstance(steps, list):
        return _err('steps(단계 설계)가 필요해요.')
    if len(steps) > 3:
        return _err('단계는 최대 3개까지예요.')

    from lemouton.sourcing.option_service import create_combination_options
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=code).first()
        if m is None:
            return _err('모음전을 찾을 수 없어요.', 404)
        result = create_combination_options(s, code, steps, selected=selected, prune=prune)
        return _ok(**result)
    except Exception as e:
        s.rollback()
        return _err(str(e), 500)
    finally:
        s.close()


@bp.get('/bundles/<code>/runs')
def bundle_runs(code: str):
    """모음전 단위 실행 이력 조회."""
    from lemouton.sourcing.run_history import list_for_bundle
    limit = int(request.args.get('limit', '20'))
    return _ok(items=list_for_bundle(code, limit=limit))


@bp.get('/runs/active')
def runs_active():
    """실시간 로그 패널용 — 실행 중 + 최근 종료된 run 목록."""
    from lemouton.sourcing.run_history import list_active
    limit = int(request.args.get('limit', '30'))
    return _ok(items=list_active(limit=limit))


@bp.get('/runs/<int:run_id>')
def run_detail(run_id: int):
    """단일 run 상세 — 행 펼치기."""
    from lemouton.sourcing.run_history import get_run
    item = get_run(run_id)
    if item is None:
        return _err('실행 이력을 찾을 수 없어요.', 404)
    return _ok(item=item)


# ---------- 전체 사이클 — 크롤만 / 업로드만 ----------

@bp.post('/cycle/crawl')
def cycle_crawl_all():
    """전체 모음전 크롤링 — 모음전마다 1개의 워커 스레드(=1 탭) 로 병렬 실행.

    - 부모 bulk run 1행 (model_code=NULL) + 모델 N개에 대해 자식 run N행
      → 우측 실행 로그 패널에서 "한 모음전 = 1행" 으로 동시에 표시
    - 동시 실행 워커 수 제한: max_workers=4 (사이트 부하 방지)
    """
    # [크롤=로컬 원칙] 서버 직접 크롤은 기본 OFF — 로컬 확장이 담당.
    from lemouton.sourcing.server_crawl_gate import server_crawl_enabled, DISABLED_MESSAGE
    if not server_crawl_enabled():
        return _ok(triggered=False, server_crawl_disabled=True, message=DISABLED_MESSAGE)

    from lemouton.sourcing.run_history import (
        record_start, record_end, summarize_status, SOURCE_KEYS,
    )
    from concurrent.futures import ThreadPoolExecutor
    import threading, time as _time

    parent_id = record_start(model_code=None, phase='crawl', triggered_by='manual')

    # v27 — widget progress (전역)
    from webapp.progress_state import progress_set, progress_tick, progress_finish

    def _bulk_bg():
        from shared.db import SessionLocal as SL2
        from lemouton.sourcing.bulk_crawl import SOURCE_URL_FIELD as _SUF
        from lemouton.sourcing.models import Option as _Opt
        s_init = SL2()
        try:
            # 크롤 대상 = URL 보유 + 우리 Option(색상/사이즈) 보유 모음전만
            _url_cols = list(_SUF.values())
            _opt_codes = {r[0] for r in s_init.query(_Opt.model_code).distinct().all()}
            codes = [m.model_code for m in s_init.query(Model).order_by(Model.model_code).all()
                     if any(getattr(m, c, None) for c in _url_cols) and m.model_code in _opt_codes]
        finally:
            s_init.close()
        # widget 시작 — 전체 모음전 N개
        try: progress_set('crawl', total=len(codes), label='전체 모음전 크롤링', current='시작...')
        except Exception: pass

        started_parent = _time.monotonic()
        per_child: dict[str, dict] = {}

        def _one(code: str):
            cid = record_start(model_code=code, phase='crawl', triggered_by='bulk')
            t0 = _time.monotonic()
            d: dict = {'sources': {}}
            err = None
            st = 'ok'
            try: progress_tick('crawl', current=f'{code} 크롤 중...')
            except Exception: pass
            try:
                # [2026-06-03] 저장 배선 — run_pipeline(미저장) → crawl_and_save_model(PriceTrackHistory 저장)
                from lemouton.sourcing.bulk_crawl import crawl_and_save_model
                res = crawl_and_save_model(code)
                srcs = {k: v for k, v in res.items() if not k.startswith('_')}
                d['sources'] = {
                    k: {'ok': v.get('ok'), 'items_crawled': v.get('options', 0),
                        'saved': v.get('saved', 0), 'error': v.get('error')}
                    for k, v in srcs.items()
                }
                d['saved'] = sum(v.get('saved', 0) for v in srcs.values() if v.get('ok'))
                oks = [v for v in srcs.values() if v.get('ok')]
                if srcs and not oks:
                    st = 'failed'
                elif len(oks) < len(srcs):
                    st = 'partial'
                else:
                    st = 'ok'
            except Exception as e:
                err = str(e)
                st = 'failed'
                d['sources'] = {}
            d['duration_sec'] = round(_time.monotonic() - t0, 1)
            record_end(cid, status=st, details=d, error=err)
            per_child[code] = {'ok': st != 'failed', 'status': st,
                                'duration_sec': d['duration_sec'], 'saved': d.get('saved', 0)}
            try: progress_tick('crawl', delta=1, current=f'{code} ✓ ({len(per_child)}/{len(codes)})')
            except Exception: pass

        if codes:
            with ThreadPoolExecutor(max_workers=3) as ex:
                list(ex.map(_one, codes))

        # 부모 집계
        oks = sum(1 for v in per_child.values() if v.get('ok'))
        fails = len(per_child) - oks
        total_saved = sum(v.get('saved', 0) for v in per_child.values())
        parent_details = {
            'sources': {k: {'ok': True, 'items_crawled': 0} for k in SOURCE_KEYS},
            'saved': total_saved,
            'children': per_child,
            'duration_sec': round(_time.monotonic() - started_parent, 1),
            'children_total': len(per_child),
            'children_ok': oks,
            'children_failed': fails,
        }
        parent_status = 'ok' if fails == 0 else ('partial' if oks > 0 else 'failed')
        record_end(parent_id, status=parent_status, details=parent_details,
                   error=None if parent_status != 'failed' else f'{fails}/{len(per_child)} 실패')
        try: progress_finish('crawl')
        except Exception: pass

    threading.Thread(target=_bulk_bg, daemon=True).start()
    return _ok(run_id=parent_id, triggered=True)


@bp.post('/cycle/upload')
def cycle_upload_all():
    """전체 모음전 업로드 — 모음전마다 1개의 워커 스레드(=1 탭) 로 병렬 실행.

    body: {markets: ['smartstore', 'coupang'], mode: 'diff'|'force'|'dryrun'}
    부모 bulk run 1행 + 자식 run N행 (N=모음전 수). 우측 실행 로그 패널에서
    한 모음전 = 1행으로 동시 표시.
    """
    payload = request.get_json(silent=True) or {}
    markets = payload.get('markets') or ['smartstore', 'coupang']
    mode = payload.get('mode', 'diff')
    if mode not in ('diff', 'force', 'dryrun'):
        return _err("mode는 'diff'|'force'|'dryrun' 중 하나여야 해요.", 400)

    from lemouton.sourcing.run_history import record_start, record_end, summarize_status
    from concurrent.futures import ThreadPoolExecutor
    import threading, time as _time

    parent_id = record_start(model_code=None, phase='upload', triggered_by='manual')

    # v27 — widget progress
    from webapp.progress_state import progress_set as _pset, progress_tick as _ptick, progress_finish as _pfinish

    def _bulk_bg():
        from shared.db import SessionLocal as SL2
        s_init = SL2()
        try:
            codes = [m.model_code for m in s_init.query(Model).all()]
        finally:
            s_init.close()
        try: _pset('upload', total=len(codes), label=f'전체 업로드 ({", ".join(markets)})', current='시작...')
        except Exception: pass

        started_parent = _time.monotonic()
        per_child: dict[str, dict] = {}

        def _one(code: str):
            cid = record_start(model_code=code, phase='upload', triggered_by='bulk')
            t0 = _time.monotonic()
            d: dict = {'markets': {}, 'mode': mode, 'requested_markets': markets}
            err = None
            st = 'ok'
            try: _ptick('upload', current=f'{code} 업로드 중...')
            except Exception: pass
            try:
                from lemouton.uploader.orchestrator import run_uploader
                try:
                    r = run_uploader(model_code=code,
                                     dry_run=(mode == 'dryrun'),
                                     force=(mode == 'force'),
                                     only_markets=markets)
                except TypeError:
                    try:
                        r = run_uploader(model_code=code, dry_run=(mode == 'dryrun'))
                    except TypeError:
                        r = run_uploader(dry_run=(mode == 'dryrun'))
                if isinstance(r, dict):
                    if 'per_market' in r:
                        d['markets'] = {k: v for k, v in r['per_market'].items() if k in markets}
                    else:
                        for mk in markets:
                            d['markets'][mk] = {
                                'ok': not bool(r.get('failed', 0)) or bool(r.get('uploaded', 0)),
                                'uploaded': r.get('uploaded', 0),
                                'skipped': r.get('skipped', 0),
                                'failed': r.get('failed', 0),
                            }
                else:
                    d['markets'] = {mk: {'ok': True} for mk in markets}
            except Exception as e:
                err = str(e)
                st = 'failed'
                d['markets'] = {mk: {'ok': False, 'error': err} for mk in markets}
            d['duration_sec'] = round(_time.monotonic() - t0, 1)
            if st != 'failed':
                st = summarize_status(d)
            record_end(cid, status=st, details=d, error=err)
            per_child[code] = {'ok': st != 'failed', 'status': st,
                                'duration_sec': d['duration_sec']}
            try: _ptick('upload', delta=1, current=f'{code} ✓ ({len(per_child)}/{len(codes)})')
            except Exception: pass

        if codes:
            with ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(_one, codes))

        oks = sum(1 for v in per_child.values() if v.get('ok'))
        fails = len(per_child) - oks
        parent_details = {
            'markets': {mk: {'ok': True} for mk in markets},
            'mode': mode,
            'requested_markets': markets,
            'children': per_child,
            'duration_sec': round(_time.monotonic() - started_parent, 1),
            'children_total': len(per_child),
            'children_ok': oks,
            'children_failed': fails,
        }
        parent_status = 'ok' if fails == 0 else ('partial' if oks > 0 else 'failed')
        record_end(parent_id, status=parent_status, details=parent_details,
                   error=None if parent_status != 'failed' else f'{fails}/{len(per_child)} 실패')
        try: _pfinish('upload')
        except Exception: pass

    threading.Thread(target=_bulk_bg, daemon=True).start()
    return _ok(run_id=parent_id, triggered=True, markets=markets, mode=mode)


# ---------- 알림 채널 라우팅 (메모리만 — 후속 영구화) ----------

_ALERTS_ROUTING_OVERRIDE: dict = {}

@bp.post('/alerts/route')
def alerts_route():
    payload = request.get_json(silent=True) or {}
    key = payload.get('event_key')
    channel = payload.get('channel')
    enabled = bool(payload.get('enabled'))
    if not key or not channel:
        return _err('event_key, channel 모두 필요해요.', 400)
    _ALERTS_ROUTING_OVERRIDE.setdefault(key, {})[channel] = enabled
    return _ok(event_key=key, channel=channel, enabled=enabled,
               note='메모리 저장 — 영구화는 후속 작업')



# ──────────────────────────────────────────────────────────
#  /api/sources/detect — v6 Phase 5.5 (E5)
#  미등록 도메인 검출 → 신규 소싱처 추가 위저드로 안내
# ──────────────────────────────────────────────────────────

# 검출 이벤트 메모리 로그 (영구화는 별도 phase — DiscoveryQueue 등에 push 가능)
_DOMAIN_DETECT_LOG: list = []


@bp.post('/sources/detect')
def sources_detect():
    """모음전 편집 페이지에서 미등록 도메인 입력 시 호출.

    POST 본문: {"domain": "29cm.co.kr"}
    응답: {ok: True, domain: "...", next_url: "/accounts/sourcing?new=29cm.co.kr",
           detected_at: "...", message: "..."}
    """
    payload = request.get_json(silent=True) or {}
    domain = (payload.get('domain') or '').strip().lower()
    if not domain:
        return _err('domain 필드가 필요합니다.', 400)
    # 알려진 표준 소싱처 도메인은 무시
    KNOWN = {'lemouton.kr', 'lemouton.co.kr', 'musinsa.com',
             'ssfshop.com', 'lotteon.com', 'lotte.com',
             'smartstore.naver.com'}
    if domain in KNOWN or any(domain.endswith('.' + k) for k in KNOWN):
        return _err('이미 등록된 표준 도메인입니다.', 400)
    # 메모리 로그 기록
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _DOMAIN_DETECT_LOG.append({'domain': domain, 'detected_at': now})
    # 위저드로 안내
    next_url = '/accounts/sourcing?new=' + domain
    return _ok(
        domain=domain,
        next_url=next_url,
        detected_at=now,
        message=(f'"{domain}" 검출 기록됨. 소싱처 위저드(/accounts/sourcing)에서 '
                 'SourcingAccount 등록 + scraper 모듈 연결 필요.'),
    )


@bp.get('/sources/detect/log')
def sources_detect_log():
    """검출 이력 (개발자용 — 메모리 누적 분량 반환)."""
    return _ok(log=list(_DOMAIN_DETECT_LOG)[-50:])


# ──────────────────────────────────────────────────────────────────
#  v6 P5.5 — 신규 소싱처 추가 (시안 A) URL probe
#  POST /api/sources/probe {url: "..."} → {domain, favicon, title, color}
# ──────────────────────────────────────────────────────────────────

@bp.post("/sources/probe")
def sources_probe():
    """URL 1개 입력 → 도메인 추출 + favicon + 타이틀 자동 fetch.

    시안 A 의 자동 채우기 용도 — 사용자 입력 줄이기.
    실패해도 도메인은 항상 반환.
    """
    from urllib.parse import urlparse
    import re as _re
    payload = request.get_json(silent=True) or {}
    url = (payload.get('url') or '').strip()
    if not url:
        return _err('URL 이 필요해요.', 400)
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    try:
        p = urlparse(url)
        domain = (p.hostname or '').replace('www.', '').lower()
    except Exception:
        return _err('URL 파싱 실패', 400)

    if not domain:
        return _err('도메인 추출 실패', 400)

    # 시스템 키 자동 생성 — 도메인 첫 부분 (영숫자)
    base_key = domain.split('.')[0]
    source_key = _re.sub(r'[^a-z0-9_]', '', base_key.lower())[:30]

    # 라벨 자동 — 도메인 대문자 (예: SSG.COM)
    auto_label = domain.upper()

    out = {
        'url': url,
        'domain': domain,
        'source_key': source_key,
        'label_suggestion': auto_label,
        'logo_letter': base_key[:1].upper() if base_key else 'X',
        'favicon_url': f'https://{domain}/favicon.ico',
        'logo_color': '#3182F6',  # 기본
        'title': None,
        'fetched': False,
    }

    # 실제 fetch 시도 (timeout 8s, 실패해도 위 메타는 반환)
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            ct = r.headers.get('Content-Type', '')
            if 'html' in ct or 'text' in ct:
                html = r.read(80000).decode('utf-8', errors='replace')
                # title
                m = _re.search(r'<title[^>]*>([^<]+)</title>', html, _re.I)
                if m:
                    out['title'] = m.group(1).strip()[:200]
                # favicon (link rel=icon)
                for pat in [
                    r'<link[^>]+rel=["\'](?:shortcut icon|icon|apple-touch-icon)["\'][^>]+href=["\']([^"\']+)["\']',
                    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'](?:shortcut icon|icon|apple-touch-icon)["\']',
                ]:
                    fm = _re.search(pat, html, _re.I)
                    if fm:
                        fav = fm.group(1).strip()
                        if fav.startswith('//'):
                            fav = 'https:' + fav
                        elif fav.startswith('/'):
                            fav = f'https://{domain}' + fav
                        elif not fav.startswith('http'):
                            fav = f'https://{domain}/' + fav.lstrip('./')
                        out['favicon_url'] = fav
                        break
                # theme-color meta
                tm = _re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']', html, _re.I)
                if tm:
                    color = tm.group(1).strip()
                    if color.startswith('#') and len(color) in (4, 7):
                        out['logo_color'] = color
                out['fetched'] = True
    except Exception as e:
        out['fetch_error'] = str(e)[:200]

    return _ok(**out)


@bp.post('/sources/add')
def api_sources_add():
    """[소싱처 통합] 신규 소싱처 사이트 추가 → SourcingSource 마스터에 기록.

    URL 섹션·소싱처 계정 페이지가 같은 SourcingSource 목록을 공유하므로 양쪽에 자동 반영.
    Body: {label, domain, logo_color?, logo_letter?, favicon_url?, needs_login?}
    """
    import re as _re
    from lemouton.sourcing.models import SourcingSource
    data = request.get_json(silent=True) or {}
    label = (data.get('label') or '').strip()
    domain = (data.get('domain') or '').strip().lower()
    domain = domain.replace('https://', '').replace('http://', '').replace('www.', '').rstrip('/')
    if not label or not domain:
        return _err('소싱처 이름과 도메인을 입력하세요.')
    base = _re.sub(r'[^a-z0-9_]', '', domain.split('/')[0].split('.')[0].lower()) or 'src'
    builtin = {'lemouton', 'musinsa', 'ssf', 'lotteon', 'ss_lemouton'}
    s = SessionLocal()
    try:
        key, n = base, 2
        while key in builtin or s.query(SourcingSource).filter_by(source_key=key).first():
            key = f'{base}{n}'
            n += 1
        row = SourcingSource(
            source_key=key, label=label, domain=domain,
            logo_color=(data.get('logo_color') or '#3182F6'),
            logo_letter=((data.get('logo_letter') or label[:1]).upper()[:4]),
            favicon_url=(data.get('favicon_url') or None),
            needs_login=bool(data.get('needs_login')),
            has_adapter=False, is_active=True,
            sort_order=100 + s.query(SourcingSource).count(),
        )
        s.add(row)
        s.commit()
        return _ok(source_key=key, label=label)
    except Exception as e:
        s.rollback()
        return _err(str(e), 500)
    finally:
        s.close()


@bp.get('/sources/catalog')
def api_sources_catalog():
    """[소싱처 추가] 크롤링 가이드 기반 소싱처 카탈로그 + 추가 여부.

    옵션 모달 '신규 소싱처 추가' 탭(시안 D)이 검색·표시.
    added=이미 사용 가능(builtin 또는 SourcingSource 등록됨).
    """
    from lemouton.sourcing.source_registry import (
        get_catalog, is_builtin_key, get_all_keys,
    )
    existing = set(get_all_keys())
    items = []
    for c in get_catalog():
        c['builtin'] = is_builtin_key(c['key'])
        c['added'] = c['key'] in existing  # builtin 도 existing 에 포함됨
        items.append(c)
    return _ok(items=items)


@bp.post('/sources/catalog/add')
def api_sources_catalog_add():
    """[소싱처 추가] 카탈로그 항목을 SourcingSource 로 전역 등록.

    Body: {key}. builtin/이미등록 은 거부(중복 차단 — 데이터 무결성).
    has_adapter=False(예: 롯데아이몰)는 '크롤 미지원'으로 추가 허용(URL 저장 가능,
    어댑터 작성 후 자동 활성화).
    """
    from lemouton.sourcing.models import SourcingSource
    from lemouton.sourcing.source_registry import (
        get_catalog_entry, is_builtin_key, get_all_keys,
    )
    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    entry = get_catalog_entry(key)
    if not entry:
        return _err('카탈로그에 없는 소싱처에요.')
    if is_builtin_key(key):
        return _err('기본 제공 소싱처라 이미 사용 중이에요.')
    if key in set(get_all_keys()):
        return _err(f"'{entry['label']}' 은 이미 추가된 소싱처에요.")
    s = SessionLocal()
    try:
        if s.query(SourcingSource).filter_by(source_key=key).first():
            return _err(f"'{entry['label']}' 은 이미 추가된 소싱처에요.")
        row = SourcingSource(
            source_key=key, label=entry['label'],
            domain=(entry.get('domain') or key),
            logo_color=(entry.get('logo_color') or '#3182F6'),
            logo_letter=((entry.get('glyph') or entry['label'][:1]).upper()[:4]),
            needs_login=bool(entry.get('needs_login')),
            has_adapter=bool(entry.get('has_adapter')),
            is_active=True,
            sort_order=100 + s.query(SourcingSource).count(),
        )
        s.add(row)
        s.commit()
        return _ok(source={
            'key': key, 'label': entry['label'],
            'color': entry.get('logo_color') or '#3182F6',
            'glyph': entry.get('glyph') or '',
            'crawler': bool(entry.get('has_adapter')),
        })
    except Exception as e:
        s.rollback()
        return _err(str(e), 500)
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
#  제품 공유 v1 — 제품 마스터 ② 복사·일괄생성 / ③ 삭제 경고 / ⑤ 역참조
# ════════════════════════════════════════════════════════════

def _new_option_payload(src, color_code, size_code, *, color_display=None, size_display=None):
    """기준 옵션 src 를 베이스로 새 Option 생성용 kwargs.

    canonical_sku = {model_code}-{색상}-{사이즈}. 색상·사이즈만 바꾸고 모델 그대로.
    표시명 규칙 — 명시 전달값 우선 → 코드가 src 와 같으면 src 표시명 → 아니면 새 코드.
    (코드가 바뀌었는데 src 표시명을 그대로 쓰면 잘못된 라벨이 됨)
    """
    from lemouton.sourcing.models import Option as _Opt  # noqa
    sku = f"{src.model_code}-{color_code}-{size_code}"
    if color_display is None:
        color_display = (src.color_display or src.color_code) if color_code == src.color_code else color_code
    if size_display is None:
        size_display = (src.size_display or src.size_code) if size_code == src.size_code else size_code
    return sku, dict(
        canonical_sku=sku,
        model_code=src.model_code,
        color_code=color_code,
        color_display=color_display or color_code,
        size_code=size_code,
        size_display=size_display or size_code,
        sort_order=getattr(src, 'sort_order', 0) or 0,
    )


def _create_linked_product(s, opt, model):
    """새 Option 1개에 대해 InventoryProduct + OptionProductLink 행을 함께 생성.

    InventoryProduct.canonical_sku 는 옵션 SKU 와 동일 (1:1 신규 제품).
    inventory_compose_bundle 패턴 — 옵션 만들 때 재고제품·링크 동시 생성.
    """
    from lemouton.inventory.models import InventoryProduct, OptionProductLink
    sku = opt.canonical_sku
    if not s.query(InventoryProduct).filter_by(canonical_sku=sku).first():
        s.add(InventoryProduct(
            canonical_sku=sku,
            option_name=f"{opt.color_display or opt.color_code}-{opt.size_display or opt.size_code}",
            model_code=opt.model_code,
            color_code=opt.color_code,
            size_code=opt.size_code,
            brand=(model.brand if model else None),
            barcode=opt.barcode,
            status='draft',
        ))
    if not s.query(OptionProductLink).filter_by(option_canonical_sku=sku).first():
        s.add(OptionProductLink(
            option_canonical_sku=sku,
            product_canonical_sku=sku,
        ))


@bp.post('/inventory/products/copy')
def inventory_product_copy(  # noqa: C901
):
    """② 제품 복사 — 한 행을 복제. 같은 model_code, 색상·사이즈만 수정.

    Body: {src_sku, color_code, size_code, color_display?, size_display?}
    새 Option + InventoryProduct + OptionProductLink 동시 생성.
    """
    payload = request.get_json(silent=True) or {}
    src_sku = (payload.get('src_sku') or '').strip()
    color = (payload.get('color_code') or '').strip()
    size = (payload.get('size_code') or '').strip()
    if not src_sku or not color or not size:
        return _err('src_sku / color_code / size_code 가 필요해요.', 400)

    s = SessionLocal()
    try:
        src = s.query(Option).filter_by(canonical_sku=src_sku).first()
        if src is None:
            return _err(f'기준 제품을 찾을 수 없어요: {src_sku}', 404)
        model = s.query(Model).filter_by(model_code=src.model_code).first()

        new_sku, kw = _new_option_payload(
            src, color, size,
            color_display=(payload.get('color_display') or '').strip() or None,
            size_display=(payload.get('size_display') or '').strip() or None,
        )
        if new_sku == src_sku or s.query(Option).filter_by(canonical_sku=new_sku).first():
            return _err(f"옵션 '{new_sku}' 가 이미 존재해요.", 409)

        opt = Option(**kw)
        s.add(opt)
        s.flush()
        _create_linked_product(s, opt, model)
        s.commit()
        return _ok(canonical_sku=new_sku)
    except Exception as e:
        s.rollback()
        return _err(f'복사 실패: {e}', 500)
    finally:
        s.close()


@bp.post('/inventory/products/bulk-generate')
def inventory_product_bulk_generate():  # noqa: C901
    """② 색상×사이즈 매트릭스 일괄생성.

    Body: {src_sku, combos:[{color_code,size_code,color_display?,size_display?}, ...]}
    체크한 조합마다 Option + InventoryProduct + OptionProductLink 생성.
    이미 존재하는 SKU 는 skip (중복 안전).
    """
    payload = request.get_json(silent=True) or {}
    src_sku = (payload.get('src_sku') or '').strip()
    combos = payload.get('combos') or []
    if not src_sku:
        return _err('src_sku 가 필요해요.', 400)
    if not isinstance(combos, list) or not combos:
        return _err('생성할 조합(combos)이 없어요.', 400)

    s = SessionLocal()
    try:
        src = s.query(Option).filter_by(canonical_sku=src_sku).first()
        if src is None:
            return _err(f'기준 제품을 찾을 수 없어요: {src_sku}', 404)
        model = s.query(Model).filter_by(model_code=src.model_code).first()

        created, skipped = [], []
        seen = set()
        for c in combos:
            if not isinstance(c, dict):
                continue
            color = (c.get('color_code') or '').strip()
            size = (c.get('size_code') or '').strip()
            if not color or not size:
                continue
            new_sku, kw = _new_option_payload(
                src, color, size,
                color_display=(c.get('color_display') or '').strip() or None,
                size_display=(c.get('size_display') or '').strip() or None,
            )
            if new_sku in seen:
                continue
            seen.add(new_sku)
            if s.query(Option).filter_by(canonical_sku=new_sku).first():
                skipped.append(new_sku)
                continue
            opt = Option(**kw)
            s.add(opt)
            s.flush()
            _create_linked_product(s, opt, model)
            created.append(new_sku)
        s.commit()
        return _ok(created=created, skipped=skipped,
                   created_count=len(created), skipped_count=len(skipped))
    except Exception as e:
        s.rollback()
        return _err(f'일괄생성 실패: {e}', 500)
    finally:
        s.close()


def _usage_for_products(s, product_skus):
    """⑤ 역참조 batch 조회 (N+1 회피).

    product_canonical_sku 리스트 → {product_sku: [{model_code, model_name, option_sku,
    option_label}, ...]} 형태로 모음전·옵션 트리 데이터 반환.
    """
    from lemouton.inventory.models import OptionProductLink
    result = {sk: [] for sk in product_skus}
    if not product_skus:
        return result
    links = (s.query(OptionProductLink)
             .filter(OptionProductLink.product_canonical_sku.in_(product_skus))
             .all())
    opt_skus = [l.option_canonical_sku for l in links]
    if not opt_skus:
        return result
    # 옵션 batch 조회
    opts = {o.canonical_sku: o for o in
            s.query(Option).filter(Option.canonical_sku.in_(opt_skus)).all()}
    model_codes = {o.model_code for o in opts.values() if o.model_code}
    models = {m.model_code: m for m in
              s.query(Model).filter(Model.model_code.in_(model_codes)).all()} if model_codes else {}
    for l in links:
        opt = opts.get(l.option_canonical_sku)
        if opt is None:
            continue
        m = models.get(opt.model_code)
        color = (opt.color_display or opt.color_code or '').strip()
        size = (opt.size_display or opt.size_code or '').strip()
        opt_label = ' '.join(x for x in (color, size) if x) or opt.canonical_sku
        result.setdefault(l.product_canonical_sku, []).append({
            'model_code': opt.model_code or '',
            'model_name': (m.model_name_display or m.model_name_raw) if m else (opt.model_code or '(모음전 없음)'),
            'option_sku': opt.canonical_sku,
            'option_label': opt_label,
        })
    return result


def _group_usage_by_bundle(rows):
    """역참조 평면 리스트 → 모음전별 그룹 트리. [{model_code, model_name, options:[...]}]."""
    bundles = {}
    for r in rows:
        mc = r['model_code']
        b = bundles.setdefault(mc, {
            'model_code': mc, 'model_name': r['model_name'], 'options': [],
        })
        b['options'].append({'option_sku': r['option_sku'], 'option_label': r['option_label']})
    return list(bundles.values())


@bp.get('/inventory/products/<path:sku>/usage')
def inventory_product_usage(sku):
    """③·⑤ 단건 역참조 — 이 제품을 쓰는 모음전·옵션 트리.

    응답: {ok, product_sku, total_options, total_bundles, bundles:[{model_code,
    model_name, options:[{option_sku, option_label}]}]}
    """
    s = SessionLocal()
    try:
        flat = _usage_for_products(s, [sku]).get(sku, [])
        bundles = _group_usage_by_bundle(flat)
        return _ok(product_sku=sku, total_options=len(flat),
                   total_bundles=len(bundles), bundles=bundles)
    finally:
        s.close()


@bp.get('/inventory/products/usage-batch')
def inventory_product_usage_batch():
    """⑤ 역참조 batch — 여러 제품의 사용처 개수 한 번에 (N+1 회피).

    Query: skus=sku1&skus=sku2 ...  (또는 skus=a,b,c)
    응답: {ok, usage:{product_sku: {option_count, bundle_count, bundles:[...]}}}
    """
    skus = request.args.getlist('skus')
    if len(skus) == 1 and ',' in skus[0]:
        skus = [x.strip() for x in skus[0].split(',') if x.strip()]
    skus = [x for x in skus if x]
    s = SessionLocal()
    try:
        usage_map = _usage_for_products(s, skus)
        out = {}
        for sk, flat in usage_map.items():
            bundles = _group_usage_by_bundle(flat)
            out[sk] = {
                'option_count': len(flat),
                'bundle_count': len(bundles),
                'bundles': bundles,
            }
        return _ok(usage=out)
    finally:
        s.close()


@bp.post('/inventory/products/<path:sku>/delete')
def inventory_product_delete(sku):
    """③ 제품 삭제 — Option + InventoryProduct + OptionProductLink 정리.

    삭제 전 경고(사용처)는 프론트가 GET .../usage 로 먼저 확인.
    이 엔드포인트는 실제 삭제 — '알고도 삭제' 확정 시 호출.
    """
    from lemouton.inventory.models import InventoryProduct, OptionProductLink
    s = SessionLocal()
    try:
        opt = s.query(Option).filter_by(canonical_sku=sku).first()
        product = s.query(InventoryProduct).filter_by(canonical_sku=sku).first()
        if opt is None and product is None:
            return _err(f'제품을 찾을 수 없어요: {sku}', 404)

        # 이 옵션이 쓰는 링크 + 이 제품을 가리키는 링크 모두 정리
        s.query(OptionProductLink).filter(
            (OptionProductLink.option_canonical_sku == sku)
            | (OptionProductLink.product_canonical_sku == sku)
        ).delete(synchronize_session=False)
        if product is not None:
            s.delete(product)
        if opt is not None:
            from sqlalchemy import text as _sa_text
            # 자식 테이블 정리 — 옵션 삭제 전 FK 참조 행 제거.
            # PostgreSQL 은 SQLite 의 PRAGMA foreign_keys 가 없으므로,
            # 각 DELETE 를 SAVEPOINT 로 격리해 한 문이 실패해도 트랜잭션이
            # abort 되지 않게 한다 (테이블 부재 등 대비).
            for tbl in ('etc_source_urls', 'price_track_history',
                        'market_registrations', 'option_source_links',
                        'option_account_registrations', 'option_benefit_overrides'):
                sp = s.begin_nested()
                try:
                    s.execute(_sa_text(f"DELETE FROM {tbl} WHERE canonical_sku = :sku"),
                              {'sku': sku})
                    sp.commit()
                except Exception:
                    sp.rollback()
            s.delete(opt)
        s.commit()
        return _ok(deleted_sku=sku)
    except Exception as e:
        s.rollback()
        return _err(f'삭제 실패: {e}', 500)
    finally:
        s.close()
