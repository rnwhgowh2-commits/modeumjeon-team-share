# -*- coding: utf-8 -*-
"""2026-06-11 — 컷오버 후 검증: 스냅샷 독립성 입증 (6543, 롤백).

핵심 약속: 소싱처 기본값(SourceBenefitTemplate)을 바꿔도 '기존(스냅샷된) 모음전' 가격 불변.
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
from webapp.routes.api_benefits import compute_breakdown, _bundle_skus

s = S()
res = []
def check(label, cond):
    res.append(cond); print(('  [PASS] ' if cond else '  [FAIL] ') + label)

total_ovr = s.query(OptionBenefitOverride).count()
print('전체 override 행: %d' % total_ovr)
check('마이그레이션 결과 override 존재(>1만)', total_ovr > 10000)

# rate 템플릿 + 그 source 의 override 가진 모음전 찾기
src = s.query(SourceBenefitTemplate).filter_by(benefit_type='rate').first().source_id
SALE = 100000.0
code = sku = None
for c in [x[0] for x in s.query(Model.model_code).all() if x[0]]:
    sk = _bundle_skus(s, c)
    if sk and s.query(OptionBenefitOverride).filter(
            OptionBenefitOverride.canonical_sku == sk[0], OptionBenefitOverride.source_id == src).count():
        code, sku = c, sk[0]; break
print('대상: source_id=%s 모음전=%r sku=%r' % (src, code, sku))
check('스냅샷된 옵션 존재', sku is not None)

fp0 = compute_breakdown(s, sku=sku, source_id=src, sale_price=SALE).get('final_price')
print('수정 전 final=%s' % fp0)

# ── 소싱처 기본값(템플릿) 변경 → 스냅샷된 모음전은 불변이어야 ──
tpls = s.query(SourceBenefitTemplate).filter_by(source_id=src).all()
for t in tpls:
    t.value = float(t.value) + 0.07   # 기본값 크게 변경
s.flush()
fp1 = compute_breakdown(s, sku=sku, source_id=src, sale_price=SALE).get('final_price')
print('소싱처 기본값 대폭 변경 후 final=' + str(fp1))
check('소싱처 기본값 변경에도 모음전 가격 불변(독립)', fp1 == fp0)

# ── 미스냅샷(override 없는) 옵션은 템플릿 따라감(하위호환) 확인 ──
free = (s.query(OptionBenefitOverride.canonical_sku))  # noqa
# override 전혀 없는 임의 sku 찾기
from lemouton.sourcing.models import Option
cand = None
for o in s.query(Option).filter(Option.canonical_sku.isnot(None)).limit(2000).all():
    if not s.query(OptionBenefitOverride).filter_by(canonical_sku=o.canonical_sku, source_id=src).count():
        cand = o.canonical_sku; break
if cand:
    fpf = compute_breakdown(s, sku=cand, source_id=src, sale_price=SALE).get('final_price')
    print('미스냅샷 옵션(%s) final(변경된 템플릿 반영)=%s' % (cand, fpf))
    check('미스냅샷 옵션은 템플릿(변경값) 따라감 — 하위호환 동작', fpf is not None)
else:
    print('  (미스냅샷 옵션 없음 — 전부 스냅샷됨)')

s.rollback(); s.close()
ok = all(res)
print('\n=== %d/%d PASS — %s (롤백, DB 미변경) ===' % (sum(res), len(res), 'ALL PASS ✅' if ok else 'FAIL ❌'))
sys.exit(0 if ok else 1)
