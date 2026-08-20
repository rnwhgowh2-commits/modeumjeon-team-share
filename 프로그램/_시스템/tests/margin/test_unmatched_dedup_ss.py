# -*- coding: utf-8 -*-
"""스마트스토어 'A(B)' 주문이 matched·unmatched_buy 양쪽에 동시에 실리던 버그.

🔴 사장님 신고(2026-07-30): 스스 6건이 화면에서 계속 미매칭. 서버에서 실제 매칭을
  돌리면 6건 전부 매칭됐는데도 그랬다. 저장된 분석(84)을 열어 보니 **matched 에도 있고
  unmatched_buy 에도 있었다**(둘 다 true).

원인 — `_augment_blackspot` 의 중복 판정이 `마켓주문번호` **글자 그대로** 비교했다.
  · matched 행의 키 = 매칭에 쓴 키(괄호 안 '2026072829254311')
  · 더망고 원본의 키 = 'A(B)' 원형('2026072847520961(2026072829254311)')
  둘이 달라 "이미 매칭됨"을 못 알아채고 미매칭 목록에 또 넣었다.
  스마트스토어만 이 형태라 스스에서만 터졌다.

처방 — matcher 와 **같은 규칙**(order_match_keys)으로 후보키를 펴서 하나라도 겹치면 제외.
"""
from webapp.routes.api_margin import _order_keys_for_dedup


def test_smartstore_paren_keys_are_expanded():
    """스스 'A(B)' → A·B 둘 다 후보. matched 가 어느 쪽을 갖고 있어도 걸러진다."""
    keys = _order_keys_for_dedup("2026072847520961(2026072829254311)", "스마트스토어")
    assert "2026072847520961" in keys        # 괄호 밖
    assert "2026072829254311" in keys        # 괄호 안 — matched 가 갖는 키
    assert "2026072847520961(2026072829254311)" in keys   # 원본도 유지


def test_other_market_keeps_original_only():
    """다른 마켓은 괄호 형태가 아니므로 원본 키 하나면 충분하다."""
    keys = _order_keys_for_dedup("4463818179", "G마켓")
    assert keys == ["4463818179"]


def test_blank_is_empty():
    assert _order_keys_for_dedup("", "스마트스토어") == []
    assert _order_keys_for_dedup(None, "스마트스토어") == []


def test_matched_key_hits_dedup():
    """실사고 재현 — matched 가 괄호 안 키만 갖고 있어도 중복으로 잡아낸다."""
    existing = {"2026072829254311"}          # matched 에 실린 키
    mk = "2026072847520961(2026072829254311)"  # 더망고 원본
    keys = _order_keys_for_dedup(mk, "스마트스토어")
    assert any(k in existing for k in keys), "이미 매칭된 건인데 못 걸러냄"
