# -*- coding: utf-8 -*-
"""🔴 자동 계산이 **사장님이 손으로 정한 값을 덮으면 안 된다.**

[2026-08-13] 수기 가격을 전송에 이으면서 드러났다.
`webapp/routes/api.py` 의 `bundle_price_apply`(가격 적용/푸시)가 계산한 값을
**수기 칸(option_price_config.manual_ss_price / manual_stock)에 그대로 써 넣는다.**

    UPDATE option_price_config SET manual_stock=:st, manual_ss_price=:p …

그 칸은 「사장님이 자동을 끄고 직접 넣은 값」이 사는 자리다.
예전엔 아무도 그 칸을 안 읽어서 티가 안 났지만, 이제 **전송이 그 칸을 읽는다.**
그대로 두면 이런 일이 벌어진다:

    ① 사장님이 자동을 끄고 120,000 을 넣는다
    ② 가격 적용을 한 번 돌린다  → 그 칸이 자동 계산값으로 덮인다
    ③ 다음 전송에 **자동값이 나간다** — 사장님은 120,000 인 줄 안다

에러도 안 나고 화면도 그럴듯해서 **아무도 모른다.** 이 프로젝트가 가장 경계하는
조용한 실패다. 푸시 이력은 수기 칸이 아니라 **다른 자리에** 남겨야 한다.
"""
from __future__ import annotations

import inspect
import re


def _price_apply_src() -> str:
    """가격 적용 라우트의 **코드만** — 주석·독스트링은 뺀다.

    ⚠️ 낱말로 판정하는 시험은 **설명 글까지 잡는다.** 「예전엔 이렇게 썼다」고 적은
       주석 때문에 멀쩡한 코드가 실패했다(2026-08-13). 낱말 검사는 코드에만 건다.
    """
    from webapp.routes import api
    src = inspect.getsource(api.bundle_price_apply)
    out = []
    for line in src.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            out.append(code)
    return "\n".join(out)


def test_가격적용이_수기_가격칸에_안_쓴다():
    """사장님이 정한 가격을 자동값으로 덮으면 그게 그대로 마켓에 나간다."""
    src = _price_apply_src()

    assert not re.search(r"manual_ss_price\s*=\s*:", src), (
        "가격 적용이 수기 가격칸(manual_ss_price)에 자동 계산값을 써 넣는다 — "
        "사장님이 손으로 정한 값이 조용히 지워지고 그 자동값이 마켓에 나간다")
    assert not re.search(r"manual_cp_price\s*=\s*:", src)


def test_가격적용이_수기_재고칸에_안_쓴다():
    """재고도 마찬가지 — 실사한 수가 자동값으로 덮이면 오버셀이다."""
    src = _price_apply_src()

    assert not re.search(r"manual_stock\s*=\s*:", src), (
        "가격 적용이 수기 재고칸(manual_stock)에 계산값을 써 넣는다")


def test_자동_스위치를_임의로_켜지_않는다():
    """`auto_enabled=1` 을 끼워 넣으면 사장님이 꺼 둔 수기 모드가 풀린다."""
    src = _price_apply_src()

    assert "auto_enabled" not in src, (
        "가격 적용이 자동/수기 스위치를 건드린다 — 사장님이 꺼 둔 걸 켜면 안 된다")
