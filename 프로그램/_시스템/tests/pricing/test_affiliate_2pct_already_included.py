# -*- coding: utf-8 -*-
"""가격비교(제휴) 2% — **또 더하면 이중 계상이다.**

사장님: 「2% 없으면 어떻게? 우리는 항상 켜.. 롯데온 같은 경우 실제 프로그램
들어가서 제휴 여부로 판단하고 있어」 (2026-08-13)

🔴 조사 결과, 「아직 계산에 안 들어간다」는 표현이 오해를 부른다.
  옥션 15% · G마켓 15% 는 **이미 「제휴 2% 포함」**된 값이고, 11번가는 미포함이라
  요율 자체를 13% 로 고쳤다. 어느 쪽이든 정책의 `fee_add_pct=2` 를 **또 더하면**
  수수료가 2%p 과대 계상돼 **판매가가 그만큼 비싸게 나간다**(팔리지 않는 손해).

  쿠팡은 등록 API 에 이 개념 자체가 없다.
  스마트스토어 6% 는 항목 합(결제 + 매출연동)이라 연동 몫이 이미 들어 있다.

🔴 **11번가는 미포함이었다** — 사장님 확정(2026-08-13) 「11%(1년 이내 8%)이고
  가격비교 노출 2% 는 미포함」. 그래서 정책 칸에서 더하는 게 아니라
  **요율 숫자 자체를 13%(1년 이내 10%)로 고쳤다** (계산이 쓰는 값은 언제나
  정책에 저장된 숫자 하나다 — `fee_defaults` 모듈 주석).
"""
import pytest

from lemouton.pricing.fee_defaults import AFFILIATE_IN_BASE, affiliate_note


def test_이미_포함된_마켓을_데이터로_안다():
    """🔴 코드 여기저기에 적어 두면 반드시 갈린다.

    🔴 [2026-08-13] 11번가가 **미포함**으로 확인되면서 요율 자체를 13%(10%)로
      고쳤다 — 그래서 이제 「포함」이다. 값을 표에 적는 게 아니라 요율을 고치는 것이
      이 저장소의 규약이다(계산이 쓰는 값은 언제나 숫자 하나).
    """
    for m in ('lotteon', 'eleven11', 'auction', 'gmarket'):
        assert AFFILIATE_IN_BASE.get(m) is True, f'{m} 은 이미 포함이다'


def test_쿠팡은_개념_자체가_없다():
    assert AFFILIATE_IN_BASE.get('coupang') is False


def test_롯데온_15퍼센트는_판매13에_유입2를_더한_값이다():
    """🔴 제휴 2% 는 **제휴 경유 주문에만** 붙는다 — 늘 켜므로 요율에 합쳐 뒀다.

    롯데ON 직접 유입 주문은 13% 만 빠져 2%p 더 남는다. 그 사실이 안 적혀 있으면
    다음 사람이 「늘 15% 빠진다」로 알고 그 위에 집을 짓는다.
    """
    from lemouton.pricing.fee_defaults import RATE_EVIDENCE, SEED
    assert SEED['lotteon']['base_pct'] == 15.0
    note = str(RATE_EVIDENCE['lotteon'].get('note') or '')
    assert '직접 유입' in note, '직영 주문이 다르다는 말이 없다'
    assert AFFILIATE_IN_BASE.get('lotteon') is True


def test_기존_NOTES_와_어긋나지_않는다():
    """🔴 같은 사실이 두 곳에 있으면 한쪽만 고쳐져 갈린다."""
    from lemouton.pricing.fee_defaults import NOTES
    for m, note in NOTES.items():
        if '제휴 2% 포함' in note:
            assert AFFILIATE_IN_BASE.get(m) is True, f'{m}: NOTES 와 표가 어긋난다'


def test_확정된_마켓은_포함이라고_말한다():
    got = affiliate_note('eleven11')
    assert got and ('이미' in got or '포함' in got), got


def test_이미_포함된_마켓은_더하지_말라고_말한다():
    got = affiliate_note('auction')
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
