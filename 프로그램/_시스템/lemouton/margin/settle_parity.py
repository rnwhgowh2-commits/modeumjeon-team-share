# -*- coding: utf-8 -*-
"""정산 대조기 — 「우리가 받을 거라 계산한 돈」 vs 「마켓이 실제로 준 돈」.

🔴 왜 (2026-08-06 사장님 지적: "이걸 놓치면 엄청난 정산 금액 차이")
   정산예정금액 화면이 쓰는 금액은 **주문별 정산액**(쿠팡 매출내역 settlementAmount)이다.
   그런데 통장에 실제로 들어오는 돈은 정산 **회차**의 finalAmount 이고, 거기서
     전담택배비 · 판매자서비스이용료 · 정산차감 · 전주채권 · 쿠런티이용료 · 판매자할인쿠폰
   이 **더 빠진다**(쿠팡 지급내역조회 필드 정의). 즉 우리 화면 금액이 실제보다 클 수 있다.
   라이브 정산율 90~92%(수수료 6~18% 인데)가 이 자리를 가리킬 가능성이 크다.

★ 대조 축 = **매출인식일**. 회차의 [from, to] 구간에 주문의 recognitionDate 가 들면 그 회차 몫.
★ 「아직 안 준 돈」(SUBJECT)은 실지급에 넣지 않는다 — 넣으면 대조가 거짓이 된다.
  대신 미지급회차합으로 따로 보여준다(숨기지 않는다).
"""
from __future__ import annotations

#: 이 % 이상 벌어지면 「봐야 할 차이」로 본다(반올림·소액 차감은 걸러낸다)
GAP_WARN_PCT = 3.0


def compare(histories: list, ours: list) -> dict:
    """회차 목록 × 우리 주문 정산액 → 대조 결과.

    histories = fetch_settlement_histories() 결과
                [{type,status,settlementDate,from,to,finalAmount}]
    ours      = [{주문번호, _recognition_date, 정산액}]
    """
    done = [h for h in histories or [] if h.get("status") == "DONE"]
    subj = [h for h in histories or [] if h.get("status") != "DONE"]
    실지급 = sum(int(h.get("finalAmount") or 0) for h in done)
    미지급 = sum(int(h.get("finalAmount") or 0) for h in subj)

    # 회차 구간(전체)을 하나로 합쳐 「이 인식월에 속하는 주문」을 고른다
    spans = [(h["from"], h["to"]) for h in (histories or []) if h.get("from") and h.get("to")]
    안, 밖 = [], 0
    for o in ours or []:
        d = str(o.get("_recognition_date") or "")[:10]
        if d and any(f <= d <= t for f, t in spans):
            안.append(o)
        else:
            밖 += 1
    우리합 = sum(int(o.get("정산액") or 0) for o in 안)

    if not done or not 안:
        return {"판정": "대조불가", "실지급합": 실지급, "미지급회차합": 미지급,
                "우리계산합": 우리합, "대조건수": len(안), "구간밖건수": 밖,
                "차이": None, "차이율": None,
                "사유": ("지급완료 회차가 없음" if not done else "대조할 주문이 없음")}

    차이 = 우리합 - 실지급
    차이율 = round(abs(차이) / 우리합 * 100, 1) if 우리합 else None
    if 차이율 is not None and 차이율 < GAP_WARN_PCT:
        판정 = "정상"
    elif 차이 > 0:
        판정 = "우리가 더 큼"          # 화면 금액이 실제 입금보다 크다 = 자금계획 부풀림
    else:
        판정 = "우리가 더 작음"
    return {"판정": 판정, "실지급합": 실지급, "미지급회차합": 미지급,
            "우리계산합": 우리합, "대조건수": len(안), "구간밖건수": 밖,
            "차이": 차이, "차이율": 차이율,
            "차이후보": ("서비스이용료·정산차감·전주채권·쿠런티이용료·판매자할인쿠폰 등 "
                        "회차에서만 빠지는 항목(주문별 정산액엔 안 들어 있음)"
                        if 차이 > 0 else "회차에 다른 달 몫이 섞였거나 우리 저장분이 덜 찼을 수 있음")}
