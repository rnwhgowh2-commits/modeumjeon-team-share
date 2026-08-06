"""가격/재고 데이터 무결성 — 전수 점검 하니스 (Phase 0).

금전 직결 불변식을 "표본이 아니라 전 데이터" 로 검사한다.
설정된 DB_URL(로컬 SQLite 또는 라이브 DATABASE_URL) 을 그대로 사용하므로,
  - 로컬:   python scripts/verify_integrity.py
  - 라이브: DATABASE_URL=postgresql://... python scripts/verify_integrity.py
둘 다 같은 코드로 돈다.

각 불변식은 (코드, 설명, 위반건수, 샘플) 을 반환한다.
위반 0 = 그 시점 전 데이터에서 그 불변식이 "완전히" 성립함을 증명한다.
하나라도 위반이면 exit code 1 (CI/배포 게이트로 사용 가능).

주의: 이 스크립트는 읽기 전용. 어떤 행도 수정하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from shared.db import SessionLocal  # noqa: E402

# ── URL 정규화 (점검 전용, 엄격판) ──────────────────────────────────────────
# 운영 normalize_url 은 ckwhere/appPopYn 등을 보존해 "같은 상품"을 다른 행으로
# 분열시킨다(H2). 점검에서는 추적·쿠폰·유입 파라미터를 모두 제거해 "원래 같은
# 상품인데 따로 저장된" 행을 찾아낸다. itemId/goodsNo 같은 상품식별 파라미터는 보존.
_TRACKING_KEYS = {
    "ckwhere", "apppopyn", "napm", "nl-ts", "utag", "fbclid", "gclid",
    "_trk", "cooper", "mtag", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "wlog_rcd", "wlog_clk", "src",
}


def strict_norm(url: str) -> str:
    if not url:
        return ""
    try:
        sp = urlsplit(url.strip())
        q = [(k, v) for (k, v) in parse_qsl(sp.query, keep_blank_values=False)
             if k.lower() not in _TRACKING_KEYS]
        q.sort()
        host = sp.netloc.lower()
        path = sp.path.rstrip("/")
        return urlunsplit((sp.scheme.lower(), host, path, urlencode(q), ""))
    except Exception:
        return url.strip()


# ── 점검 결과 컨테이너 ────────────────────────────────────────────────────
class Check:
    def __init__(self, code, title, money_impact):
        self.code = code
        self.title = title
        self.money_impact = money_impact
        self.count = 0
        self.samples: list[str] = []

    def add(self, sample: str):
        self.count += 1
        if len(self.samples) < 8:
            self.samples.append(sample)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "title": self.title,
            "money_impact": self.money_impact,
            "count": self.count,
            "ok": self.count == 0,
            "errored": self.count < 0,
            "samples": self.samples,
        }


def _rows(s, sql, **params):
    return s.execute(text(sql), params).fetchall()


def _is_sqlite(s) -> bool:
    """지금 붙은 DB 가 SQLite 인가 — 시각 차이 계산 문법이 갈려서 필요하다.
       (SQLite=JULIANDAY · PostgreSQL=EXTRACT(EPOCH ...)). 못 알아내면 라이브(Postgres)로 본다."""
    try:
        return s.bind.dialect.name == "sqlite"
    except Exception:   # noqa: BLE001
        return False


def _ago(seconds: float) -> str:
    """초 → 사람이 읽는 '얼마나'. 판단에 쓰는 값이라 반올림해서 짧게.

    ★버림이 아니라 **반올림**이다. SQLite 의 JULIANDAY 는 날짜를 소수(일)로 주므로
      ×86400 하면 3초가 2.9999… 로 나온다 — 버리면 「2초」로 보인다(테스트가 잡았다).
    """
    sec = int(round(seconds or 0))
    if sec < 60:
        return f"{sec}초"
    if sec < 3600:
        return f"{sec // 60}분"
    if sec < 86400:
        return f"{sec // 3600}시간"
    return f"{sec // 86400}일"


# ── 불변식들 ──────────────────────────────────────────────────────────────
def inv1_option_dup(s) -> Check:
    """INV-1 [중복] 활성 옵션에 (model_code,color_code,size_code) 중복 0건."""
    c = Check("INV-1", "옵션 (모델·색·사이즈) 중복", "중복 옵션 = 재고/가격 이중집계·발주 혼란")
    # [2026-08-01] `options` 에는 deleted_at 칸이 **없다**(그 칸은 source_products·
    #   source_options 쪽 것이다). 여기만 그 칸을 보고 있어서 라이브(PostgreSQL)에서
    #   `column "deleted_at" does not exist` 로 죽었고, 그 바람에 이 점검뿐 아니라
    #   **뒤따르는 6개도 전부** 못 돌았다(아래 run_checks 주석 참고).
    #   `options` 의 활성 표시는 `is_active` 다 (lemouton/sourcing/models.py:249).
    rows = _rows(s, """
        SELECT model_code, color_code, size_code, COUNT(*) n
        FROM options
        WHERE is_active = TRUE
        GROUP BY model_code, color_code, size_code
        HAVING COUNT(*) > 1
        ORDER BY n DESC
    """)
    for r in rows:
        c.add(f"{r.model_code} / {r.color_code} / {r.size_code} → {r.n}행")
    return c


def inv2_sp_url_split(s) -> Check:
    """INV-2 [분열] 같은 site 에서 정규화 URL 이 같은데 별도 SourceProduct 로 분열 0건."""
    c = Check("INV-2", "소싱처 상품 URL 분열(ckwhere 등)", "분열 = 가격 빈칸/엉뚱한 변형가 표시")
    rows = _rows(s, """
        SELECT id, site, url FROM source_products WHERE deleted_at IS NULL
    """)
    groups: dict[tuple, list] = {}
    for r in rows:
        key = (r.site, strict_norm(r.url))
        groups.setdefault(key, []).append(r.url)
    for (site, norm), urls in groups.items():
        if len(urls) > 1:
            c.add(f"{site} :: {norm} → {len(urls)}행")
    return c


def inv3_ok_without_price(s) -> Check:
    """INV-3 [위장] last_status='ok' 인데 가격이 NULL/0 인 SourceProduct 0건."""
    c = Check("INV-3", "ok 인데 가격 없음/0", "'완료'로 위장된 빈 결과 → stale/누락")
    rows = _rows(s, """
        SELECT id, site, url, last_price FROM source_products
        WHERE deleted_at IS NULL AND last_status = 'ok'
          AND (last_price IS NULL OR last_price <= 0)
    """)
    for r in rows:
        c.add(f"sp#{r.id} {r.site} price={r.last_price} {str(r.url)[:60]}")
    return c


# 한 크롤 안에서 옵션을 먼저 쓰고 상품 행을 나중에 만지면 **몇 초** 차이로도 stale 조건에
# 걸린다. 그건 기록 순서일 뿐 무해하다 — 이 창(1시간) 안쪽은 위반으로 세지 않는다.
_STALE_BENIGN_SEC = 3600


def _sellable_linked_count(s, so_ids):
    """낡은 옵션 중 **팔 수 있는 우리 옵션**에 실제로 물린 게 몇 건인가.

    stale 자체는 데이터 문제지만, **돈**이 되는 건 그 낡은 숫자가 판매 중인 옵션에
    닿을 때뿐이다(판매가능 = options.is_active AND NOT crawl_blocked — 모델 정의
    lemouton/sourcing/models.py:249·256). 라이브 실측(2026-08-06)에서 「오버셀 후보
    48건」이 전부 **아무 옵션에도 안 물린 고아 상품**이었다 — 그 사실을 숫자로 말하려고 센다.

    못 세면 None 을 돌려 「확인 불가」로 적는다. 여기서 예외를 그냥 내면 run_checks 가
    INV-4 를 통째로 '판정 불가'로 만들어 **진짜 위반까지 안 보이게** 되기 때문이다.
    """
    ids = [int(x) for x in so_ids]
    if not ids:
        return 0
    in_list = ",".join(str(i) for i in ids)     # 전부 int 로 검증된 값만 들어간다
    try:
        return int(s.execute(text(f"""
            SELECT COUNT(DISTINCT so.id)
            FROM source_options so
            JOIN source_products sp ON sp.id = so.source_product_id
            LEFT JOIN model_source_links ml ON ml.source_product_id = sp.id
            LEFT JOIN bundle_source_urls bsu ON bsu.url = sp.url
            LEFT JOIN option_source_url_links l
                   ON l.bundle_source_url_id = bsu.id
            JOIN options o
              ON o.model_code = ml.model_code
              OR o.canonical_sku = l.option_canonical_sku
            WHERE so.id IN ({in_list})
              AND o.is_active = TRUE AND o.crawl_blocked = FALSE
        """)).scalar() or 0)
    except Exception:   # noqa: BLE001 — 못 세는 건 「확인 불가」이지 점검 실패가 아니다
        try:
            s.rollback()
        except Exception:   # noqa: BLE001
            pass
        return None


def inv4_option_stock_stale(s) -> Check:
    """INV-4 [stale] 낡은 **숫자**를 현재값처럼 들고 있는 옵션 0건."""
    c = Check("INV-4", "옵션 재고 stale(낡은 숫자가 현재값 행세)",
              "확장 push 가 옵션재고 미갱신 → 품절품 winner")
    # [2026-08-01] **얼마나 낡았는지**를 같이 잰다. 건수만으로는 판단할 수 없기 때문이다 —
    #   한 크롤 안에서 옵션을 먼저 쓰고 상품 행을 나중에 만지면 몇 **초** 차이로도 이 조건에
    #   걸린다(무해한 기록 순서). 반대로 **몇 시간·며칠** 벌어졌다면 그건 옵션 재고가 진짜로
    #   안 따라온 것이라, 화면이 낡은 숫자를 현재값처럼 보여 준다(품절품이 winner = 오버셀).
    #   → 뒤늦은 순으로 보여 주고, 사람이 볼 눈금(1시간·1일)으로 나눠 센다.
    rows = _rows(s, """
        SELECT so.id, sp.site, sp.url,
               so.current_stock AS stock,
               (JULIANDAY(sp.last_fetched_at) - JULIANDAY(so.last_fetched_at)) * 86400.0
                   AS gap_sec
        FROM source_options so
        JOIN source_products sp ON so.source_product_id = sp.id
        WHERE so.deleted_at IS NULL AND sp.deleted_at IS NULL
          AND so.last_fetched_at IS NOT NULL AND sp.last_fetched_at IS NOT NULL
          AND so.last_fetched_at < sp.last_fetched_at
        ORDER BY gap_sec DESC
    """) if _is_sqlite(s) else _rows(s, """
        SELECT so.id, sp.site, sp.url,
               so.current_stock AS stock,
               EXTRACT(EPOCH FROM (sp.last_fetched_at - so.last_fetched_at)) AS gap_sec
        FROM source_options so
        JOIN source_products sp ON so.source_product_id = sp.id
        WHERE so.deleted_at IS NULL AND sp.deleted_at IS NULL
          AND so.last_fetched_at IS NOT NULL AND sp.last_fetched_at IS NOT NULL
          AND so.last_fetched_at < sp.last_fetched_at
        ORDER BY gap_sec DESC
    """)
    # 🔴 [2026-08-06 이슈 #636] **무엇을 위반으로 셀 것인가**를 실측으로 좁혔다.
    #   라이브 373건을 뜯어 보니 세 부류가 한 숫자에 뭉쳐 있었다.
    #     ① 1시간 미만 13건 — 한 크롤 안의 기록 순서(이 함수 주석이 이미 '무해'라고 적어 둔 것)
    #     ② 재고 NULL 285건 — NULL 은 화면이 「확인 불가」로, 업로드는 「보류」로 안전하게
    #        끊는다(api_pricing.py:886 stock_uncollected · reconcile.py:504). 게다가 이 285건은
    #        **INV-5 가 세는 바로 그 행들**이라 총합이 이중으로 부풀었다(373+285=658 로 보고됨).
    #     ③ 재고에 숫자가 든 66건 — 이것만이 「낡은 값을 현재값처럼」 보여 주는 진짜 부류.
    #   ①②를 위반에서 빼되 **숨기지는 않는다**(아래 money_impact 에 건수로 남긴다).
    #   검사를 무르게 하는 게 아니라 ③을 가리던 소음을 걷어내는 것이다 — 소음이 쌓이면
    #   감시기를 아무도 안 보게 되고, 그게 감시기가 죽는 흔한 방식이다.
    benign_recent = 0       # ① 기록 순서(1시간 미만)
    unknown_stock = 0       # ② 재고 NULL = 「확인 불가」
    over_day = risky = 0
    stale_ids: list[int] = []
    for r in rows:
        gap = float(r.gap_sec or 0)
        if gap < _STALE_BENIGN_SEC:
            benign_recent += 1
            continue
        if r.stock is None:
            unknown_stock += 1
            continue
        # 여기부터가 위반 — 낡았는데 **숫자**가 들어 있다(아무도 낡은 줄 모르고 현재값처럼 쓴다.
        #   _resolve_stock 에 stale 개념이 없다). 양수는 오버셀, 0 은 멀쩡한 물건을 품절로 막는다.
        if int(r.stock) > 0:
            risky += 1
        if gap >= 86400:
            over_day += 1
        stale_ids.append(int(r.id))
        c.add(f"so#{r.id} {r.site} 재고={r.stock} {_ago(gap)} 뒤처짐 {str(r.url)[:44]}")
    if c.count:
        linked = _sellable_linked_count(s, stale_ids)
        linked_txt = ("판매 연결 확인 불가" if linked is None
                      else f"그중 판매가능 옵션에 물린 것 {linked}건")
        c.money_impact += (
            f" · 1일↑ {over_day}건 · 🔴낡은 양수재고 {risky}건(오버셀 후보)"
            f" · {linked_txt}")
    if benign_recent or unknown_stock:
        c.money_impact += (
            f" · [위반 아님] 1시간 미만 {benign_recent}건(기록 순서)"
            f" · 재고 NULL {unknown_stock}건(「확인 불가」로 안전하게 끊김"
            f" — 가격까지 있으면 INV-5 가 잡는다)")
    return c


def inv5_price_present_stock_missing(s) -> Check:
    """INV-5 [재고누락] 옵션 가격은 있는데 재고가 NULL (C1 증상) 0건."""
    c = Check("INV-5", "옵션 가격 있음 + 재고 NULL", "재고 미상인데 가격만 → 품절 판정 불가")
    # [2026-08-06 이슈 #636] 대표가를 함께 읽어 **가격이 어디서 왔는지**를 말하게 한다.
    #   라이브 285건은 전부 current_price == sp.last_price 였고 상품당 서로 다른 가격이
    #   1종뿐이었다 = 옵션을 실제로 읽은 값이 아니라 **상품 대표가 복사본**(폴백 가격).
    #   원인 경로는 crawl-result 의 옵션가 일괄 갱신(webapp/routes/api_pricing.py) —
    #   options[] 없이 온 크롤이 그 상품의 모든 옵션에 대표가를 칠했다.
    #   그 수를 같이 내놓아야 "재고 수집이 안 되는 소싱처"와 "폴백 가격"을 안 헷갈린다.
    rows = _rows(s, """
        SELECT so.id, sp.site, so.current_price, sp.last_price
        FROM source_options so
        JOIN source_products sp ON so.source_product_id = sp.id
        WHERE so.deleted_at IS NULL AND sp.deleted_at IS NULL
          AND so.current_price IS NOT NULL AND so.current_price > 0
          AND so.current_stock IS NULL
    """)
    same_as_product = 0
    for r in rows:
        if r.last_price is not None and r.current_price == r.last_price:
            same_as_product += 1
        c.add(f"so#{r.id} {r.site} price={r.current_price} stock=NULL")
    if c.count:
        c.money_impact += (
            f" · 그중 {same_as_product}건은 가격이 상품 대표가와 같다"
            f" = 옵션을 읽은 값이 아니라 **대표가 복사본**(폴백 가격 — 정합성 원칙 ② 위반)")
    return c


def inv6_color_substring_ambiguity(s) -> Check:
    """INV-6 [오매칭위험] 같은 상품·같은 사이즈에서 색상명이 부분포함 관계 0건(H1)."""
    c = Check("INV-6", "색상 부분일치 모호성", "substring 매칭이 엉뚱한 색 가격을 붙임")
    rows = _rows(s, """
        SELECT source_product_id, size_text, color_text
        FROM source_options
        WHERE deleted_at IS NULL AND color_text IS NOT NULL AND color_text != ''
    """)
    by_key: dict[tuple, list] = {}
    for r in rows:
        by_key.setdefault((r.source_product_id, r.size_text or ""), []).append(
            (r.color_text or "").replace(" ", "")
        )
    for (spid, size), colors in by_key.items():
        uniq = list(dict.fromkeys(colors))
        for i in range(len(uniq)):
            for j in range(len(uniq)):
                if i != j and uniq[i] and uniq[j] and uniq[i] in uniq[j]:
                    c.add(f"sp#{spid} size={size}: '{uniq[i]}' ⊂ '{uniq[j]}'")
                    break
            else:
                continue
            break
    return c


def inv7_negative_price(s) -> Check:
    """INV-7 [이상가] 음수 가격 0건."""
    c = Check("INV-7", "음수/이상 가격", "음수가가 최저가로 선정되면 판매가 붕괴")
    rows = _rows(s, """
        SELECT id, site, last_price FROM source_products
        WHERE deleted_at IS NULL AND last_price IS NOT NULL AND last_price < 0
    """)
    for r in rows:
        c.add(f"sp#{r.id} {r.site} price={r.last_price}")
    rows2 = _rows(s, """
        SELECT id, current_price FROM source_options
        WHERE deleted_at IS NULL AND current_price IS NOT NULL AND current_price < 0
    """)
    for r in rows2:
        c.add(f"so#{r.id} price={r.current_price}")
    return c


CHECKS = [
    inv1_option_dup, inv2_sp_url_split, inv3_ok_without_price,
    inv4_option_stock_stale, inv5_price_present_stock_missing,
    inv6_color_substring_ambiguity, inv7_negative_price,
]


def run_checks(session) -> list:
    """전 불변식 실행 → Check 리스트. CLI·웹 엔드포인트 공용 (읽기 전용)."""
    results = []
    for fn in CHECKS:
        try:
            results.append(fn(session))
        except Exception as e:  # 한 점검 실패가 전체를 막지 않게
            # 🔴 [2026-08-01] 이 약속이 PostgreSQL 에서는 **지켜지지 않고 있었다.**
            #   Postgres 는 문(statement) 하나가 실패하면 그 트랜잭션을 통째로 중단시킨다.
            #   예외만 삼키고 넘어가면 세션이 중단된 채라, 다음 점검부터는 무엇을 물어도
            #   InFailedSqlTransaction 으로 죽는다 — 실제로 라이브 첫 실행에서
            #   inv1 하나가 깨지자 **나머지 6개가 전부 도미노로 죽어** '판정 불가'가 됐다.
            #   (SQLite 는 이런 중단이 없어 로컬에서는 안 드러난다 — 그래서 여태 몰랐다.)
            #   rollback() 으로 세션을 되살려 놔야 다음 점검이 제 몫을 한다.
            try:
                session.rollback()
            except Exception:   # noqa: BLE001 — 되살리기 실패해도 남은 점검은 시도한다
                pass
            c = Check(fn.__name__, f"(점검 실패: {type(e).__name__})", str(e)[:120])
            c.count = -1
            results.append(c)
    return results


def main() -> int:
    # Windows 콘솔(cp949)에서도 이모지/박스문자 출력되도록 utf-8 강제 (CLI 전용).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    s = SessionLocal()
    try:
        # 어느 DB 인지 표시
        try:
            dialect = s.bind.dialect.name
            label = "라이브/원격" if "postgres" in dialect else "로컬 SQLite"
            print(f"[verify_integrity] DB={dialect} ({label})\n")
        except Exception:
            print("[verify_integrity] DB 확인 실패\n")

        results = run_checks(s)

        total_viol = 0
        errored = 0
        print(f"{'코드':<7} {'위반':>6}  불변식")
        print("─" * 70)
        for c in results:
            mark = "⚠️ 점검오류" if c.count < 0 else ("✅" if c.count == 0 else "❌")
            n = "-" if c.count < 0 else str(c.count)
            print(f"{c.code:<7} {n:>6}  {mark} {c.title}")
            if c.count < 0:
                errored += 1
                print(f"          └ {c.money_impact}")
            elif c.count > 0:
                total_viol += c.count
                print(f"          └ 영향: {c.money_impact}")
                for sm in c.samples:
                    print(f"            · {sm}")
                if c.count > len(c.samples):
                    print(f"            … 외 {c.count - len(c.samples)}건")
        print("─" * 70)
        if errored:
            print(f"⚠️ 점검 {errored}건 실행 실패 — DB 연결/스키마 확인 필요(판정 불가).")
            return 2
        if total_viol == 0:
            print("✅ 모든 불변식 위반 0건 — 이 시점 전 데이터에서 성립.")
            return 0
        print(f"❌ 총 위반 {total_viol}건 — 위 항목 수정 필요.")
        return 1
    finally:
        s.close()


if __name__ == "__main__":
    raise SystemExit(main())
