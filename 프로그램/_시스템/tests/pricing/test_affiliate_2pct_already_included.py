# -*- coding: utf-8 -*-
"""가격비교(제휴) 2% — **또 더하면 이중 계상이다.**

사장님: 「2% 없으면 어떻게? 우리는 항상 켜.. 롯데온 같은 경우 실제 프로그램
들어가서 제휴 여부로 판단하고 있어」 (2026-08-13)

🔴 조사 결과, 「아직 계산에 안 들어간다」는 표현이 오해를 부른다.
  `fee_defaults.NOTES` 가 말하듯 **롯데온 18% · 옥션 15% · G마켓 15% 는
  이미 「제휴 2% 포함」된 값**이다. 여기에 정책의 `fee_add_pct=2` 를 또 더하면
  수수료가 2%p 과대 계상돼 **판매가가 그만큼 비싸게 나간다**(팔리지 않는 손해).

  쿠팡은 등록 API 에 이 개념 자체가 없다.
  스마트스토어 6% 는 항목 합(결제 + 매출연동)이라 연동 몫이 이미 들어 있다.

🔴 **11번가만 근거가 없다.** 11%(1년 이내 8%)에 가격비교 몫이 포함인지
  확인된 문서가 없다. 모르는 것을 아는 척 더하지 않는다 — 사장님께 여쭙고
  정해지면 **정책의 수수료율 숫자 자체**를 고친다(계산이 쓰는 값은 언제나
  정책에 저장된 숫자 하나다 — `fee_defaults` 모듈 주석).
"""
import pytest

from lemouton.pricing.fee_defaults import AFFILIATE_IN_BASE, affiliate_note


def test_이미_포함된_마켓을_데이터로_안다():
    """🔴 코드 여기저기에 「롯데온은 포함」이라고 적어 두면 반드시 갈린다."""
    for m in ('lotteon', 'auction', 'gmarket'):
        assert AFFILIATE_IN_BASE.get(m) is True, f'{m} 은 이미 포함이다'


def test_쿠팡은_개념_자체가_없다():
    assert AFFILIATE_IN_BASE.get('coupang') is False


def test_11번가는_모른다고_말한다():
    """🔴 True/False 로 단정하지 않는다 — 근거가 없다."""
    assert AFFILIATE_IN_BASE.get('eleven11') is None


def test_기존_NOTES_와_어긋나지_않는다():
    """🔴 같은 사실이 두 곳에 있으면 한쪽만 고쳐져 갈린다."""
    from lemouton.pricing.fee_defaults import NOTES
    for m, note in NOTES.items():
        if '제휴 2% 포함' in note:
            assert AFFILIATE_IN_BASE.get(m) is True, f'{m}: NOTES 와 표가 어긋난다'


def test_모르는_마켓엔_안내가_모른다고_적힌다():
    got = affiliate_note('eleven11')
    assert got and ('확인' in got or '모' in got), got


def test_이미_포함된_마켓은_더하지_말라고_말한다():
    got = affiliate_note('lotteon')
    assert got and ('이미' in got or '포함' in got), got
    assert '더하' in got or '중복' in got or '이중' in got, \
        '또 더하면 안 된다는 말이 없다'


def test_정책_안내문이_거짓_숙제처럼_읽히지_않는다():
    """🔴 「아직 안 들어갑니다」는 「구현이 덜 됐다」로 읽힌다 — 사실은 반대다."""
    from lemouton.registration.process_rule_schema import SCHEMAS
    f = next(x for x in SCHEMAS['price_compare'].fields if x.key == 'fee_add_pct')
    assert '아직 안 들어갑니다' not in (f.hint or ''), \
        '안내가 아직 「구현이 덜 됐다」처럼 읽힌다'
    assert '이미' in (f.hint or ''), '이미 포함이라는 사실이 안내에 없다'
