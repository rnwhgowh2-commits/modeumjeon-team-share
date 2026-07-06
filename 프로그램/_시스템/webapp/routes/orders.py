"""[v2] 주문·정산·CS·신규등록 — `/orders`.

판매자 마켓 API 연동 데이터 위에서 동작(주문·정산·문의반품·신규등록·마진).
확장 기능 커넥터(lemouton.markets.capabilities) + 마스터 게이트 LEMOUTON_MARKET_EXTRA.
게이트 OFF(기본) = '연결됨(검증대기)' — 샘플 미리보기 + 액션 버튼 비활성. 실데이터는
실계정 키 연결 + 검증 후. (관련: CLAUDE.md 🔒 3대 원칙 — 검증 전 완료/전송 금지)

레이아웃 = 사용자 확정 "5번(KPI 요약 + 표)" — 네 탭(list·sales·cs·register)이 공통.
"""
import datetime as _dt
import io as _io

from flask import Blueprint, render_template, request, send_file, abort

from lemouton.markets import capabilities as _cap
from lemouton.markets import order_export as _oe


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '📋 주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    {'key': 'sales', 'label': '💵 정산·매출', 'desc': '마켓별 정산 예정금액·매출 집계'},
    {'key': 'cs', 'label': '💬 문의·반품', 'desc': '고객문의·반품/취소/교환 조회·처리'},
    {'key': 'register', 'label': '🆕 신규 상품 등록', 'desc': '모음전 상품을 마켓에 신규 등록'},
    {'key': 'margin', 'label': '🧮 마진 계산기', 'desc': '가격·수수료·배송비 입력 → 실 마진 시뮬'},
]

# 각 탭의 "5번 레이아웃"(KPI 요약 + 표) 설정. rows/kpis 는 레이아웃 미리보기용 샘플
# (실데이터 아님 — 게이트+검증 후 capabilities.resolve 로 대체). cols type: text/num/mono/mk/status.
TAB_CONFIG = {
    'list': {
        'kpis': [('신규주문', '2건'), ('발송대기', '1건'), ('발송완료', '2건'), ('주문 합계', '774,000원')],
        'cols': [('no', '주문번호', 'mono'), ('mk', '마켓', 'mk'), ('pd', '상품 · 옵션', 'text'),
                 ('qty', '수량', 'num'), ('amt', '금액', 'num'), ('net', '정산예정금액', 'num'),
                 ('date', '주문일', 'text'), ('st', '상태', 'status')],
        'action': '송장입력',
        'rows': [
            {'no': '2026070500123', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트 · 베이지/95', 'qty': '1', 'amt': '189,000원', 'net': '169,155원', 'date': '07-05 09:12', 'st': {'t': '발송대기', 'c': 'wait'}},
            {'no': '2026070500118', 'mk': '스마트스토어', 'pd': '르무통 울 머플러 · 차콜', 'qty': '2', 'amt': '118,000원', 'net': '111,510원', 'date': '07-05 08:40', 'st': {'t': '신규주문', 'c': 'new'}},
            {'no': '2026070500097', 'mk': '쿠팡', 'pd': '르무통 니트 집업 · 네이비/100', 'qty': '1', 'amt': '129,000원', 'net': '—', 'date': '07-05 07:55', 'st': {'t': '신규주문', 'c': 'new'}},
            {'no': '2026070499801', 'mk': '스마트스토어', 'pd': '르무통 램스울 가디건 · 오트밀/M', 'qty': '1', 'amt': '149,000원', 'net': '140,540원', 'date': '07-04 21:03', 'st': {'t': '발송완료', 'c': 'done'}},
            {'no': '2026070499777', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트 · 블랙/100', 'qty': '1', 'amt': '189,000원', 'net': '169,155원', 'date': '07-04 19:41', 'st': {'t': '발송완료', 'c': 'done'}},
        ],
    },
    'sales': {
        'kpis': [('정산 예정', '3건'), ('정산 완료', '12건'), ('이번달 매출', '4,820,000원'), ('예상 수수료', '486,000원')],
        'cols': [('no', '정산번호', 'mono'), ('mk', '마켓', 'mk'), ('pd', '상품', 'text'),
                 ('sale', '판매액', 'num'), ('fee', '수수료', 'num'), ('net', '정산 예정액', 'num'), ('date', '정산일', 'text'), ('st', '상태', 'status')],
        'action': None,
        'rows': [
            {'no': 'ST-260705-01', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트', 'sale': '189,000원', 'fee': '19,845원', 'net': '169,155원', 'date': '07-12 예정', 'st': {'t': '정산 예정', 'c': 'new'}},
            {'no': 'ST-260705-02', 'mk': '스마트스토어', 'pd': '르무통 울 머플러', 'sale': '118,000원', 'fee': '6,490원', 'net': '111,510원', 'date': '07-11 예정', 'st': {'t': '정산 예정', 'c': 'new'}},
            {'no': 'ST-260628-14', 'mk': '쿠팡', 'pd': '르무통 니트 집업', 'sale': '129,000원', 'fee': '13,545원', 'net': '115,455원', 'date': '07-04 완료', 'st': {'t': '정산 완료', 'c': 'done'}},
        ],
    },
    'cs': {
        'kpis': [('미답변 문의', '2건'), ('답변 완료', '8건'), ('반품 요청', '1건'), ('처리 완료', '5건')],
        'cols': [('kind', '유형', 'text'), ('mk', '마켓', 'mk'), ('pd', '상품', 'text'),
                 ('body', '내용', 'text'), ('date', '접수일', 'text'), ('st', '상태', 'status')],
        'action': '처리',
        'rows': [
            {'kind': '문의', 'mk': '쿠팡', 'pd': '르무통 캐시미어 코트', 'body': '배송 언제 되나요?', 'date': '07-05 10:20', 'st': {'t': '미답변', 'c': 'new'}},
            {'kind': '반품', 'mk': '스마트스토어', 'pd': '르무통 램스울 가디건', 'body': '사이즈가 안 맞아요', 'date': '07-05 09:05', 'st': {'t': '반품요청', 'c': 'wait'}},
            {'kind': '문의', 'mk': '쿠팡', 'pd': '르무통 울 머플러', 'body': '색상 차이 문의', 'date': '07-04 18:30', 'st': {'t': '답변완료', 'c': 'done'}},
        ],
    },
    'register': {
        'kpis': [('등록 대기', '4건'), ('등록 완료', '20건'), ('검토중', '2건'), ('반려', '1건')],
        'cols': [('pd', '상품명', 'text'), ('brand', '브랜드', 'text'), ('opt', '옵션수', 'num'),
                 ('cat', '카테고리', 'text'), ('mk', '마켓', 'mk'), ('st', '상태', 'status')],
        'action': '등록',
        'rows': [
            {'pd': '르무통 캐시미어 코트', 'brand': '르무통', 'opt': '12', 'cat': '여성의류 > 코트', 'mk': '쿠팡', 'st': {'t': '등록 대기', 'c': 'new'}},
            {'pd': '르무통 울 머플러', 'brand': '르무통', 'opt': '3', 'cat': '패션잡화 > 머플러', 'mk': '스마트스토어', 'st': {'t': '검토중', 'c': 'wait'}},
            {'pd': '르무통 니트 집업', 'brand': '르무통', 'opt': '9', 'cat': '여성의류 > 니트', 'mk': '쿠팡', 'st': {'t': '등록 완료', 'c': 'done'}},
        ],
    },
}


@bp.route('/')
def orders_index():
    tab = (request.args.get('tab') or 'list').strip()
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'list'
    ctx = dict(active=f'orders_{tab}', tab=tab, subtabs=SUBTABS)
    cfg = TAB_CONFIG.get(tab)
    if cfg:
        live = _cap.market_extra_enabled()   # 기본 False = 안전 OFF
        ctx.update(
            cfg=cfg,
            live_enabled=live,
            # 게이트 OFF = 샘플 미리보기. ON(향후 실fetch 배선 시)이면 빈 목록 → 빈 상태.
            rows=[] if live else cfg['rows'],
            # 주문 내역 탭: 실데이터 엑셀 내보내기 가능한 마켓(코드+키+검증된 것만).
            export_markets=sorted(_oe.SUPPORTED) if tab == 'list' else [],
        )
    return render_template('orders/index.html', **ctx)


@bp.route('/export.xlsx')
def orders_export():
    """선택 마켓 최근 N일 주문 → 샵마인 형식 엑셀 다운로드(서버측 실조회).

    미지원 마켓은 400(추측 데이터 안 만듦). 스마트스토어만 실배선(2026-07-07 검증).
    """
    market = (request.args.get('market') or 'smartstore').strip()
    try:
        days = int(request.args.get('days') or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(90, days))
    try:
        rows = _oe.order_rows(market, days=days)
    except ValueError as e:
        abort(400, str(e))
    except Exception as e:   # noqa: BLE001 — 마켓 API/인증/IP 오류를 사유와 함께 표면화(키는 미노출)
        import logging
        logging.getLogger(__name__).exception("order export failed market=%s", market)
        # 4xx 로 반환(CDN 이 5xx 본문을 자기 페이지로 가려 사유가 안 보임 → 사유 표면화)
        abort(400, f"[{market}] 주문 조회 실패: {type(e).__name__}: {str(e)[:300]}")
    xlsx = _oe.rows_to_xlsx(rows)
    stamp = _dt.datetime.now(_oe.KST).strftime('%Y%m%d')
    fname = f"모음전_{market}_최근{days}일주문_{stamp}.xlsx"
    return send_file(
        _io.BytesIO(xlsx), as_attachment=True, download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
