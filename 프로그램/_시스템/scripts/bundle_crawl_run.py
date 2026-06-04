# -*- coding: utf-8 -*-
"""등록 URL(bundle_source_urls) 크롤 실행.

  python -m scripts.bundle_crawl_run 르무통_메이트 musinsa   # 무신사만 (검증)
  python -m scripts.bundle_crawl_run 르무통_메이트            # 전체 소싱처
"""
from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import config  # noqa
from lemouton.sources.bundle_url_crawl import crawl_registered_urls


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "르무통_메이트"
    sources = sys.argv[2].split(",") if len(sys.argv) > 2 else None
    print("=" * 70)
    print(f" 등록 URL 크롤 — model={model} sources={sources or '전체'}")
    print("=" * 70)
    summ = crawl_registered_urls(model, sources=sources, on_progress=print)
    print("\n" + "=" * 70)
    print(f" URL {summ['total_urls']}개 | 성공 {summ.get('urls_ok')} 건너뜀 {summ.get('urls_skipped')} 실패 {summ.get('urls_failed')}")
    print(f" 저장 옵션 {summ['total_saved']} | 우리옵션 매칭 {summ['total_matched']}")
    print(" URL별:")
    for r in summ["per_url"]:
        tag = "ERR" if r["error"] else ("SKIP" if r.get("skipped") else "OK ")
        note = r["error"][:50] if r["error"] else (r.get("skipped") or "")
        print(f"  [{tag}] {r['label'] or r['source']:18} 옵션{r['options']:>3} 저장{r['saved']:>3} 매칭{r['matched']:>3}"
              + (f"  {note}" if note else ""))
    print("=" * 70)


if __name__ == "__main__":
    main()
