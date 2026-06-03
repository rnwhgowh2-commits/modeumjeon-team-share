"""전역 진행 상태 추적 (v27 시안 ③ — 우상단 floating widget 용).

인메모리 dict 기반. 멀티 워커 환경에서는 부정확하지만 — 본 앱은 단일 워커 dev/prod 패턴.
멀티 워커 필요 시 Redis 로 교체.

API 사용:
    from webapp.progress_state import progress_set, progress_tick, progress_finish

    progress_set('crawl', total=144, label='모음전 5사이트 재크롤')
    progress_tick('crawl', current='그레이-235 @ 무신사', done=72)
    progress_finish('crawl')

GET /api/progress 응답 형식:
    {
        ok: true,
        tasks: {
            crawl: {kind, total, done, current, label, started_at, ...} | null,
            upload: ... | null,
        }
    }
"""
from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.RLock()
_STATE: dict[str, dict[str, Any] | None] = {
    'crawl': None,    # 수동 per-bundle 크롤 (소싱처별 breakdown) — 위젯 메인 패널
    'upload': None,
    'auto': None,     # [2026-06-03] 백그라운드 스케줄러 자동 cycle — 'crawl' 과 분리(깜빡임 방지)
}


def progress_set(kind: str, *, total: int, label: str = '', current: str = '',
                 breakdown: list[dict[str, Any]] | None = None) -> None:
    """작업 시작 — 진행 상태 초기화.

    breakdown: 소싱처별 진행 [{key, label, total, done, status}, ...] (선택).
    """
    with _lock:
        _STATE[kind] = {
            'kind': kind,
            'total': max(int(total), 0),
            'done': 0,
            'current': current or '',
            'label': label or '',
            'breakdown': list(breakdown) if breakdown else [],
            'started_at': time.time(),
            'updated_at': time.time(),
            'finished_at': None,
        }


def progress_tick(kind: str, *, done: int | None = None,
                  current: str = '', delta: int = 0,
                  total: int | None = None,
                  breakdown: list[dict[str, Any]] | None = None) -> None:
    """진행 갱신. ``done`` 절댓값 또는 ``delta`` 증분 중 하나.

    total/breakdown 도 함께 갱신 가능 (소싱처별 진행 표시용).
    """
    with _lock:
        st = _STATE.get(kind)
        if not st:
            return
        if done is not None:
            st['done'] = max(int(done), 0)
        elif delta:
            st['done'] = max(st['done'] + int(delta), 0)
        if total is not None:
            st['total'] = max(int(total), 0)
        if current:
            st['current'] = current
        if breakdown is not None:
            st['breakdown'] = list(breakdown)
        st['updated_at'] = time.time()


def progress_finish(kind: str) -> None:
    """작업 종료 — 잠깐 (~3초) 후 None 으로 사라지게 finished_at 기록."""
    with _lock:
        st = _STATE.get(kind)
        if st:
            st['finished_at'] = time.time()
            st['done'] = st.get('total', 0)
            # 소싱처별 진행도 모두 완료 처리 (마지막 tick 누락 대비)
            for row in st.get('breakdown') or []:
                row['done'] = row.get('total', row.get('done', 0))
                row['status'] = 'done'
            st['updated_at'] = time.time()


def progress_clear(kind: str | None = None) -> None:
    """강제 클리어 (테스트/관리)."""
    with _lock:
        if kind is None:
            for k in _STATE:
                _STATE[k] = None
        else:
            _STATE[kind] = None


def progress_get() -> dict[str, Any]:
    """현재 진행 상태 dict (얕은 copy)."""
    now = time.time()
    with _lock:
        out: dict[str, Any] = {}
        for k, v in _STATE.items():
            if v is None:
                out[k] = None
                continue
            # 종료 후 4초 경과 = 클리어 (widget 자연 fade-out)
            if v.get('finished_at') and (now - v['finished_at']) > 4.0:
                _STATE[k] = None
                out[k] = None
                continue
            out[k] = dict(v)
        return {'ok': True, 'tasks': out, 'now': now}
