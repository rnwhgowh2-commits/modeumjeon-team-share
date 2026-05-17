"""[E] T15 — Coupang 자동 등록 wrapping.

Vendored shared.platforms.coupang.products.create_product 위에 르무통 도메인 객체를 매핑.
쿠팡은 단일 상품에 multiple items (옵션별 vendorItem)을 한 번에 등록한다.

Coupang은 페이로드 빌더가 vendor 모듈에 없고 운영 스크립트에서 만들어왔으므로,
여기서 표준 빌더를 제공한다 (쇼핑몰별 템플릿은 외부에서 주입).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CoupangRegistrationInputs:
    """쿠팡 등록 페이로드의 외부 입력."""
    display_category_code: int
    brand: str = "르무통"
    seller_product_name: Optional[str] = None
    item_image_url: str = ""        # 옵션 이미지 (대표 이미지)
    detail_html: str = ""
    delivery_charge: int = 3500
    delivery_charge_type: str = "FREE"
    return_charge: int = 5000
    after_service_information: str = "고객센터 문의"
    after_service_contact_number: str = "02-0000-0000"
    outbound_shipping_place_code: int = 0
    return_center_code: str = ""
    return_charge_vendor: str = ""
    return_address: str = ""
    return_address_detail: str = ""
    return_zip_code: str = ""
    barcode: str = ""
    notice_category_id: str = "00045"
    notices: list = field(default_factory=list)
    attributes: list = field(default_factory=list)


def _build_payload(*, bundle, options, sale_price: int, inputs: CoupangRegistrationInputs) -> dict:
    """Model + Options + 입력값으로 쿠팡 등록 페이로드 빌드 (옵션마다 1 item)."""
    items = []
    for o in options:
        if not o.market_visible_coupang:
            continue
        item_name = f"{o.color_code}-{o.size_code}"
        items.append({
            "itemName": item_name,
            "originalPrice": int(sale_price),
            "salePrice": int(o.option_coupang_price_override or sale_price),
            "maximumBuyCount": "0",
            "maximumBuyForPerson": "0",
            "outboundShippingTimeDay": "1",
            "maximumBuyForPersonPeriod": "1",
            "unitCount": "1",
            "adultOnly": "EVERYONE",
            "taxType": "TAX",
            "parallelImported": "NOT_PARALLEL_IMPORTED",
            "overseasPurchased": "NOT_OVERSEAS_PURCHASED",
            "pccNeeded": "false",
            "externalVendorSku": o.canonical_sku,
            "barcode": "",
            "modelNo": bundle.model_code,
            "extraProperties": {},
            "certifications": [],
            "searchTags": [bundle.model_code, o.color_code],
            "images": [{
                "imageOrder": 0,
                "imageType": "REPRESENTATION",
                "vendorPath": inputs.item_image_url,
            }] if inputs.item_image_url else [],
            "notices": inputs.notices,
            "attributes": inputs.attributes,
            "contents": [{
                "contentsType": "TEXT",
                "contentDetails": [{
                    "content": inputs.detail_html or "<p>상세 페이지</p>",
                    "detailType": "TEXT",
                }],
            }],
            "offerCondition": "NEW",
        })

    return {
        "displayCategoryCode": int(inputs.display_category_code),
        "sellerProductName": inputs.seller_product_name
            or bundle.coupang_product_name_override
            or bundle.model_name_display
            or bundle.model_name_raw,
        "vendorId": "",  # CoupangClient가 헤더로 채움
        "saleStartedAt": "2026-01-01T00:00:00",
        "saleEndedAt": "2099-12-31T23:59:59",
        "displayProductName": bundle.model_name_display or bundle.model_name_raw,
        "brand": inputs.brand,
        "generalProductName": bundle.model_name_display or bundle.model_name_raw,
        "productGroup": bundle.model_code,
        "deliveryMethod": "SEQUENCIAL",
        "deliveryCompanyCode": "CJGLS",
        "deliveryChargeType": inputs.delivery_charge_type,
        "deliveryCharge": int(inputs.delivery_charge),
        "freeShipOverAmount": 0,
        "deliveryChargeOnReturn": int(inputs.return_charge),
        "remoteAreaDeliverable": "N",
        "unionDeliveryType": "UNION_DELIVERY",
        "returnCenterCode": inputs.return_center_code,
        "returnChargeName": inputs.return_charge_vendor,
        "companyContactNumber": inputs.after_service_contact_number,
        "returnZipCode": inputs.return_zip_code,
        "returnAddress": inputs.return_address,
        "returnAddressDetail": inputs.return_address_detail,
        "returnCharge": int(inputs.return_charge),
        "outboundShippingPlaceCode": int(inputs.outbound_shipping_place_code) or 0,
        "vendorUserId": "",
        "requested": False,        # 임시 등록 (검토용)
        "items": items,
        "requiredDocuments": [],
        "extraInfoMessage": "",
        "manufacture": inputs.brand,
    }


def register_bundle_to_coupang(
    *,
    bundle,
    options,
    inputs: CoupangRegistrationInputs,
    sale_price: Optional[int] = None,
) -> dict:
    """Model + Options를 쿠팡에 등록 (requested=False — 임시 검토 상태).

    Returns:
        {'ok': bool, 'seller_product_id': int|None, 'error': str|None, ...}
    """
    from shared.platforms.coupang.products import create_product, ProductCreationError, get_product

    if sale_price is None:
        from shared.db import SessionLocal
        from lemouton.templates.models import PriceTemplate
        s = SessionLocal()
        try:
            tpl = (s.query(PriceTemplate)
                   .filter_by(id=bundle.price_template_id).first()
                   if bundle.price_template_id else None)
            sale_price = tpl.coupang_boxhero_sale_price if tpl else 128900
        finally:
            s.close()

    payload = _build_payload(bundle=bundle, options=options,
                             sale_price=int(sale_price), inputs=inputs)

    try:
        seller_product_id = create_product(payload)
    except ProductCreationError as e:
        return {'ok': False, 'error': str(e), 'detail': e.payload}
    except Exception as e:
        logger.exception('coupang create_product raised')
        return {'ok': False, 'error': str(e)}

    # vendorItemId 매핑
    vendor_items = {}
    try:
        detail = get_product(seller_product_id)
        for it in detail.get('items', []):
            mp = it.get('marketplaceItemData', {})
            external_sku = it.get('externalVendorSku')
            if external_sku and mp.get('vendorItemId'):
                vendor_items[external_sku] = mp['vendorItemId']
    except Exception:
        logger.exception('vendorItemId 조회 실패 — 등록은 성공함')

    # DB 반영
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    s = SessionLocal()
    try:
        m = s.query(Model).filter_by(model_code=bundle.model_code).first()
        if m:
            m.coupang_product_id = str(seller_product_id)
        for sku, vendor_item_id in vendor_items.items():
            o = s.query(Option).filter_by(canonical_sku=sku).first()
            if o:
                o.coupang_option_id = str(vendor_item_id)
        s.commit()
    finally:
        s.close()

    return {
        'ok': True,
        'seller_product_id': seller_product_id,
        'vendor_items': vendor_items,
    }
