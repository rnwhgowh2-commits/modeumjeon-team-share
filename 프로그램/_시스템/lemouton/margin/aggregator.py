# -*- coding: utf-8 -*-
r"""매칭 결과 -> 요약 + 6종 집계 (마켓/일별/월별/브랜드/금액대/상품).

원본: C:\dev\대량등록 마진계산기\app.py `_aggregate` (903행) -- 기계적 추출.
summary dict 의 키 구조는 프론트가 그대로 읽으므로 바꾸지 않는다.
소싱처 확인 카운터(card_sourcing 등)는 3 범위 -- result_rows 에 '소싱처확인결과' 키가
없으므로 1 에서는 자동으로 0 이 된다. 삭제하지 말 것.
"""
import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)


def aggregate(result_rows, price_ranges):
    """매칭 결과 집계 — 레거시 UI 가 기대하는 한글 필드명으로 출력.

    price_ranges: [(min, max, label), ...] tuple 리스트.
    """
    if not result_rows:
        return {
            'summary': {},
            'market': [], 'daily': [], 'monthly': [],
            'brand': [], 'priceRange': [],
            'filters': {'brands': [], 'markets': [], 'priceRange': []},
            'reconcile': {'총매출': 0, 'Σ마켓별': 0, 'Σ브랜드별': 0, '일치': True,
                          '더망고만': 0, '샵마인만': 0, '마켓미확정': 0},
            'brand_unresolved': {'건수': 0, '매출': 0, '상품명': []},
        }

    df = pd.DataFrame(result_rows)

    # ★ 주문미이행 only (메모 s/p/x/empty + 매입흔적 X) 만 집계 제외
    #   매입흔적 (송장/URL/구매가)은 일반 마진 분류 → 합계 포함 (사용자 요청)
    if '_주문미이행' in df.columns:
        before = len(df)
        mask_unful = df['_주문미이행'].fillna(False).apply(lambda v: bool(v) is True)
        if '_매입흔적' in df.columns:
            mask_trace = df['_매입흔적'].fillna(False).apply(lambda v: bool(v) is True)
            mask_drop  = mask_unful & ~mask_trace   # 주문미이행 AND NOT 매입흔적
        else:
            mask_drop = mask_unful
        df = df[~mask_drop].copy().reset_index(drop=True)
        if before != len(df):
            logger.info(f"_aggregate: 주문미이행 only {before - len(df)}건 집계 제외 (matched={before} → {len(df)} / 매입흔적은 포함)")

    # 분류 파이프라인 (classified) 행과 매칭 파이프라인 (matched) 행을 모두 지원.
    # 분류 행에는 '구매가격'/'수량_매출'/'마켓'/'이상가' 등이 없을 수 있으므로
    # 누락된 컬럼은 안전한 기본값으로 보강한다.
    if '구매가격' not in df.columns:
        df['구매가격'] = df['매입가'] if '매입가' in df.columns else 0
    if '수량_매출' not in df.columns:
        df['수량_매출'] = df['수량'] if '수량' in df.columns else 1
    if '정산예상금액' not in df.columns:
        df['정산예상금액'] = df['정산'] if '정산' in df.columns else 0
    if '마켓' not in df.columns:
        df['마켓'] = df['판매처'] if '판매처' in df.columns else ''
    if '주문일' not in df.columns:
        df['주문일'] = ''

    # 주문일 파싱 ('26.04.08' 또는 ISO 포맷 모두 대응)
    def _parse_date(s):
        s = str(s).strip()
        for fmt in ('%y.%m.%d', '%Y-%m-%d', '%Y.%m.%d'):
            try:
                return datetime.strptime(s[:10] if fmt == '%Y-%m-%d' else s, fmt).date()
            except Exception:
                continue
        return None

    df['_date'] = df['주문일'].apply(_parse_date)
    df['일자']  = df['_date'].apply(lambda d: d.strftime('%Y-%m-%d') if d else '')
    df['월']    = df['_date'].apply(lambda d: d.strftime('%Y-%m') if d else '')

    # 금액대 분류
    label_order = [lbl for lo, hi, lbl in price_ranges]

    def _classify(price):
        for lo, hi, lbl in price_ranges:
            if lo <= price < hi:
                return lbl
        return '기타'

    # 판매가(=단가×수량) 우선 사용, 없으면 단가×수량_매출 으로 계산 (과거 데이터 호환)
    if '판매가' not in df.columns:
        df['판매가'] = df['단가'].fillna(0) * df['수량_매출'].fillna(1)

    # 금액대는 판매가(수량 반영) 기준
    df['금액대'] = df['판매가'].apply(_classify)

    def _agg(g):
        매출  = g['판매가'].sum()
        매입  = g['구매가격'].sum()
        순마진 = g['순마진'].sum()
        건수  = len(g)
        마진율 = (순마진 / 매출 * 100) if 매출 > 0 else 0
        return {
            '매출':   int(round(매출)),
            '매입':   int(round(매입)),
            '순마진': int(round(순마진)),
            '건수':   int(건수),
            '마진율': round(float(마진율), 2),
        }

    def _groupby_records(data, col):
        result = []
        for key, grp in data.groupby(col):
            row = _agg(grp)
            row[col] = key
            result.append(row)
        return result

    total_매출   = df['판매가'].sum()
    total_정산   = df['정산예상금액'].sum() if '정산예상금액' in df.columns else 0
    total_실결제 = df['실결제금액'].sum()   if '실결제금액'   in df.columns else 0
    total_매입   = df['구매가격'].sum()
    total_순마진 = df['순마진'].sum()
    avg_마진율   = (total_순마진 / total_매출 * 100) if total_매출 > 0 else 0

    # 이상가 제외 집계
    if '이상가' in df.columns:
        normal = df[df['이상가'] == False]
    else:
        normal = df
    normal_매출   = normal['판매가'].sum()
    normal_매입   = normal['구매가격'].sum()
    normal_순마진 = normal['순마진'].sum()
    normal_마진율 = (normal_순마진 / normal_매출 * 100) if normal_매출 > 0 else 0
    이상가건수 = int(len(df) - len(normal))

    # ── 소싱처 확인 현황 (Task 7) ──
    # 간단메모에 http URL 이 포함되어 있고 아직 확인 안 한 건 / 확인 완료된 건 카운트
    card_sourcing_need = 0
    card_sourcing_done = 0
    for r in result_rows:
        has_url = '간단메모' in r and str(r.get('간단메모', '')).find('http') >= 0
        result = r.get('소싱처확인결과', '')
        if result:
            card_sourcing_done += 1
        elif has_url:
            card_sourcing_need += 1

    # ── 블랙스팟 카드 집계 (Phase 2c) ──
    # 카드 집계 기준: 더망고 기준 (매칭 + 더망고만) — 샵마인만 제외
    # 블랙스팟 판단의 핵심은 실제 사용자가 주문한 건(더망고) 이므로.
    # _aggregate 는 matched 기반이라 '데이터출처' 필드가 없을 수 있음.
    # 그 경우 아래 기본 카드 카운트는 0 으로 두고, api_analyze 에서
    # store['classified'] 기반 카드 카운트를 덮어쓴다 (_compute_card_counts).
    mango_based = [
        r for r in result_rows
        if r.get('데이터출처') in ('더망고+샵마인', '더망고만')
    ]
    shopmine_only_count = sum(
        1 for r in result_rows if r.get('데이터출처') == '샵마인만'
    )

    immediate_check = 0
    sourcing_check = 0
    market_check = 0
    normal_count = 0
    pending_count = 0
    kkadaegi_count = 0
    margin_issue = 0

    # 상호 배타(exclusive) 카드 집계 — 한 행이 한 카드에만 카운트됨.
    # 마진 이상은 별도(중첩) 집계.
    for row in mango_based:
        detail = row.get('상세분류', '')
        code = detail.split('_')[0] if detail else ''
        need_s = bool(row.get('소싱처확인필요'))
        need_m = bool(row.get('마켓확인필요'))
        is_margin = code in ('1-2', '1-3')
        is_normal_code = (
            code in ('1-1', '3-1', '3-2', '4-1', '5-1', '5-2', '5-3')
            or '정상' in detail
        )
        is_pending_code = code in ('1-11', '2-9', '3-9', '4-9')
        is_kkadaegi_code = code in ('1-12', '2-10', '3-10', '4-10')

        if is_kkadaegi_code:
            kkadaegi_count += 1
        elif need_s and need_m:
            immediate_check += 1
        elif need_s and not need_m:
            sourcing_check += 1
        elif need_m and not need_s:
            market_check += 1
        elif is_normal_code:
            normal_count += 1
        elif is_pending_code:
            pending_count += 1

        if is_margin:
            margin_issue += 1  # 중첩 집계

    summary = {
        '총매출':     int(round(total_매출)),
        '총실결제':   int(round(total_실결제)),
        '총정산':     int(round(total_정산)),
        '총매입':     int(round(total_매입)),
        '총순마진':   int(round(total_순마진)),
        '평균마진율': round(float(avg_마진율), 2),
        '매칭건수':   int(len(df)),
        '고유상품수': int(df['상품코드'].nunique()) if '상품코드' in df.columns else 0,
        '정상매출':   int(round(normal_매출)),
        '정상매입':   int(round(normal_매입)),
        '정상순마진': int(round(normal_순마진)),
        '정상마진율': round(float(normal_마진율), 2),
        '이상가건수': 이상가건수,
        'card_sourcing_need': card_sourcing_need,
        'card_sourcing_done': card_sourcing_done,
        # ── Phase 2c: 블랙스팟 7카드 집계 ──
        'card_all':                  len(mango_based),
        'card_immediate':            immediate_check,
        'card_sourcing':             sourcing_check,
        'card_market':               market_check,
        'card_normal':               normal_count,
        'card_pending':              pending_count,
        'card_kkadaegi':             kkadaegi_count,
        'card_margin':               margin_issue,
        'card_shopmine_only_count':  shopmine_only_count,
    }

    ndf = normal

    market_rows = _groupby_records(ndf, '마켓')

    daily_rows = _groupby_records(ndf[ndf['일자'] != ''], '일자')
    daily_rows.sort(key=lambda r: r['일자'])

    monthly_rows = _groupby_records(ndf[ndf['월'] != ''], '월')
    monthly_rows.sort(key=lambda r: r['월'])

    brand_rows = _groupby_records(ndf, '브랜드')
    brand_rows.sort(key=lambda r: r['매출'], reverse=True)

    price_rows = _groupby_records(ndf, '금액대')
    label_idx = {lbl: i for i, lbl in enumerate(label_order)}
    price_rows.sort(key=lambda r: label_idx.get(r['금액대'], 999))

    # 상품별 집계 — 상품코드 + 상품명 조합 키로 묶어 레거시 UI 의 상품별 탭 지원
    if '상품코드' in ndf.columns:
        product_rows = []
        for (code, name), grp in ndf.groupby(['상품코드', '상품명']):
            row = _agg(grp)
            row['상품코드'] = code or ''
            row['상품명']   = name or ''
            row['마켓'] = ', '.join(sorted(grp['마켓'].dropna().unique().tolist()))
            product_rows.append(row)
        product_rows.sort(key=lambda r: r['매출'], reverse=True)
    else:
        product_rows = []

    filters = {
        'brands':     sorted(df['브랜드'].dropna().unique().tolist()) if '브랜드' in df.columns else [],
        'markets':    sorted(df['마켓'].dropna().unique().tolist())   if '마켓'   in df.columns else [],
        'priceRange': label_order,
    }

    # ── 정합성 검산 + 브랜드 미확정 (원본 _aggregate 추적 — 요약 검산 칩·브랜드 배너용) ──
    _sum_market = sum(r['매출'] for r in market_rows)
    _sum_brand  = sum(r['매출'] for r in brand_rows)
    reconcile = {
        '총매출':    int(round(total_매출)),
        'Σ마켓별':  int(_sum_market),
        'Σ브랜드별': int(_sum_brand),
        '일치':      bool(_sum_market == int(round(total_매출)) == _sum_brand),
    }
    _src = df['데이터출처'] if '데이터출처' in df.columns else pd.Series([], dtype=str)
    reconcile['더망고만'] = int((_src == '더망고만').sum())
    reconcile['샵마인만'] = int((_src == '샵마인만').sum())
    reconcile['마켓미확정'] = int((df['마켓'].fillna('').astype(str).str.strip() == '').sum()) if '마켓' in df.columns else 0

    _mj = df[df['브랜드'] == '미확정'] if '브랜드' in df.columns else df.iloc[0:0]
    brand_unresolved = {
        '건수':   int(len(_mj)),
        '매출':   int(round(_mj['판매가'].sum())) if len(_mj) else 0,
        '상품명': sorted(_mj['상품명'].dropna().astype(str).unique().tolist()) if len(_mj) else [],
    }

    return {
        'summary':    summary,
        'market':     market_rows,
        'daily':      daily_rows,
        'monthly':    monthly_rows,
        'brand':      brand_rows,
        'priceRange': price_rows,
        'product':    product_rows,
        'filters':    filters,
        'reconcile':  reconcile,
        'brand_unresolved': brand_unresolved,
    }
