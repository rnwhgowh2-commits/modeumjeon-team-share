"""Phase B 시연 (회원가 Playwright 경로) — yaml-driven v2 vs hardcoded.

목적: docs/sources/musinsa/profile.yaml 의 member_price 섹션이
       기존 config.SOURCING_AUTH 와 동일한 회원가 결과를 만드는지 검증.

방식: 같은 product 를 두 번 크롤
       (1) 기존: MusinsaPlaywrightCrawler — config.SOURCING_AUTH 직접 사용
       (2) v2 : yaml 값으로 config.SOURCING_AUTH overwrite 후 동일 크롤러 호출
                → 결과 동일 = yaml 이 config.py 를 대체 가능 입증

범위: 988줄의 _EXTRACT_JS / 9단계 가격산식 / 5단계 fail-safe 는 코드 그대로.
       yaml 화 가능한 부분 (account · headless · timeout · stock_cap · 정책 룰) 만 추출.
       JS / 산식 yaml 화 = 다음 세션 (1-2주 작업).
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import yaml

# 경로 셋업 (OneDrive 운영본 import)
SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

ROOT = Path(r"C:\dev\모음전 프로젝트")
PROFILE_PATH = ROOT / "docs" / "sources" / "musinsa" / "profile.yaml"
profile = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────
# 결과 normalize (비교용)
# ─────────────────────────────────────────────────────────────
def normalize(r):
    """CrawlResult → dict (비교 가능 형태)."""
    return {
        "source": r.source,
        "product_url": r.product_url,
        "product_name_raw": r.product_name_raw,
        "brand": getattr(r, "brand", "") or "",
        "discount_info": getattr(r, "discount_info", "") or "",
        "options_count": len(r.options),
        # 핵심 가격 필드 (옵션 0번)
        "option0_sample": {
            "color_text": r.options[0].get("color_text") if r.options else None,
            "size_text": r.options[0].get("size_text") if r.options else None,
            "original_price": r.options[0].get("original_price") if r.options else None,
            "sale_price": r.options[0].get("sale_price") if r.options else None,
            "benefit_price": r.options[0].get("benefit_price") if r.options else None,
            "member_price": r.options[0].get("member_price") if r.options else None,
            "is_member_price": r.options[0].get("is_member_price") if r.options else None,
        },
    }


# ─────────────────────────────────────────────────────────────
# 기존 (hardcoded) — config.SOURCING_AUTH 그대로
# ─────────────────────────────────────────────────────────────
def hardcoded(url):
    from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
    c = MusinsaPlaywrightCrawler(account_name="영빈", headless=True)
    return c.fetch(url)


# ─────────────────────────────────────────────────────────────
# v2 (yaml-driven) — config.SOURCING_AUTH 를 yaml 값으로 overwrite 후 동일 크롤러 호출
# ─────────────────────────────────────────────────────────────
def v2_yaml_driven(url, prof):
    """yaml 의 member_price 섹션 → config.SOURCING_AUTH 로 적용 → 크롤러 호출."""
    import config
    mp = prof["member_price"]

    # 1) 기본 timeout / stock_cap 적용
    for k in ("crawl_timeout_ms", "csr_wait_ms", "dropdown_interval_ms", "stock_cap"):
        if k in mp:
            config.SOURCING_AUTH[k] = mp[k]

    # 2) musinsa_rules 적용
    if "musinsa_rules" in mp:
        if "musinsa_rules" not in config.SOURCING_AUTH:
            config.SOURCING_AUTH["musinsa_rules"] = {}
        config.SOURCING_AUTH["musinsa_rules"].update(mp["musinsa_rules"])

    # 3) 크롤러 인스턴스화 (account_name, headless 모두 yaml 에서)
    from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
    c = MusinsaPlaywrightCrawler(
        account_name=mp["account_name"],
        headless=mp.get("headless", True),
    )
    return c.fetch(url)


# ─────────────────────────────────────────────────────────────
# 비교
# ─────────────────────────────────────────────────────────────
def compare(url):
    print("=" * 70)
    print(f"[TEST URL] {url}")
    print("=" * 70)

    print("\n[1/2] 기존 (hardcoded SOURCING_AUTH) 회원가 크롤링 ...")
    print("       (30~60초 소요 — Playwright 백그라운드 실행)")
    try:
        r1 = hardcoded(url)
        n1 = normalize(r1)
        print(f"   ✅ 회원가(benefit_price): {n1['option0_sample']['benefit_price']:,}원")
        print(f"      member_price: {n1['option0_sample']['member_price']}")
        print(f"      옵션 {n1['options_count']}개  brand={n1['brand']}")
    except Exception as e:
        print(f"   ❌ 실패: {type(e).__name__}: {e}")
        return 1

    print("\n[2/2] v2 (yaml-driven) 회원가 크롤링 ...")
    print(f"       (yaml 의 member_price.account_name={profile['member_price']['account_name']!r})")
    print("       (30~60초 소요 — Playwright 백그라운드 실행)")
    try:
        r2 = v2_yaml_driven(url, profile)
        n2 = normalize(r2)
        print(f"   ✅ 회원가(benefit_price): {n2['option0_sample']['benefit_price']:,}원")
        print(f"      member_price: {n2['option0_sample']['member_price']}")
        print(f"      옵션 {n2['options_count']}개  brand={n2['brand']}")
    except Exception as e:
        print(f"   ❌ 실패: {type(e).__name__}: {e}")
        return 1

    print("\n" + "=" * 70)
    print("[DIFF 비교]")
    print("=" * 70)
    a = json.dumps(n1, ensure_ascii=False, sort_keys=True, indent=2)
    b = json.dumps(n2, ensure_ascii=False, sort_keys=True, indent=2)
    if a == b:
        print("✅✅✅ 100% 일치 — yaml-driven v2 가 기존(SOURCING_AUTH) 와 동일하게 동작")
        print(f"   회원가·옵션·브랜드·discount_info 모두 일치")
        return 0
    print("❌ 차이 발견:")
    print(f"  기존: {a}")
    print(f"  v2  : {b}")
    return 2


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.musinsa.com/products/4210142"
    sys.exit(compare(url))
