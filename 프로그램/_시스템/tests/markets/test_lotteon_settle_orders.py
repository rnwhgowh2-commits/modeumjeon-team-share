"""롯데온 과거 주문 백필(SettleProduct) — 1일 창 365회를 29일 창 13회로.

지도 fields 로 확인한 필드만 쓴다. 없는 값(수령자·주소·송장)은 **비운다** —
과거 이력 조회용이지 발송용이 아니고, 지어내면 그게 더 위험하다.
"""
from __future__ import annotations

import datetime as _dt

from lemouton.markets import line_uid as L
from shared.platforms.lotteon import settle_orders as SO

KST = _dt.timezone(_dt.timedelta(hours=9))


def _line(**kw):
    r = {"odNo": "D1", "odSeq": "2", "procSeq": "1", "odTypCd": "10",
         "sitmNo": "S1", "sitmNm": "블랙 / M", "spdNo": "P1", "spdNm": "티셔츠",
         "slQty": "2", "slUprc": "10000.0", "slAmt": "20000.0",
         "pyDttm": "20260701153000", "seStdDt": "20260705"}
    r.update(kw)
    return r


class _Fake:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def request(self, method, path, body=None, **kw):
        self.calls.append((body.get("startDate"), body.get("endDate")))
        i = len(self.calls) - 1
        return {"data": self.pages[i] if i < len(self.pages) else []}


# ── 행 변환 ───────────────────────────────────────────────────
def test_필드가_우리_열로_옮겨진다():
    r = SO.to_row(_line())
    assert r["오픈마켓주문번호"] == "D1"
    assert r["상품명"] == "티셔츠" and r["옵션"] == "블랙 / M"
    assert r["수량"] == 2 and r["단가"] == 10000
    assert r["주문일"] == "2026-07-01 15:30:00"
    assert r["주문상태"] == "주문" and r["주문상태원본"] == "10"


def test_line_uid_를_만들_수_있다():
    """이게 안 되면 적재에서 통째로 버려진다."""
    r = SO.to_row(_line())
    assert L.line_uid("lotteon", r) == "lotteon|D1|2|S1"


def test_없는_값은_비운다():
    """수령자·주소·송장은 이 API 에 없다 — 지어내면 발송 사고가 난다."""
    r = SO.to_row(_line())
    for k in ("수령자", "수령자전화번호", "주소", "송장입력", "구매자"):
        assert r[k] == "", k


def test_숫자가_없으면_0이_아니라_공란():
    """0 으로 채우면 '단가 0원'이 되어 마진이 틀어진다."""
    r = SO.to_row(_line(slQty=None, slUprc=None))
    assert r["수량"] == "" and r["단가"] == ""


def test_취소_반품_교환은_클레임_이벤트로_표시된다():
    """주문 라인을 덮어쓰면 원래 주문이 사라진다."""
    for code, label in (("20", "취소완료"), ("30", "교환완료"), ("40", "반품완료")):
        r = SO.to_row(_line(odTypCd=code))
        assert r["_kind"] == "change" and r["주문상태"] == label


def test_일반주문은_클레임이_아니다():
    assert "_kind" not in SO.to_row(_line(odTypCd="10"))


def test_모르는_주문유형은_상태를_비운다():
    """추측해서 '주문'으로 칠하면 취소건이 매출로 잡힌다."""
    r = SO.to_row(_line(odTypCd="99"))
    assert r["주문상태"] == "" and r["주문상태원본"] == "99"


def test_결제일시가_없으면_정산기준일로():
    r = SO.to_row(_line(pyDttm=""))
    assert r["주문일"] == "2026-07-05"


# ── 순회 ──────────────────────────────────────────────────────
def test_29일_창으로_나눠_돈다():
    c = _Fake([[]])
    list(SO.iter_rows(_dt.datetime(2026, 1, 1, tzinfo=KST),
                      _dt.datetime(2026, 7, 1, tzinfo=KST), client=c))
    assert len(c.calls) >= 6                      # 181일 / 29 ≈ 7창
    assert all(len(s) == 8 and len(e) == 8 for s, e in c.calls)   # yyyymmdd


def test_같은_라인이_두_창에_걸쳐도_한_번만():
    c = _Fake([[_line()], [_line()]])
    rows = list(SO.iter_rows(_dt.datetime(2026, 5, 1, tzinfo=KST),
                             _dt.datetime(2026, 7, 1, tzinfo=KST), client=c))
    assert len(rows) == 1


def test_클레임_처리순번이_다르면_다른_라인():
    """procSeq 는 클레임마다 +1 — 주문과 그 반품이 한 줄로 접히면 안 된다."""
    c = _Fake([[_line(procSeq="1"), _line(procSeq="2", odTypCd="40")]])
    rows = list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                             _dt.datetime(2026, 6, 20, tzinfo=KST), client=c))
    assert len(rows) == 2


def test_주문번호가_없는_행은_버린다():
    c = _Fake([[_line(odNo="")]])
    assert list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                             _dt.datetime(2026, 6, 20, tzinfo=KST), client=c)) == []


# ── 백필 배선 ─────────────────────────────────────────────────
def test_백필은_롯데온만_29일_창을_쓴다():
    from lemouton.markets import order_ingest as OI
    assert OI.backfill_chunk_days("lotteon") == 29        # 365회 → 13회
    assert OI.chunk_days("lotteon") == 1                  # 증분은 그대로 1일(209)
    assert OI.backfill_chunk_days("smartstore") == 1      # 24시간 하드 제약


# ── 페이징 (다른 세션 제보: 롯데온 목록 API 는 pageNo·rowsPerPage 를 요구한다) ──
class _Paged:
    """페이징을 지원하는 마켓. dataCount 로 전체를 알려준다."""
    def __init__(self, total):
        self.total, self.calls = total, []

    def request(self, method, path, body=None, **kw):
        self.calls.append(dict(body))
        p = body.get("pageNo")
        if p is None:
            return {"returnCode": "9000", "returnMessage": "처리 중 오류"}
        size = body.get("rowsPerPage") or 100
        s0 = (p - 1) * size
        rows = [_line(odNo=f"D{i}") for i in range(s0, min(s0 + size, self.total))]
        return {"returnCode": "0000", "dataCount": self.total, "data": rows}


def test_100건이_넘으면_다음_페이지까지_가져온다():
    """🔴 페이징을 안 하면 첫 100건만 오고 나머지가 **에러 없이** 사라진다."""
    c = _Paged(250)
    rows = list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                             _dt.datetime(2026, 6, 20, tzinfo=KST), client=c))
    assert len(rows) == 250, f"{len(rows)}건만 가져왔다 — 조용한 유실"
    assert [c.calls[i]["pageNo"] for i in range(3)] == [1, 2, 3]


def test_페이징_파라미터를_먼저_보낸다():
    c = _Paged(10)
    list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                      _dt.datetime(2026, 6, 20, tzinfo=KST), client=c))
    assert c.calls[0]["pageNo"] == 1 and c.calls[0]["rowsPerPage"] == 100


def test_정확히_100건이면_2페이지를_확인한다():
    """딱 상한에 걸리면 더 있는지 알 수 없다 — 확인 안 하면 유실이 숨는다."""
    c = _Paged(100)
    rows = list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                             _dt.datetime(2026, 6, 20, tzinfo=KST), client=c))
    assert len(rows) == 100
    assert len(c.calls) >= 1


class _NoPaging:
    """페이징 파라미터를 안 받는 마켓 — 넣으면 거부하고, 빼면 정상."""
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None, **kw):
        self.calls.append(dict(body))
        if "pageNo" in body:
            return {"returnCode": "9000", "returnMessage": "잘못된 파라미터"}
        return {"returnCode": "0000", "data": [_line()]}


def test_페이징을_거부하면_원래_방식으로_되돌린다():
    """페이징이 필요한지 문서로 확정할 수 없어 먼저 시도하고 거부되면 폴백한다."""
    c = _NoPaging()
    rows = list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                             _dt.datetime(2026, 6, 20, tzinfo=KST), client=c))
    assert len(rows) == 1
    assert "pageNo" in c.calls[0] and "pageNo" not in c.calls[1]


class _AllFail:
    def request(self, method, path, body=None, **kw):
        return {"returnCode": "9000", "returnMessage": "처리 중 오류"}


def test_두_방식_다_실패하면_사유와_함께_예외():
    """조용히 0건으로 넘어가면 그 구간이 빈 채로 완료된 것처럼 보인다."""
    import pytest
    with pytest.raises(RuntimeError, match="9000"):
        list(SO.iter_rows(_dt.datetime(2026, 6, 1, tzinfo=KST),
                          _dt.datetime(2026, 6, 20, tzinfo=KST), client=_AllFail()))
