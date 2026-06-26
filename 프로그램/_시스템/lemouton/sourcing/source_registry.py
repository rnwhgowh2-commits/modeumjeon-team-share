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
    {'key': 'ssg',         'label': 'SSG',                 'brand': 'ssg',        'glyph': 'SG', 'crawler': False, 'legacy': False, 'logo_color': '#F47216', 'builtin': True},
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


# ════════════════════════════════════════════════════════════
#  소싱처 카탈로그 (2026-06-26) — 프로그램/_시스템/docs/크롤링-가이드.md §1·§2 의 소싱처 목록.
#  모달 '신규 소싱처 추가' 탭이 이 카탈로그를 검색·추가한다(시안 D).
#  단일 진실 원천: builtin 6 은 SOURCES 와 key 일치. 신규(롯데아이몰 등)는 여기 한 줄
#  추가 → 추가 시 SourcingSource 로 전역 등록되어 UI/API/매트릭스 자동 노출.
#  crawl_method/stock_rule/benefit/has_adapter = 가이드 표 그대로(상세 미리보기용).
# ════════════════════════════════════════════════════════════
SOURCE_CATALOG = [
    {'key': 'lemouton', 'label': '르무통 공홈', 'glyph': '르', 'logo_color': '#a78bfa',
     'domain': 'lemouton.co.kr', 'crawl_method': 'HTML(Cafe24)',
     'stock_rule': 'option_stock_data 파싱 → 실조합·실재고', 'benefit': '-',
     'has_adapter': True, 'needs_login': False},
    {'key': 'musinsa', 'label': '무신사', 'glyph': 'M', 'logo_color': '#191F28',
     'domain': 'musinsa.com', 'crawl_method': 'API(POST)',
     'stock_rule': 'outOfStock→0 / 잔여 N개→실수량 / 표시없음→999',
     'benefit': 'member_price·등급적립·무신사머니', 'has_adapter': True, 'needs_login': True},
    {'key': 'ssf', 'label': 'SSF샵', 'glyph': 'SS', 'logo_color': '#14b8a6',
     'domain': 'ssfshop.com', 'crawl_method': 'HTML(curl_cffi)',
     'stock_rule': 'statCd=SLDOUT→품절 / 품절임박(N)→실수량',
     'benefit': 'point_rate(멤버십)·gift_point(기프트)', 'has_adapter': True, 'needs_login': False},
    {'key': 'ssg', 'label': 'SSG', 'glyph': 'sg', 'logo_color': '#F47216',
     'domain': 'ssg.com', 'crawl_method': 'SSR <script> JS',
     'stock_rule': 'usablInvQty 정규식 (0→품절, else 실수량)',
     'benefit': 'ssg_money·card_benefit·product_coupon', 'has_adapter': True, 'needs_login': False},
    {'key': 'lotteon', 'label': '롯데온', 'glyph': '롯', 'logo_color': '#ef4444',
     'domain': 'lotteon.com', 'crawl_method': 'API 우선 → DOM 폴백',
     'stock_rule': '옵션매핑 실수량 / soldout→0 / else 999',
     'benefit': 'lotte_member_discount·store_jjim_coupon', 'has_adapter': True, 'needs_login': False},
    {'key': 'ss_lemouton', 'label': '스마트스토어 르무통', 'glyph': 'N', 'logo_color': '#22c55e',
     'domain': 'smartstore.naver.com', 'crawl_method': '확장 n/v2 per-SKU(로그인)',
     'stock_rule': 'sku_stock (0=품절·N=실수량) → current_stock 영속',
     'benefit': '-', 'has_adapter': True, 'needs_login': True},
    {'key': 'lotteimall', 'label': '롯데아이몰', 'glyph': '롯i', 'logo_color': '#ED1C24',
     'domain': 'lotteimall.com', 'crawl_method': 'API→DOM (어댑터 준비중)',
     'stock_rule': 'itemInvQtyInfo.inv_qty (준비중)',
     'benefit': 'point_rewards(L.POINT)', 'has_adapter': False, 'needs_login': False},
    {'key': 'hmall', 'label': '현대H몰', 'glyph': 'H', 'logo_color': '#00A05B',
     'domain': 'hmall.com', 'crawl_method': '내장 __NEXT_DATA__ (어댑터 준비중)',
     'stock_rule': 'itemPtc.stockList[].stockCount (0=품절·N=실수량)',
     'benefit': 'H.Point 적립·카드 즉시할인', 'has_adapter': False, 'needs_login': False},
]

_BUILTIN_KEYS = {s['key'] for s in SOURCES}


def get_catalog():
    """소싱처 카탈로그(크롤링 가이드 기준) 복사본 반환."""
    return [dict(c) for c in SOURCE_CATALOG]


def is_builtin_key(key):
    """builtin 6개 소싱처 key 여부."""
    return key in _BUILTIN_KEYS


def get_catalog_entry(key):
    """카탈로그 단건 조회 (없으면 None)."""
    for c in SOURCE_CATALOG:
        if c['key'] == key:
            return dict(c)
    return None
