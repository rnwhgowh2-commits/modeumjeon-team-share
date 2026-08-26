# -*- coding: utf-8 -*-
"""옵션별 대표이미지를 **어느 마켓이 실제로 받나** (2026-08-24 Phase 4-4).

■ 왜 이 표가 필요한가
  화면에서 옵션마다 사진을 걸어 두어도, 마켓이 그 칸을 안 받으면 아무 일도 안 난다.
  그런데 화면이 「걸었다」고만 보여 주면 사장님은 **걸린 줄 안다.** 어느 마켓에
  실제로 나가는지를 화면이 말해야 한다.

■ 근거 — 2026-08-24 판매처 지도 **전문** 정독 + 라이브 대조 (consult-market-map 게이트)
  · 쿠팡    `items[].images` (vendorPath·imageType·imageOrder) → **받는다**
  · 11번가  `optionImage` → **조건부** — 「우아(OOAh) 서비스 상품」일 때만,
            그것도 첫 번째 옵션(보통 색상) 기준으로만. 게다가 **우리 등록 코드가
            아직 이 칸을 안 만든다** → 화면엔 「아직 안 보냄」으로 말한다.
  · 옥션    「옵션 이미지 url. **사용하지 않음, 입력 불가**」 → **안 받는다**
  · G마켓   위와 같음 → **안 받는다**
  · 스마트스토어 옵션 하위 이미지 칸이 지도에 없다 → **확인 불가**
  · 롯데온  등록 API 필드가 지도에 부분만 실려 있다 → **확인 불가**

🔴 「확인 불가」를 「안 받는다」로 적지 않는다. 모르는 것을 단정하면, 나중에 받는 걸로
  밝혀져도 아무도 다시 안 본다(이 저장소가 반복해 겪은 형태).
"""
from __future__ import annotations

#: 받는다 — 옵션마다 다른 사진이 **실제로 나간다**.
SUPPORTED = 'supported'
#: 마켓은 받지만 **우리가 아직 안 보낸다**. 「나간다」고 하면 거짓말이 된다.
#:   🔴 [2026-08-25 정정] 11번가를 `SUPPORTED` 로 적어 뒀는데, 우리 11번가 등록
#:     XML 은 이 칸을 아예 안 만든다 — 화면이 「나감」이라 말하고 있었다.
NOT_WIRED = 'not_wired'
#: 안 받는다 — 마켓이 칸을 막아 뒀다. 보내도 소용없거나 거부당한다.
UNSUPPORTED = 'unsupported'
#: 확인 불가 — 지도에 근거가 없다. **없다고 단정하지 않는다.**
UNKNOWN = 'unknown'

SUPPORT = {
    'coupang': (SUPPORTED,
                'items[].images — 옵션마다 다른 사진이 실제로 나갑니다.'),
    # 🔴 [2026-08-25 정정] 예전에 「받습니다」라고만 적어 뒀는데 지도 원문은 **조건부**다:
    #   ① 「옵션이미지 우아(OOAh)서비스 상품일 경우 등록이 가능합니다」 — 아무 상품이나 안 된다.
    #   ② 「첫번째 옵션에 해당하는 항목들 기준으로만」 — 색상별까지고, 색상×사이즈
    #      조합별은 안 된다.
    #   게다가 우리 11번가 등록 XML(`build_register_xml`)은 이 칸을 아예 안 만든다.
    'eleven11': (NOT_WIRED,
                 '11번가는 「우아(OOAh) 서비스 상품」일 때만, 그것도 첫 번째 옵션'
                 '(보통 색상) 기준으로만 받습니다. 우리 등록 코드는 아직 이 칸을 '
                 '안 보내고 있어서 지금은 대표 사진만 나갑니다.'),
    'auction': (UNSUPPORTED,
                '옥션 등록 API 문서에 「옵션 이미지 url. 사용하지 않음, 입력 불가」로 '
                '적혀 있습니다 — 걸어 두어도 안 나갑니다.'),
    'gmarket': (UNSUPPORTED,
                'G마켓 등록 API 문서에 「옵션 이미지 url. 사용하지 않음, 입력 불가」로 '
                '적혀 있습니다 — 걸어 두어도 안 나갑니다.'),
    'smartstore': (UNKNOWN,
                   '스마트스토어 등록 API 필드에서 옵션 하위 이미지 칸을 찾지 못했습니다 '
                   '— 「없다」가 아니라 「모른다」입니다. 지금은 대표 사진만 나갑니다.'),
    'lotteon': (UNKNOWN,
                '롯데온 등록 API 필드가 지도에 부분만 실려 있습니다 — 「없다」가 아니라 '
                '「모른다」입니다. 지금은 대표 사진만 나갑니다.'),
}

LABEL = {SUPPORTED: '옵션별로 나감', NOT_WIRED: '아직 안 보냄',
         UNSUPPORTED: '안 나감', UNKNOWN: '확인 불가'}


def support_of(market: str) -> tuple:
    """(상태, 왜) — 모르는 마켓도 「확인 불가」로 답한다(터지지 않는다)."""
    return SUPPORT.get(str(market or '').strip(),
                       (UNKNOWN, '지도에 그 마켓이 없습니다.'))


def sends_per_option(market: str) -> bool:
    """옵션마다 다른 사진이 실제로 나가나. 확인 불가는 **False** — 보내지 않는다."""
    return support_of(market)[0] == SUPPORTED


def badges(markets=None) -> list:
    """화면이 배지를 그릴 근거 — [{market, state, label, why}]."""
    from lemouton.policy.fields import MARKET_KEYS, MARKET_LABEL
    out = []
    for mk in (markets or MARKET_KEYS):
        st, why = support_of(mk)
        out.append({'market': mk, 'market_label': MARKET_LABEL.get(mk, mk),
                    'state': st, 'label': LABEL[st], 'why': why})
    return out
