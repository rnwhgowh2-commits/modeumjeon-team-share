# -*- coding: utf-8 -*-
"""대량등록 탭 정적 미리보기 — 워크트리가 프로젝트 루트 밖이라 preview_start 를 못 쓴다.

테스트 클라이언트로 **실제 페이지 + 실제 API 응답**을 뽑아 자급 HTML 로 만든다.
fetch 를 실제 응답으로 스텁하므로 JS 렌더 로직은 그대로 검증된다.

사용:
  python scripts/_bulk_preview.py collect out.html
  python scripts/_bulk_preview.py process out.html [--seed]
      --seed 를 주면 정책 몇 개를 만들어 화면을 채운다(빈 DB 대비).
"""
import io
import json
import os
import sys

os.environ.setdefault("DISABLE_AUTH", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABS = {
    "collect": ("/bulk/?tab=collect", "/bulk/api/collect/grades"),
    "process": ("/bulk/?tab=process", "/bulk/api/process/policies"),
}


def _seed(client):
    """빈 DB 에서도 화면을 볼 수 있게 정책·연결을 만든다."""
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import (
        attach_market, attach_source, create_policy, set_rule,
    )
    s = SessionLocal()
    try:
        try:
            p = create_policy(s, name="나이키 스니커즈 기본")
        except ValueError:
            return                      # 이미 있음 — 멱등
        attach_source(s, policy_id=p.id, source_key="musinsa", brand="나이키",
                      url="https://www.musinsa.com/search/goods?keyword=나이키")
        attach_source(s, policy_id=p.id, source_key="ssg", brand="나이키")
        attach_market(s, policy_id=p.id, market="smartstore", account_key="acc1")
        attach_market(s, policy_id=p.id, market="coupang", account_key="acc1")
        for k in ("name", "category", "price", "options", "images"):
            set_rule(s, policy_id=p.id, item_key=k, config={"demo": True})
        create_policy(s, name="마켓 안 붙인 정책")
        s.commit()
    finally:
        s.close()


def main():
    if len(sys.argv) < 3:
        sys.stdout.write("usage: _bulk_preview.py <collect|process> <out.html> [--seed]\n")
        return 2
    tab, out = sys.argv[1], sys.argv[2]
    if tab not in TABS:
        sys.stdout.write("unknown tab: %s\n" % tab)
        return 2
    page_url, api_url = TABS[tab]

    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    c = flask_app.test_client()

    if "--seed" in sys.argv:
        with flask_app.app_context():
            _seed(c)

    page = c.get(page_url).get_data(as_text=True)
    data = c.get(api_url).get_json()

    stub = (
        "<script>window.__API__=" + json.dumps(data, ensure_ascii=False) + ";"
        "window.fetch=function(){return Promise.resolve({ok:true,"
        "json:function(){return Promise.resolve(window.__API__);}});};</script>"
    )
    banner = ('<div style="background:#1B64DA;color:#fff;padding:8px 16px;'
              'font:600 12px/1.6 -apple-system,sans-serif">정적 미리보기 · '
              + tab + ' · 서버 없이 렌더만 확인</div>')
    html = page.replace("</head>", stub + "</head>", 1) if "</head>" in page else stub + page
    html = html.replace("<body>", "<body>" + banner, 1)

    with io.open(out, "w", encoding="utf-8") as f:
        f.write(html)
    rows = len((data or {}).get("rows") or [])
    sys.stdout.write("wrote: %s  (tab=%s rows=%d)\n" % (os.path.abspath(out), tab, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
