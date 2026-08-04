# -*- coding: utf-8 -*-
"""전송 작업 기록 — 실패 부류(우리 말)와 사유(마켓 말)를 섞지 않는다.

사장님 확정 2026-08-02 ③-b:
  "실패사유 … 이 내용은 api 실제 마켓으로부터 전송 실패한 이유를 적어야함"

이 파일이 지키는 것 — **우리가 만든 문장이 「마켓이 한 말」 자리에 들어가지 않는다.**
들어가는 순간 사장님은 그걸 마켓 말로 읽고 엉뚱한 데를 고친다.
"""
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.send import models as M
from lemouton.send import service as S


@pytest.fixture()
def s():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    yield sess
    sess.close()


@dataclass
class FakeResult:
    market: str
    canonical_sku: str = 'SKU1'
    success: bool = False
    http_status: int | None = None
    error: str | None = None


# ── 마켓 말 / 우리 말 가르기 ────────────────────────────────────────────

def test_코드와_메시지를_가른다():
    code, msg, from_market = S.split_market_error('PRODUCT_INVALID: 상품명이 너무 깁니다')
    assert (code, msg, from_market) == ('PRODUCT_INVALID', '상품명이 너무 깁니다', True)


def test_코드를_못_가르면_통째로_메시지다():
    """억지로 쪼개면 없는 코드를 만들어내게 된다."""
    code, msg, from_market = S.split_market_error('상품 등록에 실패했습니다')
    assert code == ''
    assert msg == '상품 등록에 실패했습니다'
    assert from_market is True


def test_우리쪽_예외는_마켓_말이_아니다():
    """`ConnectionError: ...` 는 마켓이 한 말이 아니라 우리가 못 닿은 것이다."""
    for raw in ('ConnectionError: timed out', 'TimeoutError: 30s',
                'ValueError: bad option'):
        code, msg, from_market = S.split_market_error(raw)
        assert from_market is False, raw
        assert code == '' and msg == ''


def test_빈_값은_마켓_말이_아니다():
    for raw in (None, '', '   ', 123):
        assert S.split_market_error(raw) == ('', '', False)


# ── 기록 ───────────────────────────────────────────────────────────────

def test_성공을_적는다(s):
    job = S.start_job(s)
    S.record_upload_result(s, job=job, result=FakeResult('coupang', success=True,
                                                         http_status=200),
                           set_id=1, model_code='M1')
    assert job.ok_count == 1 and job.fail_count == 0
    row = s.query(M.SendJobRow).one()
    assert row.kind == M.KIND_OK
    assert row.market_code is None and row.market_message is None


def test_마켓이_거부하면_원문을_그대로_담는다(s):
    job = S.start_job(s)
    S.record_upload_result(
        s, job=job,
        result=FakeResult('smartstore', http_status=400,
                          error='INVALID_CATEGORY: 리프 카테고리가 아닙니다'),
        set_id=1)
    row = s.query(M.SendJobRow).one()
    assert row.kind == M.KIND_MARKET_REJECTED
    assert row.market_code == 'INVALID_CATEGORY'
    assert row.market_message == '리프 카테고리가 아닙니다'
    assert row.our_note is None                 # 우리 말은 안 섞였다
    assert '리프 카테고리가 아닙니다' in row.reason_text


def test_우리쪽_사정이면_마켓_칸을_비워_둔다(s):
    """마켓이 한 말이 없는데 마켓 칸을 채우면 그게 거짓이다."""
    job = S.start_job(s)
    S.record_upload_result(s, job=job,
                           result=FakeResult('coupang', error='ConnectionError: reset'),
                           set_id=1)
    row = s.query(M.SendJobRow).one()
    assert row.market_code is None and row.market_message is None
    assert row.kind == M.KIND_NETWORK
    assert 'ConnectionError' in row.our_note     # 원문은 우리 칸에 남는다


def test_사유를_안_주면_안_준다고_적는다(s):
    """「거부당했다」고만 하고 사유가 비면 화면이 거짓말처럼 보인다."""
    job = S.start_job(s)
    S.record(s, job=job, market='lotteon', kind=M.KIND_MARKET_REJECTED, set_id=1)
    row = s.query(M.SendJobRow).one()
    assert row.kind == M.KIND_NO_REASON_GIVEN   # 부류가 바뀌어 적힌다
    assert '주지 않았습니다' in row.reason_text


def test_전송_전_게이트는_고치는_법을_말한다(s):
    job = S.start_job(s)
    S.record(s, job=job, market='eleven11', kind=M.KIND_REQUIRED_MISSING, set_id=1,
             our_note='브랜드가 비어 있습니다')
    row = s.query(M.SendJobRow).one()
    assert row.market_code is None               # 마켓을 부르지도 않았다
    assert '정책 생성' in row.reason_text         # 어디 가서 고치는지 말한다


def test_모르는_부류는_막는다(s):
    job = S.start_job(s)
    with pytest.raises(S.SendError):
        S.record(s, job=job, market='coupang', kind='아무거나')


def test_모르는_작업방식은_막는다(s):
    with pytest.raises(S.SendError):
        S.start_job(s, mode='몰라')


# ── 되짚기 ──────────────────────────────────────────────────────────────

def test_요약은_실패를_위로_올린다(s):
    job = S.start_job(s)
    for _ in range(3):
        S.record(s, job=job, market='coupang', kind=M.KIND_OK)
    S.record(s, job=job, market='smartstore', kind=M.KIND_NO_POLICY)
    S.record(s, job=job, market='gmarket', kind=M.KIND_NO_POLICY)
    S.record(s, job=job, market='auction', kind=M.KIND_STOCK_UNKNOWN)
    S.finish_job(s, job=job)
    got = S.job_summary(s, job.id)
    assert got['total'] == 6 and got['ok'] == 3 and got['fail'] == 3
    assert got['by_kind'][0]['failed'] is True           # 실패가 맨 위
    assert got['by_kind'][0]['kind'] == M.KIND_NO_POLICY  # 많은 것부터
    assert got['by_kind'][0]['how_to_fix']                # 고치는 법이 같이 온다


def test_실패목록은_마켓말과_우리말을_따로_준다(s):
    job = S.start_job(s)
    S.record(s, job=job, market='coupang', kind=M.KIND_MARKET_REJECTED, set_id=7,
             market_code='E1001', market_message='재고가 0입니다',
             our_note='우리 쪽 메모')
    got = S.failures(s, job.id)
    assert len(got) == 1
    r = got[0]
    assert r['market_code'] == 'E1001'
    assert r['market_message'] == '재고가 0입니다'
    assert r['our_note'] == '우리 쪽 메모'      # 섞이지 않았다
    assert r['kind_label'] == '마켓이 거부'


def test_성공한_것만_마지막_전송시각에_들어간다(s):
    job = S.start_job(s)
    S.record(s, job=job, market='coupang', kind=M.KIND_OK, set_id=5)
    S.record(s, job=job, market='gmarket', kind=M.KIND_MARKET_REJECTED, set_id=5,
             market_code='X', market_message='안 됨')
    got = S.last_sent_at(s, set_ids=[5])
    assert 'coupang' in got[5]
    assert 'gmarket' not in got[5], '실패한 것이 「보냈다」로 잡혔다'


def test_구성을_지워도_이력은_남는다(s):
    """FK 를 안 건 이유 — 구성을 지웠다고 「왜 실패했었나」가 사라지면 안 된다."""
    job = S.start_job(s)
    S.record(s, job=job, market='coupang', kind=M.KIND_OK, set_id=999999)
    s.commit()
    assert s.query(M.SendJobRow).count() == 1


# ── 응답 봉투와 값이 이름으로 부딪히지 않는가 (실측으로 걸린 버그) ──────────

def test_로그_응답에_ok_라는_값이_없다(s):
    """🔴 성공 건수를 `ok` 라고 부르면 응답 봉투의 `ok`(성공 여부)를 덮는다.

    라이브에서 실제로 걸렸다 — 서버는 200 OK 인데 화면은 「로그를 못 읽었습니다」.
    0건일 때 `ok:0` 이 되어 화면이 실패로 읽었기 때문이다.
    """
    from lemouton.send import runner as R
    job = S.start_job(s)
    s.commit()
    got = R.log_since(s, job.id)
    assert 'ok' not in got, f'봉투의 ok 를 덮는 키가 있다: {sorted(got)}'
    assert got['sent'] == 0 and got['fail'] == 0


def test_로그는_새_줄만_준다(s):
    """통째로 다시 주면 화면이 깜빡이고 스크롤이 튄다."""
    from lemouton.send import runner as R
    job = S.start_job(s)
    for mk in ('coupang', 'smartstore', 'gmarket'):
        S.record(s, job=job, market=mk, kind=M.KIND_OK, set_id=1)
    s.commit()
    first = R.log_since(s, job.id, 0)
    assert len(first['lines']) == 3
    assert R.log_since(s, job.id, first['last_id'])['lines'] == []


def test_로그_줄은_마켓말과_우리말을_따로_준다(s):
    from lemouton.send import runner as R
    job = S.start_job(s)
    S.record(s, job=job, market='coupang', kind=M.KIND_MARKET_REJECTED, set_id=1,
             market_code='E1', market_message='재고가 0입니다', our_note='우리 메모')
    s.commit()
    line = R.log_since(s, job.id)['lines'][0]
    assert line['market_code'] == 'E1'
    assert line['market_message'] == '재고가 0입니다'
    assert line['our_note'] == '우리 메모'
    assert line['tone'] == 'fail'


def test_두_벌이_동시에_돌지_않는다(s):
    """같은 상품을 두 벌이 보내면 마켓이 같은 값을 두 번 받거나 서로 덮어쓴다."""
    from lemouton.send import runner as R
    R._running.add(999)
    try:
        with pytest.raises(S.SendError):
            R.start(s, set_ids=[1], markets=['coupang'])
    finally:
        R._running.discard(999)


def test_보낼_것이_없으면_시작도_안_한다(s):
    from lemouton.send import runner as R
    with pytest.raises(S.SendError):
        R.start(s, set_ids=[], markets=['coupang'])
    with pytest.raises(S.SendError):
        R.start(s, set_ids=[1], markets=[])


def test_서버가_재시작돼_죽은_작업은_로그가_닫아준다(s):
    """🔴 배포로 스레드가 죽으면 DB 는 'running' 인데 스레드는 없다 — 그대로 두면
    화면이 영원히 폴링한다(라이브 실측으로 예견). 로그 조회가 'stopped' 로 바로잡는다.

    판정 근거는 **하트비트 신선도**다 — 마지막 박동이 한참 전이면 죽은 것."""
    import datetime as _dt
    from lemouton.send import runner as R
    job = S.start_job(s)                 # status='running', 스레드는 안 띄움 = 고아
    job.started_at = R._now() - _dt.timedelta(seconds=R._STALE_SEC + 5)
    job.heartbeat_at = job.started_at    # 박동이 끊긴 지 오래
    s.commit()
    got = R.log_since(s, job.id)
    assert got['status'] == 'stopped'
    assert got['running'] is False


def test_다른_워커에서_돌고_있는_작업을_고아로_오판해_닫지_않는다(s):
    """🔴🔴 라이브 사고(job 2) 재발 방지 — 서버는 워커 2개라 폴링이 다른 워커에
    떨어지면 `_running` 에 그 작업이 **없는 게 정상**이다. 그 근거로 닫았다가
    100초짜리 조립 중이던 살아있는 작업을 죽였다. 하트비트가 신선하면 살아있는
    것으로 보고 절대 닫지 않는다."""
    from lemouton.send import runner as R
    job = S.start_job(s)                 # 이 프로세스의 _running 에는 없다 = 다른 워커 상황
    job.heartbeat_at = R._now()          # 방금 박동
    job.stage = '구성 8 사본 조립 중'
    s.commit()
    got = R.log_since(s, job.id)
    assert got['status'] == 'running', '살아있는 작업을 닫아버렸다(라이브 사고 재현)'
    assert got['running'] is True        # 화면이 계속 폴링하게
    assert '조립' in got['stage']         # 뭘 하는 중인지도 알려준다


def test_다른_워커에서_돌고_있으면_새_전송을_막는다(s):
    """이중실행 가드도 메모리가 아니라 DB 하트비트로 — 워커가 다르면 메모리엔 안 보인다."""
    from lemouton.send import runner as R
    job = S.start_job(s)
    job.heartbeat_at = R._now()
    s.commit()
    with pytest.raises(S.SendError):
        R.start(s, set_ids=[1], markets=['coupang'])


def test_끝난_작업의_stage_는_화면에_안_나간다(s):
    from lemouton.send import runner as R
    job = S.start_job(s)
    job.stage = '구성 1 조립 중'
    S.finish_job(s, job=job)
    s.commit()
    assert R.log_since(s, job.id)['stage'] == ''


def test_조립이_터져도_스레드가_죽지_않고_사유를_남긴다(s, monkeypatch):
    """🔴 라이브 실측 — 조립 예외로 세션이 「실패한 트랜잭션」이 된 채 기록을 시도하면
    기록도 터져 스레드가 통째로 죽었다(job 1 · 기록 0줄 고아). 롤백 후 적어야 한다."""
    from lemouton.send import runner as R
    from lemouton.policy import to_payload as TP
    job = S.start_job(s); s.commit()

    def 터지는_조립(session, *, set_id):
        raise RuntimeError('조립 실패 흉내')
    monkeypatch.setattr(TP, 'set_view', 터지는_조립)
    # 스레드 없이 본체를 직접 부른다 — 같은 세션 흐름
    monkeypatch.setattr('shared.db.SessionLocal', lambda: s)
    monkeypatch.setattr(s, 'close', lambda: None)     # run_job 의 close 무시
    R.run_job(job.id, set_ids=[1], markets=['coupang'])

    rows = s.query(M.SendJobRow).filter_by(job_id=job.id).all()
    assert rows, '한 줄도 못 적고 죽었다(라이브 재현)'
    assert '조립 실패 흉내' in (rows[0].our_note or '')
    done = s.get(M.SendJob, job.id)
    assert done.status == 'done'                       # 작업이 닫혔다
    assert done.heartbeat_at is not None               # 시작하자마자 첫 박동을 찍었다
