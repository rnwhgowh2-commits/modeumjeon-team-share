# -*- coding: utf-8 -*-
"""자체 바코드 — 브랜드 공식 바코드가 없을 때만 우리가 만든다.

━━ 왜 이 파일이 있나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  라벨을 붙이고 재고를 스캔하려면 옵션마다 바코드가 있어야 한다. 그런데 브랜드가
  공식 바코드를 안 주는 상품(자체제작·수공예·비브랜드)이 있다. 그때 쓸 값을 만든다.

🔴 **이 값은 쿠팡에 보내면 안 된다.** 쿠팡 공지(2026-05-27, API 등록 상품은
   2026-08-01 시행)가 「임의로 생성한 숫자」·「판매자 내부 관리용 SKU 코드」를
   상품 식별번호로 쓰는 것을 **금지**한다. 어기면 등록 제한 또는 노출 제한이다.
   → `for_market()` 이 마켓마다 보낼지 말지를 정한다. 직접 꺼내 쓰지 말 것.

🔴 **왜 `2` 로 시작하나** — 국제표준(GS1)이 200~299 를 **매장 내부용**으로 비워
   두었다. 한국 정식 상품은 880 으로 시작하므로 **겹칠 수가 없다.** 덕분에
   값만 보고도 「이건 공식이 아니다」를 알 수 있어, 출처를 담는 칸을 따로 두지
   않아도 된다(칸을 둘로 나누면 값과 표시가 어긋난다 — 이 저장소의 반복 사고다).

🔴 **숫자만 쓴다**(사장님 확정). 영문이 섞이면 EAN-13 이 아니라서 스캐너가 못 읽고,
   마켓도 표준상품코드로 인정하지 않는다.
"""
from __future__ import annotations

#: 사내용 예약 대역의 첫 글자. 바꾸면 기존 라벨과 어긋난다.
INTERNAL_PREFIX = '2'

#: 일련번호가 들어갈 자리 수 (앞 1 + 여기 11 + 체크디지트 1 = 13)
_SERIAL_LEN = 11
_MAX_SERIAL = 10 ** _SERIAL_LEN - 1

#: 자체 바코드를 마켓으로 내보내는 곳.
#:
#: 🔴 [2026-08-13 사장님 확정] **비어 있다 — 어느 마켓에도 안 보낸다.**
#:   자체 생성 값은 라벨 인쇄·재고 스캔용이고, 마켓에 보낼 이유가 지금은 없다.
#:   (스마트스토어는 칸 이름이 `sellerBarcode`(판매자 바코드)라 기술적으로는 되지만,
#:    사장님이 「지금 불필요하다」로 정하셨다. 나중에 필요해지면 여기에 'smartstore'
#:    한 줄만 넣으면 된다 — 판단이 이 한 곳에 모여 있다.)
_SELF_OK = ()

#: 공식 바코드라면 보내는 마켓. 확인한 것만.
_OFFICIAL_OK = ('coupang', 'smartstore', 'auction', 'gmarket')


def _check_digit(twelve: str) -> str:
    """EAN-13 체크디지트 — 홀수 자리 합 + 짝수 자리 합×3 을 10 의 배수로 채운다."""
    odd = sum(int(c) for c in twelve[0::2])
    even = sum(int(c) for c in twelve[1::2])
    return str((10 - (odd + even * 3) % 10) % 10)


def make_internal(serial: int) -> str:
    """일련번호 → 자체 바코드 13자리. 같은 번호는 늘 같은 값이 나온다.

    🔴 지어내지 않는다 — 담을 수 없는 번호는 조용히 자르지 말고 거절한다.
      잘라 내면 서로 다른 옵션이 **같은 바코드**를 갖게 되고, 스캔이 엉뚱한
      제품을 집는다(에러 없이 물건만 틀리는 사고다).
    """
    n = int(serial)
    if n < 1 or n > _MAX_SERIAL:
        raise ValueError(
            f'바코드로 만들 수 없는 번호입니다: {serial} '
            f'(1 ~ {_MAX_SERIAL:,} 까지만 됩니다)')
    body = INTERNAL_PREFIX + str(n).zfill(_SERIAL_LEN)
    return body + _check_digit(body)


def is_internal(value) -> bool:
    """우리가 만든 값인가. **화면이 매 행 부르므로 무엇이 와도 안 터진다.**"""
    s = str(value or '').strip()
    return len(s) == 13 and s.isdigit() and s.startswith(INTERNAL_PREFIX)


def for_market(value, market: str) -> str:
    """그 마켓에 실제로 보낼 바코드. 보내면 안 되면 빈 문자열.

    🔴 쿠팡에 자체 생성 값을 보내면 **노출 제한**이다 — 빈 값으로 만들어
      `emptyBarcode=true` 로 나가게 한다(그게 쿠팡이 정해 둔 정식 탈출구다).
    """
    s = str(value or '').strip()
    mk = str(market or '').strip()
    if not s or not mk:
        return ''
    if is_internal(s):
        return s if mk in _SELF_OK else ''
    return s if mk in _OFFICIAL_OK else ''
