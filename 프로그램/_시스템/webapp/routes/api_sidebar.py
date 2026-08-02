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
    # [2026-08-02] 노션 「상품 생성 (옵션 생성 & 상품 생성)」 하위탭 3개 그대로.
    #   🔴 항목이 하나면 펼침 메뉴에 한 줄만 뜬다 — 사장님이 라이브에서 잡았다.
    #      노션 원문은 하위탭 3개(직접 / 내마켓 불러오기 / 상품 생성)다.
    'i_optgen_direct':  {'emoji': '✏️', 'name': '모음전 옵션 생성 (직접)', 'url': '/optgen?tab=direct',  'active_key': 'optgen_direct',   'badge_key': None},
    'i_optgen_market':  {'emoji': '🏪', 'name': '모음전 옵션 생성 (내마켓 불러오기)', 'url': '/optgen?tab=market', 'active_key': 'optgen_market', 'badge_key': None},
    'i_optgen_product': {'emoji': '📦', 'name': '모음전 상품 생성', 'url': '/optgen?tab=product',     'active_key': 'optgen_product',  'badge_key': None},
    'i_bundles':        {'emoji': '📋', 'name': '모음전 상품관리',   'url': '/bundles',               'active_key': 'bundles',         'badge_key': None},
    'i_matrix':         {'emoji': '🧱', 'name': '모음전 옵션관리',   'url': '/matrix',                'active_key': 'matrix',          'badge_key': None},
    # [2026-07-31] 노션 「(이름변경(기존): 마켓별 정책) → 정책 생성」
    'i_policies':       {'emoji': '🔧', 'name': '정책 생성',        'url': '/policies',              'active_key': 'policies',        'badge_key': None},
    # [2026-08-01] 노션 「상품 가공」 하위탭 ② — 상품 고르고 정책 붙이기
    'i_policy_apply':   {'emoji': '🧩', 'name': '상품 정책 적용',  'url': '/policies/apply',        'active_key': 'policy_apply',    'badge_key': None},
    'i_templates':      {'emoji': '💲', 'name': '가격 정책',        'url': '/templates',             'active_key': 'templates',       'badge_key': None},
    # [2026-08-02] 「자동화」 분류 → 「상품 마켓 전송」 하위탭 2개 (사장님 확정 ⑤).
    #   ① 마켓 전송 = 골라서 지금 보내기(더망고식) / ② 자동화 = 저절로 돌기(지금 화면)
    'i_market_send':    {'emoji': '📤', 'name': '마켓 전송',        'url': '/market-send',           'active_key': 'market_send',     'badge_key': None},
    'i_automation':     {'emoji': '⚙️', 'name': '자동화',           'url': '/automation',            'active_key': 'automation',      'badge_key': None},
    'i_catalog':        {'emoji': '📦', 'name': '마켓 상품 현황',    'url': '/catalog/',              'active_key': 'catalog',         'badge_key': None},
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
    # [2026-08-02] 노션 투두 일일보고 점검 화면. 여태 **어느 메뉴에도 링크가 없어**
    #   사장님이 주소를 직접 쳐야만 들어갈 수 있었다(사장님 지적으로 발견).
    'i_notion_report':  {'emoji': '📅', 'name': '노션 일일보고',    'url': '/reports/notion-todo',   'active_key': 'notion_report',   'badge_key': None},
}

# 스테이지 스펙 — (id, 이모지, 이름, 색, 항목 id 순서). 노션 8분류 그대로.
_STAGE_SPEC: list[tuple] = [
    ('s_collect',   '📥', '옵션생성 & 상품생성', '#3182F6', ['i_optgen_direct', 'i_optgen_market',
                                                              'i_optgen_product']),
    ('s_process',   '🔧', '상품 가공',     '#F59E0B', ['i_policies', 'i_policy_apply', 'i_templates']),
    ('s_auto',      '📤', '상품 마켓 전송', '#8B5CF6', ['i_market_send', 'i_automation']),
    ('s_catalog',   '📦', '상품 관리',     '#06B6D4', ['i_bundles', 'i_matrix', 'i_catalog']),
    ('s_order',     '🧾', '주문 관리',     '#A855F7', ['i_orders', 'i_ship', 'i_cs']),
    ('s_stats',     '📊', '통계·분석',     '#EC4899', ['i_margin']),
    ('s_inventory', '🏷', '재고관리',      '#10B981', ['i_inventory']),
    ('s_etc',       '⚙️', '기타',          '#6B7280', ['i_crawl_guide', 'i_mk_acct', 'i_live_send_test',
                                                       'i_trash', 'i_alerts', 'i_data_guide',
                                                       'i_notion_report']),
]

# 없애기로 확정된 항목 — 마이그레이션에서 저장 레이아웃에서도 제거(사장님 확정 2026-07-30).
#   가격·재고 추적 / 신규 상품 등록(→①로 이관) / 자동화 로그기록 /
#   숨은 5탭(소싱처 운영센터·미맵핑 큐·맵핑·소싱처 사전·업로드 실패함) / 옛 잔재.
_REMOVED_IDS: set[str] = {
    'i_track', 'i_register', 'i_automation_log',
    'i_sources', 'i_queue', 'i_mapping', 'i_src_dict', 'i_dlq',
    'i_inspect', 'i_sales',
    # [2026-08-01] 사장님 확정 — 신규 모음전 등록 / 기존 마켓 연동 / 판매처 연동
    'i_new', 'i_migrate', 'i_sets_dash',
    # [2026-08-02] 하위탭 3개로 갈라짐 → 합쳐져 있던 옛 항목. 저장본에 남아 있어도 안 뜬다.
    'i_optgen',
}

#: 「옵션생성 & 상품생성」 항목 id — 옛것(합본) + 지금것(하위탭 3개).
#  🔴 마이그레이션의 「이미 했나」 판정에 쓴다. 옛 id 하나만 보면, 3개로 갈라진 뒤
#     그 id 가 사라져 옛 마이그레이션이 **다시 돌고** 상품관리에 i_bundles·i_matrix 가
#     겹쳐 들어간다(id 중복 → 저장 검증 실패).
_OPTGEN_ITEM_IDS: tuple[str, ...] = ('i_optgen', 'i_optgen_direct',
                                     'i_optgen_market', 'i_optgen_product')
#: 지금 쓰는 하위탭 3개 — 노션 원문 순서 그대로.
_OPTGEN3: tuple[str, ...] = ('i_optgen_direct', 'i_optgen_market', 'i_optgen_product')

# 이름·이모지를 **강제로** 바꿀 항목 — 사용자가 고친 값이 있어도 덮어씀(의도된 개명).
#   i_templates: 「템플릿」 → 「가격 정책」 (2단계에서 정책 엔진이 대체할 자리)
#   [2026-08-01] i_bundles·i_matrix·i_catalog: 상품관리 3탭으로 이동하며 개명.
#     사장님이 예전에 고쳐둔 옛 이름이 남아 있으면 옮긴 뜻이 안 보인다.
# [2026-07-31] i_policies 추가 — 노션 「(이름변경(기존): 마켓별 정책) → 정책 생성」.
#   🔴 여기 안 넣으면 **라이브에 저장된 옛 이름이 이겨서** 화면에 그대로 「마켓별 정책」이
#     남는다. 코드만 고치고 끝냈다고 착각하기 딱 좋은 자리다.
#   [2026-08-02] i_automation: 「수집·전송 자동화」 → 「자동화」.
#     하위탭 2개로 갈리면서 이름이 짧아졌다. 여기 안 넣으면 저장본의 옛 긴 이름이
#     이겨서 화면엔 그대로 「수집·전송 자동화」가 남는다(i_policies 때 그 자리).
_FORCE_RENAME: set[str] = {'i_templates', 'i_bundles', 'i_matrix', 'i_catalog',
                           'i_policies', 'i_policy_apply', 'i_automation'}

#: 「상품 마켓 전송」 하위탭 2개 — 화면 가로탭(`market_send.SUBTABS`)과 **같은 순서**여야 한다.
#  🔴 두 곳을 같이 안 고치면 메뉴만 옛것으로 남는다(optgen 하위탭 때 실제로 겪은 함정).
_SEND2: tuple[str, ...] = ('i_market_send', 'i_automation')


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


def _migrate_optgen(layout: dict) -> bool:
    """[2026-08-01] 「상품수집·생성」 → 「옵션생성 & 상품생성」 재편(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 사장님이 드래그로
       저장한 레이아웃을 쓴다. 그래서 **저장본 자체를 갈아끼운다.**

    · 수집 스테이지 항목을 i_optgen 하나로
    · i_bundles(모음전 상품관리) · i_matrix(모음전 옵션관리) 는 상품관리로 이동
    · 삭제 확정분(i_new · i_migrate · i_sets_dash)은 _REMOVED_IDS 가 렌더에서 거르지만,
      저장본에서도 빼서 다음 저장 때 되살아나지 않게 한다.
    """
    # 🔴 옛 id 하나만 보면 안 된다 — 아래 _migrate_optgen3 가 그 id 를 3개로 갈라
    #    없애므로, 다음 로드 때 이 마이그레이션이 다시 돌아 상품관리에 항목이 겹친다.
    if any(_has_item_id(layout, i) for i in _OPTGEN_ITEM_IDS):
        return False                                   # 이미 재편됨

    stages = layout.get('stages') or []
    moved: dict[str, dict] = {}
    for st in stages:
        keep = []
        for it in st.get('items') or []:
            iid = it.get('id')
            if iid in ('i_bundles', 'i_matrix'):
                moved.setdefault(iid, it)              # 어느 스테이지에 있든 뽑아낸다
                continue
            if iid in _REMOVED_IDS:
                continue
            # 🔴 강제 개명은 **이미 저장본에 있던** 항목에도 걸어야 한다.
            #   옮겨오는 항목만 개명하면, 제자리에 있던 i_catalog 가 옛 이름
            #   「상품관리」 그대로 떴다(라이브에서 잡음).
            keep.append(_item(iid, it) if iid in _FORCE_RENAME else it)
        st['items'] = keep

    for st in stages:
        if st.get('id') == 's_collect':
            st['emoji'], st['name'] = '📥', '옵션생성 & 상품생성'
            st['items'] = [_item(i) for i in _OPTGEN3]
            break
    else:
        stages.append({'id': 's_collect', 'emoji': '📥', 'name': '옵션생성 & 상품생성',
                       'color': '#3182F6', 'collapsed': False,
                       'items': [_item(i) for i in _OPTGEN3]})

    cat = next((st for st in stages if st.get('id') == 's_catalog'), None)
    if cat is None:
        cat = {'id': 's_catalog', 'emoji': '📦', 'name': '상품 관리',
               'color': '#06B6D4', 'collapsed': False, 'items': []}
        stages.append(cat)
    cat['items'] = ([_item(i, moved.get(i)) for i in ('i_bundles', 'i_matrix')]
                    + list(cat.get('items') or []))

    layout['stages'] = stages
    return True


def _migrate_optgen3(layout: dict) -> bool:
    """[2026-08-02] 「옵션생성 & 상품생성」 합본 1개 → 노션 하위탭 3개(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 저장본을 쓴다.
       그래서 **저장본 자체를 갈아끼운다.** (i_policies 때와 같은 자리의 함정)

    사장님 실측: 상단 메뉴 「옵션생성 & 상품생성」 을 펼치면 한 줄만 떴다.
    노션 원문은 하위탭 3개 — 직접 / 내마켓 불러오기 / 상품 생성.
    """
    if _has_item_id(layout, 'i_optgen_direct'):
        return False                                   # 이미 갈라짐

    stages = layout.get('stages') or []
    # 합본 항목은 어느 스테이지에 있든 걷어낸다(사장님이 드래그로 옮겨놨을 수 있다).
    for st in stages:
        st['items'] = [it for it in (st.get('items') or [])
                       if it.get('id') != 'i_optgen']
    layout['standalone'] = [it for it in (layout.get('standalone') or [])
                            if it.get('id') != 'i_optgen']

    for st in stages:
        if st.get('id') == 's_collect':
            st['items'] = [_item(i) for i in _OPTGEN3] + list(st.get('items') or [])
            break
    else:
        stages.append({'id': 's_collect', 'emoji': '📥', 'name': '옵션생성 & 상품생성',
                       'color': '#3182F6', 'collapsed': False,
                       'items': [_item(i) for i in _OPTGEN3]})

    layout['stages'] = stages
    return True


def _migrate_send2(layout: dict) -> bool:
    """[2026-08-02] 「자동화」 분류 → 「상품 마켓 전송」 + 하위탭 2개(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 **저장본**을 쓴다.
       optgen 하위탭 때 겪은 그 자리라, 저장본 자체를 갈아끼운다.

    분류 이름·이모지도 바꾼다 — 항목만 넣고 이름을 두면 「자동화」 안에 「마켓 전송」이
    들어앉아 무슨 분류인지 알 수 없다.
    """
    if _has_item_id(layout, 'i_market_send'):
        return False                                   # 이미 들어감

    stages = layout.get('stages') or []
    for st in stages:
        if st.get('id') != 's_auto':
            continue
        st['emoji'], st['name'] = '📤', '상품 마켓 전송'
        # 저장본에 있던 i_automation 은 사장님이 고친 이모지가 있을 수 있어 살려 옮긴다.
        #   (다만 이름은 _FORCE_RENAME 이 「자동화」로 덮는다 — 의도된 개명)
        saved = {it.get('id'): it for it in (st.get('items') or [])}
        st['items'] = [_item(i, saved.get(i)) for i in _SEND2]
        layout['stages'] = stages
        return True

    # s_auto 가 통째로 없는 저장본(옛 레이아웃) — 분류째로 만들어 넣는다.
    stages.append({'id': 's_auto', 'emoji': '📤', 'name': '상품 마켓 전송',
                   'color': '#8B5CF6', 'collapsed': False,
                   'items': [_item(i) for i in _SEND2]})
    layout['stages'] = stages
    return True


def _migrate_notion_report(layout: dict) -> bool:
    """[2026-08-02] 「📅 노션 일일보고」 메뉴 추가 — 기타 분류 맨 아래(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 **저장본**을 쓴다.
       (i_ship·i_policies·optgen 하위탭 때 반복된 그 자리)

    여태 이 화면은 **어느 메뉴에도 링크가 없어** 주소를 직접 쳐야 들어갔다.
    """
    if _has_item_id(layout, 'i_notion_report'):
        return False

    stages = layout.get('stages') or []
    for st in stages:
        if st.get('id') == 's_etc':
            st['items'] = list(st.get('items') or []) + [_item('i_notion_report')]
            layout['stages'] = stages
            return True

    # 기타 분류가 통째로 없는 저장본 — 분류째로 만들어 넣는다.
    stages.append({'id': 's_etc', 'emoji': '⚙️', 'name': '기타',
                   'color': '#6B7280', 'collapsed': False,
                   'items': [_item('i_notion_report')]})
    layout['stages'] = stages
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
        _mig5 = _migrate_optgen(data)      # [2026-08-01] 옵션생성 & 상품생성 재편(1회)
        _mig6 = _migrate_optgen3(data)     # [2026-08-02] 합본 1개 → 하위탭 3개(1회)
        _mig7 = _migrate_send2(data)       # [2026-08-02] 자동화 → 상품 마켓 전송 2탭(1회)
        _mig8 = _migrate_notion_report(data)  # [2026-08-02] 노션 일일보고 메뉴 추가(1회)
        if _mig1 or _mig2 or _mig3 or _mig4 or _mig5 or _mig6 or _mig7 or _mig8:
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
