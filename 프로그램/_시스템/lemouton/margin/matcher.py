# -*- coding: utf-8 -*-
"""매칭 엔진.

`match_data`: 더망고 매입 DF ↔ 샵마인 매출 DF 3단계 매칭.
Stage 1: 주문번호 + 상품코드 + 옵션(정규화)
Stage 2: 주문번호 + 상품코드
Stage 3: 주문번호만
"""
import re
import logging
from collections import defaultdict

import pandas as pd

from lemouton.margin.config import MARKET_MAP, MARKET_REVERSE

logger = logging.getLogger(__name__)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def normalize_order_number(order_num, market_name):
    """주문번호 정규화 (단일값, 하위호환).
    스마트스토어: '1234(5678)' → 괄호 안 숫자 추출.
    그 외: strip 만.
    """
    s = str(order_num).strip()
    if '스마트스토어' in str(market_name):
        m = re.search(r'\((\d+)\)', s)
        if m:
            return m.group(1)
    return s


def order_match_keys(order_num, market_name):
    """매칭용 후보 키 list 반환 (사용자 요구: 괄호 밖/안 둘 다 시도).
    스마트스토어 'A(B)' → [A, B] 둘 중 하나가 샵마인 오픈마켓주문번호와 매칭되면 성공.
    그 외 마켓: [원본 1개].
    """
    s = str(order_num).strip()
    if '스마트스토어' in str(market_name):
        m = re.search(r'(\d+)\s*\(\s*(\d+)\s*\)', s)
        if m:
            return [m.group(1), m.group(2)]
    return [s] if s else []


def extract_product_code(product_name):
    """상품명에서 5자리 이상 숫자 마지막 매칭값 추출."""
    try:
        if pd.isna(product_name):
            return ''
    except (TypeError, ValueError):
        pass
    matches = re.findall(r'\d{5,}', str(product_name))
    return matches[-1] if matches else ''


KNOWN_BRANDS = [
    'NATIONAL GEOGRAPHIC', 'NATIONALGEOGRAPHIC', 'NATIONAL GEOGRAPHIC KIDS',
    'CODES COMBINE INNERWEAR', 'CODES COMBINE',
    'EMPORIO ARMANI', 'EMPORIO ARMANI UNDERWEAR',
    'BEANPOLE KIDS', 'BEANPOLE',
    'THE NORTH FACE', 'NORTH FACE',
    'WACKY WILLY', 'SAINT BARNET',
    'PARTIMENTO WOMEN', 'PARTIMENTO',
    'JANSPORT', 'KODAK', 'KODAK APPAREL',
    'TOPTEN KIDS', 'TOPTEN',
    'TRILLION',
    'CGP', 'EIDER', 'PUMA', 'ARENA',
    '나이키', '아디다스', '푸마', '코오롱스포츠',
    '파르티멘토', '와키윌리', '잔스포츠', '코닥',
    '노스페이스', '빈폴키즈', '빈폴', '폴햄',
    '탑텐키즈', '탑텐', '트릴리온',
    '오르시떼', '에이더',
    'LEE', 'NIKE', 'CGP', 'ORCITE',
]
BRAND_NORMALIZE = {
    'NATIONAL GEOGRAPHIC': '내셔널지오그래픽', 'NATIONALGEOGRAPHIC': '내셔널지오그래픽',
    'NATIONAL GEOGRAPHIC KIDS': '내셔널지오그래픽',
    'CODES COMBINE INNERWEAR': '코데즈컴바인', 'CODES COMBINE': '코데즈컴바인',
    'EMPORIO ARMANI UNDERWEAR': '엠포리오아르마니', 'EMPORIO ARMANI': '엠포리오아르마니',
    'THE NORTH FACE': '노스페이스', 'NORTH FACE': '노스페이스', '노스페이스': '노스페이스',
    'BEANPOLE KIDS': '빈폴키즈', 'BEANPOLE': '빈폴', '빈폴키즈': '빈폴키즈', '빈폴': '빈폴',
    'WACKY WILLY': '와키윌리', '와키윌리': '와키윌리',
    'SAINT BARNET': '세인트바넷',
    'PARTIMENTO WOMEN': '파르티멘토', 'PARTIMENTO': '파르티멘토', '파르티멘토': '파르티멘토',
    'JANSPORT': '잔스포츠', '잔스포츠': '잔스포츠',
    'KODAK': '코닥', 'KODAK APPAREL': '코닥', '코닥': '코닥',
    'TOPTEN KIDS': '탑텐키즈', 'TOPTEN': '탑텐', '탑텐키즈': '탑텐키즈', '탑텐': '탑텐',
    'TRILLION': '트릴리온', '트릴리온': '트릴리온',
    'CGP': '씨지피', 'EIDER': '에이더', 'PUMA': '푸마', 'ARENA': '아레나',
    '나이키': '나이키', 'NIKE': '나이키',
    '아디다스': '아디다스',
    '푸마': '푸마', '코오롱스포츠': '코오롱스포츠',
    '폴햄': '폴햄',
    'LEE': '리', 'Lee': '리',
    'ORCITE': '오르시떼', '오르시떼': '오르시떼',
    '에이더': '에이더',
}
KNOWN_BRANDS.sort(key=len, reverse=True)


def extract_brand(product_name):
    """상품명에서 브랜드 추출. 사전 매칭 → 나이키 모델 → fallback."""
    try:
        if pd.isna(product_name):
            return '기타'
    except (TypeError, ValueError):
        pass
    s = str(product_name)
    s_upper = s.upper()

    for brand in KNOWN_BRANDS:
        if brand.upper() in s_upper:
            return BRAND_NORMALIZE.get(brand, brand)

    nike_models = ['에어맥스', '에어포스', '코트 비전', '조던', '덩크', 'P-6000',
                   '빅토리', '킬샷', '플렉스', '보메로', '코르테즈', 'V5 RNR',
                   '윈드러너', '챌린저', '스톰', 'NSW', '드라이 핏', '폼 러너',
                   '레트로', '프로 웜업', '스포츠웨어', '런 스위프트', '런 디파이',
                   '스탠다드 이슈', '카와 슬라이드', '에브리데이 플러스']
    for model in nike_models:
        if model in s:
            return '나이키'

    cleaned = re.sub(r'<[^>]+>', '', s)
    cleaned = re.sub(r'\[[^\]]*\]\s*', '', cleaned)

    if re.search(r'\b[A-Z]{2}\d{4}', s):
        m2 = re.search(r'매장정품[>]?\s+([가-힣]{1,4})\s', cleaned)
        if m2 and m2.group(1) not in ['탑텐', '빈폴', '코닥', '폴햄', '아레나']:
            return '나이키'

    m = re.search(r'매장정품\s+(\S+)', cleaned)
    if m:
        word = m.group(1)
        if not word.isdigit():
            return BRAND_NORMALIZE.get(word, word)

    return '기타'


def normalize_option(option_text):
    """옵션 텍스트 정규화: 수량접미사 제거 + 구분자 통일 + 알파벳 정렬."""
    try:
        if pd.isna(option_text):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(option_text).strip()
    s = re.sub(r'[-/]\d+개\s*$', '', s).strip()
    s = re.sub(r'[,:/\s]+', '|', s)
    parts = [p.strip() for p in s.split('|') if p.strip()]
    parts.sort()
    return '|'.join(parts)


# ── 핵심 매칭 엔진 ────────────────────────────────────────────────────────

def match_data(buy_df, sell_df):
    """더망고 매입 ↔ 샵마인 매출 3단계 매칭.

    Returns:
        (result_rows, unmatched_buy_rows, unmatched_sell_rows)
    """
    buy = buy_df.copy()
    # ★ 사용자 요구: 스마트스토어 'A(B)' 형태에서 A 와 B 둘 다 매칭 시도.
    buy['_order_keys'] = buy.apply(
        lambda r: order_match_keys(r['마켓주문번호'], r['마켓명']), axis=1
    )
    # 하위호환: 단일 키 (마지막 후보 = 스마트스토어면 괄호 안)
    buy['_order_key'] = buy['_order_keys'].apply(lambda l: l[-1] if l else '')
    buy['_product_code']  = buy['마켓상품명'].apply(extract_product_code)
    buy['_brand']         = buy['마켓상품명'].apply(extract_brand)
    buy['_option_norm']   = buy['옵션1'].apply(normalize_option)
    buy['_market_std']    = buy['마켓명'].map(MARKET_MAP).fillna(buy['마켓명'])

    sell = sell_df.copy()

    def _sell_order_key(v):
        if pd.isna(v):
            return ''
        try:
            return str(v.item()) if hasattr(v, 'item') else str(int(v))
        except (ValueError, TypeError, OverflowError):
            s = str(v).strip()
            if s.endswith('.0'):
                s = s[:-2]
            return s

    sell['_order_key']    = sell['오픈마켓주문번호'].apply(_sell_order_key)
    sell['_product_code'] = sell['상품명'].apply(extract_product_code)
    sell['_brand']        = sell['상품명'].apply(extract_brand)
    sell['_option_norm']  = sell['옵션'].apply(normalize_option) if '옵션' in sell.columns else ''

    result_rows = []
    matched_buy_idx  = set()
    matched_sell_idx = set()

    def _make_result_row(b_row, s_row, match_type):
        settlement  = pd.to_numeric(s_row.get('정산예상금액_배송비포함', 0), errors='coerce') or 0
        buy_price   = pd.to_numeric(b_row.get('구매가격', 0), errors='coerce') or 0
        sell_price  = pd.to_numeric(s_row.get('단가', 0), errors='coerce') or 0
        qty         = int(pd.to_numeric(s_row.get('수량', 1), errors='coerce') or 1)
        sales_total = sell_price * qty          # 판매가 = 단가 × 수량
        margin      = settlement - buy_price
        margin_rate = (margin / sales_total * 100) if sales_total > 0 else 0

        shopname = str(s_row.get('쇼핑몰', ''))
        market_display = MARKET_REVERSE.get(shopname, shopname)
        fee_rate = str(s_row.get('수수료율', ''))

        return {
            '주문일':        str(s_row.get('주문일', '')),
            '마켓':          market_display,
            '상품명':        str(s_row.get('상품명', '')),
            '브랜드':        b_row.get('_brand', '기타'),
            '옵션_매출':     str(s_row.get('옵션', '')) if '옵션' in s_row else '',
            '옵션_매입':     str(b_row.get('옵션1', '')),
            '단가':          sell_price,
            '판매가':        sales_total,          # 단가 × 수량 (총 판매액)
            '실결제금액':    pd.to_numeric(s_row.get('실결제금액', 0), errors='coerce') or 0,
            '정산예상금액':  settlement,
            '구매가격':      buy_price,
            '순마진':        margin,
            '마진율':        round(margin_rate, 2),  # 판매가 기준
            '수수료율':      fee_rate,
            '수량_매출':     qty,
            '수령인':        str(s_row.get('수취고객명', '')),
            '상품코드':      b_row.get('_product_code', ''),
            '매칭타입':      match_type,
            '마켓주문번호':  b_row.get('_order_key', ''),
            # ── 전체내역 상세/소싱처/필터 용 buy_row 원본 정보 보강 ──
            '간단메모':                  str(b_row.get('간단메모', '') or ''),
            '사이트주문번호':            str(b_row.get('사이트주문번호', '') or ''),
            '국내송장번호':              str(b_row.get('국내송장번호', '') or ''),
            '국내송장번호 택배사':       str(b_row.get('국내송장번호 택배사', '') or ''),
            '더망고주문상태 (사용자 연동)': str(b_row.get('더망고주문상태 (사용자 연동)', '') or ''),
            '마켓주문상태 (오픈 마켓 연동)': str(b_row.get('마켓주문상태 (오픈 마켓 연동)', '') or ''),
            '마켓주문일자':              str(b_row.get('마켓주문일자', '') or ''),
            '수령인명':                  str(b_row.get('수령인명', '') or s_row.get('수취고객명', '') or ''),
            '마켓상품명':                str(b_row.get('마켓상품명', '') or ''),
            # 샵마인 측 정보
            '샵마인_주문상태':           str(s_row.get('주문상태', '') or ''),
            '샵마인_샵마인주문상태':     str(s_row.get('샵마인주문상태', '') or ''),
            '샵마인_정산예상금액(배송비포함)': str(s_row.get('정산예상금액_배송비포함', '') or ''),
            '샵마인_송장입력':           str(s_row.get('송장입력', '') or ''),
        }

    # Stage 1: 주문번호 + 상품코드 + 옵션
    for bi, br in buy[~buy.index.isin(matched_buy_idx)].iterrows():
        cands = sell[
            (~sell.index.isin(matched_sell_idx)) &
            (sell['_order_key'].isin(br['_order_keys'])) &
            (sell['_product_code'] == br['_product_code']) &
            (sell['_option_norm']  == br['_option_norm'])
        ]
        if cands.empty:
            continue
        si = cands.index[0]
        result_rows.append(_make_result_row(br, sell.loc[si], '정밀'))
        matched_buy_idx.add(bi)
        matched_sell_idx.add(si)

    # Stage 2: 주문번호 + 상품코드
    for bi, br in buy[~buy.index.isin(matched_buy_idx)].iterrows():
        cands = sell[
            (~sell.index.isin(matched_sell_idx)) &
            (sell['_order_key'].isin(br['_order_keys'])) &
            (sell['_product_code'] == br['_product_code'])
        ]
        if cands.empty:
            continue
        si = cands.index[0]
        result_rows.append(_make_result_row(br, sell.loc[si], '기본'))
        matched_buy_idx.add(bi)
        matched_sell_idx.add(si)

    # Stage 3: 주문번호만
    for bi, br in buy[~buy.index.isin(matched_buy_idx)].iterrows():
        cands = sell[
            (~sell.index.isin(matched_sell_idx)) &
            (sell['_order_key'].isin(br['_order_keys']))
        ]
        if cands.empty:
            continue
        si = cands.index[0]
        result_rows.append(_make_result_row(br, sell.loc[si], '주문번호'))
        matched_buy_idx.add(bi)
        matched_sell_idx.add(si)

    # 미매칭 수집
    unmatched_buy_idx  = set(buy.index)  - matched_buy_idx
    unmatched_sell_idx = set(sell.index) - matched_sell_idx
    unmatched_buy_df   = buy[buy.index.isin(unmatched_buy_idx)]
    unmatched_sell_df  = sell[sell.index.isin(unmatched_sell_idx)]

    # 2차 수령인 이름 매칭 (참고용)
    sell_names = set(unmatched_sell_df['수취고객명'].dropna().astype(str))
    buy_names  = set(unmatched_buy_df['수령인명'].dropna().astype(str))

    status_cols = [c for c in buy.columns
                   if any(k in str(c) for k in ['주문상태', '마켓상태', '상태', '취소', '교환', '반품', 'status'])]

    unmatched_buy_rows = []
    for _, br in unmatched_buy_df.iterrows():
        name = str(br.get('수령인명', ''))
        matched_names = [n for n in sell_names if n == name]
        remarks = []
        for sc in status_cols:
            val = str(br.get(sc, '')).strip()
            if val and val != 'nan':
                remarks.append(f'{sc}:{val}')
        unmatched_buy_rows.append({
            '주문일':         str(br.get('마켓주문일자', '')),
            '마켓주문번호':   str(br.get('마켓주문번호', '')),
            '마켓명':         str(br.get('마켓명', '')),
            '상품명':         str(br.get('마켓상품명', '')),
            '옵션':           str(br.get('옵션1', '')),
            '구매가격':       pd.to_numeric(br.get('구매가격', 0), errors='coerce') or 0,
            '수령인':         name,
            '수령인_2차매칭': ', '.join(matched_names),
            '비고':           ' / '.join(remarks),
            # ★ V4/V1 — 클라이언트 매입흔적 5기준 판정용
            '사이트주문번호': str(br.get('사이트주문번호', '')),
            '국내송장번호':   str(br.get('국내송장번호', '')),
            '간단메모':       str(br.get('간단메모', '')),
            '더망고주문상태 (사용자 연동)': str(br.get('더망고주문상태 (사용자 연동)', '')),
        })

    unmatched_sell_rows = []
    for _, sr in unmatched_sell_df.iterrows():
        name = str(sr.get('수취고객명', ''))
        matched_names = [n for n in buy_names if n == name]
        unmatched_sell_rows.append({
            '주문일':         str(sr.get('주문일', '')),
            '마켓주문번호':   str(sr.get('오픈마켓주문번호', '')),
            '쇼핑몰':         str(sr.get('쇼핑몰', '')),
            '상품명':         str(sr.get('상품명', '')),
            '옵션':           str(sr.get('옵션', '')) if '옵션' in sr else '',
            '단가':           pd.to_numeric(sr.get('단가', 0), errors='coerce') or 0,
            '정산예상금액':   pd.to_numeric(sr.get('정산예상금액_배송비포함', 0), errors='coerce') or 0,
            '수령인':         name,
            '수령인_2차매칭': ', '.join(matched_names),
            '비고':           '',
        })

    # 플래그
    name_to_orders = defaultdict(set)
    for r in result_rows:
        name_to_orders[r['수령인']].add(r['마켓주문번호'])

    for r in result_rows:
        orders = name_to_orders[r['수령인']]
        r['동일인연속'] = len(orders) > 1
        r['수량2이상']  = r['수량_매출'] >= 2
        # 이상가 판정: 판매가(=단가×수량) 기준으로 매입비가 3배 초과하거나 매입 50만원 초과
        r['이상가'] = (
            (r['구매가격'] > r['판매가'] * 3 and r['판매가'] > 0) or
            r['구매가격'] > 500000
        )

    logger.info(
        f"매칭 결과: matched={len(result_rows)}, "
        f"unmatched_buy={len(unmatched_buy_rows)}, "
        f"unmatched_sell={len(unmatched_sell_rows)}"
    )
    return result_rows, unmatched_buy_rows, unmatched_sell_rows


# ── 블랙스팟 분류 엔진용 양방향 매칭 ──────────────────────────────────────

def match_for_classifier(mango_df, shopmine_df):
    """classifier 가 요구하는 형태로 양방향 매칭.

    같은 주문번호에 정상건(SETTLEMENT_O_EXACT) 이 있으면 대표 행으로 선택하고,
    '샵마인_정상건존재' 플래그를 True 로 설정 — classifier 가 최우선 정산 O 판정.

    Returns:
        {
            "matched":         [dict, ...],  # 더망고 행 + '샵마인_*' 필드
            "mango_unmatched": [dict, ...],  # 더망고에만 있는 행
            "shopmine_only":   [dict, ...],  # 샵마인에만 있는 행
        }
    """
    from lemouton.margin.config import SETTLEMENT_O_EXACT, SETTLEMENT_X_EXCEPT_TO_O, SHOPMINE_COLS

    mango_key    = '마켓주문번호'
    shopmine_key = SHOPMINE_COLS.get('order_no', '오픈마켓주문번호')
    status_col   = SHOPMINE_COLS.get('order_status', '주문상태')

    if mango_df.empty and shopmine_df.empty:
        return {"matched": [], "mango_unmatched": [], "shopmine_only": []}

    # 주문번호별 그룹핑 (정상 + 클레임 공존 시 정상건 우선)
    shopmine_by_order = {}
    for _, row in shopmine_df.iterrows():
        key = str(row.get(shopmine_key, '')).strip()
        if not key:
            continue
        shopmine_by_order.setdefault(key, []).append(row.to_dict())

    shopmine_lookup       = {}
    shopmine_has_normal   = {}
    shopmine_all_statuses = {}
    for key, rows in shopmine_by_order.items():
        statuses = [str(r.get(status_col, '')).strip() for r in rows]
        has_normal = any(
            s in SETTLEMENT_O_EXACT or s in SETTLEMENT_X_EXCEPT_TO_O
            for s in statuses
        )
        if has_normal:
            rep = next(
                (r for r in rows
                 if str(r.get(status_col, '')).strip() in SETTLEMENT_O_EXACT
                 or str(r.get(status_col, '')).strip() in SETTLEMENT_X_EXCEPT_TO_O),
                rows[0]
            )
        else:
            rep = rows[0]
        shopmine_lookup[key]       = rep
        shopmine_has_normal[key]   = has_normal
        shopmine_all_statuses[key] = statuses

    matched = []
    mango_unmatched = []
    matched_shopmine_keys = set()

    for _, mango_row in mango_df.iterrows():
        row_dict = mango_row.to_dict()
        mango_order = str(row_dict.get(mango_key, '')).strip()
        mango_market = str(row_dict.get('마켓명', '')).strip()

        # ★ 스마트스토어 'A(B)' 양측 매칭: 후보 키 list 로 lookup
        candidate_keys = order_match_keys(mango_order, mango_market) if mango_order else []
        matched_key = next((k for k in candidate_keys if k in shopmine_lookup), None)

        if matched_key:
            shopmine_row = shopmine_lookup[matched_key]
            for col, val in shopmine_row.items():
                row_dict[f"샵마인_{col}"] = val
            row_dict["샵마인_매칭"]       = True
            row_dict["샵마인_정상건존재"] = shopmine_has_normal.get(matched_key, False)
            row_dict["샵마인_모든주문상태"] = " | ".join(shopmine_all_statuses.get(matched_key, []))
            matched.append(row_dict)
            matched_shopmine_keys.add(matched_key)
        else:
            row_dict["샵마인_매칭"] = False
            mango_unmatched.append(row_dict)

    shopmine_only = []
    for _, row in shopmine_df.iterrows():
        key = str(row.get(shopmine_key, '')).strip()
        if key and key not in matched_shopmine_keys:
            shopmine_only.append(row.to_dict())

    logger.info(
        f"classifier용 매칭: matched={len(matched)}, "
        f"mango_unmatched={len(mango_unmatched)}, "
        f"shopmine_only={len(shopmine_only)}"
    )
    return {
        "matched":         matched,
        "mango_unmatched": mango_unmatched,
        "shopmine_only":   shopmine_only,
    }
