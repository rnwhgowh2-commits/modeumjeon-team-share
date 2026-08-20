# -*- coding: utf-8 -*-
"""원본 마진계산기 index.html → 모음전 margin_embed.html 무수정 이식 빌드.

원본(개발자 PC 단독앱)의 index.html 을 읽어, 아래 '씨앗(seam)' 문자열만 정확히
치환하고 나머지 10,819 줄(렌더 함수·CSS·`_getRowsByCardFilter_internal` 우선순위
체인 등)은 verbatim 으로 옮긴다.

■ 무수정 보장 방식 — `transform()` 은 순수 함수다. 씨앗 치환은 총 11건:
    1) 자산 ref (margin_rules.js)                        · 1회
    2) 업로드 FormData 필드 (buy_file/sell_file→file)    · 1회
    3) 업로드 엔드포인트 (/api/upload→/api/margin/*)       · 1회
    4) 업로드 응답 정규화 (data[type]→flat)               · 1회
    5) 분석 엔드포인트 (/api/analyze→/api/margin/analyze)  · 3회
    6) 내보내기 body 에 analysis_id 주입                   · 1회
    7) 내보내기 엔드포인트 (/api/download→/api/margin/export)· 1회
    8) 분석버튼 게이트 (buyLoaded&&sellLoaded→buyLoaded)   · 2회
  각 치환은 기대 발생 횟수를 assert 한다 — 원본이 상류에서 바뀌어 씨앗이 안 맞으면
  조용히 넘어가지 않고 크게 실패한다(SILENT MISS 방지).

■ 동치 가드 — tests/margin/test_margin_embed_verbatim.py 가 `transform(원본)` 이
  현재 서빙 템플릿과 정확히 일치함을 검증한다(원본 없는 PC 에선 skip).

  실행: python tools/build_margin_embed.py   (cwd = 프로그램/_시스템)
"""
from __future__ import annotations

import io
import pathlib

# 원본은 개발자 PC 에만 있는 단독앱 (CI·팀원 PC 엔 없음 → 빌드는 이 PC 에서만).
ORIGINAL = pathlib.Path(r"C:\dev\대량등록 마진계산기\templates\index.html")
# 서빙 템플릿 (프로그램/_시스템 기준 상대).
DST = pathlib.Path(__file__).resolve().parents[1] / "webapp" / "templates" / "orders" / "margin_embed.html"


# ── 씨앗 치환 테이블: (old, new, expected_count) ──────────────────────────
# 순서는 무의미(문자열이 서로 겹치지 않음). 각 old 는 원본에서 정확히 count 회.
SEAMS: list[tuple[str, str, int]] = [
    # 1) 자산 참조 (원본 841행) — 모음전 static/margin_rules.js (js/ 하위경로 제거)
    #    + [E2] 소싱처 주문상태 검사 seam 스크립트 주입 (원본 fetch('/api/check-sourcing')
    #      대체 = window._moumExtCheckFetch → 부모 MoumExt 로컬 크롬확장). iframe 이 부모와
    #      same-origin 이므로 이 파일이 로드되어 window.parent.MoumExt.send 를 호출한다.
    (
        "<script src=\"{{ url_for('static', filename='js/margin_rules.js') }}\"></script>",
        "<script src=\"{{ url_for('static', filename='margin_rules.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_ext_check.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_refresh_orders.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_kkadaegi_sent.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_rate_cell.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_route_cell.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_etc_reasons.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_all_tab.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_col_filter_fix.js') }}\"></script>  <!-- [모음전 2026-08-20] 전체내역 컬럼필터 (빈값)·제외/비대량등록 통일 -->\n"
        "  <script src=\"{{ url_for('static', filename='margin_settle_cell.js') }}\"></script>\n"
        "  <script src=\"{{ url_for('static', filename='margin_checksum.js') }}\"></script>\n"
        "  <style>.upload-row{grid-template-columns:1fr}</style>  <!-- [모음전] id=\"sellBox\" 감춤 → 매입 칸이 한 칸 전체 -->",
        1,
    ),
    # 2) 업로드 FormData 필드: 원본 buy_file/sell_file → 모음전 'file'
    (
        "for (const f of files) fd.append(type + '_file', f);",
        "for (const f of files) fd.append('file', f);  /* [모음전] /api/margin/upload* 는 'file' 필드 */",
        1,
    ),
    # 3) 업로드 엔드포인트: type 로 라우팅 (매입=더망고 / 매출=샵마인 보조)
    (
        "    const res  = await fetch('/api/upload', { method: 'POST', body: fd });",
        "    const _mUploadUrl = (type === 'buy') ? '/api/margin/upload' : '/api/margin/upload-shopmine';  /* [모음전] 매입=더망고, 매출=샵마인 */\n"
        "    const res  = await fetch(_mUploadUrl, { method: 'POST', body: fd });",
        1,
    ),
    # 4) 업로드 응답 정규화: 모음전은 flat {rows,markets,...} (원본 data[type].success 래퍼 없음)
    (
        "    const info = data[type];",
        "    const info = { success: true, rows: data.rows };  /* [모음전] /api/margin/upload* 는 flat {rows,markets,period_from,period_to} 반환 (success 래퍼 없음) */",
        1,
    ),
    # 5) 분석 엔드포인트 (3곳: 최초 분석 / 키워드 저장후 재분석 / 블랙스팟 재분석)
    ("'/api/analyze'", "'/api/margin/analyze'", 3),
    # 6) 내보내기: export 는 저장 payload 를 analysis_id 로 로드 → body 에 필수 주입
    (
        "    const body = JSON.stringify({\n      tab: useFilterMode ? 'detail_filtered' : 'all',",
        "    const body = JSON.stringify({\n      analysis_id: (window.analysisData && window.analysisData.analysis_id),  /* [모음전] /api/margin/export 는 저장 payload 로드에 analysis_id 필수 */\n      tab: useFilterMode ? 'detail_filtered' : 'all',",
        1,
    ),
    # 7) 내보내기 엔드포인트 URL (원본 /api/download → /api/margin/export)
    ("'/api/download'", "'/api/margin/export'", 1),
    # 8) [모음전 신규 씨앗] 분석 버튼 게이트 — 원본은 매입+매출 둘 다 업로드해야 활성
    #    (buyLoaded && sellLoaded). 모음전은 매출(SALES)이 분석 시점에 마켓 API 에서
    #    오고 사용자 업로드가 아니므로(샵마인 sell/보조 업로드는 OPTIONAL) 매입 업로드만
    #    으로 활성화해야 한다. updateAnalyzeBtn() + startAnalysis()의 finally 2곳 모두.
    (
        "!(buyLoaded && sellLoaded)",
        "!buyLoaded  /* [모음전] 매출=마켓API(분석시점)·샵마인 보조업로드 OPTIONAL → 매입만으로 활성 */",
        2,
    ),
    # 9) [모음전 신규 씨앗] 소싱처 주문번호 추출 — 무상태 서버는 uid 만으론 메모를 모른다.
    #    원본은 서버 store['buy_missing_df'] 에서 uid 로 행을 찾아 간단메모를 읽었다.
    #    모음전 analyze 는 무상태(그 저장소 없음) → uid 행의 간단메모를 클라이언트
    #    (window.analysisData.missing_order_no) 에서 찾아 POST 에 동봉한다. 그래야
    #    /api/blackspot/fetch_order_no 가 순수 파싱만으로 주문번호를 뽑을 수 있다.
    (
        "  fetch('/api/blackspot/fetch_order_no', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:uid})})",
        "  var _mMissRow = ((window.analysisData && window.analysisData.missing_order_no) || []).filter(function(x){return String(x['_uid'])===String(uid);})[0] || {};  /* [모음전] 무상태 서버 → uid 행의 간단메모를 클라에서 찾아 동봉 (_mMissRow) */\n"
        "  fetch('/api/blackspot/fetch_order_no', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({uid:uid, memo:(_mMissRow['간단메모']||'')})})  /* [모음전] memo 동봉 (_mMissRow) */",
        1,
    ),
    # 10) [모음전 신규 씨앗] 추출 성공 UX — 무상태 서버는 재매칭을 안 하므로:
    #     (a) '매칭 N건, 미기입 N건' 조각은 undefined 만 보여주고 거짓 숫자를 암시 → 제거.
    #     (b) analyzeAndRender()(재분석=로그 삭제)로 추출값을 날리는 대신, 반영칸
    #         (supp_input_<uid>)에 프리필해 사용자가 [✏️ 반영] 으로 확정하게 한다.
    #     로그는 그대로 유지. (검증 기준 = 사용자가 화면에서 보는 것)
    (
        "        const summary = '✅ ' + (res.site_name || '소싱처') + ' 주문번호: ' + res.order_no + ' (출처: ' + res.source + ')\\n매칭 ' + res.matched_count + '건, 미기입 ' + res.missing_count + '건';\n"
        "        if (logContent) logContent.textContent = logs + '\\n\\n' + summary;\n"
        "        analyzeAndRender();",
        "        const summary = '✅ ' + (res.site_name || '소싱처') + ' 주문번호: ' + res.order_no + ' (출처: ' + res.source + ')';  /* [모음전] 무상태 → 매칭/미기입 카운트 없음(거짓 숫자 금지) */\n"
        "        if (logContent) logContent.textContent = logs + '\\n\\n' + summary;\n"
        "        var _mSupp = document.getElementById('supp_input_' + uid); if (_mSupp) _mSupp.value = res.order_no;  /* [모음전] 무상태 → 재분석(로그 삭제) 대신 반영칸 프리필 */",
        1,
    ),
    # 11) [모음전 신규 씨앗 · E2] 소싱처 주문상태 확인 = 서버 Playwright(/api/check-sourcing) 제거
    #     → 로컬 크롬확장(window._moumExtCheckFetch, margin_ext_check.js 가 정의). 크롤=로컬 원칙.
    #     단일확인(checkSourcing)·일괄확인(_runBatchSourcingCheck) 2곳의 fetch 호출부만 치환한다.
    #     소비 코드(`var result = await resp.json();` + result.status/courier/tracking/error 사용)는
    #     그대로 — _moumExtCheckFetch 가 .json() 으로 동일 형태를 반환한다(다른 라인 무변경).
    #     확장 미설치/미로그인/파싱실패는 margin_ext_check.js 에서 정직하게 error 로 표면화.
    (
        "fetch('/api/check-sourcing', {",
        "_moumExtCheckFetch('/api/check-sourcing', {",
        2,
    ),
    # 12) [모음전 신규 씨앗] 매출 = 마켓 API 자동 조회 → 샵마인 매출 엑셀 업로드칸 제거.
    #     원본은 매입(더망고)·매출(샵마인) 두 업로드칸이 있으나, 모음전은 SALES 를
    #     분석 시점에 판매처 마켓 API 에서 자동 조회한다(사용자가 샵마인 엑셀을 올리지
    #     않음). 따라서 매출 업로드칸(label#sellBox)을 비상호작용 안내로 교체한다.
    #     ── JS 무결성: initUploadBox('sellBox','sellFileInput','sell') (원본 로직)이
    #     getElementById 로 두 요소를 찾으므로 id="sellBox"·sellFileInput·sellStatus 를
    #     그대로 남겨 콘솔 에러 없이 조용히 초기화되게 한다(sellLoaded 는 영구 false 지만
    #     분석 게이트가 이미 !buyLoaded(씨앗 8)라 무해). 외곽은 <label> 유지(닫는 태그
    #     무변경) + for 제거 + input 을 disabled·display:none 로 두어 클릭해도 파일창이
    #     열리지 않게 한다. 라벨/아이콘/설명/상태 텍스트만 안내 문구로 치환.
    (
        "    <label class=\"upload-box\" id=\"sellBox\" for=\"sellFileInput\">\n"
        "      <input type=\"file\" id=\"sellFileInput\" accept=\".xlsx,.xls,.htm,.html\" multiple>\n"
        "      <div class=\"upload-icon\">📤</div>\n"
        "      <div class=\"upload-label\">매출 엑셀 (샵마인)</div>\n"
        "      <div class=\"upload-sub\">.xlsx / .xls — 클릭 또는 드래그</div>\n"
        "      <div class=\"upload-status\" id=\"sellStatus\">파일 없음</div>\n"
        "    </label>",
        "    <label class=\"upload-box\" id=\"sellBox\" style=\"display:none\">  <!-- [모음전] 매출=마켓API 자동조회 → 올릴 게 없어 칸 자체를 감춘다(요소는 원본 initUploadBox 가 찾으므로 남김) -->\n"
        "      <input type=\"file\" id=\"sellFileInput\" accept=\".xlsx,.xls,.htm,.html\" multiple disabled style=\"display:none\">\n"
        "      <div class=\"upload-icon\">🔗</div>\n"
        "      <div class=\"upload-label\">매출 = 마켓 API 자동 조회</div>\n"
        "      <div class=\"upload-sub\">샵마인 업로드 불필요 — 분석 시작 시 판매처 API에서 매출을 불러옵니다</div>\n"
        "      <div class=\"upload-status\" id=\"sellStatus\" style=\"display:none\">파일 없음</div>\n"
        "    </label>",
        1,
    ),
    # 13) [모음전 신규 씨앗 · 버그수정] 업로드 에러 핸들러 이중읽기(body stream already read).
    #     원본은 res.json() 이 (비-JSON 본문에서) 읽기를 시작한 뒤 throw 하면, catch 의
    #     res.text() 가 "body stream already read" 로 다시 실패했다. 단일 읽기로 교체:
    #     본문을 text() 로 한 번만 읽고, 그 문자열을 JSON.parse 시도한다.
    (
        "      try { var ej = await res.json(); errText = ej.error || ''; } catch(_) { errText = await res.text(); }",
        "      var raw = ''; try { raw = await res.text(); } catch(_) {} try { errText = (JSON.parse(raw).error) || raw; } catch(_) { errText = raw || String(res.status); }  /* [모음전] 단일 읽기 — body stream 이중읽기 방지 */",
        1,
    ),
    # 14) [모음전 신규 씨앗] 연동 안 된/조회 실패한 마켓 표면화 (사용자 요청).
    #     서버 analyze 는 markets_failed(=제외 사유 배너 목록)을 응답에 담는다. 원본
    #     updateAnalyzeMsg 는 '분석 완료 N건 매칭 / 총매출 / 총마진'만 보여줘, 매출에서
    #     빠진 마켓이 조용히 사라진다(블랙스팟 오신호). analyze 메시지 아래에 빨간 안내로
    #     '이 마켓은 API 연동이 안 돼(또는 조회 실패) 제외됐어요'를 항상 표면화한다.
    #     updateAnalyzeMsg 는 제외/편집 토글마다 재실행되지만 innerHTML= 로 매번 새로
    #     조립 후 += 로 덧붙이므로 누적되지 않는다(멱등).
    (
        "    + ' <span style=\"margin-left:12px;color:' + (margn<0?'#dc2626':'#1AB053') + ';font-weight:700;font-size:35px;\">총마진 ' + fmtW(margn) + '원</span>';",
        "    + ' <span style=\"margin-left:12px;color:' + (margn<0?'#dc2626':'#1AB053') + ';font-weight:700;font-size:35px;\">총마진 ' + fmtW(margn) + '원</span>';\n"
        "  try{ var _sc=(window._moumSettleChips)?window._moumSettleChips((typeof getFilteredData==='function'&&(getFilteredData()||{}).matched)||(window.analysisData&&window.analysisData.matched)||[]):''; if(_sc) msg.innerHTML += _sc; }catch(_e){}  /* [모음전] 정산 정직성 색칩(실정산·추정·미확인) */\n"
        "  var _mFailed = (window.analysisData && window.analysisData.markets_failed) || [];  /* [모음전] 연동안됨/조회실패 마켓 표면화 (markets_failed) */\n"
        "  if (_mFailed.length) { msg.innerHTML += '<div style=\"margin-top:8px;padding:8px 12px;background:#FFF3F3;border:1px solid #FFD5D5;border-radius:8px;color:#dc2626;font-size:13px;line-height:1.65;\">⚠️ 아래 마켓은 API 연동이 안 됐거나 조회에 실패해 <b>매출에서 제외</b>하고 분석했어요:<br>' + _mFailed.map(function(w){ return '· ' + String(w); }).join('<br>') + '</div>'; }  /* [모음전] _mFailed 배너 */\n"
        "  var _mNotice = (window.analysisData && window.analysisData.notices) || [];  /* [모음전] 제외가 아닌 안내(_mNotice) — 빨간 배너와 분리 */\n"
        "  if (_mNotice.length) { msg.innerHTML += '<div style=\"margin-top:8px;padding:8px 12px;background:#F2F7FF;border:1px solid #CFE0F7;border-radius:8px;color:#1F4E86;font-size:13px;line-height:1.65;\">💡 ' + _mNotice.map(function(w){ return String(w).replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>'); }).join('<br>') + '</div>'; }  /* [모음전] _mNotice 배너 */\n"
        "  var _rFailed = window._moumRefreshFailed || [];  /* [모음전] 분석 앞단 최신수집(refreshOrdersToNow)에서 못 불러온 마켓 */\n"
        "  if (_rFailed.length) { msg.innerHTML += '<div style=\"margin-top:8px;padding:8px 12px;background:#FFF8E8;border:1px solid #F2D9A0;border-radius:8px;color:#8A5A00;font-size:13px;line-height:1.65;\">⏳ 분석 전 <b>최신 주문 받아오기</b>에 실패한 판매처가 있어요 — 아래 마켓은 <b>저장된(옛) 주문</b>으로 분석했습니다:<br>' + _rFailed.map(function(w){ return '· ' + String(w); }).join('<br>') + '</div>'; }  /* [모음전] _rFailed 배너 */",
        1,
    ),
    # 15) 「최신까지 불러오기」 버튼 — **삭제됨** (2026-08-02 사장님 지적).
    #     이 버튼은 #414 에서 생겼고, 그때는 「분석 시작」과 별개로 먼저 눌러야 했다.
    #     그런데 바로 다음 #419 가 아래 16) 씨앗으로 「분석 시작」이 같은 함수를
    #     **조건 없이 먼저** 돌리게 바꿨다 → 그 순간부터 버튼은 완전한 중복이었다.
    #     (남겨 두면 "이걸 먼저 눌러야 하나?" 하는 잘못된 순서 안내가 된다.)
    #     ★ 버튼만 없앤다. 수집 자체(마켓별로 나눠 /api/orders-ingest/run-sync 호출)는
    #       그대로 필요하다 — 6마켓을 한 요청에 묶으면 옥션 58.1초에 묶여 서버 상한을
    #       넘고 응답이 JSON 이 아니게 된다(2026-07-23 실측 61.7초 → 502 → "서버 오류").
    #       그래서 static/margin_refresh_orders.js 와 씨앗 1)의 script ref 는 유지한다.
    #     자리는 따로 옮기지 않는다 — 버튼이 빠지면 「분석 시작」이 그 자리로 온다
    #     (원본에서 두 버튼이 이미 나란히 붙어 있다: 금액대 설정 → [삭제] → 분석 시작).
    # 16) [모음전 신규 씨앗] 「분석 시작」이 최신 수집을 **먼저** 돌린다 (사장님 지시: 라이브로).
    #     분석 요청 하나에 6마켓 라이브 조회를 넣으면 61.7초로 서버 상한을 넘어 502 가 된다.
    #     그래서 순서를 바꾼다: (마켓별로 나눠 수집) → (저장분 분석). 결과는 라이브와 같고
    #     요청은 각각 짧다. 수집이 실패해도 분석은 진행한다 — 저장분만으로도 결과는 나오고,
    #     못 불러온 마켓은 refreshOrdersToNow 가 이름을 남겨 화면에 보인다(조용한 실패 금지).
    (
        "async function startAnalysis() {",
        "async function startAnalysis() {\n"
        "  try { var _b0 = document.getElementById('analyzeBtn'); if (_b0) _b0.disabled = true;  /* [모음전] refreshOrdersToNow 전에 버튼부터 잠금 — 1분 가까이 걸려 '눌러도 반응 없음'으로 보인다 */\n"
        "        if (window.refreshOrdersToNow) await window.refreshOrdersToNow(); }  /* [모음전] 분석 전 최신 수집 (refreshOrdersToNow) — 실패 마켓은 window._moumRefreshFailed 로 남아 씨앗 14 배너가 그린다 */\n"
        "  catch (_) {}  /* [모음전] refreshOrdersToNow 실패해도 분석은 진행 */",
        1,
    ),
    # ── 17~23) [모음전 신규 씨앗] 「까대기 송장번호 전송 완료」 카드 (사장님 지시 2026-07-23)
    #   대상 = 더망고 「현지배송완료」(까대기 주문 후 송장 뽑아 마켓까지 전송한 건).
    #   「해외현지배송중」(주문만 넣은 상태)은 기존 까대기 카드 그대로 — 섞지 않는다.
    #   카드 안 양분(송장 입력 완료/미입력)과 막대 조립은 static/margin_kkadaegi_sent.js.
    # 17) 카드 키워드 기본값
    (
        "    kkadaegi:            {mg: ['해외현지배송중']},",
        "    kkadaegi:            {mg: ['해외현지배송중']},\n"
        "    kkadaegi_sent:       {mg: ['현지배송완료']},  /* [모음전] 까대기 송장번호 전송 완료 */",
        1,
    ),
    # 18) 카드 색 — 까대기와 짝으로 보이게 같은 teal 계열
    (
        "  kkadaegi:   {main:'#0D9488', bg:'#ccfbf1', text:'#065f46', emoji:'📦', label:'까대기'},",
        "  kkadaegi:   {main:'#0D9488', bg:'#ccfbf1', text:'#065f46', emoji:'📦', label:'까대기'},\n"
        "  kkadaegi_sent: {main:'#0D9488', bg:'#ccfbf1', text:'#065f46', emoji:'🚚', label:'까대기 송장번호 전송 완료'},  /* [모음전] */",
        1,
    ),
    # 19) 카드 설명 한 줄
    (
        "  kkadaegi:  {sub:'해외→사무실 입고 후 발송 예정', reason:'소싱처에서 우리 사무실로 배송 중(까대기) — 입고 확인 후 고객 발송'},",
        "  kkadaegi:  {sub:'해외→사무실 입고 후 발송 예정', reason:'소싱처에서 우리 사무실로 배송 중(까대기) — 입고 확인 후 고객 발송'},\n"
        "  kkadaegi_sent:  {sub:'송장 뽑아 마켓까지 전송 완료', reason:'까대기 주문 후 송장번호를 입력해 마켓까지 전송한 건 — 실제 발송 여부는 별도 확인'},  /* [모음전] */",
        1,
    ),
    # 20) 카드 건수 집계
    (
        "    kkadaegi:   cnt('kkadaegi'),",
        "    kkadaegi:   cnt('kkadaegi'),\n"
        "    kkadaegi_sent: cnt('kkadaegi_sent'),  /* [모음전] */",
        1,
    ),
    # 21) 판정 재료 — 2곳(카드 필터·breakdown) 모두 같은 변수를 갖게 한다.
    #     ★키워드가 팀 DB 설정에 아직 없으면 _kw 가 빈 목록을 준다 → 아무것도 매칭 못 해
    #       카드가 0 건이 된다(2026-07-23 라이브에서 실제로 그랬다). 팀 DB 는 최초 1회만
    #       시드되므로 나중에 추가한 카드는 영영 안 들어간다 → 기본값을 여기서 준다.
    (
        "    var isMgKkadaegi     = _matchesAny(mg, _kw('kkadaegi', 'mg'));",
        "    var isMgKkadaegi     = _matchesAny(mg, _kw('kkadaegi', 'mg'));\n"
        "    var _kwSent = _kw('kkadaegi_sent', 'mg'); if (!_kwSent.length) _kwSent = ['현지배송완료'];  /* [모음전] kkadaegi_sent 기본값 — 팀 DB 에 없으면 0건이 된다 */\n"
        "    var isMgKkadaegiSent = _matchesAny(mg, _kwSent);  /* [모음전] kkadaegi_sent 판정 */",
        2,
    ),
    # 22) 분류 우선순위 — **맨 앞**(까대기와 같은 급). 사장님 확정 2026-07-23:
    #     "기타뿐 아니라 현지배송완료는 **모두** 까대기 송장완료 카드로".
    #     ⚠️ 그 대가로 다른 카드에 있던 현지배송완료 건도 이 카드로 옮겨온다
    #        (골든 실측: tracking_failed 1→0 · mango_check 3→2). 의도된 이동이다.
    (
        "    if (isMgKkadaegi)                                            return type === 'kkadaegi';",
        "    if (isMgKkadaegiSent)                                        return type === 'kkadaegi_sent';  /* [모음전] 현지배송완료는 상태 불문 전부 이 카드 */\n"
        "    if (isMgKkadaegi)                                            return type === 'kkadaegi';",
        1,
    ),
    # 23) 카드 이름표(2곳)
    (
        "kkadaegi:'까대기',",
        "kkadaegi:'까대기',kkadaegi_sent:'까대기 송장번호 전송 완료',",
        2,
    ),
    # 24) [모음전 신규 씨앗] 카드 배치 — 사장님 지정(2026-07-23)
    #     1행 : 정상/완료 · 발송 대기 · 송장 재전송 실패
    #     2행 : 까대기 · 까대기 송장번호 전송 완료
    #     (원본은 1행에 까대기, 그 아래 송장 재전송 실패가 혼자 넓은 줄을 썼다)
    #   ⚠️ 지우는 줄을 최소화한다 — 동치 가드는 **변경된 모든 줄**에 씨앗 토큰을 요구하는데,
    #      지워지는 원본 줄에는 토큰을 심을 수 없다. 그래서 감싸는 <div> 줄은 건드리지 않고
    #      카드 줄만 바꾼다(1행의 까대기 자리 → 송장 재전송 실패 / 그 아래 2행 신설).
    (
        "  h += _summaryCardHTML('kkadaegi', ex.kkadaegi, '까대기',    'teal');",
        "  h += _summaryCardHTML('tracking_failed', ex.tracking_failed, '송장 재전송 실패', 'cyan', _splitTrackingNormalEtc('tracking_failed'));  /* [모음전] kkadaegi_sent 배치 — 1행으로 이동 */",
        1,
    ),
    # ── 26~28) 「기타」로 새던 상태 3종 (2026-07-24 실측: 기타 55건 = 롯데온 55건) ──
    #   저장된 분석(414행)을 화면과 같은 코드로 돌려 사유를 셌다:
    #     · 53건 국내배송중 + 판매처 '출고지시'  → 어느 목록에도 없어 끝까지 떨어짐
    #     ·  1건 국내배송중 + 판매처 '취소요청'  → 진행중 목록에 '취소요청'이 없었다
    #        (반품요청·교환요청은 있는데 취소요청만 빠져 있었다)
    #     ·  1건 더망고 '결제완료'               → 국내배송중 규칙 자체가 안 걸림
    # 31) [모음전 신규 씨앗] 매출 = **고객이 실제로 낸 돈** (사장님 확정 2026-07-24).
    #     원본은 매출을 `판매가`(단가×수량)로 본다 — 할인 전 금액이라 실제 매출과 다르다
    #     (실측: 판매가 36,700 vs 실결제 32,740). 고객 결제금액 = 상품 실결제 + 배송비 결제.
    #     ★배송비는 배송건 첫 행에만 실려 있어 행별로 더해도 중복되지 않는다.
    #     ★실결제가 없는 옛 데이터는 기존 계산(판매가)으로 물러난다 — 0 으로 만들지 않는다.
    #     ⚠️ 지우는 줄이 없도록 함수 첫머리에 **덧붙이기만** 한다(동치 가드가 지워지는 줄에도
    #        씨앗 토큰을 요구하는데 원본 줄엔 토큰을 심을 수 없다).
    #     ★2026-08-13 사장님 재확정 — 매출 = 정가 + 배송비 − **판매자부담** 할인.
    #        실결제는 마켓이 부담한 할인까지 빠진 값이라 우리 매출보다 작다(라이브 30일 실측:
    #        롯데온 3,205,562원·스스 24,000원 과소). 마켓 부담분은 마켓이 대신 내주고 우리는
    #        정가대로 정산받으므로 빼면 안 된다.
    #        값은 주문내역(order_export)이 `_매출기준액` 한 칸으로 만들어 둔다 — 화면은 **받아
    #        쓰기만** 한다(두 곳이 각자 계산하면 규약 바뀐 날 조용히 갈린다).
    (
        "function saleAmt(r) {",
        "function saleAmt(r) {\n"
        "  if (!r) return 0;  /* [모음전 매출기준] r 접근 전 가드 */\n"
        "  var _sale = Number(r['_매출기준액']);  /* [모음전 매출기준] 정가+배송비−판매자할인 */\n"
        "  if (isFinite(_sale) && _sale > 0) return _sale;  /* [모음전 매출기준] 단일 원천 */\n"
        "  var _paid = Number(r['실결제금액']);  /* [모음전 매출기준] 폴백 — 할인 모름·옛 저장분 */\n"
        "  if (isFinite(_paid) && _paid > 0) return _paid + (Number(r['배송비']) || 0);  /* [모음전 매출기준] */",
        1,
    ),
    # 33) [모음전 신규 씨앗] 기간 평균 배너도 **같은 매출 정의**를 쓴다 (2026-08-13).
    #     원본은 여기만 판매가(단가×수량)라, 같은 화면 안에서 상단 카드와 숫자가 달랐다.
    (
        "    s += MR.rowSale(r, function(x){ return Number(x['판매가']||0)||0; });",
        "    s += MR.rowSale(r, saleAmt);  /* [모음전 매출기준] 상단 카드·집계탭과 같은 정의 */",
        1,
    ),
    # 34) [모음전 신규 씨앗] 총매출 카드 부제 — 라벨은 「판매가」인데 값은 매출 기준이라
    #     서로 달랐다(사장님이 화면에서 잡아내신 자리). 뜻대로 고친다.
    (
        "     + _sumCard('총매출','판매가', fmt(매출)+'원')",
        "     + _sumCard('총매출','정가−판매자할인', fmt(매출)+'원')  /* [모음전 매출기준] 표기 */",
        1,
    ),
    # 32) [모음전 신규 씨앗] 카드 「세부보기」 → **전체내역 탭**으로 통일 (사장님 확정).
    #     그동안 ①카드 아래 상세내역 ②전체내역 두 갈래였다 → 전체내역 하나만 쓴다.
    #     카드를 누르면 전체내역으로 가서 **그 카드 건만** 남는다.
    #     원본 showCardBreakdown 은 폴백으로 남긴다(스크립트 미로드 시 옛 동작).
    (
        '    + \'<button onclick="event.stopPropagation();showCardBreakdown(\\\'\'+type+\'\\\',\'+\'\\\'\'+label+\'\\\')" \'',
        '    + \'<button onclick="event.stopPropagation();(window._goAllWithCardFilter||showCardBreakdown)(\\\'\'+type+\'\\\',\'+\'\\\'\'+label+\'\\\')" \'  /* [모음전] _goAllWithCardFilter — 전체내역으로 통일 */',
        1,
    ),
    (
        "    + 'title=\"'+btnTitle+'\">📋 세부보기</button>'",
        "    + 'title=\"'+btnTitle+'\">📋 전체내역에서 보기</button>'  /* [모음전] _goAllWithCardFilter */",
        1,
    ),
    (
        "  var cols = ['마켓주문일자','마켓명','_소싱처','마켓주문번호','수령인명','마켓상품명','옵션1','구매가격','샵마인_정산예상금액(배송비포함)','마진금액','마진율','더망고주문상태 (사용자 연동)','마켓주문상태 (오픈 마켓 연동)','샵마인_주문상태','샵마인_샵마인주문상태','샵마인_송장입력','간단메모','교차검증','확인사항','소싱처확인결과','_추가메모'];",
        "  var cols = ['제외','비대량등록','더망고주문상태 (사용자 연동)','마켓주문상태 (오픈 마켓 연동)','국내송장번호','샵마인_주문상태','샵마인_송장입력','샵마인_택배사','주문일','_소싱처','마켓','마켓주문번호','수령인명','브랜드','상품명','옵션_매출','단가','수량_매출','실결제금액','배송비','정산예상금액','구매가격','순마진','마진율','판매경로','소싱처확인결과','간단메모','_추가메모'];  /* [모음전] 전체내역 열 구성 — 사장님 지정 순서 2026-07-24, 제외·비대량등록·간단메모 추가 2026-07-25 */",
        1,
    ),
    (
        "    '소싱처확인결과':'소싱처 주문상태',\n    '_추가메모':'추가메모'\n  };",
        "    '소싱처확인결과':'소싱처 주문상태',\n    '_추가메모':'추가메모',\n    /* [모음전] colLabels — 사장님 지정 열 이름표(어느 쪽 자료인지 앞에 붙임) */\n    '국내송장번호':'[더망고] 송장번호',\n    '샵마인_송장입력':'[판매처] 송장번호',\n    '샵마인_주문상태':'[판매처] 주문상태',\n    '주문일':'주문일',\n    '마켓':'판매처',\n    '상품명':'상품명',\n    '옵션_매출':'옵션',\n    '수량_매출':'수량',\n    '정산예상금액':'정산예정금액(배송비포함)',\n    '구매가격':'매입가(더망고)',\n    '순마진':'순마진',\n    '제외':'제외',\n    '비대량등록':'비대량등록',\n    '간단메모':'[더망고] 간단메모',\n    '샵마인_택배사':'[판매처] 택배사'\n  };",
        1,
    ),
    # 33) [모음전 신규 씨앗] buildDetailTable 도 제외·비대량등록·간단메모 열을 **항상** 보이게
    #     (사장님 요청 2026-07-25 — 전체내역 탭처럼 체크 가능하게). usedCols 필터가 값 없는
    #     열을 떨어뜨리는데, 이 세 열은 값이 비어도 유지해야 체크박스·메모 칸이 나온다.
    (
        "  var usedCols = cols.filter(function(c){ if(c==='소싱처확인결과' || c==='_추가메모') return true; return rows.some(function(r){ return r[c]!=null && r[c]!==''; }); });",
        "  var usedCols = cols.filter(function(c){ if(c==='소싱처확인결과' || c==='_추가메모' || c==='제외' || c==='비대량등록' || c==='간단메모' || c==='샵마인_택배사') return true; return rows.some(function(r){ return r[c]!=null && r[c]!==''; }); });  /* [모음전] 제외·비대량등록·간단메모 항상 표시 */",
        1,
    ),
    # 30) [모음전 신규 씨앗] 「정상/완료」 카드에 역마진 경고 (사장님 지적 2026-07-24).
    #     카드는 주문 상태만 보므로 마진율 −101% 인 건도 배송만 끝났으면 정상으로 앉는다.
    #     분류를 바꾸는 게 아니라(그 건은 실제로 매입가가 판매가의 1.9배였다) **보이게** 한다.
    #     손실 판정은 margin_rules.js(MR) 단일 원천. 로직은 static/margin_etc_reasons.js.
    (
        "  h += _summaryCardHTML('normal',   ex.normal,   '정상/완료', 'green');",
        "  h += (window._normalCardHTML ? window._normalCardHTML(ex.normal)\n"
        "                               : _summaryCardHTML('normal',   ex.normal,   '정상/완료', 'green'));  /* [모음전] 역마진 경고 (_normalCardHTML) */",
        1,
    ),
    # 32) [모음전 신규 씨앗] 편집 시 마진율 재계산도 매출=실결제+배송비 기준 (사장님 확정
    #     2026-07-25). 서버 pipeline._recompute_margin_rate 와 같은 규칙 — 안 맞추면
    #     셀을 편집한 순간 그 행만 판매가 기준으로 되돌아가 화면이 갈린다.
    #     실결제 없으면 판매가→정산 순으로 폴백(원본 규칙 보존).
    #     ★2026-08-13 — 단가를 손으로 고치면 서버가 만든 `_매출기준액`이 낡는다. 판매자부담
    #        할인만 살려 다시 만든다: 할인 = (총주문금액+배송비) − 매출기준액.
    #        둘 중 하나라도 모르면 손대지 않고 옛 폴백(실결제+배송비 → 판매가 → 정산).
    (
        "  const _rateBase = 판매가 > 0 ? 판매가 : 정산;",
        "  var _ship = Number(r['배송비']) || 0, _paid = Number(r['실결제금액']) || 0;  /* [모음전 매출기준] */\n"
        "  var _opt = Number(r['옵션추가금']) || 0;  /* [모음전 매출기준] 정가=단가×수량+옵션추가금 */\n"
        "  var _gross0 = Number(r['총주문금액']) || 0, _sale0 = Number(r['_매출기준액']) || 0;  /* [모음전 매출기준] */\n"
        "  if (_gross0 > 0 && _sale0 > 0) {  /* [모음전 매출기준] 편집으로 낡은 값을 다시 만든다 */\n"
        "    var _sellerDc = Math.max(0, (_gross0 + _ship) - _sale0);  /* [모음전 매출기준] 판매자부담 */\n"
        "    r['_매출기준액'] = Math.max(0, (판매가 + _opt) + _ship - _sellerDc);  /* [모음전 매출기준] */\n"
        "  }  /* [모음전 매출기준] */\n"
        "  var _sale = Number(r['_매출기준액']) || 0;  /* [모음전 매출기준] */\n"
        "  const _rateBase = _sale > 0 ? _sale  /* [모음전 매출기준] */\n"
        "                  : (_paid > 0 ? (_paid + _ship) : (판매가 > 0 ? 판매가 : 정산));  /* [모음전 매출기준] 폴백 */",
        1,
    ),
    # 31) [모음전 신규 씨앗] 전체내역 송장번호 앞에 택배사 이름 (사장님 요청 2026-07-24).
    #     [더망고] 송장번호(국내송장번호) → '국내송장번호 택배사'(더망고 엑셀 값),
    #     [판매처] 송장번호(샵마인_송장입력) → '샵마인_택배사'(ESM TakbaeName·pipeline 이 부착).
    #     ★택배사 코드가 불안정한 마켓(11번가 등)은 실값이 없어 번호만 나온다 — 이름을
    #       지어내지 않는다(무결성 1원칙). 기본 렌더 줄 앞에 두 열만 가로챈다.
    (
        "      h += '<td title=\"'+String(v).replace(/\"/g,'&quot;')+'\">'+esc(v)+'</td>';",
        "      if(c==='제외'||c==='비대량등록'){  /* [모음전] 제외·비대량등록 체크박스 (전체내역 탭과 동일) */\n"
        "        var _cbIdx=(r&&r._idx!=null)?r._idx:-1;  /* [모음전] 체크박스 */\n"
        "        var _on=(c==='제외')?!!r._excluded:!!r._manual_reg;  /* [모음전] 체크박스 */\n"
        "        var _fn=(c==='제외')?'toggleExclude':'toggleManualReg';  /* [모음전] 체크박스 */\n"
        "        var _ccls=(c==='제외')?'excl-cell':'mreg-cell';  /* [모음전] 체크박스 */\n"
        "        h += '<td class=\"'+_ccls+'\"><input type=\"checkbox\"'+(_on?' checked':'')+' onchange=\"'+_fn+'('+_cbIdx+', this.checked)\"></td>';  /* [모음전] 체크박스 */\n"
        "        return;  /* [모음전] 체크박스 */\n"
        "      }  /* [모음전] 체크박스 */\n"
        "      if(c==='정산예상금액' && window._moumSettleCell){  /* [모음전] 정산 추정/미확인 배지+호버(왜 추정인지) */\n"
        "        h += window._moumSettleCell(r, v, esc);  /* [모음전] 정산 정직성 셀 */\n"
        "        return;  /* [모음전] 정산 정직성 셀 */\n"
        "      }  /* [모음전] 정산 정직성 셀 */\n"
        "      if(c==='국내송장번호' && v){  /* [모음전] [더망고] 송장번호 앞 택배사(인라인) */\n"
        "        var _cr=String(r['국내송장번호 택배사']||'').trim();  /* [모음전] 없으면 번호만 — 이름 날조 금지 */\n"
        "        h += '<td>'+(_cr?'<b style=\"font-weight:600\">'+esc(_cr)+'</b> ':'')+esc(v)+'</td>';  /* [모음전] 택배사 */\n"
        "        return;  /* [모음전] 택배사 */\n"
        "      }  /* [모음전] 택배사 */\n"
        "      if(c==='샵마인_택배사'){  /* [모음전] [판매처] 택배사 별도 칼럼 (사장님 요청 2026-07-25) */\n"
        "        var _pc=String(r['샵마인_택배사']||'').trim();  /* [모음전] 없으면 빈칸 — 이름 날조 금지 */\n"
        "        h += '<td>'+(_pc?'<b style=\"font-weight:600\">'+esc(_pc)+'</b>':'<span style=\"color:#c4c4c4\">-</span>')+'</td>';  /* [모음전] 택배사 */\n"
        "        return;  /* [모음전] 택배사 */\n"
        "      }  /* [모음전] 택배사 */\n"
        "      h += '<td title=\"'+String(v).replace(/\"/g,'&quot;')+'\">'+esc(v)+'</td>';",
        1,
    ),
    # 35) [모음전 신규 씨앗] 전체내역 탭을 카드 상세와 **완전 같은 뿌리**로 (사장님 확정
    #     2026-07-25). 탭 디스패치 map.all 이 렉시컬 renderAll 을 잡아 외부 override 가 안
    #     먹으므로, 여기서 window._moumRenderAll 이 있으면 그걸 쓰게 연다. 실제 위임 구현은
    #     static/margin_all_tab.js — buildDetailTable 로 렌더해 편집·체크박스·간단메모까지
    #     카드 상세와 동일. 데이터(analysisData)가 공유라 한쪽 수정이 양쪽에 반영된다.
    (
        "    all:        renderAll,",
        "    all:        (window._moumRenderAll || renderAll),  /* [모음전] 전체내역=카드 상세 통일 override */",
        1,
    ),
    # 34) [모음전 신규 씨앗] 카드 상세(buildDetailTable)에도 단가·정산·매입 인라인 편집
    #     (사장님 확정 2026-07-25 — 전체내역 탭과 카드 상세를 **완전 같은 뿌리**로, 한쪽에서
    #     수정하면 동기화). editCell 이 analysisData(공유 데이터)를 고치고 _refreshRowDisplay
    #     가 「마지막 편집칸 다음 두 칸」으로 순마진·마진율을 갱신 — cols 에서 구매가격→순마진
    #     →마진율이 연속이라 그대로 맞는다. numCols 처리보다 **앞**에 둔다(숫자로 안 굳게).
    #     renderAll 이 이 함수에 위임하므로 전체내역 탭도 자동으로 같은 편집을 얻는다.
    (
        "      if(numCols[c] && typeof v==='number') {",
        "      if(c==='단가'||c==='정산예상금액'||c==='구매가격'){  /* [모음전] 인라인 편집(공용 뿌리) */\n"
        "        var _eIdx=(r&&r._idx!=null)?r._idx:-1;  /* [모음전] 편집 */\n"
        "        var _ev=Number(r[c])||0, _eed=r['_edited_'+c]?' edited':'';  /* [모음전] 편집 */\n"
        "        var _sbdg=(c==='정산예상금액'&&window._moumSettleBadge)?window._moumSettleBadge(r,_ev):'';  /* [모음전] 인라인편집 input 옆 정산 추정/미확인 배지 */\n"
        "        h += '<td style=\"white-space:nowrap\"><input type=\"number\" class=\"cell-input'+_eed+'\" value=\"'+_ev+'\" onchange=\"editCell('+_eIdx+', &quot;'+c+'&quot;, this.value)\" title=\"수정 시 마진 자동 재계산\">'+_sbdg+'</td>';  /* [모음전] 편집+정산 배지 */\n"
        "        return;  /* [모음전] 편집 */\n"
        "      }  /* [모음전] 편집 */\n"
        "      if(numCols[c] && typeof v==='number') {",
        1,
    ),
    # 26-a) 🔴 '배송중'을 **발송 대기 목록에서 뺀다** (2026-07-24 실측: 발송대기 50건 중
    #      15건이 이미 발송된 건이었다 — 판매처 배송중 8 + 발송완료(배송중) 7, 송장 전부 있음).
    #      '발송 대기'는 아직 안 보낸 것인데 '배송중'은 이미 보낸 것이라 목록 자체가 모순이었고,
    #      '발송완료(배송중)' 도 글자에 '배송중'이 들어 있어 같이 걸렸다.
    #      빼면 바로 아래 줄의 `sm.indexOf('배송')` 에 걸려 정상/완료로 간다.
    (
        "        sm.indexOf('배송중') >= 0 || sm.indexOf('배송준비') >= 0 || sm.indexOf('발송대기') >= 0 || sm.indexOf('상품준비') >= 0",
        "        sm.indexOf('배송준비') >= 0 || sm.indexOf('발송대기') >= 0 || sm.indexOf('상품준비') >= 0  /* [모음전] '배송중' 제외 — 이미 발송된 건이 발송 대기로 잡히던 것 */",
        2,
    ),
    # 26) 출고지시 → 정상/완료 (사장님 확정 — 송장까지 전송돼 손 뗄 일 없는 건)
    (
        "        sm.indexOf('구매확정') >= 0 || sm.indexOf('수취완료') >= 0 || sm.indexOf('배송완료') >= 0 || sm.indexOf('확정') >= 0 || sm.indexOf('배송') >= 0",
        "        sm.indexOf('구매확정') >= 0 || sm.indexOf('수취완료') >= 0 || sm.indexOf('배송완료') >= 0 || sm.indexOf('확정') >= 0 || sm.indexOf('배송') >= 0 || sm.indexOf('출고지시') >= 0  /* [모음전] 롯데온 출고지시 — 기타로 새던 53건 */",
        2,
    ),
    # 27) 취소요청 → 진행중 (반품요청·교환요청은 이미 있는데 취소요청만 빠져 있었다)
    (
        "  var PROGRESS_PATTERNS = ['회수지시','철회','진행중','취소진행','반품진행','교환진행','출고중지','반품접수','반품요청','교환신청','교환요청'];",
        "  var PROGRESS_PATTERNS = ['회수지시','철회','진행중','취소진행','반품진행','교환진행','출고중지','반품접수','반품요청','교환신청','교환요청','취소요청'];  /* [모음전] 취소요청 추가 — 기타로 새던 1건 */",
        2,
    ),
    # 28) 더망고 '결제완료' → 발송 대기 (서버 config MANGO_PENDING_STATUSES 와 같은 뜻).
    #     ★위치는 **기타 직전**이다. isMgPending 자리(7순위)에 두면 더망고 점검·진행중보다
    #       앞서서, 점검이 필요한 결제완료 건까지 발송 대기로 숨는다
    #       (실측: mango_check 1 → 0 으로 사라졌다. 사장님이 요청한 이동이 아니다).
    #       기타로 갈 뻔한 행만 가져간다.
    (
        "    /* ★ 마지막 분기: 메모 unknown korean → etc (위에서 이동) */",
        "    if (mg.indexOf('결제완료') >= 0)                              return type === 'pending';  /* [모음전] 결제완료=발송 전 → 발송 대기(기타로 갈 뻔한 것만) */\n"
        "    /* ★ 마지막 분기: 메모 unknown korean → etc (위에서 이동) */",
        1,
    ),
    # 29) [모음전 신규 씨앗] 「기타」 카드에 '왜 기타인지' 사유 표시 (사장님 확정 2026-07-24).
    #     기타는 '어느 조건에도 안 걸린 나머지'라 숫자만 보면 원인을 알 수 없다.
    #     (판매처 · 판매처 주문상태)로 묶어 많은 순서로 보여준다 — 모르는 상태가 생기면
    #     카드만 봐도 드러난다. 로직은 static/margin_etc_reasons.js.
    (
        "  h += _summaryCardHTML('etc',             ex.etc,             '기타',                     'gray');",
        "  h += (window._etcCardHTML ? window._etcCardHTML(ex.etc)\n"
        "                            : _summaryCardHTML('etc',             ex.etc,             '기타',                     'gray'));  /* [모음전] 기타 사유 표시 (_etcCardHTML) */",
        1,
    ),
    # 25) 그 아래 줄을 '까대기 · 까대기 송장번호 전송 완료' 2칸으로 (바깥 div 는 원본 그대로 재사용)
    (
        "  /* 🆕 송장 재전송 실패 — 사용자 요청 (대부분 정상, 일부 점검) */",
        "  /* [모음전] 2행 — 까대기 · 까대기 송장번호 전송 완료 (kkadaegi_sent) */",
        1,
    ),
    (
        "  h += _summaryCardHTML('tracking_failed', ex.tracking_failed, '송장 재전송 실패', 'cyan', _splitTrackingNormalEtc('tracking_failed'));\n"
        "  h += '</div>';",
        "  h += '<div style=\"display:grid;grid-template-columns:repeat(2,1fr);gap:6px\">';  /* [모음전] kkadaegi_sent 2행 */\n"
        "  h += _summaryCardHTML('kkadaegi', ex.kkadaegi, '까대기',    'teal');  /* [모음전] kkadaegi_sent 와 짝 */\n"
        "  h += (window._kkadaegiSentCardHTML ? window._kkadaegiSentCardHTML(ex.kkadaegi_sent)\n"
        "                                     : _summaryCardHTML('kkadaegi_sent', ex.kkadaegi_sent, '까대기 송장번호 전송 완료', 'teal'));\n"
        "  h += '</div>';  /* [모음전] kkadaegi_sent 2행 닫기 */\n"
        "  h += '</div>';",
        1,
    ),
    # 26) 마진율 칸 — 판매가·정산이 둘 다 0 이면 「계산불가」로 표시(2026-07-24 사장님).
    #     마진율 = 순마진 ÷ 판매가 인데 판매가 0 이면 분모가 0 이라 규칙상 0 이 나오고,
    #     화면엔 0.0% 로 찍힌다. 그 0.0% 가 '마진 없음'처럼 보여, 실제로는 매입 36,490원을
    #     통째로 손해 본 역마진 건이 아무 표시 없이 정상처럼 지나갔다(라이브 실측).
    #     로직은 static/margin_rate_cell.js 에 두고 본문엔 **호출 한 줄만** 넣는다
    #     (본문 무수정 원칙 — kkadaegi_sent 와 같은 방식). 함수가 없으면 원본대로 렌더.
    (
        "       + '<td style=\"font-weight:700;\"' + (dispMarginRate < 0 ? ' class=\"neg\"' : '') "
        "+ '>' + (isBs ? '-100%' : fmtPct(r['마진율'])) + '</td>'",
        "       + (window._moumMarginRateCell ? window._moumMarginRateCell(r, isBs, dispMarginRate, fmtPct) "
        ": '<td style=\"font-weight:700;\"' + (dispMarginRate < 0 ? ' class=\"neg\"' : '') "
        "+ '>' + (isBs ? '-100%' : fmtPct(r['마진율'])) + '</td>')",
        1,
    ),
]

# 27) 판매경로 칸 — '미확인'을 회색으로 떼기 (2026-07-25 샵마인 대조).
#     원본은 '제휴'가 아닌 값을 전부 롯데ON 파란 칸으로 그려, '미확인'인데도 확정된
#     롯데ON 처럼 보였다(2% 안 뗀 정산이 맞는 값처럼 읽힘). 로직은 static/margin_route_cell.js
#     에 두고 본문엔 호출 한 줄만 넣는다(무수정 원칙 — margin_rate_cell.js 와 같은 방식).
#     ★IIFE 의 여는/닫는 줄은 건드리지 않는다 — 즉시함수 **안쪽 첫 줄**에 가드만 끼운다.
#       (바깥에서 감싸면 '+ (function(){' · '})()' 줄까지 바뀌어 무수정 diff 가드에 걸린다.)
#       함수 없으면 그 아래 원본 그대로 렌더(폴백).
SEAMS.append((
    "       + (function(){\n"
    "           /* 판매경로 — 롯데온 제휴(상품가 2% 수수료)/롯데ON(0). 크롤 확정값. */",
    "       + (function(){\n"
    "           if (window._moumRouteCell) return window._moumRouteCell(r, esc);"
    "  /* [모음전] 판매경로 칸: '미확인' 회색 분리 (margin_route_cell.js) */\n"
    "           /* 판매경로 — 롯데온 제휴(상품가 2% 수수료)/롯데ON(0). 크롤 확정값. */",
    1,
))

# ── [모음전 신규 씨앗] 「검산 요약」 + 실마켓(API) 미매칭 카드 + '샵마인'→'실마켓(API)' 개명
#    (사장님 확정 2026-07-25) ────────────────────────────────────────────────
# 검산 요약(가로 3분할: 총/매칭/미매칭+바로가기) — 최상단(가로탭 아래·이상마진 배너 위).
#   탭 디스패치가 이상마진 배너를 prepend(renderAbnormalBanner + html)하는 바로 뒤에서,
#   블랙스팟 탭에 한해 요약을 다시 prepend → 최종순서 = [검산요약][이상마진][본문].
#   본문 무수정 원칙: 로직은 static/margin_checksum.js, 여기선 호출 한 줄만.
SEAMS.append((
    "    html = renderAbnormalBanner(bannerRows) + html;",
    "    html = renderAbnormalBanner(bannerRows) + html;\n"
    "    if (currentTab === 'blackspot' && window._moumChecksumHTML) html = window._moumChecksumHTML() + html;  /* [모음전] 분류 검산 요약 최상단 (margin_checksum.js) */",
    1,
))
# 실마켓(API) 미매칭 카드 — 「확인된 블랙스팟」 줄(2칸)에 한 칸 더해 3칸으로.
#   수치 = analysisData.unmatched_buy(더망고엔 있으나 실마켓서 못 불러온 매입건). 1,024 분류
#   밖이라 검산 합에는 안 들어간다. 카드 부품(_summaryCardHTML)을 그대로 써 모양을 맞춘다.
SEAMS.append((
    "  h += '<div style=\"display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin:6px 0 0 0\">';\n"
    "  h += _summaryCardHTML('confirmed_blackspot', ex.confirmed_blackspot, '확인된 블랙스팟', 'pink');\n"
    "  h += _summaryCardHTML('memo_settled', ex.memo_settled, '입금/철회 완료', 'teal');\n"
    "  h += '</div>';",
    "  h += '<div style=\"display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:6px 0 0 0\">';  /* [모음전] 실마켓(API) 미매칭 카드 추가 → 3칸 (프로그램(API) 미매칭 카드는 '매입기록 없음=취소·클레임'이라 별 정보 아님 → 사장님 확정 삭제 2026-07-30) */\n"
    "  h += _summaryCardHTML('confirmed_blackspot', ex.confirmed_blackspot, '확인된 블랙스팟', 'pink');\n"
    "  h += _summaryCardHTML('memo_settled', ex.memo_settled, '입금/철회 완료', 'teal');\n"
    "  h += (window._moumUnmatchedBuyCardHTML ? window._moumUnmatchedBuyCardHTML() : '');  /* [모음전] 실마켓(API) 미매칭 = analysisData.unmatched_buy */\n"
    "  h += '</div>';",
    1,
))
# ── [모음전 신규 씨앗] ② '매입 흔적만'(데이터검증 배너 1-2) 카드 클릭 → 상세 펼침 ──
#   사장님 요청 2026-07-30: 정적 숫자였던 1-2 박스를 눌러도 아무 일 없었다. 다른 블랙스팟
#   카드처럼 눌러 아래(#detail-section)에 해당 행을 전체내역 양식으로 펼치게 onclick+cursor
#   만 더한다. 핸들러 _moumTraceOnlyClick → _showCardAllRows('trace_only')(margin_checksum.js
#   가 _getRowsByCardFilter 에 trace_only 를 심음, 배너 traceOnly 와 동일 기준 → 숫자·목록 일치).
#   ★1-1 박스와 스타일 문자열이 같아 '/* 1-2 */' 주석까지 앵커로 잡아 1-2 만 정확히 친다.
SEAMS.append((
    "/* 1-2 */\n    +     '<div style=\"background:#fef3c7;border:1px solid #fde68a;border-radius:10px;padding:12px 14px\">'",
    "/* 1-2 */\n    +     '<div onclick=\"_moumTraceOnlyClick()\" title=\"클릭 → 매입 흔적만 행 보기\" style=\"background:#fef3c7;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;cursor:pointer\">'  /* [모음전] ② 매입 흔적만 카드 클릭 상세 */",
    1,
))
# ── [모음전 신규 씨앗] 블랙스팟 「카드 선택」 사이드 패널 제거 (사장님 요청 2026-07-25) ──
#   카드 누르면 아래에 상세가 바로 뜨므로 우측 액션 패널은 의미 없어졌다. 좌우 그리드를
#   단일 칸(카드 전폭)으로 바꾸고, bsSidePanel div 자체를 안 그린다.
#   ★_selectBsCard 는 document.getElementById('bsSidePanel') 을 if(panel) 로 가드하므로
#     패널이 없어도 안전(널 → no-op).
SEAMS.append((
    "  h += '<div style=\"display:grid;grid-template-columns:1fr 270px;gap:14px;align-items:start\">';",
    "  h += '<div style=\"display:grid;grid-template-columns:1fr;gap:14px;align-items:start\">';  /* [모음전] 사이드 패널 제거 → 카드 전폭 */",
    1,
))
SEAMS.append((
    "  h += '<div id=\"bsSidePanel\" style=\"position:sticky;top:16px;background:#1f2937;color:#fff;border-radius:12px;padding:18px\">'",
    "  h += '<div id=\"bsSidePanel\" style=\"display:none\">'  /* [모음전] 「카드 선택」 사이드 패널 제거(숨김) — 카드 누르면 아래 상세가 바로 뜬다 */",
    1,
))
# '샵마인' 표시 문구 → '실마켓(API)'.
#   ★데이터 키는 손대지 않는다 — '샵마인_주문상태' 등 '샵마인_*' 필드명, 데이터출처 값
#     '샵마인만'·'더망고+샵마인'(byGroup/src 매칭 키)은 그대로 둔다(개명 시 데이터 조인 깨짐).
#   화면에 보이는 라벨·안내·설명 문구만 아래 목록으로 정확 치환(발생 횟수 assert 로 보호).
for _old, _new, _cnt in [
    ("샵마인 매칭",               "실마켓(API) 매칭",              1),
    ("더망고=매입 · 샵마인=매출",  "더망고=매입 · 실마켓(API)=매출", 1),
    ("(샵마인↔더망고)",           "(실마켓↔더망고)",              5),
    ("샵마인 미동기화",           "실마켓(API) 미동기화",          4),
    ("샵마인 미매칭",             "실마켓(API) 미매칭",            5),
    ("샵마인에만 있음",           "실마켓(API)에만 있음",          2),
    ("샵마인(마켓 정산)",         "실마켓 API(마켓 정산)",         1),
]:
    SEAMS.append((_old, _new, _cnt))


# ── [모음전 2026-07-31] 디자인 타입을 마진계산기에도 태운다 ────────────────
#  사장님 지적: 「검정A·B 타입인데 화이트 타입 디자인인 곳이 있다. 예: 마진계산기」
#
#  원인 — 이 화면은 base.html 을 안 쓰는 홀로 선 페이지(iframe 안)라
#  `ds` 클래스도, tokens.css 도 없다. 그래서 늘 원본의 흰 디자인 그대로였다.
#  라이브 실측(2026-07-31, 검정A): 흰 배경 잔재 13곳.
#
#  ★ 원본을 고치지 않는다 — 원본은 개발자 PC 의 별개 단독앱이다.
#    빌드 단계에서만 (1) 토큰 CSS 를 싣고 (2) body 에 타입 클래스를 붙인다.
#
#  ★ 「기존 타입」은 한 픽셀도 안 바뀐다 — 확인한 근거:
#    tokens.css / scope_fix.css / dark_badge_fix.css 세 파일의 선택자가
#    전부 `.ds` 아래이고, :root 에는 색이 하나도 없다(글꼴·크기·여백·둥글기뿐).
#    기존 타입이면 body 에 ds 가 안 붙으므로 이 규칙들은 통째로 잠든다.
# [2026-08-01] <html> 에도 타입 클래스를 붙인다.
#   화면이 `:root{ --x: var(--ink,#191F28) }` 처럼 자기 색 이름을 만들면 그 값은
#   **:root(=html) 자리에서** 굳는다. html 에 ds 가 없으면 밝은 예비값으로 굳어
#   이후 어느 후손이 써도 밝은 값이 나온다.
SEAMS.append((
    '<html lang="ko">',
    '<html lang="ko" class="{{ design_body_class|default(\'\') }}">',
    1,
))
SEAMS.append((
    "</head>\n<body>",
    "<!-- [모음전] 디자인 타입 — 홀로 선 페이지라 여기서 직접 싣는다. 선택자가 전부 .ds 아래뿐이라 「기존 타입」에는 안 걸린다. -->\n"
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='tokens.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='scope_fix.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='inline_color_fix.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='margin_embed_ds.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    "</head>\n"
    "<body class=\"{{ design_body_class|default('') }}\">",
    1,
))


# ══════════════════════════════════════════════════════════════════════════
# [2026-08-02 · 사장님 지적] 표의 숫자가 왼쪽에 붙어 자릿수가 안 맞았다
# ──────────────────────────────────────────────────────────────────────────
# 원본은 숫자 칸에 **정렬을 아예 안 준다**(`<td>` 그대로). 그래서 매출·매입·순마진이
# 전부 왼쪽에 붙어, 25,310,700 과 278,200 의 자릿수가 세로로 안 맞았다.
# 눈으로 크기를 못 비교하는 표가 된다(라이브 실측: 판매처별·금액대별·상품별 전부).
#
# 규율(디자인 규칙 원칙 4) — 숫자·금액·수량 = 오른쪽 + 자릿수 고정,
#                             글자·이름 = 왼쪽, 상태·배지 = 가운데.
#
# ★ 칸을 만드는 곳이 `numCell`·`pctCell` 두 함수 하나뿐이라, 여기만 고치면
#   일별·월별·브랜드별·금액대별·상품별·마켓별·소싱처별 표가 **한꺼번에** 맞는다.
# ★ 머리글도 같이 오른쪽으로 보낸다(머리글 정렬 = 값 정렬). 어느 머리글이 숫자인지는
#   이름으로 가린다 — 매출·매입·마진·건수·단가·정산·금액·효율만 오른쪽.
#   브랜드·상품명·마켓 같은 글자 머리글은 왼쪽 그대로다.
_숫자머리글 = "/매출|매입|마진|건수|수량|단가|판매가|정산|금액|효율|평균|합계/.test(label)"

for _o, _n, _c in [
    # ① 숫자 칸 — 음수·양수·빈칸(-) 전부
    ("'<td class=\"neg\">' + fmt(n) + '</td>'",
     "'<td class=\"num neg\">' + fmt(n) + '</td>'", 1),
    ("'<td>' + fmt(n) + '</td>'",
     "'<td class=\"num\">' + fmt(n) + '</td>'", 1),
    ("'<td class=\"neg\">' + fmtPct(n) + '</td>'",
     "'<td class=\"num neg\">' + fmtPct(n) + '</td>'", 1),
    ("'<td>' + fmtPct(n) + '</td>'",
     "'<td class=\"num\">' + fmtPct(n) + '</td>'", 1),
    ("'<td>-</td>'", "'<td class=\"num\">-</td>'", 2),
    # ② 건수 칸 — numCell 을 안 거쳐 혼자 왼쪽에 남아 있었다
    ("""'<td id="' + (isMarket ? 'agg_market_cnt_' + esc(mk) : '') + '" data-count="'""",
     """'<td class="num" id="' + (isMarket ? 'agg_market_cnt_' + esc(mk) : '') + '" data-count="'""", 1),
    # ③ 머리글 — 집계표
    ("""    return '<th class="sortable" onclick="sortAggBy(&quot;' + tabKey + '&quot;,&quot;' + col + '&quot;)">'
         + label + '<span class="sort-arrow">' + arrow + '</span></th>';""",
     """    return '<th class="sortable' + (%s ? ' num' : '') + '" onclick="sortAggBy(&quot;' + tabKey + '&quot;,&quot;' + col + '&quot;)">'
         + label + '<span class="sort-arrow">' + arrow + '</span></th>';""" % _숫자머리글, 1),
    # ④ 머리글 — 소싱처별 표
    ("""    return '<th class="sortable" onclick="_sortSrc(\\''+col+'\\')">'+label+'<span class="sort-arrow">'+arrow+'</span></th>';""",
     """    return '<th class="sortable'+(%s?' num':'')+'" onclick="_sortSrc(\\''+col+'\\')">'+label+'<span class="sort-arrow">'+arrow+'</span></th>';""" % _숫자머리글, 1),
    # ⑤ 「전체내역」 표 — 위 집계표와 달리 칸을 한 줄씩 직접 만든다. 같은 규율로 맞춘다.
    #    ★ 순마진·마진율은 이미 `class="neg"` 를 조건부로 붙이므로, class 를 **하나로 합쳐**
    #      넣는다. 따로 붙이면 한 태그에 class 가 두 번 생겨 뒤엣것이 무시된다.
    ("""  return '<th class="sortable" onclick="sortAllBy(&quot;' + col + '&quot;)">' + label + '<span class="sort-arrow">' + arrow + '</span></th>';""",
     """  return '<th class="sortable' + (%s ? ' num' : '') + '" onclick="sortAllBy(&quot;' + col + '&quot;)">' + label + '<span class="sort-arrow">' + arrow + '</span></th>';""" % _숫자머리글, 1),
    ("""    return '<td><input type="number" class="cell-input'""",
     """    return '<td class="num"><input type="number" class="cell-input'""", 1),
    ("""       + '<td>' + (r['수량_매출'] || 1) + '</td>'""",
     """       + '<td class="num">' + (r['수량_매출'] || 1) + '</td>'""", 1),
    ("""       + '<td style="font-weight:600;' + (isBs ? 'color:#9ca3af' : '') + '">'""",
     """       + '<td class="num" style="font-weight:600;' + (isBs ? 'color:#9ca3af' : '') + '">'""", 1),
    ("""       + '<td style="font-weight:700;' + (dispNetMargin < 0 ? '' : '') + '"' + (dispNetMargin < 0 ? ' class="neg"' : '') + '>'""",
     """       + '<td style="font-weight:700;' + (dispNetMargin < 0 ? '' : '') + '"' + (dispNetMargin < 0 ? ' class="num neg"' : ' class="num"') + '>'""", 1),
    ("""'<td style="font-weight:700;"' + (dispMarginRate < 0 ? ' class="neg"' : '') + '>'""",
     """'<td style="font-weight:700;"' + (dispMarginRate < 0 ? ' class="num neg"' : ' class="num"') + '>'""", 1),
]:
    SEAMS.append((_o, _n, _c))

# ── 정렬 규칙 + 글자 잘림 두 곳 (스타일 한 덩어리로 넣는다) ──────────────
# 「상품 수」 칸: 폭이 80px 이라 안내글 「등록 상품수 입력」이 「등록 ㅅ」에서 잘렸다.
# 「등록상품수」 칸: 폭 90px + 숫자 오르내림 화살표가 겹쳐 숫자가 잘렸다.
# ★ 붙일 자리는 **바로 앞 씨앗이 넣어 둔 마지막 스타일 줄 뒤**로 잡는다.
#   `</head>` 만으로 잡으면 그 씨앗의 `</head>\n<body>` 와 겹쳐 서로를 망가뜨린다
#   (씨앗끼리 겹치지 않는다는 이 파일의 전제를 깨뜨림).
SEAMS.append((
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='margin_embed_ds.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    "</head>\n",
    "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='margin_embed_ds.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    # ★ 한 줄로 넣는다 — 무수정 가드(test_only_the_seams_differ)가 **바뀐 줄마다**
    #   씨앗 표식을 찾는다. 여러 줄로 넣으면 `}` 같은 표식 없는 줄이 생겨 걸린다.
    "<style>/* [모음전 정렬 2026-08-02] 표 숫자는 오른쪽 + 자릿수 고정(세로로 가지런히) ·"
    " 안내글이 잘리던 「상품 수」 칸 폭 · 오르내림 화살표가 숫자를 덮던 「등록상품수」 칸 폭 */"
    " .table-wrap th.num,.table-wrap td.num,.detail-table th.num,.detail-table td.num"
    "{text-align:right;font-variant-numeric:tabular-nums}"
    " #productCount{width:150px}"
    " .table-wrap td input[type=\"number\"]{width:112px !important;padding-right:8px}</style>\n"
    "</head>\n",
    1,
))

# ── [2026-08-03] 글꼴 한 벌 + 표 정렬 — 저장소 전체 스윕이 이 화면에도 걸려 있다 ──
#  이 세 자산은 서빙본에만 들어가 있었다. 재빌드하면 통째로 사라진다
#  (2026-08-06 발견 — 동치 가드 2건이 그래서 깨져 있었다). 씨앗으로 못 박는다.
#  ★ 앞 씨앗이 넣어 둔 <style> 줄 뒤에 붙인다 — `</head>` 만으로 잡으면 겹친다.
_앞줄_2026_08_02 = (
    "<style>/* [모음전 정렬 2026-08-02] 표 숫자는 오른쪽 + 자릿수 고정(세로로 가지런히) ·"
    " 안내글이 잘리던 「상품 수」 칸 폭 · 오르내림 화살표가 숫자를 덮던 「등록상품수」 칸 폭 */"
    " .table-wrap th.num,.table-wrap td.num,.detail-table th.num,.detail-table td.num"
    "{text-align:right;font-variant-numeric:tabular-nums}"
    " #productCount{width:150px}"
    " .table-wrap td input[type=\"number\"]{width:112px !important;padding-right:8px}</style>\n"
)
SEAMS.append((
    _앞줄_2026_08_02 + "</head>\n",
    _앞줄_2026_08_02
    + "{# [2026-08-03] 표 정렬 — 머리글과 내용을 둘 다 가운데로 (사장님 확정 「1-C」).\n"
    + "   이 화면은 base.html 을 안 물려받는 독립 화면(창 안의 창)이라 여기에도 따로 싣는다.\n"
    + "   ★ 위 2026-08-02 규칙(.num 오른쪽)보다 **뒤에** 와야 이긴다. #}\n"
    + "{# [2026-08-03] 글꼴 한 벌 — 화면마다 굴림체·맑은 고딕으로 갈리던 것을 Pretendard 로.\n"
    + "   라이브 실측 131개 화면 중 40곳이 규칙 밖 글꼴이었다. #}\n"
    + "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='font_unify.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    + "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='table_align.css') }}?v={{ STATIC_VER|default('') }}\">\n"
    + "<script src=\"{{ url_for('static', filename='table_align.js') }}?v={{ STATIC_VER|default('') }}\" defer></script>\n"
    + "</head>\n",
    1,
))


# ── [2026-08-12] 매입 엑셀 = 실매입가 **단일 원천에도** 저장 → 그 결과를 말한다 ──
#  서버(api_margin.upload → _share_to_purchase_store)가 같은 엑셀을 주문 라인
#  (`order_line_purchases`)에도 저장한다(사장님 확정 규칙 6 「실마진이 필요한 곳에 공유」).
#  🔴 저장 결과를 화면이 말해야 한다 — 조용히 넘어가면 「올렸는데 주문 내역엔 왜 없지」가 된다.
SEAMS.append((
    "      setStatus(type, 'ok', info.rows.toLocaleString() + '건 로드됨' + extra);\n",
    "      /* [모음전 2026-08-12] _moumShared = 이 엑셀이 실매입가 단일 원천에도 저장된 결과"
    " (api_margin._share_to_purchase_store) — 조용히 넘어가면 「올렸는데 주문 내역엔 왜 없지」가 된다 */\n"
    "      var _moumShared = (data && data.shared) || null;\n"
    "      var _moumSharedTxt = !_moumShared ? ''\n"
    "        : (_moumShared.error ? (' · 주문 내역 공유 실패: ' + _moumShared.error)\n"
    "           : (' · 주문 내역에도 ' + Number(_moumShared.saved || 0).toLocaleString() + '줄 저장'\n"
    "              + ((_moumShared.unmatched || _moumShared.ambiguous || _moumShared.skipped_zero)\n"
    "                 ? '(못 붙음 ' + (_moumShared.unmatched || 0) + ' · 여럿 ' + (_moumShared.ambiguous || 0)\n"
    "                   + ' · 구매가격 빈칸 ' + (_moumShared.skipped_zero || 0) + ')' : '')));\n"
    "      setStatus(type, 'ok', info.rows.toLocaleString() + '건 로드됨' + extra + _moumSharedTxt);\n",
    1,
))


def _글자_바닥선_12(text: str) -> str:
    """<style> 블록 안 `font-size` 가 12px 미만이면 12px 로 올린다.

    🔴 12 이상은 절대 안 건드린다 — 11.5px 를 12.5px 로 만드는 실수를 막는다.
    🔴 <style> 밖(JS 문자열·인쇄용 pt)은 범위 밖이다.
    """
    import re as _re

    def _블록(m):
        속 = m.group(2)

        def _한자리(mm):
            공백, 값 = mm.group(1), float(mm.group(2))
            return mm.group(0) if 값 >= 12 else f'font-size:{공백}12px'

        return m.group(1) + _re.sub(r'font-size:(\s*)([0-9.]+)px', _한자리, 속) + m.group(3)

    return _re.sub(r'(?s)(<style[^>]*>)(.*?)(</style>)', _블록, text)


def _색을_토큰으로(text: str) -> str:
    """<style> 블록의 굳은 색을 `var(--토큰, 원래색)` 으로 바꾼다.

    이 저장소가 템플릿 155개에서 이미 6,167곳에 쓴 것과 **같은 도구**다
    (scripts/design_sweep.py). 여기서만 다시 만들지 않는다.

    ★ 예비값(괄호 안 원래색) 덕분에 「기존 타입」은 무손실이다 — 그 타입에는
      토큰이 아예 정의돼 있지 않아 브라우저가 예비값을 그대로 쓴다.
    ★ <style> 블록만 건드린다 — 자바스크립트가 문자열로 만드는 색은 손대지 않는다
      (건드리면 코드가 깨진다).
    """
    import sys as _sys
    _scripts = str(pathlib.Path(__file__).resolve().parents[1] / 'scripts')
    if _scripts not in _sys.path:
        _sys.path.insert(0, _scripts)
    from design_sweep import 스타일블록만_색치환, 스타일블록만_흰배경_서페이스로
    from split_faint_text import _바꾸기 as _흐린글자_가르기
    text = 스타일블록만_색치환(text)
    # 흰색은 COLOR_MAP 에 일부러 없다(같은 #fff 가 바탕일 수도 글자일 수도 있어서).
    # `background:` 선언 안일 때만 따로 바꾼다 — 이걸 빼먹어 `.card{background:#FFFFFF}`
    # 같은 흰 판이 검정 타입에 그대로 남아 있었다(라이브 실측 56곳).
    text = 스타일블록만_흰배경_서페이스로(text)
    # 흐린 색 이름 하나가 「글자」와 「테두리」 두 일을 해서, 글자로 쓴 자리만
    # 읽히는 이름으로 가른다(저장소 전체에 이미 적용된 규칙 — scripts/split_faint_text.py).
    text, _바뀐수 = _흐린글자_가르기(text)
    # 의미색(초록·빨강·주황·파랑)도 같은 이유로 「글자용」을 따로 낸다.
    # 한 이름이 ①밝은 바탕 위 글자 ②검정 위 글자 ③흰 글자용 배경 셋을 겸해서
    # 한 값으로는 셋 다 만족시킬 수 없다(scripts/split_semantic_text.py 설명 참고).
    from split_semantic_text import _바꾸기 as _의미색_가르기
    text, _바뀐수2 = _의미색_가르기(text)
    # 글자색 이름을 **배경**으로 쓴 자리도 가른다 — `--ink` 는 어두운 화면에서
    # 밝은 값으로 뒤집혀, 배경으로 쓰면 흰 글자에 흰 배경이 된다
    # (라이브 실측: 「분석 시작」 단추 대비 1.09).
    from split_bg_from_text_token import _바꾸기 as _배경_가르기
    text, _바뀐수3 = _배경_가르기(text)
    # 표 안쪽 여백·줄간격을 규칙값(4의 배수 7단)으로 맞춘다 — 사장님 확정 「2-B」.
    #  🔴 이 스윕은 원래 **서빙본에만** 걸려 있었다. 그래서 재빌드하면 여백 통일이
    #     통째로 되돌아갔고, 동치 가드 2건이 그 드리프트로 깨진 채 방치돼 있었다
    #     (2026-08-06 발견 — 「재빌드하면 고쳐진다」는 안내문이 오히려 일을 지웠다).
    #     빌드가 같이 부르면 재빌드해도 안 잃는다.
    from snap_table_spacing import 스타일블록만_여백스냅
    text = 스타일블록만_여백스냅(text, 'margin_embed.html')
    # 글자 바닥선 — 12px 미만을 12px 로 올린다 (사장님 확정 2026-08-13).
    #  🔴 여백 스냅과 **같은 이유로 여기서 부른다**. 서빙본만 고치면 재빌드가
    #     통째로 되돌리고 동치 가드가 깨진다(2026-08-06 에 그렇게 당했다).
    #  🔴 <style> 블록만 건드린다 — JS 가 문자열로 만드는 값은 손대지 않는다.
    #     라벨 인쇄용 pt 값처럼 px 이 아닌 것도 정규식이 애초에 안 잡는다.
    text = _글자_바닥선_12(text)
    return text


def transform(original_text: str) -> str:
    """원본 index.html 텍스트에 씨앗 치환을 적용해 margin_embed.html 텍스트를 반환.

    순수 함수 — 파일 I/O 없음. 각 씨앗의 발생 횟수가 기대와 다르면 ValueError 로 크게
    실패한다(상류 원본 변경으로 씨앗이 어긋나면 조용히 넘어가지 않도록).

    마지막에 <style> 블록의 색을 토큰으로 바꾼다(디자인 타입 대응). 이것도
    순수 함수라 동치 가드(test_margin_embed_verbatim.py)는 그대로 성립한다.
    """
    text = original_text
    for old, new, expect in SEAMS:
        n = text.count(old)
        if n != expect:
            raise ValueError(
                f"씨앗 불일치 — 기대 {expect}회, 실제 {n}회:\n---\n{old[:160]}\n---")
        text = text.replace(old, new)
    return _색을_토큰으로(text)


def main() -> None:
    if not ORIGINAL.exists():
        raise SystemExit(f"원본이 없습니다(이 PC 에서만 빌드 가능): {ORIGINAL}")
    # 텍스트 모드(universal newlines) → CRLF 를 LF 로 정규화해 씨앗 매칭.
    original = ORIGINAL.read_text(encoding="utf-8")
    out = transform(original)
    # LF 로 기록(서빙 템플릿은 LF). newline="" → 파이썬이 재변환하지 않음.
    with io.open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    src_lines = original.count("\n") + 1
    out_lines = out.count("\n") + 1
    print(f"원본 {src_lines}줄 → 출력 {out_lines}줄, 씨앗 {len(SEAMS)}종 적용 → {DST}")



# ── [모음전 2026-07-30] NEW 배지 제거 + 1-3 블랙스팟 의심 클릭 ──
#  사장님: "NEW 이런 개념은 없다" — 신규/기존 구분이 없어 오해만 준다.
#  1-3 박스 클릭 → 그 행을 전체내역 양식으로 펼침(로직은 margin_checksum.js).
for _o, _n in [
    ('    +       \'<span>🔎 매입 진행 여부 <span style="background:#10b981;color:#fff;font-size:9px;font-weight:800;padding:1px 4px;border-radius:2px">NEW</span></span>\'', "    +       '<span>🔎 매입 진행 여부</span>'  /* [모음전] NEW 배지 제거 */"),
    ('        + \'<span style="background:#dc2626;color:#fff;font-size:9px;padding:0 4px;border-radius:2px;font-weight:800;margin-right:3px">NEW</span>\'', "        + ''  /* [모음전] NEW 배지 제거 */"),
    ('    +         \'<span style="font-size:11px;font-weight:700;color:#991b1b;background:#fee2e2;padding:2px 7px;border-radius:10px">1-3 <span style="background:#dc2626;color:#fff;font-size:9px;font-weight:800;padding:0 3px;border-radius:2px;margin-left:1px">NEW</span></span>\'', '    +         \'<span style="font-size:11px;font-weight:700;color:#991b1b;background:#fee2e2;padding:2px 7px;border-radius:10px">1-3</span>\'  /* [모음전] NEW 배지 제거 */'),
    ('    +     \'<div style="background:#fef2f2;border:1.5px solid #fca5a5;border-radius:10px;padding:12px 14px">\'', '    +     \'<div onclick="if(window._moumSuspectClick)window._moumSuspectClick()" title="클릭 → 블랙스팟 의심 건 상세" style="background:#fef2f2;border:1.5px solid #fca5a5;border-radius:10px;padding:12px 14px;cursor:pointer">\'  /* [모음전] 블랙스팟 의심 클릭 */'),
]:
    SEAMS.append((_o, _n, 1))

# ── [모음전 2026-08-20] 일별/브랜드/상품 그룹 재계산 — 편집 후 그룹합계 필터 통일 ──
#  사장님 신고: 일별탭에서 단가/정산/매입 아무 셀이나 고치면 그날 매출·매입·순마진이
#  갑자기 이상해짐. 원인 — _refreshGroupTotals 의 local recompute() 가 쓰는 "살아있는 행"
#  판정이 초기 렌더(_isLiveRow, 2219행)·백엔드 aggregator.py(35-47행)와 다르게
#  "_주문미이행 && !_매입흔적" 조건이 빠져 있었다. 그래서 최초엔 안 잡히던 행이
#  편집을 계기로 그룹 재집계에 슬쩍 끼어들어 건수·매출·순마진이 튀었다.
#  세 곳(초기 렌더·편집 후 재집계·백엔드)의 "포함 대상" 정의를 하나로 맞춘다.
SEAMS.append((
    "  function recompute(items) {\n"
    "    const live = items.filter(function(x) {\n"
    "      if (x._excluded) return false;\n"
    "      if (MR.isMarginUncomputable(x)) return false;\n"
    "      return true;\n"
    "    });",
    "  function recompute(items) {\n"
    "    const live = items.filter(function(x) {\n"
    "      if (x._excluded) return false;\n"
    "      if (x['_주문미이행'] && !x['_매입흔적']) return false;  /* [모음전 2026-08-20] 일별/브랜드/상품 그룹 재계산 — 초기 렌더(_isLiveRow)·백엔드 aggregator.py 와 동일 기준으로 통일 (누락 시 편집 직후 그룹 건수·매출·순마진이 튐) */\n"
    "      if (MR.isMarginUncomputable(x)) return false;\n"
    "      return true;\n"
    "    });",
    1,
))

# ── [모음전 2026-08-20] 전체내역 컬럼 필터 — 제외/비대량등록 + nan/None 빈값 통일 ──
#  사장님 신고: 헤더 필터를 걸어도 안 걸러지는 칼럼이 있고, 빈 셀도 (빈값)으로 안 걸린다.
#  원인 — '제외'·'비대량등록' 칼럼은 체크박스가 r._excluded/r._manual_reg 를 보는데
#  필터는 r['제외']/r['비대량등록'](늘 undefined)을 읽어 옵션이 (빈값) 하나뿐이었고,
#  "nan"/"None" 문자열이 (빈값)과 갈라져 별도 옵션으로 남았다. 값-키 산출을 한 곳
#  (static/margin_col_filter_fix.js, window._moumColFilterKey)으로 모은다 — 함수 없으면
#  원본 동작 그대로 폴백(안전).
SEAMS.append((
    "      return activeCols.every(function(c){\n"
    "        var allowed = colFilters[c];\n"
    "        var val = r[c];\n"
    "        var key = (val == null || val === '') ? '(빈값)' : String(val);\n"
    "        return allowed.has(key);\n"
    "      });",
    "      return activeCols.every(function(c){\n"
    "        var allowed = colFilters[c];\n"
    "        var key = (window._moumColFilterKey ? window._moumColFilterKey(r, c) : ((r[c] == null || r[c] === '') ? '(빈값)' : String(r[c])));  /* [모음전 2026-08-20] 컬럼필터 — 제외/비대량등록 + nan/None 빈값 통일 (margin_col_filter_fix.js) */\n"
    "        return allowed.has(key);\n"
    "      });",
    1,
))
SEAMS.append((
    "      allRows = allRows.filter(function(r){\n"
    "        var val = r[c];\n"
    "        var key = (val == null || val === '') ? '(빈값)' : String(val);\n"
    "        return cf[c].has(key);\n"
    "      });",
    "      allRows = allRows.filter(function(r){\n"
    "        var key = (window._moumColFilterKey ? window._moumColFilterKey(r, c) : ((r[c] == null || r[c] === '') ? '(빈값)' : String(r[c])));  /* [모음전 2026-08-20] 컬럼필터 — 제외/비대량등록 + nan/None 빈값 통일 (margin_col_filter_fix.js) */\n"
    "        return cf[c].has(key);\n"
    "      });",
    1,
))
SEAMS.append((
    "  var valueMap = {};\n"
    "  allRows.forEach(function(r){\n"
    "    var val = r[col];\n"
    "    var key = (val == null || val === '') ? '(빈값)' : String(val);\n"
    "    valueMap[key] = (valueMap[key] || 0) + 1;\n"
    "  });",
    "  var valueMap = {};\n"
    "  allRows.forEach(function(r){\n"
    "    var key = (window._moumColFilterKey ? window._moumColFilterKey(r, col) : ((r[col] == null || r[col] === '') ? '(빈값)' : String(r[col])));  /* [모음전 2026-08-20] 컬럼필터 — 제외/비대량등록 + nan/None 빈값 통일 (margin_col_filter_fix.js) */\n"
    "    valueMap[key] = (valueMap[key] || 0) + 1;\n"
    "  });",
    1,
))

# ── [모음전 2026-08-20] 요약탭 고마진/손실 상세 — 매입가·정산가 인라인 편집 ──
#  사장님 요청: 요약탭 고마진/주문 내역에서 바로 매입가·정산가를 고칠 수 있게.
#  기존엔 정산·매입 칸이 「전→후」 텍스트뿐인 읽기전용이었다. 전체내역 탭과 같은
#  editCell()/recomputeRow() 를 그대로 재사용(같은 analysisData.matched 참조라 전체내역과
#  자동 동기화) — input 으로 바꾸고, onchange 시 이 패널(#etd-<kind>)만 다시 그린다.
SEAMS.append((
    "      var o정 = r['_orig_정산예상금액'], o매 = r['_orig_구매가격'];\n"
    "      var payChanged = (o정!=null && o정!==정산), buyChanged = (o매!=null && o매!==매입);\n"
    "      var pay = payChanged ? _ba(fmt(o정), fmt(정산), {changed:true, color:'color:#1AB053', delta:{dir:'up', txt:(정산-o정>=0?'+':'−')+fmt(Math.abs(정산-o정))}}) : _ba(fmt(정산), fmt(정산));\n"
    "      var buyc = buyChanged ? _ba(fmt(o매), fmt(매입), {changed:true, color:'color:#3182F6', delta:{dir:'dn', txt:(매입-o매>=0?'+':'−')+fmt(Math.abs(매입-o매))}}) : _ba(fmt(매입), fmt(매입));\n",
    "      var o정 = r['_orig_정산예상금액'], o매 = r['_orig_구매가격'];\n"
    "      var payChanged = (o정!=null && o정!==정산), buyChanged = (o매!=null && o매!==매입);\n"
    "      /* [모음전 2026-08-20] 요약탭 고마진/손실 상세도 전체내역과 같은 인라인 편집(editCell) — 사장님 요청. 편집 시 이 패널만 즉시 다시 그림(_moumAbnEdit). */\n"
    "      var pay = '<input type=\"number\" class=\"cell-input'+(payChanged?' edited':'')+'\" value=\"'+정산+'\" onchange=\"_moumAbnEdit('+r._idx+', &quot;정산예상금액&quot;, this.value, &quot;'+kind+'&quot;)\" title=\"수정 시 마진 자동 재계산\" style=\"width:88px\">';\n"
    "      var buyc = '<input type=\"number\" class=\"cell-input'+(buyChanged?' edited':'')+'\" value=\"'+매입+'\" onchange=\"_moumAbnEdit('+r._idx+', &quot;구매가격&quot;, this.value, &quot;'+kind+'&quot;)\" title=\"수정 시 마진 자동 재계산\" style=\"width:88px\">';\n",
    1,
))
SEAMS.append((
    "  h += '</tbody></table>';\n"
    "  return h;\n"
    "}\n"
    "window.toggleAbnRows = function(kind){",
    "  h += '</tbody></table>';\n"
    "  return h;\n"
    "}\n"
    "/* [모음전 2026-08-20] 요약탭 고마진/손실 상세 인라인 편집 — editCell 로 실제 반영 후,\n"
    "   analysisData.matched 는 모든 탭이 공유하는 같은 행 참조라 renderCurrentTab() 한 번이면\n"
    "   이 탭(요약) 상단 카드·E표까지 전부 최신값으로 다시 그려지고, 전체내역·일별 등 다른 탭도\n"
    "   다음에 열 때(재렌더/탭 전환) 같은 데이터를 읽어 자동으로 반영된다. */\n"
    "window._moumAbnEdit = function(idx, field, val, kind){\n"
    "  editCell(idx, field, val);\n"
    "  if (typeof renderCurrentTab === 'function' && typeof currentTab !== 'undefined' && currentTab === 'summary') {\n"
    "    renderCurrentTab();\n"
    "    if (typeof toggleAbnRows === 'function') toggleAbnRows(kind);\n"
    "    return;\n"
    "  }\n"
    "  var det = document.getElementById('etd-' + kind);\n"
    "  if (det) det.innerHTML = _renderAbnDetail(kind);\n"
    "};\n"
    "window.toggleAbnRows = function(kind){",
    1,
))

if __name__ == "__main__":
    main()

