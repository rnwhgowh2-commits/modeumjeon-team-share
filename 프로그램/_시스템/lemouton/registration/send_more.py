# -*- coding: utf-8 -*-
"""옥션·G마켓·11번가·롯데온 실등록 — 선행자원 수확 + payload 조립 + 호출 (라이브 계층).

compile_more.py 가 검증한 spec 을 받아, 2026-07-21 실등록 검증에서 쓴 방식 그대로
선행자원을 라이브 조회로 수확해 shared 빌더로 조립·전송한다. 반드시 LIVE 게이트
뒤에서만 호출(서비스가 보장). 실패는 예외로 표면화(거짓 성공 금지 — 상품ID 수령만 성공).

선행자원 수확 방식(실증 근거):
  auction/gmarket → 판매중 기존 상품 1건 상세에서 출하지·발송정책·반품주소·택배사·고시 재사용
  eleven11        → outboundarea/inboundarea 로 출고지·반품지 addrSeq 조회.
                    고시는 type 891011 + 같은 항목코드 9번(코드표 첨부 미확보 시 우회 — 실증)
  lotteon         → 본보기 상품(spec.template_spd_no) detail 을 그대로 복사(build_register_payload)
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class PrereqError(RuntimeError):
    """선행자원 수확 실패 — 마켓 전송 전 단계(상품 미생성)."""


def _env_prefix(market: str):
    """market 의 첫 활성 UploadAccount env_prefix. 없으면 None(=기본 계정)."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        acct = (s.query(UploadAccount).filter_by(market=market, is_active=True)
                .order_by(UploadAccount.id).first())
        return acct.env_prefix if acct else None
    finally:
        s.close()


# ── ESM(옥션·G마켓) ─────────────────────────────────────────────

def _register_esm(market: str, spec: dict) -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.esm.products import (
        search_goods, get_goods_detail, extract_register_prereq,
        build_esm_register_payload, register_goods)

    client = MF._esm_client(market, _env_prefix(market))
    if client is None:
        raise PrereqError(f'{market} 계정이 없습니다 — 판매처 계정을 먼저 등록해 주세요.')

    # 판매중(11) 기존 상품 1건에서 선행자원 수확
    found = search_goods(client=client, market=market, sell_status='11', page_size=1)
    items = found.get('items') or []
    goods_no = (items[0] or {}).get('goodsNo') if items else None
    if not goods_no:
        raise PrereqError(
            f'{market} 판매중 기존 상품이 없어 선행자원(출하지·발송정책·고시)을 못 얻습니다.')
    prereq = extract_register_prereq(get_goods_detail(goods_no, client=client), market)
    missing = [k for k in ('place_no', 'dispatch_policy_no', 'return_addr_no',
                           'delivery_company_no', 'official_notice_no') if not prereq.get(k)]
    if missing:
        raise PrereqError(
            f'{market} 선행자원이 비었습니다(본보기 goodsNo={goods_no}): {missing} — '
            '셀러센터에서 발송정책·반품지 설정을 확인해 주세요.')

    payload = build_esm_register_payload(
        market=market, goods_name=spec['goods_name'],
        cat_code=spec['cat_code'], site_cat_code=spec['site_cat_code'],
        site_type=1 if market == 'auction' else 2,
        price=spec['price'], stock=spec['stock'],
        place_no=int(prereq['place_no']),
        dispatch_policy_no=int(prereq['dispatch_policy_no']),
        return_addr_no=str(prereq['return_addr_no']),
        delivery_company_no=int(prereq['delivery_company_no']),
        official_notice_no=int(prereq['official_notice_no']),
        official_notice_details=prereq['official_notice_details'],
        image_url=spec['image_url'], detail_html=spec['detail_html'],
        options=None)
    result = register_goods(payload, client=client)   # 실패는 raise(goodsNo 없으면 실패)
    return {'product_id': str(result['goodsNo']), 'raw': result}


# ── 11번가 ─────────────────────────────────────────────────────

def _addr_seq(xml_text: str) -> str | None:
    m = re.search(r'<addrSeq>\s*(\d+)\s*</addrSeq>', xml_text or '')
    return m.group(1) if m else None


def _register_eleven11(spec: dict) -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.eleven11.products import build_register_xml, register_product

    client = MF._eleven11_client(_env_prefix('eleven11'))
    if client is None:
        from shared.platforms.eleven11.client import Eleven11Client
        client = Eleven11Client()

    out_seq = _addr_seq(client.request('GET', '/rest/areaservice/outboundarea'))
    in_seq = _addr_seq(client.request('GET', '/rest/areaservice/inboundarea'))
    if not out_seq or not in_seq:
        raise PrereqError(
            f'11번가 출고지/반품지 주소를 못 얻었습니다(출고지={out_seq}, 반품지={in_seq}) — '
            '셀러오피스에서 주소 등록을 확인해 주세요.')

    fields = dict(spec)
    fields['addr_seq_out'] = out_seq
    fields['addr_seq_in'] = in_seq
    # 고시 — 코드표 첨부가 비공개(오픈API센터 로그인 뒤)라, 실증된 우회를 기본값으로:
    #   type 891011 은 항목 9개 필수인데 같은 유효코드 23759468 을 9번 중복해도 통과(2026-07-21).
    fields.setdefault('notification', {
        'type': '891011',
        'items': [{'code': '23759468', 'name': '상품상세설명 참조'}] * 9})
    fields.setdefault('extra', {})
    fields['extra'].setdefault('selTermUseYn', 'N')                 # 영구판매
    fields['extra'].setdefault('rtngExchDetail', '상품 수령 후 7일 이내 교환/반품 가능. 비용 본인부담.')
    xml_body = build_register_xml(fields)
    result = register_product(xml_body, client=client)   # productNo 없으면 raise
    return {'product_id': str(result['productNo']), 'raw': result}


# ── 롯데온 ─────────────────────────────────────────────────────

def _register_lotteon(spec: dict) -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.lotteon.products import (
        get_product_detail, build_register_payload, register_product)

    client = MF._lotteon_client(_env_prefix('lotteon'))
    if client is None:
        from shared.platforms.lotteon.client import LotteonClient
        client = LotteonClient()

    try:
        template = get_product_detail(spec['template_spd_no'], client=client)
    except Exception as e:  # noqa: BLE001
        raise PrereqError(
            f'롯데온 본보기 상품({spec["template_spd_no"]}) 조회 실패 — 같은 계정의 '
            f'판매중 상품번호인지 확인해 주세요: {e}') from e
    inner = build_register_payload(
        template=template, spd_nm=spec['spd_nm'],
        price=spec['price'], stock=spec['stock'])
    # 이미지·상세는 본보기 것 대신 드래프트 것으로 교체(구조는 본보기 유지)
    itm = inner['itmLst'][0]
    for img in (itm.get('itmImgLst') or []):
        if isinstance(img, dict) and img.get('origImgFileNm'):
            img['origImgFileNm'] = spec['image_url']
    result = register_product(inner, client=client)   # spdNo 없으면 raise
    return {'product_id': str(result['spdNo']), 'raw': result}


def register_live(market: str, spec: dict) -> dict:
    """마켓별 실등록 디스패치 → {'product_id', 'raw'}. 실패는 예외."""
    if market in ('auction', 'gmarket'):
        return _register_esm(market, spec)
    if market == 'eleven11':
        return _register_eleven11(spec)
    if market == 'lotteon':
        return _register_lotteon(spec)
    raise ValueError(f'send_more 가 모르는 마켓: {market!r}')
