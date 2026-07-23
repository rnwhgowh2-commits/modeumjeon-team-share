"""브랜드 제한 판정 — 정규화 비교·마켓/카테고리 범위."""
from lemouton.registration import brand_restrict as br


def _rule(brand='나이키', market='coupang', prefix='', active=True, reason='지재권'):
    return {'brand': brand, 'market': market, 'category_prefix': prefix,
            'active': active, 'reason': reason}


def test_브랜드는_대소문자_공백_무시하고_매칭한다():
    assert br.normalize('  Nike ') == br.normalize('NIKE') == br.normalize('nike')
    assert br.is_blocked([_rule(brand='NIKE')], brand='nike', market='coupang', cat_path='') is not None


def test_스타_마켓은_전마켓_차단이다():
    rules = [_rule(market='*')]
    for m in ('smartstore', 'coupang', 'eleven11'):
        assert br.is_blocked(rules, brand='나이키', market=m, cat_path='')


def test_카테고리_프리픽스가_있으면_그_경로_이하만_막는다():
    rules = [_rule(prefix='패션잡화>운동화')]
    assert br.is_blocked(rules, brand='나이키', market='coupang', cat_path='패션잡화>운동화>여성운동화')
    assert br.is_blocked(rules, brand='나이키', market='coupang', cat_path='가전>노트북') is None
    # 카테고리 미정(빈 경로)이면 보수적으로 막는다 — 지재권은 안전 우선
    assert br.is_blocked(rules, brand='나이키', market='coupang', cat_path='')


def test_비활성_규칙과_다른_브랜드는_안_막는다():
    assert br.is_blocked([_rule(active=False)], brand='나이키', market='coupang', cat_path='') is None
    assert br.is_blocked([_rule()], brand='아디다스', market='coupang', cat_path='') is None


# ── [2026-07-23 리뷰 C2] 브랜드가 비면 제한표가 통째로 무력해진다 ────────────

def test_브랜드가_비면_무판정이라_아무것도_안_막는다():
    """is_blocked 의 사실 확인 — 이게 needs_brand 가 존재하는 이유다."""
    assert br.is_blocked([_rule(market='*')], brand='', market='coupang', cat_path='') is None


def test_제한_규칙이_있는데_브랜드가_비면_사유를_준다():
    assert br.needs_brand([_rule()], '') == br.BRAND_REQUIRED_REASON
    assert br.needs_brand([_rule()], '   ') == br.BRAND_REQUIRED_REASON


def test_브랜드가_있거나_활성_규칙이_없으면_안_막는다():
    assert br.needs_brand([_rule()], '나이키') is None
    assert br.needs_brand([_rule(active=False)], '') is None
    assert br.needs_brand([], '') is None
