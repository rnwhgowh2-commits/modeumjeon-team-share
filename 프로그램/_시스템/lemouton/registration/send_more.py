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


def _env_prefix(market: str, account_key: str = ''):
    """market 활성 UploadAccount env_prefix.

    account_key 지정(≠''·≠'default') 시 그 계정을 찾는다 — **없으면 예외**
    (기본 계정 폴백 금지: 기록은 acctB 인데 전송은 기본 계정으로 나가는 거짓 장부 방지.
    선례: 롯데온 trNo 8888 사고 — 계정 식별자는 계정 것만).
    미지정이면 첫 활성 계정(없으면 None=전역 기본).
    """
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        q = s.query(UploadAccount).filter_by(market=market, is_active=True)
        if account_key and account_key != 'default':
            acct = q.filter_by(account_key=account_key).first()
            if acct is None:
                have = [a.account_key for a in q.order_by(UploadAccount.id).all()]
                raise PrereqError(
                    f'{market} 계정 {account_key!r} 을 찾을 수 없습니다(활성 계정: {have}) — '
                    '기본 계정으로 대신 보내지 않습니다(기록·전송 계정 불일치 방지).')
            return acct.env_prefix
        acct = q.order_by(UploadAccount.id).first()
        return acct.env_prefix if acct else None
    finally:
        s.close()


# ── ESM(옥션·G마켓) ─────────────────────────────────────────────

def _register_esm(market: str, spec: dict, account_key: str = '') -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.esm.products import (
        search_goods, get_goods_detail, extract_register_prereq,
        build_esm_register_payload, register_goods)

    client = MF._esm_client(market, _env_prefix(market, account_key))
    if client is None:
        raise PrereqError(f'{market} 계정이 없습니다 — 판매처 계정을 먼저 등록해 주세요.')

    # 판매중(11) 기존 상품에서 선행자원 수확 — ★ ESM 은 마스터 카탈로그가 공용이라
    #   siteId 검색에도 반대 사이트 전용 상품이 섞인다(예: 옥션 전용은 gmkt 발송정책 0).
    #   선행자원이 다 찰 때까지 후보를 순회한다(최대 15건 상세조회 — 라이브 실측 함정).
    _NEED = ('place_no', 'dispatch_policy_no', 'return_addr_no',
             'delivery_company_no', 'official_notice_no')
    found = search_goods(client=client, market=market, sell_status='11', page_size=30)
    items = [it for it in (found.get('items') or []) if isinstance(it, dict)]
    if not items:
        raise PrereqError(
            f'{market} 판매중 기존 상품이 없어 선행자원(출하지·발송정책·고시)을 못 얻습니다.')
    prereq = None
    tried = []
    for it in items[:15]:
        goods_no = it.get('goodsNo')
        if not goods_no:
            continue
        cand = extract_register_prereq(get_goods_detail(goods_no, client=client), market)
        missing = [k for k in _NEED if not cand.get(k)]
        if not missing:
            prereq = cand
            break
        tried.append(f'{goods_no}(빈값 {missing})')
    if prereq is None:
        raise PrereqError(
            f'{market} 선행자원을 채울 본보기 상품을 못 찾았습니다 — 훑은 후보: '
            f'{"; ".join(tried[:5])} — 셀러센터에서 그 사이트 발송정책·반품지 설정을 확인해 주세요.')

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
    goods_no_new = str(result['goodsNo'])

    # [2026-07-21 옵션 지원] 옵션 있으면 등록 직후 recommended-options PUT 로 부착.
    #   봉투 구조는 계정의 기존 조합형 옵션상품 GET 봉투를 실측 본보기로 미러링
    #   (과거이력: PUT 은 GET 봉투 echo-back 필수·details 만 보내면 400).
    #   부착 실패 = 옵션 없는 단일상품이 판매중으로 남는 것 → 즉시 판매중지로 회수 후
    #   에러 표면화(상품번호를 메시지에 남겨 셀러센터 확인 가능하게 — 미아 방지).
    if spec.get('options'):
        try:
            _attach_esm_options(market, client, goods_no_new, items, spec['options'])
        except Exception as e:  # noqa: BLE001
            from shared.platforms.esm.inventory import set_sold_out
            try:
                set_sold_out(goods_no_new, market, client=client)
                rollback = '상품은 판매중지로 내려두었습니다'
            except Exception:  # noqa: BLE001 — 등록 직후 2~3분 수정금지 창이면 실패 가능
                rollback = ('⚠️판매중지 실패 — 셀러센터에서 직접 내려주세요'
                            '(등록 직후 2~3분은 수정 불가)')
            raise PrereqError(
                f'{market} 상품({goods_no_new})은 등록됐지만 옵션 부착에 실패했습니다: '
                f'{e} / {rollback}') from e
    return {'product_id': goods_no_new, 'raw': result}


def _attach_esm_options(market: str, client, goods_no: str, search_items: list,
                        options: list) -> None:
    """신규 상품에 조합형(색상×사이즈) 옵션 부착 — PUT recommended-options.

    봉투 본보기 = 같은 계정의 기존 조합형 옵션상품(GET recommended-options 실응답).
    details 원소도 본보기 구조를 복제해 값(옵션값·재고·추가금)만 교체한다(추측 금지).
    """
    from shared.platforms.esm.products import site_field, _ci_get

    # 1) 조합형 봉투 본보기 찾기 — 검색 결과에서 옵션 있는 상품의 GET 봉투를 순회 수확
    envelope = None
    for it in search_items[:15]:
        gno = it.get('goodsNo')
        if not gno or str(gno) == str(goods_no):
            continue
        try:
            env = client.request(
                method='GET', path=f'/item/v1/goods/{gno}/recommended-options')
        except Exception:  # noqa: BLE001 — 본보기 후보 실패는 다음 후보로
            continue
        body = env.get('data') if isinstance(env.get('data'), dict) else env
        if isinstance(body, dict) and _ci_get(body, 'type') in (1, 2, '1', '2'):
            envelope = body
            break
    if envelope is None:
        raise PrereqError(
            f'{market} 옵션 봉투 본보기(기존 옵션상품)를 못 찾았습니다 — '
            '옵션 상품이 하나라도 판매중이어야 구조를 복제할 수 있습니다.')

    # 2) 본보기 details[0] 구조 복제 → 우리 옵션으로 교체
    grp_key = 'combination' if _ci_get(envelope, 'combination') else 'independent'
    grp = _ci_get(envelope, grp_key) or {}
    tpl_details = _ci_get(grp, 'details') or []
    if not tpl_details:
        raise PrereqError(f'{market} 봉투 본보기에 details 가 없습니다(구조 미확보).')
    d_tpl = tpl_details[0]
    skey = site_field(market)   # iac|gmkt
    new_details = []
    for o in options:
        d = {k: v for k, v in d_tpl.items()
             if k not in ('optSeq', 'manageCode')}   # 식별자는 마켓이 새로 발급
        # 옵션값 — 본보기의 값 필드 형태를 따라 교체(조합형: recommendedOptValue*)
        for vk in list(d.keys()):
            lk = str(vk).lower()
            if lk.startswith('recommendedoptvalue') and isinstance(d.get(vk), dict):
                # {koreanText: ...} 직접입력 형태
                idx = '1' if lk.endswith('1') or lk.endswith('value') else '2'
                d[vk] = dict(d[vk])
                d[vk]['koreanText'] = o['color'] if idx == '1' else o['size']
        # 재고·추가금·품절 — 사이트별 키(실측: qty {gmkt,iac}·isSoldOutSite)
        qty = d.get('qty') if isinstance(d.get('qty'), dict) else {}
        qty = dict(qty)
        qty[skey] = int(o['stock'])
        d['qty'] = qty
        d['addAmnt'] = int(o.get('extra_price') or 0)
        d['isSoldOut'] = False
        if o.get('sku'):
            d['manageCode'] = o['sku']
        new_details.append(d)

    put_body = {k: v for k, v in envelope.items()}
    put_body[grp_key] = dict(grp)
    put_body[grp_key]['details'] = new_details
    resp = client.request(
        method='PUT', path=f'/item/v1/goods/{goods_no}/recommended-options',
        body=put_body)
    rc = _ci_get(resp or {}, 'resultCode')
    if rc is not None and str(rc) not in ('0', '0000', 'SUCCESS', 'OK'):
        raise PrereqError(
            f'옵션 PUT 거부 resultCode={rc} {str(_ci_get(resp, "message"))[:200]}')


# ── 11번가 ─────────────────────────────────────────────────────

def _addr_seq(xml_text: str) -> str | None:
    m = re.search(r'<addrSeq>\s*(\d+)\s*</addrSeq>', xml_text or '')
    return m.group(1) if m else None


def _register_eleven11(spec: dict, account_key: str = '') -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.eleven11.products import build_register_xml, register_product

    client = MF._eleven11_client(_env_prefix('eleven11', account_key))
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

def _register_lotteon(spec: dict, account_key: str = '') -> dict:
    from lemouton.uploader import market_fetch as MF
    from shared.platforms.lotteon.products import (
        get_product_detail, build_register_payload, register_product)

    client = MF._lotteon_client(_env_prefix('lotteon', account_key))
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


def register_live(market: str, spec: dict, account_key: str = '') -> dict:
    """마켓별 실등록 디스패치 → {'product_id', 'raw'}. 실패는 예외.

    account_key: UploadAccount.account_key. ''/'default'=첫 활성 계정.
    """
    if market in ('auction', 'gmarket'):
        return _register_esm(market, spec, account_key)
    if market == 'eleven11':
        return _register_eleven11(spec, account_key)
    if market == 'lotteon':
        return _register_lotteon(spec, account_key)
    raise ValueError(f'send_more 가 모르는 마켓: {market!r}')
