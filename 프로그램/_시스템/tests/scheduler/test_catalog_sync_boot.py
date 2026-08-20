# -*- coding: utf-8 -*-
"""마켓 상품 야간 훑기 — **프로덕션에서 실제로 도는 자리에** 있어야 한다.

라이브 실측 2026-08-04: 마켓 상품 캐시가 3,291건에서 멈춰 있었다.
롯데온 한 마켓만 실제 136,510건인데도(실측 run 30858107889).

원인은 「안 켰다」가 아니라 **켜도 안 도는 자리에 있었다** —
`start_scheduler()` 는 `__main__`(개발 실행)에서만 불린다. 프로덕션은 gunicorn 이라
그 블록이 아예 안 돈다. 주문 수집이 2026-07-20 에 겪은 것과 같은 자리다.

그래서 이 파일은 두 가지를 지킨다.
  ① 등록 함수가 따로 있고 시각을 켜면 실제로 등록되나
  ② **create_app() 이 그 함수를 부르나** — 이걸 안 지키면 조용히 다시 안 돈다
"""
import re
from pathlib import Path

import pytest


class FakeSched:
    running = True

    def __init__(self):
        self.jobs = {}

    def get_job(self, jid):
        return self.jobs.get(jid)

    def add_job(self, *a, **k):
        self.jobs[k.get('id')] = k
        return k

    def start(self):
        pass


@pytest.fixture
def sched(monkeypatch):
    import scheduler.main as SM
    s = FakeSched()
    monkeypatch.setattr(SM, 'get_scheduler', lambda: s)
    return s


def test_시각을_켜면_등록된다(sched, monkeypatch):
    import scheduler.main as SM
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '3')
    SM.start_catalog_sync_scheduler()
    job = sched.jobs.get('catalog_sync')
    assert job is not None, '시각을 켰는데 등록이 안 됐다'
    assert job['hour'] == 3
    assert job['max_instances'] == 1, '겹쳐 돌면 2,700 호출이 두 배로 나간다'


def test_안_켜면_안_돈다(sched, monkeypatch):
    """기본 꺼짐 — 마켓 호출 한도가 있어 사장님이 켤 때만 돈다."""
    import scheduler.main as SM
    monkeypatch.delenv('MOUM_CATALOG_SYNC_HOUR', raising=False)
    SM.start_catalog_sync_scheduler()
    assert 'catalog_sync' not in sched.jobs


def test_0시도_꺼짐이_아니다(sched, monkeypatch):
    """0 을 '꺼짐'으로 읽으면 자정 훑기가 조용히 안 돈다."""
    import scheduler.main as SM
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '0')
    SM.start_catalog_sync_scheduler()
    assert sched.jobs.get('catalog_sync', {}).get('hour') == 0


def test_두_번_불러도_한_번만_등록된다(sched, monkeypatch):
    import scheduler.main as SM
    monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', '3')
    SM.start_catalog_sync_scheduler()
    SM.start_catalog_sync_scheduler()
    assert len(sched.jobs) == 1


def test_이상한_값은_안_켠다(sched, monkeypatch):
    import scheduler.main as SM
    for bad in ('24', '-1', 'abc'):
        sched.jobs.clear()
        monkeypatch.setenv('MOUM_CATALOG_SYNC_HOUR', bad)
        SM.start_catalog_sync_scheduler()
        assert 'catalog_sync' not in sched.jobs, f'{bad!r} 로 켜지면 안 된다'


# ── ★ 여기가 핵심 ─────────────────────────────────────────────────────────
def test_create_app_이_훑기_스케줄러를_부른다():
    """🔴 이 검사가 이 파일의 존재 이유다.

    함수를 아무리 잘 만들어도 **create_app 이 안 부르면 프로덕션에서 안 돈다.**
    실제로 그래서 캐시가 3,291건에 멈춰 있었다. 배선을 글자로 고정한다.
    """
    src = (Path(__file__).resolve().parents[2] / 'app.py').read_text(encoding='utf-8')
    assert 'start_catalog_sync_scheduler' in src, (
        'app.py 가 start_catalog_sync_scheduler 를 안 부른다 — '
        '켜도 프로덕션(gunicorn)에서 영영 안 돈다')
    # `__main__` 블록이 아니라 create_app() 안에서 불려야 한다.
    head = src.split('if __name__ ==')[0]
    assert 'start_catalog_sync_scheduler' in head, (
        '__main__ 블록에서만 부르면 개발 실행에서만 돈다 — create_app() 안으로')


def test_배포가_시각을_넘겨준다():
    """설정이 컨테이너까지 닿는지 — 워크플로에 플래그가 있고 실행줄에 실려야 한다."""
    wf = (Path(__file__).resolve().parents[4] / '.github' / 'workflows'
          / 'aws-lightsail-deploy.yml')
    if not wf.exists():          # 저장소 밖에서 돌리는 경우는 건너뛴다
        pytest.skip('배포 워크플로를 찾을 수 없음')
    t = wf.read_text(encoding='utf-8')
    assert re.search(r'MOUM_CATALOG_SYNC_HOUR=\d+', t), '워크플로에 시각이 없다'
    assert '$FLAG_CATSYNC' in t, 'APP_ENVFLAGS 에 안 실리면 컨테이너까지 안 간다'
