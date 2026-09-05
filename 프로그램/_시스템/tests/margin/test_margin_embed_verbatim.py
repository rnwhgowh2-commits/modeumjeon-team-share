# -*- coding: utf-8 -*-
"""margin_embed.html 무수정 이식 동치 가드 (test_classifier_verbatim / test_matcher_verbatim 패턴).

서빙 템플릿 orders/margin_embed.html 이 원본 index.html 에서 오직 씨앗(seam, 8종/11회)만
바꾼 결과임을 증명한다 — 렌더 함수·CSS·`_getRowsByCardFilter_internal` 우선순위 체인이
드리프트하면 크게 실패한다.

원본은 개발자 PC 단독앱이라 CI·팀원 PC 엔 없다 → 원본 부재 시 skip(에러 아님).
"""
import difflib
import importlib.util
import inspect
import pathlib

import pytest

# 원본(단독앱) + 서빙 템플릿 + 커밋된 빌드 스크립트 경로.
ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\templates\index.html")
_SYS = pathlib.Path(__file__).resolve().parents[2]           # 프로그램/_시스템
SERVED = _SYS / "webapp" / "templates" / "orders" / "margin_embed.html"
BUILD_SCRIPT = _SYS / "tools" / "build_margin_embed.py"


def _load_transform():
    """커밋된 빌드 스크립트에서 순수 함수 transform 을 로드."""
    spec = importlib.util.spec_from_file_location("build_margin_embed", BUILD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm(p: pathlib.Path) -> str:
    """EOL 정규화(CRLF/LF 무관하게 내용만 비교) — 서빙=LF, 원본=CRLF 차이를 제거."""
    return p.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


# 변경된(추가/삭제) 라인에 반드시 들어있어야 하는 씨앗 토큰 화이트리스트.
# 이 목록에 없는 문자열이 변경 라인에 있으면 = 본문(렌더/CSS) 드리프트 → 실패.
_SEAM_TOKENS = (
    "margin_rules.js",                    # 자산 ref (js/margin_rules.js ↔ margin_rules.js)
    "type + '_file'", "fd.append('file'",  # 업로드 필드
    "/api/upload", "_mUploadUrl",          # 업로드 엔드포인트
    "data[type]", "success: true, rows",   # 업로드 응답 정규화
    "/api/analyze", "/api/margin/analyze",  # 분석 엔드포인트
    "/api/download", "/api/margin/export",  # 내보내기 엔드포인트
    "analysis_id: (window.analysisData",    # 내보내기 body 주입
    "buyLoaded",                            # 분석버튼 게이트 (buyLoaded&&sellLoaded ↔ buyLoaded)
    # 매출 정의 통일(2026-08-13) — 매출 = 정가 + 배송비 − 판매자부담 할인.
    #   ① 기간 평균 배너만 판매가(단가×수량)로 세어 상단 카드와 숫자가 달랐다 → saleAmt 로.
    #   ② 총매출 카드 부제가 「판매가」인데 값은 매출 기준이라 뜻이 어긋났다 → 표기 정정.
    #   두 씨앗 모두 원본 줄을 **지우므로**, 지워지는 줄의 토큰도 함께 등록한다.
    #   ③ saleAmt·recomputeRow 도 같은 정의로. 새로 넣는 줄은 전용 마커를 단다.
    "[모음전 매출기준]",
    "Number(x['판매가']||0)||0", "_sumCard('총매출'",
    "const _rateBase",
    "/api/blackspot/fetch_order_no", "_mMissRow",  # 소싱처 주문번호 추출 — 무상태 서버에 memo 동봉
    "const summary", "analyzeAndRender", "_mSupp",  # 추출 성공 UX — 거짓 카운트 제거 + 반영칸 프리필
    "margin_ext_check.js", "_moumExtCheckFetch", "/api/check-sourcing",  # [E2] 소싱처 주문상태 = 서버 Playwright 제거 → 로컬 크롬확장
    "id=\"sellBox\"", "id=\"sellFileInput\"", "upload-icon", "upload-label", "upload-sub", "id=\"sellStatus\"",  # 매출칸 → 마켓API 자동조회 안내 (샵마인 업로드 제거)
    "errText",                              # 업로드 에러 핸들러 단일읽기(이중읽기 버그수정)
    "_mFailed", "markets_failed",           # 연동안됨/조회실패 마켓 표면화 배너
    "_mNotice", "notices",                  # 제외가 아닌 안내(저장분 분석 등) — 별도 배너
    # 분석 앞단의 최신 주문 수집 — 분석은 저장분만 읽고, 수집은 마켓별로 나눠 돌린다.
    # (한 요청에 6마켓을 묶으면 옥션 58초에 묶여 서버 상한 초과 → 502 → "서버 오류")
    # 로직은 static/margin_refresh_orders.js 에 둔다 — 이 파일 본문엔 script ref 와
    # startAnalysis 첫 줄 호출만 들어간다(본문 무수정 원칙 유지).
    # ※ 2026-08-02 「최신까지 불러오기」 버튼 삭제 — 분석이 어차피 먼저 돌려 중복이었다.
    #    그래서 refreshOrdersBtn 토큰도 함께 없앴다(안 쓰는 토큰은 드리프트를 가린다).
    "margin_refresh_orders.js", "refreshOrdersToNow", "_moumRefreshFailed", "_rFailed",
    # 「까대기 송장번호 전송 완료」 카드 — 더망고 '현지배송완료'(송장 뽑아 마켓 전송한 건).
    # 카드 안 양분·막대 조립은 static/margin_kkadaegi_sent.js 에 두고, 이 파일엔
    # 카드 정의(색·설명·이름표·건수)와 배치만 씨앗으로 들어간다.
    "margin_kkadaegi_sent.js", "kkadaegi_sent", "_kkadaegiSentCardHTML",
    "tracking_failed", "kkadaegi",          # 송장 재전송 실패 1행 이동 · 까대기 2행 이동
    "🆕 송장 재전송 실패",                   # 옛 주석 줄(자리 이동으로 문구 갱신)
    # 마진율 칸 — 판매가·정산이 둘 다 0 이면 「계산불가」(0.0% 로 보이면 역마진이
    # 아무 표시 없이 정상처럼 지나간다). 원본은 fmtPct 한 줄, 서빙본은 즉시함수.
    "margin_rate_cell.js", "_moumMarginRateCell", "dispMarginRate",
    # 판매경로 칸 — '미확인'을 회색으로 떼기(원본은 롯데ON 파란 칸과 뭉뚱그림). 호출 한 줄.
    "margin_route_cell.js", "_moumRouteCell",
    # 정산 칸 정직성 — 추정/미확인 배지+호버, 요약 색칩(실정산·추정·미확인)
    "margin_settle_cell.js", "_moumSettleCell", "_moumSettleChips", "정산 정직성",
    "_moumSettleBadge", "_sbdg", "정산 배지",
    # 「기타」로 새던 상태 3종 수정 + 기타 카드에 사유 표시
    "margin_etc_reasons.js", "_etcCardHTML", "_normalCardHTML", "출고지시", "취소요청", "결제완료",
    "_summaryCardHTML('normal'",           # 정상/완료 카드 → 역마진 경고 래퍼
    "_paid",                                # 매출 = 고객 실결제 + 배송비
    "margin_all_tab.js", "_goAllWithCardFilter", "showCardBreakdown",
    "var cols = [", "'_추가메모'", "colLabels",  # 전체내역 열 구성·이름표 교체
    "'국내송장번호'", "'샵마인_송장입력'", "'샵마인_주문상태'", "'주문일'",
    "'마켓'", "'상품명'", "'옵션_매출'", "'수량_매출'", "'정산예상금액'",
    "'구매가격'", "'순마진'",
    "송장번호 앞 택배사", "_crf", "샵마인_택배사", "[모음전] 택배사",   # 송장번호 앞 택배사
    "[판매처] 택배사", "샵마인_택배사 별도 칼럼", "[판매처] 택배사 별도 칼럼", "국내송장번호 택배사",   # [판매처] 택배사 별도 칼럼
    "_rateBase", "매출=실결제+배송비", "[모음전] 매출 기준",   # 편집 재계산 마진율 기준
    "[모음전] 체크박스", "제외·비대량등록", "'제외'", "'비대량등록'", "'간단메모'",   # 상세표 체크박스+간단메모
    "[모음전] 편집", "인라인 편집(공용 뿌리)",   # 카드 상세 인라인 편집
    "_moumRenderAll", "전체내역=카드 상세 통일", "all:        renderAll",   # 전체내역 탭 위임(지운 원본 줄 포함)

    "세부보기</button>", "전체내역에서 보기</button>",
    "PROGRESS_PATTERNS",                    # 취소요청 추가(지워지는 옛 줄엔 토큰을 못 심는다)
    "sm.indexOf('구매확정')",               # 국내배송중 정상/완료 목록에 출고지시 추가
    "_summaryCardHTML('etc'",              # 기타 카드 → 사유 표시 래퍼
    "sm.indexOf('배송중')", "'배송중' 제외",   # 발송 대기 목록에서 '배송중' 제거(지운 줄·새 줄 양쪽)
    # ── [모음전 2026-07-25] 검산식(시안 20) + 실마켓(API) 미매칭 카드 + '샵마인'→'실마켓(API)' 개명 ──
    "margin_checksum.js", "_moumChecksumHTML", "_moumUnmatchedBuyCardHTML",  # 검산식·실마켓 미매칭 카드
    "_moumUnmatchedSellCardHTML", "프로그램(API) 미매칭", "실마켓·프로그램 미매칭",  # 프로그램(API) 미매칭 카드
    # ── [모음전 2026-07-30] 프로그램(API) 미매칭 카드 삭제 + ② 매입 흔적만 카드 클릭 상세 ──
    "repeat(4,1fr);gap:6px;margin:6px 0 0 0",     # 4칸→3칸(지워지는 옛 그리드 줄, 프로그램 미매칭 카드 제거)
    "_moumTraceOnlyClick", "매입 흔적만 카드 클릭",  # ② 1-2 박스 onclick(추가측)
    "border:1px solid #fde68a;border-radius:10px;padding:12px 14px",  # ② 1-2 박스 원본 라인(삭제측) 매칭
    "사이드 패널 제거", "display:none", "270px", "bsSidePanel",  # 카드선택 사이드패널 제거(숨김)+그리드 단일칸
    "_moumSuspectClick", "NEW 배지 제거", "블랙스팟 의심 클릭",  # NEW 배지 3곳 제거 + 1-3 클릭
    ">NEW</span>", "매입 진행 여부", "1-3 <span",  # 지워지는 옛 NEW 배지 줄
    "background:#fef2f2;border:1.5px solid #fca5a5",  # 1-3 박스 원본 줄(클릭 추가로 교체)
    "실마켓",                                    # 개명된 표시 문구(새 라인)·새 카드 주석 — 전부 '실마켓' 포함
    "repeat(2,1fr);gap:6px;margin:6px 0 0 0",    # 블랙스팟 줄 2칸→3칸(지워지는 옛 그리드 줄)
    # 개명으로 지워지는 옛 '샵마인' 표시 문구 — 데이터 키 '샵마인_*'·데이터출처 '샵마인만'과 구분되는 display 전용
    "샵마인 매칭", "샵마인=매출", "샵마인↔더망고", "샵마인 미동기화",
    "샵마인 미매칭", "샵마인에만 있음", "샵마인(마켓 정산)",
    # ── [모음전 2026-07-31] 디자인 타입을 이 화면에도 태운다 ──
    #  사장님 지적: 「검정A·B 타입인데 마진계산기는 화이트 디자인」.
    #  이 화면은 base.html 을 안 쓰는 홀로 선 페이지(iframe 안)라 ds 클래스도
    #  tokens.css 도 없었다. head 에 토큰 CSS 를 싣고 body 에 타입 클래스를 붙인다.
    #  (색 자체의 치환은 씨앗이 아니라 빌드 마지막의 스윕이 하고, 위 테스트가
    #   원본에 같은 스윕을 걸어 놓고 비교하므로 여기 화이트리스트와 무관하다.)
    "디자인 타입", "tokens.css", "scope_fix.css", "dark_badge_fix.css",
    "margin_embed_ds.css", "inline_color_fix.css", "design_body_class", "</head>",
    # ── [2026-08-03] 글꼴 한 벌 + 표 정렬 — 저장소 전체 스윕이 이 화면에도 걸린다 ──
    #  서빙본에만 있던 것을 씨앗으로 못 박았다(2026-08-06). 주석 줄까지 표식을 준다 —
    #  여러 줄 삽입이라 표식 없는 줄이 생기면 무수정 가드가 걸린다.
    "font_unify.css", "table_align.css", "table_align.js", "[2026-08-03]",
    "base.html 을 안 물려받는", "2026-08-02 규칙(.num", "라이브 실측 131개",
    "<body>",   # 지워지는 옛 줄 — class 붙은 <body class="…"> 로 바뀐다
    # [2026-08-01] <html> 에도 타입 클래스 — 화면이 :root 에서 만든 색 이름이
    #   거기서 밝은 예비값으로 굳는 것을 막는다.
    '<html lang="ko"',
    # ── [2026-08-02 · 사장님 지적] 표의 숫자가 왼쪽에 붙어 자릿수가 안 맞던 것 ──
    #   숫자 칸·머리글에 `num` 표시를 달아 오른쪽 + 자릿수 고정으로 맞춘다.
    #   칸을 만드는 곳(numCell·pctCell·mkSortTh·sTh·건수·전체내역 행)이 전부 바뀐다.
    '[모음전 정렬 2026-08-02]',   # 스타일 한 줄(정렬 규칙 + 잘리던 두 칸 폭)
    'class="num',                 # 숫자 칸 — `class="num"` · `class="num neg"`
    "' num'",                     # 머리글 — 이름으로 숫자 칸을 가려 붙인다
    # 지워지는 옛 줄(정렬 표시가 없던 그대로의 칸·머리글)
    "'<td>-</td>'",                       # numCell·pctCell 빈칸
    '<th class="sortable" onclick=',      # 머리글 3종(집계·소싱처·전체내역)
    "'<td id=\"' + (isMarket",            # 건수 칸
    '\'<td><input type="number"',         # 단가·정산·매입가 입력칸
    "수량_매출'] || 1",                    # 수량 칸
    "font-weight:600;' + (isBs",          # 판매가 칸
    ' class="neg"',                       # 순마진·마진율(음수 표시만 있던 옛 줄)
    # ── [모음전 2026-08-12] 매입 엑셀 = 실매입가 **단일 원천에도** 저장 → 결과를 말한다 ──
    #  서버(api_margin.upload → _share_to_purchase_store)가 같은 엑셀을 주문 라인
    #  (`order_line_purchases`)에도 저장한다(사장님 확정 규칙 6). 조용히 넘어가면
    #  「올렸는데 주문 내역엔 왜 없지」가 된다 → 업로드 상태줄에 저장 결과를 덧붙인다.
    "_moumShared",                        # 새 줄 전부(변수·주석·본문)
    "setStatus(type, 'ok'",               # 지워지는 옛 상태줄 + 새 상태줄
    # ── [모음전 2026-08-20] 사장님 지적 4건 — 일별 그룹재계산 버그·전체내역 컬럼필터
    #    버그(제외/비대량등록·(빈값))·요약탭 고마진/주문내역 인라인 편집 ──
    #  아래 태그가 오늘 바뀐/추가된 줄 전부에 하나씩 붙는다(본문 무수정 가드 통과용).
    "[모음전 2026-08-20]",
    "margin_col_filter_fix.js", "_moumColFilterKey",  # 컬럼필터 (빈값)·제외/비대량등록 통일
    # ── [모음전 2026-08-27] 더망고 지연 라벨이 pending 을 먼저 채가던 버그 ──
    #  샵마인_주문상태가 이미 취소·반품 진행/완료(smC)인데 더망고가 아직 평상 라벨
    #  (배송대기중 등)이면 isMgPending 이 smC 를 안 보고 먼저 pending 카드로 채가
    #  반품·취소 자동 제외(inprogress/completed_memo_* 카드만 훑음) 대상에서 빠졌다.
    #  "isMgPending" 은 지워지는 옛 줄에도 이미 있던 토큰이라 그대로 재사용한다
    #  (PROGRESS_PATTERNS 선례와 동일 — 지워지는 줄엔 새 토큰을 못 심는다).
    "isMgPending",
    # ── [모음전 2026-08-28] sourcing_brand_marker 카드 — 르무통 등 대량등록 반품/취소 마커
    #    브랜드는 진짜 반품이 아니라 사입 판매 표시라 별도 카드로 빼고 매출/마진 총계에서
    #    뺀다(사장님 명시, git-issue-flow #margin-calculator-settlement-exclusion).
    #    거의 모든 새 줄에 "sourcing_brand_marker" 를 심어 한 토큰으로 커버하고,
    #    지워지는 옛 줄·그 옛 줄과 글자가 겹치는 새 줄만 아래처럼 개별 토큰을 둔다.
    "sourcing_brand_marker",
    "_brand_marker_excluded",             # 자동제외 플래그(수기 반품·취소 제외와 구분)
    "c.brand.join",                       # 설정 탭 카드별 키워드 표에 브랜드 열 추가
    "라벨과 함께 매칭",                    # 키워드 에디터 브랜드 입력칸 설명(새 줄)
    "isBrandCard",                        # 키워드 에디터 — 브랜드 카드는 memo/mg/mk_sync 대신 brand 필드만
    "] : [",                              # 위 삼항연산자 도입으로 생기는 줄(기존에도 3곳 있던 문법)
    "var fields = [",                     # 지워지는 옛 줄(삼항연산자로 교체됨 — PROGRESS_PATTERNS 선례와 동일)
    "'mk_sync', 'sub_rtn', 'sub_ex']",    # 지워지는 옛 저장 필드 목록 줄(브랜드 필드 추가 전)
    "'sub_ex', 'brand']",                 # 새 저장 필드 목록 줄(브랜드 필드 추가)
    "매입흔적만 (사이트번호 X)'};",         # 지워지는 옛 labelMap 줄(2곳 — sourcing_brand_marker 항목 추가 전)
    "completed:'반품/교환/취소 완료'};",    # 지워지는 옛 labelMap 줄(downloadExcelByCard, 항목 추가 전)
    # ── [모음전 2026-09-05] 정산여부 배지 + 주문상태 이력 호버 ──
    #  클레임(취소요청 등)으로 들어온 주문상태가 그 뒤 실제로 어떻게 됐는지(철회·정산완료)
    #  를 안 보여줘서 이미 끝난 정상거래가 「손실 진행중」으로 잘못 보였다(사장님 지시).
    "margin_status_history.js", "_ssVerdictCellHtml",
    # ── [모음전 2026-09-05] 대용량 매입 엑셀 — /api/margin/analyze 100초 벽(524) 우회 ──
    #  매입 12,949행짜리 더망고 엑셀에서 동기 분석이 Cloudflare 100초 게이트웨이
    #  제한에 걸려 "서버 오류"가 났다(matcher.match_data 가 매입행 수에 비례해
    #  매출 전체를 훑는 원본 무수정 알고리즘이라 대용량에서 항상 그 벽에 걸림).
    #  본문(fetch('/api/margin/analyze',...) 호출 3곳)은 무수정으로 두고, 이
    #  스크립트 한 줄만 먼저 실어 window.fetch 를 감싼다(margin_refresh_orders.js
    #  선례와 동일 패턴 — 로직은 static/margin_analyze_poll.js 에 둔다).
    "margin_analyze_poll.js",
    # ── [모음전 2026-09-06] 블랙스팟 의심 가상행 — 선택 기간(주문일) 밖이면 총마진에서 뺀다 ──
    #  실측(라이브 #171): 가상행 120건 전부가 "오늘"·"1주일" 어느 기간에도 안 속하는데도
    #  날짜 필터 무관하게 매번 concat 돼 매입원가(-498만원)가 모든 기간 총마진에 새고
    #  있었다. getFilteredData 에 공용 _passDateFilter 를 새로 만들어 실제 매출행과
    #  가상행에 동일 적용하고, renderCurrentTab 의 (이제는 무효화된) 재-concat 보정
    #  블록은 제거한다.
    "블랙스팟 의심을 항상 재집계", "블랙스팟 의심 16건을 항상 재집계",
    "날짜 필터 판별", "[2026-09-06 수정]", "[2026-09-06]",
    "매입원가(-순마진)가 다른 기간 총마진", "짧은 기간(오늘·1주일)일수록",
    "기간 무관 고정 120건",
    "_passDateFilter", "if (!hasDateF) return true;", "if (!d) return true;",
    "parseDate26(r['주문일'])", "d < dateFilterFrom", "d > dateFilterTo",
    "가상 행도 자기 주문일이 선택 기간 안일 때만 concat",
    "16건 (가상 행) — 모든 탭 마진/매출/매입 집계에 포함",
    "early-return 최적화로 16건이 빠지는 것을 보정",
    "d.matched.indexOf(_susp[0])",
    "보정 블록을 지웠다", "단일 진실 원천, _getRowsByCardFilter 와 동일 원칙",
)


def test_transform_reproduces_served_file():
    """transform(원본) == 현재 서빙 템플릿 (EOL 정규화 후 정확히 일치)."""
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    transform = _load_transform().transform
    original = _norm(ORIGINAL)
    served = _norm(SERVED)
    produced = transform(original)
    assert produced == served, (
        "transform(원본) 이 서빙 템플릿과 다릅니다 — margin_embed.html 이 손으로 편집됐거나 "
        "원본이 바뀌었는데 재빌드가 안 됐습니다. `python tools/build_margin_embed.py` 재실행 필요.")


def test_only_the_seams_differ():
    """원본 vs 서빙 diff 의 모든 변경 라인이 씨앗 토큰이어야 한다 (본문 무수정 증명).

    렌더 함수·`_getRowsByCardFilter_internal` 라인이 하나라도 바뀌면 화이트리스트에
    없어 여기서 실패한다.

    [2026-07-31] 색 치환은 따로 센다.
      빌드가 마지막에 <style> 블록의 굳은 색을 `var(--토큰, 원래색)` 으로 바꾼다
      (디자인 타입을 이 화면에도 태우기 위해서다 — 사장님 지적 「검정 타입인데
      마진계산기가 흰 디자인」). 그래서 CSS 줄은 **정상적으로** 바뀐다.

      그렇다고 CSS 줄을 통째로 봐주면 진짜 드리프트가 묻힌다. 그래서
      **원본에 같은 색 치환을 걸어 놓고 그것과 비교한다** — 색 치환으로 설명되는
      변화는 사라지고, 설명 안 되는 변화만 남아 화이트리스트 검사에 걸린다.
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")

    # 원본에 「색 치환만」 적용한 것을 기준선으로 삼는다(씨앗은 아직 안 넣은 상태).
    import sys
    _스크립트 = str(_SYS / 'scripts')
    if _스크립트 not in sys.path:
        sys.path.insert(0, _스크립트)
    from design_sweep import 스타일블록만_색치환, 스타일블록만_흰배경_서페이스로
    from split_faint_text import _바꾸기 as _흐린글자_가르기

    from split_semantic_text import _바꾸기 as _의미색_가르기

    기준선본문 = 스타일블록만_흰배경_서페이스로(스타일블록만_색치환(_norm(ORIGINAL)))
    기준선본문, _ = _흐린글자_가르기(기준선본문)
    기준선본문, _ = _의미색_가르기(기준선본문)
    from split_bg_from_text_token import _바꾸기 as _배경_가르기
    기준선본문, _ = _배경_가르기(기준선본문)
    # 표 여백·줄간격 규칙값 스냅(사장님 확정 「2-B」)도 빌드가 마지막에 건다.
    #   이걸 기준선에 안 걸면 padding 줄이 통째로 「설명 안 되는 변화」로 남아
    #   씨앗 검사에 걸린다 — 실제로 2026-08-06 까지 그 상태로 깨져 있었다.
    from snap_table_spacing import 스타일블록만_여백스냅
    기준선본문 = 스타일블록만_여백스냅(기준선본문, 'margin_embed.html')
    # 글자 바닥선 12px 스냅(사장님 확정 2026-08-13)도 빌드가 마지막에 건다.
    #   여백 스냅과 **같은 이유로** 기준선에도 걸어야 한다 — 안 걸면 글자크기 줄이
    #   통째로 「설명 안 되는 변화」가 되어 씨앗 검사에 걸린다.
    _도구 = str(_SYS / 'tools')
    if _도구 not in sys.path:
        sys.path.insert(0, _도구)
    from build_margin_embed import _글자_바닥선_12
    기준선본문 = _글자_바닥선_12(기준선본문)
    기준선 = 기준선본문.splitlines()
    served = _norm(SERVED).splitlines()
    diff = difflib.unified_diff(기준선, served, lineterm="", n=0)
    changed = [d for d in diff
               if d and d[0] in "+-" and not d.startswith(("+++", "---"))]
    assert changed, "변경 라인이 하나도 없음 — 재배선이 누락됐을 수 있음(씨앗 미적용)."
    for line in changed:
        body = line[1:]  # +/- 프리픽스 제거
        assert any(tok in body for tok in _SEAM_TOKENS), (
            f"씨앗이 아닌 라인이 변경됨(본문 드리프트 의심):\n{line}")


def test_색치환은_원래색을_예비값으로_남긴다():
    """「기존 타입」이 한 픽셀도 안 바뀌는 근거.

    치환 결과가 `var(--토큰, #원래색)` 형태여야 한다. 그 타입에는 토큰이 아예
    정의돼 있지 않아(이 화면에 ds 클래스가 안 붙는다) 브라우저가 괄호 안
    원래색을 그대로 쓴다. 예비값이 없으면 색이 통째로 사라진다.
    """
    import re
    served = _norm(SERVED)
    토큰들 = re.findall(r'var\((--[^,()]+)(,\s*[^()]*)?\)', served)
    assert 토큰들, '색 치환이 하나도 안 됐다 — 빌드가 스윕을 건너뛰었다'
    예비값없음 = [이름 for 이름, 예비 in 토큰들 if not (예비 or '').strip(' ,')]
    assert not 예비값없음, (
        '예비값 없는 토큰이 있다 — 「기존 타입」에서 이 색이 사라진다: %s'
        % sorted(set(예비값없음))[:10])


def test_structural_markers_byte_identical():
    """원본 고유 구조 마커가 서빙본에 개수까지 동일하게 존재(누락·변조 없음)."""
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    original = _norm(ORIGINAL)
    served = _norm(SERVED)
    for marker in ("_getRowsByCardFilter_internal", "renderBlackspot",
                   "_getCardKeywords", "function switchTab", "confirmed_blackspot"):
        assert original.count(marker) == served.count(marker) > 0, marker


def test_original_path_guard_is_skippable():
    """원본 경로가 없는 PC(CI·팀원)에서 FileNotFoundError 로 '에러' 나면 안 된다 (skip 이어야)."""
    for fn in (test_transform_reproduces_served_file,
               test_only_the_seams_differ,
               test_structural_markers_byte_identical):
        src = inspect.getsource(fn)
        assert "ORIGINAL.exists()" in src, f"{fn.__name__} 에 원본 부재 skip 가드가 없습니다"
