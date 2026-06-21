# -*- coding: utf-8 -*-
"""네이버페이 적립 혜택 네이밍 통일 + 롯데온 네이버페이 분류 이동 (멱등).

2026-06-12 사용자 요청:
  1) 르무통공홈(1)·스마트스토어(2)·SSF(4) 구매적립금(1%) → '네이버페이 적립금'
  2) 롯데온(5) 네이버페이: 후반영·추가 캐시백 → 후반영·결제 할인 (category 캐시백→None;
     이름 휴리스틱 _isPay 가 '네이버' 포함 → pay 그룹 → 네이버 동시 토글로 렌더)
  3) 네이버페이 적립 혜택 이름 '네이버페이 적립금' 으로 통일

계산 영향 없음: final_price 엔진은 category 미사용. 이름에 '적립' 추가돼도 _benefit_priority
상 우선순위 1(적립)로, 기존에도 첫 적용이라 순서·최종가 불변.

템플릿 + 스냅샷 override 둘 다 갱신. old_name 매칭이라 재실행 안전(멱등).

실행:  cd 프로그램/_시스템 && python scripts/migrate_naverpay_reward_naming.py
"""
from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import config  # noqa: F401
from shared.db import SessionLocal
from lemouton.sourcing.models import SourceBenefitTemplate, OptionBenefitOverride

NEW = "네이버페이 적립금"
# (source_id, old_names[], clear_category)
RULES = [
    (1, ["구매적립금 (네이버페이)"], False),
    (2, ["네이버 기본 적립"],        False),
    (4, ["구매적립금 (네이버페이)"], False),
    (5, ["네이버페이"],              True),   # 캐시백 → 결제할인(category None)
]


def _apply(rows, old_names, clear_category):
    n = 0
    for it in rows:
        nm = (it.benefit_name or "")
        hit = nm in old_names or nm == NEW  # NEW 도 포함(category 재보정 멱등)
        if not hit:
            continue
        changed = False
        if nm != NEW:
            it.benefit_name = NEW; changed = True
        if clear_category and getattr(it, "category", None) is not None:
            it.category = None; changed = True
        if changed:
            n += 1
    return n


def main():
    s = SessionLocal()
    try:
        total = 0
        for sid, old_names, clear_cat in RULES:
            tpls = s.query(SourceBenefitTemplate).filter_by(source_id=sid).all()
            ovrs = s.query(OptionBenefitOverride).filter_by(source_id=sid).all()
            nt = _apply(tpls, old_names, clear_cat)
            no = _apply(ovrs, old_names, clear_cat)
            total += nt + no
            print(f"  src={sid}: 템플릿 {nt}건, override {no}건 갱신 (old={old_names}, clear_cat={clear_cat})")
        s.commit()
        print(f"[완료] 총 {total}건 갱신.")
        # 결과 확인
        print("\n=== 결과 (src 1,2,4,5 의 '네이버페이 적립금') ===")
        for sid in (1, 2, 4, 5):
            for t in (s.query(SourceBenefitTemplate).filter_by(source_id=sid)
                      .order_by(SourceBenefitTemplate.sort_order).all()):
                if t.benefit_name == NEW:
                    print(f"  src={sid} tpl[{t.id}] name={t.benefit_name!r} cat={t.category!r} "
                          f"apply_mode={getattr(t,'apply_mode',None)!r} value={t.value}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
