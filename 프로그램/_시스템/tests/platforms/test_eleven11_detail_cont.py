# -*- coding: utf-8 -*-
"""11번가 상세수정 — **성공 메시지를 실패로 읽던 것**(2026-08-12 라이브).

라이브 응답:
    RuntimeError: 11번가 상세수정 실패: 상품 상세 내용이 수정되었습니다.
「…수정되었습니다」는 **성공**이다. 내가 「message 가 있으면 실패」로 짰다.

왜 그렇게 짰나 — 문서의 성공 예제가 빈 `<Product/>` 였다. 그런데 같은 문서
아래 「출력 결과 필드」표에는 `message`(결과내용)가 **필수(O)** 로 적혀 있다.
예제만 보고 필드표를 안 본 것이다.

🔴 교훈 두 가지
   ① 문서의 「성공 응답 예제」가 실제와 다를 수 있다. 예제와 필드표가 어긋나면
      **필드표가 더 정확하다**(예제는 자주 낡는다).
   ② 성공/실패를 **낱말로 판정하지 않는다.** 마켓이 문구를 바꾸면 조용히 깨진다.
      이 API 는 응답으로 성공을 가릴 수 없으므로 **되읽기가 유일한 검증 수단**이다
      — 그러면 여기서 판정을 흉내내지 말고, 메시지를 그대로 넘기고 러너가 되읽어 본다.
"""
from __future__ import annotations

import pytest

from shared.platforms.eleven11.detail_cont import get_detail_html, update_detail_html

_OK = ('<?xml version="1.0" encoding="euc-kr" standalone="yes"?>'
       "<Product><message>상품 상세 내용이 수정되었습니다.</message></Product>")
_AUTH_ERR = ('<?xml version="1.0" encoding="euc-kr" standalone="yes"?>'
             "<Products><message>OpenAPI Key 에 해당하는 유저가 없습니다.</message></Products>")
_READ = ('<?xml version="1.0" encoding="euc-kr" standalone="yes"?>'
         "<ProductDetailCont><prdDescContClob>&lt;p&gt;내용&lt;/p&gt;</prdDescContClob>"
         "</ProductDetailCont>")


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def request(self, *a, **kw):
        method = kw.get("method") or (a[0] if a else "GET")
        path = kw.get("path") or (a[1] if len(a) > 1 else "")
        self.calls.append((method, path, kw.get("body")))
        return self.resp


def test_수정_성공_메시지를_실패로_보지_않는다():
    """「상품 상세 내용이 수정되었습니다」는 성공이다."""
    update_detail_html("P1", "<p>새 내용</p>", client=FakeClient(_OK))


def test_인증_실패는_예외로_올린다():
    """에러 봉투는 `Products`(복수) 다 — 성공 봉투 `Product` 와 이름이 다르다."""
    with pytest.raises(RuntimeError, match="OpenAPI Key"):
        update_detail_html("P1", "<p>x</p>", client=FakeClient(_AUTH_ERR))


def test_보낸_내용은_CDATA_로_감싼다():
    """상세엔 태그가 들어간다 — 그대로 넣으면 XML 이 깨진다."""
    cli = FakeClient(_OK)

    update_detail_html("P1", "<p>내용 & 특수문자</p>", client=cli)

    body = cli.calls[-1][2]
    assert "<![CDATA[" in body and "]]>" in body
    assert "prdDescContClob" in body


def test_조회는_상세_문자열을_그대로_준다():
    assert get_detail_html("P1", client=FakeClient(_READ)) == "<p>내용</p>"


def test_상품번호가_없으면_거부한다():
    with pytest.raises(ValueError):
        get_detail_html("", client=FakeClient(_READ))
    with pytest.raises(ValueError):
        update_detail_html("P1", None, client=FakeClient(_OK))
