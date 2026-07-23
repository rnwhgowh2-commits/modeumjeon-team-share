# -*- coding: utf-8 -*-
"""T11 — 혜택엔진 전후 회귀 스냅샷 러너 + diff (머지 게이트 증거 도구).

결과 문서: docs/검증/2026-07-23-혜택엔진-가격diff.md
플랜: docs/superpowers/plans/2026-07-22-소싱처-표면노출가-혜택-최종매입가.md Task 11

사용법 (각 워크트리의 프로그램/_시스템 을 cwd 로):
  ① 스냅샷 (base 워크트리와 브랜치 워크트리에서 각각):
       DATABASE_URL=sqlite:///<완전 새 파일.db> python scripts/benefit_fx_snapshot_t11.py snap <out.json>
  ② diff:
       python scripts/benefit_fx_snapshot_t11.py diff <base.json> <head.json>

원칙:
  · DB 는 매 실행 완전 새 SQLite — 부팅과 같은 순서(create_all → 경량 마이그레이션 →
    SourceRegistry 라이브 배치 1~6 → seed_purchase_cards → seed_source_benefits).
    base 커밋에서는 base 코드의 시드만 들어간다(그 차이가 곧 비교 대상).
  · 시나리오 데이터 = OptionSourceUrl + SourceProduct(dynamic_benefits_json) 만,
    수동 템플릿 0 → diff = 시드/엔진 변경분만 반영.
  · 실 DB(Supabase/운영 SQLite)에는 절대 붙지 않는다 — sqlite 가드로 강제.
"""
import io
import json
import os
import sys

SURFACE = 100000.0

# (이름, source_id — api_benefits 계산 번호 체계, SourceProduct.site, dynamic_benefits)
SCENARIOS = [
    ('lemouton_plain',            1, 'lemouton',    {}),
    ('ss_lemouton_plain',         2, 'ss_lemouton', {}),
    ('musinsa_money0',            3, 'musinsa',
     {'surface_price': 100000, 'money_reward_amount': 0, 'money_active': False}),
    ('musinsa_money2000',         3, 'musinsa',
     {'surface_price': 100000, 'money_reward_amount': 2000, 'money_active': True}),
    ('musinsa_money4000',         3, 'musinsa',
     {'surface_price': 100000, 'money_reward_amount': 4000, 'money_active': True}),
    ('ssf_point_half_pct',        4, 'ssf', {'point_rate': 0.005}),
    ('ssf_gift9000_point5pct',    4, 'ssf',
     {'gift_point_amount': 9000, 'point_rate': 0.05}),
    ('lotteon_plain_owners',      5, 'lotteon', {'lotte_member_discount_rate': 0.005}),
    ('lotteon_maxprice_nocard',   5, 'lotteon',
     {'lotteon_max_price': 75630, 'lotteon_card_discounts': [],
      'lotte_member_discount_rate': 0.005}),
    ('lotteon_maxprice_hyundai',  5, 'lotteon',
     {'lotteon_max_price': 100000,
      'lotteon_card_discounts': [{'label': '현대카드', 'amount': 3000, 'rate': 3}],
      'lotte_member_discount_rate': 0.005}),
    ('ssg_money2pct',             6, 'ssg',
     {'ssg_money_rate': 0.02, 'ssg_money_text': '상시 2% 적립'}),
    ('hmall_empty',               'key:hmall', 'hmall', {}),
    ('hmall_typical',             'key:hmall', 'hmall',
     {'hmall_point_amount': 3000, 'hmall_card_discount': 5000}),
    ('lotteimall_empty',          'key:lotteimall', 'lotteimall', {}),
    ('lotteimall_typical',        'key:lotteimall', 'lotteimall',
     {'point_rewards': {'default_point': 2000}, 'lotteimall_card_discount': 7000}),
]

# tests/conftest.py 미러 — 전 모델 등록 후 create_all (FK 타겟 누락 방지)
MODEL_MODULES = [
    'lemouton.sourcing.models', 'lemouton.sourcing.models_pricing',
    'lemouton.pricing.settings', 'lemouton.uploader.models',
    'lemouton.templates.models', 'lemouton.inventory.models',
    'lemouton.sets.models', 'lemouton.margin.models',
    'lemouton.delivery.models', 'lemouton.sources.models',
    'lemouton.sourcing.models_v2', 'lemouton.multitenancy.models',
    'lemouton.audit.models', 'lemouton.mapping.models',
    'lemouton.registration.models', 'webapp.auth.models',
    'webapp.icon_store_model', 'webapp.server_ip_model',
]


def run_snapshot(out_path):
    os.environ.setdefault('ENVIRONMENT', 'test')
    for _m in MODEL_MODULES:
        try:
            __import__(_m)
        except ImportError:
            pass

    from shared.db import Base, engine, SessionLocal, _apply_lightweight_migrations

    assert engine.url.get_backend_name() == 'sqlite', (
        '스냅샷은 완전 새 SQLite 전용(DATABASE_URL=sqlite:///...) — 현재 %s'
        % (engine.url,))

    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()

    from lemouton.sourcing.models_pricing import SourceRegistry, OptionSourceUrl
    from lemouton.sources.models import SourceProduct
    from webapp.routes.api_benefits import compute_breakdown

    s = SessionLocal()
    # SourceRegistry 라이브 배치 — tests/pricing/test_source_benefit_seed.py 와 동일
    s.add_all([
        SourceRegistry(id=1, name='르무통 공홈', main_url='https://www.lemouton.co.kr'),
        SourceRegistry(id=2, name='스스 르무통',
                       main_url='https://smartstore.naver.com/lemouton'),
        SourceRegistry(id=3, name='무신사', main_url='https://musinsa.com'),
        SourceRegistry(id=4, name='SSF', main_url='https://ssfshop.com'),
        SourceRegistry(id=5, name='롯데온', main_url='https://lotteon.com'),
        SourceRegistry(id=6, name='SSG', main_url='https://www.ssg.com'),
    ])
    s.commit()

    # 부팅 시드 그대로 (shared/db.py init_db 순서) — 각 버전이 자기 시드만 심는다
    seed_report = {}
    try:
        from lemouton.margin.purchase_card_store import seed_purchase_cards
        seed_report['purchase_cards'] = seed_purchase_cards(s)
    except ImportError:
        seed_report['purchase_cards'] = 'N/A'
    try:
        from lemouton.sourcing.source_benefit_seed import seed_source_benefits
        seed_report['source_benefits'] = seed_source_benefits(s)
    except ImportError:
        seed_report['source_benefits'] = 'N/A'

    for name, sid, site, dyn in SCENARIOS:
        url = 'https://example.test/t11/%s' % name
        s.add(OptionSourceUrl(canonical_sku='T11-%s' % name, source_id=sid,
                              product_url=url))
        s.add(SourceProduct(site=site, url=url,
                            dynamic_benefits_json=json.dumps(dyn, ensure_ascii=False)))
    s.commit()

    out = {'seed_report': seed_report, 'scenarios': {}}
    for name, sid, site, dyn in SCENARIOS:
        r = compute_breakdown(s, sku='T11-%s' % name, source_id=sid,
                              sale_price=SURFACE)
        out['scenarios'][name] = {
            'source_id': str(sid),
            'dyn': dyn,
            'base_price': r.get('sale_price'),
            'final_price': r.get('final_price'),
            'steps': [
                {'name': st.get('name'), 'type': st.get('type'),
                 'value': round(float(st.get('value') or 0), 6),
                 'deduct': st.get('deduct')}
                for st in (r.get('steps') or [])
            ],
        }
    s.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print('wrote %s : %d scenarios, seeds=%s'
          % (out_path, len(out['scenarios']), seed_report))


def run_diff(base_path, head_path):
    base = json.load(open(base_path, encoding='utf-8'))
    head = json.load(open(head_path, encoding='utf-8'))

    def fmt(st):
        if st is None:
            return '(없음)'
        return '%s %s deduct=%s' % (st['type'], st['value'], format(st['deduct'], ','))

    names = list(head['scenarios'].keys())
    n_diff = 0
    for n in names:
        b, h = base['scenarios'][n], head['scenarios'][n]
        if (b['final_price'] == h['final_price'] and b['steps'] == h['steps']
                and b['base_price'] == h['base_price']):
            print('== %s: final %s (동일)' % (n, format(h['final_price'], ',')))
            continue
        n_diff += 1
        print('** %s: final %s -> %s | base %s -> %s'
              % (n, format(b['final_price'], ','), format(h['final_price'], ','),
                 format(b['base_price'], ','), format(h['base_price'], ',')))
        bs = {st['name']: st for st in b['steps']}
        hs = {st['name']: st for st in h['steps']}
        for k in list(bs) + [k for k in hs if k not in bs]:
            if bs.get(k) != hs.get(k):
                print('     %s: %s  ->  %s' % (k, fmt(bs.get(k)), fmt(hs.get(k))))
    print('\n총 %d 시나리오 / diff %d건' % (len(names), n_diff))


if __name__ == '__main__':
    # 윈도우 cp949 콘솔에서 한글/유니코드 출력 안전
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.path.insert(0, os.getcwd())
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'snap' and len(sys.argv) == 3:
        run_snapshot(sys.argv[2])
    elif mode == 'diff' and len(sys.argv) == 4:
        run_diff(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)
