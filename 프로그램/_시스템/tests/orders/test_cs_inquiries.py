

# ── 옥션·G마켓(ESM) 문의 배선 (2026-07-21) ─────────────────────────────────

def test_esm_판매자문의_정규화_실측필드():
    """실제 응답은 소문자 camelCase(라이브 실측 2026-07-22) — 문서의 PascalCase 아님."""
    from lemouton.cs_inquiries.service import _normalize_esm_qna
    r = _normalize_esm_qna("G마켓", {
        "messageNo": "504346613", "informStatus": "미처리", "contractType": "상품",
        "title": "상품 문의입니다.", "details": "사이즈 크게 나왔나요?",
        "receiveDate": "2026-07-20T22:28:00+09:00", "inquirerName": "박정희",
        "siteGoodsNo": "4761998630", "token": "tk"})
    assert r["문의ID"] == "504346613" and r["상태"] == "미답변"
    assert r["고객"] == "박정희" and "사이즈 크게 나왔나요?" in r["문의내용"]
    assert "[상품]" in r["문의내용"] and r["상품"] == "4761998630"


def test_esm_판매자문의_문서표기도_폴백으로_받는다():
    from lemouton.cs_inquiries.service import _normalize_esm_qna
    r = _normalize_esm_qna("옥션", {
        "MessageNo": "M1", "InformStatus": "처리완료", "ReceiveDate": "2026-07-21"})
    assert r["문의ID"] == "M1" and r["상태"] == "답변완료"


def test_esm_긴급알리미_정규화_처리완료():
    from lemouton.cs_inquiries.service import _normalize_esm_alimi
    r = _normalize_esm_alimi("G마켓", {
        "EmerMessageNo": "E9", "InformStatus": "처리완료", "ContactType": "K3",
        "OrderNo": "4470838482", "ReceiveDate": "2026-07-20", "AnswerDate": "2026-07-21"})
    assert r["상태"] == "답변완료" and r["문의ID"] == "E9"
    assert "4470838482" in r["문의내용"]


def test_esm_문의조회는_옥션_비밀글까지_G마켓은_전체만(monkeypatch):
    """qnaType — 옥션 1(일반)+2(비밀글), G마켓 3(전체)만. 문서 명시."""
    import datetime as dt
    from shared.platforms.esm import inquiries as inq

    class _C:
        def __init__(self): self.bodies = []
        def post(self, path, body, **kw):
            if path == inq.QNA_PATH: self.bodies.append(dict(body))
            return {"resultCode": 0, "Data": []}
    c1 = _C(); list(inq.iter_seller_qna("auction", dt.datetime(2026,7,15), dt.datetime(2026,7,20), client=c1))
    assert {b["qnaType"] for b in c1.bodies} == {1, 2}
    c2 = _C(); list(inq.iter_seller_qna("gmarket", dt.datetime(2026,7,15), dt.datetime(2026,7,20), client=c2))
    assert {b["qnaType"] for b in c2.bodies} == {3}
    # endDate 는 그날 끝 포함을 위해 하루 올림(클레임과 동일 실측 규약)
    assert all(b["endDate"] > b["startDate"] for b in c1.bodies)


def test_esm_조회대상없음_400은_빈결과다():
    """마켓이 '조회 대상 없음'을 HTTP 400 으로 준다(라이브 실측) — 오류 아님."""
    import datetime as dt
    from shared.platforms.esm import inquiries as inq

    class _R:  # requests.HTTPError 흉내
        text = '{"resultCode":1000,"message":"[001000]조회된 기간에 조회 대상이 없습니다","data":null}'

    class _C:
        def post(self, path, body, **kw):
            e = RuntimeError("400 Client Error"); e.response = _R(); raise e

    got = list(inq.iter_seller_qna("gmarket", dt.datetime(2026, 7, 15),
                                   dt.datetime(2026, 7, 20), client=_C()))
    assert got == []


def test_esm_최상위_리스트_응답도_행으로_받는다():
    """성공 응답이 dict 봉투가 아니라 리스트로 오는 경우(라이브 실측)."""
    import datetime as dt
    from shared.platforms.esm import inquiries as inq

    class _C:
        def post(self, path, body, **kw):
            return [{"MessageNo": "M7", "InformStatus": "미처리"}]

    got = list(inq.iter_seller_qna("gmarket", dt.datetime(2026, 7, 15),
                                   dt.datetime(2026, 7, 20), client=_C()))
    assert [r["MessageNo"] for r in got] == ["M7"]
