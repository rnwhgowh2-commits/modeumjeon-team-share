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
    "/api/blackspot/fetch_order_no", "_mMissRow",  # 소싱처 주문번호 추출 — 무상태 서버에 memo 동봉
    "const summary", "analyzeAndRender", "_mSupp",  # 추출 성공 UX — 거짓 카운트 제거 + 반영칸 프리필
    "margin_ext_check.js", "_moumExtCheckFetch", "/api/check-sourcing",  # [E2] 소싱처 주문상태 = 서버 Playwright 제거 → 로컬 크롬확장
    "id=\"sellBox\"", "id=\"sellFileInput\"", "upload-icon", "upload-label", "upload-sub", "id=\"sellStatus\"",  # 매출칸 → 마켓API 자동조회 안내 (샵마인 업로드 제거)
    "errText",                              # 업로드 에러 핸들러 단일읽기(이중읽기 버그수정)
    "_mFailed", "markets_failed",           # 연동안됨/조회실패 마켓 표면화 배너
    "_mNotice", "notices",                  # 제외가 아닌 안내(저장분 분석 등) — 별도 배너
    # 「최신까지 불러오기」 — 분석은 저장분만 읽고, 최신 수집은 마켓별로 나눠 돌린다.
    # (한 요청에 6마켓을 묶으면 옥션 58초에 묶여 서버 상한 초과 → 502 → "서버 오류")
    # 로직은 static/margin_refresh_orders.js 에 둔다 — 이 파일 본문엔 script ref 와
    # 버튼 한 줄만 들어간다(본문 무수정 원칙 유지).
    "margin_refresh_orders.js", "refreshOrdersBtn", "refreshOrdersToNow",
    # 「까대기 송장번호 전송 완료」 카드 — 더망고 '현지배송완료'(송장 뽑아 마켓 전송한 건).
    # 카드 안 양분·막대 조립은 static/margin_kkadaegi_sent.js 에 두고, 이 파일엔
    # 카드 정의(색·설명·이름표·건수)와 배치만 씨앗으로 들어간다.
    "margin_kkadaegi_sent.js", "kkadaegi_sent", "_kkadaegiSentCardHTML",
    "tracking_failed", "kkadaegi",          # 송장 재전송 실패 1행 이동 · 까대기 2행 이동
    "🆕 송장 재전송 실패",                   # 옛 주석 줄(자리 이동으로 문구 갱신)
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

    렌더 함수·CSS·`_getRowsByCardFilter_internal` 라인이 하나라도 바뀌면 화이트리스트에
    없어 여기서 실패한다.
    """
    if not ORIGINAL.exists():
        pytest.skip(f"원본 마진계산기 없음: {ORIGINAL}")
    original = _norm(ORIGINAL).splitlines()
    served = _norm(SERVED).splitlines()
    diff = difflib.unified_diff(original, served, lineterm="", n=0)
    changed = [d for d in diff
               if d and d[0] in "+-" and not d.startswith(("+++", "---"))]
    assert changed, "변경 라인이 하나도 없음 — 재배선이 누락됐을 수 있음(씨앗 미적용)."
    for line in changed:
        body = line[1:]  # +/- 프리픽스 제거
        assert any(tok in body for tok in _SEAM_TOKENS), (
            f"씨앗이 아닌 라인이 변경됨(본문 드리프트 의심):\n{line}")


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
