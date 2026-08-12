# -*- coding: utf-8 -*-
"""개발 체크리스트 데이터 라우트."""
import pytest
from flask import Flask

from webapp.routes import marketplace_guide as mg


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # _admin_only 우회
    app = Flask(__name__)
    app.register_blueprint(mg.bp)
    return app.test_client()


def test_checklist_json_ok(client):
    r = client.get("/marketplace-guide/checklist.json")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data["columns"]) == 25
    assert len(data["rows"]) == 6
    assert len(data["cells"]) == 150


def test_every_cell_has_the_keys_the_screen_reads(client):
    """화면 조각이 읽는 키가 하나라도 빠지면 정보창이 백지가 된다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    need = ("state", "spec", "required", "evidence", "note",
            "wiring", "wiring_note", "api", "conflict", "verified")
    for key, cell in data["cells"].items():
        for k in need:
            assert k in cell, f"{key} 에 {k} 없음"


def test_cell_key_is_market_then_column(client):
    """키를 뒤집으면 화면 조회가 전부 빗나가는데 개수는 그대로라 안 잡힌다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert "smartstore:5" in data["cells"]
    assert "5:smartstore" not in data["cells"]


def test_drift_banner_is_carried_to_the_screen(client, monkeypatch):
    """🔴 배너가 화면까지 안 가면, 거짓 검증완료를 아무도 못 본다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "load_marks",
                        lambda name="dev_checklist_marks.json":
                        ({"smartstore:4": {"verified": "2026-08-12"}}, ""))
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert data["drift"], "배너가 화면까지 안 왔다"
    assert "카테고리" in data["drift"][0]


def test_stored_only_cells_exist(client):
    """정책값 대부분이 저장만 되는 현실이 표에 그대로 드러나야 한다."""
    data = client.get("/marketplace-guide/checklist.json").get_json()
    assert sum(1 for c in data["cells"].values() if c["state"] == "stored") > 0


# ── 화면 조각 (_checklist_matrix.html) ──────────────────────────────────
# 🔴 아래 시험들은 「그 글자가 파일에 있나」만 센다 — 깨진 채로도 통과한다.
#    진짜 검증은 라이브 실화면 측정이다. 그래도 빠뜨림은 이 그물이 막는다.
import pathlib

TPL = pathlib.Path(mg.__file__).parents[1] / "templates"


def _matrix():
    return (TPL / "_checklist_matrix.html").read_text(encoding="utf-8")


def test_first_column_is_sticky():
    html = _matrix()
    assert "position:sticky" in html and "left:0" in html


def test_numbers_use_tabular_nums():
    assert "tabular-nums" in _matrix()


def test_hover_card_lives_on_body_and_is_fixed():
    html = _matrix()
    assert "document.body.appendChild" in html
    assert "position:fixed" in html


def test_hover_delays_match_standard():
    html = _matrix().replace(" ", "")
    assert "OPEN_DELAY=140" in html
    assert "CLOSE_DELAY=250" in html


def test_hover_closes_on_scroll():
    assert "'scroll'" in _matrix() or '"scroll"' in _matrix()


def test_six_states_are_labelled_in_korean():
    html = _matrix()
    for word in ["미착수", "저장만", "나감", "검증완료", "불가", "해당없음"]:
        assert word in html, word


def test_wired_and_done_are_not_the_same_colour():
    """🔴 지금 done 은 0칸이고 wired 가 22칸이다. 둘을 합치면 아무도 확인 안 한 것이 검증완료로 보인다."""
    html = _matrix()
    assert "wired" in html and "done" in html
    import re
    m = re.search(r"wired[^\n]{0,120}", html)
    assert m and "done" not in m.group(0), "wired 와 done 이 한 줄에서 같이 처리된다"


def test_wiring_none_is_handled_separately():
    """🔴 wiring 이 3값이다. 뭉뚱그리면 칸조차 없는 12칸이 「저장은 된다」로 뜬다."""
    assert "'none'" in _matrix() or '"none"' in _matrix()


def test_drift_banner_is_rendered():
    """🔴 배너가 안 그려지면 거짓 검증완료를 아무도 못 본다."""
    assert "drift" in _matrix()


def test_contract_functions_are_exposed():
    html = _matrix()
    assert "window.CHECKLIST_HTML" in html
    assert "window.ckInit" in html


def test_pinning_moved_to_the_card_after_panel_was_removed():
    """오른쪽 고정판을 없앤 뒤(2026-08-13 사장님 지시) 「붙잡기」는 정보창이 맡는다.

    🔴 붙잡기가 사라지면, 주소를 복사하려고 마우스를 떼는 순간 카드가 닫힌다.
    """
    html = _matrix()
    assert "ckpanel" not in html, "없앤 고정판이 남아 있다"
    assert "pinnedKey" in html, "붙잡기가 어디에도 없다"


def test_popup_is_scaled_for_being_outside_the_zoom():
    """🔴 정보창만 `.dm2{zoom:1.58}` 밖이라 같은 12.5px 가 표 17.08px · 정보창 10.81px 로 보였다.

    글자는 여전히 세 가지뿐이다 — 확대 밖 값으로 11→17.5 · 12.5→19.75 · 14→22 를 쓴다.
    """
    html = _matrix()
    for size in ["17.5px", "19.75px", "22px"]:
        assert size in html, size
    assert "742px" in html, "정보창 폭 470 × 1.58 = 742 가 없다"


def test_zoom_is_never_used_on_the_popup():
    """🔴 zoom 을 걸면 offsetWidth 가 확대 전 값이라 place() 의 자리 계산이 어긋난다.

    주석은 `.dm2{zoom:1.58}` 을 설명해야 하므로 빼고 센다 — 실제 선언에만 없으면 된다.
    """
    import re
    body = re.sub(r"/\*.*?\*/", "", _matrix(), flags=re.S)   # CSS 주석 제거
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.S)        # Jinja 주석 제거
    assert "zoom:" not in body.replace(" ", "")


def test_pinned_panel_is_not_scaled_twice():
    """🔴 1.58배 보정은 확대 밖(.ckpop)에만 건다 — .ckcard 에 걸면 확대 안 부품까지 두 배가 된다."""
    import re
    html = _matrix()
    for line in html.split("\n"):
        if "17.5px" in line or "19.75px" in line or "742px" in line:
            assert ".ckpop" in line, f"확대 보정이 정보창 밖으로 샜다: {line.strip()}"
    # 보정은 .ckcard(공용 부품)가 아니라 .ckpop 으로만 걸어야 한다
    assert not re.search(r"^\.ckcard[^\n]*(17\.5px|19\.75px|742px)", html, re.M)


def test_card_leaves_room_to_flip_instead_of_covering_the_cell():
    """🔴 74vh 면 뒤집을 자리가 없어 카드가 가리키던 칸을 덮었다(실측 613px)."""
    html = _matrix().replace(" ", "")
    assert "max-height:56vh" in html
    assert "CARD_VH=0.56" in html, "CSS 의 56vh 와 JS 상수가 갈라지면 조용히 어긋난다"
    assert "maxHeight" in html, "자리에 맞춰 높이를 잘라 주지 않으면 칸을 덮는다"


def test_table_is_widened_beyond_the_950px_host():
    """🔴 25열이 950px 안에 갇히면 눌려서 안 읽힌다(사장님 화면에서 확인)."""
    html = _matrix()
    msg = "넓히기가 판매처 틀(.dm2) 안으로 한정돼 있어야 한다 — 소싱처까지 걸면 왼쪽이 잘린다"
    assert ".dm2 .ckroot{width:1170px;margin-left:-110px;}" in html, msg


def test_header_does_not_print_the_same_word_twice():
    """묶음이 한 칸뿐이고 이름이 같으면 rowspan 으로 합친다 — 안 합치면 같은 글자가 두 번 찍힌다."""
    html = _matrix()
    assert 'rowspan="2"' in html
    assert "cols[i].group === cols[i].name" in html


# NOTE 정적 검사로 「선언 없이 쓰는 이름」을 잡아 보려 했으나 규칙이 거짓양성을 냈다.
#   실제로 이 부류(`pinnedKey` 미선언)를 잡아낸 것은 **브라우저에서 눌러 본 것**이다 —
#   시험 88개도 `node --check` 도 통과했었다. 화면 확인을 건너뛰지 말 것.
