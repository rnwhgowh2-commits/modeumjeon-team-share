"""[2026-06-03] 업로드 드라이런 미리보기 — "표시가 = 업로드가" 단일 진실 원천 다리.

배경:
  옵션트리(표시)는 PriceTemplate 정책(compute_market_price)으로 가격을 낸다.
  반면 기존 업로드 엔진([A][B][C][D])은 모델오버라이드/글로벌에서 가격을 가져와
  표시와 어긋났고, 수동 업로드 버튼은 run_uploader 시그니처 불일치로 작동도 안 했다.

이 모듈은 **실제 마켓 전송 없이**(드라이런) 각 옵션이 어떤 가격/재고로 어느
마켓 옵션에 올라갈지 미리 계산한다. 가격 산출은 옵션 매트릭스와 **동일 규칙**
(`api_pricing.get_option_matrix` 의 per-option 로직)을 따른다. 두 경로가 어긋나지
않도록 `tests/uploader/test_preview_parity.py` 가 매트릭스 엔드포인트 결과와
per-sku 교차검증한다.

실제 전송(라이브 PUT)은 본 모듈 책임 아님 — 사용자 확인 후 별도 연결.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from lemouton.sourcing.models import Model, Option
from lemouton.sourcing.models_pricing import OptionPriceConfig
from lemouton.templates.models import PriceTemplate
from lemouton.pricing.unified import compute_market_price


def _resolve_option_upload(o: Option, cfg, tpl, sources_for_opt, stock: int) -> dict:
    """단일 옵션의 마켓별 업로드 가격·우선공급 산출 (매트릭스와 동일 규칙).

    Returns: {resolved_side, src: {ss,cp}, pur: {ss,cp}|None, upload: {ss,cp}}.
    """
    # 원가(소싱) = 매트릭스와 100% 동일 규칙: 재고존재+크롤성공(error X) 중 최저 크롤가
    #   (_pick_cheapest_buyable) → 없으면 템플릿 매입가 → 95000.
    #   [2026-06-05] api_pricing 의 원가 선정과 같은 함수를 써서 '표시가=업로드가' 보장.
    #   stale(크롤 실패+옛값) 배제는 _pick_cheapest_buyable 내부 is_crawl_valid 가 담당.
    from webapp.routes.api_pricing import _pick_cheapest_buyable
    _cost_src = _pick_cheapest_buyable(sources_for_opt)
    purchase = ((_cost_src or {}).get('crawled_price')
                or (tpl.boxhero_purchase_price if tpl else None)
                or 95000)

    # 매입가(사입) 우선순위 (template/avg) — api_pricing 동일
    _avg = o.boxhero_avg_purchase_price or 0
    _tpl_purchase = (tpl.boxhero_purchase_price if tpl else 0) or 0
    _src_pri = (tpl.price_source_priority if tpl else 'template') or 'template'
    resolved_avg = (_avg or _tpl_purchase) if _src_pri == 'avg' else (_tpl_purchase or _avg)
    purchase_blocked = (resolved_avg == 0)

    # 우선 공급 — 재고≥1 무조건 사입 / 0 이면 priority 따름
    _pri = (o.purchase_priority or 'auto').lower()
    if stock >= 1:
        resolved_side = 'purchase'
    elif _pri == 'purchase':
        resolved_side = 'purchase'
    else:
        resolved_side = 'source'

    # 소싱 카드 가격 (옵션별 지정가 토글 최우선)
    src_ss = compute_market_price(tpl, 'ss', 'sourcing', purchase).final_price
    src_cp = compute_market_price(tpl, 'coupang', 'sourcing', purchase).final_price
    if o.src_fixed_ss_active and o.src_fixed_ss_price:
        src_ss = o.src_fixed_ss_price
    if o.src_fixed_cp_active and o.src_fixed_cp_price:
        src_cp = o.src_fixed_cp_price

    # 사입 카드 가격 (재고≥1 & 매입가 있을 때만)
    pur = None
    if stock >= 1 and not purchase_blocked:
        pur_ss = compute_market_price(tpl, 'ss', 'purchase', resolved_avg).final_price
        pur_cp = compute_market_price(tpl, 'coupang', 'purchase', resolved_avg).final_price
        if o.pur_fixed_ss_active and o.pur_fixed_ss_price:
            pur_ss = o.pur_fixed_ss_price
        if o.pur_fixed_cp_active and o.pur_fixed_cp_price:
            pur_cp = o.pur_fixed_cp_price
        pur = {'ss': pur_ss, 'cp': pur_cp}

    # 실제 업로드될 가격 = 적용(우선) 카드 기준
    if resolved_side == 'purchase' and pur is not None:
        upload = {'ss': pur['ss'], 'cp': pur['cp']}
    else:
        upload = {'ss': src_ss, 'cp': src_cp}

    return {
        'resolved_side': resolved_side,
        'src': {'ss': src_ss, 'cp': src_cp},
        'pur': pur,
        'upload': upload,
        'purchase_blocked': purchase_blocked,
    }


def build_upload_preview(s: Session, code: str) -> dict:
    """모음전 1건의 업로드 드라이런 미리보기.

    실제 전송 없음. 옵션별 업로드 예정 가격/재고 + 마켓ID·옵션매칭 준비점검.
    """
    m = s.query(Model).filter_by(model_code=code).first()
    if not m:
        return {'ok': False, 'error': '모음전을 찾을 수 없어요.'}

    opts = (s.query(Option).filter_by(model_code=code)
            .order_by(Option.color_code, Option.size_code).all())
    sku_list = [o.canonical_sku for o in opts]

    # [2026-06-05] 소싱처/크롤가 = 매트릭스(_option_matrix_data) 와 100% 동일 소스 사용.
    #   기존엔 OptionSourceUrl(구 저장소)만 읽어 신규 등록 URL(bundle_source_urls)을 놓쳐
    #   원가가 가짜 95000 으로 폴백 → 표시가≠업로드가 62건 불일치. 매트릭스가 두 저장소를
    #   통합하고 옵션단위 크롤가·카드할인까지 반영하므로, 그 결과(o['sources'])를 그대로
    #   재사용해 '표시가=업로드가' 단일 진실 원천(parity)을 보장한다.
    from webapp.routes.api_pricing import _option_matrix_data
    _md = _option_matrix_data(code)
    sku_to_sources: dict[str, list] = (
        {o['sku']: o.get('sources', []) for o in (_md.get('options') or [])}
        if _md.get('ok') else {})

    cfg_dict = {c.canonical_sku: c
                for c in (s.query(OptionPriceConfig)
                          .filter(OptionPriceConfig.canonical_sku.in_(sku_list)).all()
                          if sku_list else [])}

    tpl = (s.query(PriceTemplate).filter_by(id=m.price_template_id).first()
           if m.price_template_id else None)

    stock_dict: dict[str, int] = {}
    try:
        from shared.inventory_stock import get_stock_batch
        stock_dict = get_stock_batch(s, sku_list)
    except Exception:
        stock_dict = {}

    ss_active = bool(m.market_active_ss)
    cp_active = bool(m.market_active_coupang)
    ss_pid = m.naver_product_id or ''
    cp_pid = m.coupang_product_id or ''

    rows = []
    ss_ready = cp_ready = 0
    for o in opts:
        stock = stock_dict.get(o.canonical_sku, 0)
        r = _resolve_option_upload(o, cfg_dict.get(o.canonical_sku), tpl,
                                   sku_to_sources.get(o.canonical_sku, []), stock)
        ss_oid = o.naver_option_id or ''
        cp_oid = o.coupang_option_id or ''
        ss_ok = bool(ss_active and ss_pid and ss_oid)
        cp_ok = bool(cp_active and cp_pid and cp_oid)
        if ss_ok:
            ss_ready += 1
        if cp_ok:
            cp_ready += 1
        rows.append({
            'sku': o.canonical_sku,
            'color': o.color_display or o.color_code,
            'size': o.size_display or o.size_code,
            'resolved_side': r['resolved_side'],
            'stock': stock,
            'ss_price': r['upload']['ss'], 'cp_price': r['upload']['cp'],
            'ss_option_id': ss_oid, 'cp_option_id': cp_oid,
            'ss_ready': ss_ok, 'cp_ready': cp_ok,
        })

    total = len(opts)
    missing = []
    if ss_active and not ss_pid:
        missing.append('스마트스토어 상품번호 미등록')
    if cp_active and not cp_pid:
        missing.append('쿠팡 상품번호 미등록')
    if ss_active and ss_pid and ss_ready == 0:
        missing.append('스마트스토어 옵션 매칭 0건 (동기화 실행 필요)')
    if cp_active and cp_pid and cp_ready == 0:
        missing.append('쿠팡 옵션 매칭 0건 (동기화 실행 필요)')

    return {
        'ok': True,
        'dry_run': True,
        'model_code': code,
        'total_options': total,
        'markets': {
            'smartstore': {'active': ss_active, 'product_id': ss_pid,
                           'matched': ss_ready, 'total': total},
            'coupang': {'active': cp_active, 'product_id': cp_pid,
                        'matched': cp_ready, 'total': total},
        },
        'ready_to_upload': (ss_ready + cp_ready),
        'missing': missing,
        'rows': rows,
        'note': '드라이런 — 실제 마켓 전송 없음. 표시(옵션트리) 가격과 동일 산출.',
    }
