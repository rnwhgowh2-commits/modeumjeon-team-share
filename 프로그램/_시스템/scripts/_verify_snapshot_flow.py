# -*- coding: utf-8 -*-
"""2026-06-11 — 스냅샷 모델 핵심 흐름 검증 (6543, 롤백·DB 미변경).

검증: snapshot → diff(false) → 값수정 → diff(true) → reset(재복제) → diff(false).
diff 비교 로직은 엔드포인트 bundle_diff 와 동일.
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
_url = Config.DB_URL.replace(':5432/', ':6543/')
_engine = create_engine(_url, future=True, pool_pre_ping=True, pool_size=1, max_overflow=1,
                        connect_args={'connect_timeout': 10})
S = sessionmaker(bind=_engine, autoflush=False, future=True, expire_on_commit=False)
from lemouton.sourcing.models import Model, SourceBenefitTemplate, OptionBenefitOverride
from webapp.routes.api_benefits import snapshot_bundle_from_templates, _bundle_skus

s = S()
results = []
def check(label, cond):
    results.append(cond); print(('  [PASS] ' if cond else '  [FAIL] ') + label)

def diff_count(bundle_code, source_id):
    """bundle_diff 엔드포인트와 동일한 비교 로직."""
    skus = _bundle_skus(s, bundle_code)
    if not skus:
        return 0
    tpls = {t.benefit_name: t for t in s.query(SourceBenefitTemplate).filter_by(source_id=source_id).all()}
    ovrs = {o.benefit_name: o for o in s.query(OptionBenefitOverride).filter_by(canonical_sku=skus[0], source_id=source_id).all()}
    n = 0
    for nm, t in tpls.items():
        o = ovrs.get(nm)
        cur = float(o.value) if o is not None else float(t.value)
        if abs(cur - float(t.value)) > 1e-9 or (o is not None and bool(o.enabled) != bool(t.enabled)):
            n += 1
    return n

# rate 템플릿 있는 source + 작은 모음전 선정
src = s.query(SourceBenefitTemplate).filter_by(benefit_type='rate').first().source_id
tpl_names = [t.benefit_name for t in s.query(SourceBenefitTemplate).filter_by(source_id=src).all()]
code = skus = None
for c in [x[0] for x in s.query(Model.model_code).all() if x[0]]:
    sk = _bundle_skus(s, c)
    if 1 <= len(sk) <= 6 and not s.query(OptionBenefitOverride).filter(
            OptionBenefitOverride.canonical_sku.in_(sk), OptionBenefitOverride.source_id == src).count():
        code, skus = c, sk; break
print('대상: source_id=%s 모음전=%r (%d옵션) 템플릿혜택=%s' % (src, code, len(skus or []), tpl_names))

# 1) 스냅샷 전(override 0) → diff 0
check('스냅샷 전 diff=0', diff_count(code, src) == 0)
# 2) 스냅샷 → diff 0 (값=기본값)
snapshot_bundle_from_templates(s, code, source_ids=[src]); s.flush()
n_ovr = s.query(OptionBenefitOverride).filter(OptionBenefitOverride.canonical_sku.in_(skus), OptionBenefitOverride.source_id==src).count()
check('스냅샷 후 override 생성(%d>0)' % n_ovr, n_ovr > 0)
check('스냅샷 후 diff=0 (기본값과 동일)', diff_count(code, src) == 0)
# 3) 한 혜택 값 수정 → diff>=1
target_nm = tpl_names[0]
for o in s.query(OptionBenefitOverride).filter(OptionBenefitOverride.canonical_sku.in_(skus), OptionBenefitOverride.source_id==src, OptionBenefitOverride.benefit_name==target_nm).all():
    o.value = float(o.value) + 0.05
s.flush()
check('값 수정 후 diff>=1', diff_count(code, src) >= 1)
# 4) reset(재복제) → diff 0
snapshot_bundle_from_templates(s, code, source_ids=[src]); s.flush()
check('초기화(재복제) 후 diff=0', diff_count(code, src) == 0)

s.rollback(); s.close()
ok = all(results)
print('\n=== %d/%d PASS — %s (롤백, DB 미변경) ===' % (sum(results), len(results), 'ALL PASS ✅' if ok else 'FAIL ❌'))
sys.exit(0 if ok else 1)
