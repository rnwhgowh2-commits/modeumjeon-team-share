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
    # [2026-08-12] 역할 나눔(설계서 §9) — 실매입가 입력·이상마진·블랙스팟은 「주문 내역」으로
    #   옮겼다. 🔴 탭은 없애지 않는다: 이 화면에만 있는 기간 집계(일별·월별·브랜드별·
    #   금액대별·상품별·마켓별·소싱처별)가 옮겨진 적이 없어서 없애면 통째로 사라진다.
    {'key': 'margin', 'label': '마진 계산기',
     'desc': '기간 집계·분석 (일별·월별·브랜드별·마켓별·소싱처별) — 실매입가 입력은 주문 내역에서'},
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


def _parse_markets(args, dropped=None):
    """markets(콤마·다중) 또는 market(단일). supported_markets() 로 필터(순서 유지·중복 제거).

    🔴 걸러진 마켓 이름을 `dropped` 리스트에 담아 준다(2026-08-12). 옛 판은 조용히
      버리기만 해서, 옥션을 분명히 지정했는데도 화면엔 「선택된 마켓이 없어요」만
      떴다 — 「아무것도 안 골랐다」와 「고른 게 안 열렸다」가 같은 얼굴이었다.
    """
    raw = args.get('markets') or args.get('market') or 'smartstore'
    out, seen = [], set()
    _sup = _oe.supported_markets()
    for m in raw.split(','):
        m = m.strip()
        if not m or m in seen:
            continue
        if m in _sup:
            seen.add(m)
            out.append(m)
        elif dropped is not None:
            dropped.append(m)
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


# 엑셀 맨 앞에 붙일 수 있는 화면 전용 열. 화면(orders/index.html doExport)이
#  행에 같은 이름으로 값을 얹어 보낸다. 여기 없는 이름은 조용히 무시한다.
_EXPORT_LEAD_COLS = ('주문 관리',)


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
    # 화면 전용 칸 중 **엑셀에도 나가야 하는 것**만 맨 앞에 붙인다(사장님 확정 2026-08-06).
    #  🔴 화이트리스트로 막는다 — 클라이언트가 보낸 아무 이름이나 열이 되면 엑셀을 쓰는
    #    다른 흐름(마진계산기·샵마인 대조 양식)이 모르는 열을 만나게 된다.
    #  🔴 기존 열 목록(ALL_COLUMNS)에는 넣지 않는다 → 기존 열 순서·이름은 그대로다.
    _lead_in = d.get('lead_cols')
    if not isinstance(_lead_in, (list, tuple)):
        _lead_in = []
    lead = [c for c in _lead_in if c in _EXPORT_LEAD_COLS]
    xlsx = _oe.rows_to_xlsx(rows, columns=cols, lead_columns=lead)
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
    dropped = []
    markets = _parse_markets(request.args, dropped)
    days = _parse_days(request.args)
    since, until = _parse_range(request.args)
    if not markets:
        # 🔴 「고른 게 없다」와 「고른 게 안 열렸다」를 갈라 말한다. 옥션·G마켓은
        #   고정 목록이 아니라 **라이브 검증 결과**로 열리므로, 그 확인이 실패하면
        #   여기로 떨어진다 — 옛 문구는 그 사실을 통째로 숨겼다(라이브 400 사고).
        if dropped:
            _ko = "·".join(_oe.market_label(m) for m in dropped)
            return jsonify(ok=False, dropped=dropped,
                           error=f"{_ko} 은(는) 아직 조회가 열리지 않았어요 — "
                                 f"판매처관리에서 「🧪 라이브 검증」을 마쳐 주세요. "
                                 f"(검증을 마쳤는데도 이 말이 뜨면 검증 상태를 "
                                 f"확인하지 못한 것이니 잠시 뒤 다시 눌러 주세요.)"), 400
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


@bp.route('/diag/esm-timing')
def orders_diag_esm_timing():
    """옥션·G마켓 조회가 **어디서 시간을 쓰는지** 재는 창구(읽기 전용).

    🔴 왜 있나 — 2026-08-13 클레임 49회를 동시에 보내도록 고쳤는데 오히려 느려 보였다.
      그런데 「클레임에 몇 초 썼는지」가 서버 기록에만 있어 화면에서 원인을 가릴 수
      없었다. 되돌릴지 유지할지 정하려면 이 숫자가 있어야 한다.
      마켓을 실제로 부르므로(5초/1회 제한) 진단용으로만 쓴다.
    """
    import time as _t
    from flask import jsonify
    market = (request.args.get('market') or '').strip()
    if market not in ('auction', 'gmarket'):
        return jsonify(ok=False, error="market 은 옥션(auction)·G마켓(gmarket)만 돼요."), 400
    try:
        days = max(1, min(int(request.args.get('days') or 1), 31))
    except (TypeError, ValueError):
        days = 1
    until = _dt.datetime.now()
    since = until - _dt.timedelta(days=days)
    # 🔴 주문조회는 **계정 키로 만든 클라이언트**가 있어야 돈다. 안 붙이면
    #   `AttributeError: 'NoneType' object has no attribute 'request_orders'` 로 터진다
    #   (2026-08-13 라이브에서 바로 겪음 — 시험이 esm_order_rows 를 가짜로 갈아
    #    끼워 이 구멍을 못 봤다).
    cli = _oe._account_client(market)
    if cli is None:
        return jsonify(ok=False, error=f"{_oe.market_label(market)} API 키(자격증명)가 "
                                       f"등록돼 있지 않아 잴 수 없어요."), 200
    diag, warns = {"counts": {}, "errors": {}}, []
    t0 = _t.monotonic()
    try:
        rows = _oe.esm_order_rows(market, since, until, client=cli,
                                  diag=diag, warnings=warns)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, 총초=round(_t.monotonic() - t0, 1),
                       error=f"{type(e).__name__}: {str(e)[:300]}",
                       counts=diag.get("counts"), errors=diag.get("errors")), 200
    return jsonify(ok=True, market=market, days=days,
                   총초=round(_t.monotonic() - t0, 1), 행수=len(rows),
                   counts=diag.get("counts") or {}, errors=diag.get("errors") or {},
                   warnings=warns)


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


@bp.post('/fulfillment/recheck.json')
def orders_fulfillment_recheck():
    """이행 판단 ② — 「값이 바뀌는 상품」만 다시 긁도록 확인 요청을 찍는다 (노션 ⑤).

    사장님 확정: *"변경값 없는건 저장된 크롤값 그대로 + 변경값있는건 새로 긁고 판정.
    해당 주문건에 소싱처 url 있는것만 긁으면 돼"* — 「변경값」 = 그 상품의 **가격·재고**가
    바뀐 것(2026-08-13 확인). 그 신호는 크롤이 이미 남기고 있다(`no_change_streak`).

    🔴 여기서 긁지 않는다 — 크롤은 사장님 PC 확장 몫이다(서버는 IP 가 다르다).
      표식만 찍고, 두 마감 경로(벽시계·랩)가 그걸 읽어 맨 앞으로 올린다.

    payload: {rows: [주문행, ...]}  →  {ok, 요청, 대상주문, 값이_안_바뀌는_상품, ...}
    """
    from lemouton.orders import fulfillment as _ff
    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    if not rows:
        return jsonify(ok=True, 요청=0, 대상주문=0)
    s = SessionLocal()
    try:
        res = _ff.request_recheck(s, rows)
        s.commit()
        return jsonify(ok=True, **res)
    except Exception as e:   # noqa: BLE001
        s.rollback()
        import logging
        logging.getLogger(__name__).exception("확인 요청 실패 rows=%d", len(rows))
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    finally:
        s.close()


# ──────────────────────────────────────────────────────────────
#  실매입가 — 저장(수기) · 우선순위 조회 · 더망고 매입 엑셀 매칭
#   설계서 docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md §5
#   🔴 주문 라인 인라인 저장 경로는 여기가 처음이다(조사 확인) — 새로 만든 길.
# ──────────────────────────────────────────────────────────────

def _invalidate_tower_sales(reason: str) -> None:
    """실매입가가 바뀌면 상품관리 「판매 이력」 집계 캐시를 즉시 버린다.

    🔴 왜 필요한가(라이브 실측 2026-08-06) — 판매 이력은 300초 서버 캐시라, 여기서
    매입가를 저장해도 **최대 5분간 옛 값**(「매입가 미입력」)이 그대로 보였다.
    돈 화면이라 사장님이 「저장이 안 됐나?」로 읽는 자리다.

    이건 **이 워커 몫**이다. 라이브 워커는 2개고 캐시는 프로세스 메모리라, 다른
    워커는 이 호출을 못 받는다 — 그쪽은 `bundles_tower.purchase_stamp`(DB 도장)로
    스스로 알아챈다. 그래서 여기가 실패해도 낡은 채로 굳지는 않지만, **조용히
    넘기지는 않는다**(로그로 남긴다 — 도장까지 못 읽는 상황을 눈으로 봐야 한다).
    """
    try:
        from webapp.routes import bundles_tower as _tower
        _tower.invalidate_sales_cache(reason)
    except Exception:   # noqa: BLE001 — 캐시 비우기 실패가 저장을 되돌리면 안 된다
        import logging
        logging.getLogger(__name__).exception(
            "판매 이력 캐시 무효화 실패 — %s (DB 도장으로는 여전히 갱신됩니다)", reason)


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
                         source=_pp.SOURCE_MANUAL, memo=memo, input_by=_who())
        # 저장이든 삭제(0·빈칸)든 실현 마진이 달라진다 — 둘 다 캐시를 버린다.
        _invalidate_tower_sales(f'실매입가 저장 uid={line_uid}')
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


def _who():
    """지금 로그인한 사람(이메일). 못 알면 None — 「모른다」를 지어내지 않는다."""
    try:
        from flask_login import current_user
        return getattr(current_user, 'email', None)
    except Exception:   # noqa: BLE001 — 로그인 매니저 없는 테스트 앱
        return None


@bp.get('/api/purchase-price/history')
def purchase_price_history():
    """한 주문 줄의 실매입가 변경 이력. `?line_uid=...&limit=50`

    화면(매입가 칸의 「이력」)이 그대로 그린다. 이력이 없으면 빈 목록 —
    **「변경 없음」과 「이력 기능 도입 전」을 화면이 구분해 말한다**(items 가 비면 안내문).
    """
    from lemouton.markets import purchase_price as _pp

    uid = (request.args.get('line_uid') or '').strip()
    if not uid:
        return jsonify(ok=False, error="line_uid 가 없어요."), 400
    try:
        limit = max(1, min(200, int(request.args.get('limit') or 50)))
    except (TypeError, ValueError):
        limit = 50
    s = SessionLocal()
    try:
        return jsonify(ok=True, line_uid=uid, items=_pp.history(s, uid, limit=limit))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("매입가 이력 조회 실패 uid=%s", uid)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/purchase-price/bulk')
def purchase_price_bulk():
    """고른 여러 줄에 **같은** 실매입가를 한꺼번에. payload: {line_uids:[...], price, memo?}

    · 상태 열 일괄 지정(`/api/line-status/bulk`)과 **같은 규약**이다 — 열쇠는 반드시
      `line_uid`. 🔴 주문번호로 묶으면 다품목 주문의 형제 줄까지 같은 값이 박힌다.
    · `price` 가 비었거나 0 이면 **고른 줄의 실매입가를 지운다**(= 「입력 안 함」).
      한 줄 저장과 같은 규칙이라 「빈칸으로 저장 = 지움」이 화면마다 갈리지 않는다.
    · 🔴 한 줄이 실패해도 나머지를 되돌리지 않는다 — 대신 실패한 줄을 **그대로 돌려준다**
      (조용한 실패 금지). 화면이 「N줄 저장 · M줄 실패」로 말한다.
    """
    from lemouton.markets import purchase_price as _pp

    payload = request.get_json(silent=True) or {}
    uids = payload.get('line_uids') or []
    if not isinstance(uids, list) or not uids:
        return jsonify(ok=False, error="선택된 주문 줄이 없어요."), 400
    if len(uids) > 2000:
        return jsonify(ok=False, error="한 번에 2,000줄까지예요 — 나눠서 저장해 주세요."), 400
    raw = payload.get('price')
    if raw not in (None, ''):
        try:                          # 숫자가 아니면 조용히 0(=삭제)으로 흘리지 않는다
            float(str(raw).replace(',', '').strip())
        except (TypeError, ValueError):
            return jsonify(ok=False, error="매입가는 숫자로 적어 주세요."), 400
    memo = payload.get('memo')
    memo = str(memo)[:255] if memo not in (None, '') else None
    who = _who()
    s = SessionLocal()
    try:
        saved, deleted, failed = 0, 0, []
        for u in uids:
            uid = str(u or '').strip()
            if not uid:
                continue
            try:
                row = _pp.upsert(s, line_uid=uid, price=raw,
                                 source=_pp.SOURCE_MANUAL, memo=memo,
                                 input_by=who)
                if row is None:
                    deleted += 1
                else:
                    saved += 1
            except Exception as e:   # noqa: BLE001 — 한 줄 실패가 나머지를 막지 않는다
                failed.append({'line_uid': uid, 'error': f"{type(e).__name__}: {str(e)[:120]}"})
        if saved or deleted:
            _invalidate_tower_sales(f'실매입가 일괄 저장 {saved}줄 · 지움 {deleted}줄')
        return jsonify(ok=True, saved=saved, deleted=deleted, failed=failed,
                       price=(None if not saved else _pp._to_price(raw)),
                       tier=(None if not saved else _pp.TIER_REAL),
                       label=(_pp.LABEL_UNKNOWN if not saved
                              else _pp.TIER_LABEL[_pp.TIER_REAL]))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("실매입가 일괄 저장 실패 n=%d", len(uids))
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/purchase-price/resolve')
def purchase_price_resolve():
    """매입가 우선순위 3단계 조회 + 가로 탭 판정.

    payload: {rows: [주문행, ...]} → {ok, prices:{line_uid:{...}}, flags:{line_uid:{...}}}

    price-diff.json 과 **같은 규약**: 화면이 이미 불러온 행을 그대로 보내면 계산해 돌려준다
    (주문 조회에 얹으면 소싱 계산이 표 전체를 붙잡는다).

    🔴 판정(`flags`)을 **여기서 같이** 내는 이유 — 판정은 「주문 행 + 그 매입가」의 순수
      함수인데, 그 둘이 다 모여 있는 곳이 여기뿐이다. 따로 부르면 소싱처 최종매입가
      계산(`resolve_purchase_price` 의 제일 무거운 부분)을 **두 번** 돌린다.
      규칙 자체는 `lemouton/orders/margin_flags.py` 하나에만 있다(마진 계산기에서 이식).
    """
    from lemouton.markets import purchase_price as _pp
    from lemouton.orders import margin_flags as _mf

    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    uids = [u for u in ((r or {}).get('_line_uid') for r in rows) if u]
    if not uids:
        return jsonify(ok=True, prices={}, flags={})
    s = SessionLocal()
    try:
        prices = _pp.resolve_purchase_price(s, uids, rows=rows)
        return jsonify(ok=True, prices=prices, flags=_mf.flag_rows(rows, prices))
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


# ──────────────────────────────────────────────────────────────
#  「주문 관리」 상태 — 사장님이 만든 항목 + 줄마다 지정 (사장님 확정 2026-08-06)
#   · 항목은 팀 전체가 공유한다. **처음엔 빈 목록**이다(기본 항목을 심지 않는다).
#   · 색은 우리 프로그램 색 7가지에서만 고른다(자유 색 금지).
#   · 「기본 항목」은 **표시만** 한다 — 주문 줄마다 행을 미리 만들지 않는다.
#   · 실매입가(`/api/purchase-price`)·공급방식과 **같은 규약**(resolve 로 일괄 조회).
# ──────────────────────────────────────────────────────────────

@bp.get('/api/status-options')
def status_options_list():
    """항목 목록(정한 순서대로) + 고를 수 있는 색 목록.

    🔴 비어 있는 게 정상이다 — 화면은 그때 「+ 첫 항목 만들기」를 안내한다.
    """
    from lemouton.markets import models_order_status as _mos
    from lemouton.markets import order_status as _st

    s = SessionLocal()
    try:
        return jsonify(ok=True, options=_st.list_options(s),
                       colors=list(_mos.STATUS_COLORS),
                       color_labels=_mos.COLOR_LABELS)
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 항목 목록 조회 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/status-options')
def status_options_create():
    """항목 추가. payload: {name, color?, is_default?} — 이름이 겹치면 400."""
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        opt = _st.create_option(s, name=payload.get('name'),
                                color=payload.get('color') or 'gray',
                                is_default=bool(payload.get('is_default')))
        return jsonify(ok=True, option=opt, options=_st.list_options(s))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 항목 추가 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.patch('/api/status-options/<int:option_id>')
def status_options_update(option_id):
    """항목 수정. payload: {name?, color?, sort_no?, is_default?}

    `is_default: true` 면 **기존 기본은 자동으로 내려간다**(둘 다 True 인 상태 없음).
    """
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    dflt = payload.get('is_default')
    s = SessionLocal()
    try:
        opt = _st.update_option(
            s, option_id,
            name=payload.get('name') if 'name' in payload else None,
            color=payload.get('color') if 'color' in payload else None,
            sort_no=payload.get('sort_no') if 'sort_no' in payload else None,
            is_default=(bool(dflt) if dflt is not None else None))
        return jsonify(ok=True, option=opt, options=_st.list_options(s))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 항목 수정 실패 id=%s", option_id)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/status-options/reorder')
def status_options_reorder():
    """끌어서 바꾼 순서 저장. payload: {ids:[...]}"""
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    ids = payload.get('ids')
    if not isinstance(ids, list):
        return jsonify(ok=False, error="ids 는 배열이어야 해요."), 400
    s = SessionLocal()
    try:
        return jsonify(ok=True, options=_st.reorder(s, ids))
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 항목 순서 저장 실패")
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.delete('/api/status-options/<int:option_id>')
def status_options_delete(option_id):
    """항목 삭제.

    🔴 쓰는 중이면 **409 + 몇 건이 쓰는지**로 거절한다 — 화면이 「3건이 쓰는 중」
      확인창을 띄우고, 사장님이 확인하면 `?force=1` 로 다시 부른다.
      force 로 지우면 그 주문 줄들의 상태는 **비워진다**(「지정 안 함」).
    """
    from lemouton.markets import order_status as _st

    force = str(request.args.get('force') or '').strip() in ('1', 'true', 'yes')
    s = SessionLocal()
    try:
        res = _st.delete_option(s, option_id, force=force)
        return jsonify(ok=True, options=_st.list_options(s), **res)
    except _st.InUseError as e:
        # 몇 건이 쓰는지 반드시 담는다 — 화면이 그 숫자로 물어본다.
        return jsonify(ok=False, in_use=True, count=e.count, name=e.name,
                       error=str(e)), 409
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 항목 삭제 실패 id=%s", option_id)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/line-status')
def line_status_save():
    """한 줄 상태 저장·해제. payload: {line_uid, option_id|null}

    · `option_id` 가 null 이면 **행을 지운다**(= 「지정 안 함」).
    · 고르는 즉시 저장이라 저장 단추가 없다 → 결과를 그대로 돌려준다(조용한 실패 금지).
    """
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    line_uid = str(payload.get('line_uid') or '').strip()
    if not line_uid:
        return jsonify(ok=False, error="line_uid 가 없어요 — 어느 주문 줄인지 알 수 없습니다."), 400
    s = SessionLocal()
    try:
        row = _st.set_line_status(s, line_uid=line_uid,
                                  option_id=payload.get('option_id'))
        # 🔴 비운 뒤에도 `resolve` 를 돌려준다 — 기본 항목이 지정돼 있으면 그 줄은
        #   다시 「기본 표시」(is_fallback)로 돌아간다. 화면이 스스로 추측하면 갈린다.
        got = _st.resolve(s, [line_uid]).get(line_uid)
        return jsonify(ok=True, saved=row is not None, cleared=row is None,
                       status=got)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 저장 실패 uid=%s", line_uid)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/line-status/bulk')
def line_status_bulk():
    """고른 여러 줄 한꺼번에 지정. payload: {line_uids:[...], option_id|null}

    🔴 열쇠는 반드시 line_uid — 주문번호로 묶으면 다품목 주문의 형제 줄까지 같이 바뀐다.
    """
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    uids = payload.get('line_uids') or []
    if not isinstance(uids, list) or not uids:
        return jsonify(ok=False, error="선택된 주문 줄이 없어요."), 400
    s = SessionLocal()
    try:
        res = _st.set_many(s, line_uids=uids, option_id=payload.get('option_id'))
        return jsonify(ok=True, statuses=_st.resolve(s, uids), **res)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 일괄 저장 실패 n=%d", len(uids))
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"), 500
    finally:
        s.close()


@bp.post('/api/line-status/resolve')
def line_status_resolve():
    """표에 그릴 값 일괄 조회. payload: {rows:[주문행,...]}
        → {ok, statuses:{line_uid:{option_id,name,color,is_fallback}}, options:[...]}

    실매입가 `/api/purchase-price/resolve` 와 **같은 규약** — 화면이 이미 불러온
    행을 그대로 보낸다. 항목 목록도 같이 준다(드롭다운을 그리려면 어차피 필요하고,
    따로 부르면 표 한 판에 요청이 하나 더 는다).

    🔴 저장 안 된 줄에는 **기본 항목을 얹어 보내되 `is_fallback: true`** 다 —
      화면은 점선 테두리 + 「기본」 꼬리표로 「아직 안 봄」임을 구분해 보여준다.
      여기서 행을 만들지 않는다.
    """
    from lemouton.markets import order_status as _st

    payload = request.get_json(silent=True) or {}
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return jsonify(ok=False, error="rows 는 배열이어야 해요."), 400
    s = SessionLocal()
    try:
        options = _st.list_options(s)
        uids = [u for u in ((r or {}).get('_line_uid') for r in rows) if u]
        if not uids:
            return jsonify(ok=True, statuses={}, options=options)
        return jsonify(ok=True, statuses=_st.resolve(s, uids), options=options)
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("상태 조회 실패 rows=%d", len(rows))
        # 주문 표는 안 깨진다 — 실패하면 상태 칸만 빈다(옛 값을 최신인 척 하지 않는다).
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
        # 엑셀 한 번에 여러 상품이 바뀐다 — 그래서 상품별이 아니라 통째로 버린다.
        if res['saved']:
            _invalidate_tower_sales(f'더망고 매입 엑셀 {fname} — {res["saved"]}줄 저장')
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
        lines = [{"row": dict(o.row or {}), "market": o.market,
                  "account": o.account or "", "status_at": o.status_at}
                 for o in q.all()]
    finally:
        s.close()
    # 🔴 [2026-08-13] 클레임 행을 **주문번호로 원래 주문행에 이어** 표식을 남긴다.
    #   여기서 하는 이유 — 이 함수가 정산예정금액의 **유일한 줄 만드는 곳**이다.
    #   집계·드릴다운·엑셀이 전부 여기를 지나므로 한 곳만 손대면 셋이 절대 안 갈린다.
    #   (예전에 판정이 두 곳에 흩어져 「KPI 5.5억 · 목록 0건」이 라이브에 나갔다.)
    from lemouton.margin import settle_plan as _sp
    return _sp.annotate_claims(lines)


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
    # ⚡ 빠른정산으로 **이미 받은 돈**은 그 회차가 지급될 **칸에서** 뺀다.
    #   🔴 총액에서만 빼면 기간별 표가 그대로 부풀어 「이 주에 얼마 들어오나」가 거짓이 된다
    #      (2026-08-06 사장님: "결국 기간내 얼마 받을지 아는게 중요. 이미 받은걸로 헷갈리게 말 것").
    #   🔴 지급 끝난 회차는 안 뺀다 — 그 주문은 이미 「받은 것」이라 칸에 없다(이중 차감 방지).
    try:
        from lemouton.margin import settle_fast_ledger as FL
        fast = FL.summary()
        if axis != 'order':
            out = SP.apply_fast_withdrawn(out, FL.load().get('rows') or [], unit=unit)
    except Exception:   # noqa: BLE001 — 장부가 없어도 집계는 그대로 나가야 한다
        fast = {"합계": 0, "계정별": [], "차감액": 0, "수령완료분": 0, "회차수": 0}
    out['빠른정산'] = fast
    # 💰 셀러월렛 **미인출 잔액** — 이미 사장님 돈인데 아직 안 찾아간 돈(Wing 실측 세소 811만).
    #   인출해야 회차에서 공제되므로 그 전까지 주문별 정산액에 남아 「받을 돈」이 부푼다.
    #   🔴 **기간 칸에는 못 나눈다** — 어느 주문 몫인지 알 근거가 없다. 없는 근거로 특정 주에
    #      배분하면 그 주가 거짓이 된다 → 총액(net_uncollected)에서만 뺀다.
    try:
        from lemouton.margin.settle_plan_rules import load_rules as _lr, wallet_summary
        wallet = wallet_summary(_lr())
    except Exception:   # noqa: BLE001 — 규칙을 못 읽으면 안 뺀다(안전측)
        wallet = {"합계": 0, "계정별": []}
    out['셀러월렛'] = wallet
    # 🚀 로켓그로스 — 쿠팡 마켓플레이스와 **완전히 별도**라 지금까지 「받을 돈」에서 통째로
    #   빠져 있었다(2026-08-07 실측: 매출내역에 0건·정산 회차에도 안 섞임).
    #   Wing 화면 API 를 로컬 크롤이 긁어 넣는다.
    #   🔴 기간 칸에는 못 나눈다 — 회차 단위라 주문별 지급예정일이 없다. 총액에만 더한다.
    #   🔴🔴 [2026-08-13] 「받을 돈」 = **Σ최종지급액(정산일 오늘 이후 ~ 한 달)** 이다.
    #     옛 `지급액 − 빠른정산`(기간 제한 없음)은 **이미 받은 회차까지 세어** 화면이
    #     9,508,138 을 보여줬다 — 쿠팡 화면 실제 값은 7,818,202(사장님 Wing 25회차로
    #     원 단위 확인). 그 차이 1,689,936 이 「앞으로 받을 돈」 총액에 그대로 얹혔다.
    #     대조 엔진(settle_recon)만 고치고 **이 화면 숫자를 안 고쳐** 라이브가 틀린 채였다.
    #     규칙 정본 = `rg_settlement.ahead_summary()`.
    try:
        from lemouton.margin import rg_settlement as RG
        rg = RG.summary()
        _ahead = RG.ahead_summary()
        rg['앞으로받을돈'] = int(_ahead.get('금액') or 0)
        rg['앞으로회차수'] = int(_ahead.get('회차수') or 0)
        rg['이미받은회차합'] = int(_ahead.get('이미받은회차합') or 0)
        rg['창'] = _ahead.get('창') or ''
    except Exception:   # noqa: BLE001 — 로켓그로스가 없어도 나머지 집계는 나가야 한다
        rg = {"지급액": 0, "빠른정산": 0, "받을돈": 0, "최종지급": 0,
              "회차수": 0, "계정별": [], "앞으로받을돈": 0, "앞으로회차수": 0,
              "이미받은회차합": 0, "창": ""}
    out['로켓그로스'] = rg
    kpi = out.get('kpi') or {}
    if isinstance(kpi, dict):
        base = kpi.get('net_uncollected')
        if base is None:
            base = int(kpi.get('total_uncollected') or 0)
        kpi['wallet_balance'] = wallet['합계']
        # 🔴 화면·총액 둘 다 **같은 값**을 써야 한다 — 하나만 고치면 카드와 총액이 갈린다.
        _rg_ahead = int(rg.get('앞으로받을돈') or 0)
        kpi['rocket_growth'] = _rg_ahead
        kpi['net_uncollected'] = max(0, int(base) - int(wallet['합계']) + _rg_ahead)
    return jsonify(out)


def _settle_ship_part(row: dict) -> int:
    """N열(`정산예정금(배송비포함)`) 안에 들어 있는 **배송비 몫**.

    🔴 N열이 무엇을 더했는지와 **똑같아야** 한다(order_export._finalize_rows).
      마켓이 배송비 정산 실값을 주면 그 값(`_ship_settle`), 아니면 고객배송비.
      여기만 고객배송비로 쪼개면 상품·배송비 두 칸이 동시에 틀린다 —
      합계는 맞아서 눈에 안 띄고, 사장님이 마켓 화면과 맞대 볼 때만 드러난다.
    🔴 0 은 「모름」이 아니라 「배송비 정산 0원」이다 → `is not None` 으로만 가른다.
    """
    real = _oe._to_int(row.get("_ship_settle"))
    if real is not None:
        return real
    return _oe._to_int(row.get("배송비"), 0) or 0


@bp.route('/api/settle-plan/detail')
def settle_plan_detail():
    """주문건 드릴다운 — category(confirmed|unconfirmed|overdue|not_started|undated|
    assumed_paid|risk|paid)·market·account·bucket(+unit) 필터. 상품/배송비/총 3칸 + 배지.

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
    axis = (request.args.get('axis') or 'payout').strip()
    # 🔴 [2026-08-13] `orders=번호,번호` — 마켓 정산 명세와 **주문 단위로** 맞대기 위한 창구.
    #   부류(category)로 훑으면 라이브에서 `paid` 한 부류만 2,000행 상한에 걸려 잘린다
    #   (상한은 화면 보호용이라 없애면 안 된다). 대조는 「내가 아는 주문번호」로 좁히는 게
    #   맞다 — 부류를 몰라도 되고, 잘림도 없고, 다음에 같은 대조를 그대로 재현할 수 있다.
    want_orders = {o.strip() for o in (request.args.get('orders') or '').split(',')
                   if o.strip()}
    if axis == 'order':
        # 🔴 [2026-08-12 노션 c-3] 주문일 축에도 상세내역을 준다. 부류(confirmed/…)는
        #   지급예정일 축의 개념이라 여기선 안 쓴다 — 그 칸에 들어간 주문 그대로다.
        #   들어가는지/매출액이 얼마인지는 집계와 **같은 함수**(SP.order_axis_row)가 정한다.
        return _settle_plan_detail_order(SP, market, account, bucket, unit)
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
        if want_orders and str(ln["row"].get("오픈마켓주문번호") or "") not in want_orders:
            continue
        amount, src = _settlement_for(ln["row"])
        if not amount:
            continue
        evs = r["events"]
        row = ln["row"]
        if category in ("risk", "paid"):
            if cat != category:
                continue
            # 🔴 [2026-08-12 노션 c-2] 「받은 이력」 칸을 눌렀을 때 그 칸의 주문만 준다.
            #   받은 것의 날짜 축은 예정일이 아니라 **실제 받은 날**이다.
            if bucket and category == "paid":
                _pd0 = SP._norm_date(row.get("_settle_paid_date"))
                if not _pd0 or SP.bucket_key(_pd0, unit) != bucket:
                    continue
        elif category:
            evs = [e for e in evs if e.get("bucket") == category]
            if not evs:
                continue
            # 🔴 [2026-08-12] 예전엔 확정/미확정에만 칸 거르기를 걸었다 — 지난 날 칸
            #   (지남·정산시작전·받았을것)을 눌러도 그 기간과 무관한 전건이 나왔다.
            #   이벤트 날짜로 거르는 건 어느 부류든 똑같이 옳다.
            if bucket:
                evs = [e for e in evs
                       if e["date"] and SP.bucket_key(e["date"], unit) == bucket]
                if not evs:
                    continue
        ship = _settle_ship_part(row)
        dates = [e["date"] for e in evs if e["date"]]
        srcs = {e["date_source"] for e in evs if e["date_source"]}
        # 쿠팡 분할지급이면 이 목록에 걸린 **조각 금액**만 보여준다(주문 전체가 아니라).
        #  그때 상품/배송비 쪼개기는 근거가 없으므로 비우고 총액만 적는다(날조 금지).
        part = sum(e["amount"] for e in evs) if evs else amount
        is_part = bool(evs) and part != amount
        # 🔴 [2026-08-06 라이브] 이미 받은 주문은 지급 **예정**이 없어 「미정·근거없음」으로
        #   떴다. 받은 날(_settle_paid_date)이 있으니 그걸 보여준다(마켓이 알려준 실측).
        if cat == "paid":
            _pd = SP._norm_date(row.get("_settle_paid_date"))
            if _pd:
                dates, srcs = [_pd], {"real"}
        # 「지남」은 사유·확인방법을 같이 — 숫자만으론 뭘 해야 할지 알 수 없다.
        _rc = next((e.get("reason") for e in evs if e.get("reason")), "")
        _rt = SP.reason_text(_rc, ln["market"]) if _rc else {"뜻": "", "확인": ""}
        _dover = max([e.get("days_over") or 0 for e in evs] or [0])
        rows_out.append({
            "주문번호": row.get("오픈마켓주문번호") or "",
            "주문일": str(row.get("주문일") or "")[:10],
            "상품명": row.get("상품명") or "",
            "옵션": row.get("옵션") or "",
            "수량": row.get("수량") or "",
            "주문상태": row.get("주문상태") or "",
            # 🔴 [2026-08-12 노션 c-1] 마켓 정산 화면과 한 건씩 맞대 보려면 「누구에게 간
            #   주문인가」가 있어야 한다. 주문 내역 표와 **같은 수준**으로 그대로 준다
            #   (그 표도 수령자를 가리지 않는다 — 두 화면이 다르면 대조가 안 된다).
            "수령자": row.get("수령자") or "",
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
            "사유코드": _rc,
            "사유": _rt["뜻"],
            "확인방법": _rt["확인"],
            "지난일수": _dover,
        })
        if len(rows_out) >= 2000:      # 화면 보호 상한 — 잘림을 숨기지 않는다
            truncated = True
            break
    if want_orders:
        # 🔴 「달라고 한 주문 중 못 준 것」을 숨기지 않는다. 마켓 명세엔 있는데 우리에 없는
        #   주문이 바로 대조의 알맹이인데, 조용히 빠지면 「차이 0건」이 거짓말이 된다.
        #   못 준 사유는 셋 중 하나 — 저장분에 아예 없음 / `excluded` 부류 / 정산액 0·공란.
        got = {str(r_["주문번호"]) for r_ in rows_out}
        return jsonify(rows=rows_out, truncated=truncated,
                       요청주문수=len(want_orders), 찾은주문수=len(got),
                       못찾은주문=sorted(want_orders - got))
    return jsonify(rows=rows_out, truncated=truncated)


def _settle_plan_detail_order(SP, market, account, bucket, unit):
    """주문일 축 드릴다운 — 그 기간 칸에 들어간 주문 목록(매출액 + 정산예정금).

    🔴 「매출액을 실결제금액 대신 상품금액+배송비로 **대체**」한 줄은 목록에도 그 사실을
      적는다. 지금까지는 집계 meta 에 건수만 있어, 어느 주문이 대체됐는지 알 수 없었다.
    """
    rows_out, truncated = [], False
    for ln in _settle_plan_lines([market] if market else None):
        if account and (ln.get("account") or "") != account:
            continue
        hit = SP.order_axis_row(ln, unit=unit)
        if hit is None:
            continue
        if bucket and hit["bucket"] != bucket:
            continue
        row = ln["row"]
        rows_out.append({
            "주문번호": row.get("오픈마켓주문번호") or "",
            "주문일": hit["주문일"],
            "상품명": row.get("상품명") or "",
            "옵션": row.get("옵션") or "",
            "수량": row.get("수량") or "",
            "주문상태": row.get("주문상태") or "",
            "수령자": row.get("수령자") or "",
            "account": ln.get("account") or "",
            "market": ln["market"],
            "매출액": hit["revenue"],
            "매출액대체": hit["substituted"],
            "총정산예정": hit["settle"],
            "_settle_source": hit["settle_source"],
            "bucket": hit["bucket"],
        })
        if len(rows_out) >= 2000:      # 화면 보호 상한 — 잘림을 숨기지 않는다
            truncated = True
            break
    rows_out.sort(key=lambda r: (r["주문일"], r["주문번호"]), reverse=True)
    return jsonify(rows=rows_out, truncated=truncated, axis='order')


#: 내보내기·목록이 함께 쓰는 부류 이름 — 한 곳에서만 정의(둘이 갈리면 조용히 어긋난다)
_SP_CATEGORIES = ("confirmed", "unconfirmed", "overdue", "not_started", "undated",
                  # 🔴 [2026-08-13] returned = 반품·교환이 **끝난** 주문. 받을 돈에서
                  #   빼되 숨기지 않는다(반품비만 총액에 남는다).
                  "assumed_paid", "risk", "returned", "paid")
_SP_CAT_KO = {"confirmed": "확정예정", "unconfirmed": "미확정예정",
              "overdue": "입금일지남", "not_started": "정산시작전",
              "undated": "받는날미정",
              "assumed_paid": "이미받았을것", "risk": "반품취소진행",
              "returned": "반품교환완료", "paid": "이미받음"}


@bp.route('/api/settle-plan/export.xlsx')
def settle_plan_export():
    """부류별 주문 전건을 엑셀로 — 화면 목록은 2,000건에서 잘린다.

    🔴 왜 필요한가(2026-08-06 라이브) — 「이미 받은 것 3.52억」·「받았을 것 1.52억」이
      둘 다 2,000건 상한에 걸려, 사장님이 통장과 대조하려 해도 일부만 볼 수 있었다.
      내보내기는 **상한 없이** 전건을 준다(집계와 같은 판정 SP.resolve 사용).
    """
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules
    from lemouton.margin.sell_source import _settlement_for
    category = (request.args.get('category') or '').strip()
    if category not in _SP_CATEGORIES:
        return jsonify(ok=False,
                       error=f"모르는 부류예요: {category or '(빈값)'}"), 400
    market = (request.args.get('market') or '').strip()
    rules = load_rules()
    today = _dt.date.today()
    out = []
    for ln in _settle_plan_lines([market] if market else None):
        r = SP.resolve(ln, rules, today=today)
        cat = r["category"]
        if cat == "excluded":
            continue
        amount, src = _settlement_for(ln["row"])
        if not amount:
            continue
        evs = r["events"]
        if category in ("risk", "paid"):
            if cat != category:
                continue
        else:
            evs = [e for e in evs if e.get("bucket") == category]
            if not evs:
                continue
        row = ln["row"]
        ship = _settle_ship_part(row)
        part = sum(e["amount"] for e in evs) if evs else amount
        is_part = bool(evs) and part != amount
        rc = next((e.get("reason") for e in evs if e.get("reason")), "")
        rt = SP.reason_text(rc, ln["market"]) if rc else {"뜻": "", "확인": ""}
        dates = [e["date"] for e in evs if e["date"]]
        if cat == "paid":
            pd = SP._norm_date(row.get("_settle_paid_date"))
            if pd:
                dates = [pd]
        out.append({
            "부류": _SP_CAT_KO.get(category, category),
            "받는날": " · ".join(dates),
            "마켓": SP._MK_KO.get(ln["market"], ln["market"]),
            "계정": ln.get("account") or "",
            "주문번호": row.get("오픈마켓주문번호") or "",
            "주문일": str(row.get("주문일") or "")[:10],
            "상품명": row.get("상품명") or "",
            "옵션": row.get("옵션") or "",
            "수량": row.get("수량") or "",
            "주문상태": row.get("주문상태") or "",
            "상품정산예정": "" if is_part else amount - ship,
            "배송비정산예정": "" if is_part else ship,
            "총정산예정": part,
            "나눠받는조각": "예" if is_part else "",
            "근거": "실측" if all(e.get("date_source") == "real" for e in evs) and evs
                    else ("추정" if evs else ""),
            "왜안들어왔나": rt["뜻"],
            "확인방법": rt["확인"],
        })
    xlsx = _oe.rows_to_xlsx(out, columns=list(out[0].keys()) if out else None)
    fname = (f"정산예정_{_SP_CAT_KO.get(category, category)}_"
             f"{_dt.datetime.now(_oe.KST).strftime('%Y%m%d_%H%M')}.xlsx")
    return send_file(
        _io.BytesIO(xlsx), as_attachment=True, download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
        # 💰 셀러월렛 미인출 잔액 — 이미 사장님 돈인데 아직 안 찾아간 돈.
        #   인출해야 회차에서 공제되므로 그 전까지 「받을 돈」이 그만큼 부푼다(Wing 실측 811만).
        #   셀러월렛은 별도 시스템이라 읽을 API 가 없어 손으로 적는다. 정제는 load_rules 가 한다
        #   (숫자 아님·음수·모르는 마켓은 버림 — 근거 없이 총액을 깎지 않으려고).
        wb = body.get("wallet_balance")
        if wb is not None:
            if not isinstance(wb, dict):
                return jsonify(ok=False, error="wallet_balance 형식 오류"), 400
            rules["wallet_balance"] = wb
        save_rules(rules)
        return jsonify(ok=True, rules=load_rules())
    rules = load_rules()
    lines = _settle_plan_lines()
    # 빠른정산 계정을 손으로 적으면 오타가 조용히 안 걸린다 — 실제 등록 계정 목록을 준다.
    #  한 마켓의 키가 없어도 나머지는 보여준다(전체 실패로 규칙 창을 못 열면 손해).
    accounts = {}
    for mk in DEFAULT_RULES["markets"]:
        try:
            accounts[mk] = [nm for _prefix, nm in (_oe._active_accounts(mk) or []) if nm]
        except Exception:   # noqa: BLE001 — 계정 열거 실패는 규칙 화면을 막지 않는다
            accounts[mk] = []
    return jsonify(rules=rules, accounts=accounts,
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


@bp.route('/diag/esm-delivery-settle')
def orders_diag_esm_delivery_settle():
    """[읽기 전용] 옥션·G마켓 **배송비 정산조회**(getsettledeliveryfee, 지도 esm:42) 원본.

    왜 필요한가(2026-08-13) — 우리는 이 창구를 **한 번도 안 불렀다**
    (`shared/platforms/__init__.py` 에 경로만 「후속」으로 적혀 있고 호출부 0곳).
    그래서 두 가지가 통째로 빈다:
      ① 배송비 정산 **실값** — N열(`정산예정금(배송비포함)`)이 고객배송비를 **전액** 더한다.
         쿠팡은 실값(`_ship_settle`)을 쓰는데 ESM 만 옛 폴백이라, ESM 은 배송비 수수료
         (`DelFeeCommission`)만큼 상시 과대일 수 있다 — 그게 사실인지 눈으로 본다.
      ② **반품·교환 배송비** — 지도 `DelFeeType` 코드표에 40 반품배송비 / 50 추가반품배송비
         / 60 무료반품배송비 / 70 교환배송비 가 있다. 사장님 확정(2026-08-13)
         「반품완료여도 반품·교환 배송비는 우리가 받는다」의 **실값 창구**가 바로 여기다.

    `?market=gmarket&from=YYYY-MM-DD&to=YYYY-MM-DD&srch=D1,D3,D6&alias=`
      · SrchType(지도 esm:42): D1 입금확인일 · D3 매출마감일 · D6 송금일 · D7 환불일
        · D8 입금확인일+환불일 · D10 글로벌셀러 예치금 송금일 (D4·D5 는 **없다**)
      · 🔴 당일·미래 날짜로 조회하면 Error 414 — 어제까지로 물어야 한다(지도 코드표).
    응답은 금액·날짜·배송비번호뿐 — 고객정보는 담지 않는다.
    """
    from flask import jsonify
    from collections import Counter
    market = (request.args.get('market') or 'gmarket').strip()
    if market not in ('gmarket', 'auction'):
        return jsonify(ok=False, error='옥션·G마켓 전용이에요.'), 400
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    srchs = [s.strip().upper() for s in (request.args.get('srch') or 'D1').split(',')
             if s.strip()]
    alias = (request.args.get('alias') or '').strip()
    try:
        rows_cap = max(1, min(int(request.args.get('rows') or 500), 500))
    except (TypeError, ValueError):
        rows_cap = 500
    try:
        sample = max(0, min(int(request.args.get('sample') or 5), 40))
    except (TypeError, ValueError):
        sample = 5
    site = 'G' if market == 'gmarket' else 'A'
    path = "/account/v1/settle/getsettledeliveryfee"

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    out, errors = {}, {}
    for srch in srchs:
        try:
            cli = _client_for_diag(market, alias)
            if cli is None:
                errors[srch] = "계정 클라이언트 없음(키 미등록)"
                continue
            resp = cli.post(path, {"SiteType": site, "SrchType": srch,
                                   "SrchStartDate": f"{since:%Y-%m-%d}",
                                   "SrchEndDate": f"{until:%Y-%m-%d}",
                                   "PageNo": 1, "PageRowCnt": rows_cap}) or {}
        except Exception as e:   # noqa: BLE001 — 기준일 하나가 막혀도 나머지는 보여준다
            errors[srch] = f"{type(e).__name__}: {str(e)[:300]}"
            continue
        data = resp.get("Data") or []
        # 배송비 유형별로 나눠 본다 — 「원배송비」와 「반품·교환배송비」는 뜻이 완전히 다르다.
        by_type: dict = {}
        for r in data:
            t = str(r.get("DelFeeType") or "")
            e = by_type.setdefault(t, {"건수": 0, "DelFeeAmt합": 0.0,
                                       "DelFeeCommission합": 0.0})
            e["건수"] += 1
            e["DelFeeAmt합"] += _f(r.get("DelFeeAmt"))
            e["DelFeeCommission합"] += _f(r.get("DelFeeCommission"))
        out[srch] = {
            "ResultCode": resp.get("ResultCode"),
            "Message": resp.get("Message"),
            "TotalCount": resp.get("TotalCount"),
            "TotalDelFeeAmt": resp.get("TotalDelFeeAmt"),
            "받은행수": len(data),
            "유형별": by_type,
            "Kind분포": dict(Counter(str(r.get("Kind")) for r in data)),
            "합_DelFeeAmt": round(sum(_f(r.get("DelFeeAmt")) for r in data), 2),
            "합_DelFeeCommission": round(sum(_f(r.get("DelFeeCommission"))
                                             for r in data), 2),
            "표본": data[:sample],
        }
    return jsonify(ok=True, market=market, alias=alias or "(대표)", path=path,
                   기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   결과=out, 실패=errors)


@bp.route('/diag/esm-order-raw')
def orders_diag_esm_order_raw():
    """[읽기 전용] 옥션·G마켓 주문조회 raw 금액 필드 — 판매자 할인을 잴 수 있나.

    왜 필요한가(2026-08-06) — 이 두 마켓은 `_finalize_rows` 의 `force_orig` 가
    `실결제금액`을 원금(단가×수량+옵션)으로 **덮어써서**, 화면의 「마켓 할인」이
    구조적으로 늘 0 이다. 「할인이 없어서 0」인지 「덮어써서 0」인지 가르려면
    **마켓이 실제로 준 값**을 봐야 한다(원문 안 보고 「필드가 없다」고 단정 금지).

    지도(esm 주문조회) 확정 필드:
      · `SalePrice`   주문 시점 연동된 판매가
      · `ContrAmount` 수량
      · `OptSelPrice` / `OptAddPrice` 옵션단가·추가구성단가(×수량)
      · `ShippingFee` 배송비
      · `OrderAmount` G마켓=(판매단가×수량) / 옥션=(판매단가×수량) − **사이트 할인금액**
      · `AcntMoney`   (판매단가×수량)+옵션가 − **판매자 할인금액 총액** − 판매자 지급
                      스마일캐시 − 사이트 할인금액 + 배송비
        ⚠️ 배송비는 **장바구니 합계**로 내려온다(G마켓은 1개 주문번호에만, 옥션은 모든
           주문번호에 같은 합계). 그래서 줄 단위 역산이 어긋날 수 있다 — 그걸 확인하는 게
           이 창구의 목적이다.

    `?market=auction&orders=번호,번호` — **이 길을 쓴다.** 주문번호당 1회 호출이라 빠르다.
    `?market=auction&days=14&limit=40&alias=` — 기간 훑기(느림).
      🔴 ESM 주문조회는 **5초당 1회** 제한이라(ResultCode=3000) 기간이 넓으면
         Cloudflare 100초 벽에 걸려 524 로 끊긴다(2026-08-06 실측: days=3 도 못 넘김).
         그래서 실측은 `orders=` 로 한다.
    응답은 금액·수량·주문번호뿐 — 고객정보(이름·전화·주소)는 담지 않는다.
    """
    from flask import jsonify
    market = (request.args.get('market') or 'auction').strip()
    if market not in ('gmarket', 'auction'):
        return jsonify(ok=False, error='옥션·G마켓 전용이에요.'), 400
    try:
        days = max(1, min(int(request.args.get('days') or 14), 60))
    except (TypeError, ValueError):
        days = 14
    try:
        limit = max(1, min(int(request.args.get('limit') or 40), 200))
    except (TypeError, ValueError):
        limit = 40
    alias = (request.args.get('alias') or '').strip()
    until = _dt.datetime.now(_oe.KST)
    since = until - _dt.timedelta(days=days)

    from shared.platforms.esm import orders as _eo
    #  담을 필드만 화이트리스트 — 실수로 고객정보가 새지 않게 「빼기」가 아니라 「고르기」.
    #  [2026-08-12] 할인 부담 갈래 — 지도에 있는데 우리가 안 읽던 필드.
    #    SellerDiscountPrice(판매자할인 1+2 최종) · DirectDiscountPrice(사이트 지원 할인).
    #    「G마켓은 구조적 불가」로 적었던 앞선 결론은 이 둘을 못 보고 내린 오판이었다.
    _KEEP = ("OrderNo", "GoodsName", "SalePrice", "ContrAmount", "OptSelPrice",
             "OptAddPrice", "ShippingFee", "OrderAmount", "AcntMoney", "OrderStatus",
             "SellerDiscountPrice", "SellerDiscountPrice1", "SellerDiscountPrice2",
             "DirectDiscountPrice")
    want = [o.strip() for o in (request.args.get('orders') or '').split(',') if o.strip()]
    rows, keys_seen = [], set()
    # 🔴 어느 계정으로 물었는지 **응답에 적는다** — 별칭이 안 맞아 대표로 폴백하면
    #   「0건」이 돌아오는데, 그걸 「그 주문이 없다」로 오독하게 된다
    #   (2026-08-06 실측: 옥션 2건이 0건으로 나와 한참 헤맴).
    쓴계정 = None
    try:
        for _p, _n in (_oe._active_accounts(market) or []):
            if not alias or str(_n) == str(alias) or str(_n).split('(')[0].strip() == alias:
                쓴계정 = {"prefix": _p, "name": _n}
                break
    except Exception:   # noqa: BLE001 — 진단 부가정보라 실패해도 본 조회는 계속
        쓴계정 = None
    try:
        cli = _client_for_diag(market, alias)
        if want:
            # 주문번호 조회는 **호출 제한이 없다**(공식문서 etapi.gmarket.com/67:
            #   "주문조회는 5초당 1회. 단, 주문번호로 조회하는 경우 제한 없습니다").
            #   기간 훑기는 그 제한에 걸려 Cloudflare 100초 벽에서 524 로 끊긴다.
            #   반환은 (행, 실패사유) 튜플이다 — 사유도 같이 보여 준다(삼키지 않는다).
            for no in want[:limit]:
                od, 사유 = _eo.fetch_by_order_no(market, no, client=cli)
                if od is None:
                    rows.append({"OrderNo": no, "_실패사유": 사유})
                    continue
                keys_seen |= set(od.keys())
                rows.append({k: od.get(k) for k in _KEEP})
        else:
            for od in _eo.iter_orders(market, since, until, client=cli):
                keys_seen |= set(od.keys())
                rows.append({k: od.get(k) for k in _KEEP})
                if len(rows) >= limit:
                    break
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 400

    def _num(v):
        try:
            return round(float(str(v).replace(",", "")))
        except (TypeError, ValueError):
            return None

    # 「판매자 할인이 실제로 잡히나」를 그 자리에서 계산해 보여 준다(눈으로 판정용).
    for r in rows:
        u, q = _num(r.get("SalePrice")), _num(r.get("ContrAmount")) or 1
        opt = (_num(r.get("OptSelPrice")) or 0) + (_num(r.get("OptAddPrice")) or 0)
        ship, oa, am = _num(r.get("ShippingFee")) or 0, _num(r.get("OrderAmount")), _num(r.get("AcntMoney"))
        정가 = (u * q + opt) if u is not None else None
        r["_정가"] = 정가
        # 옥션만: 사이트할인 = 판매단가×수량 − OrderAmount
        r["_사이트할인"] = (u * q - oa) if (market == "auction" and u is not None and oa is not None) else None
        # 판매자부담(할인+스마일캐시) = 옵션가 + OrderAmount + 배송비 − AcntMoney  (옥션 전용 유도)
        r["_판매자부담_추정"] = ((opt + oa + ship - am)
                                if (market == "auction" and oa is not None and am is not None) else None)
        r["_정가와AcntMoney차"] = ((정가 + ship - am) if (정가 is not None and am is not None) else None)
    깎인건 = [r for r in rows if (r.get("_정가와AcntMoney차") or 0) > 0]
    return jsonify(ok=True, market=market, alias=alias or "(대표)", days=days,
                   쓴계정=쓴계정,
                   등록계정=[n for _p, n in (_oe._active_accounts(market) or [])],
                   조회건수=len(rows),
                   깎인건수=len(깎인건),
                   응답에_있던_필드=sorted(keys_seen),
                   행=rows)


@bp.route('/diag/coupang-settle-hist')
def orders_diag_coupang_settle_hist():
    """[읽기 전용] 쿠팡 지급내역조회 raw — 「입금됐나」를 판정하는 원본을 눈으로.

    왜 필요한가(2026-08-06) — 이 API 는 문서 예시와 **응답 모양이 달랐다**(배열 그대로).
    라이브에서 8계정 전부 실패한 뒤에야 드러났다. 다음에 또 어긋나면 여기서 바로 본다.

    `?ym=YYYY-MM&alias=` — 응답 타입·키 목록·회차 샘플(금액·상태·구간)만. 계좌·예금주 등
    개인정보 필드는 담지 않는다.
    """
    from shared.platforms.coupang import settlements as _cs
    ym = (request.args.get('ym') or _dt.date.today().strftime('%Y-%m')).strip()
    alias = (request.args.get('alias') or '').strip()
    try:
        # 진단은 조회만 — 별칭 퍼지 매칭(정확매칭이면 다계정이 대표로 폴백돼 0건이 된다)
        cli = _client_for_diag('coupang', alias)
        raw = cli.request(
            method="GET",
            path=_cs.COUPANG["paths"]["settlement_histories"],
            query=(f"vendorId={(getattr(cli, '_cfg', {}) or {}).get('vendor_id') or ''}"
                   f"&revenueRecognitionYearMonth={ym}"))
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, ym=ym, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    rows = raw if isinstance(raw, list) else ((raw or {}).get('data') or [])
    keys = sorted({k for r in rows[:5] if isinstance(r, dict) for k in r})
    safe = [{k: r.get(k) for k in
             ('settlementType', 'status', 'settlementDate',
              'revenueRecognitionDateFrom', 'revenueRecognitionDateTo',
              # 🔴 2026-08-06 Wing 실측 — finalAmount(통장 입금액)만 보면 빠른정산 쓴 계정이
              #   「우리가 4배 부풀었다」로 오독된다. 대조 상대는 settlementTargetAmount.
              'totalSale', 'settlementTargetAmount', 'settlementAmount',
              'pendingReleasedAmount', 'deductionAmount', 'sellerServiceFee',
              'dedicatedDeliveryAmount', 'debtOfLastWeek', 'couranteeFee',
              'sellerDiscountCoupon', 'finalAmount')}
            for r in rows[:10] if isinstance(r, dict)]
    return jsonify(ok=True, ym=ym, alias=alias or '(대표)',
                   응답타입=type(raw).__name__, 회차수=len(rows),
                   키목록=keys, 샘플=safe,
                   파싱결과=_cs.fetch_settlement_histories(ym, client=cli)[:5])


@bp.route('/diag/coupang-settle-parity')
def orders_diag_coupang_settle_parity():
    """[읽기 전용] 쿠팡 — 「우리가 받을 거라 계산한 돈」 vs 「실제로 준 돈」 대조.

    🔴 왜(2026-08-06 사장님: "이걸 놓치면 엄청난 정산 금액 차이") — 우리 화면 금액은
      주문별 정산액이다. 마켓이 인정한 **정산대상액**과 같은지 스스로 검산할 창구가 없었다.

    🔴 대조 상대를 한 번 갈아탔다 — 처음엔 회차 finalAmount(통장 입금액)와 맞댔더니
      세소 6월이 861만(77%) 벌어졌다. Wing 화면 실측 결과 원인은 우리 계산이 아니라
      **빠른정산 선인출**(2,916,626 을 7/14 에 미리 받아 회차에서 공제)이었다.
      정산대상액 11,081,786 vs 우리 계산 11,131,180 = **0.44% 차, 우리가 맞았다.**

    `?ym=YYYY-MM&alias=` — 매출인식월 기준. 금액·건수만 반환(고객정보 없음).
    """
    from lemouton.margin import settle_parity as _sp
    from lemouton.margin.sell_source import _settlement_for
    from shared.platforms.coupang import settlements as _cs
    ym = (request.args.get('ym') or _dt.date.today().strftime('%Y-%m')).strip()
    alias = (request.args.get('alias') or '').strip()
    try:
        cli = _client_for_diag('coupang', alias)
        hist = _cs.fetch_settlement_histories(ym, client=cli)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, ym=ym, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    # 우리 저장분 — 인식일이 있는 쿠팡 행만(그게 대조 키다)
    ours = []
    for ln in _settle_plan_lines(["coupang"]):
        if alias and (ln.get("account") or "") != alias:
            continue
        row = ln["row"]
        rec = str(row.get("_recognition_date") or "")[:10]
        if not rec:
            continue
        amt, _src = _settlement_for(row)
        if not amt:
            continue
        ours.append({"주문번호": row.get("오픈마켓주문번호") or "",
                     "_recognition_date": rec, "정산액": amt})
    res = _sp.compare(hist, ours)
    return jsonify(ok=True, ym=ym, alias=alias or '(대표)',
                   회차수=len(hist), 저장분_인식일있는건수=len(ours), **res)


@bp.route('/diag/coupang-rg')
def orders_diag_coupang_rg():
    """[읽기 전용] 로켓그로스 주문 raw — 매출이 실제로 있나·정산은 어디에 잡히나.

    왜 필요한가(2026-08-06 사장님 지적) — 로켓그로스는 **별도 창구**라 우리가 안 불렀고,
    그래서 주문내역·정산예정금액에 한 건도 없었다. 이 API 는 판매가·수량만 주고
    **정산액은 안 준다** — 정산이 마켓플레이스 매출내역(revenue-history)에 같이 잡히는지
    여기서 확인한 뒤에야 금액을 정할 수 있다(추정 금지).

    `?from=YYYY-MM-DD&to=YYYY-MM-DD&alias=` — 계정별. 응답은 건수·금액·표본뿐(고객정보 없음).
    """
    from shared.platforms.coupang import rocket_growth as _rg
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    alias = (request.args.get('alias') or '').strip()
    raw_head = None
    try:
        cli = _client_for_diag('coupang', alias)
        # 🔴 0건이 「정말 없음」인지 「권한 없어 조용히 빈 응답」인지 갈라야 한다
        #   (11번가가 창 초과를 에러 없이 0건으로 주던 부류). raw 머리를 그대로 보여준다.
        try:
            _p = _rg.COUPANG["paths"]["rg_orders"].format(
                vendorId=(getattr(cli, "_cfg", {}) or {}).get("vendor_id") or "")
            _q = (f"vendorId={(getattr(cli, '_cfg', {}) or {}).get('vendor_id') or ''}"
                  f"&paidDateFrom={since:%Y%m%d}&paidDateTo={until:%Y%m%d}&nextToken=")
            _raw = cli.request(method="GET", path=_p, query=_q)
            raw_head = ({"타입": type(_raw).__name__, "길이": len(_raw)}
                        if isinstance(_raw, list)
                        else {"타입": type(_raw).__name__,
                              "code": (_raw or {}).get("code"),
                              "message": str((_raw or {}).get("message") or "")[:120],
                              "키": sorted((_raw or {}).keys())[:12],
                              "data길이": len((_raw or {}).get("data") or [])})
            # 🔴 [2026-08-06] 세소 계정에 data 50건이 있는데 우리 파서는 0건이었다 —
            #   응답 필드명이 문서와 다른 것. **키 이름만** 보여준다(값은 고객정보 위험).
            _lst = _raw if isinstance(_raw, list) else ((_raw or {}).get("data") or [])
            _f = _lst[0] if _lst and isinstance(_lst[0], dict) else None
            if _f:
                raw_head["첫주문_키"] = sorted(_f.keys())
                for _ik in ("orderItems", "items", "orderItemList", "rgOrderItems"):
                    _it = _f.get(_ik)
                    if isinstance(_it, list) and _it and isinstance(_it[0], dict):
                        raw_head["항목배열이름"] = _ik
                        raw_head["첫항목_키"] = sorted(_it[0].keys())
                        break
        except Exception as e:   # noqa: BLE001 — raw 확인 실패해도 본 조회는 시도
            raw_head = {"확인실패": f"{type(e).__name__}: {str(e)[:160]}"}
        rows = _rg.fetch_rg_orders(since.strftime('%Y-%m-%d'), until.strftime('%Y-%m-%d'),
                                   client=cli)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, alias=alias or '(대표)',
                       error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    oids = sorted({r['주문번호'] for r in rows})
    # 그 주문번호가 마켓플레이스 매출내역에도 잡히나 — 정산 원천을 가르는 결정적 확인
    hit = []
    try:
        imap, _dv, _dt2 = _oe._coupang_settle_map(since, until, cli)
        keys = {str(k[0]) for k in imap}
        hit = [o for o in oids if o in keys][:5]
    except Exception as e:   # noqa: BLE001 — 매출내역이 막혀도 주문 결과는 보여준다
        hit = [f"확인실패: {type(e).__name__}"]
    return jsonify(ok=True, alias=alias or '(대표)',
                   기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   원본머리=raw_head,
                   주문수=len(oids), 옵션행수=len(rows),
                   상품금액합=sum(r['상품금액'] for r in rows),
                   표본=rows[:5],
                   매출내역에도_있는_주문=hit,
                   해석=('매출내역에 있으면 정산이 통합 → 기존 경로로 정산액 확보 가능. '
                         '없으면 로켓그로스 정산은 별도라 금액 산출 방법을 따로 정해야 함'))


@bp.route('/diag/coupang-order-settle')
def orders_diag_coupang_order_settle():
    """[읽기 전용] 쿠팡 — **주문번호로** 정산 원본을 본다(`orders=`).

    왜 필요한가 (2026-08-13):
      ① 배송비 판정의 결정적 근거 — 쿠팡 자기 정산 엑셀은 배송료를 독립 행으로 주고
         3.3% 수수료를 뗀다(4,000→3,868). 우리가 API 로 받는
         `deliveryFee.settlementAmount` 가 **그 값과 같은지**를 눈으로 대조해야
         「실값을 쓴다」는 판단이 근거를 갖는다.
      ② 「엑셀엔 있는데 우리에 없는 31건」이 취소인지·조회창 밖인지·진짜 누락인지.
         쿠팡만 `orders=` 진단 창구가 없어 여태 못 좁혔다(ESM·옥션·스스·롯데온은 있다).

    `?from=YYYY-MM-DD&to=YYYY-MM-DD&orders=번호,번호&alias=`
      · 창은 **매출인식일** 기준(revenue-history 규약). 25일 창으로 쪼개 순회한다.
      · orders 를 주면 그 주문만. 안 주면 창 전체 요약(표본만).
      · 응답은 금액·날짜·식별자뿐 — 고객정보는 담지 않는다.
    """
    from flask import jsonify

    from shared.platforms.coupang.settlements import fetch_revenue_page
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    want = {o.strip() for o in (request.args.get('orders') or '').split(',') if o.strip()}
    alias = (request.args.get('alias') or '').strip()
    try:
        cli = _client_for_diag('coupang', alias)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500

    by_order: dict = {}
    errors: list = []
    seen_orders = 0
    # 🔴 revenue-history 는 "1개월 미만" 제약이 있다 — order_export 와 **같은** 25일 창을
    #   쓴다(여기만 30일로 두면 진단이 HTTP 400 으로 조용히 0건이 된다).
    for _w0, _w1 in _oe._cp_windows(since, until, days=25):
        rec_from = _w0.strftime('%Y-%m-%d')
        rec_to = (_w1 - _dt.timedelta(days=1)).strftime('%Y-%m-%d')
        if rec_from > rec_to:      # 꼬리 창(뒤집힘) — 앞 창이 이미 덮는다
            continue
        token = ''
        for _ in range(200):       # 페이징 안전 상한(빌더와 동일)
            try:
                resp = fetch_revenue_page(rec_from, rec_to, token=token,
                                          max_per_page=50, client=cli)
            except Exception as e:   # noqa: BLE001 — 한 창이 막혀도 나머지는 본다
                errors.append(f"{rec_from}~{rec_to}: {type(e).__name__}: {str(e)[:150]}")
                break
            for order in (resp.get('data') or []):
                seen_orders += 1
                oid = str(order.get('orderId') or '')
                if want and oid not in want:
                    continue
                ent = by_order.setdefault(oid, {
                    '상품정산합': 0, '배송비정산': 0, '행수': 0, '구간': []})
                _sale = order.get('saleType')
                _sign = -1 if _sale == 'REFUND' else 1
                _d = (order.get('deliveryFee') or {}).get('settlementAmount')
                # 🔴 부호 규칙은 빌더와 같아야 한다(order_export._coupang_settle_map):
                #   deliveryFee 는 REFUND 에서 **이미 음수**, items 는 양수라 부호를 준다.
                if _d is not None:
                    try:
                        ent['배송비정산'] += int(_d)
                    except (TypeError, ValueError):
                        pass
                for it in (order.get('items') or []):
                    try:
                        ent['상품정산합'] += _sign * int(it.get('settlementAmount') or 0)
                    except (TypeError, ValueError):
                        pass
                    ent['행수'] += 1
                ent['구간'].append({
                    'saleType': _sale,
                    '매출인식일': str(order.get('recognitionDate') or '')[:10],
                    '정산예정일': str(order.get('settlementDate') or '')[:10],
                    '최종정산일': str(order.get('finalSettlementDate') or '')[:10],
                    'deliveryFee_settlementAmount': _d,
                    '조회창': f"{rec_from}~{rec_to}",
                })
            if not resp.get('hasNext'):
                break
            token = resp.get('nextToken') or ''
            if not token:
                break

    for ent in by_order.values():
        ent['총정산'] = ent['상품정산합'] + ent['배송비정산']
    missing = sorted(want - set(by_order)) if want else []
    return jsonify(
        ok=True, alias=alias or '(대표)',
        기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}(매출인식일)",
        요청주문수=len(want), 찾은주문수=len(by_order), 창안_전체주문수=seen_orders,
        # ② 의 출발점 — 「이 창에서 못 찾은 주문」. 창을 넓혀 다시 부르면 취소·기간밖이 갈린다.
        못찾은주문=missing,
        합계={'상품정산합': sum(e['상품정산합'] for e in by_order.values()),
              '배송비정산합': sum(e['배송비정산'] for e in by_order.values()),
              '총정산합': sum(e['총정산'] for e in by_order.values())},
        주문별=(by_order if want else dict(list(by_order.items())[:5])),
        오류=errors,
        해석=('배송비정산 = deliveryFee.settlementAmount(총배송비 − 배송비수수료 − VAT). '
              '쿠팡 정산 엑셀의 <기본배송료>·<추가배송료> 행 정산금액 합과 같아야 한다. '
              '같으면 N열(정산예정금(배송비포함))이 이 실값을 쓰는 것이 옳다는 증거.'))


@bp.route('/diag/rg-rounds')
def orders_diag_rg_rounds():
    """[읽기 전용] 로켓그로스 회차 표 — Wing 화면과 **같은 표로** 맞대려고.

    🔴 왜(2026-08-13 사장님 지적) — 화면 「지급 예상금액」이 우리 숫자와 다르다.
      *"선정산 받은거 제외안해도돼? 내 생각엔 최종지급액 합산되어야하는거 아닌지?"*
      맞는 의심이다. 우리는 `받을돈 = 지급액 − 빠른정산` 으로 세는데, 화면 목록의
      열 이름은 **「최종지급액」**(`final_amount`)이다. 둘이 같은 것인지 **아직 증명된 적이
      없다** — 그래서 회차별로 나란히 놓고 봐야 한다.

    🔴 합계만 비교하면 「우연히 비슷」과 「정말 같음」을 못 가른다. 회차(정산일·비율)마다
      지급액·빠른정산·최종지급액을 다 보여준다.

    `?account=` — 계정 필터(선택). 응답은 금액·날짜뿐(고객정보 없음).
    """
    from lemouton.sourcing.models_v2 import RocketGrowthSettlement as M
    acc = (request.args.get('account') or '').strip()
    today = _dt.date.today().isoformat()
    s = SessionLocal()
    try:
        q = s.query(M)
        if acc:
            q = q.filter(M.account == acc)
        rows = sorted(q.all(), key=lambda o: (o.settlement_date or '', o.ratio or 0))
        out = [{
            '정산일': o.settlement_date or '', '지급비율': o.ratio,
            '매출인식일': f"{o.period_start or ''}~{o.period_end or ''}",
            '계정': o.account or '(대표)',
            '판매액': int(o.sales_amount or 0),
            '지급액': int(o.payable_amount or 0),
            '빠른정산_이미받음': int(o.fast_withdrawn or 0),
            '최종지급액': int(o.final_amount or 0),
            '정산일_지남': bool((o.settlement_date or '') and o.settlement_date <= today),
        } for o in rows]
        _pay = sum(r['지급액'] for r in out)
        _fast = sum(r['빠른정산_이미받음'] for r in out)
        _fin = sum(r['최종지급액'] for r in out)
        _future = [r for r in out if not r['정산일_지남']]
        return jsonify(
            ok=True, 오늘=today, 회차수=len(out), 계정=acc or '(전체)',
            합계={
                'Σ지급액': _pay,
                'Σ빠른정산_이미받음': _fast,
                '지급액−빠른정산 (지금 우리가 쓰는 값)': max(0, _pay - _fast),
                'Σ최종지급액 (화면 목록의 그 열)': _fin,
                'Σ최종지급액_오늘이후_정산일만 (노션 규칙)':
                    sum(r['최종지급액'] for r in _future),
                '오늘이후_회차수': len(_future),
            },
            회차별=out,
            해석=('화면 「지급 예상금액」이 위 넷 중 무엇과 같은지로 규칙이 정해진다. '
                  '같은 게 하나도 없으면 화면 숫자의 정의를 모르는 것이므로 '
                  '「대조 성공」이라 말하면 안 된다.'))
    finally:
        s.close()


@bp.route('/diag/stale-delivered')
def orders_diag_stale_delivered():
    """[진단·수동실행] 「배송완료」에 굳은 옛 주문 되살리기 — 왜 안 줄어드나 눈으로.

    🔴 왜 필요한가(2026-08-12) — 자동 틱을 얹은 지 4일인데 롯데온 미확정이 622→579건,
      43건밖에 안 줄었다. 3~4월 319건(1,792만)은 그대로다. 여기서 갈리는 가설이 셋인데
      **로그를 못 보면 어느 쪽인지 모른다**:
        ① 우리 틱이 아예 안 돈다        ② 되조회해도 마켓이 여전히 배송완료라 답한다
        ③ 오래된 주문이라 단건 조회에서 not_found 다
      ②·③ 이면 「우리가 낡은 것」이 아니라 **마켓 쪽 사실**이므로 되살리기를 아무리
      돌려도 안 줄어든다 — 그때는 다른 방법(정산 창구 조인)으로 가야 한다.

    `?market=lotteon&limit=50&dry=1`
      · `dry=1` — **마켓을 부르지 않고** 대상만 센다(월별 분포). 안전한 첫 걸음.
      · `dry=0` — 실제로 되조회하고 전이(moves)·not_found 를 그대로 돌려준다.
        자동 틱보다 크게 잡아 밀린 것을 한 번에 밀어낼 수도 있다.
    """
    from flask import jsonify

    from lemouton.markets.order_ingest import (_STALE_STATUSES,
                                               refresh_stale_delivered)
    market = (request.args.get('market') or 'lotteon').strip()
    try:
        limit = max(1, min(400, int(request.args.get('limit') or 50)))
    except ValueError:
        limit = 50
    min_age = int(request.args.get('min_age_days') or 30)
    max_age = int(request.args.get('max_age_days') or 180)
    dry = (request.args.get('dry') or '1') not in ('0', 'false', 'no')
    if dry:
        from shared.db import SessionLocal
        from lemouton.markets.models_orders import MarketOrderLine as L
        now = _dt.datetime.now(_oe.KST)
        newest = (now - _dt.timedelta(days=min_age)).strftime('%Y-%m-%d')
        oldest = (now - _dt.timedelta(days=max_age)).strftime('%Y-%m-%d')
        with SessionLocal() as s:
            rows = (s.query(L).filter(L.market == market,
                                      L.status.in_(_STALE_STATUSES),
                                      L.order_date >= oldest,
                                      L.order_date <= newest).all())
            by, tried = {}, 0
            for o in rows:
                k = (o.order_date or '?')[:7]
                by[k] = by.get(k, 0) + 1
                if (o.row or {}).get('_stalestat_tried_at'):
                    tried += 1
            return jsonify(ok=True, dry=True, market=market,
                           창=f'{oldest}~{newest}', 대상건수=len(rows),
                           월별=by, 이미시도한건수=tried,
                           주문번호수=len({o.order_no for o in rows}),
                           해석='이미시도한건수가 대상건수와 비슷한데 안 줄면 = 마켓이 '
                                '여전히 배송완료라고 답하는 것(우리 문제가 아님)')
    try:
        rep = refresh_stale_delivered(market, min_age_days=min_age,
                                      max_age_days=max_age, limit=limit)
    except Exception as e:                              # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f'{type(e).__name__}: {str(e)[:300]}'), 500
    return jsonify(ok=True, dry=False, market=market, **rep)


@bp.route('/diag/eleven11-settle')
def orders_diag_eleven11_settle():
    """[읽기 전용] 11번가 정산내역조회 raw — **어떤 필드가 실제로 오는지** 눈으로.

    🔴 왜 필요한가(2026-08-07) — 문서·지도에는 `stlDy`(정산일, [필수])가 있어 그걸
      「입금됐다」의 근거로 붙였는데, 라이브 스윕이 292건을 갱신하고도 **받은 날이 0건**이었다.
      즉 그 필드가 실제 응답에 없거나 빈 값이다. 문서만 보고 판단하면 이런 걸 못 잡는다.

    `?from=YYYY-MM-DD&to=YYYY-MM-DD&alias=` — 라인에 실린 태그 이름과 표본만.
    고객정보는 담지 않는다(금액·날짜 필드만).
    """
    from flask import jsonify
    since, until = _parse_range(request.args)
    if not since or not until:
        return jsonify(ok=False, error='from·to(YYYY-MM-DD)가 필요해요.'), 400
    alias = (request.args.get('alias') or '').strip()
    from shared.platforms.eleven11 import settlement as _el
    from shared.platforms.eleven11.orders import _localname, _parse
    cli = _client_for_diag('eleven11', alias)
    path = _el._PATH.format(s=since.strftime('%Y%m%d'), e=until.strftime('%Y%m%d'))
    try:
        xml_text = cli.request("GET", path)
    except Exception as e:   # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 500
    root = _parse(xml_text)
    keys, samples = set(), []
    if root is not None:
        for el in root.iter():
            ent = {_localname(c.tag): (c.text or "").strip() for c in el}
            if not ent.get("ordNo") or ent.get("stlAmt") in (None, "", "null"):
                continue
            keys.update(ent.keys())
            if len(samples) < 3:
                # 날짜·금액 필드만 — 고객정보는 담지 않는다
                samples.append({k: v for k, v in ent.items()
                                if any(t in k.lower() for t in
                                       ("dy", "dt", "amt", "fee", "no", "seq", "stat"))})
    return jsonify(ok=True, 기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   alias=alias or "(대표)", 라인키목록=sorted(keys),
                   stlDy_있나=("stlDy" in keys), stlPlnDy_있나=("stlPlnDy" in keys),
                   표본=samples, 원본머리=str(xml_text or "")[:400])


@bp.route('/diag/e11-seller-dc')
def orders_diag_e11_seller_dc():
    """[읽기 전용·마켓 안 부름] 11번가 판매자할인을 못 받은 주문이 얼마나 밀려 있나.

    🔴 왜 필요한가(2026-08-13) — 배송중·배송완료·구매확정 주문은 **목록조회가
      `sellerDscPrc` 를 아예 안 준다**(라이브 실측 150/157행). 그래서 그 행들의 매출이
      「정가 − 판매자할인」으로 못 넘어가고 옛 기준(실결제+배송비)에 머문다.
      회수는 단건조회(eleven11.110)로만 되는데 **주문당 1콜**이라, 한도를 정하려면
      백로그가 몇 건인지부터 세어야 한다. 이 창구는 저장분만 읽는다(마켓 호출 0).

    `?days=180` — 주문일 기준 창(최대 730).
    돌려주는 것: 대상 건수·주문번호 수·월별 분포·이미 시도한 건수·단가까지 빈 행 수.
      ★`정체불명금액` = Σ(총주문금액 − 실결제금액). 이 돈이 우리 부담인지 마켓 부담인지
        아직 모르는 몫이다 — 「할인 0원」이 아니라 「모름」이다.
    """
    from flask import jsonify

    from shared.db import SessionLocal
    from lemouton.markets.models_orders import MarketOrderLine as L

    try:
        days = max(1, min(730, int(request.args.get('days') or 180)))
    except ValueError:
        days = 180
    now = _dt.datetime.now(_oe.KST)
    oldest = (now - _dt.timedelta(days=days)).strftime('%Y-%m-%d')
    # 배송이 시작된 뒤 상태만 — 결제완료·배송준비중은 목록조회가 이미 할인을 준다.
    STS = ('배송중', '배송완료', '구매확정')

    def _i(v):
        try:
            return int(float(str(v).replace(',', '')))
        except (TypeError, ValueError):
            return 0

    with SessionLocal() as s:
        rows = (s.query(L).filter(L.market == 'eleven11',
                                  L.status.in_(STS),
                                  L.order_date >= oldest).all())
        by, tried, blank, gap, nos = {}, 0, 0, 0, set()
        for o in rows:
            r = o.row or {}
            if str(r.get('_dc_seller') or '').strip():
                continue                      # 이미 받아 둔 행
            k = (o.order_date or '?')[:7]
            by[k] = by.get(k, 0) + 1
            nos.add(o.order_no)
            if r.get('_dcfill_tried_at'):
                tried += 1
            if not str(r.get('단가') or '').strip():
                blank += 1                    # 단가가 없으면 회수해도 매출 기준이 안 바뀐다
            gap += _i(r.get('총주문금액')) - _i(r.get('실결제금액'))
        return jsonify(ok=True, 창=f'{oldest}~{now:%Y-%m-%d}',
                       조회한행=len(rows), 대상건수=sum(by.values()),
                       주문번호수=len(nos), 월별=dict(sorted(by.items())),
                       이미시도한건수=tried, 단가까지빈행=blank,
                       정체불명금액=gap,
                       안내='주문당 1콜 — 주문번호수가 곧 필요한 호출 수다.')


@bp.route('/diag/e11-order-raw')
def orders_diag_e11_order_raw():
    """[읽기 전용·저장 안 함] 11번가 단건조회(eleven11.110) 원본 필드 — 값이 오나 눈으로.

    🔴 왜 필요한가(2026-08-13) — 지도에 `sellerDscPrc` 가 있다는 것은 **「칸이 있다」**이지
      **「값이 온다」**가 아니다. 배송완료·구매확정 주문에서도 실값을 채워 주는지 확인하지
      않고 회수 스윕을 지으면, 못 구하는 주문을 계속 두드리기만 하는 코드가 된다.
      (같은 함정의 반대 방향 사고가 이미 있었다 — 「마켓이 안 준다」고 보고했는데 실은
       우리가 버리고 있던 건.)

    `?ordno=202608130001234&alias=` — 주문번호 하나. 금액·번호 계열 필드만 돌려준다
    (고객정보는 담지 않는다). 저장분에 아무것도 쓰지 않는다.
    """
    from flask import jsonify

    from shared.platforms.eleven11.orders import fetch_order

    ordno = (request.args.get('ordno') or '').strip()
    if not ordno:
        return jsonify(ok=False, error='ordno(주문번호)가 필요해요.'), 400
    alias = (request.args.get('alias') or '').strip()
    cli = _client_for_diag('eleven11', alias)
    try:
        ods = fetch_order(ordno, client=cli)
    except Exception as e:                    # noqa: BLE001 — 사유를 숨기지 않는다
        return jsonify(ok=False, error=f'{type(e).__name__}: {str(e)[:300]}'), 500
    # 관심 필드 — 할인 갈래 + 배송비(지도와 코드가 서로 다르게 말하는 자리) + 금액.
    WANT = ('sellerDscPrc', 'sellerDscPrcPerSeq', 'lstSellerDscPrc',
            'tmallDscPrc', 'tmallDscPrcPerSeq', 'tmallApplyDscAmt',
            'ordPayAmt', 'ordAmt', 'selPrc', 'ordQty',
            'dlvCst', 'lstDlvCst', 'bmDlvCst', 'bndlDlvYN',
            'ordPrdSeq', 'ordNo', 'ordPrdStat', 'ordPrdStatNm', 'stlPlnAmt')
    out = []
    for od in ods:
        out.append({k: od.get(k) for k in WANT if k in od})
    return jsonify(ok=True, ordno=ordno, alias=alias or '(대표)',
                   라인수=len(ods),
                   전체키목록=sorted({k for od in ods for k in od}),
                   sellerDscPrc_왔나=any(str(od.get('sellerDscPrc') or '').strip()
                                        for od in ods),
                   관심필드=out)


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
    _keys: set = set()          # 원본이 실제로 주는 필드 — 문서와 어긋날 때 여기서 본다
    _types: dict = {}           # settleType 분포(빠른정산/일반정산/공제…)
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
                    # ⚡ 2026-08-06 — 스스 빠른정산(도쿄산초메)은 **집화 +1영업일에 100% 선지급**
                    #   이다(쿠팡의 70/30 분할과 다름). 그 주문은 이미 받은 돈인데 우리 화면엔
                    #   「앞으로 받을 돈」으로 서 있다. 사장님이 보내주신 QuickSettleByCase 엑셀이
                    #   바로 이 API 의 산출물이라, settleType 만 읽으면 엑셀 없이 가려낼 수 있다.
                    'settleType': el.get('settleType'),
                    'settleDecisionType': el.get('settleDecisionType'),
                    'settleCompleteDate': el.get('settleCompleteDate'),
                    'searchDate': day.strftime('%Y-%m-%d'),
                })
                _keys.update(k for k in el)
                _t = str(el.get('settleType') or '(없음)')
                _b = _types.setdefault(_t, {'건수': 0, '금액': 0})
                _b['건수'] += 1
                _b['금액'] += int(amt or 0)
                if amt is not None:
                    by_order[oid]['합계'] += amt
        except Exception as e:   # noqa: BLE001 — 하루가 막혀도 나머지 진행
            by_order.setdefault('_errors', []).append(
                f"{day:%Y-%m-%d}: {type(e).__name__}: {str(e)[:150]}")
        day += _dt.timedelta(days=1)
    return jsonify(ok=True, 기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   alias=alias or "(대표)", 주문수=len([k for k in by_order if not k.startswith('_')]),
                   키목록=sorted(_keys), 정산구분별=_types, 주문별=by_order)


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
    # 🔴 [2026-08-12] 원본 **필드 이름**도 같이 준다(값 아님).
    #   롯데온 지급내역(seCmptDt=실입금일)은 **구매확정일(seStdDt) 단위**로 묶여 있어
    #   주문에 붙이려면 그 주문의 구매확정일이 있어야 한다. 그런데 우리는 그 값을
    #   어디에도 안 갖고 있다(롯데온 주문 API 에 구매확정 단계 자체가 없다).
    #   SettleItmdSales 응답에 확정일 계열 필드가 오는지 **추측 말고 눈으로** 확인하려는
    #   목적이다. 있으면 조인이 되고, 없으면 일자별 조회로 창을 쪼개는 수밖에 없다.
    키목록 = sorted({k for r in rows[:200] for k in (r or {}).keys()})
    return jsonify(ok=True, 기간=f"{since:%Y-%m-%d}~{until:%Y-%m-%d}",
                   alias=alias or "(대표)", 주문수=len(by_order), 주문별=by_order,
                   원본필드이름=키목록)


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
        # 🔴 `defs`(노랑 표본)는 목록이라 **detail 쪽**에 둔다 — summary 에 두면
        #   실행 30회치가 그대로 쌓여 Supabase 무료 티어를 먹는다.
        #   집계인 `def_reasons` 는 작으므로 summary 에 남아 화면 요약에 쓰인다.
        detail = {k: res[k] for k in ('missing', 'mismatch', 'undecided', 'defs')}
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


# ── 주문 내역 화면 설정 (열 순서·너비·빠른 기간·엑셀 양식) — 팀 공유 ──────────
#  사장님(2026-08-12): "기간 직접 만들었는데 자꾸 사라져."
#  원인은 재배포가 아니라 **브라우저 안에만 저장**돼 있던 것. 서버로 옮긴다.
#  단 컨테이너 data/ 는 배포마다 사라지므로 state_store 를 쓴다(모듈 주석 참조).

@bp.route('/api/view-prefs', methods=['GET', 'POST'])
def order_view_prefs():
    """GET = 저장된 설정 / POST = 보낸 칸만 덮어쓰기(부분 저장).

    🔴 실패를 조용히 삼키지 않는다 — 저장이 안 됐는데 성공한 척하면 사장님이
      같은 설정을 몇 번이고 다시 고치게 된다.
    """
    from lemouton.markets import order_view_prefs as _vp
    if request.method == 'GET':
        return jsonify(ok=True, prefs=_vp.load())
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(ok=False, error='보낸 값이 올바르지 않습니다.'), 400
    try:
        return jsonify(ok=True, prefs=_vp.save(body))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except RuntimeError as e:
        return jsonify(ok=False, error=str(e)), 500


# ── 마켓 정산 대조 (노션 주문관리 c-4) ────────────────────────────────────────
#  마켓 정산 화면에서 내려받은 엑셀 ↔ 우리 정산예정금액. 규칙·엔진 = margin/settle_recon.py

@bp.route('/settle-recon/items')
def settle_recon_items():
    """대조 항목 목록 + 기준일 규칙 — 화면이 「마켓에서 이렇게 뽑으세요」를 그대로 보여준다."""
    from lemouton.margin import settle_recon as _sr
    return jsonify(ok=True, items=[{'key': k, **v} for k, v in _sr.ITEMS.items()])


@bp.route('/settle-recon/run', methods=['POST'])
def settle_recon_run():
    """마켓 정산 엑셀 업로드 → 우리 값과 대조 → 결과 저장(지난번 대비 추적).

    🔴 열 이름을 추측하지 않는다 — 금액 열을 못 찾으면 파일에서 본 열 이름을 그대로
      돌려주며 422 로 실패한다. 조용히 0원으로 넘어가면 「대조했는데 일치」가 된다.
    """
    from lemouton.margin import settle_recon as _sr
    from lemouton.margin.models_settle_recon import SettleReconRun
    from lemouton.margin.settle_plan_rules import load_rules, wallet_summary

    item = (request.form.get('item') or '').strip()
    if item not in _sr.ITEMS:
        return jsonify(ok=False,
                       error=f'모르는 대조 항목입니다: {item or "(없음)"}'), 400
    f = request.files.get('file')
    if not f:
        return jsonify(ok=False, error='파일이 없습니다.'), 400
    try:
        parsed = _sr.parse_sheet(f.read())
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 422
    except Exception as e:   # noqa: BLE001 — 손상 파일 등 사유 표면화(조용한 성공 금지)
        return jsonify(ok=False, error=f'엑셀을 읽지 못했습니다: {type(e).__name__}: {e}'), 400

    rules = load_rules()
    lines = _settle_plan_lines([_sr.ITEMS[item]['market']])
    try:
        from lemouton.margin import rg_settlement as RG
        rg = RG.summary()
    except Exception:   # noqa: BLE001 — 로켓그로스가 없어도 나머지는 대조된다
        rg = {}
    try:
        from lemouton.margin import settle_fast_ledger as FL
        fast = FL.summary()
    except Exception:   # noqa: BLE001
        fast = {}
    try:
        wallet = wallet_summary(rules)
    except Exception:   # noqa: BLE001
        wallet = {}
    res = _sr.reconcile(item, parsed, lines, rules, today=_dt.date.today(),
                        rg_summary=rg, fast_summary=fast, wallet_summary=wallet)

    s = SessionLocal()
    try:
        prev = (s.query(SettleReconRun).filter(SettleReconRun.item == item)
                .order_by(SettleReconRun.id.desc()).first())
        run = SettleReconRun(item=item, filename=f.filename or '',
                             market_total=int(res['마켓값'] or 0),
                             ours_total=int(res['우리값'] or 0),
                             verdict=res['판정'],
                             parsed={k: v for k, v in parsed.items() if k != 'rows'},
                             result=res)
        s.add(run)
        # 저장 상한 30회 — Supabase 무료 티어(500MB) 보호. 오래된 실행부터 삭제.
        for o in (s.query(SettleReconRun).order_by(SettleReconRun.id.desc())
                  .offset(29).all()):
            s.delete(o)
        s.commit()
        return jsonify(ok=True, ran_at=run.ran_at.isoformat(), result=res,
                       parsed=parsed,
                       prev=(prev.result if prev else None),
                       prev_ran_at=(prev.ran_at.isoformat() if prev else None))
    finally:
        s.close()


@bp.route('/settle-recon/run-live', methods=['POST', 'GET'])
def settle_recon_run_live():
    """엑셀 없이 대조 — 마켓 API 에서 **마켓 값을 우리가 직접 읽어** 우리 값과 맞댄다.

    🔴 왜(2026-08-13) — 스마트스토어 대조는 「기준일 규칙만 코드에 넣고 실행은 한 번도
      안 한」 상태였다. 사장님께 정산 엑셀을 부탁하기 전에, 이미 있는 자동 경로
      (스스 정산 API)를 쓰는 게 맞다. 로켓그로스 엑셀 184개를 요청했던 실수와 같은 부류다.

    `?item=smartstore&alias=` — 지금은 스마트스토어만. 결과는 엑셀 경로와 **같은 표**에
    저장돼 지난번 판정과 이어진다.
    """
    from lemouton.margin import settle_recon as _sr
    from lemouton.margin.models_settle_recon import SettleReconRun
    from lemouton.margin.settle_plan_rules import load_rules, wallet_summary

    item = (request.args.get('item') or request.form.get('item') or 'smartstore').strip()
    if item != 'smartstore':
        return jsonify(ok=False, error=(
            f'자동 대조는 아직 스마트스토어만 됩니다(요청: {item}). '
            '쿠팡은 정산 엑셀 업로드(/settle-recon/run) 를 쓰세요.')), 400
    alias = (request.args.get('alias') or request.form.get('alias') or '').strip()
    today = _dt.date.today()
    try:
        cli = _client_for_diag('smartstore', alias)
        parsed = _sr.market_actual_smartstore(
            today=today, window_days=_sr.ITEMS[item]['window_days'], client=cli)
    except ValueError as e:      # 조용한 0원 금지 — 사유를 그대로 올린다
        return jsonify(ok=False, error=str(e)), 502
    except Exception as e:       # noqa: BLE001
        return jsonify(ok=False,
                       error=f'{type(e).__name__}: {str(e)[:300]}'), 502

    rules = load_rules()
    lines = _settle_plan_lines([_sr.ITEMS[item]['market']])
    try:
        from lemouton.margin import settle_fast_ledger as FL
        fast = FL.summary()
    except Exception:   # noqa: BLE001
        fast = {}
    try:
        wallet = wallet_summary(rules)
    except Exception:   # noqa: BLE001
        wallet = {}
    res = _sr.reconcile(item, parsed, lines, rules, today=today,
                        fast_summary=fast, wallet_summary=wallet)
    res['자동'] = True
    res['출처'] = parsed.get('출처') or ''
    res['마켓_배송비정산합'] = parsed.get('배송비정산합')
    res['마켓_정산구분별'] = parsed.get('정산구분별')
    res['조회오류'] = parsed.get('오류') or []

    s = SessionLocal()
    try:
        prev = (s.query(SettleReconRun).filter(SettleReconRun.item == item)
                .order_by(SettleReconRun.id.desc()).first())
        run = SettleReconRun(item=item, filename='(마켓 API 자동)',
                             market_total=int(res['마켓값'] or 0),
                             ours_total=int(res['우리값'] or 0),
                             verdict=res['판정'],
                             parsed={k: v for k, v in parsed.items() if k != 'rows'},
                             result=res)
        s.add(run)
        for o in (s.query(SettleReconRun).order_by(SettleReconRun.id.desc())
                  .offset(29).all()):
            s.delete(o)
        s.commit()
        return jsonify(ok=True, ran_at=run.ran_at.isoformat(), result=res,
                       parsed={k: v for k, v in parsed.items() if k != 'rows'},
                       prev=(prev.result if prev else None),
                       prev_ran_at=(prev.ran_at.isoformat() if prev else None))
    finally:
        s.close()


@bp.route('/settle-recon/run-manual', methods=['POST'])
def settle_recon_run_manual():
    """마켓 **화면 합계**를 손으로 적어 대조 — 엑셀로는 재현이 안 되는 항목용.

    🔴 왜 이 칸이 필요한가(2026-08-13 실측) — 쿠팡 「미구매확정」 상세 엑셀
      (UNCONFIRMED_SNAPSHOT_REPORT_DETAIL_LIST)엔 **수수료 열이 없다.**
      판매금액 293,000 + 판매배송비 24,000 = 317,000 만 있고, 우리가 배운 상품별
      실요율(11.55%)과 배송비 3.3% 로 계산하면 **282,366** 이 나온다.
      사장님 화면 값은 268,840 이라 **13,526 이 설명되지 않는다** — 게다가 화면은
      「5건」인데 엑셀엔 주문이 9건이라 **애초에 같은 묶음인지도 확실하지 않다.**
      추측으로 계수를 맞추면 그 순간 대조는 자기 자신을 증명하는 거짓말이 된다.
      그래서 **마켓 화면 숫자를 그대로 받아** 우리 값과 맞댄다.

    🔴 이 숫자는 **대조 상대**일 뿐, 우리 정산액이 되지 않는다. 돈 값의 원천은 끝까지
      마켓 API 다(사람이 적은 값이 금액 계산에 섞이면 원천이 둘로 갈린다).

    `item=` · `market_total=` (필수) · `market_count=` · `memo=` · `screen_basis=`
    """
    from lemouton.margin import settle_recon as _sr
    from lemouton.margin.models_settle_recon import SettleReconRun
    from lemouton.margin.settle_plan_rules import load_rules, wallet_summary

    item = (request.form.get('item') or '').strip()
    if item not in _sr.ITEMS:
        return jsonify(ok=False,
                       error=f'모르는 대조 항목입니다: {item or "(없음)"}'), 400
    raw = (request.form.get('market_total') or '').strip()
    total = _sr._num(raw)
    if total is None:
        return jsonify(ok=False, error=(
            '마켓 화면 합계를 숫자로 적어 주세요. '
            '0 을 넣으면 「대조했는데 일치」라는 거짓말이 됩니다.')), 400
    try:
        count = int(_sr._num(request.form.get('market_count') or '') or 0)
    except (TypeError, ValueError):
        count = 0
    memo = (request.form.get('memo') or '').strip()[:300]
    basis = (request.form.get('screen_basis') or '').strip()[:200]

    rules = load_rules()
    lines = _settle_plan_lines([_sr.ITEMS[item]['market']])
    try:
        from lemouton.margin import rg_settlement as RG
        rg = RG.summary()
    except Exception:   # noqa: BLE001
        rg = {}
    try:
        from lemouton.margin import settle_fast_ledger as FL
        fast = FL.summary()
    except Exception:   # noqa: BLE001
        fast = {}
    try:
        wallet = wallet_summary(rules)
    except Exception:   # noqa: BLE001
        wallet = {}
    # `parse_sheet` 와 같은 모양으로 감싸 `reconcile` 을 그대로 태운다(원천 하나).
    #  🔴 주문번호가 없으므로 주문 단위 대조는 「못 한다」고 정직하게 말한다.
    parsed = {"columns": [], "amount_col": "(화면 값 직접 입력)", "date_col": "",
              "ratio_col": "", "is_base_amount": False, "order_col": "", "fast_col": "",
              "건수": count, "금액건수": count, "합계": int(total), "빠른정산합계": 0,
              "기간시작": "", "기간끝": "", "rows": [], "상세잘림": False,
              "화면기준": basis, "메모": memo}
    res = _sr.reconcile(item, parsed, lines, rules, today=_dt.date.today(),
                        rg_summary=rg, fast_summary=fast, wallet_summary=wallet)
    res['손입력'] = True
    res['화면기준'] = basis
    res['메모'] = memo

    s = SessionLocal()
    try:
        prev = (s.query(SettleReconRun).filter(SettleReconRun.item == item)
                .order_by(SettleReconRun.id.desc()).first())
        run = SettleReconRun(item=item, filename='(마켓 화면 값 직접 입력)',
                             market_total=int(total),
                             ours_total=int(res['우리값'] or 0),
                             verdict=res['판정'], parsed=parsed, result=res)
        s.add(run)
        for o in (s.query(SettleReconRun).order_by(SettleReconRun.id.desc())
                  .offset(29).all()):
            s.delete(o)
        s.commit()
        return jsonify(ok=True, ran_at=run.ran_at.isoformat(), result=res,
                       parsed=parsed,
                       prev=(prev.result if prev else None),
                       prev_ran_at=(prev.ran_at.isoformat() if prev else None))
    finally:
        s.close()


@bp.route('/lotteon-paid/context')
def orders_lotteon_paid_context():
    """[읽기 전용] 롯데온 입금내역 가져오기에 필요한 것 + **최근 가져온 내역**.

    🔴 왜 `trNo` 를 서버가 주나(2026-08-13 라이브 실패) — 확장이 셀러오피스 **화면에서**
      판매자ID 를 긁게 해 뒀는데 라이브에서 `trNo not found` 로 실패했다. 화면 구조에
      기대는 방식이라 로그인 상태·페이지에 따라 못 찾는다. 우리는 그 번호를 **계정
      설정에 이미 갖고 있다**(`client._cfg['tr_no']` — 상품·가격·재고 호출 필수값).
      아는 값을 화면에서 다시 긁을 이유가 없다.

    🔴 왜 「최근 가져온 내역」인가(사장님 지적) — 단추를 눌러도 **언제 · 얼마나 들어왔는지**
      알 길이 없었다. 그러면 「눌렀는데 된 건가?」를 영영 확인할 수 없다.
    """
    from lemouton.margin import lotteon_paid as LP
    accounts, errs = [], []
    try:
        for prefix, name in (_oe._active_accounts('lotteon') or [(None, '')]):
            try:
                cli = _oe._account_client('lotteon', prefix)
                tr = str((getattr(cli, '_cfg', {}) or {}).get('tr_no') or '').strip()
            except Exception as e:      # noqa: BLE001 — 한 계정이 막혀도 나머지는 준다
                errs.append(f"{name or '(대표)'}: {type(e).__name__}")
                continue
            if tr:
                accounts.append({'계정': name or '(대표)', 'trNo': tr})
    except Exception as e:              # noqa: BLE001
        errs.append(f"{type(e).__name__}: {str(e)[:120]}")
    try:
        summary = LP.summary()
    except Exception as e:              # noqa: BLE001
        summary = {'오류': f'{type(e).__name__}: {str(e)[:120]}'}
    return jsonify(
        ok=True, 계정=accounts, 오류=errs, 최근가져온내역=summary,
        해석=('trNo 는 계정 설정에 이미 있는 값이다 — 확장이 화면에서 긁다 실패하면 '
              '(trNo not found) 이 값을 실어 보내면 된다.'))


@bp.route('/settle-recon/latest')
def settle_recon_latest():
    """항목별 마지막 대조 결과 — 탭에 들어오면 지난번 판정이 바로 보인다."""
    from lemouton.margin.models_settle_recon import SettleReconRun
    s = SessionLocal()
    try:
        out = {}
        for r in (s.query(SettleReconRun)
                  .order_by(SettleReconRun.id.desc()).limit(60).all()):
            if r.item in out:
                continue
            out[r.item] = {'ran_at': r.ran_at.isoformat(), 'filename': r.filename,
                           'result': r.result, 'parsed': r.parsed}
        return jsonify(ok=True, latest=out)
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
