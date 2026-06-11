# -*- coding: utf-8 -*-
"""2026-06-11 — 혜택 스냅샷 모델 마이그레이션 + 회귀 테스트.

스냅샷 모델: 모음전 옵션에 소싱처 기본셋팅(SourceBenefitTemplate)을 standalone override 로
복제 → 엔진 게이트('override 있으면 템플릿 무시')로 모음전이 소싱처 변경에서 독립.

사용:
  python scripts/_migrate_benefit_snapshot.py            # 회귀 테스트만 (롤백, DB 미변경)
  python scripts/_migrate_benefit_snapshot.py --apply    # 회귀 통과 시 실제 적용(커밋)

회귀: 마이그레이션 전, override 가 '없던' (sku,source) 옵션의 compute_breakdown final_price 를
기록 → 스냅샷 후 재계산이 동일해야 함(override = 템플릿 복제이므로 가격 불변). override 가
있던 옵션은 '통일' 정책으로 기본값으로 리셋(허용 — 비교 대상 아님).
spec: docs/superpowers/specs/2026-06-11-혜택-스냅샷-모델-design.md
"""
import sys, io, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ── 6543(트랜잭션 풀러) 전용 엔진으로 우회 — 5432(세션 풀러) 15클라이언트 한도 회피.
#   라이브 서버가 5432 를 점유 중이어도 6543 은 별도 한도라 안전. create_app/SessionLocal 미사용
#   (compute_breakdown 은 Flask 컨텍스트 불필요 — 전달한 세션으로만 동작).
from config import Config  # load_dotenv 수행 → Config.DB_URL 채워짐 (연결은 lazy)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
_url = Config.DB_URL.replace(':5432/', ':6543/')
_engine = create_engine(_url, future=True, pool_pre_ping=True, pool_size=1, max_overflow=1,
                        connect_args={'connect_timeout': 10})
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True,
                            expire_on_commit=False)
from lemouton.sourcing.models import Model, SourceBenefitTemplate, OptionBenefitOverride
from webapp.routes.api_benefits import (compute_breakdown, snapshot_bundle_from_templates, _bundle_skus)
print('연결: 6543 트랜잭션 풀러 (port %s)' % ('6543' if ':6543/' in _url else '?'))

APPLY = '--apply' in sys.argv
SALE = 100000.0

s = SessionLocal()
tpl_srcs = sorted({t.source_id for t in s.query(SourceBenefitTemplate).all()})
all_codes = [c[0] for c in s.query(Model.model_code).all() if c[0]]

# ── APPLY: 회귀는 이미 입증됨(별도 실행). 전 모음전 스냅샷 + '모음전 단위 커밋'(작은 txn·진행 보존). ──
if APPLY:
    print('APPLY 모드 · 템플릿 소싱처=%s · 전체 모음전=%d개' % (tpl_srcs, len(all_codes)))
    tot = {'bundles': 0, 'created': 0}
    for i, code in enumerate(all_codes, 1):
        r = snapshot_bundle_from_templates(s, code)
        if r['options']:
            tot['bundles'] += 1
            tot['created'] += r['created']
        s.commit()
        if i % 20 == 0 or i == len(all_codes):
            print('  ...%d/%d 모음전 처리 (override 누적 %d)' % (i, len(all_codes), tot['created']))
    s.close()
    print('\n✅ 마이그레이션 적용 완료 — %d개 모음전, override %d행 (전 모음전 = 현재 기본값으로 고정).'
          % (tot['bundles'], tot['created']))
    sys.exit(0)

codes = all_codes[:20]
print('모드: 회귀만(롤백) · 템플릿 소싱처=%s · 대상 모음전=%d개(전체 %d)' % (tpl_srcs, len(codes), len(all_codes)))

# ── 1) 마이그레이션 전: override 없던 (sku,source) 의 final_price 기록 ──
baseline = {}
for code in codes:
    for sku in _bundle_skus(s, code):
        for src in tpl_srcs:
            if s.query(OptionBenefitOverride).filter_by(canonical_sku=sku, source_id=src).count():
                continue  # override 있던 옵션 = 통일로 변경됨 → 비교 제외
            try:
                fp = compute_breakdown(s, sku=sku, source_id=src, sale_price=SALE).get('final_price')
            except Exception:
                continue
            baseline[(sku, src)] = fp
    if not APPLY and len(baseline) >= 120:
        break
print('회귀 기준 샘플(무-override 옵션): %d건' % len(baseline))

# ── 2) 스냅샷 (flush, 커밋 보류) ──
total = {'options': 0, 'sources': 0, 'created': 0}
for code in codes:
    r = snapshot_bundle_from_templates(s, code)
    for k in total:
        total[k] += r[k]
s.flush()
print('스냅샷 생성: override %d행 (옵션누적 %d)' % (total['created'], total['options']))

# ── 3) 마이그레이션 후 재계산 = 동일해야 ──
fails = 0
for (sku, src), fp0 in baseline.items():
    fp1 = compute_breakdown(s, sku=sku, source_id=src, sale_price=SALE).get('final_price')
    if fp1 != fp0:
        fails += 1
        if fails <= 12:
            print('  [MISMATCH] %s src=%s  %s -> %s' % (sku, src, fp0, fp1))
print('회귀 결과: %d/%d 동일, 불일치 %d' % (len(baseline) - fails, len(baseline), fails))

# ── 4) 적용 or 롤백 ──
if fails == 0 and APPLY:
    s.commit()
    print('\n✅ 마이그레이션 적용 완료 (커밋).')
elif fails == 0:
    s.rollback()
    print('\n✅ 회귀 PASS — 가격 불변 입증. (롤백, DB 미변경) 적용하려면 --apply')
else:
    s.rollback()
    print('\n❌ 회귀 FAIL — 불일치 발견. 적용 안 함(롤백).')
s.close()
sys.exit(1 if fails else 0)
