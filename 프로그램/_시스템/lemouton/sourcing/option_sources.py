# -*- coding: utf-8 -*-
"""옵션 하나에 붙은 소싱처들 → **어디서 사오나 · 재고를 믿을 수 있나**.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md (4a)

━━ 왜 옮겼나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  이 판정들은 원래 `webapp/routes/api_pricing.py` 안에 있었다. 화면(매트릭스)만
  쓰던 동안엔 그래도 됐지만, 「마켓 전송」이 같은 판정을 해야 하는 순간
  **자기 판정을 새로 만들게** 된다 — 그럼 화면은 「품절·A소싱처」인데 전송은
  「있음·B소싱처」로 나간다. 이 저장소가 반복해서 겪은 원천 분열 그대로다.

  🔴 **로직은 한 글자도 안 바꿨다.** 라우트는 옛 이름으로 다시 내보내기만 한다.

━━ 여기 없는 것 (일부러) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  소싱처 셀을 **DB 에서 조립하는 부분**(카드할인 환원·최종매입가 캐시)은 아직
  라우트에 있다. 그쪽은 가격 표시와 얽혀 있어 따로 옮긴다.
  여기 있는 것은 **조립된 셀을 놓고 내리는 판정**뿐이다 — 판정이 갈리는 게
  훨씬 위험하기 때문에 이쪽을 먼저 뗐다.

  셀(dict)이 갖춰야 할 칸:
    site · crawled_price · crawled_stock · last_status ·
    match_failed · stock_uncollected · final_purchase_price(있으면)
"""
from lemouton.pricing.unified import is_crawl_valid
from lemouton.sourcing.stock_resolve import resolve_stock, stock_state


def effective_stock_status(d):
    """셀(소싱처 dict) → 재고 해석용 유효 status. crawled_stock=None 을 무엇으로 풀지 결정.

    [2026-07-05] 두 '재고 없음' 케이스를 상품 last_status='ok'(→'재고있음' ample)로
      둔갑시키지 않고 'uncollected'(→'확인 불가')로 확정:
        · stock_uncollected = 매칭됐으나 이 셀 per-size 재고 미수집
        · match_failed       = 소싱처가 안 파는 색×사이즈 조합(르무통 오렌지 260/270 유령재고)
      둘 다 실재고 근거 없음 → '재고있음' 금지(품절둔갑=금전위험). 그 외엔 상품 last_status.
    """
    # [2026-07-08] (다) 소멸 vs 이름불일치 구분:
    #   match_failed = 소싱처가 옵션 목록을 성공(ok) 크롤했는데 이 색×사이즈가 그 목록에 없음
    #     = 소싱처 미판매/소멸 → '품절'(not_sold). 크롤 실패·미크롤이면 목록이 최신이 아니라
    #     품절 둔갑 금지 → '확인 불가'(uncollected). (오버셀 아님 — 품절은 판매 제외·기회손실 방향)
    #   stock_uncollected = 매칭됐으나 이 셀 per-size 재고 미수집(애매) → '확인 불가'.
    if d.get('match_failed'):
        return 'not_sold' if d.get('last_status') == 'ok' else 'uncollected'
    if d.get('stock_uncollected'):
        return 'uncollected'
    return d.get('last_status')


def pick_cheapest_buyable(sources):
    """옵션의 소싱처들 중 "재고존재(품절X) + 크롤성공(error X) + 가격>0" 최저가.
       없으면 크롤성공+가격있는 것 중 최저(품절은 허용 — 실가격은 유효).
       그것도 없으면 None.
       winner(★최저)·원가의 단일 정의 — 품절/stale 소싱처가 원가로 잡히는 것 방지.

    [2026-06-05] 폴백도 is_crawl_valid 게이트를 통과해야 한다. 기존엔 폴백이
       `crawled_price` 만 봐서, 모든 소싱처가 크롤 실패(error)면 옛 가격(stale)이
       원가로 잡혀 잘못된 판매가가 계산되던 누수가 있었음. 품절(stock_out)은
       '실가격은 받았으나 재고 0'이라 폴백 후보로 허용하되, error 는 끝까지 배제.
    """
    buyable = [s for s in sources
               if is_crawl_valid(s.get('crawled_price'), s.get('last_status'))
               and not s.get('stock_out')]
    priced = buyable or [s for s in sources
                         if is_crawl_valid(s.get('crawled_price'), s.get('last_status'))]
    if not priced:
        return None
    # [2026-07-19] 최저가 판정 기준 = 최종매입가(혜택 차감 후). 실제로 지불하는 돈이
    #   원가이므로, 표면가가 싼 소싱처가 혜택 반영 후엔 더 비쌀 수 있다.
    #   프론트 셀의 대표 선택(_matrix_v3.html:5835 '완전B')과 동일 규칙 —
    #   최종매입가 있으면 그것, 없으면 표면가. (표시=업로드 단일 진실 원천)
    return min(priced, key=lambda x: (x.get('final_purchase_price')
                                      or x.get('crawled_price') or 9e15))


def decorate_stock(sources) -> None:
    """셀마다 재고 해석을 붙인다 — `stock_qty·stock_label·stock_out·stock_state`.

    [2026-06-03] 재고 의미 확정 — 화면 표시 단일 진실 원천.
      사이트별 센티넬(999·무신사 cap 10·상품합계 더미)을 백엔드에서 해석해
      stock_qty(실수량|None)·stock_label('품절'|'재고있음'|'N개')·stock_out 로 확정.
      프론트는 이 값만 렌더(가짜 '재고 10' 제거).

    🔴 `pick_cheapest_buyable` 보다 **먼저** 불러야 한다 — 그 함수가 `stock_out` 을
      보고 「살 수 있는 곳」을 가린다. 순서가 뒤바뀌면 품절인 곳이 원가로 잡힌다.
      (라우트도 같은 순서다: 재고 해석 → _attach_final_purchase → 픽)
    """
    for d in sources or []:
        eff = effective_stock_status(d)
        q, lbl, out = resolve_stock(d.get('site'), d.get('crawled_stock'), eff)
        d['stock_qty'] = q
        d['stock_label'] = lbl
        d['stock_out'] = out
        d['stock_state'] = stock_state(d.get('site'), d.get('crawled_stock'), eff)


# ── 마켓 전송이 쓰는 한 마디 ────────────────────────────────────────────

def sendable_for_option(sources) -> tuple[bool, int | None, str, dict | None]:
    """이 옵션의 재고를 마켓에 보내도 되나. `(보내도 되나, 수량, 사유, 고른 소싱처)`.

    화면이 「이 옵션은 A소싱처에서 사오고 재고는 N」이라고 말하는 것과 **같은 답**을
    내야 한다 — 그래서 화면이 쓰는 함수(`decorate_stock`·`pick_cheapest_buyable`)를
    그대로 부른다.

    🔴 고를 소싱처가 없으면 **막는다**. 「어디서 사오는지 모른다」는 곧 「재고를
      모른다」이고, 모르는 재고를 올리면 오버셀이다.
    """
    from lemouton.sourcing.stock_resolve import NOT_SURE_STATES

    if not sources:
        return (False, None, '이 옵션에 붙은 소싱처가 없습니다 — 재고를 알 길이 없습니다.',
                None)
    decorate_stock(sources)
    picked = pick_cheapest_buyable(sources)
    if picked is None:
        return (False, None,
                '살 수 있는 소싱처가 없습니다(전부 크롤 실패이거나 가격이 없습니다) — '
                '옛 가격으로 올리지 않습니다.', None)
    if picked.get('stock_state') in NOT_SURE_STATES:
        return (False, None,
                f'재고를 확인할 수 없습니다({picked.get("stock_label")}) — 있다고 '
                f'단정하지 않고 보내지 않습니다.', picked)
    return (True, picked.get('stock_qty'), '', picked)
