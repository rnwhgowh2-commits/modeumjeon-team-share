# -*- coding: utf-8 -*-
"""노션 일일보고 점검 화면 — 7단계 배치(시안 C · 사장님 확정 2026-08-02).

옛 화면은 설정 4덩어리가 위에 있고 오늘 나갈 문구가 한참 아래였다. 매일 여는
화면인데 매번 스크롤해야 했고, 「지금 보고가 나갈 상태인가」는 회색 JSON 덩어리라
사람이 읽을 수 없었다.
"""
import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import app as A
    from lemouton.reports import notion_todo as nt

    monkeypatch.setenv("MOUM_NO_AUTOCONFIRM_SCHED", "1")
    monkeypatch.setenv("MOUM_ORDER_INGEST_HOURS", "0")
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    return A.create_app().test_client()


def _text(r):
    return r.get_data(as_text=True)


def test_기본은_오늘_나갈_것이다(client):
    """매일 여는 목적은 「오늘 뭐가 나가나」 — 그게 첫 화면이어야 한다."""
    r = client.get("/reports/notion-todo")
    assert r.status_code == 200
    body = _text(r)
    assert "오늘 보고 내용" in body
    # 왼쪽 단계 목록이 늘 보인다
    for name in ("무엇을 읽나", "언제 보내나", "어디로 보내나", "사진 준비",
                 "오늘 나갈 것", "지금 보내보기", "지나간 기록"):
        assert name in body


@pytest.mark.parametrize("step,must", [
    ("1", "읽을 노션 문서 고르기"),
    ("2", "발송 시각"),
    ("3", "카카오 연결"),
    ("4", "노션 캡처"),
    ("5", "오늘 보고 내용"),
    ("6", "지금 보내보기"),
    ("7", "지나간 기록"),
])
def test_일곱_단계가_모두_열린다(client, step, must):
    r = client.get(f"/reports/notion-todo?step={step}")
    assert r.status_code == 200
    assert must in _text(r)


def test_신호등이_지금_상태를_말한다(client):
    """하나만 꺼져도 그날 보고가 통째로 빠진다 — 색으로 보이게."""
    body = _text(client.get("/reports/notion-todo"))
    for name in ("노션 문서", "카카오", "발송 시각", "사진"):
        assert name in body
    assert "lights" in body


def test_옛_주소는_그대로_살아있다(client):
    """카톡 버튼과 북마크가 옛 주소로 온다 — 죽으면 안 된다."""
    assert "지금 보내보기" in _text(client.get("/reports/notion-todo/test"))
    assert "지나간 기록" in _text(client.get("/reports/notion-todo/history"))


def test_문서_바꾸기_칸이_1단계에_있다(client, monkeypatch):
    from lemouton.reports import notion_todo as nt

    monkeypatch.setattr(nt, "_token", lambda: "ntn_x")
    body = _text(client.get("/reports/notion-todo?step=1"))
    assert "문서 목록 불러오기" in body
    assert "목록에 없어요" in body                  # 주소 붙여넣기(접힘)
    assert "어제 기준선을 비우고" in body           # 왜 안전한지 말해준다
    assert "연결" in body                           # 노션에서 해야 할 한 번의 클릭


def test_시크릿이_없으면_목록_대신_할_일을_말한다(client):
    """버튼을 눌러봐야 실패한다 — 무엇을 먼저 해야 하는지 말해준다."""
    body = _text(client.get("/reports/notion-todo?step=1"))
    assert "노션 시크릿이 아직 없어" in body
    assert "문서 목록 불러오기" not in body


def test_문서를_바꾸면_기준선을_비웠다고_말한다(client, monkeypatch):
    from lemouton.reports import notion_todo as nt

    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)
    monkeypatch.setattr(nt, "start_refresh", lambda: True)
    r = client.post("/reports/notion-todo/page",
                    data={"page": "https://www.notion.so/"
                                  "aaaaaaaabbbbccccddddeeeeeeeeeeee",
                          "title": "새 문서"})
    assert r.status_code == 200
    body = _text(r)
    assert "새 문서" in body
    assert "기준선을 비웠습니다" in body
    assert nt.page_id() == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_잘못된_주소는_화면이_이유를_말한다(client):
    r = client.post("/reports/notion-todo/page", data={"page": "그냥 글자"})
    assert r.status_code == 400
    assert "문서 번호를 찾지 못했습니다" in _text(r)


def test_카톡_두통이_폰_모양으로_보인다(client, monkeypatch):
    """실제 카톡엔 사진·버튼이 붙는데 화면엔 글만 보여 오해가 났던 자리."""
    from lemouton.reports import notion_todo as nt

    monkeypatch.setattr(nt, "load_last_report", lambda: {
        "ok": True, "collected_at": "2026-08-02T18:33:23",
        "photo_message": "영빈 투두 8/2(일)\n오늘(일) 남은 일 35건",
        "change_message": "8/2(일) · 변경 2건\n11:20 ✅ 끝낸 일",
        "picked": {"weekday": "일요일", "count": 37,
                   "first_item": "첫 항목", "total_blocks_for_weekday": 2},
        "changes": {"added": [1, 2], "completed": []},
    })
    body = _text(client.get("/reports/notion-todo"))
    assert "남은 일 35건" in body
    assert "변경 2건" in body
    assert "노션에서 보기" in body          # 말풍선 아래 버튼까지 그린다
    assert "/ 200자" in body
    assert "일요일" in body                 # 요일 판정도 같은 화면에


def test_사이드바_메뉴에_들어갔다():
    """여태 어느 메뉴에도 링크가 없어 주소를 직접 쳐야 했다."""
    import webapp.routes.api_sidebar as SB

    assert 'i_notion_report' in SB._ITEM_DEFS
    etc = {s[0]: s for s in SB._STAGE_SPEC}['s_etc']
    assert 'i_notion_report' in etc[4]
    assert SB._ITEM_DEFS['i_notion_report']['url'] == '/reports/notion-todo'


def test_옛_저장본에도_메뉴를_넣어준다():
    """🔴 스펙만 고치면 라이브엔 안 나온다 — 서버는 저장본을 쓴다."""
    import webapp.routes.api_sidebar as SB

    old = {'version': 1, 'schema': 8, 'standalone': [],
           'stages': [{'id': 's_etc', 'emoji': '⚙️', 'name': '기타',
                       'color': '#6B7280', 'collapsed': False,
                       'items': [{'id': 'i_alerts', 'emoji': '🔔',
                                  'name': '알림 채널 설정', 'url': '/alerts',
                                  'active_key': 'alerts', 'badge_key': None}]}]}
    assert SB._migrate_notion_report(old) is True
    ids = [it['id'] for it in old['stages'][0]['items']]
    assert ids == ['i_alerts', 'i_notion_report']
    # 두 번 돌려도 겹쳐 들어가지 않는다
    assert SB._migrate_notion_report(old) is False
