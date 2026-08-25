# -*- coding: utf-8 -*-
"""옵션별 대표이미지 (Phase 4-4).

🔴 이 파일이 막는 사고
  ① 옵션마다 사진을 걸어 뒀는데 **모든 옵션에 대표 사진 한 장이 똑같이** 나갔다.
     쿠팡은 옵션별 사진을 받는데도 그랬다 — 색이 달라도 구매자에겐 같은 사진.
  ② 「확인 불가」를 「안 받는다」로 적으면, 나중에 받는 걸로 밝혀져도 아무도 다시 안 본다.
"""
import pytest

from lemouton.registration import option_images as OI
from lemouton.registration.options import build_coupang_items


# ── 마켓 지원 표 ──────────────────────────────────────────────────────────

def test_쿠팡만_옵션별로_실제로_나간다():
    """🔴 [2026-08-25 정정] 11번가를 「나감」으로 적어 뒀는데 사실이 아니었다.

    지도 원문이 **조건부**다 — 「우아(OOAh) 서비스 상품일 경우」 + 「첫번째 옵션에
    해당하는 항목들 기준으로만」. 게다가 우리 11번가 등록 XML 은 이 칸을 아예 안
    만든다. 화면이 「나감」이라 말하면 사장님은 걸린 줄 안다.
    """
    assert OI.sends_per_option('coupang') is True
    assert OI.sends_per_option('eleven11') is False


def test_11번가는_조건과_미배선을_같이_말한다():
    상태, 왜 = OI.support_of('eleven11')
    assert 상태 == OI.NOT_WIRED
    assert '우아' in 왜, '조건(OOAh 서비스)을 안 말하면 「왜 안 되지」가 된다'
    assert '첫 번째 옵션' in 왜, '색상별까지라는 한계를 말해야 한다'
    assert '안 보내고' in 왜, '우리가 아직 안 보낸다는 사실을 말해야 한다'


def test_옥션과_G마켓은_마켓이_막아_뒀다():
    """지도에 「사용하지 않음, 입력 불가」 — 걸어 두어도 안 나간다."""
    for mk in ('auction', 'gmarket'):
        상태, 왜 = OI.support_of(mk)
        assert 상태 == OI.UNSUPPORTED
        assert '입력 불가' in 왜
        assert OI.sends_per_option(mk) is False


def test_스스와_롯데온은_확인_불가다():
    """🔴 「없다」가 아니라 「모른다」다 — 단정하면 다시 안 본다."""
    for mk in ('smartstore', 'lotteon'):
        상태, 왜 = OI.support_of(mk)
        assert 상태 == OI.UNKNOWN
        assert '모른다' in 왜 or '확인' in 왜
        assert OI.sends_per_option(mk) is False, '모르면 안 보낸다'


def test_모르는_마켓도_안_터진다():
    상태, _ = OI.support_of('없는마켓')
    assert 상태 == OI.UNKNOWN


def test_화면이_쓸_배지에_이유가_붙는다():
    got = OI.badges()
    assert len(got) == 6
    for b in got:
        assert b['label'] and b['why'], '왜 그런지 없이 배지만 달면 못 고친다'
    쿠팡 = [b for b in got if b['market'] == 'coupang'][0]
    assert 쿠팡['label'] == '옵션별로 나감'
    십일 = [b for b in got if b['market'] == 'eleven11'][0]
    assert 십일['label'] == '아직 안 보냄'


# ── 쿠팡 옵션별 사진이 실제로 실리나 ──────────────────────────────────────

def _옵션(color, size, image_url='', stock=5):
    return {'color': color, 'size': size, 'stock': stock,
            'sku': f'{color}-{size}', 'image_url': image_url}


def test_옵션마다_다른_사진이_나간다():
    """🔴 예전엔 대표 사진 한 장이 모든 옵션에 똑같이 붙었다."""
    opts = [_옵션('블랙', '270', 'https://r2/black.jpg'),
            _옵션('화이트', '270', 'https://r2/white.jpg')]
    items, _ = build_coupang_items(opts, sale_price=50000,
                                   image_url='https://r2/대표.jpg')
    나간사진 = [it['images'][0]['vendorPath'] for it in items]
    assert 나간사진 == ['https://r2/black.jpg', 'https://r2/white.jpg']


def test_옵션에_사진이_없으면_대표_사진으로_되받는다():
    """지어내지 않는다 — 대표 사진은 실제로 있는 사진이다."""
    opts = [_옵션('블랙', '270'), _옵션('화이트', '270', 'https://r2/white.jpg')]
    items, _ = build_coupang_items(opts, sale_price=50000,
                                   image_url='https://r2/대표.jpg')
    나간사진 = [it['images'][0]['vendorPath'] for it in items]
    assert 나간사진 == ['https://r2/대표.jpg', 'https://r2/white.jpg']


def test_대표도_옵션도_사진이_없으면_빈_채로_둔다():
    opts = [_옵션('블랙', '270')]
    items, _ = build_coupang_items(opts, sale_price=50000, image_url='')
    assert items[0]['images'] == []


def test_옵션_사진이_공백뿐이면_대표로_되받는다():
    opts = [_옵션('블랙', '270', '   ')]
    items, _ = build_coupang_items(opts, sale_price=50000,
                                   image_url='https://r2/대표.jpg')
    assert items[0]['images'][0]['vendorPath'] == 'https://r2/대표.jpg'


def test_구성_사본이_옵션_사진을_싣는다():
    """사본이 안 실으면 조립기가 아무리 잘해도 늘 대표 사진만 나간다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'policy' / 'to_payload.py').read_text(encoding='utf-8')
    assert "'image_url': o.image_url or ''" in 소스


def test_정규화가_사진을_안_버린다():
    """🔴 여기서 버려서 조립기까지 도달을 못 했다."""
    import pathlib
    소스 = (pathlib.Path(__file__).resolve().parents[2]
            / 'lemouton' / 'registration' / 'options.py').read_text(encoding='utf-8')
    코드만 = chr(10).join(l for l in 소스.splitlines()
                        if not l.lstrip().startswith('#'))
    assert "'image_url': _text(o.get('image_url'))" in 코드만


# ── 화면에 실제로 그려지나 ────────────────────────────────────────────────

import os  # noqa: E402

os.environ.setdefault('DISABLE_AUTH', '1')


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tests.design.conftest import _build_isolated_app, _원래대로_되돌리기
    app, temp_engine, temp_session, o_e, o_s = _build_isolated_app(tmp_path, monkeypatch)

    import sys as _sys
    for _m in list(_sys.modules.values()):
        if _m is None:
            continue
        try:
            if getattr(_m, 'SessionLocal', None) is o_s:
                monkeypatch.setattr(_m, 'SessionLocal', temp_session)
        except Exception:       # noqa: BLE001
            pass

    with app.test_client() as c:
        c._Session = temp_session
        yield c
    _원래대로_되돌리기(temp_engine, temp_session, o_e, o_s)
    temp_engine.dispose()


@pytest.fixture()
def html(client):
    pid = client.post('/api/policies', json={'name': 'P'}).get_json()['id']
    r = client.get(f'/policies/{pid}?m=coupang')
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_화면이_마켓별로_말해_준다(html):
    assert '옵션별 사진, 어디로 나가나' in html
    assert '옵션별로 나감' in html
    assert '안 나감' in html
    assert '확인 불가' in html


def test_왜_안_나가는지도_말해_준다(html):
    """배지만 달면 사장님이 못 고친다 — 왜인지를 같이 준다."""
    assert '입력 불가' in html


def test_이미지_항목_원래_칸이_안_사라졌다(html):
    """회귀 — 배지를 끼우면서 기존 입력칸을 밀어내지 않았나."""
    assert 'data-k="square_crop"' in html
    assert 'data-k="excluded_brands"' in html
