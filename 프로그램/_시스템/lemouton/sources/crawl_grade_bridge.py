"""기존 랩 통계(CrawlChangeStat) → 등급 강도(%) 다리.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §2

━━ 왜 다리가 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  이미 쌓이는 통계(:class:`~lemouton.sources.models.CrawlChangeStat`)는
  **크롤 1회당 변동 확률**(변동률 r)로 센다.
  등급 엔진(:mod:`lemouton.sources.crawl_grade`)은
  **하루에 몇 번 바뀌나**(강도 %)로 센다.

  같은 얘기를 다른 자로 잰 것이다:

      강도(%) = 변동률 r × 하루 크롤 횟수 × 100

  하루 10번 긁어서 그중 20% 가 변동 → 하루 2회 변동 → 강도 200%.

  ★ 이 식의 좋은 성질 — **크롤을 늘려도 추정이 안 흔들린다.**
    2배로 긁으면 관측이 2배 늘고 변동률은 절반이 되어 곱이 같다.
    (이게 없으면 계수를 올릴수록 '더 자주 바뀐다'고 오판해 스스로 부풀어 오른다.)

━━ ⚠️ 이건 「구성 평균」이지 상품별이 아니다 ━━━━━━━━━━━━━━━━━━
  CrawlChangeStat 은 (랩, 소싱처, 브랜드) 단위 집계다. 상품별 행이 없다 —
  무료 티어 500MB 때문에 일부러 그렇게 설계됐다(모델 docstring 참조).
  그래서 여기서 나오는 강도는 **그 구성의 평균 상품**이 얼마나 자주 바뀌나이다.
  시안 11 의 「상품별 기간 산포」는 이 데이터로 만들 수 없다 — 별도 기록이 필요하다.
  화면이 오해하지 않도록 결과에 ``granularity: "composition"`` 을 박아 둔다.

━━ 기존 recommend_weight 와의 관계 ━━━━━━━━━━━━━━━━━━━━━━━━━━
  :func:`~lemouton.sources.crawl_change_stats.recommend_weight` 도 변동률로 계수를
  권한다(w ∝ r, 경계 2/5/10/20%). **같은 아이디어를 다른 단위로 표현한 것**이라
  경쟁 관계가 아니다. 사장님이 확정한 등급 체계(설계서 §3)로 통일하려면 이 다리를 쓴다.
  ⚠️ 둘을 동시에 화면에 띄우면 서로 다른 계수를 권해 혼선이 난다 — 하나만 남길 것.
"""
from __future__ import annotations

from lemouton.sources.crawl_grade import GradeConfig, summarize

# 표본이 이보다 적으면 변동률을 말하지 않는다. 숫자가 요동쳐 계수가 튄다.
MIN_OBSERVATIONS = 30


def change_rate(*, observed: int, changed: int):
    """크롤 1회당 변동 확률. 표본이 모자라면 None(= 모름)."""
    if observed < 0 or changed < 0:
        raise ValueError(f"관측·변동은 음수일 수 없습니다: observed={observed}, changed={changed}")
    if changed > observed:
        raise ValueError(
            f"변동({changed})이 관측({observed})보다 많을 수 없습니다 — 데이터가 모순입니다")
    if observed < MIN_OBSERVATIONS:
        return None
    return changed / observed


def intensity_from_rate(rate, *, crawls_per_day: float):
    """변동률 → 강도(%). 하루 1회 변동 = 100%."""
    if crawls_per_day <= 0:
        raise ValueError(f"하루 크롤 횟수는 0보다 커야 합니다: {crawls_per_day}")
    if rate is None:
        return None
    return rate * crawls_per_day * 100.0


def estimate_union_count(*, intensity_pct: float, window_days: int) -> float:
    """강도(%) → 기간 내 변동 횟수. crawl_grade.summarize 의 입력 단위로 되돌린다."""
    if window_days <= 0:
        raise ValueError(f"기간(일)은 0보다 커야 합니다: {window_days}")
    return intensity_pct / 100.0 * window_days


def summarize_composition(*, source_key: str, brand: str,
                          observed: int, changed: int,
                          price_changed: int = 0, stock_changed: int = 0,
                          crawls_per_day: float, window_days: int,
                          config: GradeConfig | None = None) -> dict:
    """한 구성(소싱처 × 브랜드)의 등급 요약.

    등급은 **합집합(changed)** 으로 매긴다 — 크롤은 한 번 돌면 축을 다 얻으므로.
    축별(price·stock)은 화면·업로드 게이트용으로 같이 담는다.

    ★ 축 합이 합집합보다 **커도 정상**이다. 같은 크롤에 가격·재고가 같이 바뀌면
      changed 는 1로 세기 때문. 반대로 합집합이 축 최댓값보다 **작으면 모순**이라
      조용히 계산하지 않고 터뜨린다.
    """
    name = f"{source_key} > {brand}"
    axis_counts = {"price": price_changed, "stock": stock_changed}

    if max(axis_counts.values(), default=0) > changed:
        raise ValueError(
            f"[{name}] 합집합({changed})이 축 최댓값({max(axis_counts.values())})보다 "
            f"작습니다 — 어느 축이든 바뀐 크롤은 합집합에도 잡혀야 합니다")

    rate = change_rate(observed=observed, changed=changed)
    if rate is None:
        return {
            "composition": name, "granularity": "composition",
            "observed": observed, "changed": changed,
            "grade": None, "grade_name": None,
            "intensity_pct": None, "proposed_per_day": None,
            "note": (f"표본 부족 — 관측 {observed}회(최소 {MIN_OBSERVATIONS}회). "
                     f"몇 바퀴 더 돌아야 등급을 말할 수 있습니다."),
        }

    pct = intensity_from_rate(rate, crawls_per_day=crawls_per_day)
    out = summarize(
        counts_by_axis={
            k: estimate_union_count(
                intensity_pct=intensity_from_rate(
                    v / observed, crawls_per_day=crawls_per_day),
                window_days=window_days)
            for k, v in axis_counts.items()
        },
        union_count=estimate_union_count(intensity_pct=pct, window_days=window_days),
        window_days=window_days,
        config=config,
    )
    out.update({
        "composition": name,
        "granularity": "composition",
        "observed": observed,
        "changed": changed,
        "change_rate": rate,
        "crawls_per_day": crawls_per_day,
        "note": (f"관측 {observed}회 중 {changed}회 변동 = 변동률 {rate * 100:.1f}% · "
                 f"하루 {crawls_per_day:g}회 크롤 → 강도 {pct:.0f}%"),
    })
    return out
