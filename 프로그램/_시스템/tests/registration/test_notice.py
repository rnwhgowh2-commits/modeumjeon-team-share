# -*- coding: utf-8 -*-
"""스스 상품고시정보 4종 — 순수 함수. DB·네트워크 없음."""
import pytest

from lemouton.registration.notice import (
    NOTICE_TYPES, build_notice,
    NoticeError, NoticeFieldMissing, UnknownNoticeType,
)


def _full(**over):
    base = dict(material='면 100%', color='블랙', size='95', type='숄더백',
                manufacturer='르무통', caution='세탁 시 단독세탁',
                # 아래 2개는 네이버 공식 문구가 없어 기본값이 없다 → 호출자가 넣어야 한다.
                # (나머지 공통 5개는 네이버 공식 문구가 기본값으로 들어간다)
                warranty_policy='구매일로부터 1년',
                after_service_director='테스트 A/S 담당자 (실제 연락처 아님)')
    base.update(over)
    return base


def test_notice_types_are_the_four():
    assert set(NOTICE_TYPES) == {'WEAR', 'SHOES', 'BAG', 'FASHION_ITEMS'}


def test_wear_shape():
    """WEAR → {productInfoProvidedNoticeType, wear:{...}} + 공통 7 전부 채워짐."""
    body = build_notice('WEAR', _full())
    assert body['productInfoProvidedNoticeType'] == 'WEAR'
    w = body['wear']
    assert w['material'] == '면 100%'
    assert w['color'] == '블랙'
    assert w['size'] == '95'
    assert w['manufacturer'] == '르무통'
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
    # NoticeFieldMissing 도 ValueError 라서, 유형이 아니라 '무엇으로' 실패했는지까지 본다.
    with pytest.raises(UnknownNoticeType, match='FOOD'):
        build_notice('FOOD', _full())


def test_notice_errors_share_one_base():
    """상위(Task 6 컴파일러)가 NoticeError 하나만 잡으면 되도록."""
    assert issubclass(NoticeFieldMissing, NoticeError)
    assert issubclass(UnknownNoticeType, NoticeError)
    assert issubclass(NoticeError, ValueError)


def test_user_can_override_common_defaults():
    body = build_notice(
        'WEAR', _full(quality_assurance_standard='구매일로부터 2년 무상 A/S'))
    assert body['wear']['qualityAssuranceStandard'] == '구매일로부터 2년 무상 A/S'


@pytest.mark.parametrize('field', [
    'warranty_policy',            # 판매자별 약속 — 네이버 프리셋 없음
    'after_service_director',     # 판매자별 정보 — 네이버 프리셋 없음
])
def test_fields_without_official_text_have_no_default(field):
    """네이버 공식 문구가 없는 필드에 우리가 약속을 지어내면 안 된다.

    특히 warrantyPolicy 는 법적·금전적 약정이라, 판매자가 말한 적 없는 보증기간이
    라이브 리스팅에 게시되면 안 된다.
    """
    data = _full()
    del data[field]
    with pytest.raises(NoticeFieldMissing):
        build_notice('WEAR', data)


def test_blank_does_not_resurrect_default():
    """일부러 비운 값이 기본값으로 덮여 되살아나면 안 된다 (빈칸 ≠ 미입력)."""
    with pytest.raises(NoticeFieldMissing, match='qualityAssuranceStandard'):
        build_notice('WEAR', _full(quality_assurance_standard=''))


def test_non_string_values_are_coerced_not_crashed():
    """notice_json 은 UI 발 자유형 JSON — size: 95 (int) 가 와도 500 이면 안 된다."""
    body = build_notice('WEAR', _full(size=95))
    assert body['wear']['size'] == '95'


def test_legal_defaults_are_naver_official_text():
    """공통 5개 법정 문구 고정 — 우리가 쓴 문장이 섞여 들어가는 걸 막는다.

    ★ 3개는 option 0(전문), 2개는 option 1('상품상세 참조'). 섞인 건 의도한 것이다.

      returnCostReason / compensationProcedure 는 option 0 전문이
      marketplace_api_map.json 에 문장 중간에서 잘린 채로 접수돼 있다(237/285자,
      닫는 괄호도 option 1 도 없음, 468개 occurrence 전부 동일 지점). 네이버 문서
      페이지도 client-rendered 라 재수집이 안 된다. 그래서 네이버가 미입력 시
      자동으로 넣는 값인 option 1 을 쓴다.

    ⚠️ 이 2개를 '전문으로 업그레이드' 한다며 기억에 의존해 손으로 써넣지 말 것.
       그게 바로 이 테스트가 막으려는 행위다(우리가 판매자 대신 법적 문구를 창작).
       지도 재접수로 option 0 전문을 확보했을 때만 교체하고, 그때 이 테스트도 같이
       고칠 것.
    """
    w = build_notice('WEAR', _full())['wear']

    # option 0 (전문) — 확보된 3개
    assert w['qualityAssuranceStandard'] == (
        '소비자분쟁해결기준(공정거래위원회 고시) 및 관계법령에 따릅니다.')
    assert w['troubleShootingContents'] == (
        '소비자분쟁해결기준(공정거래위원회 고시) 및 관계법령에 따릅니다.')
    assert w['noRefundReason'] == (
        '전자상거래 등에서의 소비자보호에 관한 법률 등에 의한 청약철회 제한 사유에 해당하는 '
        '경우 및 기타 객관적으로 이에 준하는 것으로 인정되는 경우 청약철회가 제한될 수 있습니다.')

    # option 1 — 원본 잘림으로 전문 미확보인 2개
    assert w['returnCostReason'] == '상품상세 참조'
    assert w['compensationProcedure'] == '상품상세 참조'
