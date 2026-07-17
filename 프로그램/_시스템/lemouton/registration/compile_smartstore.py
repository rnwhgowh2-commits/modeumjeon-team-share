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
from lemouton.registration.compile_common import (
    CompileError, coerce_int, loads_json, require_category,
)
from lemouton.registration.notice import build_notice, NoticeError
from lemouton.registration.options import build_smartstore_options, OptionError

_CDN_HOST = 'shop-phinf.pstatic.net'


def compile_smartstore(draft, *, category_code: str, require_cdn_images: bool = True):
    """ProductDraft → (POST /v2/products body, 제외된 옵션 목록).

    excluded 를 함께 돌려주는 이유: 사용자가 폼에 입력한 옵션 행이 품절·확인불가로
    빠져도 화면은 "성공" 만 보여주던 조용한 실패를 막기 위함. 상위(서비스·라우트)가
    사용자에게 무엇이 왜 빠졌는지 알려야 한다.

    require_cdn_images: 스스 CDN 이미지는 라이브 업로드로만 만들 수 있는데(image_prep),
        업로드는 LIVE 게이트 뒤에서만 돈다. 서비스는 게이트 앞 '예비 컴파일' 을 이걸 False 로
        불러 A/S·옵션·고시 오류를 먼저 잡고 '실등록 꺼짐' 메시지를 보이게 한다. 게이트 뒤에서
        이미지를 업로드해 cdn_images_json 을 채운 뒤 True 로 재컴파일해 진짜 body 를 만든다.
        False 면 이미지 검사·images 블록을 생략한다(그 body 로 실전송하면 안 된다).

    Returns:
        (body: dict, excluded: list[dict])  — excluded 원소 = {color,size,stock,reason}

    Raises:
        CompileError: 카테고리·이미지·판매가 누락 / 비 CDN 이미지 / 고시·옵션 문제 등
    """
    require_category(category_code, what='카테고리(leafCategoryId)')

    # 폼·엑셀 붙여넣기가 '75,800'·'75800.0' 을 보내도 500 대신 깔끔히 처리(coerce_int).
    sale_price = coerce_int(draft.sale_price, '판매가')
    if sale_price is None or sale_price <= 0:
        raise CompileError(f'판매가가 0 이하입니다({sale_price}) — 등록을 막습니다.')

    images = loads_json(draft.cdn_images_json, [], what='이미지')
    if require_cdn_images:
        if not images:
            raise CompileError(
                '네이버 CDN 이미지가 없습니다 — 스스는 CDN URL 만 받습니다. 업로드가 먼저입니다.')
        # ★ 원소 타입을 믿지 않는다. cdn_images_json='[null]'·'[123]' 이면 아래 `_CDN_HOST
        #   not in u` 가 TypeError(=500) 를 내고, [{"url":..}] 는 dict 키 멤버십으로 검사를
        #   통과해 {'url': {...}} 라는 깨진 body 가 라이브로 나간다. 문자열이 아니면 막는다.
        non_str = [u for u in images if not isinstance(u, str) or not u.strip()]
        if non_str:
            raise CompileError(
                f'이미지 URL 이 문자열이 아닙니다(손상된 데이터): {non_str}')
        bad = [u for u in images if _CDN_HOST not in u]
        if bad:
            raise CompileError(
                f'스스는 네이버 CDN({_CDN_HOST}) 이미지만 받습니다. 외부 URL: {bad}')

    # NoticeError = 상위 예외(NoticeFieldMissing·UnknownNoticeType). 하위를 각각 잡으면
    # 모르는 고시유형이 raw ValueError 로 새어나가 500 이 된다 (notice_type 은 UI 입력).
    try:
        notice = build_notice(draft.notice_type, loads_json(draft.notice_json, {}, what='고시'))
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

    opts = loads_json(draft.options_json, [], what='옵션')
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
        flat = coerce_int(draft.stock_quantity, '재고')
        stock = 0 if flat is None else flat

    origin_product = {
        # statusType 은 서버가 무시하지만 라이브 검증본과 동일하게 SUSPENSION 을 보낸다
        # (초안 전환은 등록 후 change_status.mark_suspension() — 서비스 몫).
        'statusType': 'SUSPENSION',
        'leafCategoryId': str(category_code),
        'name': draft.name,
        'salePrice': sale_price,
        'stockQuantity': stock,
        'detailContent': draft.detail_html or '',
        'detailAttribute': detail_attr,
    }
    # require_cdn_images=False(예비 컴파일)면 images 키를 아예 넣지 않는다 — 이 body 는
    # 오류 확인용이지 실전송용이 아니다. 실전송 body 는 게이트 뒤 재컴파일(True)로 만든다.
    if require_cdn_images:
        origin_product['images'] = {
            'representativeImage': {'url': images[0]},
            'optionalImages': [{'url': u} for u in images[1:]],
        }
    # 코어스 후 값으로 판단한다. 원시 '0'·'0.0' 은 문자열이라 truthy → 안 그러면
    # normalPrice: 0(0-정가 오등록)이 나간다. int 0 만 falsy 라 원시 가드로는 못 막는다.
    np = coerce_int(draft.normal_price, '정상가')
    if np:
        origin_product['normalPrice'] = np

    body = {
        'originProduct': origin_product,
        'smartstoreChannelProduct': {
            'channelProductDisplayStatusType': 'ON',
            'naverShoppingRegistration': True,
        },
    }
    return body, excluded
