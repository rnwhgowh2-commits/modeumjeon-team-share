"""마켓 동시 호출 규칙 — 데이터코드지도에서 읽는다.

사장님 지시(2026-07-19): "판매처관리 > 데이터코드지도 참고해서 마켓 API 정보 찾아봐."
→ markets[].concurrency 에 마켓 단위 규칙이 적혀 있었다. API 본문만 훑어서는 못 봤다.
"""
from lemouton.uploader.market_concurrency import (
    concurrency_note,
    market_info,
    must_be_sequential,
)


# ── 지도에 적힌 그대로 ──────────────────────────────────────────

def test_쿠팡은_토큰버킷_5rps():
    n = concurrency_note("coupang")
    assert "5 req/s" in n
    assert "429" in n            # Retry-After 존중


def test_스마트스토어는_계정_순차():
    assert "순차" in concurrency_note("smartstore")


def test_11번가는_순차_필수():
    """병렬로 쏘면 전체가 429 로 죽는다 — 지도에 그렇게 적혀 있다."""
    n = concurrency_note("eleven11")
    assert "순차" in n
    assert "429" in n


def test_롯데온은_IP_등록():
    assert "IP" in concurrency_note("lotteon")


def test_옥션_G마켓은_비어_있다():
    """모르는 걸 지어내지 않는다 — 지도에 없으면 없는 것이다."""
    assert concurrency_note("auction") == ""
    assert concurrency_note("gmarket") == ""


def test_모르는_마켓은_빈_문자열():
    assert concurrency_note("없는마켓") == ""
    assert concurrency_note("") == ""


# ── 🔴 병렬 금지 판정 ───────────────────────────────────────────

def test_순차라고_적힌_마켓은_병렬_금지():
    assert must_be_sequential("smartstore") is True
    assert must_be_sequential("eleven11") is True


def test_쿠팡은_병렬_가능():
    """5 req/s 토큰버킷 = 속도 제한이지 동시 금지가 아니다."""
    assert must_be_sequential("coupang") is False


def test_롯데온은_병렬_금지_아님():
    """IP 등록은 동시성과 무관하다 — 섞어 읽으면 안 된다."""
    assert must_be_sequential("lotteon") is False


def test_모르는_마켓은_병렬금지_아님():
    """모르는 걸 '금지'로 두면 멀쩡한 마켓이 느려진다."""
    assert must_be_sequential("없는마켓") is False


# ── 화면용 ──────────────────────────────────────────────────────

def test_화면에_넘길_한벌():
    i = market_info("eleven11")
    assert i["known"] is True
    assert i["must_be_sequential"] is True
    assert "순차" in i["concurrency_note"]


def test_모르는_마켓은_known_False():
    i = market_info("auction")
    assert i["known"] is False
    assert i["concurrency_note"] is None
