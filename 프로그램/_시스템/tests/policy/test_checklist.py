# -*- coding: utf-8 -*-
"""개발 체크리스트 — 열 정의와 셀 판정."""
import pytest

from lemouton.policy import checklist as C


def _cols():
    return {"columns": C.load_columns()}


def test_columns_are_25():
    cols = _cols()["columns"]
    assert len(cols) == 25, f"엑셀 Sheet2 는 B~Z 25열이다 (지금 {len(cols)})"


def test_every_column_has_required_keys():
    for c in _cols()["columns"]:
        for k in ("col", "group", "name", "rule", "item", "specs"):
            assert k in c, f"{c.get('name')} 에 {k} 없음"


def test_specs_cover_six_markets():
    markets = {"coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"}
    for c in _cols()["columns"]:
        assert set(c["specs"]) == markets, f"{c['name']} 의 마켓 목록이 다름"


def test_item_maps_to_real_policy_item_or_none():
    from lemouton.registration.process_policy import ITEM_KEYS
    for c in _cols()["columns"]:
        if c["item"] is not None:
            assert c["item"] in ITEM_KEYS, f"{c['name']} → 없는 항목 {c['item']}"


def test_price_column_carries_owner_rule():
    """사장님이 엑셀에 적어 두신 「▶」 기준이 살아 있어야 한다."""
    price = [c for c in _cols()["columns"] if c["item"] == "price"][0]
    assert "할인가" in price["rule"] and "마진율" in price["rule"]


def test_specs_are_not_all_empty():
    """열마다 적어도 한 마켓에는 실제 내용이 있어야 한다 — 엑셀을 헛읽으면 여기서 걸린다."""
    for c in _cols()["columns"]:
        assert any(v.strip() for v in c["specs"].values()), f"{c['name']} 의 마켓 값이 전부 비었다"


def test_column_numbers_are_unique():
    """col 로 열을 찾는 코드가 나중에 생긴다 — 중복이면 엉뚱한 열을 집는다."""
    nums = [c["col"] for c in _cols()["columns"]]
    assert len(nums) == len(set(nums)), f"열 번호 중복: {nums}"


def test_cell_na_when_excel_blank():
    """엑셀이 비었거나 「-」면 그 마켓엔 해당 없음."""
    col = {"col": 22, "name": "모델번호", "rule": "", "item": "ids",
           "specs": {"eleven11": "-"}}
    assert C.cell_state("eleven11", col) == "na"


def test_cell_impossible_when_excel_x():
    col = {"col": 13, "name": "가격비교 노출", "rule": "", "item": "price_compare",
           "specs": {"coupang": "X"}}
    assert C.cell_state("coupang", col) == "impossible"


def test_cell_todo_when_no_program_item():
    col = {"col": 24, "name": "사이즈", "rule": "", "item": None,
           "specs": {"coupang": "입력X"}}
    assert C.cell_state("coupang", col) == "todo"


def test_cell_todo_when_market_evidence_unknown():
    """롯데온은 등록 문서가 요약본이라 근거를 못 찾는다 = 미착수(불가 아님)."""
    col = {"col": 21, "name": "태그", "rule": "", "item": "tags",
           "specs": {"lotteon": "값 있음"}}
    assert C.cell_state("lotteon", col) == "todo"


def test_cell_stored_only_when_not_wired():
    """칸도 있고 마켓도 받는데 보내는 코드가 없으면 「저장만 됨」."""
    # ⚠️ 표본을 바꿀 때는 required.wiring_of 를 먼저 보라. 상품명은 2026-08-12 에
    #   배선이 생겨 「나감」이 됐다 — 그때 이 시험이 빨간불이 돼 알려 줬다.
    col = {"col": 4, "name": "카테고리", "rule": "", "item": "category",
           "specs": {"smartstore": "카테고리선택"}}
    assert C.cell_state("smartstore", col) == "stored"


def test_cell_done_needs_both_wired_and_verified():
    """판매가는 나가지만(WIRED), 실계정 확인 표시가 있어야 검증완료."""
    col = {"col": 5, "name": "판매가", "rule": "", "item": "price",
           "specs": {"smartstore": "판매가"}}
    assert C.cell_state("smartstore", col) == "wired"
    assert C.cell_state("smartstore", col,
                        marks={"smartstore:5": {"verified": "2026-08-12"}}) == "done"


def test_conflict_when_market_requires_but_we_skip():
    """11번가는 「등록 기본값」을 [필수]로 요구하는데 엑셀 제조사 칸은 「-」다.

    ⚠️ 조합을 바꾸지 마라 — required.py 의 실제 값에 맞춰 고른 것이다.
      (모델번호/11번가는 required 가 아니라 conditional 이라 여기 쓰면 안 된다.)
    """
    col = {"col": 17, "name": "제조사", "rule": "", "item": "listing",
           "specs": {"eleven11": "-"}}
    assert "필수" in C.conflict_of("eleven11", col)


def test_no_conflict_when_both_agree():
    col = {"col": 5, "name": "판매가", "rule": "", "item": "price",
           "specs": {"smartstore": "판매가"}}
    assert C.conflict_of("smartstore", col) == ""


def test_unknown_market_raises_instead_of_silently_becoming_na():
    """🔴 오타 난 마켓 이름이 「해당없음」으로 둔갑하면 아무도 못 알아챈다."""
    col = {"col": 5, "name": "판매가", "rule": "", "item": "price",
           "specs": {"smartstore": "판매가"}}
    with pytest.raises(KeyError) as e:
        C.cell_state("11st", col)          # eleven11 의 오타
    assert "11st" in str(e.value) and "smartstore" in str(e.value)


def test_status_of_none_item_is_unknown_so_branch_order_is_safe():
    """③(항목 없음)과 ④(근거 모름)가 같은 답을 내는 것은 **우연**이다.

    required.status_of(market, None) 이 UNKNOWN 을 돌려주기 때문인데,
    그게 바뀌면 cell_state 의 순서가 조용히 의미를 갖게 된다. 여기서 못 박는다.
    """
    from lemouton.policy import required as R
    assert R.status_of("smartstore", None)[0] == R.UNKNOWN


def test_marks_file_loads_and_is_a_dict():
    marks, why = C.load_marks()
    assert isinstance(marks, dict)
    assert why == "", f"저장소에 든 손보정 파일이 깨져 있다: {why}"


def test_build_returns_row_per_market():
    data = C.build()
    assert [r["market"] for r in data["rows"]] == \
        ["coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"]


def test_build_cell_count_is_columns_times_markets():
    data = C.build()
    assert len(data["cells"]) == len(data["columns"]) * len(data["rows"])


def test_denominator_counts_only_fillable_cells():
    """분모 = 채울 수 있는 칸. 해당없음·불가는 채울 길이 없으니 빼야 100%가 찬다.

    🔴 공식을 베끼지 마라 — `len(cols) - na` 로 적으면 코드가 틀려도 같이 틀려 준다.
      뜻(「분모는 상태가 옮겨 갈 수 있는 칸의 합」)으로 못 박는다.
    """
    data = C.build()
    for row in data["rows"]:
        c = row["counts"]
        assert c["total"] == c["todo"] + c["stored"] + c["wired"] + c["done"], \
            f"{row['market']} 의 분모가 채울 수 있는 칸 수와 다르다: {c}"


def test_a_market_with_impossible_cells_can_still_reach_100():
    """⚫불가는 `cell_state` 가 손보정을 보기도 전에 끊는다 = done 이 될 길이 없다.

    분모에 남겨 두면 그 마켓은 전부 검증해도 95.5% 에서 멈춘다.
    """
    data = C.build()
    row = [r for r in data["rows"] if r["market"] == "coupang"][0]
    c = row["counts"]
    assert c["impossible"] >= 1, "쿠팡에 ⚫불가 칸이 없으면 이 시험은 아무것도 안 본다"
    assert c["total"] == c["todo"] + c["stored"] + c["wired"] + c["done"]


def test_build_marks_lotteon_as_evidence_missing():
    """롯데온은 등록 문서가 요약본이라 대부분 미착수로 떠야 한다."""
    data = C.build()
    lotteon = [r for r in data["rows"] if r["market"] == "lotteon"][0]
    assert lotteon["counts"]["todo"] >= 10


def test_drift_flags_verified_on_something_that_never_goes_out():
    """🔴 조용한 통과 금지 — 나가지도 않는 값에 「검증완료」가 달려 있으면 알린다."""
    problems = C.drift({"smartstore:4": {"verified": "2026-08-12"}})   # 4 = 카테고리(저장만 됨)
    assert problems and "카테고리" in problems[0]


def test_drift_silent_when_marks_are_sane():
    assert C.drift({"smartstore:5": {"verified": "2026-08-12"}}) == []   # 5 = 판매가(나감)


def test_drift_flags_unknown_column():
    problems = C.drift({"smartstore:99": {"verified": "2026-08-12"}})
    assert problems and "99" in problems[0]


def test_build_passes_columns_file_through_to_drift(tmp_path, monkeypatch):
    """🔴 build 가 다른 열 정의를 받으면 배너도 **그 열 정의**로 판정해야 한다.

    안 넘기면 배너가 엉뚱한 표를 보고, 있는 경고를 놓치거나 없는 경고를 띄운다.
    """
    from lemouton.policy import checklist as CK

    # 열 하나뿐인 가짜 열 정의를 만들어 둔다 (77번 열은 진짜 표에 없다)
    # ⚠️ 저장소 데이터 폴더에 쓰지 마라 — git 무시 대상이 아니라 찌꺼기가 커밋에 딸려 간다.
    _write_columns(tmp_path, "fake_columns.json",
                   [{"col": 77, "group": "시험", "name": "가짜열", "rule": "",
                     "item": "category", "specs": {m: "값" for m, _ in CK.MARKETS}}])
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    monkeypatch.setattr(CK, "load_marks", lambda name="dev_checklist_marks.json":
                        ({"coupang:77": {"verified": "2026-08-12"}}, ""))
    data = CK.build("fake_columns.json")
    # 77번 열은 진짜 표엔 없다 — 파일이 안 넘어가면 「없는 열 번호」로 잘못 뜬다
    assert data["drift"], "배너가 아예 안 떴다"
    assert "가짜열" in data["drift"][0], f"엉뚱한 표를 봤다: {data['drift'][0]}"


# ══════════════════════════════════════════════════════════════════════════
#  손보정 → 화면 경로 (🔴 여기가 끊기면 검증완료가 화면에 영영 안 뜬다)
# ══════════════════════════════════════════════════════════════════════════

def test_marks_actually_reach_the_cells(monkeypatch):
    """🔴 심기 전 wired → 심은 뒤 done. 이 경로가 끊기면 화면에 검증완료가 영영 안 뜬다."""
    from lemouton.policy import checklist as CK
    before = CK.build()["cells"]["smartstore:5"]
    assert before["state"] == "wired" and before["verified"] == ""
    monkeypatch.setattr(CK, "load_marks",
                        lambda name="dev_checklist_marks.json":
                        ({"smartstore:5": {"verified": "2026-08-12"}}, ""))
    after = CK.build()["cells"]["smartstore:5"]
    assert after["state"] == "done"
    assert after["verified"] == "2026-08-12"


def test_cell_key_is_market_then_column():
    """키를 뒤집으면 화면 조회가 전부 빗나가는데 개수는 그대로라 안 잡힌다."""
    data = C.build()
    assert "smartstore:5" in data["cells"]
    assert "5:smartstore" not in data["cells"]


def test_one_cell_is_pinned_field_by_field():
    """대표 칸 하나를 실제 값으로 못 박는다 — 개수만 세는 시험은 백지도 통과시킨다.

    (스마트스토어 × 5열 판매가 = 마켓도 필수, 우리도 실제로 내보내는 칸.)
    """
    cell = C.build()["cells"]["smartstore:5"]
    assert cell["state"] == "wired"          # 나가지만 실계정 확인 전
    assert cell["wiring"] == "wired"
    assert cell["required"] == "required"
    assert cell["api"] == "smartstore.create-product-product"
    assert cell["conflict"] == ""
    assert cell["verified"] == ""
    assert "salePrice" in cell["evidence"]


def test_cells_without_a_program_field_say_none_not_blank():
    """🔴 상수를 쓰지 마라 — 상수와 비교하면 상수를 바꿔도 통과한다(자기 자신과의 비교).

    화면 조각이 `wiring != 'wired'` 로 뭉뚱그리면, 프로그램에 칸조차 없는 칸이
    「저장은 된다」는 거짓말로 뜬다. 그래서 빈 문자열이 아니라 **이름 있는 값**이어야 한다.
    """
    cells = C.build()["cells"]
    nones = [k for k, v in cells.items() if v["wiring"] == "none"]
    assert nones, "프로그램에 칸이 없는 칸이 하나도 없다 — 데이터가 바뀌었는지 확인하라"
    assert len(nones) == 12, f"item 없는 열 2개 × 6마켓 = 12칸이어야 한다 (지금 {len(nones)})"
    assert all(cells[k]["wiring_note"] for k in nones), "왜 none 인지 설명이 비었다"
    assert not any(v["wiring"] == "" for v in cells.values()), "이름 없는 빈 값이 남아 있다"
    assert {v["wiring"] for v in cells.values()} <= {"wired", "stored", "none"}


def test_verified_is_only_carried_on_done_cells(monkeypatch):
    """🔴 초록이 아닌 칸에 날짜가 실리면 화면이 「반쯤 검증됨」으로 읽힌다."""
    from lemouton.policy import checklist as CK
    seeded = {"smartstore:4": {"verified": "2026-08-12"},   # 저장만 됨(카테고리)
              "lotteon:6": {"verified": "2026-08-12"},      # 해당없음
              "coupang:13": {"verified": "2026-08-12"},     # 불가
              "smartstore:5": {"verified": "2026-08-12"}}   # 나감 → 검증완료
    monkeypatch.setattr(CK, "load_marks",
                        lambda name="dev_checklist_marks.json": (seeded, ""))
    cells = CK.build()["cells"]
    assert cells["smartstore:5"]["verified"] == "2026-08-12"
    for k in ("smartstore:4", "lotteon:6", "coupang:13"):
        assert cells[k]["verified"] == "", f"{k} 에 날짜가 실렸다 ({cells[k]['state']})"


# ══════════════════════════════════════════════════════════════════════════
#  drift 는 cell_state 하나에만 물어본다 (잣대가 둘이면 화면과 배너가 딴말한다)
# ══════════════════════════════════════════════════════════════════════════

def test_drift_names_an_unknown_market_no_matter_which_column():
    """🔴 같은 오타가 열 번호에 따라 침묵/오보로 갈리면 안 된다.

    예전엔 11st:5 는 조용했고 11st:2 는 없는 마켓 이름을 찍어 진짜 경고인 척했다.
    """
    for col_no in (2, 5, 13):
        problems = C.drift({f"11st:{col_no}": {"verified": "2026-08-12"}})
        assert problems, f"열 {col_no} 에서 오타 난 마켓이 조용히 넘어갔다"
        assert "모르는 마켓" in problems[0] and "11st" in problems[0]
        assert "eleven11" in problems[0], "쓸 수 있는 이름을 같이 알려 줘야 한다"


def test_drift_gives_the_real_reason_not_a_stand_in():
    """사유가 틀리면 사장님이 엉뚱한 데를 고치러 간다 — 배선을 뒤져도 답이 없다."""
    na = C.drift({"lotteon:6": {"verified": "2026-08-12"}})      # 엑셀이 「-」
    assert na and "해당 없는" in na[0], na
    imp = C.drift({"coupang:13": {"verified": "2026-08-12"}})    # 엑셀이 「X」
    assert imp and "기능 자체가 없" in imp[0], imp
    todo = C.drift({"lotteon:2": {"verified": "2026-08-12"}})    # 롯데온 근거 못 찾음
    assert todo and "근거를 아직 못 찾" in todo[0], todo


def test_na_and_impossible_cells_never_carry_a_verified_date(monkeypatch):
    """🔴 ➖ 옆에 검증일이 붙으면 화면 자체가 모순이다 — 말은 배너가 한다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "load_marks", lambda name="dev_checklist_marks.json":
                        ({"lotteon:6": {"verified": "2026-08-12"},
                          "coupang:13": {"verified": "2026-08-12"}}, ""))
    data = CK.build()
    assert data["cells"]["lotteon:6"]["state"] == "na"
    assert data["cells"]["lotteon:6"]["verified"] == ""
    assert data["cells"]["coupang:13"]["state"] == "impossible"
    assert data["cells"]["coupang:13"]["verified"] == ""
    assert len(data["drift"]) == 2, "화면에서 숨겼으면 배너로는 반드시 말해야 한다"


# ══════════════════════════════════════════════════════════════════════════
#  손보정 파일 읽기 — 오타 한 칸이 표를 가리지도, 조용히 사라지지도 않게
# ══════════════════════════════════════════════════════════════════════════

def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return name


def _write_columns(tmp_path, name, columns):
    import json as _json
    return _write(tmp_path, name, _json.dumps({"columns": columns}, ensure_ascii=False))


def test_load_marks_missing_file_is_quiet(tmp_path, monkeypatch):
    """아직 아무도 안 달았을 뿐 — 이건 사고가 아니다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    assert CK.load_marks("아직없는파일.json") == ({}, "")


def test_load_marks_broken_json_reports_instead_of_killing_the_table(tmp_path, monkeypatch):
    """후행 쉼표 하나로 표 150칸이 통째로 사라지면 안 된다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write(tmp_path, "m.json", '{"marks": {"smartstore:5": {"verified": "2026-08-12"},}}')
    marks, why = CK.load_marks("m.json")
    assert marks == {}
    assert "읽지 못했습니다" in why and "반영되지 않습니다" in why


def test_load_marks_without_the_marks_wrapper_is_not_silently_empty(tmp_path, monkeypatch):
    """🔴 껍데기를 빠뜨리면 손보정이 통째로 사라지면서 배너까지 같이 꺼졌었다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write(tmp_path, "m.json", '{"smartstore:5": {"verified": "2026-08-12"}}')
    marks, why = CK.load_marks("m.json")
    assert marks == {}
    assert "marks 가 없습니다" in why


def test_load_marks_rejects_values_that_are_not_a_dict(tmp_path, monkeypatch):
    """값이 문자열이면 예전엔 AttributeError 로 build·drift 둘 다 죽었다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write(tmp_path, "m.json", '{"marks": {"smartstore:5": "2026-08-12"}}')
    marks, why = CK.load_marks("m.json")
    assert marks == {} and "smartstore:5" in why

    _write(tmp_path, "m2.json", '{"marks": ["smartstore:5"]}')
    marks2, why2 = CK.load_marks("m2.json")
    assert marks2 == {} and "표가 아닙니다" in why2


def test_broken_marks_file_shows_a_banner_but_the_table_still_draws(tmp_path, monkeypatch):
    """표는 그대로 그리고, 왜 손보정이 안 먹었는지는 배너 **맨 앞**에서 말한다."""
    import os as _os
    import shutil as _shutil
    from lemouton.policy import checklist as CK
    real = _os.path.join(CK._DATA, "dev_checklist_columns.json")
    _shutil.copy(real, str(tmp_path / "dev_checklist_columns.json"))
    _write(tmp_path, "m.json", '{"marks": {"smartstore:2": {"verified": "2026-08-12"},}}')
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    data = CK.build(marks_file="m.json")
    assert len(data["cells"]) == len(data["columns"]) * len(data["rows"]), \
        "오타 한 칸이 표를 통째로 가렸다"
    assert data["drift"] and "읽지 못했습니다" in data["drift"][0]


# ══════════════════════════════════════════════════════════════════════════
#  열 번호 중복 — 조용히 덮어쓰면 칸이 사라지는데 개수만 맞는다
# ══════════════════════════════════════════════════════════════════════════

def test_duplicate_column_numbers_blow_up_on_load(tmp_path, monkeypatch):
    """🔴 기본 파일만 보는 시험은 손으로 쓴 새 판을 못 지킨다 — 읽는 자리에서 막는다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write_columns(tmp_path, "dup.json",
                   [{"col": 5, "group": "시험", "name": "앞", "rule": "", "item": None,
                     "specs": {"coupang": "값"}},
                    {"col": 5, "group": "시험", "name": "뒤", "rule": "", "item": None,
                     "specs": {"coupang": "값"}}])
    with pytest.raises(ValueError) as e:
        CK.load_columns("dup.json")
    assert "5" in str(e.value) and "겹칩니다" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════
#  판(열 정의·마켓 목록·손보정) 은 셋이 같이 바뀐다
# ══════════════════════════════════════════════════════════════════════════

def test_board_switches_columns_markets_and_marks_together(tmp_path, monkeypatch):
    """🔴 하나라도 모듈에 박혀 있으면 소싱처판이 시작하자마자 터지거나 판이 섞인다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write_columns(tmp_path, "src_cols.json",
                   [{"col": 1, "group": "시험", "name": "소싱처열", "rule": "", "item": None,
                     "specs": {"musinsa": "값 있음", "ssf": "값 있음"}}])
    _write(tmp_path, "src_marks.json", '{"marks": {}}')
    board = [("musinsa", "무신사"), ("ssf", "SSF")]

    data = CK.build("src_cols.json", markets=board, marks_file="src_marks.json")
    assert [r["market"] for r in data["rows"]] == ["musinsa", "ssf"]
    assert set(data["cells"]) == {"musinsa:1", "ssf:1"}
    assert data["drift"] == []

    # 마켓 목록을 안 바꾸면 판매처 6마켓이 통째로 「빠져 있다」로 뜬다.
    # (조용히 ➖ 로 지어내면 아무도 못 알아챈다. 표는 그리되 전건을 배너로 말한다.)
    wrong = CK.build("src_cols.json", marks_file="src_marks.json")
    assert len(wrong["rows"]) == 6
    assert wrong["drift"] and "빠져 있습니다" in wrong["drift"][0]
    for m, _ in CK.MARKETS:
        assert m in wrong["drift"][0], f"{m} 이 빠졌다고 말하지 않았다"
    assert all(c["state"] == "todo" for c in wrong["cells"].values())
    # 직접 부르는 쪽은 여전히 크게 터진다 — `_spec` 의 계약은 그대로다
    with pytest.raises(KeyError):
        CK.cell_state("coupang", {"col": 1, "name": "소싱처열",
                                  "specs": {"musinsa": "값 있음"}})


def test_marks_from_another_board_do_not_become_false_alarms(tmp_path, monkeypatch):
    """판매처 손보정 파일을 소싱처 표가 읽으면 전건이 거짓 경보가 된다 — 파일부터 가른다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write_columns(tmp_path, "src_cols.json",
                   [{"col": 1, "group": "시험", "name": "소싱처열", "rule": "", "item": None,
                     "specs": {"musinsa": "값 있음", "ssf": "값 있음"}}])
    _write(tmp_path, "seller_marks.json",
           '{"marks": {"smartstore:1": {"verified": "2026-08-12"}}}')
    board = [("musinsa", "무신사"), ("ssf", "SSF")]
    data = CK.build("src_cols.json", markets=board, marks_file="seller_marks.json")
    assert data["drift"] and "모르는 마켓" in data["drift"][0]
    assert "musinsa" in data["drift"][0], "그 판에서 쓸 수 있는 이름을 알려 줘야 한다"


def test_empty_market_list_means_empty_not_everything():
    """🔴 「마켓 없음」이 「전부」로 뒤집히면, 빈 설정이 조용히 판매처 표를 그린다."""
    data = C.build(markets=[])
    assert data["rows"] == [] and data["cells"] == {}


def test_missing_market_in_a_column_shows_banner_not_a_dead_page(tmp_path, monkeypatch):
    """🔴 손으로 쓰는 소싱처 열 정의의 오타 한 칸이 지도 탭 전체를 죽이면 안 된다.

    손보정 오타는 배너로 살려 두면서 열 정의 오타만 500 이면 비대칭이다.
    다만 빠진 칸을 「해당없음」으로 지어내지는 않는다 — ⬜미착수 + 왜인지.
    """
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write_columns(tmp_path, "c.json",
                   [{"col": 1, "group": "시", "name": "빠진열", "rule": "", "item": None,
                     "specs": {"musinsa": "값"}}])          # ssf 가 빠졌다
    monkeypatch.setattr(CK, "load_marks", lambda name=None: ({}, ""))
    data = CK.build("c.json", markets=[("musinsa", "무신사"), ("ssf", "SSF")])
    assert len(data["cells"]) == 2, "빠진 칸도 자리는 있어야 한다"
    assert data["cells"]["ssf:1"]["state"] == "todo"
    assert "빠져" in data["cells"]["ssf:1"]["note"]
    assert any("빠진열" in b and "ssf" in b for b in data["drift"]), data["drift"]


def test_drift_survives_a_column_that_lost_its_market(tmp_path, monkeypatch):
    """배너를 만드는 쪽이 같은 자리에서 죽으면 표를 살려 둔 보람이 없다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write_columns(tmp_path, "c.json",
                   [{"col": 1, "group": "시", "name": "빠진열", "rule": "", "item": None,
                     "specs": {"musinsa": "값"}}])
    problems = CK.drift({"ssf:1": {"verified": "2026-08-12"}}, "c.json",
                        [("musinsa", "무신사"), ("ssf", "SSF")])
    assert problems and "빠져" in problems[0], problems


# ══════════════════════════════════════════════════════════════════════════
#  살아 있는 방어 — 셋 다 사장님이 손으로 파일을 고칠 때 실제로 나는 일이다
# ══════════════════════════════════════════════════════════════════════════

def test_marks_file_saved_as_ansi_does_not_kill_the_page(tmp_path, monkeypatch):
    """메모장에서 「ANSI」로 저장하면 utf-8 로 못 읽는다 — 500 이 아니라 배너여야 한다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    (tmp_path / "ansi.json").write_text(
        '{"marks": {"smartstore:5": {"verified": "2026-08-12", "note": "실계정 확인함"}}}',
        encoding="cp949")                      # 한글이 cp949 바이트로 들어간다
    marks, why = CK.load_marks("ansi.json")
    assert marks == {}
    assert "읽지 못했습니다" in why, why


def test_marks_file_holding_bare_null_does_not_kill_the_page(tmp_path, monkeypatch):
    """내용을 통째로 지워 `null` 만 남으면 예전엔 TypeError 로 표가 통째로 죽었다."""
    from lemouton.policy import checklist as CK
    monkeypatch.setattr(CK, "_DATA", str(tmp_path))
    _write(tmp_path, "n.json", "null")
    marks, why = CK.load_marks("n.json")
    assert marks == {}
    assert "marks 가 없습니다" in why, why


def test_zero_padded_column_number_is_explained_not_a_crash():
    """`smartstore:05` 처럼 0 을 붙여 적으면 화면이 그 값을 영영 못 읽는다.

    🔴 `int("05")` 은 5 로 통과하지만 `cell_state` 의 키는 `smartstore:5` 라 안 맞는다.
      사유 표에 그 경우가 없으면 KeyError 로 표 전체가 죽는다 — 조용히 넘기지도 않는다.
    """
    problems = C.drift({"smartstore:05": {"verified": "2026-08-12"}})
    assert problems and "형식" in problems[0], problems
    assert "0 을 붙이지" in problems[0], problems


# ══════════════════════════════════════════════════════════════════════════
#  소싱처판 — 근거표가 없어 손보정 비중이 크다. 판이 섞이는 것이 가장 무섭다.
# ══════════════════════════════════════════════════════════════════════════

def test_sourcing_specs_cover_eight_sources():
    cols = C.load_columns("dev_checklist_sourcing.json")
    keys = {k for k, _ in C.SOURCES}
    for c in cols:
        assert set(c["specs"]) == keys, f"{c['name']} 의 소싱처 목록이 다름"


def test_sourcing_column_numbers_are_unique():
    C.load_columns("dev_checklist_sourcing.json")   # 겹치면 ValueError 로 터진다


def test_sourcing_columns_carry_the_eight_groups():
    """설계서 §2-2 의 8묶음이 그대로 있어야 한다 — 묶음이 빠지면 표 머리글이 뭉갠다."""
    cols = C.load_columns("dev_checklist_sourcing.json")
    groups = []
    for c in cols:
        if not groups or groups[-1] != c["group"]:
            groups.append(c["group"])
    assert len(groups) == 8, f"묶음이 8개가 아니다: {groups}"
    assert len(groups) == len(set(groups)), f"같은 묶음이 떨어져 있다(머리글이 쪼개진다): {groups}"


def test_sourcing_items_are_all_none():
    """소싱처엔 가공정책 항목이 대응하지 않는다 — 억지로 붙이면 없는 배선을 있다고 말한다."""
    for c in C.load_columns("dev_checklist_sourcing.json"):
        assert c["item"] is None, f"{c['name']} 에 item 이 붙어 있다: {c['item']}"


def test_sourcing_lotteon_is_not_named_after_lotteimall():
    """🔴 `lotteon` 을 「롯데홈쇼핑」이라 적으면 `lotteimall` 줄과 이름이 겹친다."""
    names = dict(C.SOURCES)
    assert names["lotteon"] == "롯데온"
    assert names["lotteimall"] != names["lotteon"]
    assert len(set(names.values())) == len(names), "소싱처 이름이 겹친다"


def test_build_sourcing_has_same_shape_as_build():
    a, b = C.build(), C.build_sourcing()
    assert set(a) == set(b)
    assert set(next(iter(a["cells"].values()))) == set(next(iter(b["cells"].values())))


def test_build_sourcing_has_a_row_per_source_and_a_cell_per_column():
    data = C.build_sourcing()
    assert [r["market"] for r in data["rows"]] == [k for k, _ in C.SOURCES]
    assert len(data["cells"]) == len(data["columns"]) * len(data["rows"])


def test_sourcing_marks_do_not_mix_with_marketplace(monkeypatch):
    """🔴 판이 섞이면 있는 경고를 놓치거나 없는 경고를 띄운다."""
    import lemouton.policy.checklist as CK
    seen = []
    orig = CK.load_marks
    monkeypatch.setattr(CK, "load_marks", lambda name="dev_checklist_marks.json": (seen.append(name), orig(name))[1])
    CK.build_sourcing()
    assert "dev_checklist_sourcing_marks.json" in seen
    assert "dev_checklist_marks.json" not in seen


def test_sourcing_state_follows_crawler_then_marks(monkeypatch):
    """크롤러 있으면 🟡저장만 · 손보정 검증완료면 🟢 · 불가면 ⚫. 순서를 바꾸면 뜻이 뒤집힌다."""
    import lemouton.policy.checklist as CK
    monkeypatch.setattr(CK, "load_marks", lambda name=None:
                        ({"musinsa:3": {"verified": "2026-08-12"},
                          "ssf:3": {"impossible": True, "note": "원래 안 되는 칸"}}, ""))
    cells = CK.build_sourcing()["cells"]
    assert cells["musinsa:3"]["state"] == "done"
    assert cells["musinsa:3"]["verified"] == "2026-08-12"
    assert cells["ssf:3"]["state"] == "impossible"
    assert cells["ssf:3"]["verified"] == "", "불가 칸에 날짜가 실리면 화면이 모순이다"
    assert cells["lemouton:3"]["state"] == "stored", "크롤러가 있는데 미착수로 떨어졌다"


def test_sourcing_cells_never_carry_a_nameless_wiring():
    """🔴 빈 문자열이면 화면이 `!= 'wired'` 로 뭉뚱그려 「저장은 된다」는 거짓말이 뜬다."""
    cells = C.build_sourcing()["cells"]
    assert {v["wiring"] for v in cells.values()} <= {"wired", "stored", "none"}
    assert all(v["wiring_note"] for v in cells.values())


def test_sourcing_required_says_unknown_not_blank():
    """근거표가 없는 것은 「요구 안 한다」가 아니라 「모른다」다."""
    cells = C.build_sourcing()["cells"]
    assert all(v["required"] == "unknown" for v in cells.values())
    assert all(v["note"] for v in cells.values()), "왜 모르는지가 비었다"


def test_sourcing_denominator_counts_only_fillable_cells(monkeypatch):
    """⚫불가는 done 이 될 길이 없다 — 분모에 남기면 100%가 영영 안 찬다."""
    import lemouton.policy.checklist as CK
    monkeypatch.setattr(CK, "load_marks", lambda name=None:
                        ({"ssf:3": {"impossible": True}}, ""))
    row = [r for r in CK.build_sourcing()["rows"] if r["market"] == "ssf"][0]
    c = row["counts"]
    assert c["impossible"] == 1
    assert c["total"] == c["todo"] + c["stored"] + c["wired"] + c["done"]


def test_sourcing_drift_flags_an_unknown_source_name(monkeypatch):
    """판매처 손보정을 소싱처 표가 읽으면 전건이 거짓 경보가 된다 — 이름부터 잡는다."""
    import lemouton.policy.checklist as CK
    monkeypatch.setattr(CK, "load_marks", lambda name=None:
                        ({"smartstore:3": {"verified": "2026-08-12"}}, ""))
    drift = CK.build_sourcing()["drift"]
    assert drift and "모르는 소싱처" in drift[0]
    assert "musinsa" in drift[0], "그 판에서 쓸 수 있는 이름을 알려 줘야 한다"


def test_sourcing_drift_flags_a_column_the_table_cannot_show(monkeypatch):
    """🔴 `musinsa:03` 은 파일엔 남는데 화면 키(`musinsa:3`)와 달라 영영 안 읽힌다."""
    import lemouton.policy.checklist as CK
    monkeypatch.setattr(CK, "load_marks", lambda name=None:
                        ({"musinsa:03": {"verified": "2026-08-12"},
                          "ssf:999": {"verified": "2026-08-12"}}, ""))
    drift = CK.build_sourcing()["drift"]
    assert len(drift) == 2, drift
    assert all("열 번호를 표에서 찾지 못했습니다" in d for d in drift), drift


def test_sourcing_marks_file_in_repo_is_readable():
    marks, why = C.load_marks("dev_checklist_sourcing_marks.json")
    assert isinstance(marks, dict)
    assert why == "", f"저장소에 든 소싱처 손보정 파일이 깨져 있다: {why}"


def test_sourcing_says_so_when_it_cannot_check_the_crawlers(monkeypatch):
    """🔴 크롤러 확인 실패를 삼키면 184칸이 통째로 ⬜로 뒤집히는데 이유가 안 뜬다."""
    import lemouton.policy.checklist as CK

    def _boom(_key):
        raise ImportError("크롤러 꾸러미를 못 읽음")

    monkeypatch.setattr(CK, "_crawler_registered", _boom)
    data = CK.build_sourcing()
    assert any("확인하지 못했습니다" in d for d in data["drift"]), data["drift"]
    assert all(c["state"] == "todo" for c in data["cells"].values())


def test_crawler_registered_does_not_swallow_import_failure(monkeypatch):
    """`_crawler_registered` 자체는 조용히 False 로 떨어지면 안 된다."""
    import lemouton.policy.checklist as CK
    import lemouton.sourcing.crawlers as CR
    monkeypatch.setattr(CR, "build_crawlers", lambda: (_ for _ in ()).throw(RuntimeError("망가짐")))
    with pytest.raises(RuntimeError):
        CK._crawler_registered("musinsa")


def test_all_eight_crawlers_are_registered_today():
    """오늘의 사실을 못 박는다 — 하나라도 빠지면 그 소싱처는 아무것도 시작 안 된 것이다."""
    for key, label in C.SOURCES:
        assert C._crawler_registered(key), f"{label}({key}) 크롤러가 build_crawlers 에 없다"
