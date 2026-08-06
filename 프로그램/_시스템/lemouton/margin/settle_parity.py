# -*- coding: utf-8 -*-
"""정산 대조기 — 「우리가 받을 거라 계산한 돈」 vs 「마켓이 인정한 정산대상액」.

🔴 왜 (2026-08-06 사장님 지적: "이걸 놓치면 엄청난 정산 금액 차이")
   정산예정금액 화면이 쓰는 금액은 **주문별 정산액**(쿠팡 매출내역 settlementAmount)이다.
   이게 마켓이 인정한 금액과 같은지 스스로 검산할 창구가 없었다.

🔴 대조 상대를 한 번 갈아탔다 (Wing 화면 실측 — 사장님이 상세를 열어 보내주심)
   처음엔 회차의 **finalAmount(통장 입금액)** 와 맞댔다 → 세소 6월이 861만(77%) 벌어졌다.
   원인은 우리 계산이 아니라 **빠른정산 선인출**이었다:

       정산대상액 11,081,786  ← 우리 계산 11,131,180 과 0.44% 차 (**우리가 맞았다**)
       지급액(30%) 3,324,536
       공제금액    3,023,780  ← 빠른정산 계좌인출액 2,916,626 + 서비스이용료 107,154
       최종지급액    300,756  ← 통장에 들어온 돈

   ⇒ 정확도는 **targetAmount** 로 재고, 빠른정산 선인출은 **따로 빼서** 보여준다.
     finalAmount 로 재면 「빠른정산 쓴 계정일수록 우리가 틀린 것처럼」 보인다.

★ 대조 축 = **매출인식일**. 회차의 [from, to] 구간에 주문의 recognitionDate 가 들면 그 회차 몫.
★ 주정산 70%(WEEKLY)와 최종액정산 30%(RESERVE)는 **같은 매출**이다 — 대상액을 다 더하면
  두 배가 된다. 그래서 겹치지 않는 회차만 골라 합친다(월 전체를 덮는 회차가 있으면 그것만).
★ 「아직 안 준 돈」(SUBJECT)은 실입금에 넣지 않는다 — 넣으면 대조가 거짓이 된다.
"""
from __future__ import annotations

#: 이 % 이상 벌어지면 「봐야 할 차이」로 본다(반올림·소액 차감은 걸러낸다)
GAP_WARN_PCT = 3.0


def _pick_non_overlapping(histories: list) -> list:
    """대상액을 이중으로 세지 않도록, 인식일 구간이 겹치지 않는 회차만 고른다.

    긴 구간부터 집는다 — 월 전체를 덮는 최종액정산(RESERVE)이 있으면 그 하나가
    그 달 매출 전부를 대표하므로 주정산 회차들은 자동으로 밀려난다.
    """
    cand = [h for h in histories or [] if h.get("targetAmount") is not None]
    cand.sort(key=lambda h: (h["from"] > h["to"], h["to"] < h["from"],
                             -(_span_days(h)), h["from"]))
    picked, covered = [], []
    for h in cand:
        if any(h["from"] <= t and f <= h["to"] for f, t in covered):
            continue                      # 이미 잡은 구간과 겹친다 = 같은 매출
        picked.append(h)
        covered.append((h["from"], h["to"]))
    return picked


def _span_days(h: dict) -> int:
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(h["to"]) - _dt.date.fromisoformat(h["from"])).days
    except (ValueError, KeyError, TypeError):
        return 0


def compare(histories: list, ours: list) -> dict:
    """회차 목록 × 우리 주문 정산액 → 대조 결과.

    histories = fetch_settlement_histories() 결과
    ours      = [{주문번호, _recognition_date, 정산액}]
    """
    hist = histories or []
    done = [h for h in hist if h.get("status") == "DONE"]
    실입금 = sum(int(h.get("finalAmount") or 0) for h in done)
    미지급 = sum(int(h.get("finalAmount") or 0) for h in hist if h.get("status") != "DONE")
    빠른정산 = sum(int(h.get("fastWithdrawn") or 0) for h in hist)
    수상한회차 = [h["settlementDate"] for h in hist if h.get("항등식맞음") is False
                   and h.get("targetAmount") is not None]

    대표 = _pick_non_overlapping(hist)
    마켓대상액 = sum(int(h["targetAmount"]) for h in 대표) if 대표 else None

    # 회차 구간(전체)을 하나로 합쳐 「이 인식월에 속하는 주문」을 고른다
    spans = [(h["from"], h["to"]) for h in hist if h.get("from") and h.get("to")]
    안, 밖 = [], 0
    for o in ours or []:
        d = str(o.get("_recognition_date") or "")[:10]
        if d and any(f <= d <= t for f, t in spans):
            안.append(o)
        else:
            밖 += 1
    우리합 = sum(int(o.get("정산액") or 0) for o in 안)

    out = {"실입금합": 실입금, "미지급회차합": 미지급, "빠른정산인출": 빠른정산,
           "마켓대상액": 마켓대상액, "우리계산합": 우리합,
           "대조건수": len(안), "구간밖건수": 밖, "수상한회차": 수상한회차,
           "차이": None, "차이율": None}

    if 마켓대상액 is None or not 안:
        out["판정"] = "대조불가"
        out["사유"] = ("마켓이 정산대상액을 안 줬다(옛 응답)" if 마켓대상액 is None
                       else "대조할 주문이 없다")
        return out

    차이 = 우리합 - 마켓대상액
    차이율 = round(abs(차이) / 마켓대상액 * 100, 1) if 마켓대상액 else None
    out["차이"], out["차이율"] = 차이, 차이율
    if 차이율 is not None and 차이율 < GAP_WARN_PCT:
        out["판정"] = "정상"
    elif 차이 > 0:
        out["판정"] = "우리가 더 큼"      # 화면 금액이 마켓 인정액보다 크다 = 자금계획 부풀림
    else:
        out["판정"] = "우리가 더 작음"
    out["차이후보"] = ("우리 저장분에 취소·반품이 덜 반영됐거나, 회차가 그 달 매출을 "
                       "다 덮지 못했을 수 있다" if 차이 > 0 else
                       "우리 저장분이 덜 찼거나 회차에 다른 달 몫이 섞였을 수 있다")
    return out
