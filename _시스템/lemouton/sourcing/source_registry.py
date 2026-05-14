"""소싱처 레지스트리 — 신규 소싱처 추가 시 이 list 한 줄만 추가하면 UI 자동 노출.

key      = BundleSourceUrl.source_key 와 동일 (legacy: url_<key> 컬럼명)
label    = 사용자 노출 이름
brand    = brand-app-logo CSS 클래스
glyph    = 로고 텍스트 (1~2자)
crawler  = 어댑터 존재 여부 (False = UI 만, 크롤 미지원 → 회색 표시)
legacy   = Model.url_<key> 컬럼 보유 여부 (True = legacy sync 대상)
"""

SOURCES = [
    {'key': 'lemouton',    'label': '르무통 공홈',         'brand': 'lemouton',   'glyph': '르', 'crawler': True,  'legacy': True},
    {'key': 'musinsa',     'label': '무신사',              'brand': 'musinsa',    'glyph': 'M',  'crawler': True,  'legacy': True},
    {'key': 'ssf',         'label': 'SSF샵',               'brand': 'ssf',        'glyph': 'SS', 'crawler': True,  'legacy': True},
    {'key': 'lotteon',     'label': '롯데온',              'brand': 'lotteon',    'glyph': '롯', 'crawler': True,  'legacy': True},
    {'key': 'ss_lemouton', 'label': '스마트스토어 르무통', 'brand': 'smartstore', 'glyph': 'N',  'crawler': True,  'legacy': True},
]


def get_keys():
    return [s['key'] for s in SOURCES]


def get_labels():
    return {s['key']: s['label'] for s in SOURCES}


def is_legacy(key):
    for s in SOURCES:
        if s['key'] == key:
            return s.get('legacy', False)
    return False
