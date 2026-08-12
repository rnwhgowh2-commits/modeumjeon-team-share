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
