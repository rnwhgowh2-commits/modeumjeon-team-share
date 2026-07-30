# 디자인 4모드 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자마다 디자인 모드 4개(현재/검정 한 판/검정 3단/밝은 카드) 중 하나를 골라 쓰게 하고, 신규 모드에서 화면이 얼룩덜룩하지 않도록 템플릿 162개의 색·그림자·크기·여백을 규칙 변수로 정리한다. 기능은 하나도 빠짐없이 그대로 동작해야 한다.

**Architecture:** `users.design_mode` 칼럼에 모드를 저장하고, 서버가 화면을 그릴 때 `<div class="app">` 에 `ds ds-{mode}` 클래스를 붙인다. `current` 모드에서는 클래스를 **아예 붙이지 않아** 새 CSS 가 한 줄도 관여하지 않는다(안전망). 템플릿 정리는 전부 파이썬 스크립트로 수행하고 스크립트를 저장소에 남긴다.

**Tech Stack:** Flask · Flask-Login · SQLAlchemy(Alembic 없음, 경량 마이그레이션) · Jinja2 · pytest · 순수 CSS 변수

**Spec:** `docs/superpowers/specs/2026-07-31-design-mode-switch-design.md`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `프로그램/_시스템/webapp/auth/models.py` | `User.design_mode` 칼럼 |
| `프로그램/_시스템/shared/db.py` | 경량 마이그레이션 한 줄 |
| `프로그램/_시스템/webapp/design_mode.py` | **신규** — 모드 목록·검증·클래스 계산 (단일 원천) |
| `프로그램/_시스템/webapp/routes/__init__.py` | context_processor 로 `design_mode`·`design_body_class` 주입 |
| `프로그램/_시스템/webapp/templates/base.html` | `<html data-design>` · `.app` 클래스 부착 |
| `프로그램/_시스템/webapp/auth/views.py` | `POST /auth/design-mode` 저장 |
| `프로그램/_시스템/webapp/templates/auth/me.html` | 내 계정에서 모드 고르기 |
| `프로그램/_시스템/webapp/templates/partials/sidebar.html` | 사이드바 하단 빠른 전환 |
| `프로그램/_시스템/webapp/static/tokens.css` | `.ds-mono` `.ds-layer` `.ds-light` 3모드 정의 |
| `프로그램/_시스템/scripts/design_sweep.py` | **신규** — A~D 치환 스크립트 (재현·되돌리기 가능) |
| `프로그램/_시스템/scripts/design_shot_compare.py` | **신규** — 화면별 전/후 캡처 비교 |
| `프로그램/_시스템/tests/design/test_design_mode.py` | **신규** — 모드 로직 테스트 |
| `프로그램/_시스템/tests/design/test_design_sweep.py` | **신규** — 치환 안전성 테스트 |

---

### Task 1: 모드 단일 원천 모듈

**Files:**
- Create: `프로그램/_시스템/webapp/design_mode.py`
- Test: `프로그램/_시스템/tests/design/test_design_mode.py`

- [ ] **Step 1: 테스트 폴더와 실패하는 테스트 작성**

`프로그램/_시스템/tests/design/__init__.py` 를 빈 파일로 만든다.

`프로그램/_시스템/tests/design/test_design_mode.py`:

```python
# -*- coding: utf-8 -*-
"""디자인 모드 단일 원천 — 안전망(current)이 새 CSS 를 전혀 부르지 않는지가 핵심."""
import pytest

from webapp.design_mode import MODES, DEFAULT_MODE, normalize, body_class


def test_모드는_넷이다():
    assert list(MODES.keys()) == ['current', 'mono', 'layer', 'light']


def test_기본값은_현재디자인():
    assert DEFAULT_MODE == 'current'


def test_현재모드는_클래스를_붙이지_않는다():
    # 안전망의 핵심 — current 면 ds 가 한 글자도 안 붙어야 한다
    assert body_class('current') == ''


def test_검정한판은_ds_와_다크를_붙인다():
    assert body_class('mono') == 'ds ds-dark ds-mono'


def test_검정3단도_다크다():
    assert body_class('layer') == 'ds ds-dark ds-layer'


def test_밝은카드는_다크가_아니다():
    assert body_class('light') == 'ds ds-light'


@pytest.mark.parametrize('bad', ['', None, 'stripe', 'toss', '  ', 'MONO', '../etc'])
def test_모르는_값은_현재디자인으로_떨어진다(bad):
    assert normalize(bad) == 'current'


def test_아는_값은_그대로():
    assert normalize('layer') == 'layer'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapp.design_mode'`

- [ ] **Step 3: 최소 구현**

`프로그램/_시스템/webapp/design_mode.py`:

```python
# -*- coding: utf-8 -*-
"""디자인 모드 단일 원천.

★ current = 안전망. 이 모드에서는 tokens.css 의 어떤 규칙도 화면에 걸리지 않는다.
  화면에 ds 클래스를 붙이지 않기 때문이다. 새 디자인이 망가져도 여기로 돌리면
  예전 화면 그대로 돌아온다.

모드를 추가·삭제할 때 고칠 곳은 이 파일 하나다(템플릿·CSS 는 이 값을 따라간다).
"""
from __future__ import annotations

# 값 → (화면에 보일 이름, 설명, 어두운 화면인가)
MODES = {
    'current': ('현재',        '지금 쓰던 디자인 그대로',              False),
    'mono':    ('검정 한 판',  '화면 전체가 검정 하나',                True),
    'layer':   ('검정 3단',    '바탕 → 카드 → 표 머리가 한 단계씩 밝게', True),
    'light':   ('밝은 카드',   '흰 바탕에 가로 카드 요약',             False),
}
DEFAULT_MODE = 'current'


def normalize(mode) -> str:
    """모르는 값이 오면 안전망(current)으로 떨어뜨린다."""
    if not isinstance(mode, str):
        return DEFAULT_MODE
    m = mode.strip()
    return m if m in MODES else DEFAULT_MODE


def body_class(mode) -> str:
    """화면 바깥 상자에 붙일 클래스. current 는 빈 문자열(= 아무것도 안 붙임)."""
    m = normalize(mode)
    if m == DEFAULT_MODE:
        return ''
    parts = ['ds']
    if MODES[m][2]:          # 어두운 화면인가
        parts.append('ds-dark')
    parts.append('ds-' + m)
    return ' '.join(parts)
```

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add "프로그램/_시스템/webapp/design_mode.py" "프로그램/_시스템/tests/design/"
git commit -m "feat(design): 디자인 모드 단일 원천 모듈 — current 는 클래스를 안 붙인다"
```

---

### Task 2: users.design_mode 칼럼

**Files:**
- Modify: `프로그램/_시스템/webapp/auth/models.py` (User 클래스 `role` 아래)
- Modify: `프로그램/_시스템/shared/db.py` (`_apply_lightweight_migrations` 의 `migrations` 목록)
- Test: `프로그램/_시스템/tests/design/test_design_mode.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`프로그램/_시스템/tests/design/test_design_mode.py` 맨 아래에 추가:

```python
def test_사용자에게_디자인모드_칸이_있고_기본값이_현재다():
    from webapp.auth.models import User
    u = User(email='a@b.c', name='홍길동', password_hash='x')
    # 아직 DB 에 넣기 전에도 파이썬 기본값이 잡혀야 한다
    assert getattr(u, 'design_mode', None) in (None, 'current')
    assert User.__table__.c.design_mode.type.length == 16


def test_마이그레이션_목록에_디자인모드가_있다():
    import inspect as _i
    from shared import db as _db
    src = _i.getsource(_db._apply_lightweight_migrations)
    assert '"users", "design_mode"' in src or "'users', 'design_mode'" in src
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v -k 디자인모드`
Expected: FAIL — `AttributeError` / `KeyError: 'design_mode'`

- [ ] **Step 3: 칼럼 추가**

`프로그램/_시스템/webapp/auth/models.py` 의 `is_active` 줄 바로 아래에 추가:

```python
    # [2026-07-31] 디자인 모드 — 사람마다 따로 고른다.
    #   current = 안전망(예전 디자인 그대로). 값은 webapp/design_mode.py 가 단일 원천.
    design_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="current")
```

`프로그램/_시스템/shared/db.py` 의 `migrations = [` 바로 다음 줄에 추가:

```python
        # [2026-07-31] 디자인 모드 — 사람마다 따로. current=안전망(예전 디자인)
        ("users", "design_mode", "VARCHAR(16) DEFAULT 'current'"),
```

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: 커밋**

```bash
git add "프로그램/_시스템/webapp/auth/models.py" "프로그램/_시스템/shared/db.py" "프로그램/_시스템/tests/design/test_design_mode.py"
git commit -m "feat(design): users.design_mode 칼럼 + 경량 마이그레이션"
```

---

### Task 3: 서버가 화면에 모드를 주입

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/__init__.py` (`inject_active_app_default` 아래에 새 context_processor)
- Modify: `프로그램/_시스템/webapp/templates/base.html` (2행 `<html lang="ko">`, `<div class="app">`)
- Test: `프로그램/_시스템/tests/design/test_design_mode.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_화면에_모드가_주입된다(client):
    """로그인 없이도(DISABLE_AUTH) 화면이 뜨고 data-design 이 박혀 있어야 한다."""
    r = client.get('/')
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        html = r.get_data(as_text=True)
        assert 'data-design="' in html


def test_현재모드에서는_ds_클래스가_없다(client):
    r = client.get('/')
    if r.status_code != 200:
        return
    html = r.get_data(as_text=True)
    # 안전망 — app 상자에 ds 가 붙으면 안 된다
    assert 'class="app ds' not in html
```

`tests/conftest.py` 에 `client` 픽스처가 **없음을 확인했다**(2026-07-31). `tests/design/conftest.py` 를 만든다:

```python
# -*- coding: utf-8 -*-
"""디자인 모드 테스트용 앱 — 팩토리는 프로그램/_시스템/app.py 의 create_app."""
import os
import pytest

os.environ.setdefault('DISABLE_AUTH', '1')   # 로그인 벽 우회(솔로 개발용 플래그)


@pytest.fixture()
def client():
    from app import create_app                # 프로그램/_시스템/app.py:18
    flask_app = create_app()
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        yield c
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v -k 주입`
Expected: FAIL — `data-design="` 없음

- [ ] **Step 3: context_processor 추가**

`프로그램/_시스템/webapp/routes/__init__.py` 의 `inject_active_app_default` 함수 **바로 아래**에 추가:

```python
    @app.context_processor
    def inject_design_mode():
        """디자인 모드 주입 — 서버가 그릴 때 넣어야 화면이 깜빡이지 않는다.

        current(안전망)면 design_body_class 가 빈 문자열이라 ds 가 안 붙는다.
        """
        from webapp.design_mode import normalize, body_class, MODES, DEFAULT_MODE
        mode = DEFAULT_MODE
        try:
            from flask_login import current_user
            if getattr(current_user, 'is_authenticated', False):
                mode = normalize(getattr(current_user, 'design_mode', None))
        except Exception:
            mode = DEFAULT_MODE      # 로그인 전 화면 등 — 항상 안전망으로
        return {
            'design_mode': mode,
            'design_body_class': body_class(mode),
            'design_modes': MODES,
        }
```

- [ ] **Step 4: base.html 수정**

2행을 바꾼다:

```html
<html lang="ko" data-design="{{ design_mode|default('current') }}">
```

`<div class="app">` 을 찾아 바꾼다:

```html
<div class="app {{ design_body_class|default('') }}">
```

⚠️ **base.html 에서 이 두 곳 말고는 건드리지 않는다.**
특히 `localStorage.getItem('theme')` → `data-theme` 스크립트(`toss`/`stripe` 테마)는
**별도 축이라 그대로 둔다.** 두 축은 서로 간섭하지 않는다.

- [ ] **Step 5: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add "프로그램/_시스템/webapp/routes/__init__.py" "프로그램/_시스템/webapp/templates/base.html" "프로그램/_시스템/tests/design/"
git commit -m "feat(design): 서버가 화면에 디자인 모드 주입 (current 면 ds 미부착)"
```

---

### Task 4: 모드 3종 CSS 정의

**Files:**
- Modify: `프로그램/_시스템/webapp/static/tokens.css` (파일 맨 아래에 추가)
- Test: `프로그램/_시스템/tests/design/test_design_mode.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_tokens_css_에_모드_3종이_정의돼_있다():
    import io, os
    p = os.path.join(os.path.dirname(__file__), '..', '..',
                     'webapp', 'static', 'tokens.css')
    css = io.open(os.path.abspath(p), encoding='utf-8').read()
    for sel in ('.ds.ds-mono', '.ds.ds-layer', '.ds.ds-light'):
        assert sel in css, sel + ' 가 tokens.css 에 없다'


def test_tokens_css_에는_그림자를_쓰지_않는다():
    import io, os, re
    p = os.path.join(os.path.dirname(__file__), '..', '..',
                     'webapp', 'static', 'tokens.css')
    css = io.open(os.path.abspath(p), encoding='utf-8').read()
    나쁜것 = [m for m in re.findall(r'box-shadow:\s*([^;}\n]+)', css)
              if m.strip() != 'none' and not m.strip().startswith('var(')]
    assert 나쁜것 == [], 나쁜것
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v -k tokens`
Expected: FAIL — `.ds.ds-mono 가 tokens.css 에 없다`

- [ ] **Step 3: tokens.css 맨 아래에 추가**

```css
/* ═══════════════════════════════════════════════════════════════════
   디자인 모드 3종 — webapp/design_mode.py 가 값의 단일 원천
   ───────────────────────────────────────────────────────────────────
   current(안전망)는 여기에 없다. 클래스가 아예 안 붙으므로 규칙이 잠든다.
   ═══════════════════════════════════════════════════════════════════ */

/* ── 검정 한 판 (시안 1) — 층을 거의 두지 않는다 ─────────────────── */
.ds.ds-mono{
  --surface:rgba(255,255,255,.04);
  --surface2:rgba(255,255,255,.07);
}
.ds.ds-mono th{background:#141414}

/* ── 검정 3단 (시안 4) — 바탕 → 카드 → 표 머리 ──────────────────── */
.ds.ds-layer{
  --surface:#1D1D1F;
  --surface2:#2A2A2D;
}
.ds.ds-layer th{background:var(--surface2)}
.ds.ds-layer tbody tr:nth-child(odd) td{background:rgba(255,255,255,.02)}

/* ── 밝은 카드 (시안 9) — 흰 바탕 + 가로 카드 요약 ──────────────── */
.ds.ds-light{
  --bg:#FFFFFF;
  --surface:#FFFFFF;
  --n100:var(--ap-g1);
}
.ds.ds-light .ds-카드,.ds.ds-light .표칸{border:1px solid var(--line)}
```

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add "프로그램/_시스템/webapp/static/tokens.css" "프로그램/_시스템/tests/design/test_design_mode.py"
git commit -m "feat(design): 디자인 모드 3종 CSS (검정 한 판·검정 3단·밝은 카드)"
```

---

### Task 5: 모드 저장 API + 전환 UI

**Files:**
- Modify: `프로그램/_시스템/webapp/auth/views.py` (파일 맨 아래)
- Modify: `프로그램/_시스템/webapp/templates/auth/me.html` (「비밀번호 변경」 버튼 위)
- Modify: `프로그램/_시스템/webapp/templates/partials/sidebar.html` (맨 아래)
- Test: `프로그램/_시스템/tests/design/test_design_mode.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_모르는_모드를_보내면_저장하지_않는다(client):
    r = client.post('/auth/design-mode', data={'mode': '../etc'},
                    follow_redirects=False)
    assert r.status_code in (302, 400)


def test_아는_모드는_받아준다(client):
    r = client.post('/auth/design-mode', data={'mode': 'layer'},
                    follow_redirects=False)
    assert r.status_code in (302, 200)
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v -k 모드를`
Expected: FAIL — 404

- [ ] **Step 3: 라우트 추가**

`프로그램/_시스템/webapp/auth/views.py` 맨 아래에 추가:

```python
@bp.post("/design-mode")
@login_required
def set_design_mode():
    """디자인 모드 저장 — 사람마다 따로.

    모르는 값이 오면 저장하지 않고 안전망(current)을 유지한다.
    """
    from flask import request, redirect, url_for
    from flask_login import current_user
    from shared.db import SessionLocal
    from webapp.auth.models import User
    from webapp.design_mode import normalize, DEFAULT_MODE

    보낸값 = request.form.get("mode", "")
    모드 = normalize(보낸값)
    if 모드 != 보낸값.strip():
        모드 = DEFAULT_MODE          # 모르는 값 → 안전망

    with SessionLocal() as s:
        u = s.get(User, int(current_user.get_id()))
        if u is not None:
            u.design_mode = 모드
            s.commit()

    돌아갈곳 = request.form.get("next") or request.referrer or url_for("auth.me")
    return redirect(돌아갈곳)
```

> `login_required` · `bp` 가 이미 import 돼 있는지 파일 상단에서 확인하고, 없으면 추가한다.

- [ ] **Step 4: 내 계정 화면에 고르기 추가**

`auth/me.html` 의 「비밀번호 변경」 링크 **바로 위**에 추가:

```html
  <div style="background: var(--n100); border-radius: 10px; padding: 16px; margin-bottom: 20px;">
    <div style="font-size: var(--fs-caption); color: var(--n600); margin-bottom: 8px;">디자인</div>
    <form action="{{ url_for('auth.set_design_mode') }}" method="post">
      {% for key, info in design_modes.items() %}
        <label style="display:flex; align-items:flex-start; gap:8px; padding:8px 0; cursor:pointer;">
          <input type="radio" name="mode" value="{{ key }}"
                 {% if design_mode == key %}checked{% endif %}
                 onchange="this.form.submit()">
          <span>
            <span style="font-size: var(--fs-body); font-weight:600;">{{ info[0] }}</span>
            <span style="display:block; font-size: var(--fs-caption); color: var(--n600);">{{ info[1] }}</span>
          </span>
        </label>
      {% endfor %}
      <noscript><button type="submit">저장</button></noscript>
    </form>
    <div style="font-size: var(--fs-caption); color: var(--n600); margin-top:8px;">
      화면이 이상하면 「현재」로 되돌리세요. 예전 디자인 그대로 돌아옵니다.
    </div>
  </div>
```

- [ ] **Step 5: 사이드바 하단에 빠른 전환 추가**

`partials/sidebar.html` 맨 아래에 추가:

```html
{# [2026-07-31] 디자인 모드 빠른 전환 — 화면이 깨졌을 때 즉시 「현재」로 돌아오기 위해
   깊이 숨기지 않는다. 자세한 설명은 내 계정 화면에. #}
<form action="{{ url_for('auth.set_design_mode') }}" method="post" class="sb-design">
  <input type="hidden" name="next" value="{{ request.path }}">
  {% for key, info in design_modes.items() %}
    <button type="submit" name="mode" value="{{ key }}"
            class="sb-design-btn {% if design_mode == key %}on{% endif %}"
            title="{{ info[1] }}">{{ info[0] }}</button>
  {% endfor %}
</form>
```

- [ ] **Step 6: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_mode.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add "프로그램/_시스템/webapp/auth/views.py" "프로그램/_시스템/webapp/templates/auth/me.html" "프로그램/_시스템/webapp/templates/partials/sidebar.html" "프로그램/_시스템/tests/design/test_design_mode.py"
git commit -m "feat(design): 모드 저장 API + 내 계정·사이드바 전환 UI"
```

---

### Task 6: 치환 스크립트 뼈대 — 안전 규칙부터

**Files:**
- Create: `프로그램/_시스템/scripts/design_sweep.py`
- Test: `프로그램/_시스템/tests/design/test_design_sweep.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`프로그램/_시스템/tests/design/test_design_sweep.py`:

```python
# -*- coding: utf-8 -*-
"""치환이 기능을 깨뜨리지 않는지 — 이 테스트가 통과해야 실제 파일에 돌린다."""
from scripts.design_sweep import 색치환, BRAND_KEEP


def test_클래스이름은_안건드린다():
    원본 = '<div class="c-191f28 box" id="e5e8eb-panel" data-color="#191f28">x</div>'
    assert 색치환(원본) == 원본


def test_스타일_안의_색만_바꾼다():
    원본 = '<div style="color:#191F28">x</div>'
    assert 색치환(원본) == '<div style="color:var(--ink)">x</div>'


def test_css_블록_안의_색도_바꾼다():
    원본 = '.a{color:#6B7684;border:1px solid #E5E8EB}'
    assert 색치환(원본) == '.a{color:var(--글자-보조);border:1px solid var(--line)}'


def test_대소문자를_가리지_않는다():
    assert 색치환('color:#191f28') == 'color:var(--ink)'
    assert 색치환('color:#191F28') == 'color:var(--ink)'


def test_브랜드색은_남긴다():
    for 색 in BRAND_KEEP:
        원본 = 'color:%s' % 색
        assert 색치환(원본) == 원본, 색 + ' 은 바꾸면 안 된다'


def test_자바스크립트_문자열은_안건드린다():
    원본 = "el.style.color = '#191F28';"
    assert 색치환(원본) == 원본


def test_지킴목록_파일은_통째로_건너뛴다():
    from scripts.design_sweep import SKIP_FILES
    assert 'bundles/_matrix_v3.html' in SKIP_FILES
    assert 'inventory/data/items.html' in SKIP_FILES
    assert len(SKIP_FILES) == 9
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.design_sweep'`

- [ ] **Step 3: 스크립트 작성**

`프로그램/_시스템/scripts/design_sweep.py`:

```python
# -*- coding: utf-8 -*-
"""디자인 정리 스윕 — 화면에 박힌 값을 규칙 변수로 바꾼다.

쓰는 법
    python scripts/design_sweep.py --미리보기        # 몇 곳이 바뀌는지만
    python scripts/design_sweep.py --단계 A --적용   # 실제로 바꾼다

안전 규칙 (테스트로 지킨다)
  · class 이름 · id · data- 속성 · JS 문자열은 한 글자도 안 건드린다
  · 브랜드·마켓 색은 남긴다 (BRAND_KEEP)
  · JS 가 색을 읽는 9개 파일은 통째로 건너뛴다 (SKIP_FILES)
"""
from __future__ import annotations

import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TPL = os.path.join(ROOT, 'webapp', 'templates')

# ── JS 가 현재 색을 읽는 파일 — 자동 치환에서 뺀다(사람이 본다) ────────
SKIP_FILES = {
    'bundles/_matrix_v3.html',
    'bulk/partials/_settings.html',
    'inventory/data/items.html',
    'inventory/barcode.html',
    'accounts/upload.html',
    'orders/margin_embed.html',
    'inventory/home.html',
    'inventory/inspection_detail.html',
    'sourcing_guide/add.html',
}

# ── 바꾸면 안 되는 색 — 마켓·소싱처 브랜드 ────────────────────────────
#   회색으로 바뀌면 마켓 구분이 사라진다.
#   ★ 마켓 브랜드 색 대부분은 static/toss.css 의 .brand-* 에 있고
#     이 스크립트는 templates/ 만 훑으므로 자동으로 안전하다.
#     아래는 템플릿 안에 직접 박힌 것만(실측: 2026-07-31).
BRAND_KEEP = {
    '#03c75a',  # 네이버 (템플릿에 19곳)
    '#f43142',  # 마켓 포인트 (3곳)
    '#ff7e2d', '#e56b1f',   # SSG
    '#ed1b23', '#c40d14',   # 롯데
    '#1f2937', '#374151',   # SSF
}

# ── A: 색 → 변수 (상위 사용 순) ────────────────────────────────────────
COLOR_MAP = {
    '#191f28': 'var(--ink)',
    '#e5e8eb': 'var(--line)',
    '#6b7684': 'var(--글자-보조)',
    '#8b95a1': 'var(--sub)',
    '#4e5968': 'var(--글자-기본)',
    '#3182f6': 'var(--primary)',
    '#f2f4f6': 'var(--n100)',
    '#f9fafb': 'var(--bg)',
    '#d1d6db': 'var(--faint)',
    '#cbccd3': 'var(--faint)',
}

_HEX = re.compile(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b')
# 색이 「값 자리」에 있을 때만 바꾼다 — 앞에 : 또는 공백+색속성이 와야 한다
_VALUE_POS = re.compile(
    r'(?P<head>(?:color|background|background-color|border|border-color|'
    r'border-top-color|border-bottom-color|border-left-color|border-right-color|'
    r'outline-color|fill|stroke)\s*:\s*(?:[^;"\'{}]*?\s)?)'
    r'(?P<hex>#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3}))\b'
)
# JS 가 색을 넣는 줄 — 건드리지 않는다
_JS_SET = re.compile(r'\.style\.\w+\s*=')


def 색치환(본문: str) -> str:
    """값 자리에 있는 색만 변수로 바꾼다."""
    out = []
    for 줄 in 본문.splitlines(keepends=True):
        if _JS_SET.search(줄):
            out.append(줄)
            continue

        def _바꿔(m):
            h = m.group('hex').lower()
            if len(h) == 4:      # #abc → #aabbcc
                h = '#' + ''.join(ch * 2 for ch in h[1:])
            if h in BRAND_KEEP or h not in COLOR_MAP:
                return m.group(0)
            return m.group('head') + COLOR_MAP[h]

        out.append(_VALUE_POS.sub(_바꿔, 줄))
    return ''.join(out)


def 훑기(적용: bool, 단계: str = 'A'):
    바뀐파일, 바뀐곳 = 0, 0
    for dp, _, fns in os.walk(TPL):
        for f in fns:
            if not f.endswith('.html'):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, TPL).replace(os.sep, '/')
            if rel in SKIP_FILES:
                continue
            원본 = io.open(p, encoding='utf-8').read()
            새것 = 색치환(원본) if 단계 == 'A' else 원본
            if 새것 != 원본:
                바뀐파일 += 1
                바뀐곳 += sum(1 for a, b in zip(원본.split('#'), 새것.split('#')) if a != b)
                if 적용:
                    io.open(p, 'w', encoding='utf-8').write(새것)
    print('단계 %s — 파일 %d개 %s' % (단계, 바뀐파일, '수정함' if 적용 else '수정 예정'))
    return 바뀐파일


if __name__ == '__main__':
    인자 = sys.argv[1:]
    단계 = 인자[인자.index('--단계') + 1] if '--단계' in 인자 else 'A'
    훑기('--적용' in 인자, 단계)
```

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add "프로그램/_시스템/scripts/design_sweep.py" "프로그램/_시스템/tests/design/test_design_sweep.py"
git commit -m "feat(design): 치환 스크립트 뼈대 — 브랜드색·JS·9개 위험파일 보호"
```

---

### Task 7: A 단계 — 색 치환 실행

**Files:**
- Modify: `프로그램/_시스템/scripts/design_sweep.py` (`COLOR_MAP` 확장)
- Modify: 템플릿 다수 (스크립트가 수행)

- [ ] **Step 1: 상위 80색 실측**

Run:
```bash
cd "프로그램/_시스템" && python - <<'PY'
import io,os,re,collections,sys
sys.stdout.reconfigure(encoding='utf-8')
c=collections.Counter()
for dp,_,fns in os.walk('webapp/templates'):
    for f in fns:
        if f.endswith('.html'):
            s=io.open(os.path.join(dp,f),encoding='utf-8',errors='ignore').read()
            c.update(m.lower() for m in re.findall(r'#(?:[0-9a-fA-F]{6})\b',s))
for col,n in c.most_common(80): print('%-9s %5d' % (col,n))
PY
```
Expected: 80줄. `#191f28` `#e5e8eb` `#6b7684` 가 상위에 보인다.

- [ ] **Step 2: COLOR_MAP 을 80개로 채운다**

위 출력의 각 색을 규칙 변수로 매핑한다. 판단 기준:
- 어두운 회색(명도 30% 미만) → `var(--ink)`
- 중간 회색 → `var(--sub)` 또는 `var(--글자-보조)`
- 밝은 회색(명도 90% 이상) → `var(--line)` 또는 `var(--n100)`
- 파랑 계열 → `var(--primary)`
- 빨강 → `var(--red)` / 초록 → `var(--green)` / 주황·노랑 → `var(--amber)`
- **브랜드 색으로 보이면 `BRAND_KEEP` 에 넣는다** (마켓 로고·소싱처 색)

- [ ] **Step 3: 미리보기**

Run: `cd "프로그램/_시스템" && python scripts/design_sweep.py --단계 A`
Expected: `단계 A — 파일 N개 수정 예정` (N ≥ 90)

- [ ] **Step 4: 적용**

Run: `cd "프로그램/_시스템" && python scripts/design_sweep.py --단계 A --적용`

- [ ] **Step 5: 위반이 줄었는지 확인**

Run: `cd "프로그램/_시스템/.." && python "프로그램/_시스템/scripts/check_design_tokens.py"`
Expected: 「색」 항목이 9,121곳에서 **크게 줄어야** 한다(2,000곳 이하 목표).

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor(design): A단계 — 상위 80색을 규칙 변수로 치환"
```

---

### Task 8: B 단계 — 그림자·자간·최소 글자

**Files:**
- Modify: `프로그램/_시스템/scripts/design_sweep.py` (`단계 B` 추가)
- Test: `프로그램/_시스템/tests/design/test_design_sweep.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_그림자를_없앤다():
    from scripts.design_sweep import B단계
    assert B단계('.a{box-shadow:0 4px 12px rgba(0,0,0,.06)}') == '.a{border:1px solid var(--line)}'


def test_이미_없는_그림자는_그대로():
    from scripts.design_sweep import B단계
    assert B단계('.a{box-shadow:none}') == '.a{box-shadow:none}'


def test_음수자간을_0으로():
    from scripts.design_sweep import B단계
    assert B단계('h1{letter-spacing:-0.03em}') == 'h1{letter-spacing:0}'
    assert B단계('h1{letter-spacing:-.5px}') == 'h1{letter-spacing:0}'


def test_11px_미만은_11px_로_올린다():
    from scripts.design_sweep import B단계
    assert B단계('.x{font-size:10.5px}') == '.x{font-size:11px}'
    assert B단계('.x{font-size:8.5px}') == '.x{font-size:11px}'


def test_11px_이상은_그대로():
    from scripts.design_sweep import B단계
    assert B단계('.x{font-size:12px}') == '.x{font-size:12px}'
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v -k "그림자 or 자간 or 11px"`
Expected: FAIL — `ImportError: cannot import name 'B단계'`

- [ ] **Step 3: B단계 구현**

`design_sweep.py` 에 추가:

```python
_SHADOW = re.compile(r'box-shadow:\s*(?!none)[^;}"\']+')
_NEG_LS = re.compile(r'letter-spacing:\s*-[\d.]+(?:em|px|rem)')
_SMALL = re.compile(r'font-size:\s*([\d.]+)px')


def B단계(본문: str) -> str:
    """그림자 제거(선으로) · 음수 자간 0 · 11px 미만 올림."""
    s = _SHADOW.sub('border:1px solid var(--line)', 본문)
    s = _NEG_LS.sub('letter-spacing:0', s)

    def _올림(m):
        return 'font-size:11px' if float(m.group(1)) < 11 else m.group(0)

    return _SMALL.sub(_올림, s)
```

`훑기()` 의 분기에 추가:

```python
            elif 단계 == 'B':
                새것 = B단계(원본)
```

(`새것 = 색치환(원본) if 단계 == 'A' else 원본` 을 if/elif 로 바꾼다)

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v`
Expected: PASS

- [ ] **Step 5: 적용 후 확인**

Run:
```bash
cd "프로그램/_시스템" && python scripts/design_sweep.py --단계 B --적용
cd .. && python "프로그램/_시스템/scripts/check_design_tokens.py"
```
Expected: 「그림자」 206 → **0**, 「음수 자간」 34 → **0**, 「너무 작은 글자」 329 → **0**

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor(design): B단계 — 그림자 제거·음수 자간 0·11px 미만 올림"
```

---

### Task 9: C 단계 — 크기·여백·둥근 모서리

**Files:**
- Modify: `프로그램/_시스템/scripts/design_sweep.py` (`C단계` 추가)
- Test: `프로그램/_시스템/tests/design/test_design_sweep.py` (추가)

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_글자크기를_가까운_등급으로():
    from scripts.design_sweep import C단계
    assert C단계('.x{font-size:13px}') == '.x{font-size:12px}'      # 12·14 중 아래쪽
    assert C단계('.x{font-size:15px}') == '.x{font-size:14px}'
    assert C단계('.x{font-size:18px}') == '.x{font-size:17px}'
    assert C단계('.x{font-size:12px}') == '.x{font-size:12px}'      # 이미 등급


def test_여백을_가까운_단계로():
    from scripts.design_sweep import C단계
    assert C단계('.x{padding:6px}') == '.x{padding:4px}'            # 애매하면 작은 쪽
    assert C단계('.x{padding:10px}') == '.x{padding:8px}'
    assert C단계('.x{padding:18px}') == '.x{padding:16px}'
    assert C단계('.x{padding:8px}') == '.x{padding:8px}'


def test_둥근모서리를_가까운_단계로():
    from scripts.design_sweep import C단계
    assert C단계('.x{border-radius:5px}') == '.x{border-radius:8px}'
    assert C단계('.x{border-radius:10px}') == '.x{border-radius:12px}'
    assert C단계('.x{border-radius:9999px}') == '.x{border-radius:9999px}'   # 알약은 그대로
```

- [ ] **Step 2: 실패 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v -k "등급 or 단계로"`
Expected: FAIL — `ImportError: cannot import name 'C단계'`

- [ ] **Step 3: C단계 구현**

```python
FS등급 = [11, 12, 14, 17, 24, 32, 48]
SP단계 = [0, 4, 8, 12, 16, 24, 32, 48]
RAD단계 = [0, 8, 12, 18]


def _가까운(값: float, 후보: list) -> int:
    """애매하면 작은 쪽. 커지면 한 화면에 안 들어간다."""
    아래 = [c for c in 후보 if c <= 값]
    위 = [c for c in 후보 if c > 값]
    if not 아래:
        return 후보[0]
    if not 위:
        return 후보[-1]
    a, b = 아래[-1], 위[0]
    return a if (값 - a) <= (b - 값) else b


_RAD = re.compile(r'border-radius:\s*([\d.]+)px')
_PAD = re.compile(r'(padding|margin|gap)(-(?:top|right|bottom|left))?:\s*([\d.]+)px(?=[;}"\'])')


def C단계(본문: str) -> str:
    def _fs(m):
        v = float(m.group(1))
        return 'font-size:%dpx' % (11 if v < 11 else _가까운(v, FS등급))

    def _rad(m):
        v = float(m.group(1))
        return m.group(0) if v >= 100 else 'border-radius:%dpx' % _가까운(v, RAD단계)

    def _sp(m):
        return '%s%s:%dpx' % (m.group(1), m.group(2) or '',
                              _가까운(float(m.group(3)), SP단계))

    s = _SMALL.sub(_fs, 본문)
    s = _RAD.sub(_rad, s)
    return _PAD.sub(_sp, s)
```

`훑기()` 분기에 `elif 단계 == 'C': 새것 = C단계(원본)` 추가.

- [ ] **Step 4: 통과 확인**

Run: `cd "프로그램/_시스템" && python -m pytest tests/design/test_design_sweep.py -v`
Expected: PASS

- [ ] **Step 5: 적용 후 확인**

Run:
```bash
cd "프로그램/_시스템" && python scripts/design_sweep.py --단계 C --적용
cd .. && python "프로그램/_시스템/scripts/check_design_tokens.py"
```
Expected: 「글자크기」·「여백」·「둥근모서리」가 각각 **90% 이상 감소**

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor(design): C단계 — 크기 7등급·여백 7단·둥근모서리 4단으로 반올림"
```

---

### Task 10: D 단계 — 남은 색과 화면별 손질

**Files:**
- Modify: `프로그램/_시스템/scripts/design_sweep.py` (`COLOR_MAP` 확장)
- Modify: 템플릿 다수

- [ ] **Step 1: 남은 색 목록 뽑기**

Run: `cd ".." && python "프로그램/_시스템/scripts/check_design_tokens.py" --자세히 60`
Expected: 남은 색과 그 위치가 `파일:줄` 로 나온다.

- [ ] **Step 2: 남은 색을 COLOR_MAP 에 추가**

출력에 나온 색을 Task 7 Step 2 의 기준으로 분류해 `COLOR_MAP` 에 넣는다.
브랜드로 보이면 `BRAND_KEEP` 에 넣는다.

- [ ] **Step 3: 다시 적용**

Run: `cd "프로그램/_시스템" && python scripts/design_sweep.py --단계 A --적용`

- [ ] **Step 4: 확인**

Run: `cd ".." && python "프로그램/_시스템/scripts/check_design_tokens.py"`
Expected: 위반 합계가 **2,000곳 이하**

- [ ] **Step 5: 커밋**

```bash
git add -A
git commit -m "refactor(design): D단계 — 남은 색 정리"
```

---

### Task 11: 위험 9개 파일 수동 확인

**Files:**
- Modify: `SKIP_FILES` 의 9개 파일 (사람이 직접)

- [ ] **Step 1: 각 파일에서 색을 읽는 곳 찾기**

Run:
```bash
cd "프로그램/_시스템/webapp/templates" && grep -n "getComputedStyle\|\.style\.color\|\.style\.backgroundColor\|\.style\.borderColor" \
  bundles/_matrix_v3.html bulk/partials/_settings.html inventory/data/items.html \
  inventory/barcode.html accounts/upload.html orders/margin_embed.html \
  inventory/home.html inventory/inspection_detail.html sourcing_guide/add.html
```
Expected: 37줄

- [ ] **Step 2: 각 줄이 무엇을 하는지 확인하고, 값 비교가 없으면 그 파일만 치환**

색을 **읽어서 화면에 다시 넣는 것뿐**이면 치환해도 안전하다.
색을 **읽어서 판단(if)** 하면 그 부분은 손대지 않는다.

파일 하나씩:
```bash
cd "프로그램/_시스템" && python - <<'PY'
import io
from scripts.design_sweep import 색치환, B단계, C단계
p='webapp/templates/bundles/_matrix_v3.html'
s=io.open(p,encoding='utf-8').read()
io.open(p,'w',encoding='utf-8').write(C단계(B단계(색치환(s))))
print('완료', p)
PY
```

- [ ] **Step 3: 해당 화면을 실제로 열어 확인**

`_matrix_v3` = 매트릭스 화면, `items` = 재고 데이터, `margin_embed` = 마진계산기.
각 화면에서 **색으로 구분하던 것이 여전히 구분되는지** 눈으로 본다.

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "refactor(design): 위험 9개 파일 수동 확인 후 정리"
```

---

### Task 12: 전/후 캡처 비교 도구

**Files:**
- Create: `프로그램/_시스템/scripts/design_shot_compare.py`

- [ ] **Step 1: 스크립트 작성**

```python
# -*- coding: utf-8 -*-
"""화면별 전/후 캡처를 나란히 놓은 HTML 을 만든다.

쓰는 법
    python scripts/design_shot_compare.py --기준 before   # 바꾸기 전 캡처
    python scripts/design_shot_compare.py --기준 after    # 바꾼 뒤 캡처
    python scripts/design_shot_compare.py --비교          # 나란히 놓은 HTML

전제: 로컬 서버가 떠 있고 DISABLE_AUTH=1 이다.
"""
from __future__ import annotations

import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE = os.environ.get('MOUM_BASE', 'http://127.0.0.1:5000')
경로들 = [
    ('주문내역', '/orders/'),
    ('마진계산기', '/orders/margin'),
    ('상품수집', '/sourcing/'),
    ('상품관리', '/catalog/'),
    ('대량등록', '/bulk/'),
    ('매트릭스', '/bundles/'),
    ('재고데이터', '/inventory/data/items'),
    ('설정', '/settings/'),
    ('내 계정', '/auth/me'),
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '_shots')


def 비교HTML():
    os.makedirs(OUT, exist_ok=True)
    줄 = []
    for 이름, 경로 in 경로들:
        줄.append(
            '<div class="r"><h3>%s <small>%s</small></h3>'
            '<div class="p"><figure><figcaption>바꾸기 전</figcaption>'
            '<img src="before/%s.png"></figure>'
            '<figure><figcaption>바꾼 뒤</figcaption>'
            '<img src="after/%s.png"></figure></div></div>'
            % (이름, 경로, 이름, 이름))
    html = ('<!doctype html><meta charset="utf-8"><title>디자인 전후 비교</title>'
            '<style>body{font-family:Pretendard,system-ui;padding:24px;background:#F5F5F7}'
            '.r{background:#fff;border:1px solid #D2D2D7;border-radius:12px;'
            'padding:16px;margin-bottom:16px}.p{display:grid;'
            'grid-template-columns:1fr 1fr;gap:12px}img{width:100%;'
            'border:1px solid #E8E8ED;border-radius:8px}'
            'figcaption{font-size:12px;color:#86868B;margin-bottom:4px}'
            'h3{font-size:17px;font-weight:600}small{color:#86868B;font-weight:400}'
            '</style>' + ''.join(줄))
    p = os.path.join(OUT, 'compare.html')
    io.open(p, 'w', encoding='utf-8').write(html)
    print('만들었습니다 :', os.path.abspath(p))
    print('캡처는 브라우저 도구로 %s 의 각 경로를 찍어 before/ after/ 에 넣으세요.' % BASE)


if __name__ == '__main__':
    비교HTML()
```

- [ ] **Step 2: 바꾸기 전 캡처**

Task 6 시작 **전** 커밋으로 되돌린 상태에서 서버를 띄우고, 위 9개 경로를 캡처해 `_shots/before/` 에 넣는다.

- [ ] **Step 3: 바꾼 뒤 캡처**

현재 상태에서 같은 9개 경로를 캡처해 `_shots/after/` 에 넣는다.

- [ ] **Step 4: 비교 HTML 열기**

Run: `cd "프로그램/_시스템" && python scripts/design_shot_compare.py --비교`
그리고 만들어진 `compare.html` 을 브라우저로 연다.

- [ ] **Step 5: 커밋**

```bash
git add "프로그램/_시스템/scripts/design_shot_compare.py"
git commit -m "test(design): 화면별 전후 캡처 비교 도구"
```

---

### Task 13: 최종 검증

- [ ] **Step 1: 새로 깨진 테스트만 골라내기**

⚠️ `origin/main` 에 **원래 실패하는 테스트가 있다.** 반드시 대조한다.

```bash
cd "프로그램/_시스템"
git stash
python -m pytest tests -q > /tmp/before.txt 2>&1 || true
git stash pop
python -m pytest tests -q > /tmp/after.txt 2>&1 || true
diff /tmp/before.txt /tmp/after.txt
```
Expected: **차이 없음** (새로 깨진 테스트 0개)

- [ ] **Step 2: 규칙 검사기**

Run: `cd ".." && python "프로그램/_시스템/scripts/check_design_tokens.py"`
Expected: 위반 합계가 20,693 → **2,000곳 이하**. 「그림자」·「음수 자간」·「너무 작은 글자」는 **0**

- [ ] **Step 3: 네 모드를 실제로 눌러 확인**

각 모드로 바꾸며 아래를 확인한다.

| 모드 | 확인 |
|---|---|
| 현재 | **예전과 똑같아야 한다** (한 픽셀도 안 바뀜) |
| 검정 한 판 | 전체가 검정, 글자가 읽힌다 |
| 검정 3단 | 바탕/카드/표머리 밝기가 다르다 |
| 밝은 카드 | 흰 바탕, 카드 테두리가 보인다 |

- [ ] **Step 4: 기능 확인 (모드마다)**

주문내역에서: 조회 · 기간 바꾸기 · 필터 · 열 정렬 · 헤더 필터 · 송장 입력 · 엑셀 내보내기
마진계산기에서: 분석 · 카드 클릭 상세 · 전체 내역
매트릭스에서: **색으로 구분하던 것이 여전히 구분되는지**

- [ ] **Step 5: 기준선 갱신 후 커밋**

```bash
cd "프로그램/_시스템/.." && python "프로그램/_시스템/scripts/check_design_tokens.py" --기준저장
git add -A
git commit -m "chore(design): 정리 후 검사 기준선 갱신"
```

- [ ] **Step 6: PR 만들고 바로 병합**

⚠️ 다른 작업 브랜치가 80여 개 열려 있어 **오래 두면 충돌**한다.

```bash
git push -u origin feature/design-modes
gh pr create --title "feat(design): 디자인 4모드 전환 + 전 화면 정리" --body-file <(echo "스펙: docs/superpowers/specs/2026-07-31-design-mode-switch-design.md") --base main
```

병합 후 `origin/main` 에서 실제로 들어갔는지 grep 으로 확인한다(배포 로그만 믿지 않는다).

---

## 되돌리기

| 상황 | 방법 |
|---|---|
| 새 디자인이 이상하다 | 사이드바에서 **「현재」** 클릭 — 배포 불필요 |
| 특정 단계가 문제다 | 그 커밋만 `git revert` |
| 전부 되돌린다 | 이 브랜치 머지 커밋을 revert |
