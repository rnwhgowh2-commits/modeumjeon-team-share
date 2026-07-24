# -*- coding: utf-8 -*-
"""시각은 「어느 시간대인지」를 반드시 함께 준다.

★ [2026-07-24 라이브에서 발견] 타임존 표시 없이 `2026-07-24T10:45:25` 를 주면
  브라우저가 이걸 **한국시간 10:45** 로 읽는다. 실제는 UTC 10:45 = 한국 19:45.
  방금 동기화했는데 화면에 「11시간 전」으로 떴다 — 사장님이 낡은 데이터로 오해한다.
"""
from datetime import datetime, timezone

from lemouton.catalog.timefmt import iso_utc


def test_시간대_없는_시각에_UTC_를_붙여_준다():
    naive = datetime(2026, 7, 24, 10, 45, 25)      # DB 에서 이렇게 돌아온다
    out = iso_utc(naive)
    assert out.endswith('+00:00'), f'시간대 표시가 없다: {out}'
    assert out.startswith('2026-07-24T10:45:25')


def test_이미_시간대가_있으면_그대로_둔다():
    aware = datetime(2026, 7, 24, 10, 45, 25, tzinfo=timezone.utc)
    assert iso_utc(aware).endswith('+00:00')


def test_없으면_None():
    assert iso_utc(None) is None


def test_브라우저가_읽으면_9시간_차이가_안_난다():
    """붙인 표시대로 읽으면 UTC 10:45 = 한국 19:45 여야 한다."""
    from datetime import timedelta
    out = iso_utc(datetime(2026, 7, 24, 10, 45, 25))
    parsed = datetime.fromisoformat(out)
    kst = parsed.astimezone(timezone(timedelta(hours=9)))
    assert kst.hour == 19 and kst.minute == 45
