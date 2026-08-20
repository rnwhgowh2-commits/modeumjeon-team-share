# -*- coding: utf-8 -*-
"""① 데이터수집 탭 정적 미리보기 — 워크트리가 프로젝트 루트 밖이라 preview_start 를
못 써서, 테스트 클라이언트로 실제 페이지 + 실제 API 응답을 뽑아 자급 HTML 로 만든다.

fetch 를 실제 응답으로 스텁하므로 **JS 렌더 로직은 그대로** 검증된다.
서버 없이 브라우저로 열어 확인하는 용도.

사용: python scripts/_collect_preview.py [out.html] [--fixture]
      --fixture 를 주면 DB 가 비어 있어도 표본 데이터로 화면을 채운다.
"""
import io
import json
import os
import sys

os.environ.setdefault("DISABLE_AUTH", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE = {
    "granularity": "composition",
    "mode": "continuous",
    "base_interval_seconds": 0,
    "avg_lap_minutes": 30,
    "window": {"window_days": 30, "laps_found": 10},
    "note": "등급은 구성 평균입니다. 상품별 산포는 이 데이터로 만들 수 없습니다.",
    "counts": {"total": 3, "graded": 3, "ungraded": 0},
    "excluded_zero": [],
    "rows": [
        {"source_key": "musinsa", "source_label": "무신사", "brand": "나이키",
         "observed": 1000, "changed": 200, "price_changed": 120, "stock_changed": 150,
         "current_weight": 2, "crawls_per_day": 96.0,
         "grade": 0, "grade_name": "하루 2회 이상", "intensity_pct": 1920.0,
         "average_period_days": 0.0125, "proposed_per_day": 2.0, "proposed_text": "2회/일",
         "capped": True, "floored": False,
         "axes": {"price": {"intensity_pct": 1152.0}, "stock": {"intensity_pct": 1440.0}},
         "note": "관측 1000회 중 200회 변동 = 변동률 20.0% · 하루 96회 크롤 → 강도 1920%"},
        {"source_key": "ssg", "source_label": "SSG", "brand": "뉴발란스",
         "observed": 800, "changed": 24, "price_changed": 10, "stock_changed": 18,
         "current_weight": 1, "crawls_per_day": 48.0,
         "grade": 0, "grade_name": "하루 2회 이상", "intensity_pct": 144.0,
         "average_period_days": 0.69, "proposed_per_day": 2.0, "proposed_text": "2회/일",
         "capped": False, "floored": False,
         "axes": {"price": {"intensity_pct": 60.0}, "stock": {"intensity_pct": 108.0}},
         "note": "관측 800회 중 24회 변동 = 변동률 3.0% · 하루 48회 크롤 → 강도 144%"},
        {"source_key": "lotteon", "source_label": "롯데온", "brand": "아식스",
         "observed": 20, "changed": 1,
         "current_weight": 1, "crawls_per_day": 48.0,
         "grade": None, "grade_name": None, "intensity_pct": None,
         "note": "표본 부족 — 관측 20회(최소 30회). 몇 바퀴 더 돌아야 등급을 말할 수 있습니다."},
    ],
}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "collect_preview.html"
    use_fixture = "--fixture" in sys.argv

    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    c = flask_app.test_client()

    page = c.get("/bulk/?tab=collect").get_data(as_text=True)
    api = c.get("/bulk/api/collect/grades")
    data = api.get_json()
    live_rows = len((data or {}).get("rows") or [])
    if use_fixture or not live_rows:
        data = FIXTURE
        src = "표본 데이터(DB 비어 있음)" if not live_rows else "표본 데이터(--fixture)"
    else:
        src = f"실제 DB / 구성 {live_rows}개"

    stub = (
        "<script>window.__COLLECT__=" + json.dumps(data, ensure_ascii=False) + ";"
        "window.fetch=function(u){return Promise.resolve({ok:true,"
        "json:function(){return Promise.resolve(window.__COLLECT__);}});};</script>"
    )
    banner = (
        '<div style="background:#1B64DA;color:#fff;padding:8px 16px;font:600 12px/1.6 '
        '-apple-system,sans-serif">정적 미리보기 · ' + src + ' · 서버 없이 렌더만 확인</div>'
    )
    # fetch 스텁을 화면 스크립트보다 **먼저** 넣어야 한다.
    html = page.replace("<body", banner and "<body", 1)
    if "</head>" in html:
        html = html.replace("</head>", stub + "</head>", 1)
    else:
        html = stub + html
    html = html.replace("<body>", "<body>" + banner, 1)
    if banner not in html:
        html = banner + html

    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)
    # 콘솔이 cp949 라 한글·em-dash 가 깨진다 → ASCII 로만 찍는다.
    sys.stdout.write("wrote: %s  (rows=%d)\n" % (os.path.abspath(out), len(data.get("rows") or [])))


if __name__ == "__main__":
    main()
