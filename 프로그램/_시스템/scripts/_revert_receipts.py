# -*- coding: utf-8 -*-
"""무신사·롯데온·SSG 가이드 영수증을 populate 원본값으로 복구. 스크린샷은 보존.

(2026-06-11) 손계산으로 잘못 넣은 영수증을 되돌린다. 계산은 프로그램
compute_breakdown 이 라이브로 하므로 가이드 예제는 팀 원본값 유지.
"""
from __future__ import annotations
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
import config  # noqa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg
from shared.db import engine as _base_engine

from populate_musinsa_guide import MUSINSA_GUIDE
from populate_lotteon_guide import LOTTEON_GUIDE
from populate_ssg_guide import SSG_GUIDE

# 6543(트랜잭션 풀러) 우회
_url = str(_base_engine.url.render_as_string(hide_password=False)).replace(":5432/", ":6543/")
_engine = create_engine(_url, pool_size=1, max_overflow=0, connect_args={"prepare_threshold": None})
SessionLocal = sessionmaker(bind=_engine)

RFIELDS = ("surface_price", "pre", "base1", "deducts", "base2", "pay", "final_price", "note")
SRC = {"무신사": MUSINSA_GUIDE, "롯데온": LOTTEON_GUIDE, "SSG": SSG_GUIDE}


def main():
    s = SessionLocal()
    try:
        for name, orig_guide in SRC.items():
            orig_by_url = {e["url"]: e for e in orig_guide["verification"]["examples"]}
            src = s.query(SourceRegistry).filter(SourceRegistry.name == name).first()
            g = cg.loads(src.crawl_guide)
            exs = (g.get("verification") or {}).get("examples") or []
            n = 0
            for ex in exs:
                o = orig_by_url.get(ex.get("url"))
                if not o:
                    continue
                cur_final = ex.get("final_price")
                for f in RFIELDS:
                    if f in o:
                        ex[f] = o[f]
                # captured_at 도 원본으로(없으면 유지), screenshot_url 은 절대 안 건드림
                if "captured_at" in o:
                    ex["captured_at"] = o["captured_at"]
                print(f"  [{name}] {ex.get('name'):20s} final {cur_final} -> {ex.get('final_price')}  shot={'Y' if ex.get('screenshot_url') else '-'}")
                n += 1
            if n:
                src.crawl_guide = cg.dumps(cg.validate_guide(g))
                s.commit()
                print(f"=> {name}: {n}건 복구\n")
    finally:
        s.close()
    print("[완료] 무신사·롯데온·SSG 영수증 원본 복구 (스크린샷 보존)")


if __name__ == "__main__":
    main()
