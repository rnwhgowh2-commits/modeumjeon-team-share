"""더망고 매입 엑셀 → 주문 라인(`line_uid`) 붙이기.

설계서 `docs/superpowers/specs/2026-08-06-실매입가-주문통합-design.md` §5.2.

## 왜 얇은 어댑터인가

매칭 규칙(키 만들기 3종 + 3단계)은 **마진 계산기의 것을 그대로 쓴다**
(`margin.matcher.order_match_keys` · `extract_product_code` · `normalize_option`).
그런데 `matcher.match_data` 는 매출 쪽을 **샵마인 DataFrame** 으로 받아 결과 행에
`line_uid` 를 안 싣는다. 실매입가는 **주문 라인 1줄**에 붙여야 하므로 그 식별자가
반드시 필요하다.

그래서 `match_data` 를 고치지 않는다 — 마진 계산기 동작 불변이 최우선이다(사장님 규칙 1).
대신 **같은 키 함수를 불러** 주문 적재 행(`_line_uid` 를 들고 있다)에 직접 붙이는
얇은 어댑터를 여기 따로 둔다.

## 「하나로 못 좁히면 저장하지 않는다」

`match_data` 는 후보가 여럿이면 첫 행을 고른다(집계용이라 그래도 된다). 여기서는
**돈을 특정 주문 줄에 적는 일**이라 그러면 안 된다 — 엉뚱한 줄에 매입가가 붙으면
그 줄의 마진이 통째로 거짓이 된다. 후보가 2건 이상이면 `ambiguous` 로 돌려주고
저장하지 않는다(화면이 목록으로 보여 준다).

## 못 붙은 행은 버리지 않는다

`unmatched` 로 전부 돌려준다. 조용히 사라지면 사장님은 「올렸는데 왜 없지」를 겪는다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 매입가 0 = 「입력 안 함」. buy_parser 가 미입력 센티널(999999999.99)을 0 으로 바꾸므로
# 여기서 0 을 저장하면 「0원에 샀다」는 거짓이 된다.
_SKIP_ZERO_REASON = "구매가격이 비어 있어요(미입력)"


def _sell_order_key(v) -> str:
    """주문 행의 주문번호 정규화 — matcher._sell_order_key 와 같은 규약('.0' 꼬리 제거)."""
    if v is None:
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def order_lines_for_matching(rows) -> list:
    """주문 적재 행 → 매칭 대상. 클레임 행 제외 + 같은 라인은 최신 관측 1건만.

    · 클레임(`_kind='change'`)은 취소·반품 이력이라 매입가를 붙일 대상이 아니다.
    · 같은 `_line_uid` 가 여러 행으로 남아 있을 수 있다(저장 키가 시절마다 달랐던 주문).
      `margin.sell_source._one_row_per_line` 과 같은 기준 — **마켓이 가장 최근에 알려준 행**
      (`_seen_at`)을 고른다. 상태 이름으로 서열을 매기지 않는다(마켓마다 용어가 다르다).
    """
    picked: dict = {}
    for r in rows or []:
        r = r or {}
        if str(r.get("_kind") or "") == "change":
            continue
        uid = str(r.get("_line_uid") or "").strip()
        if not uid:
            continue                        # 식별자 없는 행엔 매입가를 붙일 수 없다
        seen = str(r.get("_seen_at") or "")
        prev = picked.get(uid)
        if prev is None or seen > prev[0]:
            picked[uid] = (seen, r)
    return [r for _s, r in picked.values()]


def _buy_summary(rec: dict, reason: str = "") -> dict:
    """못 붙은/애매한 행을 화면에 보여줄 요약. 원문 그대로만 담는다(지어내기 없음)."""
    out = {
        "행번호": rec.get("행번호"),
        "마켓주문일자": rec.get("마켓주문일자", ""),
        "마켓명": rec.get("마켓명", ""),
        "마켓주문번호": rec.get("마켓주문번호", ""),
        "수령인명": rec.get("수령인명", ""),
        "마켓상품명": rec.get("마켓상품명", ""),
        "옵션1": rec.get("옵션1", ""),
        "구매가격": rec.get("구매가격", 0),
    }
    if reason:
        out["사유"] = reason
    return out


def _buy_records(buy_df) -> list:
    """더망고 DF → 매칭용 레코드. 키 3종은 matcher 함수를 그대로 부른다."""
    from lemouton.margin.matcher import (extract_product_code, normalize_option,
                                         order_match_keys)

    out = []
    for i, (_idx, br) in enumerate(buy_df.iterrows()):
        market = str(br.get("마켓명", "") or "")
        rec = {
            # 엑셀 1행은 머리글 → 데이터 첫 줄이 2행. 사장님이 엑셀에서 찾을 수 있는 번호.
            "행번호": i + 2,
            "마켓주문일자": str(br.get("마켓주문일자", "") or ""),
            "마켓명": market,
            "마켓주문번호": str(br.get("마켓주문번호", "") or ""),
            "수령인명": str(br.get("수령인명", "") or ""),
            "마켓상품명": str(br.get("마켓상품명", "") or ""),
            "옵션1": str(br.get("옵션1", "") or ""),
            "구매가격": _num(br.get("구매가격", 0)),
            "_order_keys": order_match_keys(br.get("마켓주문번호"), market),
            "_product_code": extract_product_code(br.get("마켓상품명")),
            "_option_norm": normalize_option(br.get("옵션1")),
        }
        out.append(rec)
    return out


def _num(v) -> int:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


def order_keys_from_buy(buy_df) -> list:
    """엑셀이 말하는 주문번호 후보 전부(스마트스토어 `A(B)` 는 A·B 둘 다).

    `order_store.load(order_nos=...)` 로 **그 주문만** 인덱스로 읽기 위한 목록이다.
    """
    out, seen = [], set()
    for rec in _buy_records(buy_df):
        for k in rec["_order_keys"]:
            if k and k not in seen:
                seen.add(k)
                out.append(k)
    return out


def match_to_lines(buy_df, order_rows) -> dict:
    """더망고 매입 행 ↔ 주문 라인 3단계 매칭.

    Returns:
        {
          "matched":   [{"line_uid", "price", "match_type", "buy": {...}}, ...],
          "unmatched": [{...행 요약, "사유"}, ...],
          "ambiguous": [{...행 요약, "사유", "후보": [line_uid, ...]}, ...],
        }
    """
    from collections import defaultdict

    from lemouton.margin.matcher import extract_product_code, normalize_option

    sells = []
    for r in order_lines_for_matching(order_rows):
        sells.append({
            "line_uid": str(r.get("_line_uid") or "").strip(),
            "_order_key": _sell_order_key(r.get("오픈마켓주문번호")),
            "_product_code": extract_product_code(r.get("상품명")),
            "_option_norm": normalize_option(r.get("옵션")),
        })

    # 🔴 [issue #1139] order_key 별로 미리 묶어 둔다. 아래 3단계 predicate 는
    #    전부 "s['_order_key'] in b['_order_keys']" 를 공통으로 깔고 있었는데,
    #    이걸 매입행마다 매출행 전체(sells)를 선형 재스캔해서 걸렀다 —
    #    3단계 × 매입행 × 매출행이라 3,900+행에서 O(n²)로 느려진다.
    #    order_key 로 미리 나눠 두면 각 매입행은 "그 주문의 라인 수"만큼만
    #    보면 되고, 이 값은 보통 1~몇 개로 늘 작다(주문번호 자체가 유일 키는
    #    아니라 여러 줄일 수 있다 — 그래서 다음 단계로 product_code·option 으로
    #    더 좁힌다). 매칭 결과·정밀도는 원래 알고리즘과 동일, 순서만 다르다.
    by_order_key = defaultdict(list)
    for s in sells:
        if s["_order_key"]:
            by_order_key[s["_order_key"]].append(s)

    buys = _buy_records(buy_df)
    matched, unmatched, ambiguous = [], [], []
    used_sell = set()
    pending = list(range(len(buys)))

    # matcher.match_data 와 같은 3단계 — 좁은 조건부터.
    # order_key 일치는 위 버킷팅으로 이미 보장되므로 여기선 나머지 조건만 본다.
    stages = (
        ("정밀", lambda b, s: (s["_product_code"] == b["_product_code"]
                               and s["_option_norm"] == b["_option_norm"])),
        ("기본", lambda b, s: s["_product_code"] == b["_product_code"]),
        ("주문번호", lambda b, s: True),
    )

    for match_type, pred in stages:
        still = []
        for bi in pending:
            b = buys[bi]
            if not b["_order_keys"]:
                still.append(bi)
                continue
            seen_uid = set()
            cands = []
            for k in b["_order_keys"]:
                for s in by_order_key.get(k, ()):
                    uid = s["line_uid"]
                    if uid in used_sell or uid in seen_uid:
                        continue
                    if pred(b, s):
                        seen_uid.add(uid)
                        cands.append(s)
            if not cands:
                still.append(bi)
                continue
            if len(cands) > 1:
                # 🔴 하나로 못 좁혔다 → 저장하지 않는다(엉뚱한 줄에 돈을 적으면 안 된다).
                #    더 넓은 다음 단계로 내려가도 후보가 늘 뿐이라 여기서 끝낸다.
                ambiguous.append(dict(_buy_summary(
                    b, f"주문 줄 후보가 {len(cands)}개라 어느 줄인지 못 정했어요"
                       f"({match_type} 단계)"),
                    후보=[c["line_uid"] for c in cands[:10]]))
                continue
            s = cands[0]
            used_sell.add(s["line_uid"])
            matched.append({"line_uid": s["line_uid"], "price": b["구매가격"],
                            "match_type": match_type, "buy": _buy_summary(b)})
        pending = still

    for bi in pending:
        b = buys[bi]
        reason = ("마켓주문번호가 비어 있어요" if not b["_order_keys"]
                  else "이 주문번호로 저장된 주문 줄을 못 찾았어요")
        unmatched.append(_buy_summary(b, reason))

    logger.info("더망고 매입 매칭: matched=%d unmatched=%d ambiguous=%d",
                len(matched), len(unmatched), len(ambiguous))
    return {"matched": matched, "unmatched": unmatched, "ambiguous": ambiguous}


# [issue #1139] 한 트랜잭션에 몇 줄까지 모아 커밋할지. 전부 한 번에(무제한)는
# 실패 시 되돌릴 범위가 너무 커지고, 행마다(1)는 원래 버그 그대로다 — 적당히
# 큰 상수로 끊어서 "원격 왕복 수" 와 "실패 시 잃는 범위"를 같이 줄인다.
_COMMIT_CHUNK = 200


def apply(session, buy_df, order_rows, *, filename: str = "", input_by=None,
          reason=None) -> dict:
    """매칭 → `order_line_purchases` 저장. 매칭 결과를 그대로 되돌려준다.

    · 구매가격 0(미입력 센티널 포함)은 **저장하지 않고** `skipped_zero` 로 드러낸다.
    · 못 붙은 행·애매한 행은 버리지 않고 응답에 담는다.
    · `reason` 은 변경 이력에 남길 경로 이름(기본 `mango`). 마진 계산기 쪽 업로드는
      `margin` 을 넘겨 「어느 화면에서 올린 엑셀이 덮어썼나」를 나중에 알 수 있게 한다.

    🔴 [issue #1139] 대용량 매입 엑셀(3,900+행) 업로드가 Cloudflare 524(타임아웃)로
      죽었다 — 매칭된 행마다 `upsert`(커밋 1~2번 + `session.get()` 조회 1번)를 불러
      원격 DB(Supabase) 왕복이 수천 번 쌓인 게 정체였다. 여기서 두 가지로 줄인다:
      ① `get_many` 로 대상 line_uid 를 **한 번에** 읽어 `_existing` 맵을 만들고
         `upsert` 에 넘긴다 — 있던 행이든 새 행이든 이후 개별 `session.get()` 조회가
         통째로 사라진다(맵에 없으면 새 행이라는 뜻 — `get_many` 가 그 uid 목록
         전체를 이미 조회했으므로 확실하다).
      ② `commit=False` 로 넘기고 `_COMMIT_CHUNK` 줄마다 한 번씩만 커밋·플러시한다
         (행마다 왕복하지 않되, 실패해도 그 청크만 날아가게 범위를 제한한다).
    """
    from lemouton.markets import purchase_price as _pp

    res = match_to_lines(buy_df, order_rows)
    to_save = [m for m in res["matched"] if m["price"]]
    skipped_zero = [dict(m["buy"], 사유=_SKIP_ZERO_REASON)
                    for m in res["matched"] if not m["price"]]

    existing = (_pp.get_many(session, [m["line_uid"] for m in to_save])
                if to_save else {})

    saved = 0
    for i, m in enumerate(to_save):
        ref = f"{filename}#{m['buy'].get('행번호')}"[:255] if filename else None
        is_chunk_end = (i + 1) % _COMMIT_CHUNK == 0 or i == len(to_save) - 1
        _pp.upsert(session, line_uid=m["line_uid"], price=m["price"],
                   source=_pp.SOURCE_MANGO, mango_ref=ref, input_by=input_by,
                   reason=(reason or _pp.SOURCE_MANGO), commit=is_chunk_end,
                   _existing=existing)
        saved += 1
    return {
        "matched": len(res["matched"]),
        "saved": saved,
        "skipped_zero": skipped_zero,
        "unmatched": res["unmatched"],
        "ambiguous": res["ambiguous"],
        "lines": res["matched"],
    }
