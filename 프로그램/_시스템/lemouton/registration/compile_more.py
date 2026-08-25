# -*- coding: utf-8 -*-
"""ProductDraft → 옥션·G마켓·11번가·롯데온 등록 스펙 (순수 함수).

2026-07-21 4대 마켓 실등록→판매중지 라이브 검증에서 발굴한 스키마의 파이프라인 이식.
스스·쿠팡(compile_smartstore/coupang)과 달리 이 마켓들은 **선행자원**(출하지·발송정책·
주소코드·본보기 상품)이 라이브 조회로만 얻어져서, 여기서는 draft 검증·정규화만 하고
(순수 함수 유지) 실제 payload 조립은 send_more.py 가 게이트 뒤에서 수확+조립한다.

[2026-07-21 옵션 지원] 옵션(색상×사이즈) 상품도 등록한다 — spec['options'] 에 정규화.
  ESM=등록 후 recommended-options PUT(조합형·봉투 미러링) / 11번가=싱글옵션 ProductOption
  반복(colValue0="색상/사이즈" 조합값) / 롯데온=본보기 단품 복제(itmLst 다건).
  재고 0 옵션은 excluded 로 표면화(이 마켓들은 옵션 재고 0 등록 불가).

category_code 의 마켓별 의미(등록 화면 안내와 일치해야 함):
  auction/gmarket → "ESM카테고리코드/사이트카테고리코드" (예: 00120005002000000000/37500700)
  eleven11        → 최하위 dispCtgrNo (예: 1011634)
  lotteon         → 본보기 기존 상품번호 spdNo (예: LO2727500650) —
                    등록 body 가 그 상품 detail 스키마를 그대로 따르기 때문(실측).
"""
from lemouton.registration.compile_common import (
    CompileError, coerce_int, loads_json, require_category,
)

MARKETS_MORE = ('auction', 'gmarket', 'eleven11', 'lotteon')


def _normalize_options(draft, price: int):
    """options_json → (정규화 옵션 리스트, excluded).

    [2026-07-21 옵션 지원] 재고 0·미입력 옵션은 조용히 버리지 않고 excluded 로 보고
    (스스 컴파일러와 같은 규약). 유효 옵션이 하나도 없으면 CompileError.
    반환 옵션: {color, size, stock, extra_price, sku}
    """
    raw = loads_json(draft.options_json, [], what='옵션')
    if not raw:
        return [], []
    out, excluded = [], []
    for o in raw:
        if not isinstance(o, dict):
            continue
        color = str(o.get('color') or '').strip()
        size = str(o.get('size') or '').strip()
        if not color and not size:
            continue
        stock = coerce_int(o.get('stock'), f'옵션({color}/{size}) 재고')
        if stock is None or stock <= 0:
            excluded.append({'color': color, 'size': size, 'stock': stock,
                             'reason': '재고 0 또는 미입력 — 이 마켓들은 옵션 재고 0 등록 불가'})
            continue
        extra = coerce_int(o.get('extra_price'), f'옵션({color}/{size}) 추가금') or 0
        if (price + extra) % 10 != 0:
            raise CompileError(
                f'옵션({color}/{size}) 추가금 포함가가 10원 단위가 아닙니다'
                f'({price + extra}원) — ESM·11번가 규격.')
        out.append({'color': color, 'size': size, 'stock': int(stock),
                    'extra_price': int(extra), 'sku': str(o.get('sku') or '').strip(),
                    'model': str(o.get('model') or '').strip()})
    if not out and excluded:
        raise CompileError(
            '유효한 옵션이 하나도 없습니다(전부 재고 0/미입력) — 등록을 막습니다: '
            + '; '.join(f"{e['color']}/{e['size']}" for e in excluded[:5]))
    _막이_모델이_다른데_이름이_같다(out)
    return out, excluded


def _막이_모델이_다른데_이름이_같다(rows):
    """🔴 이 마켓들(옥션·G마켓·11번가·롯데온)은 옵션 이름을 **색상·사이즈로만** 만든다.

    모델모음전 3축 옵션이 오면 「메이트 블랙 260」과 「스위트 블랙 260」이
    둘 다 `블랙/260` 이 된다. 사장님 눈엔 다른 옵션인데 마켓엔 **같은 이름 두 줄**이
    올라간다 — 손님이 못 고르고, 들어온 주문이 어느 모델인지 알 수 없다.
    (11번가는 문서에 「한 상품안에서 옵션값은 중복이 될수 없습니다」라고 못 박혀 있다.
     옥션·G마켓·롯데온의 실제 거절 여부는 **미실측 — 확인불가**)

    🔴 `registration/options._normalize` 를 그대로 재사용하면 **안 된다.** 거긴
       중복을 **재고 거르기 전에** 세서, 「블랙/260 재고0 + 블랙/260 재고5」처럼
       오늘 멀쩡히 등록되는 초안(품절 재입고를 두 줄로 적은 것)을 새로 막는다(실측).
       그래서 여기서는 **팔 수 있는 줄만** 보고, **모델이 실제로 갈릴 때만** 막는다.

    ★ 모델 칸이 없는 옛 옵션은 model='' 이라 이 막이에 안 걸린다(회귀 없음).
    """
    본 = {}
    for r in rows:
        본.setdefault((r['color'], r['size']), []).append(r)
    for (색, 사이즈), 묶음 in 본.items():
        모델들 = {r.get('model', '') for r in 묶음}
        if len(묶음) > 1 and len(모델들 - {''}) > 1:
            이름 = '/'.join(p for p in (색, 사이즈) if p) or '(빈 이름)'
            raise CompileError(
                f'모델이 다른 옵션이 이 마켓에서는 같은 이름이 됩니다: {이름} '
                f'({" · ".join("「" + m + "」" for m in sorted(모델들) if m)}). '
                f'옥션·G마켓·11번가·롯데온은 옵션 이름을 색상·사이즈로만 만들어 '
                f'모델명이 실리지 않습니다 — 모델을 나눠서 올리세요.')


def _base_spec(draft) -> tuple:
    """4마켓 공통 검증 → (spec, excluded). 옵션 있으면 spec['options'] 에 정규화 리스트."""
    name = (draft.name or '').strip()
    if not name:
        raise CompileError('상품명이 비어 있습니다.')

    price = coerce_int(draft.sale_price, '판매가')
    if price is None or price <= 0:
        raise CompileError(f'판매가가 0 이하입니다({price}) — 등록을 막습니다.')
    if price % 10 != 0:
        raise CompileError(
            f'판매가는 10원 단위여야 합니다({price}원) — ESM·11번가 공통 규격.')

    options, excluded = _normalize_options(draft, int(price))
    if options:
        stock = sum(o['stock'] for o in options)   # 총재고 = 옵션합
    else:
        stock = coerce_int(draft.stock_quantity, '재고')
        if stock is None or stock <= 0:
            raise CompileError(
                f'재고가 0 이하입니다({stock}) — 이 마켓들은 재고 0 등록이 불가합니다'
                '(ESM·11번가·롯데온 공통 규격).')

    images = loads_json(draft.images_json, [], what='이미지')
    image_url = next((u for u in images if isinstance(u, str) and u.strip()), None)
    if not image_url:
        raise CompileError(
            '대표 이미지 URL 이 없습니다 — 이 마켓들은 공개 URL 을 직접 내려받아 씁니다.')

    detail_html = (draft.detail_html or '').strip()
    if not detail_html:
        raise CompileError('상세설명(HTML)이 비어 있습니다.')

    spec = {'goods_name': name, 'price': int(price), 'stock': int(stock),
            'image_url': image_url.strip(), 'detail_html': detail_html,
            'options': options}
    spec.update(_listing_consts(draft))
    return spec, excluded


#: 화면 글자 → 「면세인가」. 🔴 모르는 글자는 지어내지 않고 과세(False)로 둔다.
#:   「영세」는 사장님 확정으로 선택지에서 뺐다 — 쿠팡·옥션·G마켓엔 보낼 칸이 없다.
_VAT_FREE = {'면세': True, '과세': False}


def _listing_consts(draft) -> dict:
    """4마켓 공통 등록 상수 — 초안 칸 → spec.

    🔴 **여기서 마켓별 코드로 바꾸지 않는다.** 같은 「면세」라도 11번가는 '02',
      ESM 은 `true`, 쿠팡은 'FREE' 다. 뜻만 담아 넘기고 변환은 각 조립기가 한다 —
      한 곳에서 코드로 굳히면 마켓이 늘 때마다 여기가 갈래로 뒤덮인다.

    🔴 바코드는 `barcode.for_market` 을 **거쳐서** 담는다. 자체 생성분은
      어느 마켓에도 안 보낸다(사장님 확정) — 그 판단을 조립기마다 되풀이하면
      한 곳만 빠뜨렸을 때 조용히 새어 나간다.
    """
    from lemouton.inventory import barcode as BC
    return {
        'tax_type': str(getattr(draft, 'tax_type', '') or '').strip(),
        'manufacturer': str(getattr(draft, 'manufacturer', '') or '').strip(),
        'model_no': str(getattr(draft, 'model_no', '') or '').strip(),
        # 마켓 이름은 조립기가 알고 있지만, 자체/공식 판별은 값만 보면 되므로
        # 여기서 한 번에 거른다(BC.is_internal 은 값의 앞자리만 본다).
        'barcode': ('' if BC.is_internal(getattr(draft, 'barcode', ''))
                    else str(getattr(draft, 'barcode', '') or '').strip()),
        # 칸이 없는 옛 초안(getattr 기본 True)은 전연령 그대로.
        'minor_purchasable': bool(getattr(draft, 'minor_purchasable', True)),
    }


def compile_auction_gmarket(draft, *, category_code) -> tuple:
    """→ (spec, excluded). category_code = 'ESM캣코드/사이트캣코드'."""
    require_category(category_code, what='ESM 카테고리')
    raw = str(category_code).strip()
    if '/' not in raw:
        raise CompileError(
            '옥션·G마켓 카테고리는 "ESM카테고리코드/사이트카테고리코드" 형식입니다 '
            '(예: 00120005002000000000/37500700) — 기존 상품 상세에서 확인할 수 있어요.')
    cat_code, site_cat_code = (p.strip() for p in raw.split('/', 1))
    if not cat_code or not site_cat_code:
        raise CompileError('ESM/사이트 카테고리 중 한쪽이 비어 있습니다.')
    spec, excluded = _base_spec(draft)
    spec.update({'cat_code': cat_code, 'site_cat_code': site_cat_code})
    # ── 등록 상수를 ESM 이 쓰는 이름·모양으로 (이 파일의 기존 관례: compile_eleven11 도
    #    disp_ctgr_no·prd_nm 처럼 마켓 이름으로 담는다) ─────────────────────────
    #    지도 근거: itemAddtionalInfo>isVatFree(Boolean) · itemBasicInfo>catalog>
    #              {modelName, barCode} · itemAddtionalInfo>isAdultProduct(필수)
    #    ⚠️ 제조사·검색태그는 ESM 일반 상품에 **칸이 없다**(제조사는 「예약설치 상품」
    #      전용 Install>InstallMakerId 뿐) — 지어내서 아무 칸에나 넣지 않는다.
    spec.update({
        'is_vat_free': _VAT_FREE.get(spec['tax_type'], False),
        'bar_code': spec['barcode'],
        'is_adult_product': not spec['minor_purchasable'],
    })
    # ★ [2026-08-24 Phase 4-5] 가격비교 노출 — 지도 실측
    #     `addtionalInfo > pcs > isUse` (Boolean) · 쿠폰 `isUseIacPcsCoupon` (옥션용)
    #   🔴 G마켓 쿠폰 칸(`isUseGmkPcsCoupon`)은 지도에 **「사용불가」**로 적혀 있다 —
    #     마켓이 설정을 막아 둔 것이라 우리가 보낼 수 없다. 노출 여부만 가능.
    #   정책이 말하지 않으면 **칸을 아예 안 넣는다** — 지금까지 안 보내던 그대로.
    _pcs = getattr(draft, 'price_compare_expose', None)
    if _pcs is not None:
        spec['pcs_use'] = bool(_pcs)
    _pcs_cp = getattr(draft, 'price_compare_coupon', None)
    if _pcs_cp is not None:
        spec['pcs_coupon_iac'] = bool(_pcs_cp)
    return spec, excluded


def compile_eleven11(draft, *, category_code) -> tuple:
    """→ (spec, excluded). category_code = 최하위 dispCtgrNo."""
    require_category(category_code, what='11번가 카테고리(dispCtgrNo)')
    spec, excluded = _base_spec(draft)
    as_detail = (draft.after_service_guide or '').strip() \
        or (draft.after_service_phone or '').strip()
    if not as_detail:
        raise CompileError(
            'A/S 안내가 비어 있습니다 — 11번가는 asDetail 이 공백 불가(필수)입니다.')
    # ★ [2026-07-23 리뷰 C2] 예전에는 브랜드가 비면 **상품명 첫 토큰**을 브랜드로 합성해
    #   보냈다(`or spec['goods_name'].split()[0]`). 「나이키 에어포스 1」이면 brand='나이키'
    #   가 되어, 우리 지재권 제한표는 「브랜드 없음 = 무판정」으로 통과시키는데 11번가에는
    #   제한 브랜드가 그대로 올라갔다. 지어내지 않는다 — 없으면 막는다.
    brand = (draft.brand or '').strip()
    if not brand:
        raise CompileError(
            '브랜드가 비어 있습니다 — 11번가는 브랜드가 필수인데, 상품명에서 지어내지 '
            '않습니다(제한 브랜드가 그대로 올라갑니다). 실제 브랜드를 넣어 주세요.')
    spec.update({
        'disp_ctgr_no': str(category_code).strip(),
        'prd_nm': spec['goods_name'],
        'brand': brand,
        'as_detail': as_detail,
        'return_cost': coerce_int(draft.return_fee, '반품배송비') or 0,
        'exchange_cost': (coerce_int(draft.return_fee, '반품배송비') or 0) * 2,
    })
    # ★ [2026-08-24 Phase 4-5] 가격비교 노출 — 지도 실측
    #     `prcCmpExpYn` (Y/N, 선택) · 할인적용 `prcDscCmpExpYn` (Y/N, 선택)
    #   정책이 말하지 않으면 **칸을 아예 안 넣는다** — 지금까지 안 보내던 그대로.
    _pcs = getattr(draft, 'price_compare_expose', None)
    if _pcs is not None:
        spec['prc_cmp_exp_yn'] = 'Y' if _pcs else 'N'
    _pcs_cp = getattr(draft, 'price_compare_coupon', None)
    if _pcs_cp is not None:
        spec['prc_dsc_cmp_exp_yn'] = 'Y' if _pcs_cp else 'N'
    return spec, excluded


def compile_lotteon(draft, *, category_code) -> tuple:
    """→ (spec, excluded). category_code = 본보기 기존 상품번호(spdNo).

    같은 계정·비슷한 카테고리의 판매중 상품번호를 넣어야 카테고리·고시·배송·출하지
    값이 그대로 통한다(등록 body = 그 상품 detail 스키마 — 2026-07-21 실측).
    """
    require_category(category_code, what='롯데온 본보기 상품번호(spdNo)')
    tpl = str(category_code).strip()
    if not tpl.upper().startswith('LO'):
        raise CompileError(
            '롯데온 칸에는 카테고리 번호가 아니라 **본보기 기존 상품번호**(LO 로 시작, '
            f'예: LO2727500650)를 넣어 주세요. 받은 값: {tpl!r}')
    spec, excluded = _base_spec(draft)
    spec.update({'template_spd_no': tpl, 'spd_nm': spec['goods_name']})
    return spec, excluded
