"""[v2] 주문관리 — `/orders`.

판매자 마켓 API 연동 데이터 위에서 동작:
  - 주문내역 (마켓별 통합)
  - 매출관리 (일/월/마켓별 매출)
  - 마진계산기 (가격×수수료×배송비 → 실 마진)

현재는 placeholder — 백엔드 데이터 fetch / 매출 집계 로직은 후속.
"""
from flask import Blueprint, render_template, request


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '📋 주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    {'key': 'sales', 'label': '💵 매출 관리', 'desc': '일·월·마켓별 매출 집계'},
    {'key': 'margin', 'label': '🧮 마진 계산기', 'desc': '가격·수수료·배송비 입력 → 실 마진 시뮬'},
]


@bp.route('/')
def orders_index():
    tab = (request.args.get('tab') or 'list').strip()
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'list'
    return render_template('orders/index.html', active=f'orders_{tab}',
                           tab=tab, subtabs=SUBTABS)
