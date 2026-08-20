# -*- coding: utf-8 -*-
"""소싱처 재고 원시값 → 3상태 판정. **화면·전송이 함께 쓰는 단일 진실 원천.**

이 함수들은 원래 `webapp/routes/api_pricing.py` 안에 있었다. 라우트 안에 있으면
「마켓 전송」처럼 화면 밖에서 재고를 판정해야 하는 자리가 **자기 판정을 새로 만들게**
된다 — 그 순간 화면이 「품절」이라는데 전송은 「있음」으로 나가는 모순이 생긴다.
(이 저장소가 반복해서 겪은 원천 분열의 형태 그대로다.)

그래서 **로직은 한 글자도 바꾸지 않고** 여기로 옮기고, 라우트는 이 모듈을 다시
내보내기만 한다. 옛 이름(`_resolve_stock`·`_stock_state`)도 그대로 남아 기존
호출처·테스트가 하나도 안 바뀐다.

🔒 재고 3대 원칙 (CLAUDE.md) — 추정·폴백·평균 금지. 확인 못 하면 「확인 불가」.
"""

# config.SOURCING_AUTH['stock_cap'] 와 동일 — 무신사는 '충분'을 이 값으로 저장(센티넬).
STOCK_CAP = 10

# 불명(unknown) — 크롤은 됐으나 신뢰할 재고 신호를 못 읽음(API 키 불일치·파싱 실패·
#   호출 실패 등). "있음(999)"으로 둔갑 금지: 화면 ⚠️확인필요 + 수량0 취급(판매 제외).
#   None(미크롤=이번 런 안 긁음)과 구분되는 별개 상태.
STOCK_UNKNOWN = -1


def resolve_stock(site, raw, status=None):
    """site + raw(+last_status) → (qty:int|None, label:str, is_out:bool). 화면 표시 단일 진실 원천.

      raw == 0          → 품절
      raw is None       → 상태로 구분(가짜 '재고있음' 금지, 2026-06-28):
                            error → '크롤실패' / ok → '재고있음'(수량미상) / 그 외 → '미크롤'(시도조차 안함)
      raw >= 900        → 재고있음 (999 센티넬 · 상품합계 더미)
      무신사 raw >= CAP → 재고있음 (stock_cap=10 이 '충분' 센티넬)
      raw == -1         → ⚠️확인필요 (불명: 크롤됐으나 신호 못 읽음 · 수량0 취급)
      그 외 1~899       → 실수량 'N개'
    """
    if raw == STOCK_UNKNOWN:
        return (0, '⚠️확인필요', True)
    if raw == 0:
        return (0, '품절', True)
    # [2026-06-25] 롯데온 옵션 재고 정확히 999 = 품절 사이즈에 꽂히는 '대체상품' 센티넬(실재고 아님).
    #   롯데온 옵션 실재고는 작은 수(4·10·30·41·5)·0 뿐이고, 999×N 상품합계 더미는 >1000 이라 구분됨.
    #   → 옵션 999면 불명(⚠️확인필요·수량0). 다른 소싱처 999/롯데온 상품합계(6993 등)는 '충분' 유지.
    #   효과: 같은 색에 URL 여러 개일 때 완전한 B가 999(둔갑)를 빼고 정확한 품절 URL 을 픽.
    if (site or '') in ('lotteon', 'lotte') and raw == 999:
        return (0, '⚠️확인필요', True)
    if raw is None:
        # [2026-06-28] None = 재고값 없음 → 상태로 구분 (크롤 실패/미시도를 '재고있음'으로 둔갑 금지)
        # [2026-07-04] uncollected = 상품 크롤은 됐으나 '이 셀(색·사이즈) per-size 재고를 못
        #   긁음' → 예전엔 상품 last_stock(합계)·'재고있음'으로 둔갑(품절인데 있음=금전위험).
        #   폴백 금지·누락 표면화 원칙: '확인 불가'로 정직하게 드러낸다.
        # [2026-07-08] (다) not_sold = 소싱처가 옵션 목록을 성공 크롤했는데 이 색×사이즈가
        #   목록에 없음(미판매/소멸) → 품절. 판매 제외(기회손실 방향, 오버셀 아님).
        if status == 'not_sold':
            return (0, '품절', True)
        if status == 'uncollected':
            return (None, '확인 불가', False)
        if status == 'error':
            return (None, '크롤실패', False)
        if status == 'ok':
            return (None, '재고있음', False)   # 크롤 성공·수량미상 (드묾 — 본래 999여야 함)
        return (None, '미크롤', False)          # pending·None·no_crawler = 시도조차 안 함
    if raw >= 900:
        return (None, '재고있음', False)
    if (site or '') == 'musinsa' and raw >= STOCK_CAP:
        return (None, '재고있음', False)
    return (int(raw), f'{int(raw)}개', False)


def stock_state(site, raw, status=None):
    """재고 원시값(+last_status) → 상태 문자열(프론트 스타일/툴팁용). resolve_stock 과 동일 의미.
       soldout / unknown / limited / ample / uncrawled / crawlfail."""
    if raw is None:
        if status == 'not_sold':
            return 'soldout'       # (다) 소싱처 미판매/소멸 → 품절
        if status == 'uncollected':
            return 'uncollected'   # 매칭됐으나 이 셀 재고 미수집 → '확인 불가'
        if status == 'error':
            return 'crawlfail'
        if status == 'ok':
            return 'ample'
        return 'uncrawled'
    if raw == STOCK_UNKNOWN:
        return 'unknown'
    if raw == 0:
        return 'soldout'
    if (site or '') in ('lotteon', 'lotte') and raw == 999:
        return 'unknown'   # 롯데온 옵션 999 = 대체상품 센티넬 → 불명 (상품합계 더미 999×N 은 제외)
    if raw >= 900:
        return 'ample'
    if (site or '') == 'musinsa' and raw >= STOCK_CAP:
        return 'ample'
    return 'limited'


# ── 전송 게이트가 쓰는 한 마디 ──────────────────────────────────────────

#: 「있다고 단정할 수 없는」 상태들 — 이 상태로는 **마켓에 재고를 올리면 안 된다.**
#:   오버셀(없는 걸 있다고) 또는 기회손실(있는 걸 품절로) 어느 쪽이든 돈이 샌다.
NOT_SURE_STATES = frozenset({'unknown', 'uncollected', 'crawlfail', 'uncrawled'})


def sendable(site, raw, status=None) -> tuple[bool, int | None, str]:
    """마켓으로 이 재고를 보내도 되나. `(보내도 되나, 보낼 수량, 사유)`.

    · 품절(0)      → 보낸다. 0 은 확인된 값이다(품절도 정확한 정보다).
    · 실수량 N     → 보낸다.
    · '재고있음'   → 보낸다. 수량 미상이라 **마켓 상한을 호출자가 정한다**(여기선 None).
    · 그 밖(불명·미수집·크롤실패·미크롤) → **막는다.** 지어내지 않는다.
    """
    st = stock_state(site, raw, status)
    if st in NOT_SURE_STATES:
        label = resolve_stock(site, raw, status)[1]
        return (False, None, f'재고를 확인할 수 없습니다({label}) — 있다고 단정하지 않고 '
                             f'보내지 않습니다.')
    qty, _, _ = resolve_stock(site, raw, status)
    return (True, qty, '')
