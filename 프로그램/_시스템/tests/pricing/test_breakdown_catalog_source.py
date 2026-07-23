# -*- coding: utf-8 -*-
"""fx(계산식) 단건 조회가 **카탈로그 소싱처**(문자 키)에서도 열려야 한다.

사장님 화면 실측(2026-07-23): 현대H몰·롯데아이몰 셀의 fx 를 누르면
「계산식 로드 실패 / not_found」. 다른 소싱처는 정상.

원인: 단건 라우트가 `/breakdown/<sku>/<int:source_id>` 라 정수만 받는다.
카탈로그 소싱처는 id 가 'key:lotteimall' 같은 **문자 키**여서 라우트 자체에
매칭되지 않고 앱의 404 핸들러가 {'error':'not_found'} 를 돌려준 것.
일괄 라우트(/breakdowns)는 2026-07-20 에 _sid_key 로 이미 고쳤는데
단건만 남아 있었다(같은 버그의 짝 — 한쪽만 고친 전형).
"""
from __future__ import annotations


def _rules():
    """라우트 규칙 목록 — 앱 생성 없이 블루프린트만으로 확인(가볍고 결정적)."""
    from webapp.routes import api_benefits
    return {str(r.rule): r for r in api_benefits.bp.deferred_functions and [] or []}


def test_단건_계산식_라우트가_문자_소싱처키를_받는다():
    """`<int:source_id>` 로 고정돼 있으면 카탈로그 소싱처는 영영 404 다."""
    import inspect
    from webapp.routes import api_benefits
    src = inspect.getsource(api_benefits.get_breakdown)
    # 라우트 데코레이터는 함수 소스에 안 잡히므로 모듈 전체에서 확인
    mod = inspect.getsource(api_benefits)
    assert "'/breakdown/<sku>/<int:source_id>'" not in mod, (
        "단건 라우트가 정수 전용이면 카탈로그 소싱처(key:lotteimall 등)가 404 로 죽는다")
    assert "/breakdown/<sku>/<source_id>" in mod


def test_단건_핸들러가_sid_key_로_정규화한다():
    """일괄(/breakdowns)과 같은 규칙으로 통일 — 숫자는 숫자, 문자 키는 원본 유지."""
    import inspect
    from webapp.routes import api_benefits
    src = inspect.getsource(api_benefits.get_breakdown)
    assert "_sid_key" in src


def test_sid_key_규칙():
    from webapp.routes.api_benefits import _sid_key
    assert _sid_key("3") == 3
    assert _sid_key(3) == 3
    assert _sid_key("key:lotteimall") == "key:lotteimall"
    assert _sid_key("key:hmall") == "key:hmall"
