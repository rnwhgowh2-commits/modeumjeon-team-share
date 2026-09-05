# -*- coding: utf-8 -*-
"""무신사 메이트 크롤 매칭 진단 — 어떤 (색상/사이즈)가 우리 옵션과 안 맞는지."""
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
import json as _json
import config  # noqa
from shared.db import SessionLocal
from lemouton.sourcing.models import Model, Option, ColorDict
import lemouton.sources.models  # noqa
from lemouton.sourcing.bulk_crawl import make_crawler


def main():
    s = SessionLocal()
    mate = None
    for m in s.query(Model).all():
        u = getattr(m, "url_musinsa", None)
        if u and "4046672" in u:
            mate = m; break
    if not mate:
        print("메이트 musinsa URL 없음"); return
    our = s.query(Option).filter_by(model_code=mate.model_code).all()
    our_colors = sorted({(o.color_code or "").strip() for o in our})
    our_sizes = sorted({(o.size_code or "").strip() for o in our})
    our_pairs = {((o.color_code or "").strip().lower(), (o.size_code or "").strip()) for o in our}
    print(f"우리 색상({len(our_colors)}): {our_colors}")
    print(f"우리 사이즈: {our_sizes}")
    cdicts = {}
    for c in s.query(ColorDict).all():
        try:
            cdicts[c.color_code.lower()] = [v.lower() for v in _json.loads(c.variants_json or '[]')]
        except Exception:
            pass

    crawler = make_crawler("musinsa")
    result = crawler.fetch(getattr(mate, "url_musinsa"))
    opts = result.options or []
    print(f"\n무신사 크롤 옵션 {len(opts)}개")
    crawled_colors = sorted({(o.get('color_text') or '').strip() for o in opts})
    print(f"무신사 색상: {crawled_colors}")

    def match(c_text, s_norm):
        for oc in our_colors:
            ocl = oc.lower()
            if not ocl: continue
            if ocl in c_text or c_text in ocl:
                if (ocl, s_norm) in our_pairs: return oc
            for v in cdicts.get(ocl, []):
                if v and v in c_text and (ocl, s_norm) in our_pairs:
                    return oc
        return None

    unmatched = []
    for o in opts:
        c_text = (o.get('color_text') or '').strip().lower()
        s_norm = ''.join(ch for ch in (o.get('size_text') or '') if ch.isdigit())
        if not s_norm:
            unmatched.append((o.get('color_text'), o.get('size_text'), 'no_size')); continue
        m2 = match(c_text, s_norm)
        if not m2:
            unmatched.append((o.get('color_text'), o.get('size_text'), 'no_match'))
    print(f"\n매칭 실패 {len(unmatched)}개:")
    for u in unmatched:
        print(f"  색상='{u[0]}' 사이즈='{u[1]}' ({u[2]})")
    s.close()


if __name__ == "__main__":
    main()
