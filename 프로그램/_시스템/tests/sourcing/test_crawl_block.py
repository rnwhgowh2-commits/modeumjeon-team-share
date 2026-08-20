"""[2026-06-13] 회귀 — 크롤 시작 하드 리셋 + 종료 후 판매차단(crawl_blocked).

옛 가격/재고가 재크롤에 안 덮이면 잘못된 값으로 판매 → 치명적 손실. 그래서:
  · 크롤 시작 시 그 모음전 소싱 가격/재고/혜택 비움(NULL, status='pending')
  · 종료 후 '유효 소싱가(is_crawl_valid) 0개' 옵션을 crawl_blocked=True 로 판매차단
  · 판매가능 = Option.is_active(수동) AND NOT crawl_blocked(크롤)

이 테스트는 판매차단 판정의 핵심 로직을 고정한다.
유효가격만 판매, 리셋후 미커버(NULL)·크롤실패(error)·매칭실패는 모두 차단.

[포팅 2026-06-26] _sources_have_valid_price 가 api_pricing.py 에서 제거됨.
  판정 로직은 is_crawl_valid(lemouton.pricing.unified) + match_failed 검사로 분산.
  테스트에서 동일 의미의 로컬 헬퍼 _sources_have_valid_price 를 재정의해 포팅.
"""
from lemouton.pricing.unified import is_crawl_valid


def _sources_have_valid_price(sources) -> bool:
    """소싱처 목록 중 유효 가격(is_crawl_valid + 매칭성공)을 가진 항목이 하나라도 있으면 True.

    is_crawl_valid: price > 0 AND last_status != 'error'
    match_failed=True: 소싱처가 안 파는 색/사이즈 조합 → 폴백가 금지(차단)
    """
    if not sources:
        return False
    return any(
        is_crawl_valid(s.get('crawled_price'), s.get('last_status'))
        and not s.get('match_failed', False)
        for s in sources
    )


def test_valid_ok_price_is_sellable():
    assert _sources_have_valid_price([
        {'crawled_price': 122900, 'last_status': 'ok', 'match_failed': False}]) is True


def test_reset_uncovered_null_is_blocked():
    # 리셋 후 크롤이 안 덮음 → price=None/status=pending → 무효(판매차단)
    assert _sources_have_valid_price([
        {'crawled_price': None, 'last_status': 'pending', 'match_failed': False}]) is False


def test_crawl_error_is_blocked_even_with_stale_price():
    # 크롤 실패인데 옛 가격 잔존 → 절대 판매에 쓰지 않음(차단)
    assert _sources_have_valid_price([
        {'crawled_price': 110300, 'last_status': 'error', 'match_failed': False}]) is False


def test_match_failed_is_blocked():
    # 소싱처가 안 파는 색/사이즈(매칭 실패) → 가격 있어도 차단(폴백가 금지)
    assert _sources_have_valid_price([
        {'crawled_price': 99000, 'last_status': 'ok', 'match_failed': True}]) is False


def test_any_one_valid_source_makes_sellable():
    # 여러 소싱처 중 하나라도 유효하면 판매 가능
    assert _sources_have_valid_price([
        {'crawled_price': None, 'last_status': 'error', 'match_failed': False},
        {'crawled_price': 50000, 'last_status': 'ok', 'match_failed': False},
    ]) is True


def test_no_sources_is_blocked():
    assert _sources_have_valid_price([]) is False
    assert _sources_have_valid_price(None) is False
