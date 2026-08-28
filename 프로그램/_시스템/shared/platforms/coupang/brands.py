# -*- coding: utf-8 -*-
"""쿠팡 브랜드 API 래퍼 — brandId 조회 + 정품코드(UID) 소명 필요 여부 판별.

지도 근거 (`webapp/data/marketplace_api_map.json` · `coupang.brands.brand-search`):
  POST /v2/providers/seller_api/apis/api/v1/marketplace/brands/search
  요청: brandName(필수) · countPerPage(기본 10, **최대 10**) · page(기본 1, 최소 1)
  응답: code(SUCCESS/ERROR) · data.items[] =
        {brandId "KR-5" · brandName · brandLogoUrl · isUIDRequired · allowedUIDTypes[]}
  성공 판정: HTTP 200 이어도 **응답 code == 'SUCCESS'** 를 확인해야 한다.
  오류: 400 "brandName is required" · 401 "Authentication failed"

🔴 이 파일이 지키는 세 가지
  ① **정확일치만 matched=True.** brand-search 는 「브랜드 검색 키워드」라 이름이 비슷한
     남의 브랜드가 딸려 온다(삼바 실측: 해칭룸→해피룸, 모이에토이파리스→아미파리스).
     items[0] 을 그냥 채택하면 **남의 brandId 로 등록**된다.
  ② **「모른다」와 「아니다」를 가른다.** `uid_required=None` 은 판정 불가이지
     「소명 필요 없음(False)」이 아니다. 지도 idTraps(공지 2026-05-27 「상품 식별번호
     (GTIN/모델번호) 입력 정책」 · API 등록 상품 2026-08-01 시행): isUIDRequired=true 인
     브랜드는 상품 식별번호(GTIN·MPN)가 **의무**이고, 임의로 만든 숫자·판매자 내부 SKU 로
     채우면 등록 제한·노출 제한 대상이다. 예외를 삼켜 「자유판매」로 내리면 소명 대상
     브랜드가 그대로 올라가 계정이 정지된다.
  ③ **판정과 무판정을 가른다.** 반환 dict 의 `answered` 는 「쿠팡이 답을 줬나」다.
     쿠팡이 「그런 브랜드 없다」고 답한 것(items=[])은 판정이므로 answered=True 지만,
     401·네트워크 실패·code!=SUCCESS 는 answered=False 다. 캐시(`brand_registry.py`)가
     이 둘을 구분해야 일시적 장애가 「판정 불가」로 굳지 않는다.

책임 밖: 캐시·게이트(막기)·payload 주입. 여기는 마켓에 한 번 묻고 해석만 한다.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError
# 브랜드 이름 비교 키는 이미 하나 있다(대소문자·공백·중간점 무시). 같은 규칙을 여기서
#   다시 짜면 언젠가 한쪽만 고쳐져 답이 갈린다 — 정본을 그대로 읽는다.
#   (brand_restrict.py 는 `re` 만 import 하는 순수 모듈이라 순환 참조가 없다)
from lemouton.registration.brand_restrict import normalize


logger = logging.getLogger(__name__)


#: 지도 실측 — countPerPage 기본 10 · **최대 10**. 넘겨 보내면 400 이다.
MAX_COUNT_PER_PAGE = 10


def _no_verdict(brand_name: str, *, answered: bool) -> dict:
    """판정하지 못했을 때의 반환. 🔴 uid_required 는 None(모름) 이지 False 가 아니다."""
    return {
        'brand': brand_name,
        'brand_id': None,
        'uid_required': None,
        'allowed_uid_types': None,
        'matched': False,
        'answered': answered,
    }


def _bool_or_none(v):
    """Boolean 이 아니면 「모름」. 🔴 "false"·0 을 False 로 바꿔 읽지 않는다.

    여기서 한 번 추측하면 소명 필요한 브랜드가 「소명 필요 없음」으로 굳는다.
    """
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    logger.warning("isUIDRequired 가 Boolean 이 아니다(%r) — 「모름」으로 둔다", v)
    return None


def _list_or_none(v):
    """목록이 아니면 「모름」(None). 🔴 빈 목록 `[]` 은 쿠팡이 준 답이라 그대로 남긴다."""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x or '').strip()]
    if v is None:
        return None
    logger.warning("allowedUIDTypes 가 목록이 아니다(%r) — 「모름」으로 둔다", v)
    return None


def search_brand(
    brand_name: str,
    page: int = 1,
    count_per_page: int = MAX_COUNT_PER_PAGE,
    client: Optional[CoupangClient] = None,
) -> dict:
    """브랜드명으로 쿠팡 브랜드 라이브러리를 검색한다.

    Returns: 항상 dict (예외를 밖으로 내지 않는다 — 이 폴더의 조회형 관례)
        {
          'brand':             조회에 쓴 브랜드 문자열,
          'brand_id':          str|None   — 쿠팡 brandId (예 'KR-5'),
          'uid_required':      bool|None  — 🔴 None 은 **모름**이다,
          'allowed_uid_types': list|None  — 🔴 None 은 모름, `[]` 는 쿠팡이 준 빈 목록,
          'matched':           bool       — **정확일치**했을 때만 True,
          'answered':          bool       — 쿠팡이 판정을 돌려줬나,
        }
    """
    name = str(brand_name or '').strip()
    if not name:
        # 지도 errors: 400 "brandName is required" — 부를 필요가 없다.
        logger.info("브랜드명이 비어 브랜드 검색을 부르지 않는다")
        return _no_verdict(name, answered=False)

    if count_per_page > MAX_COUNT_PER_PAGE:
        logger.warning(
            "countPerPage=%s → %s 로 낮춘다 (지도: 최대 %s · 넘기면 400)",
            count_per_page, MAX_COUNT_PER_PAGE, MAX_COUNT_PER_PAGE,
        )
        count_per_page = MAX_COUNT_PER_PAGE
    count_per_page = max(1, int(count_per_page))
    page = max(1, int(page))

    client = client or CoupangClient()
    path = COUPANG['paths']['brand_search']
    body = {'brandName': name, 'countPerPage': count_per_page, 'page': page}

    try:
        resp = client.request(method='POST', path=path, body=body)
    except Exception as e:
        # 🔴 답을 못 받은 것이지 「소명 필요 없음」이 아니다.
        #
        # ★ [2026-08-24 실측으로 잡음] 예전에는 `except CoupangAPIError` 만 잡았다.
        #   그런데 client.request 는 그것 말고도 던진다 — 재시도를 다 쓰면
        #   `raise last_error`(client.py:210) 로 **원본 예외**가 그대로 나오고,
        #   그 원본은 대개 `requests.RequestException`(타임아웃·연결 끊김)이다.
        #   좁게 잡아 두면 쿠팡이 잠깐 죽었을 때 예외가 밖으로 새어 **등록 전체가
        #   터진다**. 브랜드 조회는 등록을 돕는 곁가지지 등록의 전제가 아니다.
        #
        #   🔴 그렇다고 「소명 필요 없음」으로 바꾸지도 않는다 — answered=False 로
        #     「못 물어봤다」를 남긴다. 모름을 아니다로 바꾸는 게 이 프로젝트의
        #     반복 사고다(uid_required 는 None 그대로).
        logger.warning(
            "브랜드 검색 실패 brand=%s err=%s: %s", name, type(e).__name__, e)
        return _no_verdict(name, answered=False)

    if not isinstance(resp, dict) or resp.get('code') != 'SUCCESS':
        logger.warning(
            "브랜드 검색 비성공 brand=%s code=%s msg=%s",
            name,
            (resp or {}).get('code') if isinstance(resp, dict) else None,
            (resp or {}).get('message') if isinstance(resp, dict) else None,
        )
        return _no_verdict(name, answered=False)

    data = resp.get('data') or {}
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        # 쿠팡이 「그 이름의 브랜드는 없다」고 답한 것 — 이건 판정이다.
        logger.info("브랜드 검색 결과 없음 brand=%s", name)
        return _no_verdict(name, answered=True)

    key = normalize(name)
    if not key:
        # 🔴 비교 키가 비면(브랜드가 특수문자·중간점뿐인 경우) 이름 없는 항목과 우연히
        #   같아져 아무 brandId 나 물어 온다. 판정하지 않는다.
        logger.warning("브랜드 비교 키가 비어 정확일치를 판정할 수 없다 brand=%r", name)
        return _no_verdict(name, answered=True)

    hits = [it for it in items
            if isinstance(it, dict) and normalize(it.get('brandName')) == key]

    if len(hits) > 1:
        # 🔴 정확일치가 둘 이상이면 어느 쪽이 우리 브랜드인지 **모른다**. 첫 번째를
        #   고르는 건 추측이고, 틀리면 남의 brandId 로 등록된다.
        logger.warning(
            "브랜드 정확일치가 %d 건이라 판정할 수 없다 brand=%s 후보=%s",
            len(hits), name, [str(i.get('brandId')) for i in hits],
        )
        return _no_verdict(name, answered=True)

    if not hits:
        # 🔴 후보는 왔지만 정확일치가 없다 — 비슷한 이름을 채택하면 남의 brandId 로 등록된다.
        logger.info(
            "브랜드 정확일치 없음 brand=%s 후보=%s",
            name,
            [str(i.get('brandName')) for i in items
             if isinstance(i, dict)][:MAX_COUNT_PER_PAGE],
        )
        return _no_verdict(name, answered=True)

    it = hits[0]
    return {
        'brand': name,
        # brandId 가 비면 None — 빈 문자열을 payload 에 실어 보내지 않는다.
        'brand_id': str(it.get('brandId') or '').strip() or None,
        'uid_required': _bool_or_none(it.get('isUIDRequired')),
        'allowed_uid_types': _list_or_none(it.get('allowedUIDTypes')),
        'matched': True,
        'answered': True,
    }
