# -*- coding: utf-8 -*-
"""상품관리 — 마켓에 올라간 상품을 한곳에서.

설계서: docs/superpowers/specs/2026-07-23-모음전-상품관리-design.md
화면 확정: 시안 65장 중 사장님이 고른 7가지(설계서 §6).
"""
from flask import Blueprint, render_template, request

bp = Blueprint('catalog', __name__, url_prefix='/catalog')

#: 상단 가로탭. ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(bulk/__init__.py 와 같은 함정).
SUBTABS = [
    {'key': 'dashboard', 'label': '📊 현황 보기',
     'desc': '마켓·계정별로 몇 개가 어떤 상태인지'},
    {'key': 'pick', 'label': '🔎 상품 담기',
     'desc': '마켓에 올라간 상품에서 찾아 모음전 상품으로'},
    {'key': 'detail', 'label': '📦 상품 상세',
     'desc': '담아둔 상품을 보고 고칩니다'},
]


@bp.context_processor
def inject_catalog_nav():
    """모든 /catalog/* 페이지에 탭 컨텍스트 주입.

    ⚠️ 라우트 kwargs 로 넘기지 않는다 — 안 넘긴 라우트에서 Jinja 가 예외 없이
    빈 nav 를 그린다(조용한 실패). 대량등록에서 같은 함정을 겪었다.
    """
    tab = request.args.get('tab', 'dashboard')
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'dashboard'
    return {'active_app': 'bundles', 'active': 'catalog',
            'catalog_subtabs': SUBTABS, 'catalog_tab': tab}


@bp.get('/')
def index():
    return render_template('catalog/index.html')


from . import dashboard  # noqa: E402,F401  (현황 보기 API)
from . import pick  # noqa: E402,F401  (검색·담기·묶기 API)
