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
from shared.db import SessionLocal
from lemouton.delivery import service as _dsvc
from lemouton.delivery.mango_parser import parse_mango_xls, MangoParseError
from lemouton.claims import service as _claim_svc
from lemouton.cs_inquiries import service as _inq_svc


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '📋 주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    # [2026-07-24] 송장 넣는 일을 한 곳에 모은 탭. 주문 내역과 **같은 화면 코드**를 쓰되
    #  배치만 4단계로 바꾼다(아이디가 같아야 기존 배선이 그대로 돈다).
    {'key': 'ship', 'label': '📦 송장 작업', 'desc': '더망고 대조 → 걸러내기 → 송장 전송 → 배송흐름 검산'},
    # [2026-07-24] 배송검사(inspect) 탭 삭제 — 「송장 작업」 ②·④ 로 흡수.
    #   같은 일을 하는 화면이 두 벌이라 어디서 뭘 하는지 알 수 없었다(사장님: "거의 안 썼다").
    #   옛 주소는 아래 orders_index 에서 tab=ship 으로 넘긴다(북마크 보호).
    # [2026-07-16] 정산·매출(sales) 탭 삭제(사용자 요청). tab=sales 진입은 list 로 폴백.
    {'key': 'cs', 'label': '💬 CS', 'desc': '취소·반품·교환 + 고객문의 조회·처리'},
    {'key': 'register', 'label': '🆕 신규 상품 등록', 'desc': '모음전 상품을 마켓에 신규 등록'},
    {'key': 'margin', 'label': '🧮 마진 계산기', 'desc': '가격·수수료·배송비 입력 → 실 마진 시뮬'},
    {'key': 'recon', 'label': '🔍 샵마인 대조', 'desc': '샵마인 정답지 엑셀 ↔ 우리 적재분 전수 대조 (누락·필드차이)'},
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
    """송장 엑셀 업로드 → 「오픈마켓주문번호」로 매칭한 결과 반환(전송 아님)."""
    from flask import jsonify
    from lemouton.markets.invoice_excel import (parse_invoice_excel, match_invoices,
                                                InvoiceExcelError)

    f = request.files.get('file')
    if f is None:
        return jsonify(ok=False, error="엑셀 파일이 없어요."), 400

    order_nos = [s.strip() for s in (request.form.get('order_nos') or '').split(',') if s.strip()]
    try:
        excel_rows = parse_invoice_excel(f.read())
    except InvoiceExcelError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001 — 손상 파일 등
        return jsonify(ok=False, error=f"엑셀을 읽지 못했어요: {type(e).__name__}"), 400

    res = match_invoices(excel_rows, order_nos)
    return jsonify(ok=True, matched=res.matched, unmatched=res.unmatched,
                   conflicts=res.conflicts, read=len(excel_rows))


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
