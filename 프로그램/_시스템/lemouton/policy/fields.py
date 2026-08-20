"""마켓별 정책 항목표.

🔴 **기본 정책 13항목은 여기서 만들지 않는다.**
   대량등록 「데이터 가공」이 쓰는 `lemouton/registration/process_rule_schema.py` 가
   이미 단일 진실 원천이고, 라이브에서 검증된 정의다. 그걸 **그대로 불러 쓴다**.
   여기 베껴 두면 두 벌이 갈려서, 대량등록에서 항목이 바뀌어도 정책 화면은 뒤처진다
   (이 프로그램에서 반복적으로 사고가 났던 그 형태).

   사장님 확정 2026-07-30 — 「마켓별 정책 기본정책 항목에 대량등록 데이터 가공에
   들어가는 가공 규칙 13항목 내용들 넣고 싶어」

   차이는 하나뿐: 대량등록은 「모든 마켓 공통」 한 벌, 여기는 **마켓마다 한 벌**.

이 파일이 직접 정의하는 것은 **마켓별 예외**뿐 — 13항목에 없고 그 마켓에만 있는 규칙.
"""
from __future__ import annotations

from lemouton.registration.process_rule_schema import all_schemas

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

# ── 「마켓 공통」 ────────────────────────────────────────────────────────
#  진짜 마켓이 아니라 **값을 담아두는 자리**다. 여기 채워 두고 마켓으로 넣거나,
#  마켓 쪽에서 불러온다. MARKET_KEYS 에 넣지 않는다 — 넣으면 전송 대상이 된다.
COMMON_KEY = 'common'
COMMON_LABEL = '마켓 공통'


# ── 마켓별 예외 — 13항목에 없고 그 마켓에만 있는 것 (노션 「(4) 마켓별 기타 정책」) ──
#   only 가 걸린 항목은 그 마켓 탭에만 나온다.
EXTRA_ITEMS: list[dict] = [
    {
        'key': '_winner', 'label': '위너일 때 가격', 'spec_ref': '노션 (4) 마켓별 기타',
        'note': '쿠팡 전용 — 위너를 뺏겼을 때 어떻게 할지.', 'only': ['coupang'],
        'fields': [
            {'key': 'rule', 'label': '위너 가격 규칙', 'type': 'choice',
             'default': '', 'choices': ['따라가지 않음', '최저가 −1원', '최저가와 같게'],
             'hint': '', 'unit': '', 'item_shape': '', 'columns': []},
            {'key': 'floor', 'label': '이 값 밑으로는 안 내림', 'type': 'int',
             'default': 0, 'choices': [], 'hint': '최종매입가 기준', 'unit': '원',
             'item_shape': '', 'columns': []},
        ],
    },
    # [2026-08-01] '_size_unify'(사이즈별 가격 통일)는 **판매가 항목 안으로 옮겼다**
    #   (확정 K3 — process_rule_schema.py 의 price.size_unify).
    #   가격을 정하는 규칙이 판매가와 떨어져 있으면 판매가만 채우고 지나친다.
    #   스스 전용도 아니게 됐다 — 가격 템플릿은 6마켓 모두 이 규칙을 갖고 있었다.
    {
        'key': '_site_discount', 'label': '사이트 부담 지원할인', 'spec_ref': '노션 (2) 기본 정책',
        'note': 'G마켓·옥션·롯데온만 있는 항목.', 'only': ['gmarket', 'auction', 'lotteon'],
        'fields': [
            {'key': 'amount', 'label': '지원할인 금액', 'type': 'int', 'default': 0,
             'choices': [], 'hint': '', 'unit': '원', 'item_shape': '', 'columns': []},
        ],
    },
    {
        'key': '_max_per_person', 'label': '인당 최대 구매수', 'spec_ref': '노션 (2) 기본 정책',
        'note': '쿠팡만 있는 항목.', 'only': ['coupang'],
        'fields': [
            {'key': 'count', 'label': '한 사람이 살 수 있는 최대 수량', 'type': 'int',
             'default': 0, 'choices': [], 'hint': '0 = 제한 없음', 'unit': '개',
             'item_shape': '', 'columns': []},
        ],
    },
    # ── [2026-08-12] 사장님 엑셀 대조 — 그 마켓 등록 API 에만 있는 칸 ──────────
    {
        'key': '_parallel_import', 'label': '병행수입 여부',
        'spec_ref': '엑셀 「기타」 · 쿠팡 items.parallelImported[필수]',
        'note': '쿠팡 등록 API 가 필수로 요구합니다.', 'only': ['coupang'],
        'fields': [
            {'key': 'mode', 'label': '병행수입', 'type': 'choice', 'default': '병행수입 아님',
             'choices': ['병행수입 아님', '병행수입'], 'hint': '', 'unit': '',
             'item_shape': '', 'columns': []},
        ],
    },
    # ── [2026-08-13 사장님 확정] 자동 가격 조정 — **쿠팡만 해당** ─────────────
    #   쿠팡 공지(2026-05-22): 상품 생성/수정 API 에 items.autoPricingInfo
    #   {minSalePrice, active} 가 생겼다. 승인 요청 **전에만** 넣을 수 있고,
    #   승인 뒤에는 [옵션 단위 가격 변경] API 의 apMinSalePrice·apActive 로 바꾼다.
    #   🔴 minSalePrice 는 **판매가보다 작아야** 하고, apMinSalePrice·apActive 는
    #     **함께 보내야** 한다(하나만 보내면 400). 다른 마켓엔 이 칸이 없다.
    {
        'key': '_auto_pricing', 'label': '자동 가격 조정',
        'spec_ref': '쿠팡 items.autoPricingInfo · 공지 2026-05-22',
        'note': '쿠팡만 있는 항목입니다. 최저가는 판매가보다 낮아야 합니다.',
        'only': ['coupang'],
        'fields': [
            {'key': 'mode', 'label': '자동 가격 조정', 'type': 'choice', 'default': '안 씀',
             'choices': ['안 씀', '씀 — 최저가를 마진율로 계산', '씀 — 최저가 직접 입력'],
             'hint': '켜면 쿠팡이 최저가까지 알아서 가격을 내립니다', 'unit': '',
             'item_shape': '', 'columns': []},
            {'key': 'min_margin_pct', 'label': '최저 마진율', 'type': 'int', 'default': 0,
             'choices': [], 'hint': '「마진율로 계산」을 고른 경우에만 씁니다', 'unit': '%',
             'item_shape': '', 'columns': []},
            {'key': 'min_price', 'label': '최저 판매가', 'type': 'int', 'default': 0,
             'choices': [], 'hint': '「직접 입력」을 고른 경우에만 씁니다 — 판매가보다 낮아야 합니다',
             'unit': '원', 'item_shape': '', 'columns': []},
        ],
    },
    {
        'key': '_sell_method', 'label': '판매방식',
        'spec_ref': '엑셀 「상품주요정보」 · 11번가 selMthdCd[필수]',
        'note': '11번가 등록 API 가 필수로 요구합니다. 사장님 엑셀 = 고정가판매.',
        'only': ['eleven11'],
        'fields': [
            {'key': 'mode', 'label': '판매방식', 'type': 'choice', 'default': '고정가판매',
             'choices': ['고정가판매', '예약판매'], 'hint': '중고판매는 쓰지 않습니다',
             'unit': '', 'item_shape': '', 'columns': []},
        ],
    },
]

# 가격을 계산에 쓰려면 반드시 정해야 하는 항목
PRICE_REQUIRED_ITEMS = ('price',)


def base_items() -> list[dict]:
    """대량등록 가공 규칙 13항목 — 정의를 그대로 가져온다(베끼지 않는다)."""
    return [dict(s, only=None) for s in all_schemas()]


def items_for(market: str) -> list[dict]:
    """그 마켓에 해당하는 항목만. 13항목 + 그 마켓 전용 예외.

    market=COMMON_KEY 면 **13항목만** 준다 — 「쿠팡만 있는 항목」을 공통에 두면
    어느 마켓으로 넣을지 정해지지 않는다.
    """
    out = base_items()
    if market == COMMON_KEY:
        return out
    out += [dict(it) for it in EXTRA_ITEMS
            if not it.get('only') or market in it['only']]
    return out


def item_keys_for(market: str) -> list[str]:
    return [it['key'] for it in items_for(market)]


def all_item_keys() -> set[str]:
    return {it['key'] for it in base_items()} | {it['key'] for it in EXTRA_ITEMS}


def label_of(item_key: str) -> str:
    for it in base_items() + EXTRA_ITEMS:
        if it['key'] == item_key:
            return it['label']
    return item_key
