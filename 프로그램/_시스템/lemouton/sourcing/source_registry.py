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
    """소싱처 label map — builtin + DB 커스텀(hmall·롯데아이몰 등)까지.

    [2026-06-28] builtin 만 반환하면 매트릭스 컬럼/셀이 커스텀 소싱처를 'hmall' 같은
    영문 key 로 표기 → get_all_sources(builtin+SourcingSource) 라벨까지 합쳐 한글 표기.
    """
    out = {s['key']: s['label'] for s in SOURCES}
    try:
        for s in get_all_sources():
            out[s['key']] = s.get('label') or s['key']
    except Exception:
        pass
    return out


def is_legacy(key):
    """legacy=True 면 Model.url_<key> 컬럼 존재 (5 builtin 만)."""
    for s in SOURCES:
        if s['key'] == key:
            return s.get('legacy', False)
    return False


def seed_builtins():
    """[2026-06-30 단일명부] 빌트인 6개를 SourcingSource 에 멱등 seed.

    이미 source_key 가 있으면 skip → 라벨·로고 사용자 수정분 보존. 빌트인을 DB 에
    두어야 이름(껍데기) 수정이 가능해진다. 도메인/favicon 은 SOURCE_CATALOG 기준.
    """
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models import SourcingSource
    except Exception:
        return
    cat = {c['key']: c for c in SOURCE_CATALOG}
    s = SessionLocal()
    try:
        existing = {r[0] for r in s.query(SourcingSource.source_key).all()}
        for i, src in enumerate(SOURCES):
            k = src['key']
            if k in existing:
                continue
            c = cat.get(k, {})
            dom = c.get('domain') or (k + '.com')
            s.add(SourcingSource(
                source_key=k, label=src['label'], domain=dom,
                logo_color=src.get('logo_color'), logo_letter=src.get('glyph'),
                favicon_url=(f"https://{dom}/favicon.ico" if dom else None),
                needs_login=bool(c.get('needs_login', False)),
                has_adapter=bool(src.get('crawler', True)),
                is_active=True, is_builtin=True, sort_order=i + 1,
            ))
        s.commit()
    except Exception:
        try:
            s.rollback()
        except Exception:
            pass
    finally:
        s.close()


def get_all_sources(session=None):
    """전 소싱처 명부 — 하드코딩 SOURCES(기본값) 위에 DB SourcingSource 오버레이.

    [2026-06-30 단일명부] 빌트인을 DB 에 seed 하면 DB 라벨/로고가 하드코딩을 덮어써
    이름(껍데기) 수정이 전 표면에 반영된다. 빌트인이 아직 DB 에 없으면 SOURCES 폴백.
    key 로 머지 → 빌트인 중복 없음. DB 실패 시 SOURCES 만(안전).
    (session 인자는 backward-compat — 무시, 항상 새 session.)
    """
    by_key = {}
    for s in SOURCES:                                   # 기본값(폴백)
        by_key[s['key']] = dict(s)
    s2 = None
    try:
        from shared.db import SessionLocal
        from lemouton.sourcing.models import SourcingSource
        s2 = SessionLocal()
        rows = (s2.query(SourcingSource)
                  .filter(SourcingSource.is_active.is_(True))
                  .order_by(SourcingSource.sort_order, SourcingSource.id)
                  .all())
        for c in rows:
            base = by_key.get(c.source_key, {})
            merged = dict(base)
            merged.update({
                'key': c.source_key,
                'label': c.label or base.get('label') or c.source_key,
                'brand': base.get('brand', 'custom-' + c.source_key),
                'glyph': c.logo_letter or base.get('glyph') or (c.label[:1].upper() if c.label else 'X'),
                'crawler': base.get('crawler', True) if c.is_builtin else bool(c.has_adapter),
                'legacy': base.get('legacy', False),
                'logo_color': c.logo_color or base.get('logo_color') or '#3182F6',
                'favicon_url': c.favicon_url,
                'domain': c.domain,
                'needs_login': bool(c.needs_login),
                'builtin': bool(c.is_builtin) or base.get('builtin', False),
            })
            by_key[c.source_key] = merged
    except Exception:
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
    return list(by_key.values())


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
     'domain': 'lotteimall.com', 'crawl_method': 'SSR HTML→파싱 (확장 navGrab·WAF 우회)',
     'stock_rule': 'itemInvQtyInfo.inv_qty 단축·2축(색×사이즈) 3상태',
     # 2026-06-28 라이브 검증 완료(단품 13사이즈 3상태·색상모음전 97조합) → 크롤 지원.
     'benefit': 'point_rewards(L.POINT)', 'has_adapter': True, 'needs_login': False},
    {'key': 'hmall', 'label': '현대H몰', 'glyph': 'H', 'logo_color': '#00A05B',
     'domain': 'hmall.com', 'crawl_method': '내장 __NEXT_DATA__ (혜택은 확장 navGrab)',
     'stock_rule': 'itemPtc.stockList[] sellGbcd 품절판정+stockCount 실수량 (단품·모음전 공통, S21)',
     'benefit': 'H.Point 적립·카드 즉시할인', 'has_adapter': True, 'needs_login': False},
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


def domain_of(url):
    """URL → 등록가능 도메인(www·포트·경로 제거, 소문자). 빈 입력 → ''.

    예: 'https://www.hmall.com/md/pda/itemPtc?...' → 'hmall.com'
        'http://smartstore.naver.com/x' → 'smartstore.naver.com'
    서브도메인은 보존(smartstore.naver.com ≠ naver.com)하되 흔한 'www.'만 제거.
    """
    if not isinstance(url, str) or not url.strip():
        return ''
    from urllib.parse import urlparse
    host = urlparse(url.strip()).netloc.lower()
    if not host:                       # 스킴 없는 'hmall.com/x' 형태 폴백
        host = url.strip().lower().split('/')[0]
    host = host.split('@')[-1].split(':')[0]      # 인증정보·포트 제거
    if host.startswith('www.'):
        host = host[4:]
    return host


def catalog_by_domain(url):
    """URL 의 도메인이 카탈로그(빌트인 크롤 지원) 소싱처와 일치하면 그 엔트리, 없으면 None.

    도메인 suffix 매칭(상품 도메인이 카탈로그 도메인으로 끝나면 일치) — 서브도메인
    상품 URL(예: m.hmall.com)도 같은 소싱처로 잡는다.
    """
    d = domain_of(url)
    if not d:
        return None
    for c in SOURCE_CATALOG:
        cd = (c.get('domain') or '').lower()
        if cd and (d == cd or d.endswith('.' + cd)):
            return dict(c)
    return None
