# -*- coding: utf-8 -*-
"""붙이는 **화면**이 실제로 그려지는지 — 라우트만 있고 화면이 없으면 사장님은 못 쓴다.

목록 화면의 `row()` 는 템플릿 안 IIFE 라 통째로 require 할 수 없으므로,
선례(`test_preflight_render_js.py`)대로 **함수 원문을 떼어** node 로 태운다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIST_TPL = ROOT / 'webapp' / 'templates' / 'bulk' / 'partials' / '_process.html'


def _extract(src: str, fn_name: str) -> str:
    """`function 이름(...) { … }` 원문을 중괄호 짝으로 떼어낸다."""
    m = re.search(r'^\s*function\s+' + re.escape(fn_name) + r'\s*\(', src, re.M)
    assert m, f'{fn_name} 이(가) _process.html 에 없습니다 — 렌더가 사라졌습니다'
    i = src.index('{', m.end() - 1)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    raise AssertionError(f'{fn_name} 의 중괄호 짝이 안 맞습니다')


def _render_row(row: dict, policies: list) -> str:
    if not shutil.which('node'):
        pytest.skip('node 가 없어 렌더를 태울 수 없습니다')
    src = LIST_TPL.read_text(encoding='utf-8')
    script = (
        "const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g,"
        " (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n"
        "const msgs = {};\n"
        "const keyOf = (r) => (r.source_key || '') + ' > ' + (r.brand || '');\n"
        "const data = " + json.dumps({"policies": policies}, ensure_ascii=False) + ";\n"
        + _extract(src, 'policyPicker') + "\n"
        + _extract(src, 'row') + "\n"
        "console.log(JSON.stringify(row(" + json.dumps(row, ensure_ascii=False) + ")));\n")
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True,
                       encoding='utf-8')
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


_POLICIES = [{"id": 7, "name": "나이키 기본"}, {"id": 9, "name": "아디다스 기본"}]


def test_정책_없는_줄에도_고를_수_있는_드롭다운이_있다():
    """「붙여주세요」라고만 하고 붙일 수단이 없던 게 이 기능의 출발점이다."""
    html = _render_row({"source_key": "musinsa", "brand": "나이키", "url": None,
                        "policy_id": None, "policy_name": None,
                        "markets": [], "rule_count": 0}, _POLICIES)
    assert '<select' in html
    assert '— 정책 없음 —' in html
    assert '나이키 기본' in html and '아디다스 기본' in html
    assert 'class="warn"' in html            # 빨간 줄은 그대로 빨갛다


def test_붙어_있는_줄은_그_정책이_골라져_있다():
    html = _render_row({"source_key": "musinsa", "brand": "나이키", "url": None,
                        "policy_id": 9, "policy_name": "아디다스 기본",
                        "markets": [{"market": "coupang", "account_key": ""}],
                        "rule_count": 3}, _POLICIES)
    assert 'value="9" selected' in html
    assert '/bulk/process/policy/9' in html   # 상세로 가는 길
    assert 'class="warn"' not in html         # 붙어 있으면 더 이상 빨간 줄이 아니다


def test_저장_결과를_그_줄_안에_적을_자리가_있다():
    """멀리 뜨면 안 보인다 — 결과는 그 줄 옆에 붙는다."""
    html = _render_row({"source_key": "ssg", "brand": "아디다스", "url": None,
                        "policy_id": None, "policy_name": None,
                        "markets": [], "rule_count": 0}, _POLICIES)
    assert 'data-msg="ssg &gt; 아디다스"' in html


# ── 정책 상세 화면 ──────────────────────────────────────────────

_MARK = "붙이기화면"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for p in s.query(ProcessPolicy).all():
            if p.name and p.name.startswith(_MARK):
                s.delete(p)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _policy(client):
    nm = f"{_MARK}-{uuid.uuid4().hex[:8]}"
    return client.post('/bulk/api/process/policies', json={"name": nm}).get_json()["id"]


def test_상세에_마켓_추가_칸이_있다(client):
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    assert 'pd-addmkt' in html and '마켓 추가' in html
    for label in ('스마트스토어', '쿠팡', '롯데온', '11번가', '옥션', 'G마켓'):
        assert label in html, f'{label} 을(를) 고를 수 없습니다'


def test_계정_칸은_크롬_자동완성을_막는다(client):
    """[reference_chrome_autofill_corrupts_form_fields] 고유 name + off + readonly 3종."""
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    i = html.index('id="pd-addacc"')
    box = html[i - 200:i + 400]
    assert 'name="pd_policy_market_account_nofill"' in box
    assert 'autocomplete="off"' in box
    assert 'readonly' in box and "removeAttribute('readonly')" in box


def test_붙은_소싱처와_마켓이_떼기와_함께_보인다(client):
    pid = _policy(client)
    client.post(f'/bulk/api/process/policies/{pid}/sources',
                json={"source_key": "musinsa", "brand": f"{_MARK}브랜드"})
    client.post(f'/bulk/api/process/policies/{pid}/markets',
                json={"market": "coupang", "account_key": "본계정"})
    html = client.get(f'/bulk/process/policy/{pid}').get_data(as_text=True)
    assert f'{_MARK}브랜드' in html
    assert '쿠팡 · 본계정' in html
    assert html.count('떼기') >= 2
