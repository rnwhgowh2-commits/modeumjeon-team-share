# -*- coding: utf-8 -*-
"""매트릭스 OFF 저장 버그 재현 — 한 조합을 OFF(selected 제외)로 저장 후 is_active 확인.

프론트(option_url_modal.js)가 보내는 형식 그대로:
  steps = [{name, values:[...]}]   (주의: 'name' 키)
  selected = [[v1,v2], ...]        (ON 조합만)
  prune = True
"""
from __future__ import annotations
import sys, json
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import config  # noqa
from shared.db import SessionLocal
import lemouton.templates.models  # noqa  (price_templates FK 등록)
import lemouton.sources.models    # noqa
from lemouton.sourcing.models import Model, Option, BundleOptionStep
from lemouton.sourcing.option_service import create_combination_options

CODE = "르무통_메이트"
s = SessionLocal()

steps_rows = s.query(BundleOptionStep).filter_by(model_code=CODE).order_by(BundleOptionStep.step_no).all()
print("axis_steps(DB):", [(r.axis_name, len(json.loads(r.values_json or '[]'))) for r in steps_rows])
# 프론트 형식 steps ('name' 키!)
steps = [{"name": r.axis_name, "values": json.loads(r.values_json or "[]")} for r in steps_rows]

# 현재 옵션들의 axis_values
opts = s.query(Option).filter_by(model_code=CODE).all()
def axv(o):
    try:
        v = json.loads(o.axis_values_json or "[]")
        if v: return [str(x) for x in v]
    except Exception: pass
    return [x for x in [o.color_code or "", o.size_code or ""] if x]

all_axes = [axv(o) for o in opts if axv(o)]
# 첫 조합 하나를 OFF 대상으로 선택
target = all_axes[0]
print("OFF 대상 조합:", target)
selected = [a for a in all_axes if a != target]
print(f"전체 {len(all_axes)} → selected(ON) {len(selected)} (1개 OFF)")

# 저장 전 상태
before = [o for o in opts if axv(o) == target]
print("저장 전 is_active:", [(o.canonical_sku, o.is_active) for o in before])
s.close()

# 실제 저장 (프론트 autoSave 와 동일 호출)
s = SessionLocal()
res = create_combination_options(s, CODE, steps, selected=selected, prune=True)
s.close()
print("combo 결과:", {k: res[k] for k in ('created','disabled','protected','deleted') if k in res})

# 저장 후 재조회
s = SessionLocal()
after = [o for o in s.query(Option).filter_by(model_code=CODE).all() if axv(o) == target]
print("저장 후 is_active:", [(o.canonical_sku, o.is_active) for o in after])
s.close()

ok = all(o.is_active is False for o in after) if after else False
print("\n결과:", "✅ OFF 정상 저장(is_active=False)" if ok else "❌ 버그 — OFF인데 is_active 가 False 가 아님")
