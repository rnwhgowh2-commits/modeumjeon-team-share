# -*- coding: utf-8 -*-
"""대량등록 모드 — 소싱처 상품을 마켓에 신규 등록하는 3번째 최상위 모드."""
from flask import Blueprint, render_template, request

bp = Blueprint('bulk', __name__, url_prefix='/bulk')

# 대량등록 탭 (Phase 1A 는 manual 만 실동작. 나머지는 Phase 2~5)
SUBTABS = [
    {'key': 'manual', 'label': '✍️ 수기 등록', 'desc': '상품을 직접 입력해 마켓에 등록'},
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
