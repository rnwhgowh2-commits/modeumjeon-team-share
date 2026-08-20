# -*- coding: utf-8 -*-
"""롯데온 「본보기 상품」 검사 — 되돌릴 수 없는 사고 하나를 막는다.

왜 이 파일이 있나 (2026-08-06 더망고 벤치마킹 조사에서 드러남):

  롯데온 등록은 카테고리를 우리가 고르지 않는다. `compile_lotteon`(compile_more.py:148)
  이 「본보기 기존 상품번호(LO…)」를 받고, `_register_lotteon`(send_more.py:352)이 그
  상품의 detail 을 통째로 복사한다. 복사되는 필드 명부가
  `products.py:197 _REGISTER_TEMPLATE_FIELDS` 이고, 그 안에 **`dmstOvsDvDvsCd`
  (국내해외구분코드)** 가 있다.

  → 본보기가 **해외직구 상품**이면 그 코드가 그대로 복사돼 등록되는 상품 전부가
    해외직구로 나간다. **마켓에서 이 값을 바꿀 수 없다** — 삭제 후 재등록만이 복구다.
    대량등록이면 수천 건이 한 번에 잘못 나간다.

실측 근거 (dmstOvsDvDvsCd — scripts/_lotteon_pbf_dump/lemouton_base.json — 라이브 상품 덤프):
    "dmstOvsDvDvsCd": "DMST", "dmstOvsDvDvsCdNm": "국내배송"   ← :191~192
판매상태는 그 덤프가 아니라 실제 등록흐름이 부르는 get_product_detail(product/detail)의
응답 최상위 `slStatCd` 다 — [2026-08-20 정정] 원래 `spdSlStatCd`로 읽던 것이 그 덤프가
다른 API(PBF) 응답이라 실제 응답엔 없는 키였음을 라이브 재현으로 확인, `slStatCd`로 수정.

우리는 **국내 소싱·국내 배송**이다. 그래서 판정은 화이트리스트다 —
`DMST` 가 **아니면 전부 막는다.** 해외 코드값을 모르기 때문에 「아는 것만 통과」로 둔다
(프로젝트 원칙: 실측값만 적용, 모르면 미적용).

★ 실등록은 절대 하지 않는다 — 마켓 경계(get_product_detail·register_product)만
  monkeypatch 하고 나머지는 진짜 코드를 그대로 돌린다.
"""
import pytest

from lemouton.registration.send_more import PrereqError


def _spec(**over):
    """`compile_lotteon` 이 만들어 내보내는 spec 의 최소 모양."""
    spec = {
        'template_spd_no': 'LO2727500650',
        'spd_nm': '테스트 상품',
        'goods_name': '테스트 상품',
        'price': 39000,
        'stock': 10,
        'options': None,
        'image_url': 'https://example.test/a.jpg',
    }
    spec.update(over)
    return spec


def _detail(**over):
    """롯데온 상품 상세조회 응답(data) 의 최소 모양 — 기본은 **정상 본보기**."""
    d = {
        'dmstOvsDvDvsCd': 'DMST',      # 국내배송
        'dmstOvsDvDvsCdNm': '국내배송',
        'slStatCd': 'SALE',            # 판매중
        'itmLst': [{'sitmNm': '기본', 'slPrc': 10000, 'stkQty': 1}],
    }
    d.update(over)
    return d


@pytest.fixture
def market_boundary(monkeypatch):
    """마켓 경계만 가짜로. 등록 호출이 실제로 일어났는지 세어 돌려준다."""
    from lemouton.uploader import market_fetch as MF
    import shared.platforms.lotteon.products as P

    calls = {'register': 0, 'payload': 0}
    # 계정 조회(_env_prefix)는 DB 를 탄다 — 이 시험의 관심사가 아니므로 비켜 세운다.
    import lemouton.registration.send_more as SM
    monkeypatch.setattr(SM, '_env_prefix', lambda market, account_key='': 'LOTTEON')
    monkeypatch.setattr(MF, '_lotteon_client', lambda *a, **kw: object())

    def _build(**kw):
        calls['payload'] += 1
        return {'itmLst': [{'itmImgLst': [{'origImgFileNm': 'x'}]}]}

    def _register(inner, **kw):
        calls['register'] += 1
        return {'spdNo': 'LO9999999999'}

    monkeypatch.setattr(P, 'build_register_payload', _build)
    monkeypatch.setattr(P, 'register_product', _register)

    def set_detail(detail):
        monkeypatch.setattr(P, 'get_product_detail', lambda *a, **kw: detail)

    return calls, set_detail


# ── 🔴 되돌릴 수 없는 사고: 해외직구 본보기 ────────────────────────────────

def test_본보기가_해외배송이면_등록을_막는다(market_boundary):
    """dmstOvsDvDvsCd 가 DMST 가 아니면 그 필드가 복사돼 해외직구로 등록된다."""
    from lemouton.registration import send_more as SM
    calls, set_detail = market_boundary
    set_detail(_detail(dmstOvsDvDvsCd='OVS', dmstOvsDvDvsCdNm='해외직구'))

    with pytest.raises(PrereqError) as e:
        SM._register_lotteon(_spec())

    assert '해외' in str(e.value), str(e.value)
    assert calls['register'] == 0, '막았다면서 등록 API 를 불렀다'


def test_본보기_국내해외구분이_비어_있으면_막는다(market_boundary):
    """모르면 통과가 아니라 막는다 — 「아는 것만 통과」(실측값만 적용 원칙)."""
    from lemouton.registration import send_more as SM
    calls, set_detail = market_boundary
    set_detail(_detail(dmstOvsDvDvsCd='', dmstOvsDvDvsCdNm=''))

    with pytest.raises(PrereqError):
        SM._register_lotteon(_spec())
    assert calls['register'] == 0


def test_본보기가_판매중이_아니면_막는다(market_boundary):
    """판매종료·품절 본보기는 롯데온이 지울 수 있다 — 그 배치가 통째로 조용히 죽는다."""
    from lemouton.registration import send_more as SM
    calls, set_detail = market_boundary
    set_detail(_detail(slStatCd='END'))

    with pytest.raises(PrereqError) as e:
        SM._register_lotteon(_spec())

    assert '판매' in str(e.value), str(e.value)
    assert calls['register'] == 0


# ── 정상 본보기는 그대로 지나가야 한다 (막이개가 길을 막으면 안 된다) ──────

def test_국내_판매중_본보기는_그대로_등록된다(market_boundary):
    from lemouton.registration import send_more as SM
    calls, set_detail = market_boundary
    set_detail(_detail())

    out = SM._register_lotteon(_spec())

    assert out['product_id'] == 'LO9999999999'
    assert calls['register'] == 1
