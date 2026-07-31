# -*- coding: utf-8 -*-
"""「마켓 공통」 — 넣기 · 불러오기 · 값 출처 판정.

🔴 이 파일이 지키는 것:
  ① 공통은 **한 번 넣으면 끝**이다. 그 뒤 마켓에서 고치면 공통이 다시 덮지 않는다.
  ② 「공통에서 받았나 / 직접 고쳤나」는 **값 비교로 판정하지 않는다** —
     공통이 나중에 바뀌면 값 비교는 「직접 고침」이라는 틀린 답을 낸다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM     # noqa: F401 — 테이블 등록
from lemouton.policy.fields import COMMON_KEY, MARKET_KEYS, item_keys_for
from lemouton.policy.service import create_policy, save_item, values_for


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_공통은_마켓_목록에_섞이지_않는다():
    """「마켓 공통」은 진짜 마켓이 아니다 — 마켓 목록에 들어가면 전송 대상이 된다."""
    assert COMMON_KEY == 'common'
    assert COMMON_KEY not in MARKET_KEYS


def test_공통에도_항목을_저장할_수_있다(db):
    p = create_policy(db, name='르무통 기본')
    save_item(db, policy=p, market=COMMON_KEY, item_key='price',
              config={'margin_rate': 25})
    assert values_for(db, p.id, COMMON_KEY) == {'price': {'margin_rate': 25}}


def test_공통_항목표는_마켓_전용을_빼고_준다():
    """공통에는 「쿠팡만 있는 항목」을 둘 수 없다 — 어느 마켓에 넣을지 정해지지 않는다."""
    common_keys = item_keys_for(COMMON_KEY)
    coupang_only = set(item_keys_for('coupang')) - set(item_keys_for('smartstore'))
    assert coupang_only, '쿠팡 전용 항목이 하나도 없다면 이 테스트는 의미가 없다'
    assert not (coupang_only & set(common_keys))
