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


# ════════════════════════════════════════════════════════════
#  [2026-07-30] 노션 8분류 재편 — 단일 진실 원천
#    기본값·마이그레이션이 **같은 스펙**을 쓴다. 한 곳만 고치면 둘 다 반영.
#    (이전: 기본값과 「없으면 주입」 상수가 갈려 있어 라이브에 안 나오는 사고 반복)
# ════════════════════════════════════════════════════════════

# 항목 정의 — id → 표시·이동 정보. 저장 레이아웃에 이미 있으면 사용자가 고친 값을 우선.
_ITEM_DEFS: dict[str, dict] = {
    'i_new':            {'emoji': '➕', 'name': '신규 모음전 등록', 'url': '/bundles/new',           'active_key': 'bundles_new',     'badge_key': None},
    'i_bundles':        {'emoji': '📋', 'name': '모음전 구성',      'url': '/bundles',               'active_key': 'bundles',         'badge_key': None},
    'i_migrate':        {'emoji': '🔗', 'name': '기존 마켓 연동',   'url': '/bundles/migrate',       'active_key': 'bundles_migrate', 'badge_key': None},
    'i_sets_dash':      {'emoji': '🏬', 'name': '판매처 연동',      'url': '/api/sets/dashboard',    'active_key': 'sets_dashboard',  'badge_key': 'sets_alerts'},
    'i_matrix':         {'emoji': '🧱', 'name': '매트릭스 옵션',    'url': '/matrix',                'active_key': 'matrix',          'badge_key': None},
    'i_policies':       {'emoji': '🔧', 'name': '정책 생성',        'url': '/policies',              'active_key': 'policies',        'badge_key': None},
    'i_templates':      {'emoji': '💲', 'name': '가격 정책',        'url': '/templates',             'active_key': 'templates',       'badge_key': None},
    'i_automation':     {'emoji': '⚙️', 'name': '수집·전송 자동화', 'url': '/automation',            'active_key': 'automation',      'badge_key': None},
    'i_catalog':        {'emoji': '📦', 'name': '상품관리',         'url': '/catalog/',              'active_key': 'catalog',         'badge_key': None},
    'i_orders':         {'emoji': '📋', 'name': '주문 내역',        'url': '/orders/?tab=list',      'active_key': 'orders_list',     'badge_key': None},
    'i_ship':           {'emoji': '📦', 'name': '송장 작업',        'url': '/orders/?tab=ship',      'active_key': 'orders_ship',     'badge_key': None},
    'i_cs':             {'emoji': '💬', 'name': 'CS',               'url': '/orders/?tab=cs',        'active_key': 'orders_cs',       'badge_key': None},
    'i_margin':         {'emoji': '📊', 'name': '마진 계산기',      'url': '/orders/?tab=margin',    'active_key': 'orders_margin',   'badge_key': None},
    'i_inventory':      {'emoji': '🏷', 'name': '재고관리',         'url': '/inventory/',            'active_key': 'inventory',       'badge_key': None},
    'i_crawl_guide':    {'emoji': '🗒', 'name': '소싱처 관리',      'url': '/sourcing-guide/',       'active_key': 'sourcing_guide',  'badge_key': None},
    'i_mk_acct':        {'emoji': '🏪', 'name': '판매처 관리',      'url': '/accounts/upload',       'active_key': 'accounts_upload', 'badge_key': None},
    'i_live_send_test': {'emoji': '🚀', 'name': '실전송 테스트',    'url': '/live-send-test',        'active_key': 'live_send_test',  'badge_key': None},
    'i_trash':          {'emoji': '🗑', 'name': '휴지통·변경 이력', 'url': '/trash',                 'active_key': 'trash',           'badge_key': None},
    'i_alerts':         {'emoji': '🔔', 'name': '알림 채널 설정',   'url': '/alerts',                'active_key': 'alerts',          'badge_key': None},
    'i_data_guide':     {'emoji': '📖', 'name': '데이터 가이드',    'url': '/data-guide',            'active_key': 'data_guide',      'badge_key': None},
}

# 스테이지 스펙 — (id, 이모지, 이름, 색, 항목 id 순서). 노션 8분류 그대로.
_STAGE_SPEC: list[tuple] = [
    ('s_collect',   '📥', '상품수집·생성', '#3182F6', ['i_new', 'i_bundles', 'i_matrix', 'i_migrate', 'i_sets_dash']),
    ('s_process',   '🔧', '상품 가공',     '#F59E0B', ['i_policies', 'i_templates']),
    ('s_auto',      '⚙️', '자동화',        '#8B5CF6', ['i_automation']),
    ('s_catalog',   '📦', '상품 관리',     '#06B6D4', ['i_catalog']),
    ('s_order',     '🧾', '주문 관리',     '#A855F7', ['i_orders', 'i_ship', 'i_cs']),
    ('s_stats',     '📊', '통계·분석',     '#EC4899', ['i_margin']),
    ('s_inventory', '🏷', '재고관리',      '#10B981', ['i_inventory']),
    ('s_etc',       '⚙️', '기타',          '#6B7280', ['i_crawl_guide', 'i_mk_acct', 'i_live_send_test',
                                                       'i_trash', 'i_alerts', 'i_data_guide']),
]

# 없애기로 확정된 항목 — 마이그레이션에서 저장 레이아웃에서도 제거(사장님 확정 2026-07-30).
#   가격·재고 추적 / 신규 상품 등록(→①로 이관) / 자동화 로그기록 /
#   숨은 5탭(소싱처 운영센터·미맵핑 큐·맵핑·소싱처 사전·업로드 실패함) / 옛 잔재.
_REMOVED_IDS: set[str] = {
    'i_track', 'i_register', 'i_automation_log',
    'i_sources', 'i_queue', 'i_mapping', 'i_src_dict', 'i_dlq',
    'i_inspect', 'i_sales',
}

# 이름·이모지를 **강제로** 바꿀 항목 — 사용자가 고친 값이 있어도 덮어씀(의도된 개명).
#   i_templates: 「템플릿」 → 「가격 정책」 (2단계에서 정책 엔진이 대체할 자리)
#   ※ i_new 는 개명하지 않는다 — 화면이 아직 「신규 모음전 등록」 그대로다.
#     시안대로 된 「신규 상품 등록」은 2단계에서 만든다. 먼저 이름만 바꾸면 거짓 기능이 된다.
_FORCE_RENAME: set[str] = {'i_templates'}


def _item(item_id: str, saved: dict | None = None) -> dict:
    """항목 1개 생성. 저장본이 있으면 사용자가 고친 이모지·이름을 보존(개명 대상 제외)."""
    base = dict(_ITEM_DEFS[item_id])
    base['id'] = item_id
    if saved and item_id not in _FORCE_RENAME:
        for k in ('emoji', 'name'):
            if saved.get(k):
                base[k] = saved[k]
    return base


def _build_stages(saved_items: dict[str, dict] | None = None) -> list[dict]:
    """스펙 → stages. saved_items 가 있으면 사용자가 고친 표시값을 살린다."""
    saved_items = saved_items or {}
    out = []
    for sid, emoji, name, color, item_ids in _STAGE_SPEC:
        out.append({
            'id': sid, 'emoji': emoji, 'name': name, 'color': color, 'collapsed': False,
            'items': [_item(i, saved_items.get(i)) for i in item_ids],
        })
    return out


def _default_layout() -> dict:
    """노션 8분류 기본 레이아웃. 항목 url/active_key/badge 는 기존 페이지 그대로(이동만)."""
    return {
        'version': 1,
        'schema': 8,
        'updated_at': None,
        'standalone': [
            {'id': 'i_home', 'emoji': '⌂', 'name': '홈',
             'url': '/', 'active_key': 'home', 'badge_key': None},
        ],
        'stages': _build_stages(),
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


def _add_ship(layout: dict) -> bool:
    """[2026-07-24] 「📦 송장 작업」 메뉴 추가 — 주문 내역 바로 아래(idempotent).

    저장된 레이아웃이 기본값을 덮으므로, 기본값에만 넣으면 이미 쓰던 사람에게는
    메뉴가 영영 안 보인다(라이브 실측: 탭은 살아 있는데 메뉴가 없었다).
    주문 내역 아이콘도 📦 → 📋 로 바꾼다 — 둘 다 📦 면 무엇이 무엇인지 안 보인다.
    """
    changed = False
    for st in layout.get('stages') or []:
        items = st.get('items') or []
        if any(it.get('id') == 'i_ship' for it in items):
            continue
        for i, it in enumerate(items):
            if it.get('id') != 'i_orders':
                continue
            if it.get('emoji') == '📦':
                it['emoji'] = '📋'
            items.insert(i + 1, {
                'id': 'i_ship', 'emoji': '📦', 'name': '송장 작업',
                'url': '/orders/?tab=ship', 'active_key': 'orders_ship', 'badge_key': None})
            st['items'] = items
            changed = True
            break
    return changed


def _migrate_to_8groups(layout: dict) -> bool:
    """[2026-07-30] 저장 레이아웃을 노션 8분류로 재편(1회, idempotent).

    🔴 기본값만 고치면 라이브에 안 나온다 — 서버는 사장님이 드래그로 저장한 레이아웃을 쓴다.
       그래서 **저장본 자체를 갈아끼운다**. (api_sidebar.py:257 실사고 기록 참조)

    사용자가 고친 이모지·이름은 살리고(개명 확정분 제외), 스테이지 구성만 스펙대로 재배치.
    없애기로 한 항목(_REMOVED_IDS)은 저장본에서도 제거.
    """
    stages = layout.get('stages') or []
    if any(st.get('id') == 's_collect' for st in stages):
        return False                                   # 이미 재편됨
    saved_items: dict[str, dict] = {}
    for st in stages:
        for it in st.get('items') or []:
            iid = it.get('id')
            if iid and iid not in _REMOVED_IDS:
                saved_items.setdefault(iid, it)
    layout['stages'] = _build_stages(saved_items)
    layout['schema'] = 8
    return True


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
        _mig3 = _add_ship(data)            # 송장 작업 메뉴 추가 + 주문 내역 아이콘 📋(1회)
        _mig4 = _migrate_to_8groups(data)  # 노션 8분류 재편 + 삭제 확정분 제거(1회)
        if _mig1 or _mig2 or _mig3 or _mig4:
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

# [2026-07-30] 항목별 「없으면 주입」 상수 7종 삭제 — _STAGE_SPEC/_ITEM_DEFS 로 통합.
#   ★ 그 방식이 「data/sidebar_layout.json 만 고치면 라이브에 안 나온다」 사고의 원인이었다
#     (기본값·주입상수·저장본 3곳이 갈림). 이제 새 메뉴는 _STAGE_SPEC 한 곳에만 추가한다.


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

    # [2026-07-30] 없애기로 확정된 항목은 렌더에서도 한 번 더 거른다(저장본 마이그레이션의 이중 안전망).
    #   필터 후 빈 스테이지는 통째 제거.
    _stages = []
    for st in out.get('stages', []):
        items = [it for it in st.get('items', []) if it.get('id') not in _REMOVED_IDS]
        if not items:
            continue
        _stages.append({**st, 'items': items})
    out['stages'] = _stages

    # [2026-07-30] 스펙에 있는데 저장본에 없는 항목을 제자리에 주입 —
    #   항목마다 상수+if 블록을 따로 두던 방식을 스펙 1개로 통일(그 방식이 「기본값만 고쳐
    #   라이브에 안 나오는」 사고의 원인이었다). 새 메뉴는 _STAGE_SPEC 에만 추가하면 된다.
    _present = {it.get('id') for st in out.get('stages', []) for it in st.get('items', [])}
    _missing = {sid: [i for i in ids if i not in _present]
                for sid, _e, _n, _c, ids in _STAGE_SPEC}
    if any(_missing.values()):
        _by_id = {st.get('id'): st for st in out.get('stages', [])}
        _rebuilt = []
        for sid, emoji, name, color, ids in _STAGE_SPEC:
            st = _by_id.get(sid)
            if st is None:
                if not _missing[sid]:
                    continue
                st = {'id': sid, 'emoji': emoji, 'name': name, 'color': color, 'collapsed': False, 'items': []}
            else:
                st = dict(st)
            if _missing[sid]:
                # 이미 있는 항목의 순서는 건드리지 않는다 — 사장님이 드래그로 둔 자리가 곧 의도다.
                # 빠진 것만 스펙 순서대로 뒤에 붙인다.
                st['items'] = list(st.get('items', [])) + [_item(i) for i in _missing[sid]]
            _rebuilt.append(st)
        # 스펙에 없는 사용자 커스텀 스테이지는 뒤에 보존
        _spec_ids = {s[0] for s in _STAGE_SPEC}
        _rebuilt += [st for st in out.get('stages', []) if st.get('id') not in _spec_ids]
        out['stages'] = _rebuilt

    # 로드맵 — standalone 끝에 주입
    if not _has_roadmap(layout):
        out['standalone'] = list(layout.get('standalone', [])) + [dict(_ROADMAP_ITEM)]

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
