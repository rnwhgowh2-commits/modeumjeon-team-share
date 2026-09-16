# -*- coding: utf-8 -*-
"""margin_status_history.js — 「[판매처] 주문상태」 칸 = 주문상태 이력의 마지막 상태.

사장님 지시 2026-09-16 — 칸이 주문 라인의 상태만 찍어서, 그 뒤에 들어온 클레임
(반품요청 등)이 🕒 호버를 열어야만 보였다. 라이브 실제 행:
  칸 "배송완료"  /  이력 배송중 → 배송완료(확인 2026-09-15) → 반품요청(2026-09-15)

여기서 지키는 것 셋:
  ① 새로 판정하지 않는다 — 서버가 시간순으로 정렬해 준 배열의 마지막 칸을 읽을 뿐.
  ② 원본 r['판매처_주문상태'] 는 안 덮어쓴다 — 카드 분류가 그 값을 읽는다.
  ③ 화면·컬럼필터·정렬·엑셀이 **같은 값**을 쓴다(한 곳만 바꾸면 화면과 필터가 어긋난다).
"""
import json
import pathlib
import shutil
import subprocess

import pytest

_STATIC = pathlib.Path(__file__).resolve().parents[2] / "webapp" / "static"
HIST = _STATIC / "margin_status_history.js"
COLF = _STATIC / "margin_col_filter_fix.js"


def test_files_exist():
    assert HIST.exists() and COLF.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_last_status_and_consistency_via_node():
    script = r"""
    globalThis.window = globalThis;          // document 는 없음 → 호버 배선은 no-op
    require(process.argv[1]);                // margin_status_history.js
    require(process.argv[2]);                // margin_col_filter_fix.js
    const last = window._ssLastStatusText;
    const sortVal = window._moumDetailSortVal;
    const forExport = window._moumRowsForExport;
    const filterKey = window._moumColFilterKey;
    const cell = window._ssVerdictCellHtml;

    // 라이브 실제 행 — 칸은 배송완료인데 이력 마지막은 반품요청
    const claimed = {
      '판매처_주문상태': '배송완료', '정산여부': '진행중',
      '_주문상태이력': [
        {status: '배송중', at: ''},
        {status: '배송완료', at: '2026-09-15', at_kind: 'detected'},
        {status: '반품요청', at: '2026-09-15', at_kind: 'event'}
      ]
    };
    // 클레임이 안 받아들여지고 그대로 이행된 주문 — 마지막이 배송완료라 그대로
    const fulfilled = {
      '판매처_주문상태': '배송완료', '정산여부': 'O',
      '_주문상태이력': [
        {status: '취소요청', at: '2026-09-04', at_kind: 'event'},
        {status: '배송완료', at: '2026-09-06', at_kind: 'detected'}
      ]
    };
    const noHist  = {'판매처_주문상태': '배송완료', '정산여부': '확인불가', '_주문상태이력': []};
    const oneHist = {'판매처_주문상태': '', '정산여부': '확인불가',
                     '_주문상태이력': [{status: '구매확정', at: '2026-09-10'}]};

    const out = {
      claimed: last(claimed),
      fulfilled: last(fulfilled),
      noHist: last(noHist),
      oneHist: last(oneHist),
      // 원본은 그대로여야 한다(카드 분류가 읽는 값)
      raw_untouched: claimed['판매처_주문상태'],
      // 정렬·필터·엑셀이 화면과 같은 값
      sort_same: sortVal(claimed, '판매처_주문상태'),
      sort_other_number: sortVal({'순마진': 1234}, '순마진'),
      filter_same: filterKey(claimed, '판매처_주문상태'),
      filter_other: filterKey({'마켓': '쿠팡'}, '마켓'),
      export_val: forExport([claimed])[0]['판매처_주문상태'],
      export_raw_untouched: claimed['판매처_주문상태'],
      export_same_ref: forExport([fulfilled])[0] === fulfilled,
      // 이력이 1건이어도 칸 글자가 원본과 달라졌으면 🕒 호버가 있어야 한다
      hover_oneHist: cell(oneHist).indexOf('data-ss-hist') >= 0,
      hover_noHist: cell(noHist).indexOf('data-ss-hist') >= 0,
      hover_claimed: cell(claimed).indexOf('data-ss-hist') >= 0
    };
    console.log(JSON.stringify(out));
    """
    r = subprocess.run(["node", "-e", script, str(HIST), str(COLF)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])

    assert out["claimed"] == "반품요청", "이력 마지막(반품요청)이 칸에 안 찍힘"
    assert out["fulfilled"] == "배송완료", "클레임 뒤 이행된 주문까지 클레임으로 뒤집으면 안 된다"
    assert out["noHist"] == "배송완료", "이력이 없으면 원본 그대로(폴백·날조 금지)"
    assert out["oneHist"] == "구매확정", "원본이 비어도 이력이 있으면 그 상태를 찍는다"
    assert out["raw_untouched"] == "배송완료", "원본 판매처_주문상태를 덮어썼다 — 카드 분류가 어긋난다"

    assert out["sort_same"] == "반품요청", "정렬이 화면과 다른 값을 본다"
    assert out["sort_other_number"] == 1234, "다른 칼럼은 원본 그대로(숫자 정렬 유지)"
    assert out["filter_same"] == "반품요청", "컬럼필터가 화면과 다른 값을 본다"
    assert out["filter_other"] == "쿠팡", "다른 칼럼 필터 키가 바뀌었다"
    assert out["export_val"] == "반품요청", "엑셀이 화면과 다른 값을 내보낸다"
    assert out["export_raw_untouched"] == "배송완료", "엑셀 변환이 원본 행을 훼손했다"
    assert out["export_same_ref"] is True, "바뀔 게 없는 행은 복사하지 않는다(원본 참조 유지)"

    assert out["hover_claimed"], "이력 호버(🕒)가 사라짐"
    assert out["hover_oneHist"], "칸 글자가 원본과 다른데 이력 호버가 없다(설명 없는 값)"
    assert not out["hover_noHist"], "이력이 없는데 호버가 붙었다"


def test_embed_wires_the_helpers():
    """서빙 템플릿이 세 배선(셀·정렬·엑셀)을 실제로 호출하는지 — 함수만 있고 안 부르면 무효."""
    html = (pathlib.Path(__file__).resolve().parents[2]
            / "webapp" / "templates" / "orders" / "margin_embed.html").read_text(encoding="utf-8")
    assert "v = window._ssLastStatusText(r)" in html, "셀 표기 배선 없음"
    assert html.count("window._moumDetailSortVal") == 8, "정렬 배선은 표 두 곳 × (가드+호출) × (a,b) = 8회"
    assert "window._moumRowsForExport(filteredRows)" in html, "엑셀 배선 없음"
