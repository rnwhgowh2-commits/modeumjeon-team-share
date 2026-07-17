# -*- coding: utf-8 -*-
"""스스 상품고시정보 4종 — 순수 함수. DB·네트워크 없음."""
import pytest

from lemouton.registration.notice import (
    NOTICE_TYPES, build_notice, NoticeFieldMissing,
)


def _full(**over):
    base = dict(material='면 100%', color='블랙', size='95', type='숄더백',
                manufacturer='르무통', caution='세탁 시 단독세탁',
                after_service_director='르무통 고객센터 02-0000-0000')
    base.update(over)
    return base


def test_notice_types_are_the_four():
    assert set(NOTICE_TYPES) == {'WEAR', 'SHOES', 'BAG', 'FASHION_ITEMS'}


def test_wear_shape():
    """WEAR → {productInfoProvidedNoticeType, wear:{...}} + 공통 7 자동 채움."""
    body = build_notice('WEAR', _full())
    assert body['productInfoProvidedNoticeType'] == 'WEAR'
    w = body['wear']
    assert w['material'] == '면 100%'
    assert w['color'] == '블랙'
    assert w['size'] == '95'
    assert w['manufacturer'] == '르무통'
    # 공통 7 — 사용자가 안 넣어도 법정 기본문구가 들어간다
    for k in ('returnCostReason', 'noRefundReason', 'qualityAssuranceStandard',
              'compensationProcedure', 'troubleShootingContents',
              'warrantyPolicy', 'afterServiceDirector'):
        assert w[k], f'공통 필수 누락: {k}'
    assert 'type' not in w, 'WEAR 에 type 이 새어 들어갔다'


def test_bag_requires_type():
    body = build_notice('BAG', _full())
    assert body['bag']['type'] == '숄더백'
    assert body['bag']['color'] == '블랙'


def test_fashion_items_has_no_color():
    """FASHION_ITEMS 는 공식 스펙상 color 필드가 없다."""
    body = build_notice('FASHION_ITEMS', _full())
    fi = body['fashionItems']
    assert fi['type'] == '숄더백'
    assert 'color' not in fi, 'FASHION_ITEMS 에 color 를 보내면 안 된다'


def test_shoes_size_is_foot_length():
    body = build_notice('SHOES', _full(size='250'))
    assert body['shoes']['size'] == '250'


def test_missing_required_raises_not_silently_defaults():
    """필수 누락은 조용히 기본값을 넣지 말고 실패해야 한다 (폴백 금지 원칙)."""
    with pytest.raises(NoticeFieldMissing) as e:
        build_notice('WEAR', _full(material=''))
    assert 'material' in str(e.value)


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        build_notice('FOOD', _full())


def test_user_can_override_common_defaults():
    body = build_notice('WEAR', _full(warranty_policy='구매일로부터 2년'))
    assert body['wear']['warrantyPolicy'] == '구매일로부터 2년'
