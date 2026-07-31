# -*- coding: utf-8 -*-
"""옵션생성 & 상품생성 — 허브.

설계서: docs/superpowers/specs/2026-08-01-옵션생성-상품생성-탭-design.md
배치 확정: A2 (가로탭 2개 + 옵션 생성 안에서 카드 2장) — 노션 원문 그대로.

⚠️ 1단계는 **자리만 만든다.** 실제 옵션 만들기 화면은 3단계에서 온다.
   그때까지 카드는 「지금은 어디서 하는지」를 알려주고 그 화면으로 보낸다.
   없는 기능을 있는 척하면 사장님이 눌렀을 때 빈 화면을 본다.
"""
from flask import Blueprint, render_template, request

bp = Blueprint('optgen', __name__, url_prefix='/optgen')

#: 상단 가로탭. ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(catalog·bulk 와 같은 함정).
SUBTABS = [
    {'key': 'option', 'label': '모음전 옵션 생성',
     'desc': '색상·사이즈를 정해 옵션을 만듭니다'},
    {'key': 'product', 'label': '모음전 상품 생성',
     'desc': '만들어 둔 옵션을 담아 파는 단위를 만듭니다'},
]


@bp.get('/')
def index():
    tab = request.args.get('tab', 'option')
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'option'                      # 모르는 값은 조용히 빈 화면 대신 기본 탭
    return render_template('optgen/index.html',
                           active_app='bundles', active='optgen',
                           subtabs=SUBTABS, tab=tab)
