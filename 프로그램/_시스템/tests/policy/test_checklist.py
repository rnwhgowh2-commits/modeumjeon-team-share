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
    col = {"col": 2, "name": "상품명", "rule": "", "item": "name",
           "specs": {"smartstore": "100글자"}}
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
    problems = C.drift({"smartstore:2": {"verified": "2026-08-12"}})   # 2 = 상품명(저장만 됨)
    assert problems and "상품명" in problems[0]


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
                     "item": "name", "specs": {m: "값" for m, _ in CK.MARKETS}}])
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
    """🔴 빈 문자열로 내보내면 화면이 「저장만 됨」으로 그린다 — 칸조차 없는데 거짓말이다."""
    cells = C.build()["cells"]
    empty = [v for v in cells.values() if v["wiring"] == C.WIRING_NONE]
    assert len(empty) == 12, f"item 없는 열 2개 × 6마켓 = 12칸이어야 한다 (지금 {len(empty)})"
    assert all("칸이 아직 없" in v["wiring_note"] for v in empty)
    assert {v["wiring"] for v in cells.values()} <= {"wired", "stored", C.WIRING_NONE}


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

    # 마켓 목록이 판매처인 채로 두면 첫 칸에서 터진다 (조용히 ➖ 가 되면 아무도 못 알아챈다)
    with pytest.raises(KeyError):
        CK.build("src_cols.json", marks_file="src_marks.json")


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
