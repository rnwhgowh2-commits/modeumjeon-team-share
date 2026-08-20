# -*- coding: utf-8 -*-
"""폰 앱 껍데기 — '전체' 메뉴 · 설치 안내 · 폰 전용 화면 목록(단일 원천).

여기 따로 둔 이유: mobile.py 는 바코드 스캔·재고 모듈이다. 껍데기(메뉴·탭·설치)는
관심사가 다르고, 다른 blueprint(mobile_crawl)의 권한 사실까지 알아야 한다.
Task 6 의 하단 탭이 세 번째 소비자로 붙으면 껍데기 세 곳이 스캔 파일을 import 하게 된다.

라우트:
  GET  /mobile/menu     → '전체' (PC 상단 메뉴와 같은 원천)
  GET  /mobile/install  → 설치 안내
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, render_template

bp = Blueprint("mobile_shell", __name__, url_prefix="/mobile")


# ════════════════════════════════════════════════════════════
#  주소 다듬기 — 「같은 화면인가」 판정의 단일 원천
#    🔴 이게 프로덕션에 없으면 배지가 **조용히 틀린다**. 배지는 글자 그대로 맞아야
#      붙고, 안 맞아도 에러가 안 난다(그냥 'PC 화면'으로 뜬다).
# ════════════════════════════════════════════════════════════

def _norm_path(p: str) -> str:
    return p.rstrip("/") or "/"


def same_screen(url: str) -> str:
    """**메뉴 줄**의 신원 — 끝 빗금과 #조각만 다듬는다.

    [중요] 물음표 뒤(탭)는 **일부러 안 뗀다.** 주문 관리는 한 주소의 탭 4개가
      메뉴에서 각각 다른 줄이다(`/orders/?tab=list|ship|cs|margin`).
      탭을 떼면 그중 하나만 폰 전용으로 바꿔도 **네 줄 전부** 폰 전용 배지가 붙는다.
    """
    u = (url or "").split("#", 1)[0]
    path, sep, query = u.partition("?")
    return _norm_path(path) + (sep + query if query else "")


def same_route(url: str) -> str:
    """**어느 라우트가 그리는가** — 물음표 뒤까지 뗀다.

    라우트는 물음표 뒤로 갈리지 않는다. '/mobile/scan-batch?mode=in' 과
    '?mode=out' 은 메뉴에선 두 줄이지만 그리는 화면(라우트)은 하나다.
    """
    return _norm_path((url or "").split("#", 1)[0].split("?", 1)[0])


# ─── 폰 전용으로 이미 만들어진 화면들 ───
#   '전체' 메뉴에서 두 가지로 쓴다: (1) 이 화면들을 메뉴에 싣는 원천, (2) '폰 전용' 배지 판정.
#
#   🔴 왜 따로 두나 — PC 상단 메뉴(sidebar_layout)에는 이 화면들이 **하나도 없다**.
#     폰에만 있는 화면이라 PC 메뉴에 넣을 자리가 없어서다(실측: 25줄 전부 PC 주소).
#     그래서 배지 집합만 두고 PC 메뉴 줄에만 배지를 붙이면, 맞는 줄이 영영 없어
#     **모든 줄이 조용히 'PC 화면'** 으로 뜬다.
#   Task 6 — 하단 탭도 이 목록에서 골라 쓴다(두 곳에 적기 금지):
#     · `tab`       : 이 줄이 하단 탭 한 칸이다 — {key, icon, label, order}
#     · `under_tab` : 탭 칸은 아니지만 그 탭의 하위 흐름이다(연속 스캔 → 작업).
#                     지금 이 화면일 때 부모 탭이 켜져 보인다.
#     · `in_menu`   : False 면 '전체' 메뉴 목록에는 안 싣는다(기본 True).
#                     메뉴 화면 자신(/mobile/menu)이 그렇다 — 자기를 자기 목록에
#                     넣지 않는다는 MENU_EXEMPT 의 결정은 그대로 두고, 탭 원천에만 싣는다.
PHONE_NATIVE_ROWS: list[dict[str, Any]] = [
    {"emoji": "🏠", "name": "폰 홈", "url": "/mobile",
     "tab": {"key": "home", "icon": "⌂", "label": "홈", "order": 1}},
    {"emoji": "📷", "name": "바코드 스캔", "url": "/mobile/scan",
     "tab": {"key": "work", "icon": "📷", "label": "작업", "order": 2}},
    {"emoji": "📥", "name": "연속 스캔 입고", "url": "/mobile/scan-batch?mode=in",
     "under_tab": "work"},
    {"emoji": "📤", "name": "연속 스캔 출고", "url": "/mobile/scan-batch?mode=out",
     "under_tab": "work"},
    # [2026-08-06] 포장 스캔 출고 — 바코드를 찍어 「이 주문이 나갔다」를 확정한다.
    #   연속 스캔 출고와 다른 화면이다: 저건 SKU·수량만 세고, 이건 **주문 줄**을 보고
    #   「사입」으로 표시된 것만 재고를 깎는다(무재고 주문은 안 깎는다).
    #   admin_only 아님 — 포장은 팀원 모두의 일이고, 원천(주문·재고)에도 게이트가 없다.
    {"emoji": "📦", "name": "포장 스캔 출고", "url": "/mobile/scan-ship",
     "under_tab": "work"},
    {"emoji": "🏷", "name": "재고 목록", "url": "/mobile/inventory"},
    # [배치5] 주문 폰 화면 — admin_only 아님(주문은 member 의 일이다).
    #   [2026-08-06 · 사장님 확정 A1] **자기 탭 한 칸을 갖는다.**
    #     처음엔 tab/under_tab 을 안 달았다 — 재고 목록과 같은 부류로 보고, 남의 탭
    #     (작업·홈)을 켜 두면 「지금 거기 있다」는 거짓말이 되기 때문이었다.
    #     그 걱정은 **남의 탭을 빌려 쓸 때**의 것이고, 자기 칸이 생기면 사라진다
    #     (active_tab_key 가 /mobile/orders 에서 'orders' 를 켠다 — 사실 그대로).
    #     자리를 옮긴 이유: 주문은 매일 여러 번 보는 화면인데 홈 맨 아래 한 줄로만
    #     있어, 다른 화면에서 보려면 홈을 거쳐야 했다(시안 A1 확정).
    #   ★ 홈 본문은 건드리지 않는다 — 홈에 숫자를 두면 홈을 열 때마다 여섯 판매처를
    #     조회해 홈이 통째로 느려진다(3-C 「홈에는 숫자 금지」 그대로).
    {"emoji": "🧾", "name": "주문 내역", "url": "/mobile/orders",
     "tab": {"key": "orders", "icon": "🧾", "label": "주문", "order": 3}},
    # [D-1] 매트릭스 폰 화면 — 검색→옵션 카드(소싱처별 가격·재고).
    #   admin_only 아님: PC /matrix 에 권한 게이트가 없다(팀원 모두의 화면) — 폰만
    #   잠그면 두 화면이 다른 답을 낸다. 시험이 이 사실을 못 박는다.
    #   이름은 PC 메뉴의 「모음전 옵션관리」(i_matrix)와 다르게 둔다 — 같은 이름 두 줄이
    #   메뉴에 나란히 뜨면 어느 쪽이 폰 화면인지 못 가른다.
    {"emoji": "🧱", "name": "옵션 가격·재고", "url": "/mobile/matrix"},
    # [E-1] 정산 요약 폰 화면 — 기간 KPI(예정/확정) + 마켓별 막대.
    #   admin_only 아님: 원천인 PC 주문·마진 화면(/orders·margin-embed)에 권한
    #   게이트가 없다(주문·정산은 팀원 모두의 일) — 폰만 잠그면 두 화면이 다른 답을 낸다.
    {"emoji": "💰", "name": "정산 요약", "url": "/mobile/settle"},
    # [F-2] 크롤 가이드 읽기 — 목차→절. 내용은 정본 md(docs/크롤링-가이드.md)를
    #   렌더 시점에 읽는다(사본 0). admin 전용: PC 원천(/sourcing-guide/*)이
    #   team-share-dev 에서 admin 게이트(sourcing_guide._admin_only) 뒤다 —
    #   폰만 열면 두 화면이 다른 답을 낸다(리모컨과 같은 원칙, 시험이 게이트와 묶음).
    {"emoji": "🗺", "name": "크롤 가이드", "url": "/mobile/guide", "admin_only": True},
    # 크롤 리모컨은 admin 전용이다(mobile_crawl._admin_only). member 에게 보여 주면
    # 눌러도 403 만 나오는 줄이 된다 — 이 설계가 가장 피하려는 결과다.
    # 하단 탭의 크롤 칸도 같은 이유로 member 에게는 아예 안 실린다(tab_rows 가 거른다).
    {"emoji": "🛰", "name": "크롤 리모컨", "url": "/mobile/crawl/", "admin_only": True,
     "tab": {"key": "crawl", "icon": "🛰", "label": "크롤", "order": 4}},
    # '전체' 메뉴 — 폰 전용 화면이 맞아 이 목록에 싣는다(탭 원천은 여기 하나뿐이어야
    # 하므로). 단 메뉴 목록에는 안 싣는다(in_menu=False) — 위 주석의 결정 그대로.
    {"emoji": "≡", "name": "전체", "url": "/mobile/menu", "in_menu": False,
     "tab": {"key": "menu", "icon": "≡", "label": "전체", "order": 5}},
]

# ─── 3단계 — 폰 대응(@media retrofit)이 끝난 PC 화면 (단일 원천) ───
#   여기 적힌 주소에서는 껍데기가 노란 안내 띠("PC용 화면입니다")를 **생략**한다.
#   전달 경로: base.html 의 ms-tabs-data JSON(ready 칸) → mobile_shell.js.
#   JS 에 주소를 직접 적지 않는다 — 원천은 이 집합 하나뿐이다.
#
#   🔴 넣기 전 확인 두 가지(배치 1에서 못 박은 절차):
#     ① 그 화면 템플릿에 @media (max-width: 768px) 블록이 실제로 있어야 한다.
#        여기만 넣으면 띠는 사라지는데 화면은 그대로 PC 판 — 거짓 표시가 된다.
#     ② 메뉴 줄이 있는 주소면 아래 MOBILE_READY_MENU_URLS 에도 넣는다(배지).
MOBILE_READY_URLS: set[str] = {
    "/alerts",   # 알림 채널 설정 — templates/alerts/index.html (2026-08-04 배치1)
    "/trash",    # 휴지통 — templates/trash/index.html (2026-08-04 배치1)
    "/audit",    # 변경 이력 — /trash 메뉴 줄의 짝 화면, templates/trash/audit.html.
                 #   메뉴에 자기 줄이 없어 배지 대상은 아니다(아래 MENU 집합에서 제외).
    # ── 배치2 (2026-08-04) ──
    "/catalog/",                # 마켓 상품 현황 — templates/catalog/index.html
    "/catalog/?tab=dashboard",  # 🔴 탭은 물음표 뒤로 갈린다(same_screen 이 보존) —
    "/catalog/?tab=pick",       #   탭 주소를 안 적으면 그 탭에서만 노란 띠가 되살아난다.
    "/catalog/?tab=detail",     #   (partials/_dashboard·_pick·_detail.html 각자 @media)
    "/data-guide",              # 데이터 가이드 — templates/data_guide.html
    "/live-send-test",          # 실전송 테스트 — templates/live_send_test/index.html
    "/reports/notion-todo",     # 노션 일일보고 — routes/notion_report.py 의 _CSS.
                                #   base.html 밖 독립 화면이라 띠는 원래 안 뜬다 —
                                #   여기 넣는 실효는 메뉴 배지(아래 MENU 집합) 쪽이다.
    # ── 배치3 (2026-08-04) ──
    "/templates",        # 가격 정책 — templates/templates_page/index.html
    "/policies",         # 정책 생성 — templates/policy/index.html.
                         #   ⚠️ ?brand= 로 걸러진 주소는 값이 임의라 열거 불가 —
                         #   걸러진 화면에선 노란 띠가 다시 뜬다(껍데기 설계 한계).
    "/policies/apply",   # 정책 매칭 — templates/policy/apply.html
    "/accounts/upload",  # 판매처 계정 — templates/accounts/upload.html (72KB 최대 retrofit)
    # ── 배치4a (2026-08-04) ──
    "/market-send",      # 마켓 전송 — templates/market_send/index.html
    "/automation",       # 자동화 — templates/automation/index.html (89KB — 대부분 JS,
                         #   CSS retrofit 성립. zoom:1.3 해제 + 2단→1단 + 표 4벌 스크롤).
                         #   /automation/weights(크롤 계수 상세)는 별도 화면 — 배치4b 전환.
    "/bulk/",            # 대량등록 — templates/bulk/index.html + 탭별 partial.
    "/bulk/?tab=collect",   # 🔴 탭은 물음표 뒤로 갈린다(카탈로그와 같은 이유) —
    "/bulk/?tab=process",   #   탭 주소를 안 적으면 그 탭에서만 노란 띠가 되살아난다.
    "/bulk/?tab=send",      #   원천은 bulk.SUBTABS — 시험이 전 탭 열거를 대조한다.
    "/bulk/?tab=manual",
    "/bulk/?tab=products",
    "/bulk/?tab=orders",    # orders·cs·stats = _shared_screen.html(링크 안내판) 하나
    "/bulk/?tab=cs",
    "/bulk/?tab=stats",
    "/bulk/?tab=settings",
    # ── 배치4b (2026-08-04) — retrofit 마지막 배치 ──
    "/bundles",             # 모음전 상품관리 — templates/bundles/list.html (60KB).
                            #   ?status=·brand=·q= 는 데이터 필터(같은 템플릿) → PATH_ONLY.
    "/optgen",              # 옵션생성 & 상품생성 — templates/optgen/index.html.
    "/optgen?tab=direct",   # 🔴 탭은 물음표 뒤로 갈린다(카탈로그·bulk 와 같은 이유) —
    "/optgen?tab=market",   #   market 탭만 _market_pane.html 조각이 따로 실리므로
    "/optgen?tab=product",  #   PATH_ONLY 가 아니라 탭 열거다(원천 optgen.SUBTABS).
    "/inventory/",          # 재고관리 — templates/inventory/home.html (57KB — 인라인
                            #   style 판이라 iv-* id 훅 + !important retrofit).
                            #   ?sku=(행 클릭)·q= 는 데이터 필터(같은 템플릿) → PATH_ONLY.
    "/sourcing-guide/",     # 소싱처 관리(가이드 전체보기) — sourcing_guide/overview.html
                            #   (59KB). ?guide=1 등은 같은 템플릿 → PATH_ONLY.
                            #   ⚠️ 203KB 의 map.html(지도)은 괴물 배치(6) — 여기 아님.
    "/automation/weights",  # 크롤 계수 드릴다운 — automation/weights.html (4a 이월).
                            #   메뉴에 자기 줄이 없어(/audit 과 같은 부류) 배지 대상 아님.
}

#: 위 중 PC 메뉴(sidebar_layout)에 **자기 줄이 있는** 주소 — '폰 전용' 배지를 붙인다.
#  시험 test_배지집합에_넣은_PC주소는_사이드바에_실제로_있다 가 사이드바와 대조한다
#  (/audit 처럼 메뉴 줄 없는 하위 화면을 넣으면 그 시험이 막는다 — 의도된 문지기).
#  ★ MOBILE_READY_URLS 의 부분집합이어야 한다(같은 글자 그대로 — 시험이 지킨다).
MOBILE_READY_MENU_URLS: set[str] = {
    # [2026-08-12 사장님 확정 ㉠] "/trash" 를 뺐다 — PC 메뉴에서 없앴다.
    #   여기 남겨 두면 「PC 메뉴에 없는 주소」라 시험이 막는다(의도된 문지기).
    "/alerts",
    "/catalog/", "/data-guide", "/live-send-test", "/reports/notion-todo",
    "/templates", "/policies", "/policies/apply", "/accounts/upload",
    "/market-send", "/automation", "/bulk/",
    # 배치4b — 사이드바 줄 그대로(옵션생성은 하위탭 3줄이 각각 메뉴 줄이다.
    #   맨몸 /optgen·/automation/weights 는 메뉴 줄이 없다 — 넣으면 배지 시험이 막는다).
    "/bundles", "/optgen?tab=direct", "/optgen?tab=market", "/optgen?tab=product",
    "/inventory/", "/sourcing-guide/",
}

#: [배치4a] READY 중 「물음표 뒤가 데이터 거르기일 뿐, 같은 템플릿」인 화면 —
#  경로만 맞으면 띠를 생략한다(opt-in 부분집합). /policies?brand=X 는 값이 임의라
#  열거가 불가능한데 같은 index.html 을 그린다(배치3에 「설계 한계」로 기록했던 그 건).
#
#  🔴 전역으로 하면 안 된다 — /orders 는 탭(?tab=list|ship|cs|margin)마다 **다른
#    템플릿**을 그린다. 경로 일치를 기본으로 삼으면 한 탭만 전환해도 네 탭 전부
#    띠가 사라진다(= 전환 안 된 탭에 「폰 대응 완료」 거짓 표시). 그래서 탭이
#    갈리는 화면(/catalog·/bulk)은 여기 넣지 않고 탭 주소를 READY 에 열거한다.
#  ★ MOBILE_READY_URLS 의 부분집합이어야 한다(시험이 지킨다).
MOBILE_READY_PATH_ONLY: set[str] = {
    "/policies",   # ?brand= 는 임의값 필터 — templates/policy/index.html 하나를 그린다
    # 배치4b — 같은 부류 셋. 시험 test_PATH_ONLY_주소는_엉뚱한_쿼리에도_같은_템플릿을
    # _그린다 가 「같은 템플릿」 주장 자체를 template_rendered 신호로 검사한다.
    "/bundles",         # ?status=·brand=·q= → bundles/list.html 하나
    "/inventory/",      # ?sku=(행 클릭)·q=·in_stock= → inventory/home.html 하나
    "/sourcing-guide/", # ?guide=1·install=1 → sourcing_guide/overview.html 하나
    # 🔴 /optgen 은 넣지 않는다 — market 탭이 _market_pane.html 조각을 그린다(탭 열거).
}

#: JSON 에 실어 보내는 모양 — same_route 로 다듬는다.
#  JS 쪽은 sameScreen(pathname, '') 로 경로만 만들어 그대로 비교한다(정규화 두 벌 금지).
MOBILE_READY_PATH_ONLY_ROUTES: set[str] = {same_route(u) for u in MOBILE_READY_PATH_ONLY}

#: 안내 띠 생략 판정용 — same_screen 으로 다듬은 모양. JSON 에 이걸 실어 보낸다.
MOBILE_READY_SCREENS: set[str] = {same_screen(u) for u in MOBILE_READY_URLS}

#: '폰 전용' 배지를 붙일 주소.
#  ★ 3단계에서 PC 화면 하나를 폰 전용으로 바꿀 때는 위 목록에 넣지 말고 그 화면의
#    **PC 주소**(예: '/orders/?tab=list')만 MOBILE_READY_MENU_URLS 에 더한다.
#    그 화면은 이미 PC 메뉴에 있으니, 목록에 또 넣으면 같은 줄이 두 번 뜬다.
#  빗금·#조각 차이는 same_screen 이 흡수한다 — 사이드바가 '/orders?tab=list' 로
#  갖고 있어도 배지가 붙는다(그 어긋남이 예전엔 조용한 실패였다).
PHONE_NATIVE_BADGE_URLS: set[str] = ({it["url"] for it in PHONE_NATIVE_ROWS}
                                     | MOBILE_READY_MENU_URLS)

_BADGE_SCREENS: set[str] = {same_screen(u) for u in PHONE_NATIVE_BADGE_URLS}


def is_phone_native(url: str) -> bool:
    """이 주소가 폰 전용 화면인가 — 화면(템플릿)과 시험이 **같이 쓰는** 하나의 판정."""
    return same_screen(url) in _BADGE_SCREENS


#: '전체' 메뉴에 **일부러** 안 싣는 폰 라우트 — url_map 의 규칙 문자열 그대로 적는다.
#
#  🔴 왜 목록으로 두나 — PHONE_NATIVE_ROWS 만으로는 **한 방향밖에 못 지킨다**(적어 둔
#    주소가 진짜 있나). 반대쪽, 즉 '새로 만든 폰 화면이 메뉴에 실렸나'는 아무도 안 본다.
#    그러면 Task 6·7 에서 폰 화면을 만들고 목록에 안 넣어도 아무것도 안 깨지고, 이 화면이
#    존재하는 이유였던 그 사고(만든 화면이 메뉴에 없어 두 달간 주소를 직접 침)가 폰 쪽에서
#    그대로 되살아난다.
#    → 시험(test_menu_single_source.py::test_모든_폰_화면은_메뉴에_실리거나_빠진_이유가_적혀있다)이
#      /mobile/* 페이지 라우트를 훑어, 여기에도 목록에도 없으면 실패한다.
#
#  ★ 동적 주소(<sku> 같은)도 자동으로 봐주지 않는다 — 자동 예외는 한 부류를 통째로
#    조용히 빼는 것이라, 이 장치가 막으려는 사고와 정확히 같은 모양이 된다.
MENU_EXEMPT_ROUTE_RULES: dict[str, str] = {
    "/mobile/menu": "이 메뉴 화면 자신 — 자기를 자기 목록에 넣지 않는다",
    "/mobile/install": "메뉴 맨 아래 고정줄(앱 설치 방법)에 이미 있다",
    "/mobile/sku/<path:sku>": "특정 SKU 상세 — 스캔·재고 목록에서 들어가는 곳이라 "
                              "링크할 고정 주소가 없다(진입점이 아니다)",
    "/mobile/guide/s/<key>": "크롤 가이드 절 하나 읽기 — 목차(/mobile/guide)에서 "
                             "들어가는 곳이라 링크할 고정 주소가 없다(진입점이 아니다)",
}


def phone_native_rows(is_admin: bool) -> list[dict[str, Any]]:
    """메뉴에 실을 폰 전용 화면 — admin 전용 줄은 member 에게서 감춘다.

    /mobile/* 는 ENVIRONMENT=team-share-dev 에서만 등록된다(app.py). 즉 이 함수가
    도는 곳에선 mobile_crawl 의 admin 게이트도 **항상** 살아 있다 — 모드 분기가 필요 없다.

    사본을 돌려준다 — 부르는 쪽이 무심코 고치면 모듈 전역이 오염된다.
    """
    return [dict(it) for it in PHONE_NATIVE_ROWS
            if (is_admin or not it.get("admin_only")) and it.get("in_menu", True)]


# ════════════════════════════════════════════════════════════
#  Task 6 — 하단 탭. 원천은 위 PHONE_NATIVE_ROWS 하나뿐이다.
# ════════════════════════════════════════════════════════════

def tab_rows(is_admin: bool) -> list[dict[str, Any]]:
    """하단 탭에 실을 줄 — `tab` 필드가 있는 것만, order 순.

    admin 전용 탭(크롤)은 member 에게서 **아예 뺀다** — 남겨 두면 누르는 순간
    403 HTML 만 나오는 칸이 된다('눌러도 아무 일 없는 버튼'). member 는 3칸이
    되는데 빈 자리는 안 남는다: .ms-tab 이 flex:1 이라 칸 수대로 다시 나눈다.

    사본을 돌려준다 — phone_native_rows 와 같은 이유.
    """
    rows = [dict(it) for it in PHONE_NATIVE_ROWS
            if it.get("tab") and (is_admin or not it.get("admin_only"))]
    rows.sort(key=lambda it: it["tab"]["order"])
    return rows


def active_tab_key(path: str) -> str | None:
    """지금 보는 화면이 어느 탭 소속인가 — 소속이 없으면 None(아무 탭도 안 켠다).

    - 탭 화면 자신 → 그 탭. 비교는 same_route 재사용 — 빗금·쿼리 차이를 여기서
      또 처리하면 정규화가 두 벌이 된다.
    - `under_tab` 으로 소속을 밝힌 화면(연속 스캔 → 작업) → 그 부모 탭.
    - /mobile/crawl/* 은 blueprint url_prefix 가 계층 그 자체라 하위 전부 크롤 탭.
    - 그 밖(재고 목록·SKU 상세·설치 안내)은 아무 탭도 안 켠다 — 홈을 켜 두면
      「지금 홈에 있다」는 거짓말이 된다.
    """
    route = same_route(path)
    for it in PHONE_NATIVE_ROWS:
        if same_route(it["url"]) == route:
            tab = it.get("tab")
            if tab:
                return tab["key"]
            if it.get("under_tab"):
                return it["under_tab"]
    if route == "/mobile/crawl" or route.startswith("/mobile/crawl/"):
        return "crawl"
    return None


@bp.app_context_processor
def _tabbar_context() -> dict[str, Any]:
    """_tabbar.html 이 쓰는 도구 두 개를 템플릿에 준다.

    blueprint 전용(context_processor)이 아니라 **app 전역**인 이유 — _base.html 은
    mobile·mobile_crawl·mobile_shell 세 blueprint 가 같이 물려받는데, blueprint
    전용 주입은 자기 라우트가 그릴 때만 걸린다. 전역이어도 함수 참조 두 개를
    돌려줄 뿐이라 PC 화면 렌더에 드는 값은 사실상 0이다(PC 템플릿은 안 쓴다).
    """
    def rows_for_current_user() -> list[dict[str, Any]]:
        # 함수 안 import — 시험이 flask_login.current_user 를 갈아끼워
        # member/admin 두 갈래를 본다(menu() 의 같은 주석 참조).
        from flask_login import current_user
        return tab_rows(bool(getattr(current_user, "is_admin", False)))

    def shell_data() -> dict[str, Any]:
        """base.html 의 ms-tabs-data JSON 한 덩어리 — 탭 + 폰 대응 완료 주소.

        ready 는 same_screen 으로 다듬은 모양으로 보낸다 — JS 쪽 sameScreen 과
        같은 다듬기를 거쳐 그대로 비교된다(정규화 두 벌 금지, 원천은 서버).
        readyPaths 는 PATH_ONLY(쿼리 무시 화면)의 경로 모양(same_route) — [배치4a].
        """
        return {"tabs": rows_for_current_user(),
                "ready": sorted(MOBILE_READY_SCREENS),
                "readyPaths": sorted(MOBILE_READY_PATH_ONLY_ROUTES)}

    return {"ms_tab_rows": rows_for_current_user, "ms_active_tab": active_tab_key,
            "ms_shell_data": shell_data}


@bp.route("/menu")
def menu():
    """'전체' — PC 상단 메뉴와 같은 원천(sidebar_layout)을 읽어 목록으로 편다.

    폰 전용 메뉴를 따로 정의하지 않는다. 새 화면을 만들 때 한쪽에만 넣고
    다른 쪽엔 빼먹는 사고를 구조적으로 막기 위해서다(이 프로젝트엔 그 실제 기록이 있다).
    """
    # 🔴 이 import 는 **함수 안**에 둔다 — 모듈 상단으로 '정리'하면 권한 시험이 깨진다.
    #   시험이 flask_login.current_user 를 갈아끼워 member/admin 두 갈래를 보는데,
    #   상단 import 는 갈아끼우기 전의 프록시를 모듈에 붙잡아 둔다.
    from flask_login import current_user

    from webapp.routes.api_sidebar import get_layout_for_template
    is_admin = bool(getattr(current_user, "is_admin", False))
    return render_template("mobile/menu.html",
                           layout=get_layout_for_template(),
                           phone_native=phone_native_rows(is_admin),
                           is_phone_native=is_phone_native)


@bp.route("/install")
def install():
    """홈 화면에 추가하는 방법 — 아이폰 사파리 / 안드로이드 크롬."""
    return render_template("mobile/install.html")
