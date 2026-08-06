"""[v2] 주문·정산·CS·신규등록 — `/orders`.

판매자 마켓 API 연동 데이터 위에서 동작(주문·정산·문의반품·신규등록·마진).
확장 기능 커넥터(lemouton.markets.capabilities) + 마스터 게이트 MOUM_MARKET_EXTRA.
게이트 OFF(기본) = '연결됨(검증대기)' — 샘플 미리보기 + 액션 버튼 비활성. 실데이터는
실계정 키 연결 + 검증 후. (관련: CLAUDE.md 🔒 3대 원칙 — 검증 전 완료/전송 금지)

레이아웃 = 사용자 확정 "5번(KPI 요약 + 표)" — 네 탭(list·sales·cs·register)이 공통.
"""
import datetime as _dt
import io as _io
import re as _re

from flask import Blueprint, render_template, request, send_file, abort, make_response, jsonify

from lemouton.markets import capabilities as _cap
from lemouton.markets import order_export as _oe
from lemouton.markets import order_ingest as _oi   # startup 에 완전 로드 — 요청 중 첫 import 시 순환참조 partial 방지
from shared.db import SessionLocal
from lemouton.delivery import service as _dsvc
from lemouton.delivery.mango_parser import parse_mango_xls, MangoParseError
from lemouton.claims import service as _claim_svc
from lemouton.cs_inquiries import service as _inq_svc


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    # [2026-07-24] 송장 넣는 일을 한 곳에 모은 탭. 주문 내역과 **같은 화면 코드**를 쓰되
    #  배치만 4단계로 바꾼다(아이디가 같아야 기존 배선이 그대로 돈다).
    {'key': 'ship', 'label': '송장 작업',
     'desc': '택배사 엑셀 올리기 → 주문 찾아오기 → 송장·상태로 갈라 보기 → 미입력 건 전송'},
    # [2026-07-24] 배송검사(inspect) 탭 삭제 — 「송장 작업」 ②·④ 로 흡수.
    #   같은 일을 하는 화면이 두 벌이라 어디서 뭘 하는지 알 수 없었다(사장님: "거의 안 썼다").
    #   옛 주소는 아래 orders_index 에서 tab=ship 으로 넘긴다(북마크 보호).
    # [2026-07-16] 정산·매출(sales) 탭 삭제(사용자 요청). tab=sales 진입은 list 로 폴백.
    {'key': 'cs', 'label': 'CS', 'desc': '취소·반품·교환 + 고객문의 조회·처리'},
    {'key': 'register', 'label': '신규 상품 등록', 'desc': '모음전 상품을 마켓에 신규 등록'},
    {'key': 'margin', 'label': '마진 계산기', 'desc': '가격·수수료·배송비 입력 → 실 마진 시뮬'},
    {'key': 'recon', 'label': '샵마인 대조', 'desc': '샵마인 정답지 엑셀 ↔ 우리 적재분 전수 대조 (누락·필드차이)'},
    # [2026-08-06] 정산예정금액 — 기간별 미래 정산예정금(자금계획). 🔴 옛 sales 탭 id 재사용
    #   금지(사이드바 _REMOVED_IDS 가 i_sales 를 지운다) — 새 id=settle_plan.
    {'key': 'settle_plan', 'label': '정산예정금액',
     'desc': '기간별로 앞으로 들어올 정산금 — 확정/미확정 구분 · 마켓·계정·주문까지'},
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


# 주문 표(마켓·열·엑셀)를 그대로 쓰는 탭들 — 같은 화면 코드에 배치만 다르다.
_ORDER_TABS = ('list', 'ship')


@bp.route('/')
def orders_index():
    tab = (request.args.get('tab') or 'list').strip()
    if tab == 'inspect':
        # 옛 「배송검사」 주소 → 「송장 작업」. 북마크·저장된 링크가 깨지지 않게 영구 이동.
        from flask import redirect, url_for
        return redirect(url_for('orders.orders_index', tab='ship'), code=301)
    if tab not in {t['key'] for t in SUBTABS}:
        tab = 'list'
    ctx = dict(active=f'orders_{tab}', tab=tab, subtabs=SUBTABS)
    # 송장 작업은 주문 내역과 같은 화면 설정을 쓴다(별도 샘플 표를 두지 않는다).
    cfg = TAB_CONFIG.get('list' if tab == 'ship' else tab)
    if cfg:
        live = _cap.market_extra_enabled()   # 기본 False = 안전 OFF
        ctx.update(
            cfg=cfg,
            live_enabled=live,
            # 게이트 OFF = 샘플 미리보기. ON(향후 실fetch 배선 시)이면 빈 목록 → 빈 상태.
            rows=[] if live else cfg['rows'],
            # 주문 내역 탭: 실데이터 엑셀 내보내기 가능한 마켓(코드+키+검증된 것만).
            export_markets=sorted(_oe.supported_markets()) if tab in _ORDER_TABS else [],
            all_columns=_oe.ALL_COLUMNS if tab in _ORDER_TABS else [],
            col_meta=_oe.columns_meta() if tab in _ORDER_TABS else {},
        )
    return render_template('orders/index.html', **ctx)


@bp.route('/margin-embed')
def margin_embed():
    """원본 마진계산기 풀페이지(무수정 이식)를 iframe 용 standalone 로 서빙.

    base.html(사이드바/셸)을 확장하지 않는 원본 그대로의 전체 페이지다. `/orders?tab=margin`
    에서 same-origin iframe 으로 임베드(C3)하기 위해 X-Frame-Options: SAMEORIGIN 예외를 준다
    (전역 기본 DENY 가 same-origin iframe 까지 막으므로 — marketplace_guide 패턴과 동일).
    엔드포인트는 /api/margin/* 로 재배선됨(업로드·분석·내보내기). 설정(Task D)·소싱 자동검사
    (Task E) 엔드포인트는 원본 URL 유지 — 현재 404 여도 .catch 로 삼켜져 렌더를 막지 않는다.
    """
    resp = make_response(render_template('orders/margin_embed.html'))
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    return resp


def _parse_markets(args):
    """markets(콤마·다중) 또는 market(단일). supported_markets() 로 필터(순서 유지·중복 제거)."""
    raw = args.get('markets') or args.get('market') or 'smartstore'
    out, seen = [], set()
    _sup = _oe.supported_markets()
    for m in raw.split(','):
        m = m.strip()
        if m in _sup and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _parse_days(args):
    try:
        d = int(args.get('days') or 7)
    except (TypeError, ValueError):
        d = 7
    return max(1, min(90, d))


def _parse_cols(args):
    raw = (args.get('cols') or '').strip()
    return [c for c in raw.split(',') if c] if raw else None


#  실시간 조회로 감당되는 상한. 이보다 넓으면 적재분(order_store)에서 읽는다.
LIVE_RANGE_DAYS = 90
MAX_RANGE_DAYS = 365


def _is_long_range(since, until) -> bool:
    return bool(since and until and (until - since).days > LIVE_RANGE_DAYS)


def _rows_from_store(markets, since, until):
    """적재분에서 읽고, **얼마나 쌓였는지 함께 알린다**.

    아직 백필을 안 했으면 결과가 비거나 짧다. 그걸 말없이 빈 화면으로 보여주면
    「주문이 없다」로 오해한다 — 적재 현황을 배너로 명시한다(조용한 실패 금지).
    """
    from lemouton.markets import order_store as _os
    s, u = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")
    try:
        rows = _os.load(markets, since=s, until=u)
        cov = {c["market"]: c for c in _os.coverage()}
    except Exception as e:            # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("store load failed markets=%s", markets)
        return [], f"적재분을 읽지 못했어요({type(e).__name__}). 90일 이내로 조회해 주세요."

    # 90일 이내(라이브) 화면과 같은 수준으로 보강 — 같은 주문이 조회 기간에 따라 다르게
    # 보이면 안 된다(읽기 전용·새 API 호출 없음). 보강이 실패해도 주문은 그대로 보여준다.
    try:
        _oe.enrich_stored_rows(rows)
    except Exception:                 # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("store rows enrich failed markets=%s", markets)

    missing = [m for m in markets if m not in cov]
    note = ("90일이 넘는 기간은 저장해둔 주문에서 보여드려요"
            "(실시간으로 1년치를 부르면 수십 분이 걸려요). ")
    if missing:
        note += (f"아직 저장된 게 없는 마켓: {', '.join(missing)} — "
                 "'주문 적재' 백필을 한 번 돌려주세요. ")
    have = [f"{m}: {c['oldest'][:10] or '?'}~{c['newest'][:10] or '?'} {c['rows']}건"
            for m, c in cov.items() if m in markets]
    if have:
        note += "저장된 범위 — " + " / ".join(have)
    return rows, note


def _parse_range(args):
    """from·to(YYYY-MM-DD) → (since, until) KST datetime. 없으면 (None, None)=days 사용.

    since=시작일 00:00, until=종료일 23:59:59.999 (그 날 하루 전체 포함). 잘못된 형식·역순은
    무시(None) → days 폴백.

    상한 = 365일. 예전엔 90일이었는데, 그게 「1년치를 못 본다」의 진짜 원인이었다
    (마켓 API 제약이 아니라 우리 클램프였다 — 2026-07-20 실측). 90일을 넘는 구간은
    실시간 조회로는 감당이 안 돼(1년치 ≈ 1,760회 호출) 적재분에서 읽는다.
    """
    fr = (args.get('from') or '').strip()
    to = (args.get('to') or '').strip()
    if not fr or not to:
        return None, None
    try:
        d1 = _dt.datetime.strptime(fr, '%Y-%m-%d').date()
        d2 = _dt.datetime.strptime(to, '%Y-%m-%d').date()
    except ValueError:
        return None, None
    if d2 < d1:
        d1, d2 = d2, d1
    if (d2 - d1).days > MAX_RANGE_DAYS:
        d1 = d2 - _dt.timedelta(days=MAX_RANGE_DAYS)
    since = _dt.datetime(d1.year, d1.month, d1.day, 0, 0, 0, tzinfo=_oe.KST)
    until = _dt.datetime(d2.year, d2.month, d2.day, 23, 59, 59, 999000, tzinfo=_oe.KST)
    return since, until


@bp.route('/cs/claims.json')
def cs_claims():
    markets = _parse_markets(request.args)
    since, until = _parse_range(request.args)
    try:
        res = _claim_svc.list_claims(markets, since=since, until=until)
        return jsonify(ok=True, **res)
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("cs claims failed markets=%s", markets)
        return jsonify(ok=False, error=str(e), groups={"신규요청": [], "대응중": [], "대응완료": []},
                       market_counts={"전체": 0})


@bp.route('/cs/claims/ack', methods=['POST'])
def cs_claim_ack():
    d = request.get_json(silent=True) or {}
    ck = (d.get('claim_key') or '').strip()
    if not ck:
        return jsonify(ok=False, error='claim_key 필요'), 400
    try:
        _claim_svc.acknowledge(ck, market=d.get('market', ''), order_no=d.get('order_no', ''),
                               claim_type=d.get('claim_type', ''))
    except Exception as e:   # noqa: BLE001 — DB 오류를 500 HTML 대신 구조화 JSON 으로(조용한 실패 방지)
        import logging
        logging.getLogger(__name__).exception("cs ack failed ck=%s", ck)
        return jsonify(ok=False, error=str(e)), 200
    return jsonify(ok=True)


@bp.route('/cs/claims/dismiss', methods=['POST'])
def cs_claim_dismiss():
    d = request.get_json(silent=True) or {}
    ck = (d.get('claim_key') or '').strip()
    if not ck:
        return jsonify(ok=False, error='claim_key 필요'), 400
    try:
        _claim_svc.dismiss_claim(ck, market=d.get('market', ''), order_no=d.get('order_no', ''),
                                 claim_type=d.get('claim_type', ''))
    except Exception as e:   # noqa: BLE001 — DB 오류를 500 HTML 대신 구조화 JSON 으로(조용한 실패 방지)
        import logging
        logging.getLogger(__name__).exception("cs claim dismiss failed ck=%s", ck)
        return jsonify(ok=False, error=str(e)), 200
    return jsonify(ok=True)


@bp.route('/cs/claims/unack', methods=['POST'])
def cs_claim_unack():
    d = request.get_json(silent=True) or {}
    ck = (d.get('claim_key') or '').strip()
    if not ck:
        return jsonify(ok=False, error='claim_key 필요'), 400
    try:
        _claim_svc.unacknowledge(ck, market=d.get('market', ''), order_no=d.get('order_no', ''),
                                 claim_type=d.get('claim_type', ''))
    except Exception as e:   # noqa: BLE001 — DB 오류를 500 HTML 대신 구조화 JSON 으로(조용한 실패 방지)
        import logging
        logging.getLogger(__name__).exception("cs unack failed ck=%s", ck)
        return jsonify(ok=False, error=str(e)), 200
    return jsonify(ok=True)


@bp.route('/cs/claims/memo', methods=['POST'])
def cs_claim_memo():
    d = request.get_json(silent=True) or {}
    ck = (d.get('claim_key') or '').strip()
    if not ck:
        return jsonify(ok=False, error='claim_key 필요'), 400
    try:
        _claim_svc.save_memo(ck, d.get('memo', ''), market=d.get('market', ''),
                             order_no=d.get('order_no', ''), claim_type=d.get('claim_type', ''))
    except Exception as e:   # noqa: BLE001 — DB 오류를 500 HTML 대신 구조화 JSON 으로(조용한 실패 방지)
        import logging
        logging.getLogger(__name__).exception("cs memo failed ck=%s", ck)
        return jsonify(ok=False, error=str(e)), 200
    return jsonify(ok=True)


@bp.route('/cs/inquiries.json')
def cs_inquiries():
    markets = _parse_markets(request.args)
    since, until = _parse_range(request.args)
    try:
        res = _inq_svc.list_inquiries(markets, since=since, until=until)
        return jsonify(ok=True, **res)
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("cs inquiries failed")
        return jsonify(ok=False, error=str(e), groups={"미답변": [], "답변완료": []},
                       market_counts={"전체": 0}, warnings=[])


@bp.route('/cs/inquiries/dismiss', methods=['POST'])
def cs_inquiry_dismiss():
    d = request.get_json(silent=True) or {}
    ik = (d.get('inquiry_key') or '').strip()
    if not ik:
        return jsonify(ok=False, error='inquiry_key 필요'), 400
    try:
        _inq_svc.dismiss_inquiry(ik, market=d.get('market', ''))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("cs inquiry dismiss failed")
        return jsonify(ok=False, error=str(e)), 200
    return jsonify(ok=True)


@bp.route('/cs/inquiries/reply-preview', methods=['POST'])
def cs_inquiry_reply_preview():
    d = request.get_json(silent=True) or {}
    try:
        res = _inq_svc.reply_preview(d.get('market', ''), d.get('inquiry_id', ''), d.get('content', ''))
        return jsonify(ok=True, **res)
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("cs reply preview failed")
        return jsonify(ok=False, error=str(e)), 200


def _safe_fname(name):
    """다운로드 파일명 위생 처리 — 파일명 금지문자·개행(헤더 인젝션) 제거, .xlsx 보장."""
    name = str(name or "").strip()
    if not name:
        return ""
    name = _re.sub(r'[\\/:*?"<>|\r\n\t]+', '_', name)
    if not name.lower().endswith('.xlsx'):
        name += '.xlsx'
    return name[:120]


def _export_visible_rows():
    """화면에 보이는 행을 '그대로' 엑셀로 — 재조회·추정 없음(화면 = 다운로드 일치).

    클라이언트가 preview.json 으로 받은 원본 행(마스킹 없음)을 화면 필터(filtered) 결과
    그대로 POST 한다. 서버는 열 구성(cols)만 적용해 파일을 만든다. 마켓·계정·기간·검색·
    헤더필터가 모두 화면에서 이미 적용됐으므로, 사용자가 보는 건수와 정확히 일치한다.
    """
    d = request.get_json(silent=True) or {}
    rows = d.get('rows')
    if not isinstance(rows, list):
        abort(400, "내보낼 행이 없어요(화면에 표시된 주문이 없습니다).")
    cols = d.get('cols') or None
    if isinstance(cols, str):
        cols = [c.strip() for c in cols.split(',') if c.strip()]
    xlsx = _oe.rows_to_xlsx(rows, columns=cols)
    fname = _safe_fname(d.get('fname')) or \
        f"모음전_주문_{_dt.datetime.now(_oe.KST).strftime('%Y%m%d')}.xlsx"
    return send_file(
        _io.BytesIO(xlsx), as_attachment=True, download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route('/export.xlsx', methods=['GET', 'POST'])
def orders_export():
    """주문 → 엑셀 다운로드.

    POST(기본·화면 그대로): {rows, cols, fname} 를 받아 화면에 보이는 그 행만 그대로 파일로
      만든다(재조회 없음 → 마켓·계정·기간·검색·헤더필터가 화면과 100% 일치).
    GET(레거시): 선택 마켓(다중) 최근 N일 주문을 서버측 재조회해 통합. markets=콤마구분(다중),
      cols=콤마구분(열 구성·순서). 미지원 마켓/조회실패는 사유와 함께 400.
    """
    if request.method == 'POST':
        return _export_visible_rows()
    markets = _parse_markets(request.args)
    days = _parse_days(request.args)
    since, until = _parse_range(request.args)
    cols = _parse_cols(request.args)
    if not markets:
        abort(400, "선택된 마켓이 없어요(지원: 쿠팡·롯데온·스마트스토어).")
    try:
        # use_cache=True → 방금 대시보드가 받아둔 조회를 재사용(다운로드 즉시).
        rows = _oe.combined_order_rows(markets, days=days, use_cache=True,
                                       since=since, until=until)
    except ValueError as e:
        abort(400, str(e))
    except Exception as e:   # noqa: BLE001 — 마켓 API/인증/IP 오류를 사유와 함께 표면화(키 미노출)
        import logging
        logging.getLogger(__name__).exception("order export failed markets=%s", markets)
        abort(400, f"[{','.join(markets)}] 주문 조회 실패: {type(e).__name__}: {str(e)[:300]}")
    _apply_invoice_ledger(rows)   # 엑셀에도 원장으로 채운 송장 반영
    xlsx = _oe.rows_to_xlsx(rows, columns=cols)
    label = "통합" if len(markets) > 1 else markets[0]
    if since and until:               # 기간 지정 시 파일명에 시작~끝
        period = f"{since.strftime('%Y%m%d')}-{until.strftime('%Y%m%d')}"
    else:
        period = f"최근{days}일_{_dt.datetime.now(_oe.KST).strftime('%Y%m%d')}"
    fname = f"모음전_{label}주문_{period}.xlsx"
    return send_file(
        _io.BytesIO(xlsx), as_attachment=True, download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _mask_name(s):
    s = str(s or "")
    return (s[0] + "*" * (len(s) - 1)) if len(s) >= 2 else s


def _mask_phone(s):
    s = str(s or "")
    d = s.replace("-", "")
    return (s[:3] + "****" + s[-2:]) if len(d) >= 7 else s


def _mask_addr(s):
    # 시/구 수준까지만(앞 2어절)
    parts = str(s or "").split()
    return " ".join(parts[:2]) + (" …" if len(parts) > 2 else "")


@bp.route('/preview.json')
def orders_preview():
    """주문 미리보기(JSON·다중마켓 최신순) — 개인정보 마스킹. 화면 표시용. 원본은 엑셀."""
    from flask import jsonify
    markets = _parse_markets(request.args)
    days = _parse_days(request.args)
    since, until = _parse_range(request.args)
    if not markets:
        return jsonify(ok=False, error="선택된 마켓이 없어요."), 400
    warnings = []   # 일부 계정 조회 실패(IP 미등록 등) → 나머지는 보여주되 배너로 명시
    # ★롯데온 정산 크롤이 멈췄으면 여기서도 알린다 — 정산예정금이 추정치로 남는 원인이라
    #   주문내역·마진계산기 **양쪽 다** 같은 사실을 보여줘야 한다(한쪽만 보는 사람이 있다).
    #   조용한 실패 금지: 2026-08-03 실측에서 이 수집이 10일째 멈춰 있었는데 아무 신호가 없었다.
    if 'lotteon' in (markets or []):
        try:
            from lemouton.margin.sell_source import lotteon_crawl_stalled_notice
            _cn = lotteon_crawl_stalled_notice()
            if _cn:
                warnings.append(_cn.replace('**', ''))   # 이 배너는 마크다운을 안 그린다
        except Exception:   # noqa: BLE001 — 진단이 주문 조회를 죽이면 안 된다
            pass
    if _is_long_range(since, until):
        # 90일 초과 = 실시간 조회로 감당 불가(1년치 ≈ 1,760회 호출·수십 분) → 적재분에서 읽는다.
        rows, note = _rows_from_store(markets, since, until)
        if note:
            warnings.append(note)
        return jsonify(ok=True, markets=markets, days=days, source="store",
                       columns=_oe.ALL_COLUMNS, count=len(rows), rows=rows,
                       warnings=warnings)
    # fresh=1: 실패 계정 「다시 시도」 — 90초 캐시를 읽지 않고 실조회(쓰기는 유지)
    fresh = request.args.get('fresh') in ('1', 'true')
    try:
        rows = _oe.new_order_rows(markets, days=days, use_cache=True,
                                  since=since, until=until, warnings=warnings,
                                  fresh=fresh)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("order preview failed markets=%s", markets)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 400
    _apply_invoice_ledger(rows)   # 한 번 본 송장은 잃지 않게(11번가 구매확정 등)
    # 화면에 원본 그대로(구매자·수령자·전화·주소 마스킹 없이) — 사용자 요청(관리자 화면, 본인 데이터).
    return jsonify(ok=True, markets=markets, days=days,
                   columns=_oe.ALL_COLUMNS, count=len(rows), rows=rows,
                   warnings=warnings)


@bp.route('/flow-daily.json')
def orders_flow_daily():
    """배송흐름 최근 N일 요약 — 날짜별 송장 입력 / 배송 중 / 배송 완료.

    「멈춘 주문 없음」일 때 **무엇을 지켜봤는지** 보여주는 근거다.
    `?date=YYYY-MM-DD&kind=prep|ing|fin|clm|all` 이면 그날 주문 목록을 준다.
    `all` 은 네 갈래를 한 번에 — 화면은 이걸 써서 탭을 눌러도 다시 부르지 않는다.
    적재분만 읽으므로 마켓 호출 0.
    """
    from lemouton.markets import flow_daily as _fd
    date = (request.args.get('date') or '').strip()
    if date:
        kind = (request.args.get('kind') or 'prep').strip()
        if kind not in _fd._KINDS + ('all',):
            return jsonify(ok=False,
                           error="kind 는 %s·all 중 하나예요." % "·".join(_fd._KINDS)), 400
        try:
            return jsonify(ok=True, **_fd.detail(date=date, kind=kind))
        except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
            import logging
            logging.getLogger(__name__).exception("flow-daily 상세 실패")
            return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    try:
        days = max(1, min(int(request.args.get('days') or 7), 31))
    except (TypeError, ValueError):
        days = 7
    try:
        return jsonify(ok=True, **_fd.summarize(days=days))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("flow-daily 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500


@bp.route('/flow-stall.json')
def orders_flow_stall():
    """배송흐름 감시 — 송장 넣고 N시간 넘게 안 움직인 주문. **엑셀과 무관**.

    적재분에서 읽으므로 마켓 호출 0. 기준시각(마켓 발송처리일)이 없어 판정 못 한
    건수는 `unknown` 으로 함께 돌려준다 — 화면이 숨기지 않게(조용한 실패 금지).
    """
    from lemouton.markets import flow_stall as _fs
    try:
        hours = max(1, min(int(request.args.get('hours') or 24), 24 * 14))
        days = max(1, min(int(request.args.get('days') or 21), 365))
    except (TypeError, ValueError):
        hours, days = 24, 21
    try:
        return jsonify(ok=True, **_fs.find_stalled(hours=hours, days=days))
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        import logging
        logging.getLogger(__name__).exception("flow-stall 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500


@bp.route('/account-coverage.json')
def orders_account_coverage():
    """등록해 뒀는데 최근 N일 주문이 하나도 안 들어온 계정. 적재분만 읽는다(마켓 호출 0)."""
    from lemouton.markets import account_coverage as _ac
    try:
        days = max(1, min(int(request.args.get('days') or 21), 365))
    except (TypeError, ValueError):
        days = 21
    try:
        return jsonify(ok=True, **_ac.survey(days=days))
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        import logging
        logging.getLogger(__name__).exception("account-coverage 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500


@bp.post('/price-diff.json')
def orders_price_diff():
    """주문 시점 가격 차이 — 「올릴 때 매입가 / 지금 매입가」 + 지금 사면 마진.

    화면이 **이미 불러온 행을 그대로 보내면** 계산해서 돌려준다. preview.json 안에
    끼워 넣지 않는 이유: 주문 조회는 마켓별 병렬 fetch 라 여기에 소싱 계산을 얹으면
    가장 느린 계산이 주문 표시 전체를 붙잡는다. 표는 먼저 뜨고 가격 칸만 나중에 채운다.

    payload: {rows: [주문행, ...]}  →  {ok, diffs: {행키: {...}}}
    """
    from lemouton.orders import price_diff as _pd
    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    if not rows:
        return jsonify(ok=True, diffs={})
    s = SessionLocal()
    try:
        return jsonify(ok=True, diffs=_pd.build_price_diffs(s, rows))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("price-diff 실패 rows=%d", len(rows))
        # 주문 표는 절대 안 깨진다 — 실패하면 화면은 전 행 '확인 불가'로 남는다.
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


@bp.post('/fulfillment.json')
def orders_fulfillment():
    """주문 3분류 — 이행 / 미이행(재고없음·역마진·확인불가) / 클레임.

    price-diff.json 과 같은 규약: 화면이 **이미 불러온 행을 그대로 보내면** 판정해서
    돌려준다. 주문 조회에 얹지 않는 이유도 같다 — 소싱 계산이 표 전체를 붙잡는다.

    payload: {rows: [주문행, ...]}  →  {ok, marks: {행키: {...}}, summary: {...}}
    """
    from lemouton.orders import fulfillment as _ff
    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    if not rows:
        return jsonify(ok=True, marks={}, summary=_ff.summarize({}))
    s = SessionLocal()
    try:
        marks = _ff.classify_rows(s, rows)
        return jsonify(ok=True, marks=marks, summary=_ff.summarize(marks))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("fulfillment 판정 실패 rows=%d", len(rows))
        # 주문 표는 절대 안 깨진다 — 실패하면 화면은 분류 없이 그대로 남는다.
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────
#  실매입가 — 저장(수기) · 우선순위 조회 · 더망고 매입 엑셀 매칭
#   설계서 docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md §5
#   🔴 주문 라인 인라인 저장 경로는 여기가 처음이다(조사 확인) — 새로 만든 길.
# ──────────────────────────────────────────────────────────────

@bp.post('/api/purchase-price')
def purchase_price_save():
    """수기 실매입가 저장. payload: {line_uid, price, memo?}

    · price 가 비었거나 0 이면 **행을 지운다**(= 「입력 안 함」으로 되돌림).
    · 저장 성공/실패를 그대로 돌려준다 — 화면이 셀에 즉시 표시한다(조용한 실패 금지).
    """
    from lemouton.markets import purchase_price as _pp

    payload = request.get_json(silent=True) or {}
    line_uid = str(payload.get('line_uid') or '').strip()
    if not line_uid:
        return jsonify(ok=False, error="line_uid 가 없어요 — 어느 주문 줄인지 알 수 없습니다."), 400
    raw = payload.get('price')
    if raw not in (None, ''):
        try:                          # 숫자가 아니면 조용히 0(=삭제)으로 흘리지 않는다
            float(str(raw).replace(',', '').strip())
        except (TypeError, ValueError):
            return jsonify(ok=False, error="매입가는 숫자로 적어 주세요."), 400
    memo = payload.get('memo')
    memo = str(memo)[:255] if memo not in (None, '') else None
    s = SessionLocal()
    try:
        row = _pp.upsert(s, line_uid=line_uid, price=raw,
                         source=_pp.SOURCE_MANUAL, memo=memo)
        if row is None:
            return jsonify(ok=True, saved=False, deleted=True, price=None,
                           tier=None, label=_pp.LABEL_UNKNOWN)
        return jsonify(ok=True, saved=True, deleted=False,
                       price=int(row.purchase_price), tier=_pp.TIER_REAL,
                       label=_pp.TIER_LABEL[_pp.TIER_REAL])
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("실매입가 저장 실패 uid=%s", line_uid)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/purchase-price/resolve')
def purchase_price_resolve():
    """매입가 우선순위 3단계 조회. payload: {rows: [주문행, ...]} → {ok, prices:{line_uid:{...}}}

    price-diff.json 과 **같은 규약**: 화면이 이미 불러온 행을 그대로 보내면 계산해 돌려준다
    (주문 조회에 얹으면 소싱 계산이 표 전체를 붙잡는다).
    """
    from lemouton.markets import purchase_price as _pp

    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    uids = [u for u in ((r or {}).get('_line_uid') for r in rows) if u]
    if not uids:
        return jsonify(ok=True, prices={})
    s = SessionLocal()
    try:
        return jsonify(ok=True, prices=_pp.resolve_purchase_price(s, uids, rows=rows))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("매입가 조회 실패 rows=%d", len(rows))
        # 주문 표는 안 깨진다 — 실패하면 매입가 칸만 빈다(옛 값을 최신인 척 하지 않는다).
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────
#  공급방식 — 이 주문을 「무재고」로 보냈나 「사입」으로 보냈나 (사장님 확정 2026-08-06)
#   · 기본 무재고. 행이 없으면 무재고다(기본값을 행으로 만들지 않는다).
#   · 주문 내역·송장 작업이 **같은 템플릿·같은 preview.json** 이라 값은 저절로 공유된다.
#   · 🔴 여기서 재고를 깎지 않는다 — 차감은 포장하며 바코드 찍는 시점(별도 작업).
#   · 실매입가(`/api/purchase-price`)와 같은 규약을 그대로 따른다.
# ──────────────────────────────────────────────────────────────

@bp.post('/api/supply-mode')
def supply_mode_save():
    """한 줄 공급방식 저장. payload: {line_uid, mode}  (mode = 무재고|사입)"""
    from lemouton.markets import supply_mode as _sm

    payload = request.get_json(silent=True) or {}
    line_uid = str(payload.get('line_uid') or '').strip()
    if not line_uid:
        return jsonify(ok=False, error="line_uid 가 없어요 — 어느 주문 줄인지 알 수 없습니다."), 400
    s = SessionLocal()
    try:
        _sm.set_mode(s, line_uid=line_uid, mode=payload.get('mode'))
        mode = _sm.normalize_mode(payload.get('mode'))
        return jsonify(ok=True, line_uid=line_uid, mode=mode, label=_sm.label_of(mode))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("공급방식 저장 실패 uid=%s", line_uid)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/supply-mode/bulk')
def supply_mode_bulk():
    """선택한 여러 줄 일괄 지정. payload: {line_uids: [...], mode}

    🔴 열쇠는 반드시 line_uid — 주문번호로 묶으면 다품목 주문의 형제 줄까지 같이 바뀐다.
    """
    from lemouton.markets import supply_mode as _sm

    payload = request.get_json(silent=True) or {}
    uids = payload.get('line_uids') or []
    if not isinstance(uids, list) or not uids:
        return jsonify(ok=False, error="선택된 주문 줄이 없어요."), 400
    s = SessionLocal()
    try:
        res = _sm.set_many(s, line_uids=uids, mode=payload.get('mode'))
        mode = _sm.normalize_mode(payload.get('mode'))
        return jsonify(ok=True, mode=mode, label=_sm.label_of(mode), **res)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("공급방식 일괄 저장 실패 n=%d", len(uids))
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/supply-mode/resolve')
def supply_mode_resolve():
    """표에 그릴 값 일괄 조회. payload: {rows: [주문행, ...]} → {ok, modes:{line_uid: mode}}

    실매입가 `/api/purchase-price/resolve` 와 같은 규약 — 화면이 이미 불러온 행을 그대로 보낸다.
    지정 안 한 줄도 기본값(무재고)으로 채워 돌려주므로 화면이 분기할 필요가 없다.
    """
    from lemouton.markets import supply_mode as _sm

    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    uids = [u for u in ((r or {}).get('_line_uid') for r in rows) if u]
    if not uids:
        return jsonify(ok=True, modes={})
    s = SessionLocal()
    try:
        return jsonify(ok=True, modes=_sm.get_many_with_default(s, uids))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("공급방식 조회 실패 rows=%d", len(rows))
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


@bp.post('/api/purchase-price/upload-mango')
def purchase_price_upload_mango():
    """더망고 매입 엑셀 업로드 → 주문 라인 매칭 → 실매입가 저장.

    · 파서·키 규칙은 마진 계산기 것을 그대로 쓴다(`margin.buy_parser` · `margin.matcher`).
    · 대상 주문은 **엑셀이 말한 주문번호만** 적재분에서 인덱스로 읽는다(화면과 무관).
    · 🔴 못 붙은 행·후보가 여럿인 행은 버리지 않고 응답에 담는다(화면이 목록으로 보여 준다).
      화면에서 손으로 주문 줄을 지정하는 UI 는 2단계 범위.
    """
    from lemouton.margin.buy_parser import parse_buy
    from lemouton.markets import order_store as _os
    from lemouton.markets import purchase_mango as _pm

    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='파일이 없습니다.'), 400
    fname = (getattr(f, 'filename', '') or '')[:120]
    try:
        buy_df = parse_buy(f.read(), fname)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 422
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        import logging
        logging.getLogger(__name__).exception("더망고 매입 엑셀 파싱 실패 %s", fname)
        return jsonify(ok=False, error=f'엑셀을 읽지 못했어요: {type(e).__name__}'), 400

    order_nos = _pm.order_keys_from_buy(buy_df)
    if not order_nos:
        return jsonify(ok=False, error='엑셀에 마켓주문번호가 하나도 없어요.'), 422
    s = SessionLocal()
    try:
        rows = _os.load(order_nos=order_nos, include_claims=False, session=s)
        res = _pm.apply(s, buy_df, rows, filename=fname)
        return jsonify(ok=True, parsed=int(len(buy_df)),
                       matched=res['matched'], saved=res['saved'],
                       skipped_zero=res['skipped_zero'],
                       unmatched=res['unmatched'], ambiguous=res['ambiguous'])
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("더망고 매입 매칭 실패 %s", fname)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────
#  송장(운송장) 입력·전송
#   · 엑셀 업로드 → 「오픈마켓주문번호」 매칭 → 그 행에 운송장번호
#   · 직접 입력  → 행 선택 + 택배사 + 송장번호
#   · 전송은 **드라이런 기본**. 요청이 live=true 라도 전역 스위치가 꺼져 있으면 강등한다.
# ──────────────────────────────────────────────────────────────

def _live_enabled() -> bool:
    """송장 실전송 스위치(MOUM_LIVE_INVOICE). 테스트에서 monkeypatch 지점.

    가격·재고 자동 업로드(MOUM_LIVE_UPLOAD)와 분리된 스위치다.
    """
    from lemouton.uploader.runtime import live_invoice_enabled
    return live_invoice_enabled()


def _apply_invoice_ledger(rows) -> None:
    """조회 결과에 송장 원장을 적용(제자리 수정).

    ① remember: 배송중·배송완료 등에서 본 진짜 송장번호를 DB 에 보관.
    ② fill_missing: 번호가 빈 발송완료 주문('확인 불가')을 저장분에서 채움.
       → 11번가 구매확정처럼 API 가 번호를 빼먹어도 한 번 본 건 잃지 않는다.
    DB 문제로 주문 화면이 깨지면 안 되므로 실패는 조용히 무시(표시는 원본 그대로).
    """
    try:
        from lemouton.markets import invoice_ledger as _led
        _led.remember(rows)
        _led.fill_missing(rows)
    except Exception:   # noqa: BLE001 — 원장은 보조기능, 주문 조회를 막지 않는다
        import logging
        logging.getLogger(__name__).exception("invoice ledger apply failed")


def _client_for(market: str, alias: str):
    """행의 「쇼핑몰별칭」(계정 표시명) → 그 계정의 마켓 클라이언트.

    별칭이 비었거나 못 찾으면 대표 계정으로 폴백(_account_client 기본).
    다계정에서 엉뚱한 계정으로 송장이 나가지 않도록 별칭 우선 매칭.
    """
    env_prefix = None
    try:
        for prefix, name in (_oe._active_accounts(market) or []):
            if alias and str(name) == str(alias):
                env_prefix = prefix
                break
    except Exception:   # noqa: BLE001 — 계정 조회 실패는 대표 계정 폴백
        env_prefix = None
    return _oe._account_client(market, env_prefix)


def _client_for_diag(market: str, alias: str):
    """[읽기 전용 진단 전용] alias 를 **접미사 무시(퍼지)** 로 계정에 매칭.

    등록 계정명은 "브랜드위시(롯데온)" 인데 마진 화면의 계정 표시는 괄호를 뗀 "브랜드위시"라
    `_client_for` 의 정확매칭이 실패해 대표로 폴백된다(스스·롯데온 진단이 다른 계정 주문을
    0건으로 돌려주던 원인). 진단은 조회만 하므로 base 이름(괄호 앞) 일치로 느슨히 고른다.
    ★송장 발송 등 부작용 경로에는 절대 쓰지 않는다 — 엉뚱한 계정 전송 위험(그래서 별도 함수).
    """
    def _base(s):
        s = str(s or "").strip()
        i = s.find("(")
        return (s[:i] if i > 0 else s).strip()

    env_prefix = None
    if alias:
        want = _base(alias)
        try:
            for prefix, name in (_oe._active_accounts(market) or []):
                if _base(name) == want or str(name) == str(alias):
                    env_prefix = prefix
                    break
        except Exception:   # noqa: BLE001
            env_prefix = None
    return _oe._account_client(market, env_prefix)


@bp.route('/settlement-sweep/run', methods=['POST'])
def orders_settlement_sweep_run():
    """옥션·G마켓·쿠팡·스마트스토어·롯데온·11번가 저장분의 정산액을 마켓 실값으로 갱신(주문 조회 없음).

    스케줄러가 최근 45~75일을 자동으로 훑지만, 그 전에 이미 고착된 과거분은 한 번
    넓게 훑어 줘야 풀린다(2026-07-25 기준 2026-04 까지 43건). 그 수동 창구다.

    `?market=gmarket&from=YYYY-MM-DD&to=YYYY-MM-DD` — 기간 생략 시 기본(최근 60일).
    실정산이 **있는 주문만** 갱신한다(없는 값을 0 으로 채우지 않는다).

    쿠팡·스마트스토어·롯데온·11번가도 지원한다(`?market=coupang` / `smartstore` / `lotteon` / `eleven11`).
    단 이들은 from/to 가 **인식일(구매확정/결제일)** 창이다(주문일이 아니다) — 정산이
    구매확정 뒤 인식되므로 옛 주문도 최근 인식창이 덮는다.
    """
    from flask import jsonify
    market = (request.args.get('market') or '').strip()
    if market not in ('gmarket', 'auction', 'coupang', 'smartstore', 'lotteon', 'eleven11'):
        return jsonify(ok=False, error='옥션·G마켓·쿠팡·스마트스토어·롯데온·11번가 전용이에요.'), 400
    since, until = _parse_range(request.args)
    try:
        if market == 'coupang':
            from lemouton.markets.order_ingest import refresh_settlement_coupang
            st = refresh_settlement_coupang(since=since, until=until)
        elif market == 'smartstore':
            from lemouton.markets.order_ingest import refresh_settlement_smartstore
            st = refresh_settlement_smartstore(since=since, until=until)
        elif market == 'lotteon':
            from lemouton.markets.order_ingest import refresh_settlement_lotteon
            st = refresh_settlement_lotteon(since=since, until=until)
        elif market == 'eleven11':
            from lemouton.markets.order_ingest import refresh_settlement_eleven11
            st = refresh_settlement_eleven11(since=since, until=until)
        else:
            from lemouton.markets.order_ingest import refresh_settlement
            st = refresh_settlement(market, since=since, until=until)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        import logging
        logging.getLogger(__name__).exception('settlement sweep 실패 market=%s', market)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    return jsonify(ok=True, **st)


# ── 정산예정금액 탭 API ───────────────────────────────────────────────────────
#  스펙: docs/superpowers/specs/2026-08-06-settle-plan-tab-design.md
#  읽기 전용 집계 — 저장 행(MarketOrderLine.row)만 읽고 아무것도 쓰지 않는다.
#  금액은 margin.sell_source._settlement_for 단일 원천(마진계산기와 같은 숫자).

_SETTLE_PLAN_LOOKBACK_DAYS = 180   # 쿠팡 최대 2달 주기 + 여유


def _settle_plan_lines(markets=None):
    """MarketOrderLine → settle_plan 엔진 입력. 최근 180일 주문만."""
    from lemouton.markets.models_orders import MarketOrderLine
    lo = (_dt.datetime.now() - _dt.timedelta(days=_SETTLE_PLAN_LOOKBACK_DAYS)
          ).strftime("%Y-%m-%d")
    s = SessionLocal()
    try:
        q = s.query(MarketOrderLine).filter(MarketOrderLine.order_date >= lo)
        if markets:
            q = q.filter(MarketOrderLine.market.in_(list(markets)))
        return [{"row": dict(o.row or {}), "market": o.market,
                 "account": o.account or "", "status_at": o.status_at}
                for o in q.all()]
    finally:
        s.close()


@bp.route('/api/settle-plan')
def settle_plan_agg():
    """기간 버킷 집계. axis=payout(지급예정일·기본)|order(주문일), unit=day|week|month."""
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules
    axis = (request.args.get('axis') or 'payout').strip()
    unit = (request.args.get('unit') or 'week').strip()
    if unit not in ('day', 'week', 'month'):
        unit = 'week'
    mk = (request.args.get('market') or '').strip()
    lines = _settle_plan_lines([mk] if mk else None)
    if axis == 'order':
        out = SP.aggregate_by_order_date(
            lines, unit=unit,
            d_from=(request.args.get('from') or ''),
            d_to=(request.args.get('to') or ''))
    else:
        out = SP.aggregate_payout(lines, load_rules(), unit=unit,
                                  today=_dt.date.today())
    return jsonify(out)


@bp.route('/api/settle-plan/detail')
def settle_plan_detail():
    """주문건 드릴다운 — category(confirmed|unconfirmed|overdue|undated|assumed_paid|
    risk|paid)·market·account·bucket(+unit) 필터. 상품/배송비/총 3칸 + 배지.

    🔴 집계와 **같은 판정(SP.resolve)** 을 쓴다 — 예전엔 여기만 classify 로 걸러
       「KPI 5.5억 · 목록 0건」이 라이브에 나갔다(2026-08-06).
    """
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules
    from lemouton.margin.sell_source import _settlement_for
    category = (request.args.get('category') or '').strip()
    market = (request.args.get('market') or '').strip()
    account = (request.args.get('account') or '').strip()
    bucket = (request.args.get('bucket') or '').strip()
    unit = (request.args.get('unit') or 'week').strip()
    rules = load_rules()
    today = _dt.date.today()
    rows_out, truncated = [], False
    for ln in _settle_plan_lines([market] if market else None):
        r = SP.resolve(ln, rules, today=today)
        cat = r["category"]
        if cat == "excluded":
            continue
        if account and (ln.get("account") or "") != account:
            continue
        amount, src = _settlement_for(ln["row"])
        if not amount:
            continue
        evs = r["events"]
        if category in ("risk", "paid"):
            if cat != category:
                continue
        elif category:
            evs = [e for e in evs if e.get("bucket") == category]
            if not evs:
                continue
            if bucket and category in ("confirmed", "unconfirmed"):
                evs = [e for e in evs
                       if e["date"] and SP.bucket_key(e["date"], unit) == bucket]
                if not evs:
                    continue
        row = ln["row"]
        ship = _oe._to_int(row.get("배송비"), 0) or 0
        dates = [e["date"] for e in evs if e["date"]]
        srcs = {e["date_source"] for e in evs if e["date_source"]}
        # 쿠팡 분할지급이면 이 목록에 걸린 **조각 금액**만 보여준다(주문 전체가 아니라).
        #  그때 상품/배송비 쪼개기는 근거가 없으므로 비우고 총액만 적는다(날조 금지).
        part = sum(e["amount"] for e in evs) if evs else amount
        is_part = bool(evs) and part != amount
        rows_out.append({
            "주문번호": row.get("오픈마켓주문번호") or "",
            "주문일": str(row.get("주문일") or "")[:10],
            "상품명": row.get("상품명") or "",
            "옵션": row.get("옵션") or "",
            "수량": row.get("수량") or "",
            "주문상태": row.get("주문상태") or "",
            "account": ln.get("account") or "",
            "market": ln["market"],
            "category": cat,
            "bucket": (evs[0].get("bucket") if evs else cat),
            "상품정산예정": "" if is_part else amount - ship,
            "배송비정산예정": "" if is_part else ship,
            "총정산예정": part,
            "분할조각": is_part,
            "지급예정일": " · ".join(dates),
            "date_source": ("real" if srcs == {"real"}
                            else ("estimated" if srcs else "")),
            "_settle_source": src,
        })
        if len(rows_out) >= 2000:      # 화면 보호 상한 — 잘림을 숨기지 않는다
            truncated = True
            break
    return jsonify(rows=rows_out, truncated=truncated)


def _settle_plan_calibration(lines, rules):
    """규칙표 vs 실측 — 구매확정 행의 (실지급예정일 − 관측확정일) 중앙값을 마켓별로.

    재료 = `정산예정일`(마켓 실값)이 있고 상태가 구매확정 계열인 행. 관측확정일은
    status_at(우리가 그 상태를 처음 본 시각) 근사라 ±수일 오차가 있다 — 그래서 답이
    아니라 「규칙이 실측과 몇 일 어긋나는지」 참고 지표다. 재료 없으면 "측정불가"(날조 금지).
    """
    import statistics
    from lemouton.margin import settle_plan as SP
    gaps: dict = {}
    for ln in lines:
        row = ln["row"]
        st = str(row.get("주문상태") or "")
        if "구매확정" not in st and "구매결정" not in st:
            continue
        pdate = SP._norm_date(row.get("정산예정일"))
        at = ln.get("status_at")
        if not pdate or at is None:
            continue
        anchor = at.date() if isinstance(at, _dt.datetime) else at
        gaps.setdefault(ln["market"], []).append(
            (_dt.date.fromisoformat(pdate) - anchor).days)
    out = {}
    for mk, mrule in (rules.get("markets") or {}).items():
        vals = gaps.get(mk)
        if not vals:
            out[mk] = "측정불가"
            continue
        out[mk] = {"rule_days": mrule.get("cycle_days"),
                   "measured_days": int(statistics.median(vals)),
                   "n": len(vals)}
    return out


@bp.route('/api/settle-plan/rules', methods=['GET', 'POST'])
def settle_plan_rules():
    """규칙표 조회/수정 + 실측 보정 지표. POST 는 아는 키·범위만 받는다(부분 갱신)."""
    from lemouton.margin.settle_plan_rules import (DEFAULT_RULES, load_rules,
                                                  save_rules)
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        rules = load_rules()
        for mk, patch in (body.get("markets") or {}).items():
            base = rules["markets"].get(mk)
            if base is None or not isinstance(patch, dict):
                return jsonify(ok=False, error=f"모르는 마켓: {mk}"), 400
            for k, v in patch.items():
                if k not in DEFAULT_RULES["markets"][mk]:
                    return jsonify(ok=False, error=f"모르는 키: {mk}.{k}"), 400
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    return jsonify(ok=False, error=f"숫자가 아니에요: {mk}.{k}"), 400
                if k == "split_ratio":
                    if not (0.0 < fv <= 1.0):
                        return jsonify(ok=False,
                                       error=f"비율 범위(0~1) 밖: {mk}.{k}"), 400
                    base[k] = fv
                else:
                    if not (0 <= fv <= 120):
                        return jsonify(ok=False,
                                       error=f"일수 범위(0~120) 밖: {mk}.{k}"), 400
                    base[k] = int(fv)
        if "assume_paid_after_days" in body:
            try:
                v = int(body["assume_paid_after_days"])
            except (TypeError, ValueError):
                return jsonify(ok=False, error="숫자가 아니에요: assume_paid_after_days"), 400
            if not (1 <= v <= 365):
                return jsonify(ok=False,
                               error="일수 범위(1~365) 밖: assume_paid_after_days"), 400
            rules["assume_paid_after_days"] = v
        fa = body.get("fast_accounts")
        if fa is not None:
            if not isinstance(fa, dict) or not all(
                    isinstance(v, list) and all(isinstance(x, str) for x in v)
                    for v in fa.values()):
                return jsonify(ok=False, error="fast_accounts 형식 오류"), 400
            rules["fast_accounts"] = {k: v for k, v in fa.items()
                                      if k in rules["markets"]}
        save_rules(rules)
        return jsonify(ok=True, rules=rules)
    rules = load_rules()
    lines = _settle_plan_lines()
    return jsonify(rules=rules,
                   calibration=_settle_plan_calibration(lines, rules))


@bp.route('/invoice-sweep/run', methods=['POST'])
def orders_invoice_sweep_run():
    """옥션·G마켓·11번가 저장분의 **송장번호·택배사**를 마켓 실값으로 채운다(주문 재적재 없음).

    🔴 왜 필요한가(2026-07-30 실측) — 저장분 송장 보유율이 G마켓 34/190 · 옥션 25/47 ·
      11번가 109/743 로 저조했다. 같은 G마켓을 라이브로 20일 조회하면 23/23(100%) —
      마켓은 정상으로 주는데 **창고에 안 담긴 것**이다. 원인은 ESM 증분의 주문일 기준
      21일 창 이탈, 11번가 구매확정 시 invcNo 미제공.

    스케줄러가 3시간마다 자동으로 돌지만(MOUM_INVOICE_SWEEP_MINUTES), 이미 고착된
    과거분을 한 번 넓게 훑을 때 쓰는 수동 창구다.

    `?market=gmarket&from=YYYY-MM-DD&to=YYYY-MM-DD` — 기간 생략 시 기본(최근 120일).
    ⚠️ ESM 은 5초/1콜이라 기간이 넓으면 오래 걸린다(클플 100초 상한 주의 — 나눠 돌릴 것).
    """
    from flask import jsonify
    market = (request.args.get('market') or '').strip()
    if market not in ('gmarket', 'auction', 'eleven11'):
        return jsonify(ok=False,
                       error='옥션·G마켓·11번가 전용이에요(나머지는 주문조회가 송장을 늘 줍니다).'), 400
    since, until = _parse_range(request.args)

    # 🔴 ESM 은 **기간과 무관하게** 최소 비용이 크다 — 주문조회 5초/1콜 × 주문상태 5개 ×
    #   계정 3개 = 최소 75초. 7일 창도 CF 100초를 넘겨 524 가 났다(2026-07-30 실측).
    #   → 요청 스레드에서 끝까지 기다리지 않고 **백그라운드로 돌리고 즉시 응답**한다.
    #   결과는 서버 로그(order_invoice_sweep_manual)와 화면 재조회로 확인한다.
    #   ★기다리게 만들면 524 뒤에도 작업은 계속 도는데 사용자는 실패로 오해한다.
    import logging
    import threading
    log = logging.getLogger(__name__)

    def _run():
        from lemouton.markets.order_ingest import refresh_invoices
        try:
            st = refresh_invoices(market, since=since, until=until)
            log.info('order_invoice_sweep_manual[%s]: 계정 %d · 마켓송장 %d건 → 갱신 %d · 실패 %d',
                     market, st['accounts'], st['fetched'], st['updated'], len(st['errors']))
            for e in st['errors'][:3]:
                log.warning('order_invoice_sweep_manual[%s] %s', market, e)
        except Exception:   # noqa: BLE001 — 사유를 숨기지 않는다(로그로 남긴다)
            log.exception('order_invoice_sweep_manual 실패 market=%s', market)

    threading.Thread(target=_run, name=f'invoice-sweep-{market}', daemon=True).start()
    return jsonify(ok=True, started=True, market=market,
                   note='백그라운드로 시작했어요(ESM 은 5초/1콜이라 몇 분 걸립니다). '
                        '끝나면 주문내역을 다시 불러오면 채워진 송장이 보입니다.')


@bp.route('/diag/esm-settlement')
def orders_diag_esm_settlement():
    """[읽기 전용] 옥션·G마켓 판매대금 정산조회 원본 — 어떤 조회기준일에 정산액이 잡히나.

    왜 필요한가 — 정산은 **구매확정 뒤에** 확정되는데, 조회기준일(SrchType)을 잘못 잡으면
    이미 정산된 주문도 빈손으로 돌아온다. 그때 우리 화면엔 추정치가 남고, 사장님은
    「정상 정산된 건인데 왜 추정이냐」를 보게 된다. 추측으로 기준일을 고르지 않기 위한 창구다.

    지도(esm 정산조회) 확정 값:
      D1 입금확인일 · D2 배송일 · D3 배송완료일 · D4 구매결정일 · D5 정산예정일
      D6 송금일 · D7 환불일 · D8 입금확인일+환불일 · D9 배송완료일+환불일 · D10 예치금송금일

    `?market=gmarket&from=YYYY-MM-DD&to=YYYY-MM-DD&srch=D1,D4&orders=번호,번호`
      · srch 를 콤마로 여러 개 주면 기준일별로 나란히 비교한다(무엇이 정답인지 눈으로).
      · orders 를 주면 그 주문번호만 추린다(응답이 작아지고 개인정보도 안 담긴다).
    응답은 금액·수량뿐 — 고객정보는 담지 않는다.
    """
    from flask import jsonify
    market = (request.args.get('market') or 'gmarket').strip()
    if market not in ('gmarket', 'auction'):
        return jsonify(ok=False, error='옥션·G마켓 전용이에요.'), 400
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    srchs = [s.strip().upper() for s in (request.args.get('srch') or 'D1').split(',')
             if s.strip()]
    want = {o.strip() for o in (request.args.get('orders') or '').split(',') if o.strip()}
    alias = (request.args.get('alias') or '').strip()

    from shared.platforms.esm.settlements import settle_detail_map
    out, errors = {}, {}
    for srch in srchs:
        try:
            cli = _client_for(market, alias)
            smap = settle_detail_map(market, since, until, client=cli, srch_type=srch)
        except Exception as e:   # noqa: BLE001 — 기준일 하나가 막혀도 나머지는 보여준다
            errors[srch] = f"{type(e).__name__}: {str(e)[:200]}"
            continue
        picked = {k: v for k, v in smap.items() if not want or k in want}
        out[srch] = {
            "총건수": len(smap),
            "정산액_있는건수": sum(1 for v in smap.values()
                                   if v.get("정산예정금액") is not None),
            "조회한주문": picked if want else dict(list(picked.items())[:20]),
        }
    return jsonify(ok=True, market=market, alias=alias or "(대표)",
                   기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   결과=out, 실패=errors)


@bp.route('/diag/ss-settle')
def orders_diag_ss_settle():
    """[읽기 전용] 스마트스토어 정산조회 raw — 한 주문의 settleExpectAmount 행 전부.

    왜 필요한가 (2026-07-25 샵마인 대조 24건) — 프로그램은 네이버 settleExpectAmount 를
    productOrderId 별로 **전 행(상품/배송비/기타비용/지원금) 합산**한다. 샵마인 정산예상과
    갈릴 때, 어느 행이 합쳐져 갈리는지 눈으로 봐야 '프로그램이 틀렸나 샵마인이 다른가'를
    가른다(섣불리 프로그램을 고치면 네이버 실정산에서 멀어질 위험).

    `?from=YYYY-MM-DD&to=YYYY-MM-DD&orders=orderId,orderId&alias=`
      · 창은 **정산예정일** 기준(period_type=SETTLE_CASEBYCASE_PAY_DATE·인라인과 동일).
      · orders 로 orderId 를 주면 그 주문만. 응답엔 금액·유형뿐(고객정보 없음).
    """
    from flask import jsonify
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    want = {o.strip() for o in (request.args.get('orders') or '').split(',') if o.strip()}
    alias = (request.args.get('alias') or '').strip()
    import datetime as _dt
    from shared.platforms.smartstore.settlements import iter_settle_by_case
    cli = _client_for_diag('smartstore', alias)
    by_order: dict = {}
    day = since
    while day <= until:
        try:
            for el in iter_settle_by_case(
                    search_date=day.strftime('%Y-%m-%d'),
                    period_type='SETTLE_CASEBYCASE_PAY_DATE', client=cli):
                oid = str(el.get('orderId') or '')
                if want and oid not in want:
                    continue
                by_order.setdefault(oid, {'rows': [], '합계': 0})
                amt = el.get('settleExpectAmount')
                by_order[oid]['rows'].append({
                    'productOrderId': el.get('productOrderId'),
                    'productOrderType': el.get('productOrderType'),
                    'settleExpectAmount': amt,
                    'totalPayCommissionAmount': el.get('totalPayCommissionAmount'),
                    'benefitSettleAmount': el.get('benefitSettleAmount'),
                    'settleAmount': el.get('settleAmount'),
                    'searchDate': day.strftime('%Y-%m-%d'),
                })
                if amt is not None:
                    by_order[oid]['합계'] += amt
        except Exception as e:   # noqa: BLE001 — 하루가 막혀도 나머지 진행
            by_order.setdefault('_errors', []).append(
                f"{day:%Y-%m-%d}: {type(e).__name__}: {str(e)[:150]}")
        day += _dt.timedelta(days=1)
    return jsonify(ok=True, 기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   alias=alias or "(대표)", 주문수=len([k for k in by_order if not k.startswith('_')]),
                   주문별=by_order)


@bp.route('/diag/lotteon-itmd')
def orders_diag_lotteon_itmd():
    """[읽기 전용] 롯데온 SettleItmdSales raw — 한 주문의 정산 상세 행 전부.

    왜 필요한가 (2026-07-25 다품 1건 실측) — itmd_map 은 pymtAmt 를 **odNo(주문) 단위**로
    합산하는데, order_export 는 그 주문 총액을 **각 라인(odSeq)** 에 통째로 대입한다.
    다품(2벌) 주문은 라인마다 총액이 들어가 합계가 2배가 된다. SettleItmdSales 가
    odSeq(벌) 단위 pymtAmt 를 주는지 raw 로 봐야 (odNo,odSeq) 배분 수정이 안전한지 판정한다.

    `?from=YYYY-MM-DD&to=YYYY-MM-DD&orders=odNo,odNo&alias=`  응답엔 금액·식별자뿐.
    """
    from flask import jsonify
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    want = {o.strip() for o in (request.args.get('orders') or '').split(',') if o.strip()}
    alias = (request.args.get('alias') or '').strip()
    from shared.platforms.lotteon import settlement as _lo
    cli = _client_for_diag('lotteon', alias)
    cfg = getattr(cli, "_cfg", None) or _lo._CFG
    rows = _lo._fetch_all_itmd_rows(cfg, since, until, client=cli)
    by_order: dict = {}
    for r in rows:
        od = str(r.get('odNo') or '')
        if want and od not in want:
            continue
        by_order.setdefault(od, {'rows': [], 'pymtAmt합': 0})
        amt = _lo._num(r.get('pymtAmt'))
        by_order[od]['rows'].append({
            'odSeq': r.get('odSeq'), 'procSeq': r.get('procSeq'),
            'spdNo': r.get('spdNo'), 'pymtAmt': amt, 'pcsCmsn': _lo._num(r.get('pcsCmsn')),
        })
        by_order[od]['pymtAmt합'] += amt
    return jsonify(ok=True, 기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   alias=alias or "(대표)", 주문수=len(by_order), 주문별=by_order)


@bp.route('/diag/store-span')
def orders_diag_store_span():
    """[읽기 전용] 저장분(order_store)의 마켓별 최초·최신 주문일 + 건수.

    라이브 프로브(‘최대 과거 조회’)와 비교해 **끊김의 원인**을 가른다:
      · 저장분엔 옛 주문이 있는데 라이브가 0 → 그 마켓 API의 **보존한도**(과거 회수 불가)
      · 저장분도 그때부터 없음 → 단지 **우리 판매 시작일**(API 한도 아님)
    """
    from flask import jsonify
    from sqlalchemy import func
    from lemouton.markets.models_orders import MarketOrderLine
    out = {}
    try:
        with SessionLocal() as s:
            rows = (s.query(MarketOrderLine.market,
                            func.min(func.substr(MarketOrderLine.order_date, 1, 10)),
                            func.max(func.substr(MarketOrderLine.order_date, 1, 10)),
                            func.count())
                    .filter(MarketOrderLine.order_date.isnot(None))
                    .filter(MarketOrderLine.order_date != "")
                    .group_by(MarketOrderLine.market)
                    .all())
        for mk, mn, mx, cnt in rows:
            out[mk] = {"최초": mn, "최신": mx, "건수": cnt}
        return jsonify(ok=True, markets=out)
    except Exception as e:   # noqa: BLE001
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 200


@bp.route('/diag/lookback-probe')
def orders_diag_lookback_probe():
    """[읽기 전용] 마켓 「최대 과거 조회」 실측 — 지정 창을 라이브로 물어 주문 수만 반환(저장 안 함).

    각 마켓 API가 얼마나 오래된 과거까지 데이터를 주는지는 문서에 없어(마켓 정책) 실측한다.
    오래된 창일수록 주문수가 0 이거나 에러(기간 초과·거부)가 나면 그 이전은 조회 불가로 본다.
    `?market=coupang&from=YYYY-MM-DD&to=YYYY-MM-DD` (창은 7일 이내 권장 — 마켓 창 상한 안).
    """
    from flask import jsonify
    market = (request.args.get('market') or '').strip()
    since, until = _parse_range(request.args)
    if not market or not since or not until:
        return jsonify(ok=False, error='market·from·to(YYYY-MM-DD) 필요'), 400
    # ★백필(날짜 기준) 경로로 조회한다 — order_rows(증분)는 롯데온·11번가처럼 '현재 상태'
    #   기준 API라 옛 날짜를 넣어도 현재 주문을 돌려줘(2026-07-25 실측: 롯데온 2년·3년 전이
    #   똑같이 1,371건) 과거 한도 측정에 못 쓴다. _fetch_inner(backfill=True)는 SettleProduct
    #   (롯데온)·주문일 기준(쿠팡·스스·ESM)이라 그 창의 실제 과거 주문을 준다. 대표계정 1개만.
    #   ⚠️ 11번가는 백필 페처가 없어 이 경로도 증분(상태 기준)으로 떨어짐 → 과거 측정 불가.
    alias = (request.args.get('alias') or '').strip()
    prefix = None
    if alias:
        try:
            import lemouton.markets.order_export as _oe2
            for pfx, name in (_oe2._active_accounts(market) or []):
                b = str(name or '').split('(')[0].strip()
                if b == alias.split('(')[0].strip():
                    prefix = pfx
                    break
        except Exception:   # noqa: BLE001
            prefix = None
    try:
        rows = _oi._fetch_inner(market, since, until, include_settlement=False,
                                backfill=True, prefix=prefix)
        return jsonify(ok=True, market=market, path='backfill',
                       기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                       주문수=len(rows))
    except Exception as e:   # noqa: BLE001 — 에러도 실측 결과(조회 한도 신호)라 200 으로 담는다
        return jsonify(ok=True, market=market,
                       기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                       주문수=None, error=f"{type(e).__name__}: {str(e)[:200]}"), 200


@bp.route('/diag/eleven11-couriers')
def orders_diag_eleven11_couriers():
    """11번가 택배사 코드(dlvEtprsCd) 확인 — 읽기 전용.

    11번가 발송처리용 택배사 코드는 공개 출처마다 값이 달라(로젠: 00002 vs 05) 추측할 수 없다.
    정답은 이미 발송한 주문이 갖고 있다 — 배송중·배송완료 목록이 되돌려주는 dlvEtprsCd.

    `?invoice=<송장번호>` 를 주면 그 건의 코드만 곧장 찾아준다(셀러오피스 화면엔 택배사와
    송장번호가 나란히 보이므로, 송장번호 하나면 이름↔코드가 확정된다).

    등록된 11번가 계정을 모두 훑고 어느 계정에서 나온 코드인지 함께 알린다.
    응답에는 코드·건수·발송일(날짜)만 담는다(주문번호·고객정보 미포함).
    """
    from flask import jsonify
    from shared.platforms.eleven11 import orders as eo

    accounts = _oe._active_accounts('eleven11') or [(None, '대표 계정')]
    days = max(1, min(30, int(request.args.get('days', 14))))
    want = str(request.args.get('invoice') or '').strip()
    until = _dt.datetime.now()
    since = until - _dt.timedelta(days=days)

    per_account, merged, dates, match, reached = [], {}, {}, None, 0
    for _prefix, alias in accounts:
        cli = _client_for('eleven11', alias or '')
        if cli is None:
            continue
        reached += 1
        counts: dict = {}
        for src in (eo.iter_shipping, eo.iter_delivered):
            for od in src(since, until, client=cli):
                code = str(od.get('dlvEtprsCd') or '').strip()
                if want and str(od.get('invcNo') or '').strip() == want and code:
                    match = {'alias': alias, 'code': code}
                if not code:
                    continue
                counts[code] = counts.get(code, 0) + 1
                merged[code] = merged.get(code, 0) + 1
                # 발송일(날짜만) — 코드가 여러 개일 때 사람이 어느 택배사였는지 대조하는 용도.
                day = str(od.get('sndEndDt') or od.get('dlvEndDt') or '')[:10]
                if day and day not in dates.setdefault(code, []):
                    dates[code].append(day)
        per_account.append({'alias': alias, 'codes': counts})

    if not reached:
        return jsonify(ok=False, error='11번가 키가 등록돼 있지 않습니다'), 400

    if want:
        note = ('송장번호 {} 의 택배사 코드를 찾았습니다'.format(want) if match
                else '최근 {}일 발송 내역에서 그 송장번호를 찾지 못했습니다'.format(days))
    elif not merged:
        note = '최근 {}일 발송 이력이 없어 코드를 확인하지 못했습니다'.format(days)
    else:
        note = '코드가 여러 개면 ?invoice=<송장번호> 로 한 건을 콕 집어 확인하세요'

    return jsonify(ok=True, days=days, codes=merged,
                   dates={k: sorted(v) for k, v in dates.items()},
                   accounts=per_account, match=match, note=note)


@bp.route('/diag/invoice-ledger')
def orders_diag_invoice_ledger():
    """송장 원장 상태 — 읽기 전용(저장이 실제로 되는지 확인용).

    마켓별 저장 건수 + 총계. `?order_no=<주문번호>` 로 그 주문의 저장된 송장 조회.
    """
    from flask import jsonify
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import InvoiceLedger

    # 셀프테스트: 합성 행으로 remember→읽기→정리. 저장 경로가 실제로 도는지·예외를 표면화.
    if request.args.get('selftest'):
        from lemouton.markets import invoice_ledger as _led
        probe = [{"판매처": "__selftest__", "오픈마켓주문번호": "__t__",
                  "송장입력": "SELFTEST123", "주문상태": "배송완료"}]
        try:
            n = _led.remember(probe)
            s2 = SessionLocal()
            try:
                row = (s2.query(InvoiceLedger)
                       .filter(InvoiceLedger.order_no == "__t__").first())
                read_back = row.invoice_no if row else None
                if row is not None:
                    s2.delete(row); s2.commit()      # 정리(원장 오염 방지)
            finally:
                s2.close()
            return jsonify(ok=True, remembered=n, read_back=read_back)
        except Exception as e:   # noqa: BLE001 — 예외 문자열 그대로 보고(진단 목적)
            return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:400]}")

    want = str(request.args.get('order_no') or '').strip()
    s = SessionLocal()
    try:
        if want:
            row = (s.query(InvoiceLedger)
                   .filter(InvoiceLedger.order_no == want).first())
            if row is None:
                return jsonify(ok=True, found=False, order_no=want,
                               note='원장에 저장된 적 없는 주문입니다')
            return jsonify(ok=True, found=True, order_no=want,
                           market=row.market, invoice_no=row.invoice_no,
                           courier=row.courier)
        counts: dict = {}
        for row in s.query(InvoiceLedger).all():
            counts[row.market] = counts.get(row.market, 0) + 1
        return jsonify(ok=True, counts=counts, total=sum(counts.values()),
                       note='배송중·배송완료 때 본 송장번호가 여기 쌓입니다')
    finally:
        s.close()


@bp.route('/invoice/upload', methods=['POST'])
def orders_invoice_upload():
    """택배사 엑셀 업로드 → 「오픈마켓주문번호」가 맞는 **주문을 불러와** 돌려준다(전송 아님).

    ★ 2026-07-30 사장님 확정 흐름: 「엑셀 올린다 → 주문번호 맞는 주문을 불러온다 →
      송장·상태로 분류한다 → 미입력 건에 넣어 보낸다」. 그래서 화면이 미리 주문을
      불러 둘 필요가 없다 — 대조 모수는 **적재분 전체**이고, 여기서 주문번호로 찾는다
      (기간·마켓을 사용자에게 안 물어도 되고, 좁게 잡아 놓쳐 「확인불가」가 부풀 일이 없다).
    """
    from flask import jsonify
    from lemouton.markets import order_store
    from lemouton.markets.invoice_excel import (parse_invoice_excel, match_invoices,
                                                InvoiceExcelError)

    f = request.files.get('file')
    if f is None:
        return jsonify(ok=False, error="엑셀 파일이 없어요."), 400

    try:
        excel_rows = parse_invoice_excel(f.read())
    except InvoiceExcelError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001 — 손상 파일 등
        return jsonify(ok=False, error=f"엑셀을 읽지 못했어요: {type(e).__name__}"), 400

    want = [str(r.get('order_no') or '').strip() for r in excel_rows]
    want = sorted({o for o in want if o})
    # 주문번호로 인덱스 조회 — 전체를 읽지 않는다.
    #  전송 식별자(_send_ids)는 적재할 때 행 안에 함께 저장돼 그대로 딸려온다.
    rows = order_store.load(order_nos=want, include_claims=False) if want else []
    res = match_invoices(excel_rows,
                         [str(r.get('오픈마켓주문번호') or '') for r in rows])
    # 못 찾은 번호는 「왜 못 찾았나 + 가장 비슷한 우리 주문」까지 붙여 돌려준다 —
    #  번호만 나열하면 사장님이 다음에 뭘 해야 할지 모른다(2026-07-30 확정).
    near = _nearest_for(res.unmatched) if res.unmatched else {}
    return jsonify(ok=True, matched=res.matched, unmatched=res.unmatched,
                   unmatched_near=near,
                   conflicts=res.conflicts, read=len(excel_rows), rows=rows)


def _nearest_for(unmatched, *, days: int = 120) -> dict:
    """못 찾은 번호마다 가장 비슷한 우리 주문을 찾는다. 실패해도 업로드는 살린다."""
    import datetime as _dt

    from lemouton.markets.invoice_excel import nearest_orders
    try:
        from lemouton.markets.models_orders import MarketOrderLine
        from shared.db import SessionLocal
        since = (_dt.date.today() - _dt.timedelta(days=days)).strftime('%Y-%m-%d')
        s = SessionLocal()
        try:
            # 번호·판매처·주문일 세 칸만 읽는다(행 전체를 읽으면 느리다).
            q = (s.query(MarketOrderLine.order_no, MarketOrderLine.market,
                         MarketOrderLine.order_date)
                 .filter(MarketOrderLine.order_date >= since))
            cands = q.all()
        finally:
            s.close()
        return nearest_orders(unmatched, cands)
    except Exception:   # noqa: BLE001 — 곁다리 기능이 업로드를 막으면 안 된다
        import logging
        logging.getLogger(__name__).exception('비슷한 주문 찾기 실패')
        return {}


@bp.route('/invoice/send', methods=['POST'])
def orders_invoice_send():
    """선택한 주문의 운송장번호를 마켓으로 전송. 기본은 드라이런(미전송)."""
    from flask import jsonify
    from lemouton.markets.invoice_send import send_invoice

    body = request.get_json(silent=True) or {}
    rows = body.get('rows') or []
    if not rows:
        return jsonify(ok=False, error="전송할 주문이 없어요."), 400

    # 안전 게이트: 요청 live=true + 서버 전역 스위치 ON 일 때만 실제 전송.
    live = bool(body.get('live')) and _live_enabled()

    results, sent, failed = [], 0, 0
    for r in rows:
        market = str(r.get('market') or '')
        try:
            cli = _client_for(market, r.get('alias') or '') if live else None
        except Exception:   # noqa: BLE001 — 클라이언트 생성 실패도 전송 실패로 표면화
            cli = None
        res = send_invoice(market=market, order_no=r.get('order_no'),
                           courier_name=r.get('courier') or '',
                           invoice_no=r.get('invoice_no'),
                           send_ids=r.get('send_ids'), client=cli, live=live,
                           order_status=r.get('status'))
        if res.success:
            sent += 1
        else:
            failed += 1

        # 실전송 성공 시 마켓에 실제 등록된 송장번호를 되읽어 화면에 표시(입력값 아님).
        #   입력값과 다르면 프런트가 빨간 경고로 드러낸다. 못 읽으면 None(확인 대기).
        market_invoice_no = None
        if res.success and not res.dry_run:
            from lemouton.markets.invoice_send import read_registered_invoice
            market_invoice_no = read_registered_invoice(
                market=market, order_no=r.get('order_no'),
                send_ids=r.get('send_ids'), client=cli)
            # ★우리가 고른 택배사를 원장에 남긴다(사장님 요청 2026-07-25).
            #   마켓 주문조회가 택배사를 주는 곳은 ESM(TakbaeName)뿐이라, 쿠팡·롯데온·스스·
            #   11번가는 조회로는 영영 못 채운다. 보낼 때 고른 이 값이 가장 정확한 원천이고,
            #   다음 조회부터 invoice_ledger.fill_missing 이 화면에 채워 준다.
            #   ★번호는 마켓 되읽기값 우선(입력 오타가 원장에 굳지 않게).
            try:
                from lemouton.markets import invoice_ledger as _led
                _led.remember_sent(
                    _oe.market_label(market), r.get('order_no'),
                    market_invoice_no or r.get('invoice_no'), r.get('courier') or '')
            except Exception:   # noqa: BLE001 — 원장은 보조기록, 전송 결과를 막지 않는다
                import logging
                logging.getLogger(__name__).exception('invoice ledger remember_sent failed')

        results.append({"market": res.market, "order_no": res.order_no,
                        "success": res.success, "dry_run": res.dry_run,
                        "error": res.error,
                        "market_invoice_no": market_invoice_no})

    return jsonify(ok=True, live=live, sent=sent, failed=failed, results=results)


# ──────────────────────────────────────────────────────────────
#  자동전환 — 「결제완료 → 배송준비중」 마켓·계정별 ON/OFF + 즉시 전환(드라이런 기본)
#   설정=팀 공유 DB(AutoConfirmSetting, 계정 leaf 단위). 실전환은 LIVE 스위치가 또 잠근다.
# ──────────────────────────────────────────────────────────────

@bp.route('/auto-confirm/config')
def auto_confirm_config():
    """자동전환 설정 트리(마켓·계정별 ON/OFF + 이력 + LIVE 스위치)."""
    from lemouton.orders import auto_confirm as _ac
    s = SessionLocal()
    try:
        out = _ac.list_settings(s)
        try:
            from scheduler.main import auto_confirm_job_info
            out["scheduler"] = auto_confirm_job_info()
        except Exception:   # noqa: BLE001 — 스케줄러 정보 실패는 설정 조회를 막지 않음
            out["scheduler"] = {"scheduler_running": False, "tick_registered": False}
        return jsonify(ok=True, **out)
    except Exception as e:   # noqa: BLE001 — 설정 조회 실패도 화면을 막지 않게 사유 표면화
        import logging
        logging.getLogger(__name__).exception("auto-confirm config failed")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 400
    finally:
        s.close()


@bp.route('/auto-confirm/set', methods=['POST'])
def auto_confirm_set():
    """자동전환 스위치 저장. body: {scope:'all'|'market'|'account', market?, alias?, enabled}."""
    from lemouton.orders import auto_confirm as _ac
    body = request.get_json(silent=True) or {}
    scope = str(body.get('scope') or '')
    enabled = bool(body.get('enabled'))
    s = SessionLocal()
    try:
        if scope == 'all':
            n = _ac.set_all(s, enabled)
        elif scope == 'market':
            n = _ac.set_market(s, str(body.get('market') or ''), enabled)
        elif scope == 'account':
            _ac.set_account(s, str(body.get('market') or ''),
                            str(body.get('alias') or ''), enabled)
            n = 1
        else:
            return jsonify(ok=False, error='scope 는 all·market·account 중 하나여야 해요.'), 400
        return jsonify(ok=True, changed=n, **_ac.list_settings(s))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    finally:
        s.close()


@bp.route('/auto-confirm/diag-order')
def auto_confirm_diag_order():
    """[읽기전용 진단] 스스 주문 상세 원본 — 발주확인 여부 필드 확인(placeOrderStatus 등).

    상태변경 아님(조회만). ?market=smartstore&order_no=..&alias=.. .
    개인정보는 제외하고 상태·발주·배송 관련 필드만 추려 반환.
    """
    from lemouton.orders import auto_confirm as _ac
    market = (request.args.get('market') or 'smartstore').strip()
    order_no = (request.args.get('order_no') or '').strip()
    alias = (request.args.get('alias') or '').strip()
    if market != 'smartstore':
        return jsonify(ok=False, error='이 진단은 스마트스토어 전용이에요.'), 400
    if not order_no:
        return jsonify(ok=False, error='order_no 가 필요해요.'), 400
    try:
        cli = _ac._client_for(market, alias)
        from shared.platforms.smartstore import orders as ss
        resp = ss.fetch_order_detail([order_no], client=cli)
    except Exception as e:   # noqa: BLE001
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 400
    data = (resp or {}).get('data') or []
    if not data:
        return jsonify(ok=True, found=False, order_no=order_no)
    # 중첩 dict 를 훑어 상태·발주·배송·금액 관련 필드만 수집(개인정보 배제)
    #  금액 키를 넣은 이유(2026-07-24): 스마트스토어 저장분에 상품명이 「(개인통관 필수)」
    #  이고 단가·실결제·정산이 0 인 행이 123건 있다. 그 0 이 **마켓이 준 실값인지**
    #  우리가 못 받은 것인지 눈으로 확인해야 한다(추측으로 채우면 날조).
    picked = {}
    KEYS = ('status', 'place', 'confirm', 'deliver', 'dispatch', 'date',
            'amount', 'price', 'pay', 'quantity', 'unit', 'discount', 'commission')
    def walk(o, prefix=''):
        if isinstance(o, dict):
            for k, v in o.items():
                kl = str(k).lower()
                if isinstance(v, (dict, list)):
                    walk(v, prefix + k + '.')
                elif any(t in kl for t in KEYS):
                    picked[prefix + k] = v
        elif isinstance(o, list):
            for it in o[:3]:
                walk(it, prefix)
    walk(data[0])
    return jsonify(ok=True, found=True, order_no=order_no, fields=picked)


@bp.route('/auto-confirm/auto', methods=['POST'])
def auto_confirm_auto():
    """자동 실행(스케줄러) 설정 저장 — body {enabled?, interval_minutes?}.

    enabled=true 로 켜면 스케줄러가 무인 실전환을 시작한다(화면 확인창이 그 arming).
    """
    from lemouton.orders import auto_confirm as _ac
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        _ac.set_config(s,
                       enabled=body.get('enabled'),
                       interval_minutes=body.get('interval_minutes'))
        return jsonify(ok=True, **_ac.list_settings(s))
    finally:
        s.close()


@bp.route('/auto-confirm/run', methods=['POST'])
def auto_confirm_run():
    """자동전환 실행. 기본 드라이런(넘어갈 건수만). body live=true + 서버 스위치 ON 이면 실전환.

    실전환 게이트가 켜져도, 아직 실전환이 배선되지 않은 마켓은 거짓 성공 대신 명시 실패로
    표시된다(CLAUDE.md 🔒 — 확인 못한 걸 했다고 하지 않는다).
    """
    from lemouton.orders import auto_confirm as _ac
    body = request.get_json(silent=True) or {}
    live = bool(body.get('live'))
    try:
        limit = int(body.get('limit')) if body.get('limit') is not None else None
    except (TypeError, ValueError):
        limit = None
    order_nos = body.get('order_nos') or None   # 승인한 주문번호만 콕 집어 전환
    if order_nos is not None and not isinstance(order_nos, list):
        order_nos = None
    s = SessionLocal()
    try:
        return jsonify(**_ac.run(s, live=live, limit=limit, order_nos=order_nos))
    except Exception as e:   # noqa: BLE001 — 실행 실패 사유 표면화(조용한 실패 금지)
        import logging
        logging.getLogger(__name__).exception("auto-confirm run failed")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 400
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────
#  배송검사 (inspect) — 더망고 업로드 · 중복송장 · 배송흐름 · 배송방식
#   업로드=더망고 엑셀(HTML위장 .xls) → MangoOrder DB 누적. 검사·배송방식은 엑셀 기반.
# ──────────────────────────────────────────────────────────────

def _mango_to_dict(o):
    return {
        'uid': o.mango_uid, 'ord': o.market_order_no or '',  # 매칭키=오픈마켓주문번호
        'market': o.market_name, 'recipient': o.recipient,
        'product': o.product_name, 'option': o.option1, 'invoice': o.invoice_no or '',
        'mango_status': o.mango_status, 'market_status': o.market_status,
        'method': o.delivery_method, 'method_source': o.delivery_method_source,
        # v2 마켓 실데이터
        'market_api_status': o.market_api_status, 'market_api_status_raw': o.market_api_status_raw or '',
        'market_api_invoice': o.market_api_invoice or '',
        'shipped_at': o.market_shipped_at or '',      # 마켓 발송처리일(경과시간 계산용)
        'why_error': o.market_check_error,
    }


@bp.route('/inspect/data')
def inspect_data():
    """배송검사 목록 + 검사요약(v2 마켓 실데이터) + 구분자 매핑 (JSON)."""
    s = SessionLocal()
    try:
        _dsvc.seed_default_status_map(s)   # 최초 진입 시 기본 매핑 보장
        orders = (s.query(_dsvc.MangoOrder)
                  .order_by(_dsvc.MangoOrder.last_uploaded_at.desc()).limit(1000).all())
        # ★분류는 마켓 API 실데이터 기준(더망고 구분자 신빙성 없음). 백엔드는 취소(API상태)·
        #  확인불가(매칭실패)만 판정하고, 발송대상/배송흐름정체/이미발송은 프론트가 API 송장·
        #  상태로 파생한다(단일 진실 = market_api_invoice + market_api_status).
        cancel_uids = {o.mango_uid for o in orders if _dsvc.is_cancel_return(o)}
        unk_uids = {o.mango_uid for o in orders if o.market_check_error} - cancel_uids
        rows = []
        ctype_cnt = {}
        for o in orders:
            d = _mango_to_dict(o)
            is_c = o.mango_uid in cancel_uids
            d['cancel'] = is_c
            d['ctype'] = _dsvc.cancel_type(o) if is_c else None   # 취소/반품/교환/그외
            if is_c:
                ctype_cnt[d['ctype']] = ctype_cnt.get(d['ctype'], 0) + 1
            d['unknown'] = o.mango_uid in unk_uids
            rows.append(d)
        status_map = [
            {'value': m.status_value, 'meaning': m.meaning,
             'default_method': m.default_method, 'flow': bool(m.is_flow_check_target)}
            for m in sorted(_dsvc.get_status_map(s).values(), key=lambda x: x.sort_order)
        ]
        return jsonify(ok=True, orders=rows, status_map=status_map,
                       summary={'unknown': len(unk_uids), 'cancel': len(cancel_uids),
                                'cancel_types': ctype_cnt, 'total': len(orders)})
    finally:
        s.close()


@bp.route('/inspect/upload', methods=['POST'])
def inspect_upload():
    """더망고 엑셀 업로드 → 파싱 → upsert. bulk_method=까대기/직배/자동판정."""
    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='파일이 없습니다.'), 400
    bulk = request.form.get('bulk_method') or None
    if bulk == '자동판정':
        bulk = None
    try:
        rows = parse_mango_xls(f.read())
    except MangoParseError as e:
        return jsonify(ok=False, error=str(e)), 422
    except Exception as e:   # noqa: BLE001 — 손상 파일 등 사유 표면화(조용한 성공 금지)
        return jsonify(ok=False, error=f'엑셀을 읽지 못했어요: {type(e).__name__}'), 400
    s = SessionLocal()
    try:
        _dsvc.seed_default_status_map(s)
        # 실제 업로드 = 최신 스냅샷(이번 목록에 없는 옛 더망고 주문 삭제 → 누적 방지)
        res = _dsvc.upsert_orders(s, rows, bulk_method=bulk, replace_stale=True)
        # 업로드 즉시 마켓 API 조회(오픈마켓주문번호 매칭 → 실상태·실송장 캐시)
        from lemouton.delivery import market_enrich as _me
        uids = [r["mango_uid"] for r in rows]
        warn = []
        try:
            enr = _me.enrich_from_market_api(s, uids, warnings=warn)
        except Exception as e:   # noqa: BLE001 — enrich 실패해도 업로드는 성공 처리
            enr = {"checked": 0}
            warn.append(f"마켓 조회 실패: {type(e).__name__}")
        return jsonify(ok=True, inserted=res['inserted'], updated=res['updated'],
                       parsed=len(rows), market_checked=enr.get('checked', 0), warnings=warn)
    finally:
        s.close()


@bp.route('/shopmine-recon/run', methods=['POST'])
def shopmine_recon_run():
    """샵마인 정답지 엑셀 업로드 → 전수 대조 → 결과 저장(지난번 대비 추적).

    기간 = 파일이 결정(파일 주문일 min~max 로 우리 적재분을 로드). 결과는
    shopmine_recon_runs 에 저장해 다음 실행 때 「지난번 대비」로 보여준다.
    """
    from lemouton.markets import shopmine_recon as _smr
    from lemouton.markets.models_shopmine import ShopmineReconRun

    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='파일이 없습니다.'), 400
    raw = f.read()
    s = SessionLocal()
    try:
        try:
            res = _smr.run_against_store(raw, session=s)
        except ValueError as e:
            return jsonify(ok=False, error=str(e)), 422
        except Exception as e:   # noqa: BLE001 — 손상 파일 등 사유 표면화(조용한 성공 금지)
            return jsonify(ok=False, error=f'대조 실패: {type(e).__name__}: {e}'), 400
        detail = {k: res[k] for k in ('missing', 'mismatch', 'undecided')}
        summary = {k: v for k, v in res.items() if k not in detail}
        prev = (s.query(ShopmineReconRun)
                .order_by(ShopmineReconRun.id.desc()).first())
        run = ShopmineReconRun(filename=f.filename or '',
                               period_from=res['period'][0],
                               period_to=res['period'][1],
                               summary=summary, result=detail)
        s.add(run)
        # 저장 상한 30회 — Supabase 무료 티어(500MB) 보호. 오래된 실행부터 삭제.
        olds = (s.query(ShopmineReconRun)
                .order_by(ShopmineReconRun.id.desc()).offset(29).all())
        for o in olds:
            s.delete(o)
        s.commit()
        return jsonify(ok=True, ran_at=run.ran_at.isoformat(),
                       summary=summary, detail=detail,
                       prev=(prev.summary if prev else None),
                       prev_ran_at=(prev.ran_at.isoformat() if prev else None))
    finally:
        s.close()


@bp.route('/shopmine-recon/latest')
def shopmine_recon_latest():
    """마지막 대조 결과(탭 진입 시 초기 표시) + 직전 실행 요약(지난번 대비)."""
    from lemouton.markets.models_shopmine import ShopmineReconRun

    s = SessionLocal()
    try:
        runs = (s.query(ShopmineReconRun)
                .order_by(ShopmineReconRun.id.desc()).limit(2).all())
        if not runs:
            return jsonify(ok=True, latest=None)
        latest = runs[0]
        prev = runs[1] if len(runs) > 1 else None
        return jsonify(ok=True,
                       latest={'ran_at': latest.ran_at.isoformat(),
                               'filename': latest.filename,
                               'summary': latest.summary,
                               'detail': latest.result},
                       prev=(prev.summary if prev else None),
                       prev_ran_at=(prev.ran_at.isoformat() if prev else None))
    finally:
        s.close()


@bp.route('/inspect/upload-stream', methods=['POST'])
def inspect_upload_stream():
    """더망고 업로드 → 진행현황을 NDJSON 스트리밍(마켓별 실건수). 폴링 없이 응답 스트림.

    이벤트(한 줄=JSON): parsed → start(마켓목록) → market(fetching→done, matched/total) → done.
    파싱 에러는 스트림 전에 422로 낸다(스트림 시작 후엔 헤더 못 바꿈).
    """
    from flask import Response, stream_with_context
    import json as _json
    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='파일이 없습니다.'), 400
    bulk = request.form.get('bulk_method') or None
    if bulk == '자동판정':
        bulk = None
    try:
        rows = parse_mango_xls(f.read())
    except MangoParseError as e:
        return jsonify(ok=False, error=str(e)), 422
    except Exception as e:   # noqa: BLE001
        return jsonify(ok=False, error=f'엑셀을 읽지 못했어요: {type(e).__name__}'), 400

    def gen():
        from lemouton.delivery import market_enrich as _me
        s = SessionLocal()
        try:
            _dsvc.seed_default_status_map(s)
            res = _dsvc.upsert_orders(s, rows, bulk_method=bulk, replace_stale=True)
            yield _json.dumps({"phase": "parsed", "parsed": len(rows),
                               "inserted": res["inserted"], "updated": res["updated"]},
                              ensure_ascii=False) + "\n"
            warn = []
            try:
                for ev in _me.iter_enrich(s, [r["mango_uid"] for r in rows], warn):
                    yield _json.dumps(ev, ensure_ascii=False) + "\n"
            except Exception as e:   # noqa: BLE001 — enrich 실패해도 업로드는 성공(확인불가로 남음)
                warn.append(f"마켓 조회 실패: {type(e).__name__}")
                yield _json.dumps({"phase": "done", "checked": 0, "unmatched": 0,
                                   "skipped": 0, "warnings": warn}, ensure_ascii=False) + "\n"
        finally:
            s.close()

    return Response(stream_with_context(gen()), mimetype="application/x-ndjson",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@bp.route('/inspect/clear', methods=['POST'])
def inspect_clear():
    """배송검사 초기화 — 더망고 주문 전량 삭제(미실시 0 상태로)."""
    s = SessionLocal()
    try:
        n = _dsvc.clear_orders(s)
        return jsonify(ok=True, deleted=n)
    finally:
        s.close()


@bp.route('/inspect/method', methods=['POST'])
def inspect_method():
    """행별 수기 배송방식 지정."""
    body = request.get_json(silent=True) or {}
    uid, method = body.get('uid'), body.get('method')
    if method not in ('까대기', '직배', '미지정'):
        return jsonify(ok=False, error='잘못된 배송방식'), 400
    s = SessionLocal()
    try:
        return jsonify(ok=_dsvc.set_method_manual(s, uid, method))
    finally:
        s.close()


@bp.route('/inspect/bulk-method', methods=['POST'])
def inspect_bulk_method():
    """전체 일괄 배송방식 지정(수기 제외)."""
    method = (request.get_json(silent=True) or {}).get('method')
    if method not in ('까대기', '직배', '미지정'):
        return jsonify(ok=False, error='잘못된 배송방식'), 400
    s = SessionLocal()
    try:
        return jsonify(ok=True, changed=_dsvc.apply_bulk_method(s, method))
    finally:
        s.close()


@bp.route('/inspect/mapping', methods=['POST'])
def inspect_mapping():
    """구분자 매핑 저장. body: {items:[{value, meaning, default_method, flow}]}"""
    items = (request.get_json(silent=True) or {}).get('items') or []
    s = SessionLocal()
    try:
        by_value = _dsvc.get_status_map(s)
        for it in items:
            m = by_value.get(it.get('value'))
            if not m:
                continue
            m.meaning = it.get('meaning', m.meaning)
            m.default_method = it.get('default_method', m.default_method)
            m.is_flow_check_target = bool(it.get('flow', m.is_flow_check_target))
        s.commit()
        return jsonify(ok=True)
    finally:
        s.close()
