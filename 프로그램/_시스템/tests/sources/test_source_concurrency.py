# -*- coding: utf-8 -*-
"""[TEST] 소싱처별 동시 상한 저장/조회.

행 없으면 성격 기본값(창없이 8 / 창 필요 3). 저장하면 그 값. 1~10 클램프. None=해제.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base
import lemouton.sources.models  # noqa: F401 — 테이블 등록
from lemouton.sources.crawl_schedule import (
    default_source_concurrency, resolve_source_concurrency,
    set_source_concurrency, get_source_concurrency_map, source_is_windowless,
)


@pytest.fixture
def s():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    sess = Session(eng)
    yield sess
    sess.close()


class TestDefaults:
    def test_windowless_default_8(self):
        assert source_is_windowless("hmall") is True
        assert default_source_concurrency("hmall") == 8

    def test_windowed_default_3(self):
        assert source_is_windowless("musinsa") is False
        assert default_source_concurrency("musinsa") == 3

    def test_resolve_uses_default_when_no_row(self, s):
        assert resolve_source_concurrency(s, "lotteon") == 3
        assert resolve_source_concurrency(s, "ssg") == 8


class TestSetGet:
    def test_set_then_resolve(self, s):
        set_source_concurrency(s, "musinsa", 5)
        assert resolve_source_concurrency(s, "musinsa") == 5

    def test_clamp_1_to_10(self, s):
        assert set_source_concurrency(s, "hmall", 99) == 10
        assert set_source_concurrency(s, "hmall", 0) == 1
        assert set_source_concurrency(s, "hmall", -5) == 1

    def test_none_reverts_to_default(self, s):
        set_source_concurrency(s, "hmall", 2)
        assert resolve_source_concurrency(s, "hmall") == 2
        set_source_concurrency(s, "hmall", None)
        assert resolve_source_concurrency(s, "hmall") == 8   # 성격 기본값

    def test_map_only_explicit(self, s):
        set_source_concurrency(s, "musinsa", 4)
        m = get_source_concurrency_map(s)
        assert m == {"musinsa": 4}   # 저장 안 한 건 미포함

    def test_empty_key_raises(self, s):
        with pytest.raises(ValueError):
            set_source_concurrency(s, "", 3)
