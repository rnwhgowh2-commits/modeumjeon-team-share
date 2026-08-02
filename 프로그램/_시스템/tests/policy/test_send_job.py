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
