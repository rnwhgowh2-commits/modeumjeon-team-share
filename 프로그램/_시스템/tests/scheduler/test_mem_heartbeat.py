# -*- coding: utf-8 -*-
"""메모리 심박 로그 — OOM 이 SIGKILL 이라 죽는 순간 코드가 못 도는 문제 보완.

/proc/self/status 가 없는 곳(윈도우 개발 PC)에서도 예외 없이 조용히 넘어가야
스케줄러 전체가 죽지 않는다. 있으면 RSS(MiB)를 로그로 남긴다.
"""
import io

from scheduler.main import _mem_heartbeat_tick


def test_no_proc_file_does_not_raise(monkeypatch):
    """윈도우 등 /proc 가 없는 환경 — FileNotFoundError 를 삼키고 조용히 끝난다."""
    _mem_heartbeat_tick()   # 예외가 안 나야 통과 (이 저장소 CI/개발 PC 는 윈도우)


def test_parses_vmrss_and_logs_mib(monkeypatch, caplog):
    fake_status = "Name:\tpython\nVmRSS:\t  737280 kB\nVmSize:\t 1000000 kB\n"
    real_open = io.open

    def _fake_open(path, *a, **k):
        if path == "/proc/self/status":
            return io.StringIO(fake_status)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", _fake_open)
    with caplog.at_level("INFO"):
        _mem_heartbeat_tick()
    assert any("RSS=720.0MiB" in r.message for r in caplog.records)
