# -*- coding: utf-8 -*-
"""수수료율 칸이 「저장된 값」인지 「기준값을 비춘 것」인지 화면이 말해야 한다.

🔴 [2026-08-13] 무엇이 문제였나 — 이 칸은 **안 정했을 때도 마켓 기준값을 채워서**
  보여 준다. 그래서 화면만 보면 두 경우가 똑같이 생겼다:

    ① 이 정책이 6.0 을 **저장해 뒀다**   → 마켓 기준을 고쳐도 **안 바뀐다**
    ② 아직 안 정해서 기준값 6.0 을 비췄다 → 기준을 고치면 **따라 바뀐다**

  둘은 정반대인데 구분이 안 됐다. 실제로 「마켓 기준을 13% 로 고쳤는데 왜 판매가가
  그대로냐」를 화면에서 가릴 수 없었다. 더 나쁜 건, 그 상태에서 저장을 누르면
  **비춰 주던 값이 그대로 굳어** 기준을 따라가지 않게 된다.

🔴 계산이 실제로 그렇게 동작한다는 것도 같이 못 박는다 — 화면 문구만 고치고
  계산이 반대면 더 나쁜 거짓말이 된다.
"""
import pytest


# ── 계산이 정말 「저장된 값 > 기준값」인가 ──────────────────────────────
def test_저장된_값이_마켓_기준을_이긴다():
    from lemouton.policy.as_template import _PolicyTemplate
    from lemouton.pricing.unified import default_fee_rate, resolve_market_policy

    저장함 = _PolicyTemplate({'lotteon': {'price': {
        'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45, 'fee_rate': 18}}})
    pol = resolve_market_policy(저장함, 'lotteon', 'sourcing')
    assert pol['fee_rate'] == pytest.approx(0.18), '저장된 18% 가 안 쓰인다'
    assert pol['fee_rate'] != pytest.approx(default_fee_rate('lotteon')), \
        '이 시험의 전제가 깨졌다 — 기준값과 같으면 구분이 안 된다'


def test_안_정했으면_마켓_기준을_따라간다():
    from lemouton.policy.as_template import _PolicyTemplate
    from lemouton.pricing.unified import default_fee_rate, resolve_market_policy

    안정함 = _PolicyTemplate({'lotteon': {'price': {
        'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45}}})
    pol = resolve_market_policy(안정함, 'lotteon', 'sourcing')
    assert pol['fee_rate'] == pytest.approx(default_fee_rate('lotteon'))


# ── 화면이 그 차이를 말하는가 ──────────────────────────────────────────
def _detail_html():
    from pathlib import Path
    p = (Path(__file__).resolve().parents[2] / 'webapp' / 'templates'
         / 'policy' / 'detail.html')
    return p.read_text(encoding='utf-8')


def test_화면이_두_경우를_갈라_말한다():
    """🔴 같은 6.0 이라도 뜻이 정반대다 — 어느 쪽인지 화면이 말해야 한다."""
    html = _detail_html()
    assert "cfg.get('fee_rate') is not none" in html, \
        '저장 여부를 화면이 아예 안 본다'
    assert '이 정책에 저장된 값' in html, '저장된 경우를 안 말한다'
    assert '아직 안 정하셨습니다' in html, '안 정한 경우를 안 말한다'


def test_저장하면_굳는다는_사실을_미리_알린다():
    """🔴 비춰 주던 값을 저장하면 그 순간 굳는다 — 누르기 전에 알아야 한다."""
    html = _detail_html()
    assert '굳어' in html or '굳습니다' in html, \
        '저장하면 기준을 안 따라간다는 사실을 안 알린다'
    # 🔴 마크다운 별표는 화면에 **글자 그대로** 찍힌다 — 강조는 <b> 로.
    assert '**굳' not in html, '별표가 화면에 그대로 나온다'


def test_기준을_고쳐도_안_바뀐다는_말이_있다():
    html = _detail_html()
    assert '이깁니다' in html or '안 바뀝니다' in html, \
        '저장된 값이 기준을 이긴다는 사실이 안 적혀 있다'
