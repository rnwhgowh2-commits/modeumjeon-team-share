# -*- coding: utf-8 -*-
"""[Phase 1B M5] 크롤 변동 통계 — 계수(1~5)를 **감이 아니라 숫자로** 정하기 위한 근거.

■ 이 모듈이 하는 일 / 안 하는 일
    한다   : 이미 기록된 변동을 **세고**, 소싱처×브랜드로 **모으고**, 권장 계수를 **제안**한다.
    안 한다: 변동을 다시 판정하지 않는다. 계수를 자동으로 바꾸지 않는다
             (``CrawlWeightRule`` 을 이 모듈도 라우트도 쓰지 않는다).
             랩·계수 로직(:mod:`lemouton.sources.crawl_schedule`)은 손대지 않는다.

■ ★기준선 = 소싱처 (2026-07-19 교정)
    물음이 다르면 기준선도 달라야 한다.

    ===========================  ==========================================
    물음                         기준선
    ===========================  ==========================================
    얼마나 자주 크롤할까         소싱처가 얼마나 자주 바뀌나 → ``CrawlDelta``
    마켓에 올릴까                마켓이 든 값과 다른가       → ``GateDecision``
    ===========================  ==========================================

    크롤 빈도는 **마켓과 무관**하다. 처음엔 ``decide_upload`` 판정을 그대로 셌는데,
    그 기준선은 ``last_confirmed_snapshot``(마켓이 실제 받은 값)이라 실전송이 잠기면
    (``MOUM_LIVE_UPLOAD`` OFF) ``uploaded_at`` 이 영원히 안 채워져 기준선이 안 생기고
    **모든 판정이 first_upload 로 떨어져 통계가 통째로 비었다.** ``CrawlDelta`` 로
    바꾸면 잠금 여부와 무관하게 오늘부터 숫자가 나온다 — 그게 이 교정의 목적이다.

■ 지표별 출처 (섞지 않는다)
    · 관측·변동·가격변동·재고변동·품절전환·처음수집·변동률 → ``CrawlDelta``
    · P2 스킵                                             → ``GateDecision``
    화면도 두 묶음을 갈라서 보여준다 — 같은 표에 섞어 놓고 같은 기준인 척하면
    나중에 반드시 오독한다.

■ 무결성 원칙
    1. 크롤 실패를 '변동 없음'으로 세지 않는다. ``CrawlDelta`` 는 **저장에 성공한
       크롤**마다 1행이라(:mod:`lemouton.sources.lap_report` 상단 참고) 실패는 애초에
       행이 없다 — 구조적으로 분모에 섞일 수 없다. 실패를 안정으로 오독하면 계수가
       잘못 내려가 **정작 자주 바뀌는 곳을 덜 보게 된다**.
    2. 처음 수집은 변동이 아니다(``first_seen`` 분리). 회차 보고서와 같은 규칙
       (:func:`lemouton.sources.lap_report.summarize_delta`)을 그대로 쓴다.
    3. 계수 0(크롤 제외)은 통계·권장 대상에서 뺀다. 사용자가 일부러 끈 것이다.
    4. 표본이 부족하면 권장을 **보류**하고 그렇게 표시한다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 진행 중(아직 안 끝난) 랩의 lap_run_id. NULL 대신 0 을 쓰는 이유는 모델 docstring 참고.
OPEN_LAP = 0

# 브랜드 미지정 센티넬. NULL 을 쓰면 UNIQUE 가 PostgreSQL 에서 쪼개진다.
UNSPECIFIED_BRAND = "(브랜드 미지정)"

# 권장을 내기 위한 최소 관측 수.
#   근거: 권장 경계 중 가장 촘촘한 구간이 2%p(2%↔5% 사이 3%p, 그 아래 2%)다.
#   관측 30회면 1건이 3.3%p 를 움직인다 — 딱 한 경계 폭. 이보다 적으면 **관측 한 건이
#   계수를 두 칸 이상 흔들 수 있어** 권장이 잡음이 된다. 그래서 30 미만은 보류한다.
MIN_OBSERVATIONS = 30

# 변동률 → 계수 경계 (내림차순으로 처음 맞는 것). 근거는 recommend_weight docstring.
WEIGHT_BANDS = (
    (0.20, 5),
    (0.10, 4),
    (0.05, 3),
    (0.02, 2),
    (0.00, 1),
)

# 화면이 고를 수 있는 가장 긴 구간(최근 100바퀴).
MAX_REPORT_LAPS = 100
# 보관할 랩 수 — 그보다 오래된 통계 행은 지운다.
#   근거: 화면 최대 구간이 100바퀴다. 딱 100 을 두면 랩이 도는 중에 정리가 돌 때
#   화면이 보는 구간의 끝이 잘린다. **화면 구간의 2배**를 두어 어떤 시점에 정리가
#   돌아도 최근 100바퀴가 온전히 남게 한다.
#   (행이 (소싱처×브랜드)/랩 로 늘고 하루 100바퀴를 넘는데 Supabase 무료 500MB 다.)
STATS_RETENTION_LAPS = MAX_REPORT_LAPS * 2


# ── 브랜드 해석 ──────────────────────────────────────────────────────────────

def brand_of_skus(session, skus) -> dict:
    """canonical_sku → 유효 브랜드.

    ★ 출처는 ``Option`` 이다(``Model.brand`` 가 아니라).
      한 모음전에 여러 브랜드가 섞일 수 있어서 옵션별 브랜드가 따로 있고
      (``Option.brand``, 2026-07-05), 미지정이면 모델 브랜드를 상속한다.
      그 규칙의 단일 진실 원천이 :func:`effective_option_brand` 라 그걸 그대로 부른다.
    """
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_brand import effective_option_brand

    out: dict = {}
    skus = [s for s in (skus or []) if s]
    if not skus:
        return out
    for opt in (session.query(Option)
                .filter(Option.canonical_sku.in_(skus)).all()):
        out[opt.canonical_sku] = effective_option_brand(opt) or UNSPECIFIED_BRAND
    return out


def brands_of_source_product(session, source_product) -> set:
    """이 소싱처 URL 이 먹여 살리는 브랜드들.

    ★ 마켓을 거치지 않는다. 경로는 ``option_source_links``(sku ↔ source_options) —
      실제 FK 가 있는 표라 URL 문자열 비교보다 정확하다(reconcile 의 역방향 헬퍼와
      같은 경로). 마켓 대상이 하나도 없어도 브랜드는 나온다 = 실전송 잠금과 무관.

    링크가 하나도 없으면(SSG 단일상품처럼 옵션 링크가 안 만들어지는 소싱처가 있다)
    :data:`UNSPECIFIED_BRAND` 하나를 돌려준다 — 브랜드를 모른다고 **관측을 통째로
    버리면** 그 소싱처는 영원히 통계에 안 잡힌다(조용한 실패).
    """
    from lemouton.sources.models import OptionSourceLink, SourceOption

    sp_id = getattr(source_product, "id", None)
    skus: set = set()
    if sp_id is not None:
        rows = (session.query(OptionSourceLink.canonical_sku)
                .join(SourceOption,
                      OptionSourceLink.source_option_id == SourceOption.id)
                .filter(SourceOption.source_product_id == sp_id)
                .filter(SourceOption.deleted_at.is_(None))
                .all())
        skus = {r[0] for r in rows if r[0]}
    if not skus:
        return {UNSPECIFIED_BRAND}
    by_sku = brand_of_skus(session, skus)
    return {str(by_sku.get(s) or UNSPECIFIED_BRAND)[:100] for s in skus} \
        or {UNSPECIFIED_BRAND}


# ── 기록 ─────────────────────────────────────────────────────────────────────

def _bucket(session, *, lap_run_id: int, source_key: str, brand: str):
    from lemouton.sources.models import CrawlChangeStat
    row = (session.query(CrawlChangeStat)
           .filter_by(lap_run_id=lap_run_id, source_key=source_key, brand=brand)
           .first())
    if row is None:
        row = CrawlChangeStat(lap_run_id=lap_run_id, source_key=source_key,
                              brand=brand)
        session.add(row)
        session.flush()
    return row


def record_crawl_observation(session, *, source_product, detail) -> dict:
    """[소싱처 기준] 크롤 1건(=CrawlDelta 1행)을 진행 중인 랩 버킷에 누적. 호출자가 commit.

    ``_record_crawl_delta`` 가 CrawlDelta 를 만드는 바로 그 자리에서 부른다 —
    같은 diff 를 두 번 계산하지 않고, 크롤 1회당 정확히 1번만 세기 위해서다.

    Args:
        source_product: 방금 크롤이 저장된 SourceProduct (소싱처 키·브랜드의 출처).
        detail: ``detect_changes`` 가 낸 변동 문장(빈 문자열 = 아무것도 안 바뀜).

    세는 방식 (단위 = 크롤 1회):
        · 변동 문장이 **비어 있다**             → 관측 1 / 변동 0  (진짜 '안 바뀜')
        · 처음 수집만 있다(옵션 생김·없음→X)   → 관측 0 / 처음수집 1
          이전 값이 없으니 '바뀌었나'를 물을 수조차 없다. 분모에 넣으면 첫 크롤이
          전부 변동률 100% 로 둔갑한다.
        · 진짜 변동이 있다                      → 관측 1 / 변동 1 (+가격·재고·품절 내역)

    ★ 한 URL 에 브랜드가 섞여 있으면 그 URL 의 관측이 각 브랜드에 모두 계상된다.
      상품 URL 하나 = 브랜드 하나가 정상이라 실무상 거의 없고, 어느 옵션이 바뀌었는지로
      브랜드를 갈라 세면 색·사이즈 문자열 매칭에 기대게 돼 더 조용히 틀린다.

    Returns:
        이번 호출에서 올린 카운터 합계(진단·테스트용 dict).
    """
    from lemouton.sources.lap_report import summarize_delta

    site = str(getattr(source_product, "site", "") or "")[:64]
    if not site:
        return {}

    c = summarize_delta(detail or "")
    price_hit = c["price"] > 0
    stock_hit = c["stock"] > 0
    changed = price_hit or stock_hit
    first_only = (not changed) and c["first_seen"] > 0

    totals = {"observed": 0, "changed": 0, "price_changed": 0,
              "stock_changed": 0, "soldout": 0, "first_seen": 0}
    for brand in sorted(brands_of_source_product(session, source_product)):
        row = _bucket(session, lap_run_id=OPEN_LAP, source_key=site, brand=brand)
        if c["first_seen"]:
            row.first_seen = (row.first_seen or 0) + 1
            totals["first_seen"] += 1
        if first_only:
            continue                      # 기준선이 없던 크롤 — 분모에 넣지 않는다
        row.observed = (row.observed or 0) + 1
        totals["observed"] += 1
        if changed:
            row.changed = (row.changed or 0) + 1
            totals["changed"] += 1
        if price_hit:
            row.price_changed = (row.price_changed or 0) + 1
            totals["price_changed"] += 1
        if stock_hit:
            row.stock_changed = (row.stock_changed or 0) + 1
            totals["stock_changed"] += 1
        if c["soldout"]:
            row.soldout = (row.soldout or 0) + 1
            totals["soldout"] += 1

    session.flush()
    return totals


def record_gate_skips(session, *, source_product, plans) -> dict:
    """[마켓 기준] 재고가 바뀌었는데 P2 로 **안 올린** 건수만 누적. 호출자가 commit.

    ★ 이것만 ``GateDecision`` 에서 온다. "올릴까 말까"는 본질적으로 마켓 쪽 물음이라
      기준선도 마켓(``last_confirmed_snapshot``)이 맞다 — 그래서 여기 남긴다.
      변동성 통계(관측·변동률)는 이 함수가 **건드리지 않는다**(기준선이 다르므로).

    판정을 다시 하지 않는다. ``plan_uploads`` 가 이미 낸 판정을 세기만 한다.
    """
    site = str(getattr(source_product, "site", "") or "")[:64]
    if not site:
        return {}
    plans = list(plans or [])
    if not plans:
        return {}

    brands = brand_of_skus(session, {p.link.canonical_sku for p in plans})
    totals = {"p2_skipped": 0}
    for plan in plans:
        d = plan.decision
        if not (bool(getattr(d, "stock_changed", False))
                and getattr(d, "priority", "") == "P2"
                and not getattr(d, "should_upload", False)):
            continue
        brand = str(brands.get(plan.link.canonical_sku) or UNSPECIFIED_BRAND)[:100]
        row = _bucket(session, lap_run_id=OPEN_LAP, source_key=site, brand=brand)
        row.p2_skipped = (row.p2_skipped or 0) + 1
        totals["p2_skipped"] += 1

    session.flush()
    return totals


def prune_old_stats(session, keep_laps: int | None = None) -> int:
    """오래된 랩의 통계 행을 정리한다. 호출자가 commit. 반환 = 지운 행 수.

    행이 (소싱처×브랜드)/랩 로 늘고 하루 100바퀴를 넘는데 Supabase 무료 티어는
    500MB 다 — 그냥 두면 언젠가 DB 가 찬다.

    ■ 자르는 방식: **경계선(cutoff) 아래만** 지운다
      "최근 N개 집합에 없으면 지운다"가 아니라 "최근 N개 중 가장 오래된 랩보다
      **더 오래된** 것만 지운다". 앞의 방식이면 아직 ``CrawlLapRun`` 에 못 들어간
      랩(또는 우리가 모르는 id)의 통계까지 같이 날아간다 — 지우는 코드가 애매하면
      멀쩡한 근거가 조용히 사라진다. lap_run_id 는 autoincrement 라 대소 비교가 곧
      시간 순서다.

    ★ 조용히 지우지 않는다. 무엇을 얼마나 지웠는지 로그로 남긴다.
    ★ 진행 중(0) 버킷은 절대 건드리지 않는다 — 아직 어느 바퀴인지도 안 정해졌다.
    ★ 보관 기간을 아직 못 채웠으면(랩이 N개 미만) 아무것도 안 지운다.
    """
    from lemouton.sources.models import CrawlChangeStat

    keep_laps = max(1, int(STATS_RETENTION_LAPS if keep_laps is None else keep_laps))
    lap_ids = recent_lap_ids(session, keep_laps)
    if len(lap_ids) < keep_laps:
        return 0                       # 아직 보관할 만큼도 안 쌓였다
    cutoff = min(lap_ids)              # 이 랩(포함)부터는 남긴다
    n = int((session.query(CrawlChangeStat)
             .filter(CrawlChangeStat.lap_run_id != OPEN_LAP,
                     CrawlChangeStat.lap_run_id < cutoff)
             .delete(synchronize_session=False)) or 0)
    session.flush()
    if n:
        logger.info("[change_stats] 오래된 변동 통계 정리 — %d행 삭제 "
                    "(보관: 최근 %d랩, lap_run_id >= %s / 삭제: lap_run_id < %s)",
                    n, keep_laps, cutoff, cutoff)
    return n


def seal_open_lap_stats(session, lap_run_id: int) -> int:
    """랩이 끝나는 순간 진행 중(0) 버킷들에 그 랩의 도장을 찍는다. 호출자가 commit.

    이 호출 뒤로 쌓이는 관측은 자연히 다음 랩(다시 0)이 된다. 반환 = 확정된 행 수.
    도장을 찍은 김에 오래된 랩 통계도 정리한다(:func:`prune_old_stats`) — 랩이 끝나는
    순간이 유일하게 '랩이 하나 늘었다'가 확정되는 자리라서다.
    """
    from lemouton.sources.models import CrawlChangeStat
    lap_run_id = int(lap_run_id)
    if lap_run_id <= OPEN_LAP:
        raise ValueError(f"lap_run_id 는 1 이상이어야 합니다: {lap_run_id}")
    n = (session.query(CrawlChangeStat)
         .filter(CrawlChangeStat.lap_run_id == OPEN_LAP)
         .update({"lap_run_id": lap_run_id}, synchronize_session=False))
    session.flush()
    try:
        prune_old_stats(session)
    except Exception:   # noqa: BLE001 — 정리 실패가 랩 확정을 되돌릴 이유는 없다
        logger.warning("[change_stats] 오래된 통계 정리 실패 (랩 확정은 정상)",
                       exc_info=True)
    return int(n or 0)


# ── 권장 계수 ────────────────────────────────────────────────────────────────

def recommend_weight(*, rate, observed: int, crawls_per_day=None, config=None):
    """권장 계수(1~5) + 근거 문장. 표본 부족이면 (None, 사유).

    ━━ 2026-07-19 통일 (사장님 5번 = 가) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      같은 물음을 두 방식이 다르게 답하고 있었다. 사장님이 7항목을 직접 정한
      **등급 체계**로 통일한다 — 이 함수 하나만 고치면 쓰는 화면이 전부 따라온다.

      · ``crawls_per_day`` 를 주면 → **등급식**
            강도(%) = 변동률 × 하루 크롤 횟수 × 100  →  6등급  →  하루 N회  →  계수
      · 없으면 → 옛 변동률 밴드 (하위호환)
            하루 크롤 횟수를 모르면 강도를 낼 수 없다. **지어내지 않고** 옛 방식으로 답한다.

      ⚠️ 두 방식은 **같은 입력에 다른 답**을 낸다(변동률 20%: 옛 ×5 vs 등급 ×2).
        그래서 한 화면에 둘을 같이 띄우면 안 된다.

    ── 아래는 옛 밴드 방식 설명 (crawls_per_day 없을 때만 쓰인다) ──

    ★ 권장은 **표시만** 한다. 이 함수도 호출자도 ``CrawlWeightRule`` 을 쓰지 않는다 —
      계수 적용은 사람이 계수 편집 화면에서 한다.

    ■ 왜 '변동률에 비례'인가
      한 랩에서 계수 w 인 URL 은 w 번 크롤된다 → 크롤 간격 ∝ 1/w.
      변동이 크롤 1회당 확률 r 로 일어난다면, 값이 **틀린 채로 방치되는 시간**은
      대략 (변동 빈도) × (간격) ∝ r / w 이다. 소싱처마다 이 방치 시간을 비슷하게
      맞추려면 w ∝ r 이어야 한다 — 그래서 변동률이 높을수록 계수를 올린다.

    ■ 왜 경계가 2 / 5 / 10 / 20 % 인가
      실제 변동률은 0.5% 와 30% 처럼 자릿수가 다르게 흩어진다. 등간격(20/40/60/80%)
      으로 자르면 거의 전부가 최하단 1칸에 뭉쳐 계수가 무의미해진다. 그래서
      **대략 2배씩 넓어지는 경계**를 써서 각 칸이 실제로 갈리게 했다.
      ★ 이 숫자는 실측 없이 정한 출발점이다. 랩이 몇 바퀴 쌓이면 실제 분포를 보고
        다시 잘라야 한다 — 화면에 근거(관측·변동 횟수)를 같이 띄우는 이유다.
    """
    if observed < MIN_OBSERVATIONS:
        return None, (f"표본 부족 — 관측 {observed}회(권장 최소 {MIN_OBSERVATIONS}회). "
                      f"몇 바퀴 더 돌아야 계수를 말할 수 있습니다.")
    if rate is None:
        return None, "변동률 미상 — 권장 보류."

    # ── 등급식 (2026-07-19 통일) — 하루 크롤 횟수를 알면 이쪽이 정본 ──────────
    if crawls_per_day and crawls_per_day > 0:
        from lemouton.sources.crawl_grade import (
            classify, grade_name, per_day_text, proposed_per_day,
        )
        pct = rate * crawls_per_day * 100.0
        g = classify(pct, config)
        per_day = proposed_per_day(g, config)
        # 하루 N회 → 계수. 스케줄러 범위(1~5)로 맞춘다.
        #   1 미만(뜸하게)은 계수로 못 내리므로 최소 1 — 그 몫은 crawl_slowdown 이 맡는다.
        weight = max(1, min(5, round(per_day)))
        return weight, (
            f"관측 {observed}회 중 {round(rate * observed)}회 변동 · "
            f"하루 {crawls_per_day:g}회 크롤 → 강도 {pct:.0f}% "
            f"= {grade_name(g)} → {per_day_text(per_day)} (계수 ×{weight})")

    # ── 옛 변동률 밴드 (하루 크롤 횟수를 모를 때만) ────────────────────────
    for threshold, weight in WEIGHT_BANDS:
        if rate >= threshold:
            return weight, (f"최근 관측 {observed}회 중 {round(rate * observed)}회 변동 "
                            f"= 변동률 {rate * 100:.1f}% → 계수 ×{weight}")
    return 1, f"변동 없음(관측 {observed}회) → 계수 ×1"


def bucket_weight(rules: dict, source_key: str, brand: str) -> int:
    """이 (소싱처, 브랜드) 버킷의 현재 계수.

    ``resolve_crawl_weight`` 의 5단계 중 이 버킷이 표현할 수 있는 두 단계
    (브랜드 → 소싱처 → 기본 1)만 본다. url·모음전 규칙은 버킷보다 잘아서 여기 안 잡힌다
    — 그래서 화면엔 '소싱처·브랜드 규칙 기준'이라고 적는다(있는 척 금지).
    """
    b = (rules.get("brand") or {}).get(brand)
    if b is not None:
        return int(b)
    s = (rules.get("source") or {}).get(source_key)
    if s is not None:
        return int(s)
    return 1


# ── 집계 ─────────────────────────────────────────────────────────────────────

# 출처가 CrawlDelta(소싱처 기준선)인 지표.
SOURCE_FIELDS = ("observed", "changed", "price_changed", "stock_changed",
                 "soldout", "first_seen")
# 출처가 GateDecision(마켓 기준선)인 지표. ★위와 섞어 읽으면 안 된다.
GATE_FIELDS = ("p2_skipped",)

_SUM_FIELDS = SOURCE_FIELDS + GATE_FIELDS


def recent_lap_ids(session, laps: int) -> list:
    """가장 최근 완료된 랩 id 목록(최신 순). 최대 laps 개."""
    from lemouton.sources.models import CrawlLapRun
    rows = (session.query(CrawlLapRun.id)
            .order_by(CrawlLapRun.completed_at.desc(), CrawlLapRun.id.desc())
            .limit(max(1, int(laps))).all())
    return [r[0] for r in rows]


def _cpd(session, weight):
    """이 계수로 하루에 몇 번 긁나. 못 구하면 None.

    등급식 권장은 **하루 크롤 횟수**가 있어야 강도를 낼 수 있다.
    벽시계 모드는 기준주기로, 연속 모드는 랩 회전 속도로 환산한다
    (:mod:`lemouton.sources.crawl_grade_service`).

    ★ 한 번 계산하면 같은 값이라 캐시한다 — 버킷마다 랩 통계를 다시 읽으면 느려진다.
    """
    from datetime import datetime, timezone

    from lemouton.sources.crawl_grade_service import crawls_per_day, recent_avg_lap_minutes
    from lemouton.sources.crawl_schedule import base_crawl_interval_seconds, lap_stats

    cache = getattr(session, "_cpd_cache", None)
    if cache is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        base = base_crawl_interval_seconds(session)
        avg = lap_stats(session, now=now).get("avg_lap_minutes") or \
            recent_avg_lap_minutes(session)
        cache = (base, avg)
        try:
            session._cpd_cache = cache
        except Exception:       # noqa: BLE001  — 캐시 실패는 기능에 영향 없음
            pass
    base, avg = cache
    try:
        return crawls_per_day(weight=weight, base_interval_seconds=base,
                              avg_lap_minutes=avg)
    except Exception:           # noqa: BLE001
        return None


def change_stats(session, *, laps: int = 10, include_open: bool = True) -> dict:
    """최근 N 랩의 소싱처×브랜드 변동률 순위 + 현재/권장 계수.

    Args:
        laps: 최근 몇 바퀴를 볼지.
        include_open: 아직 안 끝난 랩(0)의 누적분도 포함할지.

    Returns:
        {'window', 'rows', 'totals', 'sources'} — rows 는 변동률 내림차순.
        계수 0(크롤 제외) 버킷은 rows 에서 빠지고 'excluded_zero' 에 이름만 남는다.
        'sources' 는 **어느 지표가 어느 기준선에서 왔는지**를 화면에 그대로 넘기는 칸이다.
    """
    from lemouton.sources.models import CrawlChangeStat
    from lemouton.sources.crawl_schedule import list_weight_rules

    lap_ids = recent_lap_ids(session, laps)
    wanted = list(lap_ids)
    if include_open:
        wanted.append(OPEN_LAP)

    rows_db = []
    if wanted:
        rows_db = (session.query(CrawlChangeStat)
                   .filter(CrawlChangeStat.lap_run_id.in_(wanted)).all())

    agg: dict = {}
    for r in rows_db:
        key = (r.source_key, r.brand)
        cur = agg.setdefault(key, {f: 0 for f in _SUM_FIELDS})
        for f in _SUM_FIELDS:
            cur[f] += int(getattr(r, f) or 0)

    rules = list_weight_rules(session)
    try:
        from lemouton.sources.lap_report import site_labels
        labels = site_labels()
    except Exception:   # noqa: BLE001 — 라벨은 표시용이라 실패해도 통계는 낸다
        labels = {}

    out_rows = []
    excluded_zero = []
    for (source_key, brand), c in agg.items():
        weight = bucket_weight(rules, source_key, brand)
        if weight <= 0:
            # 계수 0 = 사용자가 일부러 끈 것. 통계·권장 대상에서 뺀다(의도 존중).
            excluded_zero.append({"source_key": source_key,
                                  "source_label": labels.get(source_key, source_key),
                                  "brand": brand})
            continue
        observed = c["observed"]
        rate = (c["changed"] / observed) if observed else None
        # [2026-07-19 통일] 하루 크롤 횟수를 같이 넘겨 **등급식**으로 권한다.
        #   못 구하면(랩 기록 부족 등) None → 옛 변동률 밴드로 떨어진다(지어내지 않음).
        rec, why = recommend_weight(rate=rate, observed=observed,
                                    crawls_per_day=_cpd(session, weight))
        row = {
            "source_key": source_key,
            "source_label": labels.get(source_key, source_key),
            "brand": brand,
            "rate": rate,
            "rate_pct": (round(rate * 100, 1) if rate is not None else None),
            "current_weight": weight,
            "recommended_weight": rec,
            "recommend_reason": why,
            # 권장이 현재와 다른가 = 사람이 볼 곳. 권장 보류(None)면 False.
            "differs": bool(rec is not None and rec != weight),
        }
        row.update({f: c[f] for f in _SUM_FIELDS})
        out_rows.append(row)

    # 많이 바뀌는 순. 변동률 미상(관측 0)은 맨 뒤로.
    out_rows.sort(key=lambda r: (r["rate"] is None,
                                 -(r["rate"] or 0),
                                 -r["observed"]))

    totals = {f: sum(r[f] for r in out_rows) for f in _SUM_FIELDS}
    totals["buckets"] = len(out_rows)
    totals["rate_pct"] = (round(totals["changed"] / totals["observed"] * 100, 1)
                          if totals["observed"] else None)

    return {
        "window": {
            "laps_requested": int(laps),
            "laps_found": len(lap_ids),
            "include_open": bool(include_open),
            "min_observations": MIN_OBSERVATIONS,
            "retention_laps": STATS_RETENTION_LAPS,
        },
        # ★화면이 '이 숫자는 어디서 왔나'를 지어내지 않게 서버가 그대로 알려준다.
        "sources": {
            "crawl_delta": {
                "fields": list(SOURCE_FIELDS),
                "label": "소싱처 기준 — 크롤 변동 기록(CrawlDelta)",
                "note": "소싱처가 직전 크롤 대비 바뀌었나. 마켓·실전송 잠금과 무관합니다.",
            },
            "gate_decision": {
                "fields": list(GATE_FIELDS),
                "label": "마켓 기준 — 업로드 판정(GateDecision)",
                "note": "마켓이 든 값과 다른가. 위 숫자와 기준선이 다릅니다.",
            },
        },
        "rows": out_rows,
        "excluded_zero": excluded_zero,
        "totals": totals,
    }


def lap_change_report(session, *, laps: int = 10, now=None,
                      include_open: bool = True) -> dict:
    """랩 보고서 — 변동률 순위 + 현재/권장 계수 + 소요시간·오늘 바퀴 수 + 지금 실패 중.

    바퀴 수·소요시간은 **기존 ``lap_stats``(CrawlLapRun)를 그대로 재사용**한다.
    같은 숫자를 두 곳에서 따로 세면 화면마다 다른 값이 뜬다.

    ★ 실패는 '회차별 건수'로 지어내지 않는다. CrawlDelta 는 성공한 크롤만 남기므로
      랩별 실패 수는 존재하지 않는다 — 대신 회차 보고서와 같은 관례로 **지금 실패 중**
      (``last_status='error'``)만 따로 싣는다.
    """
    from datetime import datetime
    from lemouton.sources.crawl_schedule import lap_stats

    stats = change_stats(session, laps=laps, include_open=include_open)
    try:
        stats["lap"] = lap_stats(session, now=now or datetime.utcnow())
    except Exception as e:   # noqa: BLE001 — 랩 시계가 없어도 변동표는 살린다
        logger.warning("[change_stats] lap_stats 실패: %s", e)
        stats["lap"] = None
    try:
        from lemouton.sources.lap_report import failing_now
        stats["failing_now"] = failing_now(session)
    except Exception as e:   # noqa: BLE001
        logger.warning("[change_stats] failing_now 실패: %s", e)
        stats["failing_now"] = []
    return stats
