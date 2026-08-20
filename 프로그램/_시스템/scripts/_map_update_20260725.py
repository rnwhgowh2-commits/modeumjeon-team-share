# -*- coding: utf-8 -*-
"""[일회성] 2026-07-25 판매처 지도 최신화 — 전 마켓 정산조회 API 실측 반영.

update-data-code-map 갈래: 정산 스윕 검수(6마켓)에서 라이브로 확정한 정산조회 API 제약·
조인키·급소를 idTraps·codeRef 에 축적하고, 발견/수정한 사고를 incidents 에 기록한다.
근거 PR: #460 #462 #466 #473 #475 #476 #478 #479 (본 다중 세션 라이브 실증).
실행 후 validate_map·pytest 통과 확인하고 이 스크립트는 남겨둔다(갱신 근거 기록).
멱등: 이미 있는 trap/incident 는 다시 넣지 않는다(다른 세션 동시편집 안전).
"""
import io
import json

P = 'webapp/data/marketplace_api_map.json'
d = json.load(io.open(P, encoding='utf-8'))
by_id = {a['id']: a for a in d['apis']}
changed = {'traps': 0, 'coderef': 0, 'inc': 0}


def add_traps(aid, notes):
    a = by_id.get(aid)
    if not a:
        print('  ! api 없음:', aid)
        return
    traps = a.setdefault('idTraps', [])
    for n in notes:
        if n not in traps:
            traps.append(n)
            changed['traps'] += 1


def set_coderef(aid, ref):
    """codeRef 가 비어 있을 때만 채운다(다른 세션이 넣은 값 안 덮음)."""
    a = by_id.get(aid)
    if a is not None and not (a.get('codeRef') or '').strip():
        a['codeRef'] = ref
        changed['coderef'] += 1


def add_incident(inc):
    incs = d.setdefault('incidents', [])
    if any(x.get('id') == inc['id'] for x in incs):
        return
    incs.append(inc)
    changed['inc'] += 1


# ── ESM 판매대금 정산조회(esm.41) — 5초 버킷 무관·계정별 필수·기준일 ──────────
for m in ('auction', 'gmarket'):
    add_traps(f'{m}.esm.41', [
        '★[2026-07-25] 정산조회는 주문조회 5초/1콜 버킷을 **안 쓴다** — '
        'client.request_settlement 는 post(is_order=False)라 _throttle_orders 미적용. '
        '제한이 걸리더라도 seller 계정별이므로 계정 병렬 안전(rate 버킷=계정). '
        '로그인·세션 없음(계정별 키로 요청마다 JWT 서명).',
        '★[2026-07-25] **계정별로 물어야** 실 주문이 나온다 — 대표 계정만으로는 다른 계정 '
        '주문의 정산이 통째로 안 나온다(라이브: 대표 07-01~05=2건, 브랜드위시=4건 전부). '
        'SrchType 기준일: D1 입금확인일·D3 배송완료일·D4 구매결정일·D5 정산예정일·'
        'D6 송금일·D7 환불일. 조회창 최대 31일. 3000(호출제한) 오면 지수 백오프 재시도.',
    ])
    set_coderef(f'{m}.esm.41',
                'shared/platforms/esm/settlements.py::settle_detail_map · '
                'lemouton/markets/order_ingest.py::refresh_settlement')

# ── 쿠팡 매출내역(revenue-history) — 조회창 1개월 미만 ───────────────────────
add_traps('coupang.settlement.sales-detail-query', [
    '🔴[2026-07-25] 조회창 **≤25일** — "Date range period must be less than 1 months" 400. '
    '30일 창은 매 요청 거부라 정산 스윕이 겉만 돌고 0건(배송완료 1,361건 추정치 고착의 '
    '원인·창 25일로 수정 후 1,481건 회수). recognitionDate(인식일) 기준이라 옛 주문의 새 '
    '정산은 최근 인식일 창으로 되짚는다. 조인키=(orderId,vendorItemId). '
    'items[].settlementAmount 는 REFUND 도 양수 → saleType=REFUND 면 차감. '
    'deliveryFee.settlementAmount 는 이미 부호 실림(그대로 합산).',
])
set_coderef('coupang.settlement.sales-detail-query',
            'shared/platforms/coupang/settlements.py::fetch_revenue_page · '
            'lemouton/markets/order_export.py::_coupang_settle_map · '
            'order_ingest.py::refresh_settlement_coupang')

# ── 스마트스토어 정산(건별·결제일 기준) ─────────────────────────────────────
add_traps('smartstore.find-settle-by-case-pay-settle', [
    '[2026-07-25] 정산조회는 **하루씩**(searchDate 단일일)·periodType 결정'
    '(SETTLE_CASEBYCASE_PAY_DATE=결제일 기준). 병렬 시 **429**(AdaptiveLimiter·IP 기준)라 '
    '계정 내 순차 필수·retry_after 존중(즉시 실패로 굳히면 그 하루 정산이 통째 유실). '
    '조인키=productOrderId(상품정산)+orderId(배송비정산·주문당 1회). pageSize≤1000. '
    '아주 옛 정산은 네이버 조회한도 밖일 수 있음(1월분 회복 0 실측).',
])
set_coderef('smartstore.find-settle-by-case-pay-settle',
            'shared/platforms/smartstore/settlements.py::iter_settle_by_case,settle_expect_maps · '
            'order_ingest.py::refresh_settlement_smartstore')

# ── 롯데온 정산(상품별 주문내역·SettleProduct/scan) ─────────────────────────
add_traps('lotteon.settlement.list', [
    '★★[2026-07-25] itmd(scan)는 **odNo 단위 합계**(라인 아님) → 다품 주문의 각 라인에 '
    '그대로 쓰면 2배 계상. 단품 주문(저장 라인 1개)에만 쓰고, 다품은 라인 정밀 크롤 DB'
    '(LotteonSettlement·pymt_tgt_amt·(od_no,od_seq))가 있을 때만 채운다. '
    'pymtAmt 는 **배송비 포함액** → 상품분으로 저장 시 _lo_subtract_shipping_once 로 배송비 '
    '차감(안 하면 유료배송마다 배송비포함=pymtAmt+배송비 로 마진 과대). '
    'SettleItmdSales 페이징 급소(pageNo/rowsPerPage MAX100, 서버가 pageNo 무시 시 블로업).',
])
set_coderef('lotteon.settlement.list',
            'shared/platforms/lotteon/settlement.py::scan · '
            'order_ingest.py::refresh_settlement_lotteon')

# ── incidents (2026-07-25) ──────────────────────────────────────────────────
add_incident({
    'id': '2026-07-25-margin-settle-source-orphan',
    'date': '2026-07-25', 'markets': ['gmarket', 'auction', 'lotteon'],
    'area': '정산·마진', 'title': '정산 금액은 있는데 근거 배지가 갈라져 마진이 0으로 떨어졌다',
    'symptom': '사장님 화면 정산금 0(판매가 81,800·매입 59,510) — 주문내역 탭은 69,530 을 보여줌',
    'cause': 'order_store._merge_row 가 빈 값은 안 덮지만 "none" 은 빈 값이 아니라서 덮어 '
             '_settle_source 소실. 마진 _settlement_for 는 근거 없는 금액을 안 씀. 구매결정은 '
             'DONE_STATUSES 라 재조회도 안 돼 영구 고착(G마켓 43건).',
    'fix': '_merge_row 가 정산액 못 가져온 조회는 태그도 갱신 안 함(재발 방지) + '
           'order_export._retag_orphan_settlement 가 읽을 때 store 태깅(치유는 상태 이름 아닌 '
           '돈으로 — 정산<실결제일 때만, 회수지시 매출-in-정산 오인 방지).',
    'commit': 'PR#460 · PR#462', 'severity': 'high', 'status': 'resolved',
    'lesson': '태그는 금액의 설명이다 — 한 벌로 움직여야 한다. 치유 판정은 상태 이름이 아니라 돈으로.',
})
add_incident({
    'id': '2026-07-25-settle-after-purchase-confirm-sweep',
    'date': '2026-07-25', 'markets': ['gmarket', 'auction', 'coupang', 'smartstore', 'lotteon'],
    'area': '정산·수집', 'title': '정산은 구매확정 뒤에 확정되는데 끝난 주문을 다시 안 봐 추정치로 고착',
    'symptom': '전 마켓 실측 고착: 스스 1,682·쿠팡 1,361·롯데온 453 (real이 스스 4%뿐)',
    'cause': '증분 수집은 최근 7~21일만 훑고 refresh_open_orders 는 끝난 주문(구매확정·배송완료)을 '
             '건너뜀. 창이 닫힌 뒤 마켓에 실정산이 들어와도 다시 안 봐서 못 받음. 에러 없음(실패가 '
             '아니라 「안 본 것」)이라 로그·경보 전무.',
    'fix': '주문 조회 없이 **정산조회만** 훑는 마켓별 스윕(refresh_settlement[_coupang/_smartstore/'
           '_lotteon]) 신설·30분 틱·수동 라우트. 추정치 경보(_stale_settle_notice)를 6마켓으로 확대. '
           '실적: 스스 4→91% · 쿠팡 real 2,022→3,383.',
    'commit': 'PR#466 · #473 · #476 · #478 · #479', 'severity': 'high', 'status': 'resolved',
    'lesson': '정산은 주문 종결 뒤에 들어온다 — 끝난 주문도 정산은 계속 봐야 한다. 안 들어온 것을 '
              '경보로 드러내 조용한 고착을 막는다.',
})
add_incident({
    'id': '2026-07-25-coupang-revenue-window-1month',
    'date': '2026-07-25', 'markets': ['coupang'],
    'area': '정산', 'title': '쿠팡 정산 스윕이 매번 HTTP 400 으로 0건 — revenue 조회창 1개월 초과',
    'symptom': '넓은 정산 스윕이 7계정 전부 400 "Date range period must be less than 1 months" → settle_rows 0',
    'cause': 'revenue-history 는 발주서(31일)보다 창이 좁아 "1개월 미만"만 허용. 30일 창(_cp_windows '
             'days=30)은 매 요청 거부. 인식일 스윕 특유라 최근 주문(작은 창)엔 안 드러나고 과거 '
             'backlog 만 조용히 고착.',
    'fix': 'revenue-history 창을 25일로(_cp_windows days=25). 발주서 경로 무관. 배송완료 1,361건 회복.',
    'commit': 'PR#475', 'severity': 'high', 'status': 'resolved',
    'lesson': '같은 마켓도 엔드포인트마다 조회창 상한이 다르다 — 발주서 31일 ≠ revenue 1개월 미만.',
})

json.dump(d, io.open(P, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('갱신:', changed)
