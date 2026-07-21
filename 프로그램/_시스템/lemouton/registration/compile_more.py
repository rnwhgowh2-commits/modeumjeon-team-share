# -*- coding: utf-8 -*-
"""ProductDraft → 옥션·G마켓·11번가·롯데온 등록 스펙 (순수 함수).

2026-07-21 4대 마켓 실등록→판매중지 라이브 검증에서 발굴한 스키마의 파이프라인 이식.
스스·쿠팡(compile_smartstore/coupang)과 달리 이 마켓들은 **선행자원**(출하지·발송정책·
주소코드·본보기 상품)이 라이브 조회로만 얻어져서, 여기서는 draft 검증·정규화만 하고
(순수 함수 유지) 실제 payload 조립은 send_more.py 가 게이트 뒤에서 수확+조립한다.

★ 1차 범위 = 무옵션(단일) 상품만. 옵션 매핑(ESM 옵션값번호·11번가 멀티옵션 XML·
  롯데온 사전 옵션값)은 마켓별 추가 발굴이 필요해 명시 에러로 표면화한다(조용한 누락 금지).

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


def _base_spec(draft) -> dict:
    """4마켓 공통 검증 — 무옵션·재고>0·판매가 10원단위·이미지·상품명."""
    options = loads_json(draft.options_json, [], what='옵션')
    if options:
        raise CompileError(
            '옥션·G마켓·11번가·롯데온 등록은 1차로 무옵션(단일) 상품만 지원합니다 — '
            f'옵션 {len(options)}개가 입력돼 있어 막습니다(조용히 버리지 않음). '
            '옵션 상품은 스스·쿠팡으로 등록하거나 옵션 지원(다음 단계)을 기다려 주세요.')

    name = (draft.name or '').strip()
    if not name:
        raise CompileError('상품명이 비어 있습니다.')

    price = coerce_int(draft.sale_price, '판매가')
    if price is None or price <= 0:
        raise CompileError(f'판매가가 0 이하입니다({price}) — 등록을 막습니다.')
    if price % 10 != 0:
        raise CompileError(
            f'판매가는 10원 단위여야 합니다({price}원) — ESM·11번가 공통 규격.')

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

    return {'goods_name': name, 'price': int(price), 'stock': int(stock),
            'image_url': image_url.strip(), 'detail_html': detail_html}


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
    spec = _base_spec(draft)
    spec.update({'cat_code': cat_code, 'site_cat_code': site_cat_code})
    return spec, []


def compile_eleven11(draft, *, category_code) -> tuple:
    """→ (spec, excluded). category_code = 최하위 dispCtgrNo."""
    require_category(category_code, what='11번가 카테고리(dispCtgrNo)')
    spec = _base_spec(draft)
    as_detail = (draft.after_service_guide or '').strip() \
        or (draft.after_service_phone or '').strip()
    if not as_detail:
        raise CompileError(
            'A/S 안내가 비어 있습니다 — 11번가는 asDetail 이 공백 불가(필수)입니다.')
    spec.update({
        'disp_ctgr_no': str(category_code).strip(),
        'prd_nm': spec['goods_name'],
        'brand': (draft.brand or '').strip() or spec['goods_name'].split()[0],
        'as_detail': as_detail,
        'return_cost': coerce_int(draft.return_fee, '반품배송비') or 0,
        'exchange_cost': (coerce_int(draft.return_fee, '반품배송비') or 0) * 2,
    })
    return spec, []


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
    spec = _base_spec(draft)
    spec.update({'template_spd_no': tpl, 'spd_nm': spec['goods_name']})
    return spec, []
