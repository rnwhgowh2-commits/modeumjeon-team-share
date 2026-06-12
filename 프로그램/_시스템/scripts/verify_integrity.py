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

# Windows 콘솔(cp949)에서도 이모지/박스문자 출력되도록 utf-8 강제.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
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


def _rows(s, sql, **params):
    return s.execute(text(sql), params).fetchall()


# ── 불변식들 ──────────────────────────────────────────────────────────────
def inv1_option_dup(s) -> Check:
    """INV-1 [중복] 활성 옵션에 (model_code,color_code,size_code) 중복 0건."""
    c = Check("INV-1", "옵션 (모델·색·사이즈) 중복", "중복 옵션 = 재고/가격 이중집계·발주 혼란")
    rows = _rows(s, """
        SELECT model_code, color_code, size_code, COUNT(*) n
        FROM options
        WHERE deleted_at IS NULL
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


def inv4_option_stock_stale(s) -> Check:
    """INV-4 [stale] 옵션 갱신시각이 부모 상품보다 옛날 = 옵션재고 미갱신(C1) 0건."""
    c = Check("INV-4", "옵션 재고 stale(부모보다 옛날)", "확장 push 가 옵션재고 미갱신 → 품절품 winner")
    rows = _rows(s, """
        SELECT so.id, sp.site, sp.url
        FROM source_options so
        JOIN source_products sp ON so.source_product_id = sp.id
        WHERE so.deleted_at IS NULL AND sp.deleted_at IS NULL
          AND so.last_fetched_at IS NOT NULL AND sp.last_fetched_at IS NOT NULL
          AND so.last_fetched_at < sp.last_fetched_at
    """)
    for r in rows:
        c.add(f"so#{r.id} {r.site} {str(r.url)[:60]}")
    return c


def inv5_price_present_stock_missing(s) -> Check:
    """INV-5 [재고누락] 옵션 가격은 있는데 재고가 NULL (C1 증상) 0건."""
    c = Check("INV-5", "옵션 가격 있음 + 재고 NULL", "재고 미상인데 가격만 → 품절 판정 불가")
    rows = _rows(s, """
        SELECT so.id, sp.site, so.current_price
        FROM source_options so
        JOIN source_products sp ON so.source_product_id = sp.id
        WHERE so.deleted_at IS NULL AND sp.deleted_at IS NULL
          AND so.current_price IS NOT NULL AND so.current_price > 0
          AND so.current_stock IS NULL
    """)
    for r in rows:
        c.add(f"so#{r.id} {r.site} price={r.current_price} stock=NULL")
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


def main() -> int:
    s = SessionLocal()
    try:
        # 어느 DB 인지 표시
        try:
            from config import Config
            dialect = s.bind.dialect.name
            label = "라이브/원격" if "postgres" in dialect else "로컬 SQLite"
            print(f"[verify_integrity] DB={dialect} ({label})\n")
        except Exception:
            print("[verify_integrity] DB 확인 실패\n")

        results = []
        for fn in CHECKS:
            try:
                results.append(fn(s))
            except Exception as e:
                c = Check(fn.__name__, f"(점검 실패: {type(e).__name__})", str(e)[:80])
                c.count = -1
                results.append(c)

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
