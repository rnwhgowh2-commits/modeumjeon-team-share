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
    # [2026-08-02 사장님 확정] 「대량등록」 — 오른쪽 바로가기(C안).
    #   ★ 묶음(stage) 안에 넣지 않는다. 대량등록 화면 **안에** 「상품관리·주문관리·통계」가
    #     따로 또 있어, 묶음에 넣으면 같은 이름이 두 곳에 생겨 헷갈린다.
    'i_bulk':           {'emoji': '📚', 'name': '대량등록',        'url': '/bulk/',                 'active_key': 'bulk',            'badge_key': None},
    # [2026-08-12 노션·사장님 확정] 「모음전」을 뗀다 — 분류(「상품 관리」) 아래에 있어
    #   이미 모음전 얘기인 게 드러난다. 긴 이름이 메뉴에서 두 줄로 접히기도 했다.
    'i_bundles':        {'emoji': '📋', 'name': '상품관리',          'url': '/bundles',               'active_key': 'bundles',         'badge_key': None},
    'i_matrix':         {'emoji': '🧱', 'name': '옵션관리',          'url': '/matrix',                'active_key': 'matrix',          'badge_key': None},
    # [2026-07-31] 노션 「(이름변경(기존): 마켓별 정책) → 정책 생성」
    'i_policies':       {'emoji': '🔧', 'name': '정책 생성',        'url': '/policies',              'active_key': 'policies',        'badge_key': None},
    # [2026-08-01] 노션 「상품 가공」 하위탭 ② — 상품 고르고 정책 붙이기
    # [2026-08-12] 노션 「상품가공 > 하위탭 a. 상품 정책 적용 → 정책 적용」.
    # [2026-08-19 사장님 확정] 「정책 적용」 → 「정책 매칭」(2번째 개명).
    #   🔴 이름이 화면 밖 **안내 문구**(to_payload.py·send/models.py)에도 박혀 있을 수 있다 —
    #      한 곳만 고치면 「정책 적용에서 붙여 주세요」라고 안내해 놓고 그런 이름의
    #      메뉴가 없는 상태가 된다. id·url·active_key 는 그대로 두고 표시 이름만 바꾼다.
    'i_policy_apply':   {'emoji': '🧩', 'name': '정책 매칭',      'url': '/policies/apply',        'active_key': 'policy_apply',    'badge_key': None},
    # [2026-08-12] 노션 「상품가공 > 하위탭 b-1. 가격 정책 → 옵션 맵핑 템플릿」 + 「b-3. 가로탭
    #   3개 중 가격 템플릿 삭제」. 가격 판이 빠지고 색상·사이즈(=옵션 맵핑)만 남으므로
    #   돈 이모지 💲 는 뜻이 어긋난다 → 🔗.
    'i_templates':      {'emoji': '🔗', 'name': '옵션 맵핑 템플릿', 'url': '/templates',             'active_key': 'templates',       'badge_key': None},
    # [2026-08-02] 「자동화」 분류 → 상단 분류 개편, 하위탭 2개 (사장님 확정 ⑤ · #687).
    #   ① 마켓 전송 = 골라서 지금 보내기(더망고식) / ② 자동화 = 저절로 돌기(지금 화면)
    #   [2026-08-06] 분류 이름은 `_SEND_STAGE_NAME`(「상품수집&전송」) — 사장님 지시.
    'i_market_send':    {'emoji': '📤', 'name': '마켓 전송',        'url': '/market-send',           'active_key': 'market_send',     'badge_key': None},
    'i_automation':     {'emoji': '⚙️', 'name': '자동화',           'url': '/automation',            'active_key': 'automation',      'badge_key': None},
    # [2026-08-12 사장님 확정] 「마켓 상품 현황」 → 「실마켓 상품 현황」.
    #   우리 프로그램 안의 상품(i_bundles)과, **실제 마켓에 올라가 있는** 상품을
    #   가르는 게 이 탭의 뜻이다. 「실」 한 글자가 그 구분을 만든다.
    'i_catalog':        {'emoji': '📦', 'name': '실마켓 상품 현황',  'url': '/catalog/',              'active_key': 'catalog',         'badge_key': None},
    'i_orders':         {'emoji': '📋', 'name': '주문 내역',        'url': '/orders/?tab=list',      'active_key': 'orders_list',     'badge_key': None},
    'i_ship':           {'emoji': '📦', 'name': '송장 작업',        'url': '/orders/?tab=ship',      'active_key': 'orders_ship',     'badge_key': None},
    'i_cs':             {'emoji': '💬', 'name': 'CS',               'url': '/orders/?tab=cs',        'active_key': 'orders_cs',       'badge_key': None},
    # [2026-08-06] 정산예정금액 — 기간별 미래 정산예정금(자금계획). 🔴 삭제된 i_sales
    #   id 재사용 금지(_REMOVED_IDS 가 다시 지운다) — 새 id.
    'i_settle_plan':    {'emoji': '💰', 'name': '정산예정금액',     'url': '/orders/?tab=settle_plan', 'active_key': 'orders_settle_plan', 'badge_key': None},
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

#: 상단 분류 s_auto 의 이름·이모지 — **여기 한 곳**이 원천이다.
#  [2026-08-06 사장님 지시] 「상품 마켓 전송」 → 「상품수집&전송」.
#  🔴 상수로 뽑은 이유 — 이 이름은 스펙(_STAGE_SPEC)·저장본 갈아끼우기(_migrate_send2)·
#     개명 마이그레이션(_migrate_send_rename) 세 곳이 같이 써야 한다. 문자열을 세 번
#     적으면 다음 개명 때 또 한 곳이 남는다(i_policies·optgen 때 반복된 자리).
_SEND_STAGE_EMOJI = '📤'
_SEND_STAGE_NAME = '상품수집&전송'

#: 「상품 관리」 하위탭 3개 — 노션 b항 순서(옵션 먼저, 상품 나중, 실마켓 현황 끝).
#  🔴 스펙(_STAGE_SPEC)과 개명·재정렬 마이그레이션이 **같이** 쓴다.
#     순서를 두 곳에 적으면 다음에 한 곳만 고쳐서 또 어긋난다(_SEND2 와 같은 이유).
_CATALOG3: tuple[str, ...] = ('i_matrix', 'i_bundles', 'i_catalog')

#: 저장본 세대. 9 = 상품관리 하위탭 1회 재정렬 완료(_migrate_catalog_order).
#  🔴 이 표시가 없으면 재정렬이 매 요청마다 돌아 사장님 드래그를 되돌린다.
_SCHEMA = 9

# 스테이지 스펙 — (id, 이모지, 이름, 색, 항목 id 순서). 노션 8분류 그대로.
_STAGE_SPEC: list[tuple] = [
    ('s_collect',   '📥', '옵션생성 & 상품생성', '#3182F6', ['i_optgen_direct', 'i_optgen_market',
                                                              'i_optgen_product']),
    # [2026-08-12] 노션 「b-2. 기타 상위탭 아래로 옮기기」 — i_templates 를 s_etc 로.
    #   「상품 가공」에는 노션 하위탭 그대로 「정책 생성 / 정책 적용」 둘만 남는다.
    # [2026-08-19 사장님 확정] 「상품 가공」 → 「상품 정책화」(분류 이름 개명).
    #   하위탭도 함께: 「정책 적용」→「정책 매칭」(위 i_policy_apply 참조).
    ('s_process',   '🔧', '상품 정책화',   '#F59E0B', ['i_policies', 'i_policy_apply']),
    ('s_auto',      _SEND_STAGE_EMOJI, _SEND_STAGE_NAME,
                                     '#8B5CF6', ['i_market_send', 'i_automation']),
    ('s_catalog',   '📦', '상품 관리',     '#06B6D4', list(_CATALOG3)),
    ('s_order',     '🧾', '주문 관리',     '#A855F7', ['i_orders', 'i_ship', 'i_cs', 'i_settle_plan']),
    ('s_stats',     '📊', '통계·분석',     '#EC4899', ['i_margin']),
    ('s_inventory', '🏷', '재고관리',      '#10B981', ['i_inventory']),
    # [2026-08-12 사장님 확정 ㉠] 「휴지통·변경 이력」(i_trash) 을 뺐다 — 휴지통을 안 쓴다.
    #   🔴 목록에서도 빼야 한다. _REMOVED_IDS 에만 넣으면 「없앤 것이 아직 메뉴에 있다」고
    #      감시 시험이 잡는다(둘이 어긋나면 저장본·마이그레이션이 갈린다).
    #   ★ main 이 같은 줄에 더한 'i_templates' 는 **그대로 살린다** — 내 변경은 i_trash 하나뿐.
    ('s_etc',       '⚙️', '기타',          '#6B7280', ['i_templates', 'i_crawl_guide', 'i_mk_acct',
                                                       'i_live_send_test',
                                                       'i_alerts', 'i_data_guide',
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
    # [2026-08-12 사장님 확정] 휴지통을 안 쓴다 — 지우기는 그 자리에서 진짜로 지운다.
    #   🔴 이 메뉴엔 「변경 이력」도 같이 달려 있었다(누가 언제 무엇을 고쳤나 59건 실측).
    #      사장님이 둘 다 빼기로 확정(㉠). 화면만 감추는 것이라 /trash·/audit 주소로는
    #      여전히 열린다 — 기록 자체는 지우지 않는다.
    'i_trash',
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
#   i_templates: 「템플릿」 → 「가격 정책」 → [2026-08-12] 「옵션 맵핑 템플릿」
#     (노션 상품가공 b-1. 가격 판이 빠져 색상·사이즈만 남았다)
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

#: 「상품수집&전송」 하위탭 2개 — 화면 가로탭(`market_send.SUBTABS`)과 **같은 순서**여야 한다.
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
        # 🔴 리터럴 8 이었다 — 새 볼륨이 8로 써 놓으면 바로 다음 요청에 재정렬이
        #    또 돌아 쓸데없이 한 번 더 저장한다. 기본값은 늘 최신 세대여야 한다.
        'schema': _SCHEMA,
        'updated_at': None,
        'standalone': [
            {'id': 'i_home', 'emoji': '⌂', 'name': '홈',
             'url': '/', 'active_key': 'home', 'badge_key': None},
            # [2026-08-02 사장님 확정 · C안] 대량등록 = 오른쪽 바로가기.
            #   🔴 여기에도 적어야 한다 — 저장본이 **아직 없는** 서버는 아래 갈아끼우기
            #     (_migrate_bulk_loose)를 안 거치고 이 기본값을 그대로 저장한다.
            #     저장본이 있는 서버만 보고 「됐다」 하면 새 서버에서 조용히 빠진다.
            _item('i_bulk'),
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
    """[2026-08-02] 「자동화」 분류 → 전송 분류 + 하위탭 2개(1회, idempotent).

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
        st['emoji'], st['name'] = _SEND_STAGE_EMOJI, _SEND_STAGE_NAME
        # 저장본에 있던 i_automation 은 사장님이 고친 이모지가 있을 수 있어 살려 옮긴다.
        #   (다만 이름은 _FORCE_RENAME 이 「자동화」로 덮는다 — 의도된 개명)
        saved = {it.get('id'): it for it in (st.get('items') or [])}
        st['items'] = [_item(i, saved.get(i)) for i in _SEND2]
        layout['stages'] = stages
        return True

    # s_auto 가 통째로 없는 저장본(옛 레이아웃) — 분류째로 만들어 넣는다.
    stages.append({'id': 's_auto', 'emoji': _SEND_STAGE_EMOJI, 'name': _SEND_STAGE_NAME,
                   'color': '#8B5CF6', 'collapsed': False,
                   'items': [_item(i) for i in _SEND2]})
    layout['stages'] = stages
    return True


def _migrate_send_rename(layout: dict) -> bool:
    """[2026-08-06 사장님 지시] 전송 분류(s_auto) 이름 → 「상품수집&전송」(idempotent).

    왜 또 바꾸나 — 사장님이 「상품 마켓 전송」을 「상품수집&전송」으로 바꾸라고 지시했다.
    이 분류는 소싱처에서 **긁는 것**과 마켓으로 **보내는 것**을 함께 담고 있어, 옛 이름은
    「보내기」만 하는 곳처럼 읽혔다.

    🔴 왜 _migrate_send2 를 고치는 것으로 끝나지 않나 — 그 마이그레이션은
       `if _has_item_id(layout, 'i_market_send'): return False` 로 **이미 끝난 것**이라
       다시 돌지 않는다. 라이브 저장본(sidebar_layout)엔 옛 이름이 그대로 남아 있어,
       코드 상수만 고치면 화면은 안 바뀐다(i_policies 때 겪은 바로 그 자리).
       그래서 이름만 보는 개명 마이그레이션을 따로 둔다.

    이름 비교만 하고 옛 이름 문자열은 안 적는다 — 사장님이 손으로 고쳐 둔 다른 이름이
    있더라도 「의도된 개명」이라 덮는 게 맞다(_FORCE_RENAME 과 같은 원칙).
    """
    changed = False
    for st in (layout.get('stages') or []):
        if st.get('id') != 's_auto':
            continue
        if st.get('name') != _SEND_STAGE_NAME:
            st['name'] = _SEND_STAGE_NAME
            changed = True
        if st.get('emoji') != _SEND_STAGE_EMOJI:
            st['emoji'] = _SEND_STAGE_EMOJI
            changed = True
    return changed


def _migrate_catalog_rename(layout: dict) -> bool:
    """[2026-08-12 노션 a항] 상품 관리 하위탭 개명(idempotent, 어긋나면 언제든 다시 고침).

      모음전 상품관리 → 상품관리 · 모음전 옵션관리 → 옵션관리
      마켓 상품 현황 → 실마켓 상품 현황

    🔴 왜 `_FORCE_RENAME` 만으로는 안 되나 — 그건 `_item()` 이 불릴 때만 작동하는데,
       `get_layout_for_template()` 은 저장본에 **이미 있는** 항목을 `_item()` 없이
       그대로 통과시킨다. 세 항목 다 저장본에 있으므로 영영 안 닿는다.
       (i_policies · i_automation · s_auto 때 반복된 그 자리 — `_migrate_send_rename` 참조)

    옛 문자열을 안 적고 `_ITEM_DEFS` 와 **다르면** 갈아끼운다 — 사장님이 손으로 고쳐둔
    이름이 있어도 의도된 개명이므로 덮는 게 맞다(`_FORCE_RENAME` 과 같은 원칙).
    이름 기준이라 나중에 저장본이 어긋나도 스스로 낫는다.
    """
    changed = False
    for st in (layout.get('stages') or []):
        if st.get('id') != 's_catalog':
            continue
        for it in (st.get('items') or []):
            spec = _ITEM_DEFS.get(it.get('id'))
            if not spec or it.get('id') not in _CATALOG3:
                continue
            for k in ('emoji', 'name'):
                if it.get(k) != spec[k]:
                    it[k] = spec[k]
                    changed = True
    return changed


def _migrate_process_rename(layout: dict) -> bool:
    """[2026-08-19 사장님 확정] 「상품 가공」 → 「상품 정책화」(분류) +
       「정책 적용」 → 「정책 매칭」(하위탭) 개명(idempotent, 늘 다시 건다).

    🔴 `i_policy_apply` 는 이미 `_FORCE_RENAME` 대상이지만 그것만으론 부족하다 —
       `get_layout_for_template()` 은 저장본에 **이미 있는** 항목을 `_item()` 없이
       그대로 통과시킨다(i_policies·i_automation·s_auto 때 반복된 그 자리,
       `_migrate_send_rename`·`_migrate_catalog_rename` 참조). 분류(stage) 이름은
       애초에 `_FORCE_RENAME`(항목 전용) 이 안 닿는 자리라 더더욱 저장본을 직접 고쳐야 한다.

    이름 비교만 하고 옛 이름 문자열은 안 적는다 — 사장님이 손으로 고쳐 둔 다른 이름이
    있더라도 「의도된 개명」이라 덮는 게 맞다(`_FORCE_RENAME` 과 같은 원칙).
    """
    changed = False
    spec_name = next(n for sid, _e, n, _c, _i in _STAGE_SPEC if sid == 's_process')
    for st in (layout.get('stages') or []):
        if st.get('id') != 's_process':
            continue
        if st.get('name') != spec_name:
            st['name'] = spec_name
            changed = True
        for it in (st.get('items') or []):
            if it.get('id') != 'i_policy_apply':
                continue
            new_name = _ITEM_DEFS['i_policy_apply']['name']
            if it.get('name') != new_name:
                it['name'] = new_name
                changed = True
    return changed


def _migrate_catalog_order(layout: dict) -> bool:
    """[2026-08-12 노션 b항] 상품 관리 하위탭을 **딱 한 번** 옵션관리 먼저로 재정렬.

    🔴 왜 스펙만 고치면 안 되나 — `get_layout_for_template()` 은 「이미 있는 항목의
       순서는 건드리지 않는다」(사장님이 드래그로 둔 자리가 곧 의도다). 그래서
       `_STAGE_SPEC` 순서를 바꿔도 화면 순서는 안 바뀐다. 순서를 바꾸는 일은
       **저장본을 한 번 갈아끼우는** 마이그레이션의 몫이다.

    🔴 왜 「스펙과 다르면 고친다」가 아니라 schema 표시인가 — 그렇게 짜면 사장님이
       나중에 이 셋을 드래그로 되돌려도 **다음 요청마다 되돌아온다**(드래그가 안 먹는
       것처럼 보인다). 「의도된 1회 재정렬」과 「드래그 순서 보존」은 이 표시 하나로만
       양립한다. 개명(_migrate_catalog_rename)은 반대로 늘 다시 걸어야 하므로 따로 뒀다.
    """
    if int(layout.get('schema') or 0) >= _SCHEMA:
        return False
    layout['schema'] = _SCHEMA      # 분류가 없는 저장본에도 표시는 남긴다(재실행 방지)
    for st in (layout.get('stages') or []):
        if st.get('id') != 's_catalog':
            continue
        items = list(st.get('items') or [])
        by_id = {it.get('id'): it for it in items}
        head = [by_id[i] for i in _CATALOG3 if i in by_id]
        # 스펙 밖 항목(사장님이 이 분류에 끌어다 둔 딴 메뉴)은 잃지 않고 뒤에 그대로.
        rest = [it for it in items if it.get('id') not in _CATALOG3]
        st['items'] = head + rest
        break
    return True


def _migrate_bulk_loose(layout: dict) -> bool:
    """[2026-08-02 사장님 확정] 「대량등록」을 오른쪽 바로가기로 넣는다(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 **저장본**을 쓴다.
       (i_ship·i_policies·optgen 하위탭·노션 일일보고 때 반복된 그 자리)

    여태 이 화면은 **어느 메뉴에도 링크가 없어** 주소를 직접 쳐야 들어갔다.
    「옵션생성 & 상품생성」으로 재편할 때 빠진 채로 남아 있었다.

    왜 standalone 인가 — 위쪽 막대는 `standalone[0]`(홈)을 로고로 쓰고 **나머지를
    오른쪽에 늘어놓는다**(webapp/nav_top.py:74-76 · loose). 왼쪽 사이드바는 이미
    없으므로 이 항목은 오른쪽 한 곳에만 나온다.
    """
    if _has_item_id(layout, 'i_bulk'):
        return False
    layout['standalone'] = list(layout.get('standalone') or []) + [_item('i_bulk')]
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


def _migrate_settle_plan(layout: dict) -> bool:
    """[2026-08-06] 「💰 정산예정금액」 메뉴 — 주문 관리 분류에 추가(1회, idempotent).

    🔴 스펙(_STAGE_SPEC)만 고치면 라이브에 안 나온다 — 서버는 **저장본**을 쓴다
       (_migrate_notion_report 와 같은 자리·같은 이유).
    """
    if _has_item_id(layout, 'i_settle_plan'):
        return False
    for st in (layout.get('stages') or []):
        if st.get('id') == 's_order':
            st['items'] = list(st.get('items') or []) + [_item('i_settle_plan')]
            return True
    # 주문 관리 분류가 없는 저장본 — 오른쪽 바로가기로라도 노출(메뉴 없는 화면 재발 방지).
    layout['standalone'] = list(layout.get('standalone') or []) + [_item('i_settle_plan')]
    return True


def _migrate_templates_to_etc(layout: dict) -> bool:
    """[2026-08-12] 「옵션 맵핑 템플릿」을 「상품 가공」 → 「기타」로 이동(1회, idempotent).

    노션 「상품가공 > 하위탭 b-2. 기타 상위탭 아래로 옮기기」.

    🔴 _STAGE_SPEC 만 고치면 **절대 안 옮겨진다.** get_layout_for_template() 의
       주입 로직은 「스펙엔 있는데 저장본엔 없는」 항목만 붙인다 — i_templates 는
       저장본에 이미 있으므로 「빠진 것」으로 안 잡혀 상품 가공에 그대로 남는다.
       그래서 저장본 자체를 갈아끼운다 (_migrate_optgen 이 i_bundles·i_matrix 를
       옮긴 것과 같은 자리·같은 방법).

    🔴 「이미 했나」 판정은 **목적지에 있나**로 한다. `_has_item_id` 로 존재만
       보면 옮기기 전에도 True 라 한 번도 안 돈다.
    """
    stages = layout.get('stages') or []
    etc = next((st for st in stages if st.get('id') == 's_etc'), None)
    if etc is not None and any((it.get('id') == 'i_templates')
                               for it in (etc.get('items') or [])):
        return False                                   # 이미 기타에 있다

    moved: dict | None = None
    for st in stages:
        keep = []
        for it in st.get('items') or []:
            if it.get('id') == 'i_templates':
                moved = it                             # 어느 분류에 있든 뽑아낸다
                continue
            keep.append(it)
        st['items'] = keep
    # 오른쪽 바로가기(standalone)에 옮겨 뒀을 수도 있다 — 거기도 훑는다.
    loose = []
    for it in layout.get('standalone') or []:
        if it.get('id') == 'i_templates':
            moved = moved or it
            continue
        loose.append(it)
    layout['standalone'] = loose

    if etc is None:
        etc = {'id': 's_etc', 'emoji': '⚙️', 'name': '기타',
               'color': '#6B7280', 'collapsed': False, 'items': []}
        stages.append(etc)
    # 맨 앞에 붙인다 — 스펙(_STAGE_SPEC)의 기타 항목 순서와 같게.
    #   _item() 이 개명을 건다: i_templates 는 _FORCE_RENAME 대상이라
    #   저장본의 옛 이름(「가격 정책」)이 아니라 새 이름이 이긴다.
    etc['items'] = [_item('i_templates', moved)] + list(etc.get('items') or [])
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
        _mig7 = _migrate_send2(data)       # [2026-08-02] 자동화 → 전송 분류 2탭(1회)
        _mig8 = _migrate_notion_report(data)  # [2026-08-02] 노션 일일보고 메뉴 추가(1회)
        _mig9 = _migrate_bulk_loose(data)     # [2026-08-02] 대량등록 오른쪽 바로가기(1회)
        _mig10 = _migrate_settle_plan(data)   # [2026-08-06] 정산예정금액 메뉴(1회)
        _mig11 = _migrate_send_rename(data)   # [2026-08-06] s_auto → 「상품수집&전송」 개명
        _mig12 = _migrate_catalog_rename(data)  # [2026-08-12] 상품관리 하위탭 개명(늘)
        _mig13 = _migrate_catalog_order(data)   # [2026-08-12] 상품관리 하위탭 재정렬(1회)
        # [2026-08-12] 상품가공 — 옵션 맵핑 템플릿 → 기타(1회).
        #   🔴 다른 세션(상품관리 #963)과 **같은 번호(_mig12)로 부딪혔다.**
        #      하나를 지우면 그 메뉴 변경이 조용히 사라진다 — 셋 다 부르고 셋 다 센다.
        _mig14 = _migrate_templates_to_etc(data)
        _mig15 = _migrate_process_rename(data)  # [2026-08-19] 상품가공→상품 정책화 + 정책 적용→정책 매칭(늘)
        if (_mig1 or _mig2 or _mig3 or _mig4 or _mig5 or _mig6 or _mig7 or _mig8
                or _mig9 or _mig10 or _mig11 or _mig12 or _mig13 or _mig14 or _mig15):
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


# [2026-08-02 사장님 확정] 「로드맵」 자동 주입 상수 삭제 — 메뉴에서 뺀다.
#   화면(/roadmap)은 그대로 살아 있고 주소로 열린다.

# [2026-07-30] 항목별 「없으면 주입」 상수 7종 삭제 — _STAGE_SPEC/_ITEM_DEFS 로 통합.
#   ★ 그 방식이 「data/sidebar_layout.json 만 고치면 라이브에 안 나온다」 사고의 원인이었다
#     (기본값·주입상수·저장본 3곳이 갈림). 이제 새 메뉴는 _STAGE_SPEC 한 곳에만 추가한다.


def _has_item_id(layout: dict, item_id: str) -> bool:
    def _has(items):
        return any(isinstance(i, dict) and i.get('id') == item_id for i in items)
    if _has(layout.get('standalone', [])):
        return True
    return any(_has(st.get('items', [])) for st in layout.get('stages', []))


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

    # [2026-08-02 사장님 확정] 「로드맵」을 메뉴에서 뺀다.
    #   예전에는 저장본에 없어도 **매번 자동으로 끼워 넣어** 모두에게 보이게 했다.
    #   그 주입을 멈춘다 — 저장본에 직접 넣은 사람에게는 그대로 보인다(그건 그 사람 뜻).
    #   화면 자체(/roadmap)는 그대로 살아 있다 — 주소로 열린다.

    return out


@bp.get('/layout')
def api_get_layout():
    """편집 화면이 읽는 것 — **실제 사이드바와 같은 것**을 준다.

    🔴 전에는 `_load()` 저장본을 날것으로 줬다. 저장본에 없고 스펙에서 주입되는
      항목(정책 생성·정책 적용)이 편집 화면에서만 사라져, 「상품 가공」 서랍이
      텅 빈 채로 보였다 — 실제 사이드바에는 둘 다 있는데.
      편집 화면과 실물이 다르면 사장님이 「없어졌다」로 읽는다.
    """
    return jsonify(get_layout_for_template())


@bp.put('/layout')
def api_put_layout():
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'ok': False, 'error': 'invalid JSON'}), 400
    ok, msg = _validate(payload)
    if not ok:
        return jsonify({'ok': False, 'error': msg}), 400
    payload['version'] = 1
    # 🔴 schema 를 잃으면 1회 재정렬(_migrate_catalog_order)이 다시 돌아, 사장님이
    #    방금 드래그로 둔 순서를 되돌린다. 보내오지 않았으면 최신 세대로 채운다.
    payload.setdefault('schema', _SCHEMA)
    with _lock:
        _save(payload)
    return jsonify({'ok': True, 'updated_at': payload['updated_at']})


@bp.post('/layout/reset')
def api_reset_layout():
    with _lock:
        layout = _default_layout()
        _save(layout)
    return jsonify({'ok': True, 'layout': layout})
