"""주문 3분류 — 이행 / 미이행(재고없음·역마진) / 클레임.

사장님 확정 (2026-07-31):
    · S(재고없음) = 소싱처 URL 을 보면 재고를 알 수 있으니 그걸로 판정한다
    · P(역마진)   = 정산예정금(배송비포함) − 최종매입가 < 0 이면 역마진,
                    > 0 이면 이행 가능
    · 자동으로 판정한다

■ 계산식을 여기서 만들지 않는다
  최종매입가·SKU 매칭은 `orders.price_diff` 가 이미 하고 있다. 같은 값을 여기서
  또 만들면 두 화면이 다른 답을 내고, 이 저장소에서 그건 곧 금전 사고다.
  이 모듈은 **판정만** 한다.

■ 매출 기준 = `정산예정금(배송비포함)`
  마켓이 준 실값이다. 수수료율로 되계산하지 않는다 — 마켓마다 떼는 방식이 달라
  되계산하면 「에러 없이 틀린 숫자」가 된다(memory: 정답지=정산예정금(배송비포함)).

■ 🔴 모르면 「확인 불가」다 — 미이행도 이행도 아니다
  재고를 못 읽었거나 매입가를 못 구한 주문을 미이행으로 넣으면 **팔 수 있는 주문을
  버린다**. 반대로 이행으로 넣으면 손해 보는 주문을 그냥 내보낸다. 둘 다 돈이 샌다.
  그래서 확인 불가는 미이행 안에 **별도 사유**로 세워 눈으로 확인하게 한다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

GROUP_FULFILL = 'fulfill'        # 이행 — 보낼 수 있다
GROUP_UNFULFILL = 'unfulfill'    # 미이행 — 못 보낸다(사유 있음)
GROUP_CLAIM = 'claim'            # 클레임 — 취소·반품·교환

REASON_STOCK = 'S'               # 재고 없음
REASON_LOSS = 'P'                # 역마진
#: 🔴 「우리 상품이 아니다」와 「우리 상품인데 못 정했다」는 **다른 말**이다.
#:   뭉개면 모음전으로 관리하지도 않는 남의 상품 주문이 전부 「프로그램이 실패했다」로
#:   보인다 — 라이브 실측(2026-07-31) 쿠팡 97건 중 95건이 잔스포츠·마스마룰즈 등
#:   우리 시스템에 아예 없는 상품이었다.
REASON_NOT_OURS = 'not_ours'     # 모음전으로 관리하지 않는 상품 — 고칠 것이 없다
REASON_UNKNOWN = 'unknown'       # 우리 상품인데 자동 판정 불가 — 눈으로 확인
REASON_OTHER = 'other'           # 사람이 지정한 그 밖의 사유
#: 🔴 [2026-08-12 사장님] 소싱처 주소가 없으면 「확인 불가」가 아니다 — 우리가 못 본 게
#:   아니라 **볼 주소 자체가 없는** 것이다. 사장님이 짚은 두 경우:
#:     ① 오프라인에서 사입해 재고를 두고 파는 상품 (소싱처가 애초에 없다)
#:     ② 마켓엔 팔고 있지만 아직 우리 프로그램에 연동이 안 된 상품
#:   둘 다 「크롤하면 알 수 있는데 안 했다」가 아니라서, 같은 말로 뭉개면 사장님이
#:   고칠 게 없는 줄을 계속 들여다보게 된다.
REASON_NO_SOURCE_URL = 'no_source_url'

GROUP_LABEL = {GROUP_FULFILL: '이행', GROUP_UNFULFILL: '미이행', GROUP_CLAIM: '클레임'}
REASON_LABEL = {REASON_STOCK: '재고없음', REASON_LOSS: '역마진',
                REASON_NO_SOURCE_URL: '소싱처 URL 없음',
                REASON_NOT_OURS: '우리 상품 아님',
                REASON_UNKNOWN: '확인 불가', REASON_OTHER: '기타'}

#: 매출 기준 칸. 이름을 바꾸지 않는다 — 엑셀 열문자가 아니라 필드명이 계약이다.
SETTLE_FIELD = '정산예정금(배송비포함)'


def _to_int(v):
    """숫자로 못 읽으면 None. 0 은 값이다(빈칸과 다르다)."""
    if v is None or v == '':
        return None
    try:
        return int(round(float(str(v).replace(',', '').replace('원', '').strip())))
    except (ValueError, TypeError):
        return None


def stock_state(option: dict) -> str:
    """소싱처 재고 3상태 — 'in' | 'out' | 'unknown'.

    ★ 「품절」과 「모름」을 뭉개지 않는다. 크롤이 실패했거나 아직 안 돈 옵션을
      품절로 읽으면 팔 수 있는 주문이 미이행으로 빠진다
      (memory: project_stock_parse_fail_unknown_gate).
    """
    srcs = (option or {}).get('sources') or []
    usable = [s for s in srcs if s.get('last_status') != 'error'
              and (s.get('crawled_price') or 0) > 0]
    if not usable:
        return 'unknown'                       # 값을 준 소싱처가 하나도 없다
    if any(not s.get('stock_out') for s in usable):
        return 'in'
    return 'out'                               # 값은 있는데 전부 품절


def _memo_matrix_loader(base=None):
    """모델코드당 매트릭스를 **한 번만** 읽는 로더. price_diff 와 나눠 쓴다.

    [perf 2026-08-06] 모델코드와 무관한 조회(소싱처 상품 전수)는 `batch` 그릇으로
      한 번만 하게 한다 — 예전엔 모델코드마다 같은 표를 통째로 다시 읽었다.
      그릇은 이 로더와 수명이 같다(요청이 끝나면 같이 사라진다 — 모듈 캐시 아님).
    """
    batch = None
    if base is None:
        from webapp.routes.api_pricing import _option_matrix_data as _base
        batch = {}

        def base(model_code):
            return _base(model_code, batch=batch)
    cache = {}

    def load(model_code):
        if model_code not in cache:
            cache[model_code] = base(model_code)
        return cache[model_code]
    load.cache = cache
    return load


def classify_rows(session, rows, *, matrix_loader=None) -> dict:
    """주문 행 목록 → {행키: {group, reason, stock, purchase, settle, profit}}.

    행키는 `price_diff.row_key` 와 **같은 것**을 쓴다 — 화면이 두 결과를 같은 행에
    붙여야 하는데 키가 다르면 붙지 않는다.
    """
    from lemouton.claims.service import claim_type_of
    from lemouton.sources.site_labels import label_of as _label
    from lemouton.orders import price_diff as _pd
    from lemouton.sourcing.models import Option

    out = {}
    rows = list(rows or [])
    if not rows:
        return out

    # ── 1) 클레임 먼저 갈라낸다 — 판정 자체가 필요 없다 ──────────────────────
    rest = []
    for r in rows:
        key = _pd.row_key(r)
        if claim_type_of(r):
            out[key] = {'group': GROUP_CLAIM, 'reason': None,
                        'claim_type': claim_type_of(r),
                        'stock': None, 'purchase': None,
                        'settle': _to_int(r.get(SETTLE_FIELD)), 'profit': None}
        else:
            rest.append(r)
    if not rest:
        return out

    loader = matrix_loader or _memo_matrix_loader()

    # ── 2) 주문행 → 우리 옵션(SKU). 매칭은 price_diff 것을 그대로 쓴다 ───────
    #   verbose 를 쓰는 이유: **왜 못 찾았는지**가 사장님에게 다른 뜻이기 때문이다.
    #   「우리 상품이 아니다」는 고칠 것이 없고, 「못 좁혔다」는 봐야 할 일이다.
    try:
        targets = _pd.resolve_targets_verbose(session, rest)
    except Exception:                       # noqa: BLE001
        logger.exception('주문→옵션 매칭 실패 — %d건 확인 불가', len(rest))
        targets = {}

    sku_by_key = {k: v['sku'] for k, v in (targets or {}).items() if v.get('sku')}
    #: 우리 연동 목록에 없다 = 모음전으로 관리하지 않는 상품
    #:   ① 번호를 줬는데 색인에 없다  ② 그 마켓에 연동이 한 건도 없다
    #:   ★ 연동이 통째로 0건인 상태(MATCH_NO_LINKS)는 여기 넣지 않는다 — 그건
    #:     「남의 상품」이 아니라 「판단할 근거가 없다」이다.
    not_ours = {k for k, v in (targets or {}).items()
                if v.get('reason') == _pd.MATCH_NOT_OURS}
    skus = sorted(set(sku_by_key.values()))

    # ── 3) 최종매입가 — price_diff 단일 원천 ────────────────────────────────
    finals = {}
    if skus:
        try:
            finals, _errs = _pd._current_purchase(session, skus, matrix_loader=loader)
        except Exception:                   # noqa: BLE001
            logger.exception('최종매입가 조회 실패 — %d건 확인 불가', len(skus))

    # ── 4) 재고 + 바로가기 — 같은 매트릭스에서 읽는다(다시 부르지 않는다) ──
    #   노션 ⑤「바로가기 버튼 : 주문정보, 가격재고이력, 소싱처링크, 판매처링크,
    #   상품주문링크, 상품관리」. 무재고라 **소싱처링크 = 상품주문링크**다
    #   (그 페이지에서 우리가 산다) — 같은 주소를 두 버튼으로 두지 않는다.
    stock_by_sku, links_by_sku = {}, {}
    # 🔴 [2026-08-12] 「언제 긁은 값인가」 — 이게 없으면 3일 전 재고를 오늘 재고인 척
    #   보여주게 된다. 크롤은 사장님 PC 크롬 확장이 하고 서버는 저장분만 읽으므로,
    #   판정은 **항상 마지막 크롤 시점의 값**이다. 그 사실을 화면이 말해야 한다.
    crawl_by_sku = {}
    model_by_sku = {}
    if skus:
        model_by_sku = {o.canonical_sku: o.model_code
                        for o in session.query(Option)
                        .filter(Option.canonical_sku.in_(skus)).all()}
        for mc in sorted(set(model_by_sku.values())):
            data = None
            try:
                data = loader(mc)
            except Exception:               # noqa: BLE001
                logger.exception('옵션 매트릭스 조회 실패 model=%s', mc)
            if not data or not data.get('ok'):
                continue
            for o in (data.get('options') or []):
                if o.get('sku') not in model_by_sku:
                    continue
                stock_by_sku[o['sku']] = stock_state(o)
                # 소싱처 링크 — 매트릭스가 이미 들고 있는 주소만 쓴다(조립 금지).
                srcs = []
                for c in (o.get('sources') or []):
                    url = c.get('product_url')
                    if url and url not in [x['url'] for x in srcs]:
                        # 이름표는 단일 원천(site_labels)을 먼저 본다 — 매트릭스가
                        # 주는 source_name 이 비면 영문 키가 그대로 버튼에 뜬다.
                        key = c.get('source_key') or ''
                        srcs.append({'label': _label(key)
                                     or c.get('source_name') or '소싱처',
                                     'url': url})
                links_by_sku[o['sku']] = {
                    'sources': srcs,
                    'product': '/bundles/' + str(model_by_sku[o['sku']]),
                }
                # 가장 최근에 성공한 크롤 시각. 성공한 게 하나도 없으면 None —
                #  「모른다」를 0 이나 지금 시각으로 채우지 않는다.
                _ats = [c.get('last_fetched_at') for c in (o.get('sources') or [])
                        if c.get('last_fetched_at') and c.get('last_status') == 'ok']
                crawl_by_sku[o['sku']] = {
                    'crawled_at': max(_ats) if _ats else None,
                    'source_urls': len(srcs),
                }

    # ── 5) 판정 ─────────────────────────────────────────────────────────────
    for r in rest:
        key = _pd.row_key(r)
        sku = sku_by_key.get(key)
        settle = _to_int(r.get(SETTLE_FIELD))
        purchase = finals.get(sku) if sku else None
        stock = stock_by_sku.get(sku) if sku else None
        profit = (settle - purchase) if (settle is not None and purchase is not None) else None

        _cr = crawl_by_sku.get(sku) if sku else None
        d = {'sku': sku, 'stock': stock, 'purchase': purchase,
             'settle': settle, 'profit': profit,
             # 바로가기 — 우리 상품으로 매칭된 행만 있다. 없으면 화면이 안 그린다.
             'links': links_by_sku.get(sku) if sku else None,
             # 「언제 긁은 값인가」 — 판정과 **한 묶음**으로 보내야 화면이 같이 적는다.
             'crawled_at': (_cr or {}).get('crawled_at'),
             'source_urls': (_cr or {}).get('source_urls'),
             }
        if stock == 'out':
            d.update(group=GROUP_UNFULFILL, reason=REASON_STOCK)
        elif profit is not None and profit < 0:
            d.update(group=GROUP_UNFULFILL, reason=REASON_LOSS)
        elif stock == 'in' and profit is not None:
            d.update(group=GROUP_FULFILL, reason=None)
        elif key in not_ours:
            # 모음전으로 관리하지 않는 상품이다 — 고칠 것이 없다.
            # 「확인 불가」로 뭉개면 남의 상품 주문이 전부 문제처럼 보인다.
            d.update(group=GROUP_UNFULFILL, reason=REASON_NOT_OURS)
        elif (_cr or {}).get('source_urls') == 0:
            # 🔴 [2026-08-12 사장님] 여기까지 왔는데 소싱처 주소가 **0개**면, 우리가
            #   못 본 게 아니라 **볼 주소 자체가 없는** 것이다. 「확인 불가」로 뭉개면
            #   사장님이 고칠 게 없는 줄을 계속 들여다보게 된다.
            #   ★ 재고·역마진 판정보다 **뒤**에 둔다 — 주소가 없어도 재고를 아는 경우가
            #     있고(옵션에 재고만 저장된 상태), 그때는 그 판정이 더 정확하다.
            d.update(group=GROUP_UNFULFILL, reason=REASON_NO_SOURCE_URL,
                     no_url_why='ours_no_url')
        else:
            # 우리 상품인데 재고를 못 읽었거나 매입가·정산예정금을 못 구했다.
            # 「보낼 수 있다」고도 「못 보낸다」고도 말하지 않는다.
            d.update(group=GROUP_UNFULFILL, reason=REASON_UNKNOWN)
        out[key] = d
    return out


def request_recheck(session, rows, *, now=None) -> dict:
    """이행 판단 ② — 「값이 바뀌는 상품」만 다시 긁도록 **확인 요청** 표식을 찍는다.

    사장님 확정(2026-08-13): *"변경값 없는건 저장된 크롤값 그대로 + 변경값있는건
    새로 긁고 판정. 해당 주문건에 소싱처 url 있는것만 긁으면 돼"*
    「변경값」 = **그 상품의 가격·재고가 바뀐 것**.

    🔴 그 신호를 새로 만들지 않는다 — 크롤이 이미 남긴다. `_record_crawl_delta` 가
      가격·재고가 바뀌면 `no_change_streak = 0`, 안 바뀌면 +1 로 쌓는다.
      그래서 **`no_change_streak == 0` = 마지막 크롤에서 값이 바뀐 상품**이다.
      값이 늘 그대로인 상품(streak 가 쌓인 것)은 저장된 크롤값을 그대로 쓴다 —
      그게 「수백~수천 건을 매번 다 긁지 말라」는 요구의 알맹이다.

    🔴 표식만 찍고 **여기서 긁지 않는다.** 크롤은 사장님 PC 확장이 한다(서버는 IP 가
      다르다). 표식은 두 마감 경로(벽시계·랩)가 모두 읽어 맨 앞으로 올린다.

    반환: 무엇을 왜 골랐는지 — 숫자만 주면 「왜 3건뿐이지?」에 답할 수 없다.
    """
    import datetime as _dt

    from lemouton.claims.service import claim_type_of
    from lemouton.orders import price_diff as _pd
    from lemouton.sources.models import ModelSourceLink, SourceProduct
    from lemouton.sourcing.models import Option

    now = now or _dt.datetime.utcnow()
    rows = [r for r in (rows or []) if not claim_type_of(r)]
    out = {'요청': 0, '대상주문': 0, '값이_안_바뀌는_상품': 0,
           '소싱처URL_없음': 0, '크롤제외': 0, '우리상품아님': 0}
    if not rows:
        return out

    try:
        targets = _pd.resolve_targets_verbose(session, rows)
    except Exception:                       # noqa: BLE001
        logger.exception('확인 요청 — 주문→옵션 매칭 실패 %d건', len(rows))
        return dict(out, 오류='주문을 우리 상품과 잇지 못했어요')
    skus = sorted({v['sku'] for v in (targets or {}).values() if v.get('sku')})
    out['대상주문'] = len(skus)
    out['우리상품아님'] = sum(1 for v in (targets or {}).values() if not v.get('sku'))
    if not skus:
        return out

    models = sorted({m for (m,) in session.query(Option.model_code)
                     .filter(Option.canonical_sku.in_(skus)).distinct().all() if m})
    if not models:
        return out
    sp_ids = [i for (i,) in session.query(ModelSourceLink.source_product_id)
              .filter(ModelSourceLink.model_code.in_(models)).distinct().all()]
    if not sp_ids:
        out['소싱처URL_없음'] = len(skus)
        return out

    for sp in (session.query(SourceProduct)
               .filter(SourceProduct.id.in_(sp_ids),
                       SourceProduct.deleted_at.is_(None)).all()):
        if not (sp.url or '').strip():
            out['소싱처URL_없음'] += 1        # 볼 주소가 없다 — 긁을 수 없다
            continue
        if int(sp.crawl_weight or 0) <= 0:
            out['크롤제외'] += 1              # 「안 긁는다」고 정해 둔 것 — 뒤집지 않는다
            continue
        if int(sp.no_change_streak or 0) > 0:
            out['값이_안_바뀌는_상품'] += 1     # 저장된 크롤값 그대로 쓴다
            continue
        sp.recheck_requested_at = now
        out['요청'] += 1
    return out


def summarize(result: dict) -> dict:
    """탭 머리에 붙일 건수 — {이행, 미이행, 클레임, 사유별}."""
    counts = {GROUP_FULFILL: 0, GROUP_UNFULFILL: 0, GROUP_CLAIM: 0}
    reasons = {REASON_STOCK: 0, REASON_LOSS: 0, REASON_NO_SOURCE_URL: 0,
               REASON_NOT_OURS: 0, REASON_UNKNOWN: 0, REASON_OTHER: 0}
    for d in (result or {}).values():
        g = d.get('group')
        if g in counts:
            counts[g] += 1
        if g == GROUP_UNFULFILL and d.get('reason') in reasons:
            reasons[d['reason']] += 1
    return {'counts': counts, 'reasons': reasons}
