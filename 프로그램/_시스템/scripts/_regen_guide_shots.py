# -*- coding: utf-8 -*-
"""전 소싱처 크롤가이드 '기준 스크린샷' 일괄 재생성 → R2 → screenshot_url 갱신.

2026-06-11. SSF 캡처 크롭(bottom_anchors) 수정 후, 모든 소싱처 예제의 기준
스크린샷을 현재 라이브로 다시 찍어 R2 에 저장하고 guide.verification.examples[].
screenshot_url 을 갱신한다. 캡처 실패(로그인 만료 등)는 건너뛰고 기존값 유지.

실행: cd 프로그램/_시스템 && python scripts/_regen_guide_shots.py
"""
from __future__ import annotations
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import datetime as _dt
import config  # noqa: F401
from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg
from lemouton.sourcing import screenshot as shot

# 크롤가이드 보유 소싱처 (id 는 참고용 — 이름으로 조회)
SOURCES = ["무신사", "SSF", "롯데온", "SSG", "롯데아이몰"]


def main():
    s = SessionLocal()
    try:
        for name in SOURCES:
            src = s.query(SourceRegistry).filter(SourceRegistry.name == name).first()
            if src is None or not src.crawl_guide:
                print(f"[skip] {name}: 가이드 없음")
                continue
            guide = cg.loads(src.crawl_guide)
            exs = (guide.get("verification") or {}).get("examples") or []
            print(f"\n=== {name} (id={src.id}) — examples={len(exs)} ===")
            changed = 0
            for idx, ex in enumerate(exs):
                url = ex.get("url")
                if not url:
                    print(f"  [{idx}] url 없음 skip")
                    continue
                try:
                    data = shot.capture_screenshot(url, source_name=name)
                    public = shot.store_guide_screenshot(src.id, idx, data)
                    ex["screenshot_url"] = public
                    ex["captured_at"] = _dt.datetime.now().strftime("%Y-%m-%d")
                    changed += 1
                    print(f"  [{idx}] OK {len(data):,}B -> {public}")
                except Exception as e:
                    print(f"  [{idx}] FAIL (기존 유지) {repr(e)[:140]}")
            if changed:
                guide["updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
                src.crawl_guide = cg.dumps(cg.validate_guide(guide))
                s.commit()
                print(f"  => {name}: {changed}/{len(exs)} 갱신 저장")
            else:
                print(f"  => {name}: 갱신 0 (저장 안 함)")
    finally:
        s.close()
    print("\n[완료] 스크린샷 재생성")


if __name__ == "__main__":
    main()
