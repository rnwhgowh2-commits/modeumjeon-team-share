"""소싱처 정답 카드의 재고 규칙(stock_rules) 시드 — 멱등.

각 소싱처가 실제로 쓰는 ① 품절 마커 ② 한정수량 표기 ③ 표식없음 처리를
SourceRegistry.crawl_guide.fields.option_stock.stock_rules 에 기록한다.
(크롤러 런타임 동작은 이미 코드에 있음 — 이 시드는 가이드 카드/체크리스트가
"이 소싱처는 이렇게 재고를 읽는다"를 정답으로 보여주기 위한 문서 데이터.)

실행:
    # 개발(Supabase): DATABASE_URL 환경변수 설정 후
    set DATABASE_URL=postgresql://...        (Windows cmd)
    $env:DATABASE_URL="postgresql://..."     (PowerShell)
    python -m scripts.seed_stock_rules

소싱처 이름(부분일치)로 매칭. 이미 값이 있어도 항상 최신 규칙으로 덮어쓴다(멱등).
"""
from __future__ import annotations

import sys

# 소싱처 이름 부분일치 → 재고 규칙.  (name 소문자 비교, 키워드 any 매칭)
RULES = [
    (("무신사", "musinsa"), {
        "soldout_markers": ["품절", "재입고 알림"],
        "qty_patterns": ["잔여 N개", "N개 남음", "마지막 N개"],
        "no_marker_means": "in_stock",
    }),
    (("ssf", "ssf샵"), {
        "soldout_markers": ["품절", "statcd=SLDOUT"],
        "qty_patterns": ["품절임박 (N)"],
        "no_marker_means": "in_stock",
    }),
    (("ssg",), {
        "soldout_markers": ["usablInvQty=0"],
        "qty_patterns": ["usablInvQty=N (가용재고 정수)"],
        "no_marker_means": "in_stock",
    }),
    (("르무통", "lemouton", "스스"), {  # 르무통 공홈 + 스스 르무통(스마트스토어)
        "soldout_markers": ["is_selling=F", "stock_number=0"],
        "qty_patterns": ["stock_number=N (실재고 정수)"],
        "no_marker_means": "in_stock",
    }),
    (("롯데", "lotte"), {  # 롯데온·롯데홈쇼핑·롯데아이몰 — 수량 미제공
        "soldout_markers": ["disabled", "품절", "li.soldout"],
        "qty_patterns": [],
        "no_marker_means": "unknown",  # 수량을 안 주는 사이트 → '수량 미상'
    }),
]


def _match(name: str, keywords) -> bool:
    n = (name or "").lower()
    return any(k.lower() in n for k in keywords)


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_pricing import SourceRegistry
    from lemouton.sourcing import crawl_guide as cg

    s = SessionLocal()
    try:
        rows = s.query(SourceRegistry).all()
        if not rows:
            print("SourceRegistry 행이 없습니다 — DATABASE_URL 이 올바른지 확인하세요.")
            return 2
        updated = 0
        for src in rows:
            rule = next((r for kws, r in RULES if _match(src.name, kws)), None)
            if rule is None:
                print(f"  · {src.name}: 규칙 매칭 없음 — 건너뜀")
                continue
            guide = cg.loads(src.crawl_guide)
            guide.setdefault("fields", {}).setdefault("option_stock", {})
            guide["fields"]["option_stock"]["stock_rules"] = dict(rule)
            src.crawl_guide = cg.dumps(guide)   # validate 통과
            updated += 1
            print(f"  ✓ {src.name}: soldout={rule['soldout_markers']} / "
                  f"qty={rule['qty_patterns']} / no_marker={rule['no_marker_means']}")
        s.commit()
        print(f"\n완료 — {updated}개 소싱처 stock_rules 시드(멱등).")
        return 0
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())
