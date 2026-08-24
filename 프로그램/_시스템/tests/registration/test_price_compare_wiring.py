# -*- coding: utf-8 -*-
"""가격비교 노출이 **실제로 마켓에 나가나** (Phase 4-5).

🔴 이 파일이 막는 사고
  이 항목은 정책 화면에 칸이 있고 저장도 됐는데 **읽는 코드가 없었다.**
  스스는 `naverShoppingRegistration: True` 가 코드에 박혀 있었고,
  11번가·ESM 은 칸 자체를 안 보냈다. 사장님이 「노출 안 함」으로 정해도
  그대로 노출됐다는 뜻이다 — **가격비교는 수수료가 더 붙는다(금전 직결).**

■ 마켓별 칸 (2026-08-24 지도 전문 + 라이브 대조 실측)
  · 스마트스토어 `naverShoppingRegistration` (boolean) [필수]
  · 11번가 `prcCmpExpYn` / `prcDscCmpExpYn` (Y/N, 선택)
  · 옥션 `addtionalInfo>pcs>isUse` / `isUseIacPcsCoupon`
  · G마켓 `pcs>isUse` — 🔴 쿠폰 칸은 지도에 「사용불가」(마켓이 막아 둠)
  · 쿠팡 칸 없음 · 롯데온 확인 불가
"""
from lemouton.registration import process_apply as PA


class _Draft:
    """ProductDraft 흉내 — 순수함수라 DB 가 필요 없다."""

    def __init__(self, **kw):
        self.name = kw.pop('name', '나이키 에어포스 1')
        self.brand = kw.pop('brand', '나이키')
        self.source_site = kw.pop('source_site', 'musinsa')
        self.source_category_path = kw.pop('source_category_path', '신발>스니커즈')
        self.options_json = kw.pop('options_json', '[]')
        self.notice_json = kw.pop('notice_json', '{}')
        for k, v in kw.items():
            setattr(self, k, v)


def _적용(expose=None, coupon=None):
    cfg = {}
    if expose is not None:
        cfg['expose'] = expose
    if coupon is not None:
        cfg['coupon'] = coupon
    view, applied, skipped = PA.apply_rules(_Draft(), {'price_compare': cfg})
    return view, applied, skipped


# ── 가공 사본에 실리나 ────────────────────────────────────────────────────

def test_노출함으로_정하면_사본에_실린다():
    view, applied, _ = _적용(expose=True)
    assert getattr(view, 'price_compare_expose') is True
    assert any(a['item'] == 'price_compare' for a in applied)


def test_노출_안_함으로_정하면_사본에_실린다():
    view, applied, _ = _적용(expose=False)
    assert getattr(view, 'price_compare_expose') is False
    assert any('노출하지 않' in (a.get('note') or '') for a in applied)


def test_정책이_말하지_않으면_손대지_않는다():
    """🔴 이 항목이 배선됐다고 기존 상품이 달라지면 안 된다."""
    view, applied, _ = _적용()
    assert getattr(view, 'price_compare_expose', None) is None
    assert not [a for a in applied if a['item'] == 'price_compare']


def test_예_아니오가_아니면_지어내지_않는다():
    view, _, skipped = _적용(expose='아마도')
    assert getattr(view, 'price_compare_expose', None) is None
    assert any(s['code'] == 'BAD_EXPOSE' for s in skipped)
    assert not [s for s in skipped if s['blocking']], '전송을 막을 일은 아니다'


# ── 스마트스토어 ──────────────────────────────────────────────────────────

def _스스(draft, **kw):
    from lemouton.registration.compile_smartstore import compile_smartstore
    return compile_smartstore(draft, category_code='50000000', **kw)


def test_스스는_정책대로_보낸다():
    from lemouton.registration.compile_smartstore import compile_smartstore
    import inspect
    소스 = inspect.getsource(compile_smartstore)
    assert "'naverShoppingRegistration': True," not in 소스, (
        '노출 여부가 코드에 박혀 있다 — 정책을 무시한다')
    assert 'price_compare_expose' in 소스


def test_스스는_안_정하면_노출함이다():
    """이 칸은 [필수]라 값이 있어야 한다 — 지금까지의 동작 그대로."""
    from lemouton.registration.compile_smartstore import compile_smartstore
    import inspect
    소스 = inspect.getsource(compile_smartstore)
    assert 'is not None else True' in 소스


# ── 11번가 · 옥션 · G마켓 (실제 ProductDraft 로) ─────────────────────────

import json  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from lemouton.registration.models import ProductDraft  # noqa: E402
from shared.db import Base  # noqa: E402


@pytest.fixture()
def session():
    eng = create_engine('sqlite://', future=True)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    yield s
    s.close()


def _저장드래프트(session, **kw):
    base = dict(name='르무통 메이트 스니커즈', brand='르무통', sale_price=135820,
                stock_quantity=1,
                images_json=json.dumps(['https://r2.example.com/a.jpg']),
                detail_html='<p>르무통 메이트</p>', options_json='[]',
                after_service_phone='010-1234-5678',
                after_service_guide='평일 10-18시 고객센터', return_fee=5000)
    base.update(kw)
    d = ProductDraft(**base)
    session.add(d)
    session.commit()
    return d


class _가공사본:
    """저장 드래프트 + 가공이 얹은 칸 — `DraftProcessView` 와 같은 결."""

    def __init__(self, inner, **over):
        self._inner, self._over = inner, over

    def __getattr__(self, k):
        if k in self._over:
            return self._over[k]
        return getattr(self._inner, k)


def test_11번가는_YN_으로_보낸다(session):
    from lemouton.registration.compile_more import compile_eleven11
    d = _가공사본(_저장드래프트(session),
                price_compare_expose=True, price_compare_coupon=False)
    spec, _ = compile_eleven11(d, category_code='1011634')
    assert spec['prc_cmp_exp_yn'] == 'Y'
    assert spec['prc_dsc_cmp_exp_yn'] == 'N'


def test_11번가는_안_정하면_칸_자체를_안_넣는다(session):
    """지금까지 안 보내던 칸이다 — 갑자기 보내기 시작하면 그게 변경이다."""
    from lemouton.registration.compile_more import compile_eleven11
    spec, _ = compile_eleven11(_저장드래프트(session), category_code='1011634')
    assert 'prc_cmp_exp_yn' not in spec
    assert 'prc_dsc_cmp_exp_yn' not in spec


def _esm(d):
    from lemouton.registration.compile_more import compile_auction_gmarket
    return compile_auction_gmarket(d, category_code='00120005002000000000/37500700')


def test_ESM은_불리언으로_보낸다(session):
    spec, _ = _esm(_가공사본(_저장드래프트(session),
                          price_compare_expose=False, price_compare_coupon=True))
    assert spec['pcs_use'] is False
    assert spec['pcs_coupon_iac'] is True


def test_ESM은_안_정하면_칸_자체를_안_넣는다(session):
    spec, _ = _esm(_저장드래프트(session))
    assert 'pcs_use' not in spec
    assert 'pcs_coupon_iac' not in spec


def test_G마켓_쿠폰칸은_만들지_않는다():
    """🔴 지도에 「사용불가」 — 마켓이 설정을 막아 뒀다. 보내면 거부당한다.

    ★ 글자가 있나가 아니라 **코드가 그 칸을 만드나**를 본다.
      「사용불가라 안 만든다」고 적어 둔 주석까지 걸리면 거짓 경보가 되고,
      그 경보 때문에 진짜 문제를 놓친다(이 세션에서 이미 한 번 겪었다).
    """
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'compile_more.py').read_text(encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines() if not l.lstrip().startswith('#'))
    assert "'pcs_coupon_gmk'" not in 코드만
    assert 'isUseGmkPcsCoupon' not in 코드만


# ── 쿠팡·롯데온 ───────────────────────────────────────────────────────────

def test_쿠팡에는_가격비교_칸을_안_만든다():
    """🔴 지도·라이브 둘 다 0건 — 없는 칸을 지어내면 등록이 거부된다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'compile_coupang.py').read_text(encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines() if not l.lstrip().startswith('#'))
    for 금지 in ('price_compare_expose', 'naverShoppingRegistration', 'prcCmpExpYn'):
        assert 금지 not in 코드만, f'쿠팡에는 그런 칸이 없다: {금지}'


def test_롯데온은_확인_불가라_안_보낸다():
    """등록 API 필드가 지도에 부분만 실려 있다 — 지어내지 않는다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'compile_more.py').read_text(encoding='utf-8')
    롯데 = 소스.split('def compile_lotteon')[1]
    코드만 = chr(10).join(l for l in 롯데.splitlines() if not l.lstrip().startswith('#'))
    assert 'price_compare_expose' not in 코드만


# ── 실제 마켓 payload 까지 이어지나 ───────────────────────────────────────
#
# 🔴 spec 만 채우고 payload 를 안 만들면 또 죽은 코드다 — 이 세션에서만 같은 형태를
#   세 번 봤다(바이트 상한 · 상품명 규칙 · 마켓별 계정).

def test_ESM_payload_에_pcs_가_들어간다():
    from shared.platforms.esm.products import build_esm_register_payload
    공통 = dict(market='auction', goods_name='X', cat_code='1', site_cat_code='2',
              site_type=1, price=10000, stock=1, place_no=1, dispatch_policy_no=1,
              return_addr_no='1', delivery_company_no=1, official_notice_no=1,
              official_notice_details=[], image_url='http://x/a.jpg', detail_html='<p>x</p>')
    p = build_esm_register_payload(pcs_use=True, pcs_coupon_iac=False, **공통)
    assert p['addtionalInfo']['pcs'] == {'isUse': True, 'isUseIacPcsCoupon': False}


def test_ESM_payload_는_안_정하면_pcs_칸이_없다():
    from shared.platforms.esm.products import build_esm_register_payload
    p = build_esm_register_payload(
        market='auction', goods_name='X', cat_code='1', site_cat_code='2',
        site_type=1, price=10000, stock=1, place_no=1, dispatch_policy_no=1,
        return_addr_no='1', delivery_company_no=1, official_notice_no=1,
        official_notice_details=[], image_url='http://x/a.jpg', detail_html='<p>x</p>')
    assert 'pcs' not in p['addtionalInfo']


def test_ESM_전송이_spec_의_pcs_를_넘긴다():
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'send_more.py').read_text(encoding='utf-8')
    assert "pcs_use=spec.get('pcs_use')" in 소스
    assert "pcs_coupon_iac=spec.get('pcs_coupon_iac')" in 소스


def _11번가_XML(**extra):
    from shared.platforms.eleven11.products import build_register_xml
    f = dict(disp_ctgr_no='1011634', prd_nm='X', brand='르무통', as_detail='1588',
             image_url='http://x/a.jpg', detail_html='<p>x</p>', price=10000, stock=1,
             addr_seq_out='1', addr_seq_in='1', return_cost=5000, exchange_cost=10000)
    f.update(extra)
    return build_register_xml(f)


def test_11번가_XML_에_가격비교_줄이_들어간다():
    xml = _11번가_XML(prc_cmp_exp_yn='Y', prc_dsc_cmp_exp_yn='N')
    assert '<prcCmpExpYn>Y</prcCmpExpYn>' in xml
    assert '<prcDscCmpExpYn>N</prcDscCmpExpYn>' in xml


def test_11번가_XML_은_안_정하면_줄_자체가_없다():
    """지금까지 안 보내던 칸이다 — 갑자기 보내기 시작하면 그게 변경이다."""
    xml = _11번가_XML()
    assert 'prcCmpExpYn' not in xml
    assert 'prcDscCmpExpYn' not in xml
