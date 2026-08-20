# -*- coding: utf-8 -*-
"""마켓이 「필수」라고 못 박은 칸이 **빈 채로 나가지 못하게** 막는가.

🔴 `policy/required.py` 는 지금까지 **화면만** 읽었다 — 전송 경로는 한 번도
   보지 않았다. 그래서 상품명·상세설명이 빈 상품이 payload 로 조립됐다
   (실제로 확인: sellerProductName='' · content='' 로 만들어졌다).

🔴 「모른다」는 막지 않는다. 롯데온은 등록 API 문서를 아직 못 열어 전 항목이
   「확인 불가」다 — 모르는 것을 막으면 라이브 전송이 조용히 멈춘다.
"""
from lemouton.registration.process_apply import apply_rules, blocking_reasons


class _Draft:
    def __init__(self, **kw):
        self.name = '르무통 스니커즈'
        self.brand = '르무통'
        self.detail_html = '<p>상세</p>'
        self.minor_purchasable = True
        for k, v in kw.items():
            setattr(self, k, v)


def _blocked(draft, market, rules=None):
    _, _, skipped = apply_rules(draft, rules or {}, market=market)
    return blocking_reasons(skipped)


# ── 빈 채로 나가면 안 되는 것 ───────────────────────────────────────────────

def test_상품명이_비면_막는다():
    got = _blocked(_Draft(name=''), 'coupang')
    assert got, '빈 상품명이 그대로 나갈 뻔했다'
    assert '상품명' in ' '.join(got)


def test_상세설명이_비면_말은_하되_막지는_않는다():
    """🔴 상세설명은 **모음전 구성에 담을 칸이 아예 없다**(set_view 의 detail_html='').

    여기서 막으면 모음전 전송이 **통째로 멈춘다.** 「칸이 있는데 비었다」와
    「칸이 없다」는 다른 문제다 — 앞은 막고, 뒤는 말한다.
    """
    _, _, skipped = apply_rules(_Draft(detail_html=''), {}, market='coupang')
    s = [x for x in skipped if x['field'] == 'detail_html']
    assert s, '상세가 빈 채로 나가는 걸 조용히 넘겼다'
    assert s[0]['blocking'] is False, '막으면 모음전 전송이 통째로 멈춘다'
    assert s[0]['gap'] is True
    assert blocking_reasons(skipped) == []


def test_모음전_구성은_상세가_늘_비어_있다():
    """🔴 실제 모양으로 재 본다 — 이 사실을 놓쳐 전송을 전량 막을 뻔했다."""
    from lemouton.policy.to_payload import set_view          # noqa: F401  (존재 확인)
    import inspect
    from lemouton.policy import to_payload
    src = inspect.getsource(to_payload)
    assert "'detail_html': ''," in src, \
        '구성에 상세 칸이 생겼다면 이 시험과 게이트를 다시 봐야 한다'


def test_공백만_있어도_빈_것으로_본다():
    assert _blocked(_Draft(name='   '), 'coupang')


def test_다_차_있으면_안_막는다():
    """🔴 멀쩡한 상품을 막으면 라이브 전송이 통째로 멈춘다."""
    assert _blocked(_Draft(), 'coupang') == []
    assert _blocked(_Draft(), 'smartstore') == []


# ── 마켓마다 「필수」가 다르다 ──────────────────────────────────────────────

def test_브랜드는_11번가에서만_막는다():
    """쿠팡·스스·ESM 은 브랜드가 선택이다 — 거기서 막으면 멀쩡한 상품이 멈춘다."""
    assert _blocked(_Draft(brand=''), 'eleven11'), '11번가는 브랜드가 필수다'
    assert _blocked(_Draft(brand=''), 'coupang') == []
    assert _blocked(_Draft(brand=''), 'smartstore') == []


def test_확인_못_한_마켓은_막지_않는다():
    """🔴 「확인 불가」와 「필수 아님」은 다르다 — 모르는 것으로 막지 않는다."""
    assert _blocked(_Draft(name='', detail_html='', brand=''), 'lotteon') == []


def test_마켓을_안_정하면_막지_않는다():
    """공통 가공(마켓 미지정)에서는 마켓 필수 판정을 쓸 수 없다."""
    assert _blocked(_Draft(name=''), '') == []


# ── 사유가 사람 말인가 ─────────────────────────────────────────────────────

def test_왜_막혔는지_말한다():
    _, _, skipped = apply_rules(_Draft(name=''), {}, market='coupang')
    s = [x for x in skipped if x['field'] == 'name'][0]
    assert s['blocking'] is True
    assert '쿠팡' in s['reason'] or '필수' in s['reason']
    assert s['code'] == 'MARKET_REQUIRED_EMPTY'


# ── 표와 게이트가 갈리지 않는가 ────────────────────────────────────────────

def test_막는_칸은_전부_초안에_실제로_있는_칸이다():
    """🔴 없는 칸 이름을 적어 두면 getattr 이 늘 None → **멀쩡한 상품을 전부 막는다.**"""
    from lemouton.registration import models as M
    from lemouton.registration.process_apply import _MUST_NOT_BE_EMPTY
    cols = set(M.ProductDraft.__table__.columns.keys())
    for _, attr, label in _MUST_NOT_BE_EMPTY:
        assert attr in cols, f'{label}({attr}) 는 초안에 없는 칸이다'


def test_막는_칸은_전부_필수_판정을_받는_곳이_있다():
    """어느 마켓에서도 필수가 아닌 칸을 적어 두면 이 게이트는 영영 안 돈다."""
    from lemouton.policy import required as R
    from lemouton.registration.process_apply import (_MUST_NOT_BE_EMPTY,
                                                     _MARKET_LABEL)
    for item, _, label in _MUST_NOT_BE_EMPTY:
        got = [m for m in _MARKET_LABEL if R.status_of(m, item)[0] == R.REQUIRED]
        assert got, f'{label} 을 필수라고 하는 마켓이 하나도 없다 — 게이트가 헛돈다'
