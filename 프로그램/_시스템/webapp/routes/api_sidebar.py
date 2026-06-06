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
    """기존 sidebar.html 의 18개 메뉴를 A1 4스테이지 + 독립 1개로 재배치한 기본값."""
    return {
        'version': 1,
        'updated_at': None,
        'standalone': [
            {'id': 'i_home', 'emoji': '⌂', 'name': '홈',
             'url': '/', 'active_key': 'home', 'badge_key': None},
        ],
        'stages': [
            {'id': 's1', 'emoji': '🛒', 'name': '소싱·발견', 'color': '#FF9500',
             'collapsed': False, 'items': [
                {'id': 'i_sources', 'emoji': '🏠', 'name': '소싱처 운영센터',
                 'url': '/sources', 'active_key': 'sources', 'badge_key': None},
                {'id': 'i_queue', 'emoji': '🔍', 'name': '미맵핑 큐',
                 'url': '/queue', 'active_key': 'queue', 'badge_key': 'unmapped'},
                {'id': 'i_src_dict', 'emoji': '📖', 'name': '소싱처 사전',
                 'url': '/source-registry', 'active_key': 'source_registry', 'badge_key': None},
                {'id': 'i_src_acct', 'emoji': '🔑', 'name': '소싱처 계정',
                 'url': '/accounts/sourcing', 'active_key': 'accounts_sourcing', 'badge_key': None},
                {'id': 'i_crawl_guide', 'emoji': '🗒', 'name': '크롤링 가이드',
                 'url': '/sourcing-guide/', 'active_key': 'sourcing_guide', 'badge_key': None},
            ]},
            {'id': 's2', 'emoji': '📦', 'name': '모음전 등록', 'color': '#3182F6',
             'collapsed': False, 'items': [
                {'id': 'i_new', 'emoji': '➕', 'name': '신규 모음전 등록',
                 'url': '/bundles/new', 'active_key': 'bundles_new', 'badge_key': None},
                {'id': 'i_bundles', 'emoji': '📋', 'name': '모음전 상품관리',
                 'url': '/bundles', 'active_key': 'bundles', 'badge_key': None},
                {'id': 'i_migrate', 'emoji': '🔗', 'name': '기존 마켓 연동',
                 'url': '/bundles/migrate', 'active_key': 'bundles_migrate', 'badge_key': None},
                {'id': 'i_templates', 'emoji': '📄', 'name': '템플릿',
                 'url': '/templates', 'active_key': 'templates', 'badge_key': None},
                {'id': 'i_mapping', 'emoji': '🔗', 'name': '맵핑',
                 'url': '/mapping/', 'active_key': 'mapping', 'badge_key': None},
            ]},
            {'id': 's3', 'emoji': '🛍', 'name': '판매·운영', 'color': '#03C75A',
             'collapsed': False, 'items': [
                {'id': 'i_dlq', 'emoji': '⚠️', 'name': '업로드 실패함',
                 'url': '/dlq', 'active_key': 'dlq', 'badge_key': 'failed'},
                {'id': 'i_track', 'emoji': '📈', 'name': '가격·재고 추적',
                 'url': '/track', 'active_key': 'track', 'badge_key': None},
                {'id': 'i_orders', 'emoji': '📦', 'name': '주문 내역',
                 'url': '/orders/?tab=list', 'active_key': 'orders_list', 'badge_key': None},
                {'id': 'i_mk_upload', 'emoji': '⬆️', 'name': '마켓 업로드 설정',
                 'url': '/market-upload-config', 'active_key': 'market_upload', 'badge_key': None},
            ]},
            {'id': 's4', 'emoji': '💰', 'name': '정산·관리', 'color': '#A855F7',
             'collapsed': False, 'items': [
                {'id': 'i_sales', 'emoji': '💵', 'name': '매출 관리',
                 'url': '/orders/?tab=sales', 'active_key': 'orders_sales', 'badge_key': None},
                {'id': 'i_margin', 'emoji': '📊', 'name': '마진 계산기',
                 'url': '/orders/?tab=margin', 'active_key': 'orders_margin', 'badge_key': None},
                {'id': 'i_mk_acct', 'emoji': '🏪', 'name': '판매처 계정',
                 'url': '/accounts/upload', 'active_key': 'accounts_upload', 'badge_key': None},
                {'id': 'i_boxhero', 'emoji': '📥', 'name': '사입 재고 연동',
                 'url': '/boxhero', 'active_key': 'boxhero', 'badge_key': None},
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

# 크롤링 가이드 탭 — 소싱·발견(s1) 스테이지 끝에 항상 주입.
_CRAWL_GUIDE_ITEM = {'id': 'i_crawl_guide', 'emoji': '🗒', 'name': '크롤링 가이드',
                     'url': '/sourcing-guide/', 'active_key': 'sourcing_guide', 'badge_key': None}


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

    # 로드맵 — standalone 끝에 주입
    if not _has_roadmap(layout):
        out['standalone'] = list(layout.get('standalone', [])) + [dict(_ROADMAP_ITEM)]

    # 크롤링 가이드 — 소싱 스테이지(s1) 끝에 주입
    if not _has_item_id(layout, 'i_crawl_guide'):
        new_stages = []
        for st in out.get('stages', []):
            if st.get('id') == 's1':
                st = dict(st)
                st['items'] = list(st.get('items', [])) + [dict(_CRAWL_GUIDE_ITEM)]
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
