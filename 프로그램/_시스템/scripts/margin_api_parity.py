# -*- coding: utf-8 -*-
"""골든 테스트 2단계 — 샵마인 엑셀 SellRow vs 마켓 API SellRow 필드별 대조표.

1단계(tests/margin/test_golden_regression.py)는 매출 소스를 샵마인 엑셀로 고정해
**이식 로직이 무손실인지** 증명했다. 2단계는 나머지 절반 —
**API 어댑터가 샵마인과 같은 값을 내는지** 를 본다.

여기서 드러날 것으로 예상되는 차이 (미리 알고 있는 것)
------------------------------------------------
· 롯데온 정산액 — 우리 API 는 이제 `실결제 − 실수수료`. 샵마인과 붙어야 정상.
  안 붙으면 조사 대상. (기존 order_export 는 수수료 미차감 = 마진 과대계상이었다)
· 쿠팡 정산액 — 미정산 건은 추정 베이스가 다르다(스펙 §4). 차이의 분포를 정량화한다.
  `_settle_source == "estimated"` 인 행만 모아 본다.
· 주문상태 어휘 — 전부 불일치가 정상. ②(블랙스팟)의 주문상태 통일 매핑표가 선행 의존.
  여기서는 카운트만 남긴다.

실행 위치 (중요)
--------------
마켓 API 는 **서버 IP 허용목록**에 묶여 있다(AWS 54.116.196.90).
로컬 PC 에서 실행하면 인증 이전에 IP 로 거부된다. 반드시 서버에서 실행할 것.

사용
----
    python scripts/margin_api_parity.py <샵마인엑셀경로> <since> <until>

    python scripts/margin_api_parity.py \\
        "/data/20260704_샵마인.xls" 2026-07-01 2026-07-09

출력
----
콘솔 요약 + `margin_parity_<since>_<until>.csv`
**차이를 덮지 않는다.** 불일치 상위 건은 판매처 셀러 어드민 화면과 육안 대조한다
(🔒 3대 원칙 — 실화면이 최종 심판).
"""
import datetime as _dt
import os
import pathlib
import sys

# `python scripts/margin_api_parity.py ...` 로 직접 실행해도 lemouton/shared 를 찾도록.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

KST = _dt.timezone(_dt.timedelta(hours=9))

COMPARE = ["정산예상금액_배송비포함", "단가", "실결제금액", "마켓수수료",
           "수량", "주문상태", "쇼핑몰"]


def main(shopmine_path: str, since_s: str, until_s: str) -> None:
    from lemouton.margin import sell_source as SS

    since = _dt.date.fromisoformat(since_s)
    until = _dt.date.fromisoformat(until_s)

    p = pathlib.Path(shopmine_path)
    sm = SS.from_shopmine_excel(p.read_bytes(), p.name)
    api = SS.from_api(_dt.datetime.combine(since, _dt.time.min, tzinfo=KST),
                      _dt.datetime.combine(until, _dt.time.max, tzinfo=KST))

    warnings = api.attrs.get("warnings", [])
    if warnings:
        print("⚠ 계정 조회 경고:")
        for w in warnings:
            print("   -", w)
        print()

    for df in (sm, api):
        df["_key"] = df["오픈마켓주문번호"].astype(str).str.strip()

    merged = sm.merge(api, on="_key", how="outer",
                      suffixes=("_샵마인", "_API"), indicator=True)

    only_sm = int((merged["_merge"] == "left_only").sum())
    only_api = int((merged["_merge"] == "right_only").sum())
    both = merged[merged["_merge"] == "both"].copy()

    print(f"주문번호 매칭: 양쪽={len(both)}  샵마인만={only_sm}  API만={only_api}")
    print(f"API 정산 real     : {(api['_settle_source'] == 'real').sum()}")
    print(f"API 정산 estimated: {(api['_settle_source'] == 'estimated').sum()}")
    print(f"API 정산 none     : {(api['_settle_source'] == 'none').sum()}\n")

    if only_sm:
        print(f"※ '샵마인만' {only_sm}건 — 조회 기간 여유일(PERIOD_MARGIN_DAYS=3)이 부족하거나")
        print("   해당 마켓이 API 미지원(옥션·G마켓)일 수 있다. 마켓별 분포를 확인할 것.\n")

    rows = []
    for field in COMPARE:
        a, b = f"{field}_샵마인", f"{field}_API"
        if a not in both or b not in both:
            continue
        diff = both[both[a].astype(str) != both[b].astype(str)]
        print(f"{field:24s} 불일치 {len(diff):5d} / {len(both)}")
        for _, r in diff.iterrows():
            rows.append({"주문번호": r["_key"], "필드": field,
                         "샵마인": r[a], "API": r[b],
                         "쇼핑몰": r.get("쇼핑몰_샵마인", ""),
                         "_settle_source": r.get("_settle_source_API", "")})

    out = pathlib.Path(f"margin_parity_{since_s}_{until_s}.csv")
    pd.DataFrame(rows).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n대조표 저장: {out}  ({len(rows)} 행)")

    if rows:
        d = pd.DataFrame(rows)
        print("\n=== 쇼핑몰 × 필드별 불일치 상위 ===")
        print(d.groupby(["쇼핑몰", "필드"]).size()
              .sort_values(ascending=False).head(15).to_string())

        settle = d[d["필드"] == "정산예상금액_배송비포함"].copy()
        if not settle.empty:
            settle["차이"] = (pd.to_numeric(settle["API"], errors="coerce")
                              - pd.to_numeric(settle["샵마인"], errors="coerce"))
            print("\n=== 정산액 차이 분포 (API − 샵마인) ===")
            print(settle.groupby(["쇼핑몰", "_settle_source"])["차이"]
                  .describe()[["count", "mean", "min", "max"]].to_string())

    print("\n다음 단계:")
    print("  1) 불일치를 쇼핑몰·필드별로 판정한다 —")
    print("     [우리 API 가 틀림] 어댑터 수정 후 재실행")
    print("     [샵마인이 틀림]   스펙에 기록, API 값을 정본으로")
    print("     [정의가 다름]     스펙에 정량화해 기록, 화면에 배지로 표면화")
    print("  2) 불일치 상위 5건 + 무작위 5건을 판매처 셀러 어드민 화면과 육안 대조한다.")
    print("  3) '샵마인만' 카운트가 0 에 수렴하는 최소 여유일을 찾아")
    print("     webapp/routes/api_margin.py 의 PERIOD_MARGIN_DAYS 를 갱신한다.")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
