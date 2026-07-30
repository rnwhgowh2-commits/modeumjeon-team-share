"""마켓별 정책 항목표 — 단일 진실 원천.

노션 「상품 가공 (정책 생성 & 정책 적용)」 본문 그대로 옮겼다.
항목이 늘거나 마켓이 늘면 **여기만** 고친다.

🔴 노션에 「(2) 마켓별 기본 정책 ※ 더망고 캡처 보낼 것」이라고 적혀 있다.
   그 캡처는 사장님 컴퓨터에만 있어 못 봤다. 그래서 **노션 본문에 적힌 항목명 그대로만**
   넣었다. 캡처를 받으면 이 파일만 고치면 화면이 따라 바뀐다.

🔴 값은 **비워 둔다**. 수수료율·마진율을 임의 기본값으로 채우면 그 숫자가 그대로
   마켓에 나간다(가격 오류 = 금전 손실). 사장님이 채우기 전까지 계산에 쓰지 않는다.
"""
from __future__ import annotations

# 마켓 — 화면 가로탭 순서
MARKETS: list[tuple[str, str]] = [
    ('smartstore', '스마트스토어'),
    ('coupang', '쿠팡'),
    ('gmarket', 'G마켓'),
    ('auction', '옥션'),
    ('eleven11', '11번가'),
    ('lotteon', '롯데온'),
]
MARKET_KEYS = [k for k, _ in MARKETS]
MARKET_LABEL = dict(MARKETS)

# 항목 타입 — text / num / rate(%) / money(원) / select / bool
# only: 그 마켓에만 있는 항목 (비우면 전 마켓 공통)
GROUPS: list[dict] = [
    {
        'key': 'axis', 'name': '옵션 축 구성', 'icon': '🧩',
        'desc': '같은 옵션을 마켓마다 1축·2축·3축 중 어떻게 쪼개 올릴지.',
        'fields': [
            {'key': 'axis_count', 'name': '옵션 축 수', 'type': 'select',
             'options': ['1축 (한 줄로)', '2축 (색상·사이즈)', '3축 (모델·색상·사이즈)'],
             'hint': '1축이면 「블랙 260」처럼 한 줄, 2·3축이면 나눠서 올라갑니다.'},
            {'key': 'axis_names', 'name': '축 이름', 'type': 'text',
             'hint': '쉼표로. 예) 색상, 사이즈'},
        ],
    },
    {
        'key': 'basic', 'name': '기본 정책', 'icon': '📋',
        'desc': '마켓에 올릴 때 항상 같이 나가는 값들. (노션 본문 항목 그대로)',
        'fields': [
            {'key': 'product_name_rule', 'name': '상품명 규칙', 'type': 'text',
             'hint': '예) [브랜드] 상품명 (색상)'},
            {'key': 'category', 'name': '카테고리', 'type': 'text'},
            {'key': 'sale_price_rule', 'name': '판매가 규칙', 'type': 'text'},
            {'key': 'site_discount', 'name': '사이트 부담 지원할인', 'type': 'money',
             'only': ['gmarket', 'lotteon'],
             'hint': 'G마켓·롯데온만 있는 항목입니다.'},
            {'key': 'option_rule', 'name': '옵션 표기', 'type': 'text'},
            {'key': 'image_rule', 'name': '이미지', 'type': 'text'},
            {'key': 'detail_rule', 'name': '상세페이지', 'type': 'text'},
            {'key': 'ship_days', 'name': '배송 기간(일)', 'type': 'num'},
            {'key': 'ship_from', 'name': '출하지', 'type': 'text'},
            {'key': 'return_courier', 'name': '반품·교환 택배사', 'type': 'text'},
            {'key': 'return_to', 'name': '회송지', 'type': 'text'},
            {'key': 'notice_info', 'name': '고시정보', 'type': 'text'},
            {'key': 'brand', 'name': '브랜드', 'type': 'text'},
            {'key': 'origin', 'name': '원산지', 'type': 'text'},
            {'key': 'as_message', 'name': 'AS 안내 문구', 'type': 'text',
             'hint': '스마트스토어는 A/S 번호를 함께 넣어야 합니다.'},
            {'key': 'tags', 'name': '태그', 'type': 'text',
             'only': ['smartstore', 'coupang']},
            {'key': 'banned_words', 'name': '금지어', 'type': 'text'},
            {'key': 'bundle_ship', 'name': '묶음배송 정책', 'type': 'text',
             'only': ['smartstore', 'coupang']},
            {'key': 'max_per_person', 'name': '인당 최대 구매수', 'type': 'num',
             'only': ['coupang']},
        ],
    },
    {
        'key': 'price', 'name': '가격 정책', 'icon': '💲',
        'desc': '🔴 값이 비어 있으면 가격 계산에 쓰지 않습니다. 임의 숫자로 채우지 않았습니다.',
        'fields': [
            {'key': 'fee_rate', 'name': '마켓 수수료율(%)', 'type': 'rate'},
            {'key': 'margin_rate', 'name': '마진율(%)', 'type': 'rate'},
            {'key': 'ship_fee_type', 'name': '배송비 방식', 'type': 'select',
             'options': ['무료', '유료', '조건부 무료', '수량별']},
            {'key': 'ship_fee', 'name': '배송비(원)', 'type': 'money'},
            {'key': 'ship_free_over', 'name': '조건부 무료 기준(원)', 'type': 'money'},
            {'key': 'island_fee', 'name': '제주·도서산간 추가(원)', 'type': 'money'},
            {'key': 'return_fee', 'name': '반품비(원)', 'type': 'money'},
            {'key': 'exchange_fee', 'name': '교환비(원)', 'type': 'money'},
            {'key': 'option_extra', 'name': '옵션별 추가금(원)', 'type': 'money'},
        ],
    },
    {
        'key': 'etc', 'name': '마켓별 예외', 'icon': '⚠️',
        'desc': '그 마켓에만 있는 규칙.',
        'fields': [
            {'key': 'winner_price_rule', 'name': '위너일 때 가격 규칙', 'type': 'text',
             'only': ['coupang'], 'hint': '쿠팡 전용.'},
            {'key': 'size_price_unify', 'name': '사이즈별 가격 통일', 'type': 'select',
             'options': ['통일 안 함', '가장 비싼 값으로', '가장 싼 값으로'],
             'only': ['smartstore'], 'hint': '스마트스토어 전용.'},
        ],
    },
]

GROUP_BY_KEY = {g['key']: g for g in GROUPS}


def fields_for(market: str) -> list[dict]:
    """그 마켓에 해당하는 항목만 (only 가 걸린 항목은 걸러낸다)."""
    out = []
    for g in GROUPS:
        fs = [f for f in g['fields'] if not f.get('only') or market in f['only']]
        if fs:
            out.append({**g, 'fields': fs})
    return out


def all_field_keys() -> set[str]:
    return {f['key'] for g in GROUPS for f in g['fields']}
