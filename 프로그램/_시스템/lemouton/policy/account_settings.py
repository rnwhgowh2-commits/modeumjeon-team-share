# -*- coding: utf-8 -*-
"""2층 계정 설정 읽기 — 마켓 전송 코드의 **단일 창구**.

🔴 되받기 사슬을 여기 한 곳에만 둔다. 호출부마다 `getattr(s, k, None) or s.extra.get(k)`
   식으로 흩어 놓으면 「어느 값이 실제로 나갔나」를 못 쫓는다(이 프로젝트에서 반복적으로
   사고가 났던 형태 — 공용 규칙은 쓰는 곳 전부를 세어야 한다).

읽는 순서:
  ① 공통 컬럼(as_phone·return_fee 등) → ② extra JSON(마켓 전용 칸) → ③ 호출부 기본값
"""
from __future__ import annotations

from lemouton.policy.models import MarketAccountSetting

#: 공통 컬럼 이름 — extra 보다 먼저 본다.
_COLUMNS = frozenset({
    'as_phone', 'as_message', 'return_fee', 'exchange_fee', 'jeju_fee',
    'island_fee', 'tax_type', 'origin_default', 'stock_default',
    'promotion_message',
})


def setting_for(session, upload_account_id: int):
    """그 계정의 설정 한 벌. 아직 안 만들었으면 ``None``."""
    return (session.query(MarketAccountSetting)
            .filter_by(upload_account_id=upload_account_id)
            .one_or_none())


def value_of(session, upload_account_id: int, key: str, default=None):
    """설정 값 하나. **안 정했으면** ``default``.

    🔴 「안 정함」은 오직 ``None`` 뿐이다 (2026-08-24 사장님 확정).
      0 과 빈 문자열은 **사장님이 그렇게 정한 값**이라 그대로 돌려준다.
      예전에는 ``got in (None, '')`` 로 빈 문자열까지 「안 정함」 취급했는데,
      그러면 「A/S 안내를 일부러 비워 둠」과 「아직 안 씀」이 구분되지 않는다.

    ★ 0 을 「없음」으로 바꾸지 않는다 — 반품비 0원(무료 반품)과 미설정은 다른 뜻이고,
      배송비는 금전 직결이라 이 혼동이 곧 손실이다.
    """
    s = setting_for(session, upload_account_id)
    if s is None:
        return default
    if key in _COLUMNS:
        got = getattr(s, key)
        return default if got is None else got
    return (s.extra or {}).get(key, default)


def is_set(session, upload_account_id: int, key: str) -> bool:
    """그 칸을 **정한 적이 있나**. 0·빈 문자열도 「정한 것」으로 센다.

    화면이 「아직 안 정함」 배지를 띄우거나, 전송 게이트가 필수값 누락을 막을 때 쓴다.
    ``value_of(...) == 0`` 으로는 이걸 판정할 수 없다 — 그래서 별도 함수로 둔다.
    """
    s = setting_for(session, upload_account_id)
    if s is None:
        return False
    if key in _COLUMNS:
        return getattr(s, key) is not None
    return key in (s.extra or {})
