# -*- coding: utf-8 -*-
"""실전송 안전 게이트 — real 어댑터 사용 조건(3중)."""
from scripts.live_send_skus import resolve_send_mode


def test_dryrun_when_not_requested():
    use_real, reason = resolve_send_mode(want_live=False, confirmed=False, server_key_on=False)
    assert use_real is False
    assert reason is None


def test_refuse_live_without_confirm():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=False, server_key_on=True)
    assert use_real is False
    assert reason and "확인" in reason


def test_refuse_live_without_server_key():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=True, server_key_on=False)
    assert use_real is False
    assert reason and "MOUM_LIVE_UPLOAD" in reason


def test_real_only_when_all_three():
    use_real, reason = resolve_send_mode(want_live=True, confirmed=True, server_key_on=True)
    assert use_real is True
    assert reason is None
