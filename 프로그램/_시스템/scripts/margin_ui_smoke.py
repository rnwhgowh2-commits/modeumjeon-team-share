# -*- coding: utf-8 -*-
r"""실브라우저 검증용 — 마진 UI 전체 탭 렌더용 고정 결과 JSON 을 저장.

마켓 API(서버 IP 전용, 로컬 차단)는 이 화면과 무관하다. 이 스크립트는
분석 결과 payload 만 만들어 webapp/static/_margin_sample.json 에 떨군다.

1순위: 실데이터 — C:\dev\대량등록 마진계산기\데이터\260704 의 더망고+샵마인 엑셀을
        샵마인 경로로 분석(B.parse_buy → S.from_shopmine_excel → P.run → A.aggregate).
2순위(폴백): 실데이터가 없으면 합성 6행으로 동일한 payload 형태를 만든다.
        (손실행 / 계산불가행 / 고마진행 + 2개 이상 마켓 · 2개 이상 소싱처 키워드 포함)

어느 경로를 탔는지 print 로 남긴다.
"""
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lemouton.margin import aggregator as A  # noqa: E402
from lemouton.margin.config import DEFAULT_PRICE_RANGES  # noqa: E402

OUT_PATH = pathlib.Path("webapp/static/_margin_sample.json")
DATA_DIR = pathlib.Path(r"C:\dev\대량등록 마진계산기\데이터\260704")


def _build_from_real():
    """실 엑셀 → 매칭 파이프라인 결과. 파일이 없으면 예외를 던진다."""
    from lemouton.margin import buy_parser as B
    from lemouton.margin import pipeline as P
    from lemouton.margin import sell_source as S

    b = next(p for p in DATA_DIR.iterdir() if "더망고" in p.name)
    s = next(p for p in DATA_DIR.iterdir() if "샵마인" in p.name)
    out = P.run(
        B.parse_buy(b.read_bytes(), b.name),
        S.from_shopmine_excel(s.read_bytes(), s.name),
    )
    agg = A.aggregate(out["matched"], DEFAULT_PRICE_RANGES)
    counts = {
        "matched": len(out["matched"]),
        "unmatched_buy": len(out["unmatched_buy"]),
        "unmatched_sell": len(out["unmatched_sell"]),
        "settle_estimated": 0,
    }
    payload = {
        "analysis_id": 0,
        "counts": counts,
        "markets_failed": [],
        **out,
        **agg,
    }
    return payload, counts["matched"]


def _synthetic_rows():
    """렌더러가 읽는 실제 필드로 6행 구성.

    포함: 손실행(정산0·매입>0), 계산불가행(정산0·매입0), 고마진행(정산>0·매입0),
    정상행 다수, 마켓 2종 이상, 간단메모 소싱처 키워드 2종 이상(무신사/롯데).
    """
    def row(주문일, 마켓, 상품명, 브랜드, 상품코드, 판매가, 정산, 매입, 메모):
        return {
            "주문일": 주문일,
            "일자": "20" + 주문일 if len(주문일) == 8 else 주문일,
            "마켓": 마켓,
            "상품명": 상품명,
            "브랜드": 브랜드,
            "상품코드": 상품코드,
            "옵션_매출": "FREE",
            "옵션_매입": "FREE",
            "단가": 판매가,
            "판매가": 판매가,
            "정산예상금액": 정산,
            "구매가격": 매입,
            "순마진": (정산 - 매입) if 정산 > 0 else (-매입),
            "마진율": round(((정산 - 매입) / 판매가 * 100), 2) if 판매가 > 0 and 정산 > 0 else 0,
            "수량_매출": 1,
            "매칭타입": "정밀",
            "이상가": (매입 > 판매가 * 3 and 판매가 > 0) or 매입 > 500000,
            "데이터출처": "더망고+샵마인",
            "간단메모": 메모,
        }

    return [
        # 정상 (정산>0, 매입>0)
        row("26.07.01", "스마트스토어", "베이직 티셔츠", "무신사스탠다드", "P001",
            39000, 33000, 21000, "무신사 https://www.musinsa.com/goods/1 정상"),
        # 고마진 (정산>0, 매입0)
        row("26.07.02", "쿠팡", "프리미엄 니트", "르메르", "P002",
            128000, 110000, 0, "롯데 https://www.lotteon.com/p/2 매입미기입 고마진"),
        # 의심손실 (정산0, 매입>0)
        row("26.07.02", "스마트스토어", "가죽 벨트", "무신사스탠다드", "P003",
            25000, 0, 18000, "무신사 https://www.musinsa.com/goods/3 정산0"),
        # 계산불가 (정산0, 매입0)
        row("26.07.03", "쿠팡", "양말 세트", "기타", "P004",
            8000, 0, 0, "롯데 확인필요"),
        # 정상 (다른 마켓·브랜드)
        row("26.07.03", "11번가", "코튼 셔츠", "라코스테", "P005",
            72000, 60000, 41000, "무신사 https://www.musinsa.com/goods/5"),
        # 정상 (고가·다른 마켓)
        row("26.07.04", "롯데온", "울 코트", "산드로", "P006",
            240000, 205000, 150000, "롯데 https://www.lotteon.com/p/6"),
    ]


def _build_from_synthetic():
    rows = _synthetic_rows()
    agg = A.aggregate(rows, DEFAULT_PRICE_RANGES)
    counts = {
        "matched": len(rows),
        "unmatched_buy": 1,
        "unmatched_sell": 1,
        "settle_estimated": 0,
    }
    payload = {
        "analysis_id": 0,
        "counts": counts,
        "markets_failed": [],
        "matched": rows,
        "unmatched_buy": [{
            "주문일": "26.07.05", "마켓주문번호": "X-UB-1", "마켓명": "스마트스토어",
            "상품명": "미매칭 매입행(샘플)", "옵션": "FREE", "구매가격": 15000,
            "수령인": "홍길동", "수령인_2차매칭": "", "비고": "샵마인 미대응",
        }],
        "unmatched_sell": [{
            "주문일": "26.07.05", "마켓주문번호": "X-US-1", "쇼핑몰": "쿠팡",
            "상품명": "미매칭 매출행(샘플)", "옵션": "FREE", "단가": 12000,
            "정산예상금액": 10000, "수령인": "김철수", "수령인_2차매칭": "", "비고": "",
        }],
        "buy_missing": [],
        "settle_unknown": 0,
        "nan_coerced": 0,
        **agg,
    }
    return payload, counts["matched"]


def main():
    try:
        if not DATA_DIR.exists():
            raise FileNotFoundError(str(DATA_DIR))
        payload, matched = _build_from_real()
        path_used = "real"
    except Exception as e:  # noqa: BLE001 — 실데이터 없음/파싱 실패 → 합성 폴백
        payload, matched = _build_from_synthetic()
        path_used = "synthetic"
        print(f"[margin_ui_smoke] 실데이터 사용 불가 ({type(e).__name__}: {e}) → 합성 폴백")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    keys = sorted(payload.keys())
    print(f"[margin_ui_smoke] path={path_used} · wrote {OUT_PATH} · matched {matched}")
    print(f"[margin_ui_smoke] keys={keys}")


if __name__ == "__main__":
    main()
