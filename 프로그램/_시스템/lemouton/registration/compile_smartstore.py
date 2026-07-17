# -*- coding: utf-8 -*-
"""ProductDraft → 스마트스토어 등록 payload (순수 함수).

기존 shared/platforms/smartstore/create_product.py 의 ProductRegistration 은
  · productInfoProvidedNoticeType: "SHOES" 하드코딩
  · 대표이미지 1장 (optionalImages 없음)
  · 옵션 없음 (stockQuantity 평면)
이라 대량등록에 못 쓴다. 그 dataclass 는 모음전 경로가 쓰는 중이라 두고, 여기서
payload 를 직접 만든다.

statusType 은 서버가 무시하고 항상 SALE 로 등록하므로, 초안 효과를 원하면
등록 직후 change_status.mark_suspension() 을 호출해야 한다 (service.py 담당).
"""
import json

from lemouton.registration.notice import build_notice, NoticeError
from lemouton.registration.options import build_smartstore_options, OptionError

_CDN_HOST = 'shop-phinf.pstatic.net'


class CompileError(ValueError):
    """드래프트를 마켓 payload 로 만들 수 없음. 조용한 폴백 금지."""


def _loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def compile_smartstore(draft, *, category_code: str):
    """ProductDraft → (POST /v2/products body, 제외된 옵션 목록).

    excluded 를 함께 돌려주는 이유: 사용자가 폼에 입력한 옵션 행이 품절·확인불가로
    빠져도 화면은 "성공" 만 보여주던 조용한 실패를 막기 위함. 상위(서비스·라우트)가
    사용자에게 무엇이 왜 빠졌는지 알려야 한다.

    Returns:
        (body: dict, excluded: list[dict])  — excluded 원소 = {color,size,stock,reason}

    Raises:
        CompileError: 카테고리·이미지·판매가 누락 / 비 CDN 이미지 / 고시·옵션 문제 등
    """
    if not category_code:
        raise CompileError('카테고리(leafCategoryId)가 필요합니다.')

    sale_price = int(draft.sale_price or 0)
    if sale_price <= 0:
        raise CompileError(f'판매가가 0 이하입니다({sale_price}) — 등록을 막습니다.')

    images = _loads(draft.cdn_images_json, [])
    if not images:
        raise CompileError(
            '네이버 CDN 이미지가 없습니다 — 스스는 CDN URL 만 받습니다. 업로드가 먼저입니다.')
    bad = [u for u in images if _CDN_HOST not in u]
    if bad:
        raise CompileError(
            f'스스는 네이버 CDN({_CDN_HOST}) 이미지만 받습니다. 외부 URL: {bad}')

    # NoticeError = 상위 예외(NoticeFieldMissing·UnknownNoticeType). 하위를 각각 잡으면
    # 모르는 고시유형이 raw ValueError 로 새어나가 500 이 된다 (notice_type 은 UI 입력).
    try:
        notice = build_notice(draft.notice_type, _loads(draft.notice_json, {}))
    except NoticeError as e:
        raise CompileError(f'상품고시정보 미완성 — {e}') from e

    # ★ A/S 연락처에 폴백을 넣지 않는다. 기존 모음전 코드(create_product.py:87-88)는
    #   `or "02-0000-0000"` 로 때우는데, 그건 실제 판매 상품에 가짜 전화번호를 게시하는
    #   것이다. 프로젝트 원칙(폴백 금지·못하면 '확인불가')에 어긋나므로 여기선 막는다.
    if not (draft.after_service_phone or '').strip():
        raise CompileError('A/S 전화번호가 없습니다 — 실제 판매 상품에 가짜 번호를 올릴 수 없습니다.')
    if not (draft.after_service_guide or '').strip():
        raise CompileError('A/S 안내가 없습니다.')

    # 라이브 검증된 payload(create_product.py:81-94, 2026-04-22)와 같은 필드 구성.
    # minorPurchasable·afterServiceInfo 를 빠뜨리면 실등록이 거부된다.
    detail_attr = {
        'originAreaInfo': {
            'originAreaCode': draft.origin_area_code or '0200037',
            'importer': draft.importer or '-',
        },
        'minorPurchasable': bool(draft.minor_purchasable),
        'afterServiceInfo': {
            'afterServiceTelephoneNumber': draft.after_service_phone,
            'afterServiceGuideContent': draft.after_service_guide,
        },
        'productInfoProvidedNotice': notice,
    }

    opts = _loads(draft.options_json, [])
    excluded = []
    if opts:
        # OptionError = 상위 예외. NoSellableOption 만 잡으면 OptionValueInvalid(잘못된 재고값·
        # 중복옵션·빈 색상)가 raw ValueError 로 새어나가 500 이 된다.
        try:
            # sale_price 를 넘기는 이유: 스스는 옵션가(price)만 받고 절대가는 서버가
            # salePrice + price 로 계산한다 → 음수 옵션가로 최종가가 0 이하가 되는 구멍이
            # 쿠팡과 똑같이 존재한다. 빌더가 계산가를 검증하려면 기준가를 알아야 한다.
            groups, combos, excluded = build_smartstore_options(opts, sale_price=sale_price)
        except OptionError as e:
            raise CompileError(f'옵션 문제 — {e}') from e
        detail_attr['optionInfo'] = {
            # 미입력 시 기본이 CREATE(등록순)이고 그게 곧 구매자 드롭다운 순서다.
            # options.py 가 정렬 책임을 지므로 명시해 의도를 못박는다.
            'optionCombinationSortType': 'CREATE',
            'optionCombinationGroupNames': groups,
            'optionCombinations': combos,
        }
        stock = sum(c['stockQuantity'] for c in combos)
    else:
        stock = int(draft.stock_quantity or 0)

    origin_product = {
        # 서버가 무시하고 항상 SALE 로 등록한다. 초안 효과는 등록 직후
        # change_status.mark_suspension() 으로 낸다 (service.py 담당).
        'statusType': 'SUSPENSION',
        'leafCategoryId': str(category_code),
        'name': draft.name,
        'salePrice': sale_price,
        'stockQuantity': stock,
        'images': {
            'representativeImage': {'url': images[0]},
            'optionalImages': [{'url': u} for u in images[1:]],
        },
        'detailContent': draft.detail_html or '',
        'detailAttribute': detail_attr,
    }
    if draft.normal_price:
        origin_product['normalPrice'] = int(draft.normal_price)

    body = {
        'originProduct': origin_product,
        'smartstoreChannelProduct': {
            'channelProductDisplayStatusType': 'ON',
            'naverShoppingRegistration': True,
        },
    }
    return body, excluded
