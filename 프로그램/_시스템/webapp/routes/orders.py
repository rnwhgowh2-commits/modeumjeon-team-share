"""[v2] 주문·정산·CS·신규등록 — `/orders`.

판매자 마켓 API 연동 데이터 위에서 동작(주문·정산·문의반품·신규등록·마진).
확장 기능 커넥터(lemouton.markets.capabilities) + 마스터 게이트 MOUM_MARKET_EXTRA.
게이트 OFF(기본) = '연결됨(검증대기)' — 샘플 미리보기 + 액션 버튼 비활성. 실데이터는
실계정 키 연결 + 검증 후. (관련: CLAUDE.md 🔒 3대 원칙 — 검증 전 완료/전송 금지)

레이아웃 = 사용자 확정 "5번(KPI 요약 + 표)" — 네 탭(list·sales·cs·register)이 공통.
"""
import datetime as _dt
import io as _io

from flask import Blueprint, render_template, request, send_file, abort, jsonify

from lemouton.markets import capabilities as _cap
from lemouton.markets import order_export as _oe
from shared.db import SessionLocal
from lemouton.delivery import service as _dsvc
from lemouton.delivery.mango_parser import parse_mango_xls, MangoParseError


bp = Blueprint('orders', __name__, url_prefix='/orders')


SUBTABS = [
    {'key': 'list', 'label': '📋 주문 내역', 'desc': '마켓별 주문 통합 조회 + 송장 입력'},
    {'key': 'inspect', 'label': '🚚 배송검사', 'desc': '더망고 업로드 · 중복송장 · 배송흐름 · 배송방식'},
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
    try:
        rows = _oe.combined_order_rows(markets, days=days, use_cache=True,
                                       since=since, until=until, warnings=warnings)
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
#  배송검사 (inspect) — 더망고 업로드 · 중복송장 · 배송흐름 · 배송방식
#   업로드=더망고 엑셀(HTML위장 .xls) → MangoOrder DB 누적. 검사·배송방식은 엑셀 기반.
# ──────────────────────────────────────────────────────────────

def _mango_to_dict(o):
    return {
        'uid': o.mango_uid, 'market': o.market_name, 'recipient': o.recipient,
        'product': o.product_name, 'option': o.option1, 'invoice': o.invoice_no or '',
        'mango_status': o.mango_status, 'market_status': o.market_status,
        'method': o.delivery_method, 'method_source': o.delivery_method_source,
        'dup': bool(o.is_duplicate_invoice),
    }


@bp.route('/inspect/data')
def inspect_data():
    """배송검사 목록 + 검사요약 + 구분자 매핑 (JSON)."""
    s = SessionLocal()
    try:
        _dsvc.seed_default_status_map(s)   # 최초 진입 시 기본 매핑 보장
        orders = (s.query(_dsvc.MangoOrder)
                  .order_by(_dsvc.MangoOrder.last_uploaded_at.desc()).limit(1000).all())
        dup_uids = {o.mango_uid for o in _dsvc.find_duplicate_invoices(s)}
        flow_uids = {o.mango_uid for o in _dsvc.find_flow_missing(s)}
        rows = []
        for o in orders:
            d = _mango_to_dict(o)
            d['flow_missing'] = o.mango_uid in flow_uids
            rows.append(d)
        status_map = [
            {'value': m.status_value, 'meaning': m.meaning,
             'default_method': m.default_method, 'flow': bool(m.is_flow_check_target)}
            for m in sorted(_dsvc.get_status_map(s).values(), key=lambda x: x.sort_order)
        ]
        return jsonify(ok=True, orders=rows, status_map=status_map,
                       summary={'dup': len(dup_uids), 'flow': len(flow_uids),
                                'total': len(orders)})
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
        res = _dsvc.upsert_orders(s, rows, bulk_method=bulk)
        return jsonify(ok=True, inserted=res['inserted'], updated=res['updated'],
                       parsed=len(rows))
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
