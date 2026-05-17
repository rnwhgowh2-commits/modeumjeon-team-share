"""docs/sources/{site}/profile.yaml 로더 helper — Phase B 일반화 발판.

⚠️ DEV 전용 — 운영 코드는 아직 이 모듈 안 import. 코드 리팩토링 시 사용 가능.

사용 예:
    from docs.sources._common.yaml_loader import load_profile
    musinsa = load_profile('musinsa')
    print(musinsa['member_price']['account_name'])  # '영빈'
    print(musinsa['accuracy_baseline']['verified_skus'][0]['benefit_price'])  # 203048

확장 시나리오 (Phase B):
    1. 어댑터 코드를 yaml 으로 import: `profile = load_profile('musinsa')`
    2. config.SOURCING_AUTH 대신 profile['member_price'] 사용
    3. 셀렉터 yaml 도 동일 패턴: load_selectors('musinsa')
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Phase B 일반화 시 운영 코드에서 import 할 표준 경로
ROOT = Path(__file__).resolve().parent.parent.parent.parent  # C:\dev\모음전 프로젝트
DOCS_SOURCES = ROOT / "docs" / "sources"

try:
    import yaml  # pyyaml
except ImportError:
    raise ImportError(
        "pyyaml 필요 — pip install pyyaml"
    )


# 7 사이트 등록 (확장 시 여기 추가)
KNOWN_SITES = ["musinsa", "lemouton", "ss_lemouton", "ssf", "lotteimall", "lotteon", "ssg"]


def load_profile(site: str) -> dict[str, Any]:
    """{site}/profile.yaml 로드. 미존재 사이트는 FileNotFoundError."""
    if site not in KNOWN_SITES:
        # 미등록 사이트도 try (신규 사이트 분석 중일 때)
        pass
    path = DOCS_SOURCES / site / "profile.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"profile.yaml 없음: {path}\n"
            f"등록된 사이트: {KNOWN_SITES}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_selectors(site: str) -> dict[str, Any]:
    """{site}/selectors.yaml 로드."""
    path = DOCS_SOURCES / site / "selectors.yaml"
    if not path.exists():
        raise FileNotFoundError(f"selectors.yaml 없음: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_pricing_policy(site: str) -> dict[str, Any]:
    """{site}/pricing_policy.yaml 로드."""
    path = DOCS_SOURCES / site / "pricing_policy.yaml"
    if not path.exists():
        raise FileNotFoundError(f"pricing_policy.yaml 없음: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_all(site: str) -> dict[str, Any]:
    """3개 yaml 한 번에 (profile + selectors + pricing_policy)."""
    return {
        "profile": load_profile(site),
        "selectors": load_selectors(site),
        "pricing_policy": load_pricing_policy(site),
    }


def list_verified_skus(site: str) -> list[dict]:
    """{site} 의 accuracy_baseline.verified_skus 반환."""
    profile = load_profile(site)
    return profile.get("accuracy_baseline", {}).get("verified_skus", []) or []


def get_verified_url_for_site(site: str) -> str | None:
    """첫 번째 verified SKU 의 URL 반환 (회귀 테스트용)."""
    skus = list_verified_skus(site)
    for sku in skus:
        if "url" in sku:
            return sku["url"]
    return None


def smoke_test_self():
    """모든 7 사이트 profile 로드 가능한지 확인."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print(f"[yaml_loader smoke test] DOCS_SOURCES={DOCS_SOURCES}")
    ok = []
    fail = []
    for site in KNOWN_SITES:
        try:
            p = load_profile(site)
            display = p.get("display_name", site)
            verified = len(list_verified_skus(site))
            url = get_verified_url_for_site(site)
            ok.append((site, display, verified, url))
            print(f"  ✅ {site} ({display}) — verified={verified} SKUs")
            if url:
                print(f"     첫 URL: {url[:90]}")
        except Exception as e:
            fail.append((site, str(e)))
            print(f"  ❌ {site} — {e}")
    print(f"\n결과: ✅ {len(ok)}/{len(KNOWN_SITES)} 사이트 로드 성공")
    return len(fail) == 0


if __name__ == "__main__":
    ok = smoke_test_self()
    sys.exit(0 if ok else 1)
