"""[v2] 주문관리 — `/orders`.

판매자 마켓 API 연동 데이터 위에서 동작:
  - 주문내역 (마켓별 통합)
  - 매출관리 (일/월/마켓별 매출)
  - 마진계산기 (가격×수수료×배송비 → 실 마진)

현재는 placeholder — 백엔드 데이터 fetch / 매출 집계 로직은 후속.
"""
from flask import Blueprint, render_template, request

from lemouton.markets import capabilities as _cap


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '📋 주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    {'key': 'sales', 'label': '💵 매출 관리', 'desc': '일·월·마켓별 매출 집계'},
    {'key': 'margin', 'label': '🧮 마진 계산기', 'desc': '가격·수수료·배송비 입력 → 실 마진 시뮬'},
]

# 레이아웃 미리보기용 샘플(실주문 아님). 실주문은 실계정 키 연결 + 검증 후
# capabilities.resolve('coupang','order_fetch') 등으로 불러온다(LEMOUTON_MARKET_EXTRA).
_SAMPLE_ORDERS = [
    {'no': '2026070500123', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트', 'opt': '베이지/95', 'qty': 1, 'amt': 189000, 'date': '07-05 09:12', 'st': 'wait'},
    {'no': '2026070500118', 'mk': '스마트스토어', 'pd': '르무통 울 머플러', 'opt': '차콜', 'qty': 2, 'amt': 118000, 'date': '07-05 08:40', 'st': 'new'},
    {'no': '2026070500097', 'mk': '쿠팡', 'pd': '르무통 니트 집업', 'opt': '네이비/100', 'qty': 1, 'amt': 129000, 'date': '07-05 07:55', 'st': 'new'},
    {'no': '2026070499801', 'mk': '스마트스토어', 'pd': '르무통 램스울 가디건', 'opt': '오트밀/M', 'qty': 1, 'amt': 149000, 'date': '07-04 21:03', 'st': 'done'},
    {'no': '2026070499777', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트', 'opt': '블랙/100', 'qty': 1, 'amt': 189000, 'date': '07-04 19:41', 'st': 'done'},
]

_ST_LABEL = {'new': '신규주문', 'wait': '발송대기', 'done': '발송완료'}


@bp.route('/')
def orders_index():
    tab = (request.args.get('tab') or 'list').strip()
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'list'
    ctx = dict(active=f'orders_{tab}', tab=tab, subtabs=SUBTABS)
    if tab == 'list':
        # 안전 OFF: 확장 기능 게이트가 켜지고 실계정 검증돼야 실주문을 부른다.
        # 그 전까지는 커넥터에 '연결됨(검증대기)'로 등록만 돼 있고, 화면은 샘플 미리보기.
        live = _cap.market_extra_enabled()
        orders = [] if live else list(_SAMPLE_ORDERS)  # live=on 이어도 실fetch 배선은 후속
        ctx.update(
            live_enabled=live,
            orders=orders,
            st_label=_ST_LABEL,
            kpi_new=sum(1 for o in orders if o['st'] == 'new'),
            kpi_wait=sum(1 for o in orders if o['st'] == 'wait'),
            kpi_done=sum(1 for o in orders if o['st'] == 'done'),
            kpi_sum=sum(o['amt'] for o in orders),
        )
    return render_template('orders/index.html', **ctx)
