"""[E] T14 — Smartstore 자동 등록 wrapping.

Vendored shared.platforms.smartstore.create_product 위에 르무통 도메인 객체
(Model, PriceTemplate)를 매핑해서 1번 호출로 등록 가능하게 한다.

흐름:
  1. Model + PriceTemplate에서 ProductRegistration 빌드
  2. create_product(auto_suspend=True) 호출 → SUSPENSION (draft) 등록
  3. originProductNo 결과를 Model.naver_product_id에 저장
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RegistrationInputs:
    """모음전 등록에 필요한 5개 핵심 입력 (외부에서 주입)."""
    leaf_category_id: str
    image_url: str            # Naver CDN URL (필수)
    detail_html: str
    after_service_phone: str = "02-0000-0000"
    after_service_guide: str = "고객센터 문의"


def _build_default_shoes_notice() -> 'object':
    """SHOES 카테고리 productInfoProvidedNotice 기본값.

    실제 사용 시 이 값을 외부에서 받거나 PriceTemplate.ss_extra_json에서 추출 가능.
    """
    from shared.platforms.smartstore.create_product import ShoesNotice
    return ShoesNotice(
        material="합성피혁/고무",
        color="다양",
        size="225~280",
        manufacturer="르무통",
        caution="습기에 약함, 직사광선 보관 금지",
        warranty_policy="구매일로부터 1년",
        after_service_director="르무통 고객센터 02-0000-0000",
    )


def register_bundle_to_smartstore(
    *,
    bundle,
    inputs: RegistrationInputs,
    sale_price: Optional[int] = None,
    stock_quantity: int = 100,
    auto_suspend: bool = True,
) -> dict:
    """Model 객체를 스마트스토어에 등록.

    Args:
        bundle: lemouton.sourcing.models.Model 인스턴스
        inputs: 등록에 필요한 5개 입력
        sale_price: 판매가 (None이면 적용된 PriceTemplate.ss_boxhero_sale_price 사용)
        stock_quantity: 등록 시 표시 재고 (실 재고는 업로더가 동기화)
        auto_suspend: True면 등록 직후 SUSPENSION 처리 (검토용 draft)

    Returns:
        {'ok': bool, 'origin_product_no': int|None, 'error': str|None, ...}
    """
    from shared.platforms.smartstore.create_product import (
        ProductRegistration, create_product,
    )

    # Sale price 결정
    if sale_price is None:
        # PriceTemplate에서 가져오기
        from shared.db import SessionLocal
        from lemouton.templates.models import PriceTemplate
        s = SessionLocal()
        try:
            tpl = (s.query(PriceTemplate)
                   .filter_by(id=bundle.price_template_id).first()
                   if bundle.price_template_id else None)
            sale_price = tpl.ss_boxhero_sale_price if tpl else 115900
        finally:
            s.close()

    name = (bundle.naver_product_name_override
            or bundle.model_name_display
            or bundle.model_name_raw)

    reg = ProductRegistration(
        leaf_category_id=str(inputs.leaf_category_id),
        name=name,
        sale_price=int(sale_price),
        stock_quantity=int(stock_quantity),
        image_url=inputs.image_url,
        detail_content_html=inputs.detail_html,
        shoes_notice=_build_default_shoes_notice(),
        after_service_phone=inputs.after_service_phone,
        after_service_guide=inputs.after_service_guide,
    )

    try:
        result = create_product(reg, auto_suspend=auto_suspend)
    except Exception as e:
        logger.exception('smartstore create_product raised')
        return {'ok': False, 'error': str(e)}

    if not result.success:
        return {
            'ok': False,
            'error': result.error_message or 'unknown',
            'error_code': result.error_code,
            'invalid_inputs': result.invalid_inputs,
        }

    # Model.naver_product_id 채움
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        from lemouton.sourcing.models import Model
        m = s.query(Model).filter_by(model_code=bundle.model_code).first()
        if m and result.origin_product_no:
            m.naver_product_id = str(result.origin_product_no)
            s.commit()
    finally:
        s.close()

    return {
        'ok': True,
        'origin_product_no': result.origin_product_no,
        'channel_product_no': result.channel_product_no,
    }
