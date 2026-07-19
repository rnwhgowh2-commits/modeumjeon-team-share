"""크롤 대상 중복 제거 — 같은 소싱처의 같은 상품은 한 랩에 한 번만 긁는다.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §2-2

━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  한 상품이 같은 소싱처의 **여러 URL 구성**에 걸칠 수 있다.

    무신사 > 나이키    ▸ 덩크 로우 팬다   ┐  같은 소싱처 · 같은 상품
    무신사 > 스니커즈  ▸ 덩크 로우 팬다   ┘  → 한 랩에 두 번 크롤 (낭비)

    SSG   > 나이키    ▸ 덩크 로우 팬다      다른 소싱처 → 그대로 둔다

  사장님 확정: "소싱처에서 같은 상품 URL은 수집되지 않도록. 타 소싱처에서의 동일 상품은 괜찮음."
  타 소싱처는 **가격·혜택·재고가 다르므로 각각 필요**하다.

━━ 안전 규칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  상품 id 를 **모르면 합치지 않는다.** id 없는 것들을 한 덩어리로 접으면
  서로 다른 상품이 조용히 사라진다. 중복 크롤은 낭비일 뿐이지만, 잘못 합치면 **누락**이다.
  낭비보다 누락이 훨씬 비싸다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CrawlTarget:
    """크롤 후보 1건. 어느 구성에서 왔는지까지 들고 다닌다."""

    source_key: str            # 소싱처 (SourceProduct.site)
    product_id: str | None     # 소싱처 상품 id (SourceProduct.external_product_id)
    weight: float = 1.0        # 계수
    composition: str = ""      # 어느 URL 구성에서 왔나 (소싱처 > 브랜드)
    ref: object = None         # 원본 객체 (실제 크롤에 필요)


@dataclass(frozen=True)
class DedupedTarget:
    """합쳐진 크롤 대상. 계수는 가장 높은 것, 출처는 전부 보관."""

    source_key: str
    product_id: str | None
    weight: float
    compositions: tuple = field(default_factory=tuple)
    ref: object = None

    @property
    def merged_count(self) -> int:
        """몇 개 구성에서 합쳐졌나. 1 이면 중복이 없던 것."""
        return len(self.compositions)


def _norm_source(v) -> str:
    """소싱처 키는 대소문자를 접는다 — 'MUSINSA' 와 'musinsa' 는 같은 곳."""
    return (v or "").strip().lower()


def _norm_pid(v):
    """상품 id 는 앞뒤 공백만 정리한다.

    **대소문자는 접지 않는다** — 소싱처 상품코드는 대소문자가 의미를 가질 수 있다.
    비었으면 None(= 모름) 으로 본다.
    """
    s = (v or "").strip()
    return s or None


def dedupe_targets(targets) -> list:
    """같은 (소싱처, 상품id) 를 한 건으로 합친다. 계수는 높은 쪽.

    - 상품 id 가 없으면(None·빈문자) **합치지 않는다** — 각각 따로 남긴다.
    - 소싱처가 다르면 합치지 않는다.
    - 순서는 **처음 나온 자리**를 지킨다.
    - `compositions` 에 출처를 전부 남긴다 — 통계는 원래 구성마다 기록해야
      어느 구성이 바쁜지 알 수 있다.
    """
    merged: dict = {}
    order: list = []
    passthrough: list = []   # id 를 몰라 합칠 수 없는 것들 (자리 표시용 placeholder 포함)

    for t in targets:
        pid = _norm_pid(t.product_id)
        if pid is None:
            # 모르면 합치지 않는다. 순서 유지를 위해 자리만 잡아 둔다.
            key = ("__unknown__", len(passthrough))
            order.append(key)
            passthrough.append(
                DedupedTarget(source_key=t.source_key, product_id=None,
                              weight=t.weight,
                              compositions=(t.composition,) if t.composition else (),
                              ref=t.ref))
            merged[key] = passthrough[-1]
            continue

        key = (_norm_source(t.source_key), pid)
        prev = merged.get(key)
        if prev is None:
            order.append(key)
            merged[key] = DedupedTarget(
                source_key=t.source_key, product_id=pid, weight=t.weight,
                compositions=(t.composition,) if t.composition else (),
                ref=t.ref)
            continue

        # 이미 있다 → 계수는 높은 쪽, 원본도 높은 쪽 것을 쓴다.
        take_new = t.weight > prev.weight
        comps = prev.compositions + ((t.composition,) if t.composition else ())
        merged[key] = DedupedTarget(
            source_key=prev.source_key,
            product_id=prev.product_id,
            weight=max(prev.weight, t.weight),
            compositions=comps,
            ref=t.ref if take_new else prev.ref,
        )

    return [merged[k] for k in order]
