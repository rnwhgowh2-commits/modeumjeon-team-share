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

    🔴 물음표 뒤(탭)는 **일부러 안 뗀다.** 주문 관리는 한 주소의 탭 4개가
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
    {"emoji": "🏷", "name": "재고 목록", "url": "/mobile/inventory"},
    # 크롤 리모컨은 admin 전용이다(mobile_crawl._admin_only). member 에게 보여 주면
    # 눌러도 403 만 나오는 줄이 된다 — 이 설계가 가장 피하려는 결과다.
    # 하단 탭의 크롤 칸도 같은 이유로 member 에게는 아예 안 실린다(tab_rows 가 거른다).
    {"emoji": "🛰", "name": "크롤 리모컨", "url": "/mobile/crawl/", "admin_only": True,
     "tab": {"key": "crawl", "icon": "🛰", "label": "크롤", "order": 3}},
    # '전체' 메뉴 — 폰 전용 화면이 맞아 이 목록에 싣는다(탭 원천은 여기 하나뿐이어야
    # 하므로). 단 메뉴 목록에는 안 싣는다(in_menu=False) — 위 주석의 결정 그대로.
    {"emoji": "≡", "name": "전체", "url": "/mobile/menu", "in_menu": False,
     "tab": {"key": "menu", "icon": "≡", "label": "전체", "order": 4}},
]

#: '폰 전용' 배지를 붙일 주소.
#  ★ 3단계에서 PC 화면 하나를 폰 전용으로 바꿀 때는 위 목록에 넣지 말고 그 화면의
#    **PC 주소**(예: '/orders/?tab=list')만 여기에 더한다. 그 화면은 이미 PC 메뉴에
#    있으니, 목록에 또 넣으면 같은 줄이 두 번 뜬다.
#  빗금·#조각 차이는 same_screen 이 흡수한다 — 사이드바가 '/orders?tab=list' 로
#  갖고 있어도 배지가 붙는다(그 어긋남이 예전엔 조용한 실패였다).
PHONE_NATIVE_BADGE_URLS: set[str] = {it["url"] for it in PHONE_NATIVE_ROWS}

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
    return {"ms_tab_rows": rows_for_current_user, "ms_active_tab": active_tab_key}


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
