# -*- coding: utf-8 -*-
"""읽을 노션 문서 갈아타기 — 주소 뽑기·기준선 비우기·화면 배선.

**왜 이 테스트가 있나**
    문서를 갈아탈 때 번호만 바꾸면, 어제 기준선이 **남의 문서 것**이라 다음 회차가
    「어제 것 전부 삭제 + 오늘 것 전부 신규」로 잡혀 수백 건짜리 거짓 보고가 나간다.
    그래서 「바꾸기 = 기준선도 비우기」가 한 몸이어야 한다.
"""
import json

import pytest

from lemouton.reports import notion_todo as nt


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    """스냅샷·마지막보고·문서선택을 전부 임시 폴더로."""
    monkeypatch.setattr(nt, "_SNAPSHOT_PATH", str(tmp_path / "snap.json"))
    yield


# ──────────────────────────────────────────────────────────────
# 주소에서 문서 번호 뽑기
# ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    # 사장님이 실제로 붙여넣는 모양 — 제목이 앞에 붙고 하이픈이 없다
    ("https://www.notion.so/316cf4827373806e882bf86e9df1cbf2",
     "316cf482-7373-806e-882b-f86e9df1cbf2"),
    ("https://www.notion.so/투두리스트-영빈-316cf4827373806e882bf86e9df1cbf2?pvs=4",
     "316cf482-7373-806e-882b-f86e9df1cbf2"),
    # 하이픈이 있는 정식 모양
    ("https://www.notion.so/ws/316cf482-7373-806e-882b-f86e9df1cbf2",
     "316cf482-7373-806e-882b-f86e9df1cbf2"),
    # 번호만 던져도 받아준다
    ("316cf4827373806e882bf86e9df1cbf2", "316cf482-7373-806e-882b-f86e9df1cbf2"),
])
def test_주소에서_문서번호를_뽑는다(raw, want):
    assert nt.extract_page_id(raw) == want


def test_보기번호는_문서번호로_잡지_않는다():
    """`?v=...` 뒤 32자리는 **보기(view) 번호**다.

    그걸 문서 번호로 잡으면 있지도 않은 문서를 읽어 그날 보고가 통째로 실패한다.
    """
    url = ("https://www.notion.so/316cf4827373806e882bf86e9df1cbf2"
           "?v=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    assert nt.extract_page_id(url) == "316cf482-7373-806e-882b-f86e9df1cbf2"


def test_문서번호가_없으면_거절한다():
    assert nt.extract_page_id("https://www.notion.so/그냥제목") is None
    assert nt.extract_page_id("") is None


# ──────────────────────────────────────────────────────────────
# 갈아타기 = 기준선 비우기
# ──────────────────────────────────────────────────────────────
def test_문서를_바꾸면_어제_기준선을_비운다(monkeypatch):
    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)
    nt.save_snapshot([{"id": "a", "text": "옛 문서 항목", "checked": False}])
    nt._save_last_report({"ok": True, "photo_message": "옛 보고"})
    assert nt.load_snapshot()["todos"]          # 기준선이 있는 상태

    res = nt.set_page("https://www.notion.so/aaaaaaaabbbbccccddddeeeeeeeeeeee",
                      title="새 문서")
    assert res["ok"] is True
    assert nt.page_id() == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert nt.page_title() == "새 문서"
    # 🔴 여기가 핵심 — 남의 문서 기준선이 남아 있으면 「전부 신규」로 터진다
    assert nt.load_snapshot()["todos"] == []
    assert nt.load_last_report() is None


def test_기준선이_비면_첫회차는_발송하지_않는다(monkeypatch):
    """비운 직후 회차는 발송 없이 기준선만 저장해야 한다."""
    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)
    nt.set_page("aaaaaaaabbbbccccddddeeeeeeeeeeee")
    monkeypatch.setattr(nt, "fetch_todos",
                        lambda **k: [{"id": "n1", "text": "새 문서 할 일",
                                      "checked": False, "weekday": "일요일",
                                      "weekday_seq": 0, "order": 0}])
    sent = []
    import shared.notifier as sn
    monkeypatch.setattr(sn, "send_kakao_memo_detailed",
                        lambda *a, **k: sent.append(a) or {"ok": True})

    res = nt.run_slot_report("09:30")
    assert res.get("skipped") == "baseline_saved"
    assert sent == []


def test_잘못된_주소는_바꾸지_않는다(monkeypatch):
    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)
    before = nt.page_id()
    res = nt.set_page("https://www.notion.so/제목만있음")
    assert res["ok"] is False
    assert "번호" in res["error"]
    assert nt.page_id() == before          # 건드리지 않았다


def test_환경변수가_있으면_그게_이긴다(monkeypatch):
    """운영자가 서버에 박아둔 값이 화면 선택보다 우선."""
    nt.set_page("aaaaaaaabbbbccccddddeeeeeeeeeeee", title="화면에서 고른 것")
    monkeypatch.setenv("NOTION_TODO_PAGE_ID", "11111111-2222-3333-4444-555555555555")
    assert nt.page_id() == "11111111-2222-3333-4444-555555555555"


def test_고른_문서가_없으면_기본_문서(monkeypatch):
    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)
    assert nt.page_id() == nt._DEFAULT_PAGE_ID
    assert nt.is_default_page() is True


# ──────────────────────────────────────────────────────────────
# 문서 목록 — 노션이 열어준 것만
# ──────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self):
        return self._p


def test_목록은_제목칸_이름이_달라도_제목을_찾는다(monkeypatch):
    """제목 칸 이름은 문서마다 다르다(`title`·`이름`·`Name`).

    이름으로 찾으면 한글 워크스페이스에서 제목이 통째로 비어 보인다 — type 으로 찾는다.
    """
    monkeypatch.setattr(nt, "_token", lambda: "ntn_x")
    payload = {"results": [
        {"id": "316cf482-7373-806e-882b-f86e9df1cbf2", "url": "https://n/1",
         "properties": {"이름": {"type": "title",
                                 "title": [{"plain_text": "투두리스트 (영빈)"}]}}},
        {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "url": "https://n/2",
         "properties": {"Name": {"type": "rich_text", "rich_text": []}}},
    ]}
    monkeypatch.setattr(nt.requests, "post", lambda *a, **k: _Resp(payload))
    monkeypatch.delenv("NOTION_TODO_PAGE_ID", raising=False)

    out = nt.list_pages()
    assert out["ok"] is True
    assert out["pages"][0]["title"] == "투두리스트 (영빈)"
    assert out["pages"][0]["is_current"] is True      # 지금 읽는 문서 표시
    assert out["pages"][1]["title"] == "(제목 없음)"


def test_시크릿이_없으면_목록을_안_부른다(monkeypatch):
    monkeypatch.setattr(nt, "_token", lambda: "")
    called = []
    monkeypatch.setattr(nt.requests, "post", lambda *a, **k: called.append(1))
    out = nt.list_pages()
    assert out["ok"] is False and called == []


def test_노션이_거절하면_사유를_돌려준다(monkeypatch):
    monkeypatch.setattr(nt, "_token", lambda: "ntn_x")
    monkeypatch.setattr(nt.requests, "post",
                        lambda *a, **k: _Resp({"message": "unauthorized"}, 401))
    out = nt.list_pages()
    assert out["ok"] is False and "401" in out["error"]
