# -*- coding: utf-8 -*-
"""3축 전송 — 「모델명 · 색상 · 사이즈」 세 갈래로 스마트스토어에 올린다.

노션 ①「마켓별 업로드 시 2/3축 구성 쪼갤 수 있음 — 2축(색상,사이즈) 3축(모델명,색상,사이즈)」

## 왜 막혀 있었나 (2026-08-13 감사에서 실측)

마켓 탓이 아니었다. **우리 옵션 행에 모델명 칸이 없었다.**
코드 주석이 그대로 사유를 적어 두고 있었다 —
「옵션에 모델명을 담는 칸이 없습니다(옵션은 색상·사이즈·재고·추가금·SKU 만 담습니다)」.

마켓은 받는다 — 판매처 지도 근거(근거 서열 2 = 마켓 개발자센터 원문):
  smartstore `optionCombinations` —
  **「최대 등록 가능한 옵션 개수는 조합형은 3개, 지점형은 4개입니다.」**

🔴 그리고 진짜 위험한 자리는 따로 있었다 — `_normalize` 의 **중복 검사 키가
   `(color, size)`** 라, 모델만 다른 두 옵션이 「같은 옵션이 두 번」으로 죽었다.
   #988 에서 고친 매트릭스 중복 키와 **같은 계열의 버그**다(축이 3개인데 2개로 셌다).
"""
import pytest

from lemouton.registration.options import (
    build_smartstore_options, AXIS_ONE, AXIS_TWO, AXIS_THREE,
    OptionValueInvalid,
)

#: 모델만 다르고 색상·사이즈는 같다 — 2축으로 세면 「중복」이 되는 조합.
THREE = [
    {'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1', 'model': '메이트'},
    {'color': '블랙', 'size': '260', 'stock': 2, 'sku': 'A2', 'model': '스위트'},
]


def test_모델만_다른_옵션이_중복으로_죽지_않는다():
    """🔴 RED 였던 자리 — 「같은 옵션이 두 번 들어왔습니다: 블랙/260」로 죽었다."""
    _, combos, _ = build_smartstore_options(THREE, sale_price=10000, axis=AXIS_THREE)
    assert len(combos) == 2, combos


def test_3축이면_세_갈래로_나간다():
    groups, combos, _ = build_smartstore_options(THREE, sale_price=10000,
                                                 axis=AXIS_THREE)
    assert groups == {'optionGroupName1': '모델명',
                      'optionGroupName2': '색상',
                      'optionGroupName3': '사이즈'}
    assert [c['optionName1'] for c in combos] == ['메이트', '스위트']
    assert {c['optionName2'] for c in combos} == {'블랙'}
    assert {c['optionName3'] for c in combos} == {'260'}


def test_재고와_SKU_가_모델별로_따로_붙는다():
    """세 갈래로 쪼개도 **하나의 옵션번호**다 — SKU 가 섞이면 재고가 엉킨다."""
    _, combos, _ = build_smartstore_options(THREE, sale_price=10000, axis=AXIS_THREE)
    got = {c['sellerManagerCode']: c['stockQuantity'] for c in combos}
    assert got == {'A1': 3, 'A2': 2}


def test_2축은_예전_그대로다():
    """모델 칸이 생겨도 2축 결과는 한 글자도 안 바뀐다(회귀 방지).

    🔴 옛 옵션에는 `model` 키가 아예 없다 — 그 경우가 라이브의 대부분이다.
    """
    old = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1'},
           {'color': '크림', 'size': '260', 'stock': 1, 'sku': 'A2'}]
    groups, combos, _ = build_smartstore_options(old, sale_price=10000, axis=AXIS_TWO)
    assert groups == {'optionGroupName1': '색상', 'optionGroupName2': '사이즈'}
    assert [c['optionName1'] for c in combos] == ['블랙', '크림']
    assert all('optionName3' not in c for c in combos)


def test_모델_칸이_있어도_2축이면_무시한다():
    """축은 사장님이 정한다 — 칸이 있다고 프로그램이 멋대로 3축으로 올리지 않는다."""
    two = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1', 'model': '메이트'},
           {'color': '크림', 'size': '260', 'stock': 1, 'sku': 'A2', 'model': '메이트'}]
    groups, combos, _ = build_smartstore_options(two, sale_price=10000, axis=AXIS_TWO)
    assert 'optionGroupName3' not in groups
    assert all('optionName3' not in c for c in combos)


def test_3축인데_모델명이_비면_지어내지_않고_거절한다():
    """🔴 폴백 금지 — 빈 칸을 「?」 로 채우면 구매자 드롭다운에 그대로 나간다."""
    bad = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1', 'model': ''},
           {'color': '블랙', 'size': '260', 'stock': 2, 'sku': 'A2', 'model': '스위트'}]
    with pytest.raises(OptionValueInvalid) as ei:
        build_smartstore_options(bad, sale_price=10000, axis=AXIS_THREE)
    assert '모델명' in str(ei.value)


def test_3축이라도_모델_색상_사이즈가_다_같으면_여전히_중복이다():
    """중복 검사를 없앤 게 아니라 **축 개수만큼 넓힌** 것이다."""
    dup = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1', 'model': '메이트'},
           {'color': '블랙', 'size': '260', 'stock': 2, 'sku': 'A2', 'model': '메이트'}]
    with pytest.raises(OptionValueInvalid) as ei:
        build_smartstore_options(dup, sale_price=10000, axis=AXIS_THREE)
    assert '두 번' in str(ei.value)


def test_모델을_안_싣는_마켓으로는_겹친_채_나가지_못한다():
    """🔴 내가 만들 뻔한 회귀 — 중복 키를 무조건 넓혔더니 쿠팡으로
    `블랙-260` 두 줄이 **에러 없이** 나갔다(실측).

    쿠팡은 모델명을 갈래로 싣지 않는다. 사장님 눈엔 다른 옵션인데 마켓엔 같은
    이름으로 올라가므로, **막는 게 맞다** — 사유까지 정확히 말한다.
    """
    from lemouton.registration.options import build_coupang_items
    with pytest.raises(OptionValueInvalid) as ei:
        build_coupang_items(THREE, sale_price=10000, image_url='')
    말 = str(ei.value)
    assert '모델이 다른 옵션' in 말, 말
    assert '메이트' in 말 and '스위트' in 말, 말
    assert '3갈래' in 말, 말          # 어떻게 풀지까지 알려 준다


def test_2갈래_스스도_모델이_겹치면_막는다():
    """같은 불변식 — 스스라도 2갈래로 올리면 모델명이 안 실린다."""
    with pytest.raises(OptionValueInvalid) as ei:
        build_smartstore_options(THREE, sale_price=10000, axis=AXIS_TWO)
    assert '모델이 다른 옵션' in str(ei.value)


def test_모델이_없는_옛_옵션은_중복_사유가_예전_그대로다():
    """모델 칸이 없으면 문구를 바꾸지 않는다 — 엉뚱한 안내를 하지 않게."""
    old = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1'},
           {'color': '블랙', 'size': '260', 'stock': 2, 'sku': 'A2'}]
    with pytest.raises(OptionValueInvalid) as ei:
        build_smartstore_options(old, sale_price=10000, axis=AXIS_TWO)
    말 = str(ei.value)
    assert '같은 옵션이 두 번' in 말
    assert '모델' not in 말


def test_1축은_모델명까지_한_줄로_합친다():
    """「메이트 블랙 260」 — 한 갈래로 합칠 땐 모델명도 같이 붙는다."""
    groups, combos, _ = build_smartstore_options(THREE, sale_price=10000,
                                                 axis=AXIS_ONE)
    assert groups == {'optionGroupName1': '옵션'}
    assert [c['optionName1'] for c in combos] == ['메이트 블랙 260', '스위트 블랙 260']


# ── 저장 게이트가 전송보다 엄격하면 안 된다 (2026-08-13) ─────────────────────


def test_저장_검증은_전송이_받는_것을_거절하지_않는다():
    """🔴 실측 사고 — 대량등록 저장 화면이 3갈래 행을 거절했다.

    `build_smartstore_options` 를 axis 없이 부르면 기본이 2갈래라 `split_model=False`.
    그래서 **전송(정책 axis=three)이 받아들이는 행을 저장이 막았다.**
    게다가 거절문이 안내하는 해법(「상품가공에서 3갈래로」)은 그 게이트가
    **절대 안 읽는 설정**이라, 시키는 대로 해도 저장은 계속 막힌다.
    저장 시점엔 축을 모르므로 **축 무관 판정만** 해야 한다.
    """
    from lemouton.registration.options import validate_rows_for_save
    보낼_수_있나 = build_smartstore_options(THREE, sale_price=10000, axis=AXIS_THREE)[1]
    저장_되나, _ = validate_rows_for_save(THREE, sale_price=10000)
    assert len(보낼_수_있나) == len(저장_되나) == 2, (
        f'전송 {len(보낼_수_있나)}줄 · 저장 {len(저장_되나)}줄 — 저장이 더 엄격하다')


def test_저장_검증도_완전_중복은_막는다():
    """느슨해진 게 아니다 — 어느 축이어도 잘못인 것은 그대로 막는다."""
    from lemouton.registration.options import validate_rows_for_save
    dup = [{'color': '블랙', 'size': '260', 'stock': 3, 'sku': 'A1', 'model': '메이트'},
           {'color': '블랙', 'size': '260', 'stock': 2, 'sku': 'A2', 'model': '메이트'}]
    with pytest.raises(OptionValueInvalid):
        validate_rows_for_save(dup, sale_price=10000)


def test_저장_검증은_최종가_0원_이하를_막는다():
    """가격 검사는 축과 무관하다 — 저장 시점에도 그대로 해야 한다."""
    from lemouton.registration.options import validate_rows_for_save
    with pytest.raises(OptionValueInvalid):
        validate_rows_for_save(
            [{'color': '블랙', 'size': '260', 'stock': 3, 'extra_price': -10000}],
            sale_price=10000)
