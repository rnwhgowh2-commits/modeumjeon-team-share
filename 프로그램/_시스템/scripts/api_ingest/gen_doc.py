# -*- coding: utf-8 -*-
"""api_ingest_paths.json(정본) → docs/markets/_API문서수집법.md 자동생성.

단일 진실 원천 원칙: 접수 경로 지식은 **JSON 한 곳**에만 있고,
  · 화면(「API 문서 수집법」 탭) = /marketplace-guide/ingest-paths.json 으로 렌더
  · 사람용 문서(.md)          = 본 스크립트로 생성
→ .md 를 손으로 고치지 말 것(다음 생성 때 덮어씀). JSON 을 고쳐라.

사용: python 프로그램/_시스템/scripts/api_ingest/gen_doc.py [--check]
  --check : 생성 결과가 현재 .md 와 다르면 exit 1 (CI/사전점검용, 파일 안 씀)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))  # 저장소 루트
SRC = os.path.join(ROOT, "프로그램", "_시스템", "webapp", "data", "api_ingest_paths.json")
DST = os.path.join(ROOT, "docs", "markets", "_API문서수집법.md")


def _strip_html(s: str) -> str:
    """화면용 HTML 태그를 문서용 마크다운으로 최소 변환."""
    out = (s or "")
    for a, b in (("<b>", "**"), ("</b>", "**"), ("<code>", "`"), ("</code>", "`"),
                 ('<span class="win">', "**"), ("</span>", ""), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&")):
        out = out.replace(a, b)
    # 남은 <span ...> 류 제거
    while "<span" in out:
        i = out.find("<span")
        j = out.find(">", i)
        if j < 0:
            break
        out = out[:i] + out[j + 1:]
    return out.strip()


def render(d: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# 판매처 API 문서 수집법 — 접수 경로 × 신뢰도 매트릭스 · 전체 탭 계층 · 플레이북")
    A("")
    A("> ⚠️ **이 문서는 자동 생성됩니다. 직접 고치지 마세요.**")
    A("> 정본 = `프로그램/_시스템/webapp/data/api_ingest_paths.json` · 생성 = `프로그램/_시스템/scripts/api_ingest/gen_doc.py`")
    A("> 화면(인앱 `판매처관리 › 데이터코드지도 › API문서수집법`)도 같은 정본을 읽습니다 → 중복·모순 0.")
    A(f"> **최종 실측일**: {d.get('measured_at','')}")
    A("> **원칙**: 날조 금지 · 실측만 '가능' · robots·약관 준수 · 인증 URL 노출 금지 · 첨부에만 있으면 위치만 기록")
    A("")
    A("---")
    A("")
    A("## 1. 왜 필요한가")
    A("")
    for s in d.get("intro", []):
        A(f"- {s}")
    A("")
    A(f"**{_strip_html(d.get('headline',''))}**")
    A("")
    A("### 💡 실측이 뒤집은 통념")
    A("")
    for i, m in enumerate(d.get("myths", []), 1):
        A(f"{i}. {m}")
    A("")
    A("---")
    A("")
    A("## 2. 신뢰도 등급 (산출물 품질)")
    A("")
    A("| 등급 | 정의 | 기준 |")
    A("|---|---|---|")
    for g in d.get("grades", []):
        A(f"| **{g[0]}** | {g[1]} | {g[2]} |")
    A("")
    A("---")
    A("")
    A("## 3. 접수 경로 도구상자")
    A("")
    A("| 코드 | 방법 | 강점·기법 | 한계 |")
    A("|---|---|---|---|")
    for r in d.get("routes", []):
        A(f"| **{r[0]}** | {r[1]} | {_strip_html(r[2])} | {_strip_html(r[3])} |")
    A("")
    A("### 3-1. 경로 I 표준 절차 (로그인 게이트 마켓의 정답 · 11번가 실증)")
    A("")
    A("| 항목 | 규칙 |")
    A("|---|---|")
    for s in d.get("snippet_rules", []):
        A(f"| **{s[0]}** | {_strip_html(s[1])} |")
    A("")
    A("---")
    A("")
    A("## 4. 마켓 × 경로 매트릭스")
    A("")
    A("| 마켓 | A·자동읽기 | C·실브라우저 | D·코드 | 기타(E/F/H/I) | 채택 경로 | 접수 | 등급 |")
    A("|---|---|---|---|---|---|---|---|")
    for m in d.get("matrix", []):
        cells = " | ".join(f"{'✅' if c[0]=='ok' else ('⚠️' if c[0]=='part' else '❌')} {c[1]}" for c in m[1:5])
        A(f"| **{m[0]}** | {cells} | **{m[5]}** | {m[6]} | {m[7]} |")
    A("")
    A("범례: ✅ 뚫림 · ⚠️ 부분/미시도 · ❌ 막힘. robots·안전차단은 우회하지 않는다.")
    A("")
    A("---")
    A("")
    A("## 5. 마켓별 전체 탭 계층 (실측)")
    A("")
    for h in d.get("hier", []):
        A(f"### {h.get('mk','')} — {h.get('route','')}")
        A("")
        A(f"- **상위탭**: {' · '.join(h.get('top', []))}")
        cats = " · ".join(f"{c[0]}{f'({c[1]})' if c[1] else ''}" for c in h.get("cats", []))
        A(f"- **카테고리**: {cats}")
        A(f"- **비고**: {h.get('catNote','')}")
        A(f"- **상세 탭**: {' · '.join(h.get('detail', []))}")
        A("")
    A("---")
    A("")
    A("## 6. 플레이북 — 새 마켓 접수 시도 순서 (★경험 기반 최적 순서)")
    A("")
    A("> 원리: 싸고 빠르고 사람 개입 없는 것부터. 각 단계는 판별 1가지로 다음 갈래가 결정된다. 뚫리면 그 자리에서 끝.")
    A("")
    for p in d.get("play", []):
        A(f"{p[0]}. {_strip_html(p[1])} — {_strip_html(p[2])}")
    A("")
    A(_strip_html(d.get("decide", "")))
    A("")
    A("---")
    A("")
    A("## 7. 미확보 · 후속 과제")
    A("")
    for t in d.get("todo", []):
        A(f"- {t}")
    A("")
    A("---")
    A("")
    A("## 8. 참고 파일")
    A("")
    for r in d.get("refs", []):
        A(f"- {r}")
    A("")
    return "\n".join(L)


def main() -> int:
    with open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    md = render(d)
    check = "--check" in sys.argv
    cur = ""
    if os.path.exists(DST):
        with open(DST, encoding="utf-8") as f:
            cur = f.read()
    if check:
        if cur.strip() != md.strip():
            print("✗ _API문서수집법.md 가 정본(JSON)과 다릅니다. gen_doc.py 를 실행해 재생성하세요.")
            return 1
        print("✓ 문서 = 정본 일치")
        return 0
    with open(DST, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"✓ 생성: {DST} ({len(md)} chars) ← 정본 {os.path.basename(SRC)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
