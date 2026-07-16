"""[E] 사이드바 커스터마이징 API — A1 워크플로 스테이지 + 사용자 자율 구성.

데이터 영속화: data/sidebar_layout.json (단일 사용자 시스템 — JSON 1파일).
스키마 v1. 기본값은 기존 sidebar.html 메뉴를 A1 4스테이지로 재배치.
"""
import json
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Blueprint, jsonify, request

from config import PROJECT_ROOT

bp = Blueprint('api_sidebar', __name__, url_prefix='/api/sidebar')

LAYOUT_PATH = PROJECT_ROOT / 'data' / 'sidebar_layout.json'
_lock = Lock()


def _default_layout() -> dict:
    """기능별 6분류 기본 레이아웃. 항목 id/url/active_key/badge 는 기존 페이지 그대로 유지(이동만).
    숨김 3종(i_src_acct/i_mk_upload/i_boxhero)은 미포함 — 기능·URL 은 살아있음."""
    return {
        'version': 1,
        'updated_at': None,
        'standalone': [
            {'id': 'i_home', 'emoji': '⌂', 'name': '홈',
             'url': '/', 'active_key': 'home', 'badge_key': None},
        ],
        'stages': [
            {'id': 's_bundles', 'emoji': '📦', 'name': '모음전 구성', 'color': '#3182F6',
             'collapsed': False, 'items': [
                {'id': 'i_new', 'emoji': '➕', 'name': '신규 모음전 등록',
                 'url': '/bundles/new', 'active_key': 'bundles_new', 'badge_key': None},
                {'id': 'i_bundles', 'emoji': '📋', 'name': '모음전 구성',
                 'url': '/bundles', 'active_key': 'bundles', 'badge_key': None},
                {'id': 'i_migrate', 'emoji': '🔗', 'name': '기존 마켓 연동',
                 'url': '/bundles/migrate', 'active_key': 'bundles_migrate', 'badge_key': None},
            ]},
            {'id': 's_mapping', 'emoji': '🔗', 'name': '매핑 현황', 'color': '#FF9500',
             'collapsed': False, 'items': [
                # [2026-06-30 단일명부 통합] 소싱처 운영센터 사이드바 숨김(코드·라우트 보존, 가역).
                #   명부=소싱처 사전으로 통일. 직접 /sources 접근은 유지.
                {'id': 'i_queue', 'emoji': '🔍', 'name': '미맵핑 큐',
                 'url': '/queue', 'active_key': 'queue', 'badge_key': 'unmapped'},
                {'id': 'i_mapping', 'emoji': '🔗', 'name': '맵핑',
                 'url': '/mapping/', 'active_key': 'mapping', 'badge_key': None},
            ]},
            {'id': 's_crawl', 'emoji': '🛒', 'name': '마켓 관리', 'color': '#03C75A',
             'collapsed': False, 'items': [
                {'id': 'i_crawl_guide', 'emoji': '🗒', 'name': '소싱처 관리',
                 'url': '/sourcing-guide/', 'active_key': 'sourcing_guide', 'badge_key': None},
                # [2026-06-30] 소싱처 사전 제거(가이드 통합) + 업로드 실패함 제거(사용자 요청).
                #   탭명: 크롤링 가이드→소싱처 관리 / 판매처 계정→판매처 관리. 라우트는 보존.
                {'id': 'i_mk_acct', 'emoji': '🏪', 'name': '판매처 관리',
                 'url': '/accounts/upload', 'active_key': 'accounts_upload', 'badge_key': None},
            ]},
            {'id': 's_buy', 'emoji': '🛍', 'name': '구매', 'color': '#EF4444',
             'collapsed': False, 'items': [
                {'id': 'i_track', 'emoji': '📈', 'name': '가격·재고 추적',
                 'url': '/track', 'active_key': 'track', 'badge_key': None},
            ]},
            {'id': 's_sell', 'emoji': '💰', 'name': '판매', 'color': '#A855F7',
             'collapsed': False, 'items': [
                {'id': 'i_templates', 'emoji': '📄', 'name': '템플릿',
                 'url': '/templates', 'active_key': 'templates', 'badge_key': None},
                {'id': 'i_orders', 'emoji': '📦', 'name': '주문 내역',
                 'url': '/orders/?tab=list', 'active_key': 'orders_list', 'badge_key': None},
                # [2026-07-16] 정산·매출(i_sales) 제거(사용자 요청) + 문의·반품→CS 이름변경.
                #   순서는 그대로: 템플릿 → 주문 내역 → CS → 신규 상품 등록 → 마진 계산기.
                {'id': 'i_cs', 'emoji': '💬', 'name': 'CS',
                 'url': '/orders/?tab=cs', 'active_key': 'orders_cs', 'badge_key': None},
                {'id': 'i_register', 'emoji': '🆕', 'name': '신규 상품 등록',
                 'url': '/orders/?tab=register', 'active_key': 'orders_register', 'badge_key': None},
                {'id': 'i_margin', 'emoji': '📊', 'name': '마진 계산기',
                 'url': '/orders/?tab=margin', 'active_key': 'orders_margin', 'badge_key': None},
            ]},
            {'id': 's_etc', 'emoji': '⚙️', 'name': '기타', 'color': '#6B7280',
             'collapsed': False, 'items': [
                {'id': 'i_trash', 'emoji': '🗑', 'name': '휴지통·변경 이력',
                 'url': '/trash', 'active_key': 'trash', 'badge_key': None},
                {'id': 'i_alerts', 'emoji': '🔔', 'name': '알림 채널 설정',
                 'url': '/alerts', 'active_key': 'alerts', 'badge_key': None},
            ]},
        ],
    }


# mtime 기반 인메모리 캐시 — sidebar 는 매 페이지 렌더에서 호출되므로
# 디스크 read + JSON parse 비용이 누적. mtime 동일하면 캐시된 dict 반환.
# PUT/reset 시 파일이 갱신 → mtime 변경 → 다음 호출에서 재로드. 자동.
_layout_cache: dict = {'mtime': 0.0, 'data': None}


def _remove_inspect(layout: dict) -> bool:
    """배송검사가 주문 내역으로 흡수됨 → 저장 메뉴에 남은 '배송검사'(i_inspect) 항목 제거(idempotent).

    (구분자 매핑 설정은 주문 내역 상단 「구분자 매핑」 버튼으로 접근.)
    """
    changed = False
    for st in layout.get('stages') or []:
        items = st.get('items') or []
        new = [it for it in items if it.get('id') != 'i_inspect']
        if len(new) != len(items):
            st['items'] = new
            changed = True
    return changed


def _migrate_sell_group(layout: dict) -> bool:
    """[2026-07-16] 판매 그룹 정리(저장된 레이아웃에도 반영, idempotent):
      · 정산·매출(i_sales) 항목 제거 — 사용자 요청.
      · 문의·반품(i_cs) 이름 → 'CS' (옛 이름일 때만 교체, 사용자가 손댄 이름 보존 X → 확정 변경).
    """
    changed = False
    for st in layout.get('stages') or []:
        items = st.get('items') or []
        new = [it for it in items if it.get('id') != 'i_sales']
        if len(new) != len(items):
            st['items'] = new
            items = new
            changed = True
        for it in items:
            if it.get('id') == 'i_cs' and it.get('name') in ('문의·반품', '문의/반품', '문의반품'):
                it['name'] = 'CS'
                changed = True
    return changed


def _load() -> dict:
    """파일에서 로드. 없으면 기본값 생성·저장. mtime 캐시 적용."""
    if not LAYOUT_PATH.exists():
        layout = _default_layout()
        _save(layout)
        _layout_cache['data'] = layout
        try:
            _layout_cache['mtime'] = LAYOUT_PATH.stat().st_mtime
        except OSError:
            _layout_cache['mtime'] = 0.0
        return layout
    try:
        mtime = LAYOUT_PATH.stat().st_mtime
        if _layout_cache['data'] is not None and _layout_cache['mtime'] == mtime:
            return _layout_cache['data']
        with open(LAYOUT_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _mig1 = _remove_inspect(data)      # 배송검사 주문내역 흡수 → 저장 메뉴의 별도 항목 제거(1회)
        _mig2 = _migrate_sell_group(data)  # 정산·매출 제거 + 문의·반품→CS(1회)
        if _mig1 or _mig2:
            _save(data)
            try:
                mtime = LAYOUT_PATH.stat().st_mtime
            except OSError:
                pass
        _layout_cache['data'] = data
        _layout_cache['mtime'] = mtime
        return data
    except (json.JSONDecodeError, OSError):
        return _default_layout()


def _save(layout: dict) -> None:
    layout['updated_at'] = datetime.now().isoformat(timespec='seconds')
    LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LAYOUT_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)
    tmp.replace(LAYOUT_PATH)


def _validate(layout: dict) -> tuple[bool, str]:
    """무결성 검증 — id 유니크, 필수 필드 존재."""
    if not isinstance(layout, dict):
        return False, 'layout must be object'
    if 'stages' not in layout or not isinstance(layout['stages'], list):
        return False, 'stages must be list'
    if 'standalone' not in layout or not isinstance(layout['standalone'], list):
        return False, 'standalone must be list'
    seen_ids: set[str] = set()
    for it in layout['standalone']:
        if not isinstance(it, dict) or 'id' not in it:
            return False, 'standalone item missing id'
        if it['id'] in seen_ids:
            return False, f"duplicate id: {it['id']}"
        seen_ids.add(it['id'])
    for st in layout['stages']:
        if not isinstance(st, dict) or 'id' not in st:
            return False, 'stage missing id'
        if st['id'] in seen_ids:
            return False, f"duplicate id: {st['id']}"
        seen_ids.add(st['id'])
        for it in st.get('items', []):
            if not isinstance(it, dict) or 'id' not in it:
                return False, 'item missing id'
            if it['id'] in seen_ids:
                return False, f"duplicate id: {it['id']}"
            seen_ids.add(it['id'])
    return True, ''


# 로드맵 탭 — 저장된 레이아웃에 없으면 렌더 시 standalone 끝에 주입(저장은 안 함).
#   기존 사용자 레이아웃을 건드리지 않고 모두에게 항상 보이게 함.
_ROADMAP_ITEM = {'id': 'i_roadmap', 'emoji': '🗺', 'name': '로드맵',
                 'url': '/roadmap', 'active_key': 'roadmap', 'badge_key': None}

# 크롤링 가이드 탭 — s_crawl 기본 레이아웃에 이미 포함됨.
# 이 상수는 구형 커스텀 레이아웃(i_crawl_guide 없는 저장분)에 대한 폴백 주입용.
_CRAWL_GUIDE_ITEM = {'id': 'i_crawl_guide', 'emoji': '🗒', 'name': '소싱처 관리',
                     'url': '/sourcing-guide/', 'active_key': 'sourcing_guide', 'badge_key': None}

# 판매처 연동 탭 — 연동 현황 대시보드 진입점. 저장 레이아웃에 없으면 렌더 시
#   '모음전 구성'(s_bundles) 스테이지 끝에 주입(저장 안 함). 사용자가 옮기면 그 위치 존중.
_SETS_DASH_ITEM = {'id': 'i_sets_dash', 'emoji': '🏬', 'name': '판매처 연동',
                   'url': '/api/sets/dashboard', 'active_key': 'sets_dashboard',
                   'badge_key': 'sets_alerts'}

_AUTOMATION_ITEM = {'id': 'i_automation', 'emoji': '⚙️', 'name': '자동화 설정',
                    'url': '/automation', 'active_key': 'automation',
                    'badge_key': None}

_AUTOMATION_LOG_ITEM = {'id': 'i_automation_log', 'emoji': '📜', 'name': '자동화 로그기록',
                        'url': '/automation/log', 'active_key': 'automation_log',
                        'badge_key': None}

# 데이터 가이드 — '기타'(s_etc) 끝에 주입(저장 안 함). 참고용 전체 데이터 흐름·탭별 지도.
#   크롤 전용 /sourcing-guide/map(데이터·코드 지도)과 별개 — 프로그램 전체 참고 문서.
_DATA_GUIDE_ITEM = {'id': 'i_data_guide', 'emoji': '📖', 'name': '데이터 가이드',
                    'url': '/data-guide', 'active_key': 'data_guide', 'badge_key': None}

# 실전송 테스트 — '마켓 관리'(s_crawl) 끝에 주입(저장 안 함). 한 구성만 실제 판매처로
#   가격·재고를 안전 전송하는 전용 화면(기본 드라이런·3중 게이트).
_LIVE_SEND_TEST_ITEM = {'id': 'i_live_send_test', 'emoji': '🚀', 'name': '실전송 테스트',
                        'url': '/live-send-test', 'active_key': 'live_send_test',
                        'badge_key': None}


def _has_item_id(layout: dict, item_id: str) -> bool:
    def _has(items):
        return any(isinstance(i, dict) and i.get('id') == item_id for i in items)
    if _has(layout.get('standalone', [])):
        return True
    return any(_has(st.get('items', [])) for st in layout.get('stages', []))


def _has_roadmap(layout: dict) -> bool:
    return _has_item_id(layout, 'i_roadmap')


def get_layout_for_template() -> dict:
    """템플릿 렌더 시 호출 — sidebar.html context 용. 로드맵·크롤링가이드 탭 항상 주입."""
    layout = _load()
    out = dict(layout)

    # [2026-06-30] 사이드바 정리 — 운영센터(i_sources)·미맵핑큐(i_queue)·맵핑(i_mapping)
    #   렌더 시 숨김(코드·라우트는 보존, 가역). 필터 후 빈 스테이지(예: 매핑 현황)는 통째 제거.
    _hidden_ids = {'i_sources', 'i_queue', 'i_mapping', 'i_src_dict', 'i_dlq'}
    _stages = []
    for st in out.get('stages', []):
        items = [it for it in st.get('items', []) if it.get('id') not in _hidden_ids]
        if not items:
            continue                                 # 항목이 모두 숨겨진 빈 스테이지 제거
        _stages.append({**st, 'items': items})
    out['stages'] = _stages

    # 로드맵 — standalone 끝에 주입
    if not _has_roadmap(layout):
        out['standalone'] = list(layout.get('standalone', [])) + [dict(_ROADMAP_ITEM)]

    # 크롤링 가이드 — 크롤링&업로드 스테이지(s_crawl) 끝에 주입(없을 때만)
    if not _has_item_id(layout, 'i_crawl_guide'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_crawl':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_CRAWL_GUIDE_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    # 판매처 연동 — 모음전 구성 스테이지(s_bundles) 끝에 주입(없을 때만)
    if not _has_item_id(layout, 'i_sets_dash'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_bundles':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_SETS_DASH_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    if not _has_item_id(layout, 'i_automation'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_bundles':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_AUTOMATION_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    # 자동화 로그기록 — 자동화 설정 바로 뒤(s_bundles 끝)에 주입(없을 때만)
    if not _has_item_id(layout, 'i_automation_log'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_bundles':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_AUTOMATION_LOG_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    # 데이터 가이드 — '기타'(s_etc) 스테이지 끝에 주입(없을 때만). 참고용 전체 데이터 흐름·탭별 지도.
    if not _has_item_id(layout, 'i_data_guide'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_etc':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_DATA_GUIDE_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    # 실전송 테스트 — '마켓 관리'(s_crawl) 스테이지 끝에 주입(없을 때만).
    if not _has_item_id(layout, 'i_live_send_test'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's_crawl':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_LIVE_SEND_TEST_ITEM)]
            new_stages.append(st)
        out['stages'] = new_stages

    return out


@bp.get('/layout')
def api_get_layout():
    return jsonify(_load())


@bp.put('/layout')
def api_put_layout():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'ok': False, 'error': 'invalid JSON'}), 400
    ok, msg = _validate(payload)
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400
    payload['version'] = 1
    with _lock:
        _save(payload)
    return jsonify({'ok': True, 'updated_at': payload['updated_at']})


@bp.post('/layout/reset')
def api_reset_layout():
    with _lock:
        layout = _default_layout()
        _save(layout)
    return jsonify({'ok': True, 'layout': layout})
