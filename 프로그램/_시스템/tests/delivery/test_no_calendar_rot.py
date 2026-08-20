# -*- coding: utf-8 -*-
"""「달력썩음」 감시 — 날짜만 지나가도 저절로 빨간불이 되는 검사를 막는다.

무슨 일이 있었나 (2026-08-02~03)
    `tests/delivery/test_market_enrich.py` 가 주문일을 **'2026-06-01' 로 못 박아**
    두고 "조회 기간이 그 날짜를 덮는다"고 확인했다. 그런데 조회 기간의 바닥은
    `지금 - 62일`(_MAX_LOOKBACK_DAYS)이다. 그래서 그 날짜가 63일 전이 된
    **2026-08-02 부터 저절로 실패**했고, main 배포가 통째로 막혔다
    (PR #712·정산 PR 둘 다 「배포 전 검사」에서 떨어졌다).

    ★ 돈·로직은 멀쩡했다. **검사만 썩었다.** 그래서 고칠 곳도 검사였다.

이 파일이 지키는 것
    소급 상한(_MAX_LOOKBACK_DAYS)이 있는 한, 그 상한에 기대는 검사는 **못 박은
    날짜를 쓰면 안 된다.** 반드시 '오늘로부터 N일 전'처럼 굴러가는 날짜를 써야 한다.
    누가 다시 못 박으면 여기서 걸린다 — 배포가 막히기 **전에**.
"""
import datetime as dt
import io
import os
import re

_여기 = os.path.dirname(os.path.abspath(__file__))
_대상 = os.path.join(_여기, 'test_market_enrich.py')


def test_소급_상한이_그대로다():
    """상한이 바뀌면 아래 검사의 여유(40일)를 다시 봐야 한다."""
    from lemouton.delivery import market_enrich as me
    assert me._MAX_LOOKBACK_DAYS == 62, (
        '소급 상한이 바뀌었다 — test_market_enrich 의 「40일 전」이 아직 안쪽인지 확인하라')


def test_조회창_검사에_날짜를_못_박지_않았다():
    """`since` 를 견주는 자리에 못 박은 날짜가 있으면 언젠가 반드시 썩는다."""
    본문 = io.open(_대상, encoding='utf-8').read()
    나쁜 = []
    for 줄번호, 줄 in enumerate(본문.splitlines(), 1):
        벗김 = 줄.strip()
        if 벗김.startswith('#'):          # 설명글은 본보기로 날짜를 적어도 된다
            continue
        if 'since' not in 벗김 and 'until' not in 벗김:
            continue
        if re.search(r'date\(\s*20\d\d\s*,|["\']20\d\d-\d\d-\d\d["\']', 벗김):
            나쁜.append('%d행: %s' % (줄번호, 벗김))
    assert not 나쁜, (
        '조회 기간을 견주는 자리에 날짜를 못 박았다 — 「오늘로부터 N일 전」으로 적어라:\n'
        + '\n'.join(나쁜))


def test_지금_고친_검사는_상한_안쪽이다():
    """'오늘로부터 40일 전' 이 소급 상한(62일) 안쪽이어야 뜻이 유지된다.

    · 7일 기본창보다는 밖 (넓히는 동작을 실제로 시험한다)
    · 62일 상한보다는 안 (창이 그 날짜를 덮을 수 있다)
    """
    from lemouton.delivery import market_enrich as me
    주문일 = dt.date.today() - dt.timedelta(days=40)
    바닥 = (dt.datetime.now() - dt.timedelta(days=me._MAX_LOOKBACK_DAYS)).date()
    assert 바닥 <= 주문일, '40일 전이 소급 상한 밖으로 나갔다'
    assert 주문일 < dt.date.today() - dt.timedelta(days=7), '7일 기본창 안이면 시험이 안 된다'
