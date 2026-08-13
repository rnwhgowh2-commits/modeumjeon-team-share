# -*- coding: utf-8 -*-
"""사장님이 확정해 주신 수수료율 — 두 표가 갈리지 않게 묶어 둔다.

사장님 확정 (2026-08-13)
  · 롯데온 **판매수수료 13%**
  · 11번가 **11%(1년 이내 8%)이고 가격비교 노출 2% 는 미포함** → 늘 켜므로 13%(10%)

🔴 왜 시험으로 묶나 — 같은 「수수료율」이 저장소에 두 곳 있다:
    `pricing/fee_defaults.SEED`        판매가를 정하는 값
    `margin/settle_plan._EXPECT_FEE_PCT` 정산율이 이상한지 판정하는 값
  한쪽만 고치면 ① 정산이 정상인데 「이상하다」고 거짓 경고가 뜨거나
  ② 진짜 이상을 놓친다. 실제로 롯데온이 18 vs 13 으로 갈려 라이브에
  **9.6%p 거짓 경고**를 띄우고 있었다.
"""
import pytest

from lemouton.margin.settle_plan import _EXPECT_FEE_PCT
from lemouton.pricing.fee_defaults import SEED


def test_롯데온은_13퍼센트():
    assert SEED['lotteon']['base_pct'] == 13.0


def test_11번가는_가격비교_2를_더한_13퍼센트():
    """계약 11 + 가격비교 2 = 13. 1년 이내 계정은 8 + 2 = 10."""
    assert SEED['eleven11']['base_pct'] == 13.0
    assert SEED['eleven11']['alt_pct'] == 10.0
    assert SEED['eleven11']['alt_label'] == '1년 이내 계정'


def test_판매가용_표와_정산판정용_표가_같다():
    """🔴 두 표가 갈리면 거짓 경고가 뜨거나 진짜 이상을 놓친다."""
    for market, row in SEED.items():
        assert market in _EXPECT_FEE_PCT, f'{market} 이 정산 판정 표에 없다'
        assert row['base_pct'] == _EXPECT_FEE_PCT[market], (
            f"{market}: 판매가용 {row['base_pct']} vs 정산판정용 "
            f"{_EXPECT_FEE_PCT[market]} — 한쪽만 고쳐졌다")


def test_실정산_공식과_롯데온이_맞는다():
    """🔴 문서가 아니라 **코드**와 맞댄다 — 실정산 엑셀 86행 오차0 으로 검증된 것."""
    from lemouton.margin.lotteon_settlement import compute_settlement
    상품가 = 100_000
    직영 = compute_settlement(상품가, 0, 0, 0, 0, False)      # 롯데ON 직접 유입
    실효 = (상품가 - 직영) / 상품가 * 100
    assert abs(실효 - SEED['lotteon']['base_pct']) < 0.01, \
        f'판매가용 요율과 실정산 공식이 다르다: {SEED["lotteon"]["base_pct"]} vs {실효}'


def test_제휴_경유는_2퍼센트가_더_붙는다는_사실이_적혀_있다():
    """🔴 13% 로 판매가를 내므로, 제휴로 들어온 주문은 목표보다 2%p 적게 남는다.

    안 적어 두면 다음 사람이 「13% 면 끝」으로 알고 그 위에 집을 짓는다.
    """
    from lemouton.pricing.fee_defaults import RATE_EVIDENCE
    note = str(RATE_EVIDENCE['lotteon'].get('note') or '')
    assert '제휴' in note and '2' in note, '제휴 경유 2% 가 안 적혀 있다'


def test_가격비교를_끄면_되돌려야_한다는_사실이_적혀_있다():
    from lemouton.pricing.fee_defaults import RATE_EVIDENCE
    note = str(RATE_EVIDENCE['eleven11'].get('note') or '')
    assert '11' in note, '가격비교를 끌 때 돌아갈 값(11)이 안 적혀 있다'


def test_옛_값을_고치는_마이그레이션이_있다():
    """🔴 씨앗만 고치면 **이미 심긴 라이브 행은 안 바뀐다** — 판매가가 옛 요율로 나간다."""
    import inspect

    from shared import db as DB
    src = inspect.getsource(DB._apply_lightweight_migrations)
    assert 'market_fee_defaults' in src, '라이브 표를 고치는 코드가 없다'
    assert 'base_pct = :old' in src or 'base_pct = :new' in src, \
        '옛 값일 때만 고치는 조건이 없다 — 사장님이 손수 바꾼 값을 덮어쓸 수 있다'
