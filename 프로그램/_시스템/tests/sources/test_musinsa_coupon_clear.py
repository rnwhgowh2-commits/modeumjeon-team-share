# -*- coding: utf-8 -*-
"""[TEST] 무신사 상품쿠폰이 사라지면 저장된 dynamic_benefits_json 에서도 지워져야 한다.

배경(라이브 실측 2026-07-20):
  「르무통 상반기 결산 10% 상품쿠폰」이 무신사 상품 페이지에서 사라져 「사용가능 쿠폰
  없음」이 됐는데, 매입가 계산은 여전히 12,980원을 차감하고 있었다. 크롬 확장으로
  실제 전송 데이터를 확인하니 크롤 자체는 정상 — price 119900, surface_price 119900,
  product_coupon_list: [] 를 보냈다. 문제는 저장(save) 쪽: SourceProduct.dynamic_benefits_json
  에 옛 쿠폰이 남아 있으면, 빈 리스트가 와도 지우지 않고 그대로 둔다.

  없어진 쿠폰이 계속 차감되면 매입가를 실제보다 싸게(=마진이 더 큰 것처럼) 보게 되고,
  그 잘못된 매입가로 판매가를 잡으면 실제로는 마진이 없거나 손해인 채로 팔게 된다.
  반대로 방치하면 "가짜로 싸 보이는 매입가"가 영원히 고정되어 재크롤을 아무리 돌려도
  고쳐지지 않는다(옛 값이 새 값을 계속 이긴다).

  webapp/routes/api_pricing.py 의 동일 블록(약 1755~1762 행)은 else 로 빈 리스트를
  pop 해서 이미 정상 동작한다. lemouton/sources/service.py::save_crawl_result 의
  같은 블록만 else 가 없었다 — 저장 경로에 따라 결과가 갈리면 안 되므로 여기도 맞췄다.

  ★ 실측(TDD) 정직 기록 — 이 테스트는 else 추가 전에도 이미 통과한다(고쳐도
    결과가 안 바뀜). save_crawl_result 는 호출마다 `_dyn = {}` 로 새로 만들어
    SourceProduct.dynamic_benefits_json 전체를 통째로 덮어쓴다(옛 값과 병합하지
    않음) — 그래서 빈 리스트면 애초에 키 자체가 안 생겨, pop 을 명시해도 안 해도
    최종 JSON 은 같다. 즉 이 특정 함수만 놓고 보면 else 유무가 "지금 당장" 관측
    가능한 차이를 안 만든다. 그래도 else 를 추가한 이유: (1) api_pricing.py 의
    같은 블록과 항상 대칭을 유지해야 나중에 한쪽만 '옛값과 병합' 방식으로 리팩터돼도
    조용히 갈라지지 않는다, (2) 라이브에서 실제로 관측된 옛 쿠폰 잔존은 이 함수가
    아닌 다른 경로(멀티 SourceProduct 행 중 최적값 선택 로직 등 — 상세는 커밋
    메시지·PART 2 조사 참고)에서 발생했을 가능성이 높다. 아래 두 번째 테스트가
    '왜 이 함수에서는 실패 재현이 안 되는지'를 명시적으로 증명해 둔다(회귀 감시용).
"""
import json

from lemouton.sources.models import SourceProduct
from lemouton.sources.service import save_crawl_result
from lemouton.sourcing.crawlers.base import CrawlResult


def _sp_with_stale_coupon(db):
    """옛 쿠폰(12,980원)이 이미 저장돼 있는 SourceProduct — 재현 대상 상태."""
    stale = {
        "product_coupon_list": [{"name": "르무통 상반기 결산 10% 상품쿠폰", "amount": 12980}],
        "surface_price": 129890,
        "coupon_amount": 12980,
    }
    sp = SourceProduct(
        site="musinsa",
        url="https://www.musinsa.com/products/1234567",
        product_name="테스트 상품",
        dynamic_benefits_json=json.dumps(stale, ensure_ascii=False),
    )
    db.add(sp)
    db.flush()
    return sp


def _crawl_result_no_coupon():
    """실측대로 — 크롤은 이제 상품쿠폰 없이 정상 값을 보낸다."""
    option = {
        "color_text": None,
        "size_text": None,
        "sale_price": 119900,
        "price": 119900,
        "stock": 5,
        # ★ product_coupon_list 는 옵션(item) 레벨 키 — service.py 가 _o.get(...) 로
        #   직접 읽는다(breakdown dict 안이 아님). api_pricing.py 의 it.get(...) 과 대칭.
        "product_coupon_list": [],
        "breakdown": {
            "grade_reward_amount": 4830,
            "money_reward_amount": 4420,
            "grade_discount": 0,
            "coupon": 0,
        },
    }
    return CrawlResult(
        source="musinsa",
        product_url="https://www.musinsa.com/products/1234567",
        product_name_raw="테스트 상품",
        options=[option],
    )


def test_empty_coupon_list_clears_stale_stored_coupon(db):
    """★ 핵심 재현 — 빈 product_coupon_list 로 재크롤하면 옛 쿠폰이 지워져야 한다.

    수정 전에는 else 가 없어 옛 쿠폰(12,980원)이 그대로 남아 매입가가 실제보다
    12,980원 싸게(=거짓으로 마진 좋게) 계산된다.
    """
    sp = _sp_with_stale_coupon(db)
    save_crawl_result(db, source_product=sp, crawl_result=_crawl_result_no_coupon())

    dyn = json.loads(sp.dynamic_benefits_json) if sp.dynamic_benefits_json else {}
    assert dyn.get("product_coupon_list") in (None, []), (
        f"옛 쿠폰이 그대로 남아 있음: {dyn.get('product_coupon_list')!r} "
        "— 없어진 쿠폰이 계속 차감되면 매입가가 실제보다 싸게 보인다"
    )
    # 다른 필드(표면가·등급적립 등)는 이번 크롤 값으로 정상 갱신됐는지도 같이 확인
    # — 쿠폰만 지우고 나머지를 건드리면 안 된다(부분 갱신 사고 방지).
    assert dyn.get("surface_price") == 119900
    assert dyn.get("grade_reward_amount") == 4830


def test_dyn_is_rebuilt_not_merged_so_missing_key_already_equals_popped(db):
    """[특성 기록] save_crawl_result 는 dynamic_benefits_json 을 매번 통째로 새로 만든다.

    위 핵심 테스트가 '고쳐도 안 고쳐도 통과'하는 이유를 명시적으로 남겨 둔다: 이 함수는
    옛 저장값을 읽어 병합(`_dyn = json.loads(existing)`)하지 않고 `_dyn = {}` 로 시작해
    이번 크롤 결과만으로 dynamic_benefits_json 전체를 교체한다. 그래서 product_coupon_list
    가 비어 있으면 '키를 pop 한다'와 '애초에 키를 안 넣는다'가 최종 JSON 상 구별 불가능하다.

    ⚠️ 이 특성이 바뀌면(예: 다른 세션이 이 함수를 api_pricing.py 처럼 '옛값 병합' 방식으로
    리팩터하면) else 분기가 그때부터 진짜로 의미를 갖게 되고, 이 테스트는 깨진다 —
    그게 신호다. 그때는 else 를 반드시 유지해야 한다(안 그러면 이 파일 상단에 적은
    실제 사고 — 없어진 쿠폰이 영원히 차감 — 가 재발한다).
    """
    sp = _sp_with_stale_coupon(db)
    before = json.loads(sp.dynamic_benefits_json)
    assert before.get("product_coupon_list")  # 사전조건 — 옛 쿠폰이 실제로 있었음

    save_crawl_result(db, source_product=sp, crawl_result=_crawl_result_no_coupon())

    after = json.loads(sp.dynamic_benefits_json)
    # dynamic_benefits_json 전체가 이번 크롤 결과로 교체됐다 — 옛 키(coupon_amount 등)가
    # 이번 크롤이 채우지 않은 채로 남아있지 않아야 한다(부분 병합이 아니라 전량 교체 증거).
    assert "coupon_amount" not in after or after.get("coupon_amount") in (0, None)
