"""매일 회귀 자동 테스트 — 7 사이트 verified SKUs 일괄 크롤 + 가격 변동 알림.

⚠️ 현재 standalone — scheduler 등록 시 매일 새벽 실행 가능.

사용법:
    python docs/sources/_common/daily_regression.py [--threshold-pct 10]

동작:
  1. 7 사이트 각자 yaml accuracy_baseline.verified_skus 에서 URL 가져옴
  2. 해당 사이트 크롤러로 라이브 크롤
  3. 이번 sale_price vs 기준치 비교 — 변동률 X% 이상이면 알림
  4. 결과 console + 향후 telegram/slack 알림 채널 연동 가능

목적:
  - 매일 자동으로 BUG / 사이트 변경 / 가격 이상 감지
  - 무신사 같은 잠재 BUG 가 또 발생하면 즉시 감지 (수동 안 봐도)
  - 회귀 테스트 = 정확도 보증 자동화
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # C:\dev\모음전 프로젝트
SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(ROOT / "docs" / "sources" / "_common"))
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

from yaml_loader import KNOWN_SITES, load_profile, list_verified_skus


# 사이트별 크롤러 매핑 (런타임 import)
def _get_crawler_for(site: str):
    """site 이름 → 크롤러 인스턴스 반환."""
    if site == "musinsa":
        from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
        return MusinsaPlaywrightCrawler(account_name="영빈", headless=True)
    elif site == "lemouton":
        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
        return LemoutonCrawler()
    elif site == "ss_lemouton":
        from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler
        return SsLemoutonCrawler()
    elif site == "ssf":
        from lemouton.sourcing.crawlers.ssf import SsfCrawler
        return SsfCrawler()
    elif site == "lotteimall" or site == "lotteon":
        from lemouton.sourcing.crawlers.lotteon import LotteCrawler
        return LotteCrawler()
    elif site == "ssg":
        from lemouton.sourcing.crawlers.ssg import SsgCrawler
        return SsgCrawler()
    else:
        raise ValueError(f"Unknown site: {site}")


def _get_baseline_sale_price(sku: dict) -> int:
    """verified_sku dict 에서 기준 sale_price 추출 (yaml 마다 필드명 약간 다름)."""
    for key in ("sale_price", "benefit_price", "price", "sellprc"):
        if key in sku and isinstance(sku[key], (int, float)) and sku[key] > 0:
            return int(sku[key])
    return 0


def _extract_current_sale_price(result) -> int:
    """CrawlResult 에서 sale_price 추출 (옵션 0 의 sale_price)."""
    if not result.options:
        return 0
    o = result.options[0]
    for key in ("sale_price", "benefit_price", "price"):
        if key in o and isinstance(o[key], (int, float)) and o[key] > 0:
            return int(o[key])
    return 0


def run_regression(threshold_pct: float = 10.0) -> int:
    """전 사이트 verified SKUs 일괄 크롤 + 변동 알림.

    Returns:
        총 알림 건수 (0 = 모두 안정 / 양수 = 변동 발견)
    """
    print(f"[daily_regression] 시작 — threshold ±{threshold_pct}%\n")
    alerts = []
    passes = []
    skipped = []

    for site in KNOWN_SITES:
        try:
            skus = list_verified_skus(site)
        except FileNotFoundError:
            skipped.append((site, "profile.yaml 없음"))
            continue

        if not skus:
            skipped.append((site, "verified_skus 비어있음"))
            continue

        try:
            crawler = _get_crawler_for(site)
        except Exception as e:
            skipped.append((site, f"크롤러 인스턴스 실패: {e}"))
            continue

        for sku in skus:
            url = sku.get("url")
            if not url:
                continue

            sku_label = sku.get("name", sku.get("product_id", "unknown"))[:50]
            baseline = _get_baseline_sale_price(sku)

            try:
                print(f"  [{site}] {sku_label[:40]} ...", end=" ", flush=True)
                result = crawler.fetch(url)
                current = _extract_current_sale_price(result)
                if current == 0:
                    skipped.append((site, f"{sku_label}: 현재 가격 0"))
                    print("⚠️ skip (가격 0)")
                    continue
                if baseline == 0:
                    passes.append((site, sku_label, baseline, current, "기준치 없음"))
                    print(f"📊 {current:,}원 (기준 없음, 첫 측정)")
                    continue

                diff_pct = abs(current - baseline) / baseline * 100
                if diff_pct >= threshold_pct:
                    alerts.append((site, sku_label, baseline, current, diff_pct))
                    direction = "↑" if current > baseline else "↓"
                    print(f"🚨 ALERT — {baseline:,} → {current:,} ({direction}{diff_pct:.1f}%)")
                else:
                    passes.append((site, sku_label, baseline, current, f"±{diff_pct:.1f}%"))
                    print(f"✅ {current:,}원 (변동 {diff_pct:.1f}%)")
            except Exception as e:
                skipped.append((site, f"{sku_label}: {type(e).__name__}: {str(e)[:60]}"))
                print(f"❌ {type(e).__name__}")

    # 결과 요약
    print(f"\n{'='*70}\n[결과 요약]\n{'='*70}")
    print(f"✅ 정상: {len(passes)}건")
    print(f"🚨 ALERT (변동 ≥ {threshold_pct}%): {len(alerts)}건")
    print(f"⚠️ Skip: {len(skipped)}건")

    if alerts:
        print(f"\n🚨 알림 상세:")
        for site, label, base, curr, diff in alerts:
            print(f"  [{site}] {label}")
            print(f"     기준 {base:,}원 → 현재 {curr:,}원 (±{diff:.1f}%)")

    if skipped:
        print(f"\n⚠️ Skip 상세 (상위 5):")
        for site, reason in skipped[:5]:
            print(f"  [{site}] {reason}")

    return len(alerts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold-pct", type=float, default=10.0,
                        help="알림 임계값 (변동률 %, 기본 10)")
    args = parser.parse_args()
    alerts = run_regression(threshold_pct=args.threshold_pct)
    sys.exit(min(alerts, 1))  # 알림 0 = 0, 1+ = 1 (scheduler 알림용)
