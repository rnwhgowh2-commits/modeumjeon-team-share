# -*- coding: utf-8 -*-
"""대량등록 모드 — 소싱처 상품을 마켓에 신규 등록하는 3번째 최상위 모드."""
from flask import Blueprint, render_template, request

bp = Blueprint('bulk', __name__, url_prefix='/bulk')

# 대량등록 탭. 설계 정본 = 2026-07-17-신규상품등록-가공템플릿-design.md §3-2 (8탭)
#   ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다 — 만들었으면 반드시 추가할 것.
SUBTABS = [
    {'key': 'collect', 'label': '📥 데이터수집', 'desc': '소싱처에서 상품을 긁어옵니다 · 구성별 변동 주기와 계수'},
    {'key': 'process', 'label': '🔧 데이터가공', 'desc': '가공정책 — 소싱처 URL 을 묶어 마켓별로 내보낼 규칙'},
    {'key': 'send', 'label': '📤 데이터전송', 'desc': '마켓 업로드 — 올린 것·거른 것과 마켓별 속도 제한'},
    {'key': 'manual', 'label': '✍️ 수기 등록', 'desc': '상품을 직접 입력해 마켓에 등록'},
    {'key': 'products', 'label': '📦 상품관리', 'desc': '등록한 상품 · 상품별 업데이트 ON/OFF'},
    # ⑤⑥⑦ 은 기존 화면을 그대로 쓴다(설계서 §3-2: 데이터도 화면도 한 곳에만).
    {'key': 'orders', 'label': '🧾 주문관리', 'desc': '대량등록 주문도 같은 주문 화면에서 — 등록경로로 갈라 봅니다'},
    {'key': 'cs', 'label': '💬 CS관리', 'desc': '취소·반품·교환 + 고객문의 — 모음전 화면 그대로'},
    {'key': 'stats', 'label': '📊 통계', 'desc': '마진 계산기 — 실마진 시뮬'},
    {'key': 'settings', 'label': '⚙️ 설정', 'desc': '등급 경계·계수·하한·상한 — 여기 숫자가 최종입니다'},
]


@bp.context_processor
def inject_bulk_nav():
    """모든 /bulk/* 페이지에 모드·탭 컨텍스트 자동 주입.

    [2026-07-17] subtabs·tab 을 라우트 kwargs 로 넘기지 않는다 — sidebar_bulk.html 이
    쓰는 값이라 라우트마다 넘겨야 하는데, Jinja 는 정의 안 된 이름을 순회해도 예외 없이
    빈 nav 를 그린다(조용한 실패). 여기서 한 번 주입해 전 /bulk/* 가 공유한다.
    """
    _tab = request.args.get('tab', 'manual')
    if _tab not in {t['key'] for t in SUBTABS}:
        _tab = 'manual'   # 모르는 탭은 조용한 빈 화면 대신 기본 탭으로
    return {'active_app': 'bulk', 'subtabs': SUBTABS, 'tab': _tab}


@bp.get('/')
def index():
    # subtabs·tab 은 inject_bulk_nav 가 주입. 여기서 kwargs 로 넘기면 context processor 를
    # 덮어써(명시 kwargs 우선) ?tab= 이 무시되므로 넘기지 말 것.
    return render_template('bulk/index.html')


from . import drafts  # noqa: E402,F401  (드래프트 CRUD·등록 라우트)
from . import margin  # noqa: E402,F401  (최종매입가·마진 미리보기 — Phase 1B M2)
from . import collect  # noqa: E402,F401  (① 데이터수집 — 구성별 등급·계수 제안)
from . import process  # noqa: E402,F401  (② 데이터가공 — 가공정책)
from . import send  # noqa: E402,F401  (③ 데이터전송 — 게이트 결과·마켓별 속도)
from . import settings_tab  # noqa: E402,F401  (⑧ 설정 — 등급 경계·계수·하한·상한)
from . import products  # noqa: E402,F401  (④ 상품관리 — 목록·업데이트 토글)
from . import categories  # noqa: E402,F401  # 카테고리 사전 (M1)
from . import category_map  # noqa: E402,F401  # 맵핑표·브랜드제한표 (M2)
