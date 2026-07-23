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
        "  var _mFailed = (window.analysisData && window.analysisData.markets_failed) || [];  /* [모음전] 연동안됨/조회실패 마켓 표면화 (markets_failed) */\n"
        "  if (_mFailed.length) { msg.innerHTML += '<div style=\"margin-top:8px;padding:8px 12px;background:#FFF3F3;border:1px solid #FFD5D5;border-radius:8px;color:#dc2626;font-size:13px;line-height:1.65;\">⚠️ 아래 마켓은 API 연동이 안 됐거나 조회에 실패해 <b>매출에서 제외</b>하고 분석했어요:<br>' + _mFailed.map(function(w){ return '· ' + String(w); }).join('<br>') + '</div>'; }  /* [모음전] _mFailed 배너 */\n"
        "  var _mNotice = (window.analysisData && window.analysisData.notices) || [];  /* [모음전] 제외가 아닌 안내(_mNotice) — 빨간 배너와 분리 */\n"
        "  if (_mNotice.length) { msg.innerHTML += '<div style=\"margin-top:8px;padding:8px 12px;background:#F2F7FF;border:1px solid #CFE0F7;border-radius:8px;color:#1F4E86;font-size:13px;line-height:1.65;\">💡 ' + _mNotice.map(function(w){ return String(w).replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>'); }).join('<br>') + '</div>'; }  /* [모음전] _mNotice 배너 */",
        1,
    ),
    # 15) [모음전 신규 씨앗] 「최신까지 불러오기」 버튼 — 분석은 저장분만 읽는다.
    #     원본은 단독앱이라 매출을 엑셀로 받았다. 모음전은 마켓 API 라, 분석 요청 하나에
    #     6마켓 조회를 다 넣으면 가장 느린 옥션(58.1초)에 발이 묶여 서버 상한을 넘고
    #     응답이 JSON 이 아니게 된다(2026-07-23 실측 61.7초 → 502 → 화면 "서버 오류").
    #     그래서 분석은 저장분만 읽고, 최신 수집은 이 버튼이 **마켓별로 나눠** 돌린다.
    #     스타일은 기존 btn/btn-outline 재사용 — 새 디자인 요소를 만들지 않는다.
    (
        "    <button class=\"btn btn-outline\" onclick=\"openRangeModal()\">금액대 설정</button>",
        "    <button class=\"btn btn-outline\" onclick=\"openRangeModal()\">금액대 설정</button>\n"
        "    <button class=\"btn btn-outline\" id=\"refreshOrdersBtn\" onclick=\"refreshOrdersToNow()\""
        " title=\"판매처에서 최근 주문을 받아 저장해 둡니다. 분석은 저장된 주문으로 돌아가요.\">최신까지 불러오기</button>"
        "  <!-- [모음전] 마켓별로 나눠 적재 갱신 (refreshOrdersToNow) -->",
        1,
    ),
    # 16) [모음전 신규 씨앗] 「분석 시작」이 최신 수집을 **먼저** 돌린다 (사장님 지시: 라이브로).
    #     분석 요청 하나에 6마켓 라이브 조회를 넣으면 61.7초로 서버 상한을 넘어 502 가 된다.
    #     그래서 순서를 바꾼다: (마켓별로 나눠 수집) → (저장분 분석). 결과는 라이브와 같고
    #     요청은 각각 짧다. 수집이 실패해도 분석은 진행한다 — 저장분만으로도 결과는 나오고,
    #     못 불러온 마켓은 refreshOrdersToNow 가 이름을 남겨 화면에 보인다(조용한 실패 금지).
    (
        "async function startAnalysis() {",
        "async function startAnalysis() {\n"
        "  try { var _b0 = document.getElementById('analyzeBtn'); if (_b0) _b0.disabled = true;  /* [모음전] refreshOrdersToNow 전에 버튼부터 잠금 — 1분 가까이 걸려 '눌러도 반응 없음'으로 보인다 */\n"
        "        if (window.refreshOrdersToNow) await window.refreshOrdersToNow({ keepMessage: true }); }  /* [모음전] 분석 전 최신 수집 (refreshOrdersToNow) */\n"
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


def transform(original_text: str) -> str:
    """원본 index.html 텍스트에 씨앗 치환(8종/11회)을 적용해 margin_embed.html 텍스트를 반환.

    순수 함수 — 파일 I/O 없음. 각 씨앗의 발생 횟수가 기대와 다르면 ValueError 로 크게
    실패한다(상류 원본 변경으로 씨앗이 어긋나면 조용히 넘어가지 않도록).
    """
    text = original_text
    for old, new, expect in SEAMS:
        n = text.count(old)
        if n != expect:
            raise ValueError(
                f"씨앗 불일치 — 기대 {expect}회, 실제 {n}회:\n---\n{old[:160]}\n---")
        text = text.replace(old, new)
    return text


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


if __name__ == "__main__":
    main()
