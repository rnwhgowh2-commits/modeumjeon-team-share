"""소싱처 레지스트리 — 신규 소싱처 추가 시 이 list 한 줄만 추가하면 UI 자동 노출.

key      = BundleSourceUrl.source_key 와 동일 (legacy: url_<key> 컬럼명)
label    = 사용자 노출 이름
brand    = brand-app-logo CSS 클래스
glyph    = 로고 텍스트 (1~2자)
crawler  = 어댑터 존재 여부 (False = UI 만, 크롤 미지원 → 회색 표시)
legacy   = Model.url_<key> 컬럼 보유 여부 (True = legacy sync 대상)

v6 P5.5 (2026-05-17) — 사용자가 DB SourcingSource 에 추가한 신규 소싱처도
get_all_sources() 가 builtin + DB 합쳐서 반환. UI / API / 매트릭스 자동 노출.
"""

# Builtin 5 소싱처 (모든 환경에서 고정)
SOURCES = [
    {'key': 'lemouton',    'label': '르무통 공홈',         'brand': 'lemouton',   'glyph': '르', 'crawler': True,  'legacy': True,  'logo_color': '#191F28', 'builtin': True},
    {'key': 'musinsa',     'label': '무신사',              'brand': 'musinsa',    'glyph': 'M',  'crawler': True,  'legacy': True,  'logo_color': '#000000', 'builtin': True},
    {'key': 'ssf',         'label': 'SSF샵',               'brand': 'ssf',        'glyph': 'SS', 'crawler': True,  'legacy': True,  'logo_color': '#FF6B00', 'builtin': True},
    {'key': 'lotteon',     'label': '롯데온',              'brand': 'lotteon',    'glyph': '롯', 'crawler': True,  'legacy': True,  'logo_color': '#ED2025', 'builtin': True},
    {'key': 'ss_lemouton', 'label': '스마트스토어 르무통', 'brand': 'smartstore', 'glyph': 'N',  'crawler': True,  'legacy': True,  'logo_color': '#03C75A', 'builtin': True},
]


def get_keys():
    """Builtin keys only (legacy compat — Model.url_<key> 5개 컬럼)."""
    return [s['key'] for s in SOURCES]


def get_labels():
    """Builtin label map."""
    return {s['key']: s['label'] for s in SOURCES}


def is_legacy(key):
    """legacy=True 면 Model.url_<key> 컬럼 존재 (5 builtin 만)."""
    for s in SOURCES:
        if s['key'] == key:
            return s.get('legacy', False)
    return False


def get_all_sources(session=None):
    """builtin 5 + DB SourcingSource(is_active=True) 합쳐 dict list 반환.

    Note: 항상 자체 격리된 session 으로 조회 — 외부 session 트랜잭션과 격리해
    SourcingSource 조회 실패 시 외부 트랜잭션이 abort 되지 않게 함.
    (session 인자는 backward-compat 용이지만 무시됨 — 항상 새 session 생성)
    """
    out = list(SOURCES)
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models import SourcingSource
    except Exception:
        return out
    s2 = None
    try:
        s2 = SessionLocal()
        custom = (s2.query(SourcingSource)
                    .filter(SourcingSource.is_active.is_(True))
                    .order_by(SourcingSource.sort_order, SourcingSource.id)
                    .all())
        for c in custom:
            out.append({
                'key': c.source_key,
                'label': c.label,
                'brand': 'custom-' + c.source_key,
                'glyph': c.logo_letter or (c.label[:1].upper() if c.label else 'X'),
                'crawler': c.has_adapter,
                'legacy': False,  # builtin 아님 — BundleSourceUrl 만 사용
                'logo_color': c.logo_color or '#3182F6',
                'favicon_url': c.favicon_url,
                'domain': c.domain,
                'needs_login': c.needs_login,
                'builtin': False,
            })
    except Exception:
        # 테이블 미존재 / 컬럼 차이 등 — builtin 만 반환 (안전 fallback)
        try:
            if s2 is not None:
                s2.rollback()
        except Exception:
            pass
    finally:
        if s2 is not None:
            try:
                s2.close()
            except Exception:
                pass
    return out


def get_all_keys(session=None):
    """builtin + DB 합친 모든 source_key 리스트."""
    return [s['key'] for s in get_all_sources(session)]
