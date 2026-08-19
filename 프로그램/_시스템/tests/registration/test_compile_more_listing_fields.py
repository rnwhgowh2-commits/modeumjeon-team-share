# -*- coding: utf-8 -*-
"""등록 상수가 11번가·옥션·G마켓까지 **실제로 나가는가**.

쿠팡·스마트스토어는 조립기가 순수 함수라 payload 를 바로 볼 수 있지만, 이 셋은
`compile_more`(순수 검증) → `send_more`(라이브 수확·조립) 두 단계로 갈라져 있다.
그래서 다리를 **두 곳 다** 본다:

  ① `compile_more.*` 가 초안의 새 칸을 spec 에 담는가
  ② 조립기(`build_register_xml` · `build_esm_register_payload`)가 그 값을 payload 로 내보내는가

🔴 ① 만 보면 「담기는데 안 나가는」 것을, ② 만 보면 「나갈 수 있는데 아무도 안 담는」 것을
   놓친다. 실제로 오늘 고친 것이 정확히 그 두 번째였다(칸은 있는데 호출부가 안 넘김).
"""
import json

from lemouton.registration.compile_more import (compile_auction_gmarket,
                                                compile_eleven11)
from shared.platforms.esm.products import build_esm_register_payload
from shared.platforms.eleven11.products import build_register_xml


class D:
    """ProductDraft 를 흉내내는 최소 fake."""

    def __init__(self, **kw):
        self.name = kw.get('name', '르무통 스니커즈')
        self.brand = kw.get('brand', '르무통')
        self.sale_price = kw.get('sale_price', 75800)
        self.stock_quantity = kw.get('stock_quantity', 5)
        self.images_json = kw.get('images_json', json.dumps(['https://img/a.jpg']))
        self.detail_html = kw.get('detail_html', '<p>상세</p>')
        self.options_json = kw.get('options_json', '[]')
        self.return_fee = kw.get('return_fee', 5000)
        self.after_service_phone = kw.get('after_service_phone', '02-1234-5678')
        self.after_service_guide = kw.get('after_service_guide', '평일 10-18시')


def _d(**kw):
    """새 칸은 setattr 로 직접 얹는다.

    🔴 `D(**kw)` 는 **아는 칸만** 읽고 모르는 칸을 조용히 버린다 — 그대로 쓰면
      시험이 늘 기본값을 보면서 통과한다(스스 배선 때 실제로 당한 함정).
    """
    d = D()
    for k, v in kw.items():
        setattr(d, k, v)
    return d


# ── 11번가 ────────────────────────────────────────────────────────────────

def _xml(**kw):
    spec, _ = compile_eleven11(_d(**kw), category_code='1001')
    spec.update({'addr_seq_out': '1', 'addr_seq_in': '2'})
    return build_register_xml(spec)


def test_11번가_과세구분이_정책대로_나간다():
    """지도 근거: 요청.suplDtyfrPrdClfCd enum [필수] — 01=과세 / 02=면세 / 03=영세."""
    assert '<suplDtyfrPrdClfCd>02</suplDtyfrPrdClfCd>' in _xml(tax_type='면세')
    assert '<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd>' in _xml(tax_type='과세')


def test_11번가_과세구분을_안_정하면_과세다():
    assert '<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd>' in _xml()


def test_11번가_모르는_과세구분은_지어내지_않고_과세로_둔다():
    """🔴 「영세」는 사장님이 선택지에서 뺐다 — 옛 저장분이 남아 있어도 지어내지 않는다."""
    assert '<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd>' in _xml(tax_type='영세')


def test_11번가_제조사가_나간다():
    """지도 근거: 요청.company — 「제조사 or 수입사는 텍스트 형태로만 입력」."""
    assert '<company><![CDATA[한국제화]]></company>' in _xml(manufacturer='한국제화')


def test_11번가_제조사를_안_정하면_브랜드가_나간다():
    """정책 「브랜드와 동일」이면 다리가 아무것도 안 넣는다 — 조립기가 브랜드로 갈음한다.

    🔴 다리에서 복사하면 같은 값을 만드는 곳이 둘이 되어, 브랜드를 고쳤을 때
      제조사만 옛 값으로 남는다(쿠팡과 같은 규칙).
    """
    assert '<company><![CDATA[르무통]]></company>' in _xml()


def test_11번가_모델번호는_있을_때만_나간다():
    """지도 근거: 요청.modelCd — 「모델의 고유한 식별정보」. 필수 아님."""
    assert '<modelCd><![CDATA[SQBAB9401]]></modelCd>' in _xml(model_no='SQBAB9401')
    assert '<modelCd>' not in _xml(), '빈 모델번호를 빈 값으로 등록하면 안 된다'


def test_11번가_상품상태는_새상품이_박혀_나간다():
    """지도 근거: 요청.prdStatCd enum [필수] — 01=새상품. 사장님 확정 = 무조건 새상품."""
    assert '<prdStatCd>01</prdStatCd>' in _xml()


def test_11번가_미성년자_구매가_정책대로_나간다():
    """지도 근거: 요청.minorSelCnYn — Y=구매가능 / N=불가.

    🔴 여기가 'Y' 로 박혀 있어 「19세 이상만」으로 정해도 전연령으로 나갔다
      (쿠팡 adultOnly 와 같은 부류의 사고 — 성인상품이 미성년자에게 노출된다).
    """
    assert '<minorSelCnYn>N</minorSelCnYn>' in _xml(minor_purchasable=False)
    assert '<minorSelCnYn>Y</minorSelCnYn>' in _xml(minor_purchasable=True)


def test_11번가_바코드는_보낼_칸이_없어_안_나간다():
    """지도 실측: 등록 요청필드 235개 중 barcode·GTIN·EAN 계열이 **0개**.

    「확인 못 함」이 아니라 「칸이 없음」이다 — 지어내서 아무 태그에나 넣지 않는다.
    """
    got = _xml(barcode='8801234567890')
    assert '8801234567890' not in got


def test_11번가_판매기간은_3년_상한을_넘지_않는다():
    """마켓마다 가장 긴 값(사장님 확정). 11번가는 3년이 상한이다."""
    import datetime as dtm
    got = _xml()
    today = dtm.date.today()
    assert f'<aplBgnDy>{today.strftime("%Y/%m/%d")}</aplBgnDy>' in got
    assert f'<aplEndDy>{today.replace(year=today.year + 3).strftime("%Y/%m/%d")}</aplEndDy>' in got


# ── 옥션·G마켓 (ESM) ──────────────────────────────────────────────────────

def _esm_spec(**kw):
    spec, _ = compile_auction_gmarket(_d(**kw), category_code='001/37500700')
    return spec


def _esm_payload(**kw):
    """spec 이 담은 값이 **실제 payload 까지** 가는지 — 조립기를 직접 호출해 본다."""
    spec = _esm_spec(**kw)
    return build_esm_register_payload(
        market='auction', goods_name=spec['goods_name'],
        cat_code=spec['cat_code'], site_cat_code=spec['site_cat_code'],
        site_type=1, price=spec['price'], stock=spec['stock'],
        place_no=1, dispatch_policy_no=1, return_addr_no='1',
        delivery_company_no=1, official_notice_no=1, official_notice_details=[],
        image_url=spec['image_url'], detail_html=spec['detail_html'], options=None,
        is_vat_free=spec['is_vat_free'], model_no=spec['model_no'],
        bar_code=spec['bar_code'], is_adult_product=spec['is_adult_product'])


def test_ESM_spec_이_등록_상수를_담는다():
    """① 다리 — compile_auction_gmarket 이 초안의 새 칸을 spec 에 담는가."""
    spec = _esm_spec(tax_type='면세', model_no='SQBAB9401', barcode='8801234567890',
                     minor_purchasable=False)
    assert spec['is_vat_free'] is True
    assert spec['model_no'] == 'SQBAB9401'
    assert spec['bar_code'] == '8801234567890'
    assert spec['is_adult_product'] is True


def test_ESM_과세구분이_정책대로_나간다():
    """지도 근거: itemAddtionalInfo > isVatFree — Boolean(면세=true)."""
    assert _esm_payload(tax_type='면세')['itemAddtionalInfo']['isVatFree'] is True
    assert _esm_payload(tax_type='과세')['itemAddtionalInfo']['isVatFree'] is False


def test_ESM_과세구분을_안_정하면_과세다():
    assert _esm_payload()['itemAddtionalInfo']['isVatFree'] is False


def test_ESM_모델번호와_바코드가_카탈로그로_나간다():
    """지도 근거: itemBasicInfo > catalog > modelName · barCode."""
    cat = _esm_payload(model_no='SQBAB9401',
                       barcode='8801234567890')['itemBasicInfo']['catalog']
    assert cat['modelName'] == 'SQBAB9401'
    assert cat['barCode'] == '8801234567890'


def test_ESM_둘_다_비면_카탈로그를_아예_안_보낸다():
    """빈 문자열을 보내면 「없음」이 아니라 **빈 값으로 등록**된다(스스에서 배운 것)."""
    assert 'catalog' not in _esm_payload()['itemBasicInfo']


def test_ESM_자체_생성_바코드는_보낸다():
    """자체 바코드는 **어느 마켓에도 안 보낸다**(사장님 확정) — ESM 도 예외 아니다."""
    from lemouton.inventory import barcode as BC
    self_made = BC.make_internal(1)
    assert BC.is_internal(self_made)
    assert 'catalog' not in _esm_payload(barcode=self_made)['itemBasicInfo']


def test_ESM_미성년자_구매가_정책대로_나간다():
    """지도 근거: itemAddtionalInfo > isAdultProduct — 필수(누락 시 400).

    🔴 False 가 박혀 있어 「19세 이상만」으로 정해도 전연령으로 나갔다.
    """
    assert _esm_payload(minor_purchasable=False)['itemAddtionalInfo']['isAdultProduct'] is True
    assert _esm_payload(minor_purchasable=True)['itemAddtionalInfo']['isAdultProduct'] is False


def test_ESM_판매기간은_무제한이다():
    """마켓마다 가장 긴 값(사장님 확정). ESM 은 -1 = 무제한."""
    got = _esm_payload()['itemAddtionalInfo']['sellingPeriod']
    assert got == {'Gmkt': -1, 'Iac': -1}
