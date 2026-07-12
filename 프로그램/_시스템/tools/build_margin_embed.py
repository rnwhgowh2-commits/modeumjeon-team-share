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
        "  <script src=\"{{ url_for('static', filename='margin_ext_check.js') }}\"></script>",
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
