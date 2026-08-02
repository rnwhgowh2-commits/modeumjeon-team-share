# -*- coding: utf-8 -*-
"""상품 마켓 전송 — 골라서 지금 보내기.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md
사장님 확정 2026-08-02 — 더망고 「상품 업데이트 & 마켓등록/수정」 구조를 따르되
우리 데이터 모델(구성=벌)에 맞춘다.

━━ 🔴 하위탭 원천이 두 곳이다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  화면 가로탭 = 여기 :data:`SUBTABS`
  상단 메뉴 펼침 = `webapp/routes/api_sidebar.py` 의 `_SEND2`
  **둘을 같이 안 고치면 메뉴만 옛것으로 남는다** — optgen 하위탭 때 실제로 겪었다.

━━ 이 탭이 자동화와 다른 점 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  자동화 = 값이 바뀌면 **저절로** 나간다 (조건·주기)
  마켓 전송 = 사장님이 **골라서 지금** 보낸다 (신규 등록 포함)
"""
from flask import Blueprint, redirect, render_template, request

bp = Blueprint('market_send', __name__)

#: 상단 분류 「상품 마켓 전송」의 하위탭 2개 — 사장님 확정 ⑤.
#  ⚠️ 여기 없는 탭은 화면에 아예 안 뜬다(catalog·bulk·optgen 과 같은 함정).
SUBTABS = [
    {'key': 'send', 'label': '마켓 전송', 'url': '/market-send',
     'desc': '보낼 상품을 골라 지금 마켓으로 보냅니다'},
    {'key': 'auto', 'label': '자동화', 'url': '/automation',
     'desc': '소싱처 수집과 판매처 전송이 저절로 돌게 합니다'},
]


@bp.get('/market-send')
def index():
    """마켓 전송 — 필터·목록·전송 실행.

    지금은 자리(탭)만 잡는다. 필터·목록은 설계서 §4 · 4단계에서 채운다.
    🔴 빈 화면을 그냥 두지 않는다 — 「아직 안 만들어졌다」를 화면이 말해야
      사장님이 「고장났나」로 헤매지 않는다.
    """
    return render_template('market_send/index.html',
                           active_app='send', active='market_send',
                           subtabs=SUBTABS, tab='send')


@bp.get('/automation/')
def automation_slash():
    """끝에 빗금 붙은 주소도 자동화로 — 저장해 둔 바로가기가 죽지 않게."""
    return redirect('/automation' + (('?' + request.query_string.decode())
                                     if request.query_string else ''), code=302)
