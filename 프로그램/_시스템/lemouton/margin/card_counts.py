# -*- coding: utf-8 -*-
"""블랙스팟 카드 집계 — 원본 app.py:543-905 `_compute_card_counts` 를 그대로 이식.

원본은 단일 사용자 card_keywords.json 을 함수 안에서 load_card_keywords() 로 읽었다.
팀 공유 앱에서는 DB 세션을 함수에 끌어들이지 않기 위해, 호출자가 팀 키워드(cards)
dict 를 card_kw 로 주입한다 — 나머지 분류 로직은 원본과 100% 동일(verbatim).

호출: compute_card_counts(store['matched'], source='matched', card_kw=<팀 cards>)
→ 원본 app.py:1532 `_compute_card_counts(store['matched'], source='matched')` 미러.
"""


def compute_card_counts(classified_rows, buy_df_raw=None, source='classified', card_kw=None):
    """블랙스팟 카드 집계.

    source='classified' (기존): classified 행 기반 + raw buy_df augmentation
    source='matched' (사용자 요청 — 100% 일치): matched 행 직접 분류
       · 주문미이행 only (메모 s/p/x + 흔적 없음) 제외
       · 카드 카운트 = 전체내역 필터 결과 100% 동일

    분기 우선순위 (위에서 아래) — 메모 우선 원칙:
      1. 메모"블랙스팟"                    → confirmed_blackspot
      2. 메모"입금"/"철회" 부분매칭         → memo_settled
      3. 메모"반품/교환/취소/환불/회수/완료" → completed_memo_yes (상태 무관)
      ─── 메모 분류 끝 ───
      4. (메모 X) + 데이터 정합성 이상 → mango_check
         - 사이트주문번호 ↔ 송장번호 미스매치 (케이스 1, 2)
         - 샵마인 종결흐름 + 더망고 일반 진행중 (기존)
      5. (메모 X) + 더망고 종결(반품/교환/취소완료) → completed_memo_no
      6. (메모 X) + 진행중 → inprogress
      7. (메모 X) + 샵마인 종결 → completed_memo_no
      8. fallback (즉시/소싱처/마켓/정상/대기/까대기)
    """
    if not classified_rows:
        return {
            'card_all': 0, 'card_immediate': 0, 'card_sourcing': 0,
            'card_market': 0, 'card_normal': 0, 'card_pending': 0,
            'card_kkadaegi': 0, 'card_inprogress': 0, 'card_completed': 0,
            'card_margin': 0, 'card_shopmine_only_count': 0,
            'card_confirmed_blackspot': 0, 'card_mango_check': 0,
            'card_completed_memo_yes': 0, 'card_completed_memo_no': 0,
            'card_memo_settled': 0,
        }

    # ★ 사용자 편집 가능한 카드별 키워드 로드 (card_keywords.json)
    _card_kw = card_kw or {}
    def _kw(card, field):
        return _card_kw.get(card, {}).get(field, []) or []
    # 카드별 키워드 dict (분기에서 사용)
    # ⚠️ fallback default 제거 — 사용자가 빈 list 로 저장 시 그 카드 비활성 (의도 존중)
    KW_BLACKSPOT_MEMO = _kw('confirmed_blackspot', 'memo')
    KW_BLACKSPOT_MG   = _kw('confirmed_blackspot', 'mg')
    KW_SETTLED_MEMO   = _kw('memo_settled', 'memo')
    KW_DONE_MEMO      = _kw('completed_memo_yes', 'memo')
    KW_NORMAL_MEMO    = _kw('normal', 'memo')
    KW_KKADAEGI_MG    = _kw('kkadaegi', 'mg')
    KW_TRACKING_MG    = _kw('tracking_failed', 'mg')
    KW_TRACKING_MK    = _kw('tracking_failed', 'mk_sync')
    KW_PENDING_MG     = _kw('pending', 'mg')

    # 사용자 정의 매입 진행 흔적 (#3) — 다음 중 하나라도 있으면 매입 진행한 것으로 간주
    #   ① 구매가격 (구매가 입력됨)
    #   ② 국내송장번호 (발송 시작 또는 송장만 등록 — 케이스 2)
    #   ③ 사이트주문번호 (소싱처 매입 진행)
    #   ④ 간단메모에 URL 포함 (소싱처 링크 입력)
    #   ⑤ 마켓주문번호 + 더망고 진행 상태 (배송대기중/국내배송중)
    def _has_purchase_trace(r):
        def _v(x):
            s_ = str(x or '').strip()
            return s_ and s_ not in ('nan', '0', '0.0', 'None')
        try:
            buy = float(str(r.get('구매가격', 0)).replace(',', '') or 0)
            if buy > 0 and buy != 999999999.99:
                return True
        except (ValueError, TypeError):
            pass
        if _v(r.get('국내송장번호')):
            return True
        if _v(r.get('사이트주문번호')):
            return True
        memo = str(r.get('간단메모', '') or '')
        if 'http' in memo or 'HTTP' in memo:
            return True
        mg = str(r.get('더망고주문상태 (사용자 연동)', '') or '')
        if any(k in mg for k in ('배송대기중', '국내배송중')):
            return True
        return False

    if source == 'matched':
        # ★ 방안 A — matched 행 직접 분류 (전체내역과 100% 일치)
        #   matched 中 _주문미이행 only (메모 s/p/x + 흔적 없음) 만 제외
        mango_based = [
            r for r in classified_rows  # 함수 시그니처는 그대로지만 matched 전달됨
            if not (r.get('_주문미이행') and not r.get('_매입흔적'))
        ]
    else:
        # 기존 방식 (classified 기반 + raw augmentation)
        mango_based = [
            r for r in classified_rows
            if r.get('데이터출처') in ('더망고+샵마인', '더망고만')
        ]
        if buy_df_raw is not None and not buy_df_raw.empty:
            existing_keys = set()
            for r in mango_based:
                mk = str(r.get('마켓주문번호', '')).strip()
                if mk:
                    existing_keys.add(mk)
            for _, raw_row in buy_df_raw.iterrows():
                raw_dict = raw_row.to_dict()
                mk = str(raw_dict.get('마켓주문번호', '')).strip()
                if not mk or mk in existing_keys:
                    continue
                if _has_purchase_trace(raw_dict):
                    raw_dict['데이터출처'] = '더망고만(보강)'
                    raw_dict['상세분류'] = raw_dict.get('상세분류') or '미분류_raw보강'
                    mango_based.append(raw_dict)
                    existing_keys.add(mk)

    shopmine_only_count = sum(
        1 for r in classified_rows if r.get('데이터출처') == '샵마인만'
    )

    # 샵마인 주문상태 분류 (사용자 요구):
    #   '진행중' 류 → 새 카드 'card_inprogress'
    #   '반품/교환/취소 완료' 류 → 새 카드 'card_completed'
    #   일반 배송/수취 완료 → 'normal' (정상/완료 카드)
    PROGRESS_PATTERNS = ('회수지시', '철회', '진행중', '취소진행', '반품진행', '교환진행', '출고중지',
                         '반품접수', '반품요청', '교환신청', '교환요청')
    # 반품/교환/취소 완료 (별도 카드 = card_completed)
    DONE_RTN_PATTERNS = ('반품완료', '취소완료', '환불승인', '회수완료', '취소된거래', '취소거부')
    # 일반 정상 완료 (정상/완료 카드)
    DONE_NORMAL_PATTERNS = ('배송완료', '수취완료', '구매확정', '정산완료', '정산예정', '발송완료', '확정')

    def _shopmine_state_category(s: str) -> str:
        s = str(s or '').strip()
        if not s:
            return 'normal'
        if any(p in s for p in PROGRESS_PATTERNS):
            return 'in_progress'
        if any(p in s for p in DONE_RTN_PATTERNS):
            return 'done_rtn'  # 반품·교환·취소 완료
        if any(p in s for p in DONE_NORMAL_PATTERNS):
            return 'done_normal'  # 일반 정상 완료
        return 'normal'

    # ★ 동적 — 사용자 편집 가능 (card_keywords.json) — 위에서 로드된 KW_* 변수 사용
    #   사용자가 모두 삭제하면 빈 tuple → 매칭 X (의도된 동작)
    MEMO_DONE_KEYWORDS = tuple(KW_DONE_MEMO)
    MEMO_SETTLED_TOKENS = tuple(KW_SETTLED_MEMO)
    # 더망고 일반 진행중 패턴 (반품/교환/취소 흐름이 아닌 정상 진행중)
    MG_NORMAL_PROGRESS = ('국내배송중', '배송준비중', '배송대기중', '배송지시', '결제완료',
                          '신규주문', '발송대기', '상품준비')

    # ★ 사용자 명시 — 메모 內 알려진 정상 키워드 화이트리스트
    #   이 외 한글 단어가 메모에 있으면 → 기타 카드 (오타·의외 단어 검토용)
    KNOWN_MEMO_TOKENS = {
        '반품', '교환', '취소', '환불', '회수',
        '철회', '완료', '진행', '접수', '신청', '요청', '승인', '거부',
        '입금', '확인', '검토', '점검',
        '블랙스팟',
        '정산', '예정', '대기',
        '배송', '발송', '수취', '구매', '준비', '확정',
        '주문', '시도', '됨', '보냄', '없음', '있음', '중',
        '재', '미',
    }

    import re as _re
    from collections import Counter as _Counter

    # ★ 동적 학습 — 메모에 자주 등장하는 2-3자 한글 토큰 = 사람 이름 (주문처리 이행자) 후보
    #   사용자: '영빈/은순 등 사람이름은 주문처리 이행자, 카드에 영향 줘서는 안 됨'
    _name_counter = _Counter()
    for r in mango_based:
        memo_text = str(r.get('간단메모', '') or '')
        s = _re.sub(r'https?://\S+', '', memo_text)
        s = _re.sub(r'\d+', '', s)
        s = _re.sub(r'[a-zA-Z_]+', '', s)
        s = _re.sub(r'[^가-힣]+', ' ', s)
        for tok in s.split():
            if 2 <= len(tok) <= 3 and tok not in KNOWN_MEMO_TOKENS:
                _name_counter[tok] += 1
    # 빈도 ≥ 3 인 토큰 = 사람 이름 후보 (안전하게 자주 등장하는 것만)
    DYNAMIC_NAMES = {tok for tok, cnt in _name_counter.items() if cnt >= 3}

    def _has_unknown_korean_in_memo(memo_text, recipient_name=''):
        """메모 內 알려진 키워드 + 정상 정보 (URL/날짜/계정/소싱처/이름) 외
           한글 단어 (오타·의외 단어) 가 남아있는지 검사.
           ⚠️ 사람 이름 (DYNAMIC_NAMES) 도 정상 토큰으로 처리."""
        if not memo_text:
            return False
        s = str(memo_text)
        # 1) URL 제거
        s = _re.sub(r'https?://\S+', '', s)
        # 2) 날짜 제거
        s = _re.sub(r'\d{2,4}[./\-]\d{1,2}[./\-]\d{1,2}', '', s)
        # 3) 시간 제거
        s = _re.sub(r'\d{1,2}:\d{2}(:\d{2})?', '', s)
        # 4) 영문/숫자 제거
        s = _re.sub(r'[a-zA-Z0-9_]+', '', s)
        # 5) 구분자 제거
        s = _re.sub(r'[/\(\)\[\]\{\},\.\-\:\;@#%&*+=?!~\'\"]+', ' ', s)
        # 6) 수령인 이름 제거
        if recipient_name:
            s = s.replace(str(recipient_name), '')
        # 7) 알려진 키워드 + 동적 학습된 사람 이름 모두 제거
        for tok in KNOWN_MEMO_TOKENS:
            s = s.replace(tok, '')
        for tok in DYNAMIC_NAMES:
            s = s.replace(tok, '')
        # 8) 남은 한글 (2자 이상) 검사
        return bool(_re.search(r'[가-힣]{2,}', s))

    immediate_check = sourcing_check = market_check = 0
    normal_count = pending_count = kkadaegi_count = margin_issue = inprogress_count = completed_count = 0
    confirmed_blackspot = mango_check = completed_memo_yes = completed_memo_no = 0
    memo_settled = 0
    tracking_failed = 0  # 송장 재전송 실패 (사용자 요청 신규 카드)
    status_mismatch = 0  # 샵마인 ↔ 더망고 상태 불일치 (사용자 요청 신규 카드 — C안)
    etc_count = 0        # 기타 — 어느 분기에도 안 잡힌 행 (사용자 요청 신규 카드)

    for row in mango_based:
        detail = row.get('상세분류', '') or ''
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

        sm_status = row.get('샵마인_주문상태', '') or row.get('샵마인_샵마인주문상태', '')
        sm_cat = _shopmine_state_category(sm_status)
        mg_status = str(row.get('더망고주문상태 (사용자 연동)', '') or '')
        # 마켓주문상태 (오픈 마켓 연동) — 송장전송실패 등 마켓 sync 결과 (사용자 요청)
        mk_sync_status = str(row.get('마켓주문상태 (오픈 마켓 연동)', '') or '')
        mg_in_progress = '진행중' in mg_status
        mg_completed_rtn = '완료' in mg_status and any(k in mg_status for k in ('반품', '교환', '취소'))
        mg_normal_progress = any(k in mg_status for k in MG_NORMAL_PROGRESS)

        # 사이트주문번호 ↔ 송장번호 미스매치 (더망고 데이터 정합성 이상)
        def _has(v):
            s_ = str(v or '').strip()
            return s_ and s_ not in ('nan', '0', '0.0', 'None')
        has_site_no  = _has(row.get('사이트주문번호'))
        has_track_no = _has(row.get('국내송장번호'))
        # 케이스 1: 사이트주문번호 O + 송장 X (매입했는데 발송 안 됨)
        # 케이스 2: 사이트주문번호 X + 송장 O (매입 안 했는데 송장만 있음)
        site_track_mismatch = (has_site_no and not has_track_no) or (not has_site_no and has_track_no)

        memo = str(row.get('간단메모', '') or '')
        # ★ 사용자 편집 키워드 (card_keywords.json) 동적 매칭
        has_blackspot_memo = any(k in memo for k in KW_BLACKSPOT_MEMO)
        is_mg_blackspot    = any(k in mg_status for k in KW_BLACKSPOT_MG)
        has_settled_memo   = any(k in memo for k in MEMO_SETTLED_TOKENS)
        has_done_memo      = any(k in memo.replace(' ', '') for k in MEMO_DONE_KEYWORDS)
        has_normal_memo    = any(k in memo for k in KW_NORMAL_MEMO)

        # ── 사용자 결정 적용 (2026-05) — 우선순위 재구성 (키워드 동적화) ──
        # ★ 1순위: 더망고 = 까대기 키워드 ('해외현지배송중' 등)
        if any(k in mg_status for k in KW_KKADAEGI_MG):
            kkadaegi_count += 1
        # ★ 2순위: 메모 블랙스팟 키워드 OR 더망고 블랙스팟 키워드 ('오류입고' 등)
        elif has_blackspot_memo or is_mg_blackspot:
            confirmed_blackspot += 1
        # ★ 3순위: 메모 입금/철회
        elif has_settled_memo:
            memo_settled += 1
        # ★ 4순위 [사용자 명시 — 무조건 송장 재전송 실패 카드]: 메모/메인 분기보다 우선
        #   ⚠️ 메모 종결 phrase·정산완료 보다 위로 — 송장전송실패 행은 무조건 그 카드로
        elif any(k in mk_sync_status for k in KW_TRACKING_MK) or any(k in mg_status for k in KW_TRACKING_MG):
            tracking_failed += 1
        # ★ 5순위 [묻지도 따지지도]: 메모 종결 phrase
        elif has_done_memo:
            completed_memo_yes += 1
            completed_count += 1
        # ★ 5순위: 메모 normal 키워드 ('정산완료' 등)
        elif has_normal_memo:
            normal_count += 1
        # ★ 6순위 [결정 2 + 사용자 확장]: 더망고=국내배송중 + 샵마인 분기
        #   - 배송중/배송준비/발송대기/상품준비 → 발송 대기 (배송 진행 중)
        #   - 구매확정/수취완료/배송완료/확정/배송 → 정상/완료 (정상 종결)
        elif '국내배송중' in mg_status and any(k in str(sm_status) for k in (
            '배송중', '배송준비', '발송대기', '상품준비'
        )):
            pending_count += 1
        elif '국내배송중' in mg_status and any(k in str(sm_status) for k in (
            '구매확정', '수취완료', '배송완료', '확정', '배송'
        )):
            normal_count += 1
        # ★ 6순위: 더망고 = 발송 대기 키워드 ('배송대기중' 등)
        elif any(k in mg_status for k in KW_PENDING_MG):
            pending_count += 1
        # ★ 8순위 [결정 3 — 위로 이동]: 더망고=반품/교환/취소 완료 → 메모 phrase 일치 여부
        #   - 메모 phrase (반품완료/교환완료/취소완료/환불완료/환불승인/회수완료) 일치 → completed_memo_yes
        #   - 메모 없음 → completed_memo_no (재확인)
        #   ⚠️ site/track mismatch 보다 위 — 반품 시 송장 회수돼도 반품 카드로 분류
        elif mg_completed_rtn:
            if has_done_memo:
                completed_memo_yes += 1
                completed_count += 1
            else:
                completed_memo_no += 1
                completed_count += 1
        # ★ 9순위 [결정 3 — 위로 이동]: 더망고/샵마인 진행중 → 진행중
        #   ⚠️ site/track mismatch 보다 위 — 반품 진행 시 송장 회수돼도 진행중 카드로
        elif mg_in_progress or sm_cat == 'in_progress':
            inprogress_count += 1
        # ★ 10순위: site/track mismatch → 더망고 점검 (이전 8순위 → 아래로)
        elif site_track_mismatch:
            mango_check += 1
        # ★ 11순위: 상태 불일치 (기존)
        elif (mg_normal_progress and sm_cat in ('in_progress', 'done_rtn')) or \
             (('국내배송' in mg_status or '해외현지배송' in mg_status) and
              ('발송대기' in str(sm_status) or '배송준비' in str(sm_status))):
            status_mismatch += 1
        # ★ 12순위: 샵마인 종결 → 메모X 재확인 (기존)
        elif sm_cat == 'done_rtn':
            completed_memo_no += 1
            completed_count += 1
        # ★ 13순위: 일반 배송/수취 완료 → 정상/완료 (기존)
        elif sm_cat == 'done_normal':
            normal_count += 1
        elif is_kkadaegi_code:
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
        # ★ 마지막 분기 [위에서 이동]: 메모에 알려진 키워드 외 한글 단어 → 기타
        #   ⚠️ 모든 mg/sm 명확한 분기 통과 후에만 적용 (사용자 의도 — 정말 어디에도 못 가는 행만)
        elif _has_unknown_korean_in_memo(memo, str(row.get('수령인', '') or '')):
            etc_count += 1
        else:
            # ★ Fallback — 모든 분기 통과 = 진짜 미분류 → 기타
            etc_count += 1

        if is_margin:
            margin_issue += 1  # 중첩 집계

    # ★ frontend 동기화용 — 동적 학습된 사람 이름 list (메모에 자주 등장)
    _dynamic_names_list = sorted(DYNAMIC_NAMES)

    return {
        '_memo_dynamic_names':      _dynamic_names_list,  # frontend KNOWN_MEMO_TOKENS 보강용
        '_card_keywords':           _card_kw,              # frontend 분류 함수 동기화용 (사용자 편집 키워드)
        'card_all':                 len(mango_based),
        'card_immediate':           immediate_check,
        'card_sourcing':            sourcing_check,
        'card_market':              market_check,
        'card_normal':              normal_count,
        'card_pending':             pending_count,
        'card_kkadaegi':            kkadaegi_count,
        'card_inprogress':          inprogress_count,
        'card_completed':           completed_count,
        'card_margin':              margin_issue,
        'card_shopmine_only_count': shopmine_only_count,
        # 신규 카드
        'card_confirmed_blackspot': confirmed_blackspot,
        'card_mango_check':         mango_check,
        'card_completed_memo_yes':  completed_memo_yes,
        'card_completed_memo_no':   completed_memo_no,
        'card_memo_settled':        memo_settled,
        'card_tracking_failed':     tracking_failed,
        'card_status_mismatch':     status_mismatch,  # 샵마인 ↔ 더망고 상태 불일치
        'card_etc':                 etc_count,         # 기타 — 어느 분기에도 안 잡힌 행
    }
