# -*- coding: utf-8 -*-
r"""분석 결과 → xlsx 바이트.

원본: C:\dev\대량등록 마진계산기\app.py `/api/download` (1980~2026행).
tab='all' 이면 전체 시트, 특정 탭이면 그 시트만.
tab='detail_filtered' 는 프론트가 화면에서 필터한 행과 컬럼 순서를 그대로 받아 쓴다
(원본의 column_order reindex 를 재현 — 화면 순서 그대로 + 누락분 뒤에).

openpyxl 은 시트가 0개인 워크북을 읽지 못한다. 아무것도 안 써졌으면 '빈결과'
시트를 넣어 항상 유효한 워크북을 낸다.
"""
import io
from typing import Optional

import pandas as pd

# (payload 키, 시트명, tab 값). tab in ('all', <tab>) 이면 해당 시트를 쓴다.
_SHEETS = [
    ("matched", "전체매칭", "matched"),
    ("unmatched_buy", "마켓X_매입O", "unmatched_buy"),
    ("unmatched_sell", "마켓O_매입X", "unmatched_sell"),
    ("market", "마켓별", "market"),
    ("daily", "일별", "daily"),
    ("monthly", "월별", "monthly"),
    ("brand", "브랜드별", "brand"),
    ("priceRange", "금액대별", "priceRange"),
    ("product", "상품별", "product"),
]


def _write(writer, rows, sheet_name) -> bool:
    """rows(list[dict]) 를 sheet_name 시트로 기록. 뭔가 썼으면 True."""
    if not rows:
        return False
    pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
    return True


def to_xlsx(payload: dict, tab: str = "all",
            rows: Optional[list] = None,
            column_order: Optional[list] = None) -> bytes:
    """분석 결과 payload → xlsx 바이트.

    tab='all'       : 모든 시트 (전체매칭·마켓X_매입O·마켓O_매입X·요약·마켓별·일별·
                      월별·브랜드별·금액대별·상품별)
    tab='<name>'    : _SHEETS 의 해당 시트만. tab in ('all','summary') 은 요약 시트도 쓴다.
    tab='detail_filtered' : rows(화면 필터 결과) 를 column_order 순서로 '필터결과' 시트에.
    """
    output = io.BytesIO()
    wrote = False
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        if tab == "detail_filtered":
            df = pd.DataFrame(rows or [])
            if column_order and isinstance(column_order, list):
                # 원본 정책: ① column_order 에 있고 데이터에도 있는 컬럼 먼저(화면 순서)
                #            ② column_order 에 없는데 데이터엔 있는 컬럼 뒤에(데이터 손실 방지)
                ordered = [c for c in column_order if c in df.columns]
                extras = [c for c in df.columns if c not in ordered]
                df = df.reindex(columns=ordered + extras)
            df.to_excel(writer, sheet_name="필터결과", index=False)
            wrote = True
        else:
            for key, sheet_name, tab_key in _SHEETS:
                if tab in ("all", tab_key):
                    wrote |= _write(writer, payload.get(key), sheet_name)
            # 요약 — dict 를 항목/값 2열로 (원본은 1행 표였으나 세로가 읽기 쉽다)
            if tab in ("all", "summary"):
                summary = payload.get("summary") or {}
                if summary:
                    rows_ = [{"항목": k, "값": v} for k, v in summary.items()]
                    pd.DataFrame(rows_).to_excel(
                        writer, sheet_name="요약", index=False)
                    wrote = True

        if not wrote:
            # openpyxl 은 시트 0개 워크북을 못 읽는다 — 항상 유효한 워크북을 낸다.
            pd.DataFrame([{"결과": "데이터 없음"}]).to_excel(
                writer, sheet_name="빈결과", index=False)

    output.seek(0)
    return output.getvalue()
