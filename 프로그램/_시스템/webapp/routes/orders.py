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
            all_columns=_oe.ALL_COLUMNS if tab == 'list' else [],
            col_meta=_oe.columns_meta() if tab == 'list' else {},
        )
    return render_template('orders/index.html', **ctx)


def _parse_markets(args):
    """markets(콤마·다중) 또는 market(단일). SUPPORTED 로 필터(순서 유지·중복 제거)."""
    raw = args.get('markets') or args.get('market') or 'smartstore'
    out, seen = [], set()
    for m in raw.split(','):
        m = m.strip()
        if m in _oe.SUPPORTED and m not in seen:
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


def _parse_range(args):
    """from·to(YYYY-MM-DD) → (since, until) KST datetime. 없으면 (None, None)=days 사용.

    since=시작일 00:00, until=종료일 23:59:59.999 (그 날 하루 전체 포함). 잘못된 형식·역순은
    무시(None) → days 폴백. 최대 90일로 제한(과도한 조회 방지).
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
    if (d2 - d1).days > 90:            # 상한 90일
        d1 = d2 - _dt.timedelta(days=90)
    since = _dt.datetime(d1.year, d1.month, d1.day, 0, 0, 0, tzinfo=_oe.KST)
    until = _dt.datetime(d2.year, d2.month, d2.day, 23, 59, 59, 999000, tzinfo=_oe.KST)
    return since, until


@bp.route('/export.xlsx')
def orders_export():
    """선택 마켓(다중) 최근 N일 주문 → 엑셀 다운로드(서버측 실조회, 최신순 통합).

    markets=콤마구분(다중). cols=콤마구분(열 구성·순서, A5 양식). 미지원 마켓/조회실패는
    사유와 함께 400(CDN 이 5xx 본문을 가려서 4xx 로 표면화). 추측 데이터 안 만듦.
    """
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
    try:
        rows = _oe.combined_order_rows(markets, days=days, use_cache=True,
                                       since=since, until=until, warnings=warnings)
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:   # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("order preview failed markets=%s", markets)
        return jsonify(ok=False, error=f"{type(e).__name__}: {str(e)[:300]}"), 400
    # 화면에 원본 그대로(구매자·수령자·전화·주소 마스킹 없이) — 사용자 요청(관리자 화면, 본인 데이터).
    return jsonify(ok=True, markets=markets, days=days,
                   columns=_oe.ALL_COLUMNS, count=len(rows), rows=rows,
                   warnings=warnings)


# ──────────────────────────────────────────────────────────────
#  송장(운송장) 입력·전송
#   · 엑셀 업로드 → 「오픈마켓주문번호」 매칭 → 그 행에 운송장번호
#   · 직접 입력  → 행 선택 + 택배사 + 송장번호
#   · 전송은 **드라이런 기본**. 요청이 live=true 라도 전역 스위치가 꺼져 있으면 강등한다.
# ──────────────────────────────────────────────────────────────

def _live_enabled() -> bool:
    """송장 실전송 스위치(LEMOUTON_LIVE_INVOICE). 테스트에서 monkeypatch 지점.

    가격·재고 자동 업로드(LEMOUTON_LIVE_UPLOAD)와 분리된 스위치다.
    """
    from lemouton.uploader.runtime import live_invoice_enabled
    return live_invoice_enabled()


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
    """11번가 택배사 코드(dlvEtprsCd) 확인 — 읽기 전용, 코드·건수만.

    11번가 발송처리용 택배사 코드는 공개 출처마다 값이 달라(로젠: 00002 vs 05) 추측할 수 없다.
    정답은 이미 발송한 주문이 갖고 있다 — 배송중 목록이 되돌려주는 dlvEtprsCd 가 곧 11번가의 코드.
    응답에는 코드와 건수만 담는다(주문번호·송장번호·고객정보 미포함).
    """
    from flask import jsonify
    from shared.platforms.eleven11 import orders as eo

    cli = _client_for('eleven11', '')
    if cli is None:
        return jsonify(ok=False, error='11번가 키가 등록돼 있지 않습니다'), 400

    days = max(1, min(30, int(request.args.get('days', 14))))
    until = _dt.datetime.now()
    since = until - _dt.timedelta(days=days)

    counts: dict = {}
    for od in eo.iter_shipping(since, until, client=cli):
        code = str(od.get('dlvEtprsCd') or '').strip()
        if code:
            counts[code] = counts.get(code, 0) + 1

    note = ('최근 {}일 발송 이력이 없어 코드를 확인하지 못했습니다'.format(days) if not counts
            else '가장 많이 쓴 코드가 평소 택배사(로젠)일 가능성이 높습니다')
    return jsonify(ok=True, days=days, codes=counts, note=note)


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
                           send_ids=r.get('send_ids'), client=cli, live=live)
        if res.success:
            sent += 1
        else:
            failed += 1
        results.append({"market": res.market, "order_no": res.order_no,
                        "success": res.success, "dry_run": res.dry_run,
                        "error": res.error})

    return jsonify(ok=True, live=live, sent=sent, failed=failed, results=results)
