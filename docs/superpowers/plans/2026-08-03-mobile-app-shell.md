# 모바일 앱 1단계 — 앱 껍데기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 폰 홈화면에 설치되는 앱 껍데기를 만들어, 169개 화면 전부에 앱 안에서 접근할 수 있게 하고, 크롤을 폰에서 시작할 수 있게 한다.

**Architecture:** 기존 PC 화면(157개)은 **한 줄도 고치지 않는다.** 폰 전용 화면은 `templates/mobile/` 아래에 새로 만들고, PC 화면 위에 얹을 껍데기(하단 탭·뒤로가기·안내 띠)는 `static/mobile_shell.js` 가 **설치된 앱 + 좁은 화면일 때만** 클라이언트에서 주입한다(`base.html` 에는 `<script>` 1줄만 추가). 크롤은 서버가 "할 일"만 알려주고 PC 크롬 확장이 집어가는 기존 통로를 그대로 쓴다 — **확장은 고치지 않는다.**

**Tech Stack:** Flask + Jinja2, SQLAlchemy, flask_login, 순수 JS(빌드 도구 없음), pytest, node(정적 검사용)

**작업 위치:** `C:\dev\모음전 프로젝트\_wt_mobileapp` · 브랜치 `feature/mobile-app-shell` (origin/main `647c8764` 기준)
🔴 주 작업폴더(`C:\dev\모음전 프로젝트`)는 2,500커밋 stale — **읽지도 말 것.**

**설계서:** `docs/superpowers/specs/2026-08-03-mobile-app-shell-design.md`

⚠️ **크롤 관련 Task(1·2·3)를 시작하기 전** 프로젝트 CLAUDE.md 의 정독 게이트대로
`프로그램/_시스템/docs/크롤링-가이드.md` 를 먼저 읽는다. 이번 작업은 크롤 **로직**을 바꾸지 않고
시작 신호와 상태 표시만 더하지만, 게이트는 게이트다.

---

## 사전 확인된 사실 (구현 전 재조사 불필요)

| 항목 | 확인 결과 |
|---|---|
| `/mobile` 라이브 동작 | ✅ `https://mou-m.com/mobile` → **200** (실측). `app.py:345` 의 `ENVIRONMENT=team-share-dev` 게이트 안에서 등록되며, 그 값은 레포 밖(AWS Lightsail 컨테이너 환경변수)에 설정돼 있다. **`fly.toml` 은 잔재이니 보지 말 것** — 라이브는 Cloudflare ▶ Caddy ▶ 앱 컨테이너다 |
| `manifest.json` | `display: standalone`, **`scope: "/"`** → 사이트 전체가 설치된 앱 안에서 열린다. 수정 불필요 |
| `sw.js` | 현재 API/HTML 을 **Network First + 오프라인 시 캐시 폴백** → 낡은 가격·재고가 뜰 수 있다. Task 7 에서 교체 |
| 크롤 폴링 통로 | 🔴 **정정(2026-08-04 실측)**: 확장은 `/api/crawl/due-bundles` 만 **1분 주기**로 폴링(`chrome.alarms`). `/api/crawl/queue` 는 **PC 자동화 화면**이 1.5초로 부른다. 게다가 확장의 폴링 알람은 화면의 실행/정지 버튼이 만들어서 **크롤이 멈춰 있으면 확장은 서버를 안 부른다** |
| 크롤 on/off | `lemouton/pricing/settings.py` 의 `crawl_auto_enabled` · `get_automation()` / `save_automation()` |
| 한 바퀴 시작 | `lemouton/sources/crawl_schedule.py:444` `start_new_lap(session, now=None, record=True)` |
| PC 연결 여부 | `CrawlWorker`(`lemouton/sourcing/models.py:614`)에 `last_heartbeat_at` 컬럼은 있으나 **채우는 코드가 없다** |
| 온라인 판정 상수 | `lemouton/sourcing/crawl_queue.py` `HEARTBEAT_ONLINE_SEC = 90` |
| 메뉴 단일 원천 | `webapp/routes/api_sidebar.py:513` `get_layout_for_template()` → `{'standalone': [...], 'stages': [{'items': [...]}]}` |
| 모바일 공통 템플릿 | `webapp/templates/mobile/_base.html` (376줄) — 헤더·FAB 있음, **하단 탭 없음** |
| 로그인 | `webapp/auth/views.py:37` `login_user(user, remember=form.remember.data)`. `REMEMBER_COOKIE_DURATION` 미설정(flask_login 기본 365일) |
| 스키마 변경 | **Alembic 없다.** 신규 테이블은 `shared/db.py:init_db()` 의 `create_all` 이, 신규 컬럼은 `_apply_lightweight_migrations()` 가 만든다. 이번 작업은 **둘 다 불필요**(`crawl_workers` 테이블·컬럼이 이미 모델에 있음) — Task 1 Step 0 에서 실재 확인만 한다 |
| 파이썬 테스트 | pytest. 픽스처 관행: `monkeypatch.setenv('DISABLE_AUTH','1')` → `app.create_app()` → `test_client()` |
| JS 테스트 | `tests/js/*.js` — `node`로 직접 실행하는 소스 정적 검사. CI 연결 없음 |

### 🔴 설계서와 달라지는 점 1건 (진행률 퍼센트)

설계서 §4.4 는 "진행률 = 처리한 수 ÷ 전체 수, **정확히 낼 수 없으면 퍼센트를 지어내지 않는다**" 로 못 박았다.
조사 결과 **정확히 낼 수 없다** — 대기 목록(`due_bundle_codes`)은 *모음전 코드* 단위이고
바퀴 대상(`_lap_products`)은 *소싱처 URL* 단위라 분모·분자의 단위가 다르다.

**따라서 퍼센트 막대를 만들지 않는다.** 대신 "지금 대기 N건" + "오늘 N바퀴 · 마지막 완료 HH:MM" 을 보여준다.
(시안에 있던 62% 막대는 빠진다 — 사장님께 보고 완료해야 함)

---

## 파일 구조

### 새로 만드는 파일

| 파일 | 책임 |
|---|---|
| `webapp/routes/mobile_crawl.py` | 크롤 리모컨 — 페이지 1 + API 3 (상태·on/off·한 바퀴) |
| `webapp/templates/mobile/crawl.html` | 크롤 리모컨 화면 |
| `webapp/templates/mobile/menu.html` | "전체" 메뉴 — 진입점 25줄(PC 메뉴와 단일 원천) + 폰 전용 구역 |
| `webapp/templates/mobile/install.html` | 설치 안내 (아이폰/안드로이드) |
| `webapp/templates/mobile/_tabbar.html` | 하단 탭 4칸 (폰 전용 화면용 include) |
| `webapp/static/mobile_shell.css` | 껍데기 스타일 (하단 탭·상단바·안내 띠·safe-area) |
| `webapp/static/mobile_shell.js` | PC 화면 위에 껍데기 주입 (설치된 앱 + 좁은 화면일 때만) |
| `tests/mobile/test_crawl_presence.py` | PC 연결 감지 |
| `tests/mobile/test_crawl_remote_api.py` | 리모컨 API 3종 |
| `tests/mobile/test_menu_single_source.py` | 메뉴가 PC와 같은 원천을 쓴다 |
| `tests/mobile/test_shell_pages.py` | 새 페이지 3개가 열린다 |
| `tests/mobile/test_login_persistence.py` | 로그인 유지 90일 |
| `tests/js/test_sw_no_money_cache.js` | sw.js 가 돈 데이터를 캐시하지 않는다 |

### 고치는 파일

| 파일 | 무엇을 |
|---|---|
| `lemouton/sourcing/crawl_queue.py` | `touch_worker_heartbeat()` · `worker_presence()` 추가 |
| `webapp/routes/api.py` | `/crawl/due-bundles`·`/crawl/queue` 에서 heartbeat 기록 (각 1줄) |
| `app.py` | `mobile_crawl` blueprint 등록 · `REMEMBER_COOKIE_DURATION` |
| `webapp/auth/forms.py` | "로그인 유지" 기본 체크 |
| `webapp/templates/mobile/_base.html` | 하단 탭 include · `m-body` 클래스 (2줄) |
| `webapp/templates/mobile/home.html` | 크롤 상태 한 줄 + 최근 본 화면 |
| `webapp/templates/base.html` | `mobile_shell` css/js 링크 (2줄) — **PC 화면에서 유일하게 손대는 곳** |
| `webapp/static/sw.js` | 오프라인 정책 A안으로 교체 |


### 🔴 2026-08-04 발견 — 시험 픽스처에 `ENVIRONMENT` 가 필요하다

`/mobile/*` 라우트는 `app.py:345` 의 `if os.environ.get("ENVIRONMENT") == "team-share-dev":`
게이트 **안에서만** 등록된다. 그 값은 레포 밖(AWS Lightsail 환경변수)에 있고 pytest 는 모른다.
`tests/conftest.py` 도 `DATABASE_URL` 만 손댄다.

→ 폰 화면·API 를 치는 모든 시험의 `client` 픽스처에 반드시 넣을 것:
```python
monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
```
안 넣으면 라우트가 0개라 **전부 404** 다. (Task 1 이 안 걸린 건 게이트 밖의 `/api/crawl/*` 만 쳐서다)

라우트를 게이트 밖으로 빼는 것은 **금지** — 프로덕션 등록 조건이 바뀐다.

### 🔴 2026-08-04 발견 — 응답 리터럴을 믿는 시험은 헛돈다

`api_auto` / `api_run_lap` 은 `jsonify(ok=True, auto_enabled=True)` 처럼 **붙박이 값**을 돌려준다.
그래서 응답만 보는 시험은 저장 로직을 통째로 지워도 통과한다(Task 2 에서 실제로 발각됐다).
**반드시 `/api/status` 로 되물어 저장된 값을 확인**할 것.

---

## Task 1: "PC 연결됨" — 서버가 크롤 PC의 생존을 안다

> 🔴 **2026-08-04 정정 — 아래 Step 3·5 의 코드는 그대로 쓰지 말 것.**
> 실측 결과 전제가 틀렸다(설계서 §4.4 정정 블록 참조). 사장님 확정 A안에 따라:
> ① 확장(`background.js`)에 크롤 폴링 알람을 **항상 켜는 1줄**을 넣고 버전을 올린다
> ② 생존 신호는 **`/api/crawl/due-bundles` 한 곳만** — `crawl_queue()` 쪽 기록은 **제거**
> ③ 온라인 창 **90초 → 180초**, 판정 로직은 `online_workers()` 와 **한 곳으로 합친다**(기존 naive/aware 비교 버그도 같이 수정)
> ④ 워커 행 이름은 사람이 지을 수 있는 "크롤 PC" 대신 **센티널**(`__crawl_poll__`)
> ⑤ DB 를 열기 전에 **프로세스 로컬 시각**으로 먼저 스로틀 · 최초 INSERT 경합은 모듈 안에서 `IntegrityError` 처리
> ⑥ 시계는 `now=None` 으로 주입받는다(같은 파일의 `reap_expired_jobs`·`online_workers` 관행)

**왜:** 리모컨의 5개 기능 중 유일하게 배관이 없는 부분. 확장을 고치지 않고, 확장이 일감을 물어볼 때 서버가 시각을 남긴다.

**Files:**
- Modify: `lemouton/sourcing/crawl_queue.py` (파일 끝에 추가)
- Modify: `webapp/routes/api.py:94-150` (두 라우트에 1줄씩)
- Test: `tests/mobile/test_crawl_presence.py`

- [ ] **Step 0: `crawl_workers` 테이블이 실제로 있는지 본다**

이 저장소엔 Alembic 이 없다. 모델에만 있고 테이블이 안 만들어졌을 수 있으므로 먼저 확인한다.

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -c "
import app; app.create_app()
from shared.db import engine
from sqlalchemy import inspect
print('crawl_workers 있음:', inspect(engine).has_table('crawl_workers'))"
```
Expected: `crawl_workers 있음: True`.
False 면 `app.py` 가 `lemouton.sourcing.models` 를 import 하는지 확인한다(모델이 등록돼야 `create_all` 이 만든다).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/mobile/test_crawl_presence.py` 를 새로 만든다:

```python
# -*- coding: utf-8 -*-
"""폰 크롤 리모컨의 'PC 연결됨' 판정.

확장은 고치지 않는다 — 확장이 /api/crawl/due-bundles 를 부를 때 서버가 시각을 남긴다.
이 표시가 틀리면 사장님이 '눌러도 아무 일 없는 버튼'을 누르게 된다.
"""
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db():
    from shared.db import SessionLocal, Base, engine
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()


def _clear(s):
    from lemouton.sourcing.models import CrawlWorker
    s.query(CrawlWorker).delete()
    s.commit()


def test_아무도_안_왔으면_PC는_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    got = q.worker_presence()
    assert got["online"] is False
    assert got["last_seen_at"] is None


def test_한_번_다녀가면_PC가_켜진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    got = q.worker_presence()
    assert got["online"] is True
    assert got["seconds_ago"] is not None and got["seconds_ago"] < 10


def test_90초를_넘기면_꺼진_것으로_본다(db):
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    w = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    w.last_heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=200)
    db.commit()
    assert q.worker_presence()["online"] is False


def test_폴링이_잦아도_30초_안에는_다시_안_쓴다(db):
    """확장은 1~2초마다 부른다. 매번 DB 를 쓰면 낭비다."""
    from lemouton.sourcing import crawl_queue as q
    from lemouton.sourcing.models import CrawlWorker
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    w = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    first = w.last_heartbeat_at
    q.touch_worker_heartbeat(ip_address="1.2.3.4")
    db.expire_all()
    w2 = db.query(CrawlWorker).filter(CrawlWorker.name == q.CRAWL_PC_NAME).first()
    assert w2.last_heartbeat_at == first, "30초 안에 두 번 썼다"


def test_폰에서_연 화면은_PC로_치지_않는다(db):
    """사장님이 폰으로 PC용 자동화 화면을 열어도 'PC 연결됨'이 되면 안 된다."""
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    q.touch_worker_heartbeat(ip_address="1.2.3.4", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile/15E148")
    assert q.worker_presence()["online"] is False
```

- [ ] **Step 2: 실패를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/mobile/test_crawl_presence.py -v
```
Expected: FAIL — `AttributeError: module 'lemouton.sourcing.crawl_queue' has no attribute 'worker_presence'`

- [ ] **Step 3: 최소 구현 — `crawl_queue.py` 파일 맨 끝에 추가**

```python
# ══════════════════════════════════════════════════════════════════════
# 폰 크롤 리모컨용 — 로컬 PC 생존 신호
#
# 확장(moum-crawler)은 고치지 않는다. 확장이 /api/crawl/due-bundles 를 부르는
# 순간을 서버가 기록해서 '지금 PC 가 켜져 있나'를 판정한다.
#
# 지금 크롤 PC 는 한 대다 → 행 하나(CRAWL_PC_NAME)만 쓴다. 여러 대를 구분해야
# 하면 CrawlWorker 가 이미 name 별 다중 행을 지원하므로 그때 확장한다.
# ══════════════════════════════════════════════════════════════════════
CRAWL_PC_NAME = "크롤 PC"
HEARTBEAT_WRITE_MIN_SEC = 30      # 폴링이 1~2초마다라 매번 쓰지 않는다

_MOBILE_UA_MARKERS = ("iphone", "ipad", "android", "mobile")


def _looks_like_phone(user_agent: Optional[str]) -> bool:
    ua = (user_agent or "").lower()
    return any(m in ua for m in _MOBILE_UA_MARKERS)


def touch_worker_heartbeat(*, ip_address: Optional[str] = None,
                           user_agent: Optional[str] = None) -> None:
    """크롤 폴링이 들어온 순간을 남긴다. 폰에서 온 요청은 무시한다.

    폰으로 PC용 자동화 화면을 열어도 'PC 연결됨'이 되면 안 된다 —
    그러면 눌러도 아무 일 없는 버튼을 누르게 된다.
    """
    if _looks_like_phone(user_agent):
        return
    now = _now()
    s = SessionLocal()
    try:
        w = s.query(CrawlWorker).filter(CrawlWorker.name == CRAWL_PC_NAME).first()
        if w is None:
            s.add(CrawlWorker(name=CRAWL_PC_NAME,
                              last_heartbeat_at=now.replace(tzinfo=None),
                              ip_address=ip_address))
            s.commit()
            return
        last = _as_utc(w.last_heartbeat_at)
        if last is not None and (now - last).total_seconds() < HEARTBEAT_WRITE_MIN_SEC:
            return
        w.last_heartbeat_at = now.replace(tzinfo=None)
        if ip_address:
            w.ip_address = ip_address
        s.commit()
    finally:
        s.close()


def worker_presence() -> dict:
    """폰 리모컨용 — {'online': bool, 'last_seen_at': iso|None, 'seconds_ago': int|None}"""
    s = SessionLocal()
    try:
        w = s.query(CrawlWorker).filter(CrawlWorker.name == CRAWL_PC_NAME).first()
        last = _as_utc(w.last_heartbeat_at) if w is not None else None
    finally:
        s.close()
    if last is None:
        return {"online": False, "last_seen_at": None, "seconds_ago": None}
    ago = (_now() - last).total_seconds()
    return {
        "online": ago <= HEARTBEAT_ONLINE_SEC,
        "last_seen_at": last.isoformat(),
        "seconds_ago": int(ago),
    }


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """DB 컬럼은 naive UTC 로 저장된다 — 비교 전에 tz 를 붙인다."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
```

- [ ] **Step 4: 통과를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/mobile/test_crawl_presence.py -v
```
Expected: PASS (5 passed)

- [ ] **Step 5: 폴링 라우트에서 기록하게 한다**

`webapp/routes/api.py` 의 `crawl_queue()`(94행) 와 `crawl_due_bundles()`(121행) — **각 함수의 `return jsonify(...)` 바로 앞**에 아래를 넣는다:

```python
    # [모바일 1단계] 폰 리모컨의 'PC 연결됨' 판정 근거 — 여기 온 순간을 남긴다.
    #   확장은 고치지 않는다. 폰 UA 는 안쪽에서 걸러진다.
    try:
        from lemouton.sourcing.crawl_queue import touch_worker_heartbeat
        touch_worker_heartbeat(ip_address=request.remote_addr,
                               user_agent=request.user_agent.string)
    except Exception:       # noqa: BLE001 — 기록 실패가 크롤 폴링을 막으면 안 된다
        logger.warning("[mobile] heartbeat 기록 실패", exc_info=True)
```

`request` 와 `logger` 가 이미 `api.py` 상단에 import 돼 있는지 확인하고, 없으면 추가한다:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && grep -n "^from flask import\|^logger" webapp/routes/api.py | head -3
```

- [ ] **Step 6: 라우트가 실제로 기록하는지 테스트를 더한다**

`tests/mobile/test_crawl_presence.py` 끝에 추가:

```python
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_확장이_일감을_물어보면_PC가_켜진_것으로_바뀐다(client, db):
    from lemouton.sourcing import crawl_queue as q
    _clear(db)
    assert q.worker_presence()["online"] is False
    r = client.get('/api/crawl/due-bundles',
                   headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126'})
    assert r.status_code == 200
    assert q.worker_presence()["online"] is True
```

- [ ] **Step 7: 통과를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/mobile/test_crawl_presence.py -v
```
Expected: PASS (6 passed)

- [ ] **Step 8: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/lemouton/sourcing/crawl_queue.py 프로그램/_시스템/webapp/routes/api.py 프로그램/_시스템/tests/mobile/test_crawl_presence.py && git commit -m "feat(mobile): 크롤 PC 생존 신호 — 확장 수정 없이 폴링 시각 기록"
```

---

## Task 2: 크롤 리모컨 API 3종

**Files:**
- Create: `webapp/routes/mobile_crawl.py`
- Modify: `app.py:352-357` (blueprint 등록)
- Test: `tests/mobile/test_crawl_remote_api.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/mobile/test_crawl_remote_api.py`:

```python
# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 API — 상태 조회 / 자동 on-off / 지금 한 바퀴.

크롤 자체는 로컬 PC 원칙 그대로다. 서버는 '할 일' 표시만 바꾼다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_상태를_물으면_필요한_칸이_다_온다(client):
    r = client.get('/mobile/crawl/api/status')
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    for key in ('pc', 'auto_enabled', 'waiting', 'laps_today', 'last_lap_at'):
        assert key in d, f'{key} 칸이 없다'
    assert 'online' in d['pc']


def test_퍼센트는_지어내지_않는다(client):
    """분모·분자의 단위가 달라 정확한 퍼센트를 낼 수 없다 — 아예 안 준다."""
    d = client.get('/mobile/crawl/api/status').get_json()
    assert 'percent' not in d


def test_자동크롤을_켜고_끌_수_있다(client):
    r = client.post('/mobile/crawl/api/auto', json={'enabled': True})
    assert r.status_code == 200 and r.get_json()['auto_enabled'] is True
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is True

    r = client.post('/mobile/crawl/api/auto', json={'enabled': False})
    assert r.get_json()['auto_enabled'] is False
    assert client.get('/mobile/crawl/api/status').get_json()['auto_enabled'] is False


def test_한_바퀴를_시키면_자동크롤도_같이_켜진다(client):
    """꺼져 있으면 서버가 할 일 목록을 비워버려 PC 가 아무것도 안 집어간다."""
    client.post('/mobile/crawl/api/auto', json={'enabled': False})
    r = client.post('/mobile/crawl/api/run-lap', json={})
    assert r.status_code == 200
    d = r.get_json()
    assert d['ok'] is True
    assert d['auto_enabled'] is True


def test_한_바퀴는_가짜_완료기록을_남기지_않는다(client):
    """start_new_lap(record=True) 면 돌지도 않은 바퀴가 '완료'로 박힌다."""
    before = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    client.post('/mobile/crawl/api/run-lap', json={})
    after = client.get('/mobile/crawl/api/status').get_json()['laps_today']
    assert after == before, '누르기만 했는데 바퀴 수가 늘었다'
```

- [ ] **Step 2: 실패를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/mobile/test_crawl_remote_api.py -v
```
Expected: FAIL — 404 (blueprint 없음)

- [ ] **Step 3: `webapp/routes/mobile_crawl.py` 를 만든다**

```python
# -*- coding: utf-8 -*-
"""폰 크롤 리모컨 — 폰이 시키고 로컬 PC 크롬 확장이 실행한다.

크롤 = 로컬 PC 원칙은 그대로다. 서버는 '할 일' 표시만 바꾸고,
실제 크롤은 확장이 /api/crawl/due-bundles 를 폴링해 가져간다. 확장은 고치지 않는다.

라우트:
  GET  /mobile/crawl/            → 리모컨 화면
  GET  /mobile/crawl/api/status  → PC 생존 · 자동 on/off · 대기 건수 · 오늘 바퀴
  POST /mobile/crawl/api/auto    → {"enabled": bool}
  POST /mobile/crawl/api/run-lap → 지금 한 바퀴 (자동 켜기 + 랩 카운터 리셋)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from shared.db import SessionLocal

logger = logging.getLogger(__name__)

bp = Blueprint("mobile_crawl", __name__, url_prefix="/mobile/crawl")


@bp.route("/")
def page():
    return render_template("mobile/crawl.html")


def _status_payload() -> dict:
    from lemouton.sourcing.crawl_queue import worker_presence
    from lemouton.pricing.settings import get_automation
    from lemouton.sources.crawl_schedule import due_bundle_codes, lap_stats

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = SessionLocal()
    try:
        auto = bool(get_automation(s).get("crawl_auto_enabled"))
        waiting = len(due_bundle_codes(s, now=now)) if auto else 0
        try:
            stats = lap_stats(s, now=now) or {}
        except Exception:       # noqa: BLE001 — 통계가 죽어도 리모컨은 떠야 한다
            logger.warning("[mobile] lap_stats 실패", exc_info=True)
            stats = {}
    finally:
        s.close()

    # lap_stats 반환(실측): laps_today=int, today_laps=[{"no":1,"at":"ISO"}...],
    #   current_lap_no, avg_lap_minutes, recent_lap_minutes
    #   ⚠️ today_laps 는 '개수'가 아니라 '목록'이다 — 개수는 laps_today 다.
    today = stats.get("today_laps") or []
    return {
        "ok": True,
        "pc": worker_presence(),
        "auto_enabled": auto,
        # 퍼센트는 주지 않는다 — 대기목록(모음전 코드)과 바퀴대상(소싱처 URL)의
        # 단위가 달라 정확한 진행률을 낼 수 없다. 지어내지 않는다(설계서 §4.4).
        "waiting": waiting,
        "laps_today": int(stats.get("laps_today") or 0),
        "last_lap_at": (today[-1].get("at") if today else None),
    }


@bp.route("/api/status")
def api_status():
    return jsonify(_status_payload())


@bp.post("/api/auto")
def api_auto():
    from lemouton.pricing.settings import save_automation

    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return jsonify(ok=False, error="enabled 없음"), 400
    s = SessionLocal()
    try:
        save_automation(s, {"crawl_auto_enabled": bool(body["enabled"])})
        s.commit()
    finally:
        s.close()
    return jsonify(ok=True, auto_enabled=bool(body["enabled"]))


@bp.post("/api/run-lap")
def api_run_lap():
    """지금 한 바퀴 — 랩 카운터를 0으로 되돌려 전 대상을 '지금 긁을 것'으로 만든다.

    record=False: 실제로 돈 바퀴가 아니므로 완료 기록을 남기지 않는다
    (남기면 '오늘 몇 바퀴' 가 가짜로 부풀어 오른다).
    자동 크롤이 꺼져 있으면 서버가 할 일 목록을 비우므로 같이 켠다.
    """
    from lemouton.pricing.settings import save_automation
    from lemouton.sources.crawl_schedule import start_new_lap

    s = SessionLocal()
    try:
        save_automation(s, {"crawl_auto_enabled": True})
        n = start_new_lap(s, record=False)
        s.commit()
    finally:
        s.close()
    return jsonify(ok=True, auto_enabled=True, reset=n)
```

- [ ] **Step 4: blueprint 를 등록한다**

`app.py` 의 `app.register_blueprint(_mobile_bp)` (354행) **바로 다음 줄**에 추가:

```python
            from webapp.routes.mobile_crawl import bp as _mobile_crawl_bp
            app.register_blueprint(_mobile_crawl_bp)
```

- [ ] **Step 5: 통과를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/mobile/test_crawl_remote_api.py -v
```
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/routes/mobile_crawl.py 프로그램/_시스템/app.py 프로그램/_시스템/tests/mobile/test_crawl_remote_api.py && git commit -m "feat(mobile): 크롤 리모컨 API — 상태·자동on/off·지금 한 바퀴"
```

---

## Task 3: 크롤 리모컨 화면

> 🔴🔴 **2026-08-04 — 먼저 할 것(Step 0). 실 DB 를 망가뜨릴 수 있는 구멍이다.**
>
> Task 2 가 넣은 `member_client` 픽스처(`tests/mobile/test_crawl_remote_api.py:77-86`)는
> **DB 의 사용자를 전부 `is_active=False` 로 만들었다가 되돌린다.**
> 이 워크트리는 `.env` 가 없어 임시 SQLite 로 격리되지만, **`.env` 가 있는 체크아웃
> (= 메인 개발 폴더)에서 `pytest tests/mobile` 을 돌리면 라이브 팀 DB 를 친다.**
> 이유: `config.py:10` 이 `load_dotenv(..., override=True)` 라 `conftest.py` 가 넣은
> 임시 `DATABASE_URL` 을 **덮어쓴다**. Ctrl-C·크래시로 중간에 끊기면 복구가 안 돼
> **사장님·팀원 계정이 전부 로그인 불가로 남는다.**
>
> **Step 0 — 그 픽스처 맨 앞에 가드를 넣는다:**
> ```python
> from shared.db import engine
> if engine.url.get_backend_name() != "sqlite":
>     pytest.skip("사용자를 비활성화하는 시험이라 진짜 DB 에선 안 돈다")
> ```
> 넣은 뒤 `python -m pytest tests/mobile/ -v` 로 SQLite 에서는 여전히 도는지 확인한다.
> 이건 Task 2 가 만든 게 아니라 원래 잠들어 있던 지뢰(conftest ↔ dotenv override)를
> **처음으로 파괴적인 시험이 밟은** 것이다.


> 🔴 **2026-08-04 갱신** — Task 2 검토 결과로 API 모양과 인증 응답이 바뀌었다. 아래가 갱신본이다.

**Task 2 가 실제로 주는 응답**

```json
{"ok": true,
 "pc": {"online": true, "last_seen_at": "...", "seconds_ago": 12},
 "auto_enabled": true,
 "waiting": 148,
 "laps_today": 3,
 "stats_ok": true,
 "last_lap_today_at": "...",
 "last_lap_seconds_ago": 900}
```

`laps_today` 는 통계 조회가 실패하면 `null` 이고 그때 `stats_ok` 가 `false` 다.
`run-lap` 응답에만 있는 `reset` 은 **화면에 쓰지 말 것** — 랩 대상 전체 개수라 "리셋된 건수"가 아니다.

**꼭 지킬 것 3가지**

1. **시각 문자열을 쓰지 말고 `*_seconds_ago` 를 쓴다.** 서버가 주는 ISO 문자열엔 시간대가 없어 폰에서 9시간 어긋난다.
2. **`laps_today` 가 `null`(=`stats_ok:false`)이면 `0` 이 아니라 `-`(모름)으로 그린다.** 0 으로 그리면 "진짜 0바퀴"와 구별이 안 된다.
3. **인증 실패가 JSON 이 아니라 HTML 로 온다.** 리모컨은 admin 전용이라 member 는 **403 HTML**, 세션 만료면 **로그인 HTML** 이 온다. `r.json()` 을 바로 부르면 터진다 → content-type 을 먼저 본다.

**Files:**
- Create: `webapp/templates/mobile/crawl.html`
- Test: `tests/mobile/test_shell_pages.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/mobile/test_shell_pages.py`:

```python
# -*- coding: utf-8 -*-
"""1단계에서 새로 생기는 폰 화면들이 실제로 열리는지."""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def test_크롤_리모컨_화면이_열린다(client):
    r = client.get('/mobile/crawl/')
    assert r.status_code == 200
    assert 'mobile-crawl' in r.get_data(as_text=True)


def test_PC가_꺼져있으면_누를_수_없다는_것이_화면에_박혀있다(client):
    """누르면 되는 줄 알고 눌렀는데 아무 일도 안 일어나는 게 제일 나쁘다."""
    html = client.get('/mobile/crawl/').get_data(as_text=True)
    assert 'disabled' in html
    assert 'PC' in html


def test_화면은_시각문자열이_아니라_초를_쓴다(client):
    """서버가 주는 ISO 에는 시간대가 없어 폰에서 9시간 어긋난다."""
    html = client.get('/mobile/crawl/').get_data(as_text=True)
    assert 'seconds_ago' in html
    assert 'last_lap_today_at' not in html, '시간대 없는 문자열을 화면이 직접 쓴다'


def test_통계를_못_읽으면_0이_아니라_모름으로_그린다(client):
    html = client.get('/mobile/crawl/').get_data(as_text=True)
    assert 'stats_ok' in html, '통계 실패를 구분하지 않는다'


def test_인증_실패가_HTML로_와도_안_터진다(client):
    """리모컨은 admin 전용 — member 는 403 HTML, 세션 만료면 로그인 HTML 이 온다."""
    html = client.get('/mobile/crawl/').get_data(as_text=True)
    assert 'content-type' in html.lower(), 'JSON 인지 확인하지 않고 바로 파싱한다'


def test_리셋_건수는_화면에_쓰지_않는다(client):
    """run-lap 의 reset 은 '리셋된 건수'가 아니라 랩 대상 전체 개수다."""
    html = client.get('/mobile/crawl/').get_data(as_text=True)
    assert '건 리셋' not in html
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: FAIL — `TemplateNotFound: mobile/crawl.html`

- [ ] **Step 3: `webapp/templates/mobile/crawl.html` 을 만든다**

```html
{% extends "mobile/_base.html" %}
{% block title %}크롤{% endblock %}

{% block content %}
<div id="mobile-crawl">
  <div id="mc-pc" class="m-card" style="padding:14px;margin-bottom:10px">
    <div class="m-loading"><span class="m-spinner"></span>확인 중...</div>
  </div>

  <div id="mc-state" class="m-card" style="padding:14px;margin-bottom:10px"></div>

  <button id="mc-run" class="m-action-btn primary" style="width:100%;margin-bottom:10px" disabled>
    ▶ 지금 한 바퀴 돌리기
  </button>

  <div class="m-card" style="padding:12px 14px;display:flex;align-items:center;justify-content:space-between">
    <span style="font-weight:600">자동 크롤</span>
    <input type="checkbox" id="mc-auto" style="width:44px;height:26px" disabled>
  </div>

  <p id="mc-help" style="font-size:12px;color:var(--n500);margin-top:14px;line-height:1.7"></p>
</div>
{% endblock %}

{% block extra_script %}
<script>
(function () {
  const $pc = document.getElementById('mc-pc');
  const $state = document.getElementById('mc-state');
  const $run = document.getElementById('mc-run');
  const $auto = document.getElementById('mc-auto');
  const $help = document.getElementById('mc-help');
  let busy = false;

  // 인증 실패는 JSON 이 아니라 HTML 로 온다 — 리모컨은 admin 전용이라 member 는
  // 403 HTML, 세션이 끊기면 로그인 HTML 이다. 바로 파싱하면 터진다.
  async function askServer(url, opts) {
    const r = await fetch(url, Object.assign({ cache: 'no-store' }, opts || {}));
    const ct = (r.headers.get('content-type') || '').toLowerCase();
    if (!ct.includes('application/json')) {
      const e = new Error('not-json');
      e.kind = (r.status === 401 || r.redirected) ? 'login'
             : (r.status === 403) ? 'forbidden' : 'server';
      throw e;
    }
    return r.json();
  }

  function fmtAgo(sec) {
    if (sec === null || sec === undefined) return '없음';
    if (sec < 60) return sec + '초 전';
    if (sec < 3600) return Math.floor(sec / 60) + '분 전';
    if (sec < 86400) return Math.floor(sec / 3600) + '시간 전';
    return Math.floor(sec / 86400) + '일 전';
  }

  function lock(msg, detail) {
    $pc.innerHTML = '<b style="color:#B91C1C">' + msg + '</b>'
      + (detail ? '<div style="font-size:12px;color:var(--n500);margin-top:4px">' + detail + '</div>' : '');
    $state.innerHTML = '';
    $run.disabled = true;
    $auto.disabled = true;
    $help.textContent = '';
  }

  function render(d) {
    const online = d.pc && d.pc.online;
    $pc.innerHTML =
      '<div style="display:flex;align-items:center;gap:8px">'
        + '<span style="width:9px;height:9px;border-radius:50%;background:'
        + (online ? '#22C55E' : '#9CA3AF') + '"></span>'
        + '<b style="color:' + (online ? '#15803D' : '#B91C1C') + '">'
        + (online ? 'PC 연결됨' : 'PC 꺼져 있음') + '</b>'
      + '</div>'
      + '<div style="font-size:12px;color:var(--n500);margin-top:4px">마지막 응답 '
        + fmtAgo(d.pc && d.pc.seconds_ago) + '</div>';

    // 통계를 못 읽었으면 0 이 아니라 '-' 다. 0 으로 그리면 진짜 0바퀴와 구별이 안 된다.
    const laps = (d.stats_ok === false || d.laps_today === null || d.laps_today === undefined)
      ? '-' : d.laps_today;
    const lastLap = (d.last_lap_seconds_ago === null || d.last_lap_seconds_ago === undefined)
      ? '' : ' · 마지막 ' + fmtAgo(d.last_lap_seconds_ago);

    // 퍼센트 막대는 만들지 않는다 — 대기목록과 바퀴대상의 단위가 달라 정확한
    // 진행률을 낼 수 없다(설계서 §4.4). 지어내지 않는다.
    $state.innerHTML = d.auto_enabled
      ? '<div style="font-size:12px;color:var(--n500)">지금 대기</div>'
        + '<div style="font-size:20px;font-weight:800">' + d.waiting
        + '<span style="font-size:12px;font-weight:500;color:var(--n500)"> 건</span></div>'
        + '<div style="font-size:12px;color:var(--n500);margin-top:6px">오늘 ' + laps + '바퀴' + lastLap + '</div>'
      : '<div style="font-size:14px;font-weight:600">멈춰 있음</div>'
        + '<div style="font-size:12px;color:var(--n500);margin-top:4px">오늘 ' + laps + '바퀴' + lastLap + '</div>';

    $run.disabled = !online || busy;
    $auto.disabled = !online || busy;
    $auto.checked = !!d.auto_enabled;
    $help.textContent = online
      ? '크롤은 PC 크롬이 실행합니다. 이 화면은 시키기만 합니다.'
      : '크롤은 PC 크롬이 켜져 있어야 돕니다. 폰에서 PC를 켤 수는 없습니다.';
  }

  async function load() {
    try {
      render(await askServer('/mobile/crawl/api/status'));
    } catch (e) {
      if (e.kind === 'login') lock('다시 로그인해 주세요', '로그인이 풀렸습니다');
      else if (e.kind === 'forbidden') lock('권한이 없습니다', '크롤 리모컨은 관리자만 쓸 수 있습니다');
      else lock('연결이 안 됩니다', '잠시 후 다시 시도합니다');
    }
  }

  async function post(url, body) {
    busy = true; $run.disabled = true; $auto.disabled = true;
    try {
      await askServer(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      });
    } catch (e) {
      /* 바로 아래 load() 가 상태를 다시 읽어 사용자에게 알린다 */
    } finally {
      busy = false;
      await load();
    }
  }

  $run.addEventListener('click', function () { post('/mobile/crawl/api/run-lap', {}); });
  $auto.addEventListener('change', function () { post('/mobile/crawl/api/auto', { enabled: $auto.checked }); });

  load();
  setInterval(load, 10000);
})();
</script>
{% endblock %}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/templates/mobile/crawl.html 프로그램/_시스템/tests/mobile/test_shell_pages.py && git commit -m "feat(mobile): 크롤 리모컨 화면 — PC 꺼짐이면 버튼 비활성, 초 단위 표시, 인증 HTML 대응"
```

---

## Task 4: "전체" 메뉴 — PC와 같은 원천

**왜:** 폰 메뉴를 따로 정의하면, 앞으로 화면을 새로 만들 때 PC 메뉴에만 넣고 폰엔 빼먹는다. 이 프로젝트엔 그 실제 사고 기록이 있다.

**Files:**
- Modify: `webapp/routes/mobile.py` (`/menu` 라우트 추가)
- Create: `webapp/templates/mobile/menu.html`
- Test: `tests/mobile/test_menu_single_source.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/mobile/test_menu_single_source.py`:

```python
# -*- coding: utf-8 -*-
"""폰 '전체' 메뉴는 PC 메뉴와 같은 원천을 쓴다.

따로 정의하면 새 화면을 만들 때 한쪽에만 넣고 다른 쪽엔 빼먹는다.
이 프로젝트엔 '만든 화면을 메뉴에 안 넣어 두 달간 주소를 직접 쳐야 했던' 기록이 있다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    # 🔴 /mobile/* 라우트는 app.py 의 ENVIRONMENT 게이트 안에서만 등록된다.
    #   pytest 에선 이 값이 없어 라우트가 0개 → 안 넣으면 전부 404 로 실패한다.
    monkeypatch.setenv('ENVIRONMENT', 'team-share-dev')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _all_urls(layout):
    urls = [it.get('url') for it in layout.get('standalone', [])]
    for st in layout.get('stages', []):
        urls += [it.get('url') for it in st.get('items', [])]
    return [u for u in urls if u]


def test_PC_메뉴의_모든_항목이_폰_메뉴에도_있다(client):
    from webapp.routes.api_sidebar import get_layout_for_template
    html = client.get('/mobile/menu').get_data(as_text=True)
    missing = [u for u in _all_urls(get_layout_for_template()) if u not in html]
    assert not missing, f'폰 메뉴에서 빠진 항목: {missing}'


def test_메뉴는_하드코딩된_목록을_쓰지_않는다():
    """템플릿에 메뉴 이름을 직접 적어두면 원천이 둘로 갈라진다."""
    from pathlib import Path
    import config
    tpl = Path(config.PROJECT_ROOT) / 'webapp' / 'templates' / 'mobile' / 'menu.html'
    src = tpl.read_text(encoding='utf-8')
    assert 'layout' in src, '레이아웃 원천을 안 쓰고 있다'
    for hardcoded in ('모음전 상품관리', '주문 내역', '마진 계산기'):
        assert hardcoded not in src, f'메뉴 이름을 템플릿에 박아뒀다: {hardcoded}'


def test_로그아웃이_메뉴에_있다(client):
    html = client.get('/mobile/menu').get_data(as_text=True)
    assert '/auth/logout' in html
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_menu_single_source.py -v`
Expected: FAIL — 404

- [ ] **Step 3: 라우트를 더한다**

`webapp/routes/mobile.py` 의 `inventory_list()` (66행 부근) **다음**에 추가:

```python
@bp.route("/menu")
def menu():
    """'전체' — PC 상단 메뉴와 같은 원천(sidebar_layout)을 읽어 목록으로 편다.

    폰 전용 메뉴를 따로 정의하지 않는다. 새 화면을 만들 때 한쪽에만 넣고
    다른 쪽엔 빼먹는 사고를 구조적으로 막기 위해서다.
    """
    from webapp.routes.api_sidebar import get_layout_for_template
    return render_template("mobile/menu.html",
                           layout=get_layout_for_template(),
                           phone_native_urls=PHONE_NATIVE_URLS)


@bp.route("/install")
def install():
    return render_template("mobile/install.html")
```

같은 파일 상단(`bp = Blueprint(...)` 바로 아래)에 추가:

```python
# 폰 전용으로 이미 만들어진 화면들 — 메뉴에서 '폰 전용' 배지를 붙인다.
# 3단계에서 화면을 폰 전용으로 바꿀 때마다 여기에 URL 을 더한다.
PHONE_NATIVE_URLS = {
    "/mobile", "/mobile/", "/mobile/scan", "/mobile/inventory",
    "/mobile/scan-batch", "/mobile/crawl/",
}
```

- [ ] **Step 4: `webapp/templates/mobile/menu.html` 을 만든다**

```html
{% extends "mobile/_base.html" %}
{% block title %}전체{% endblock %}

{% block content %}
<div id="mobile-menu">
  {% if layout.standalone %}
  <div class="m-card" style="padding:4px 0;margin-bottom:12px">
    {% for it in layout.standalone %}
    <a href="{{ it.url }}" class="mm-row">
      <span class="mm-emoji">{{ it.emoji }}</span>
      <span class="mm-name">{{ it.name }}</span>
      {% if it.url in phone_native_urls %}<span class="mm-badge native">폰 전용</span>
      {% else %}<span class="mm-badge">PC 화면</span>{% endif %}
    </a>
    {% endfor %}
  </div>
  {% endif %}

  {% for st in layout.stages %}
  <div style="margin-bottom:14px">
    <div style="font-size:12px;font-weight:700;color:var(--n500);padding:0 6px 6px">
      {{ st.emoji }} {{ st.name }}
    </div>
    <div class="m-card" style="padding:4px 0">
      {% for it in st['items'] %}
      <a href="{{ it.url }}" class="mm-row">
        <span class="mm-emoji">{{ it.emoji }}</span>
        <span class="mm-name">{{ it.name }}</span>
        {% if it.url in phone_native_urls %}<span class="mm-badge native">폰 전용</span>
        {% else %}<span class="mm-badge">PC 화면</span>{% endif %}
      </a>
      {% endfor %}
    </div>
  </div>
  {% endfor %}

  <div class="m-card" style="padding:4px 0;margin-top:20px">
    <a href="/mobile/install" class="mm-row"><span class="mm-emoji">📲</span><span class="mm-name">앱 설치 방법</span></a>
    <a href="/auth/me" class="mm-row"><span class="mm-emoji">👤</span><span class="mm-name">내 계정</span></a>
    <a href="/auth/logout" class="mm-row"><span class="mm-emoji">🚪</span><span class="mm-name" style="color:#DC2626">로그아웃</span></a>
  </div>
</div>

<style>
  .mm-row { display:flex; align-items:center; gap:10px; padding:13px 14px;
            text-decoration:none; color:var(--n900,#191F28); min-height:48px;
            border-bottom:1px solid var(--n100,#F2F4F6); }
  .mm-row:last-child { border-bottom:0; }
  .mm-emoji { width:22px; text-align:center; font-size:16px; }
  .mm-name { flex:1; font-size:15px; font-weight:600; }
  .mm-badge { font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px;
              background:var(--n100,#F2F4F6); color:var(--n500,#8B95A1); white-space:nowrap; }
  .mm-badge.native { background:#DBEAFE; color:#1D4ED8; }
</style>
{% endblock %}
```

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_menu_single_source.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/routes/mobile.py 프로그램/_시스템/webapp/templates/mobile/menu.html 프로그램/_시스템/tests/mobile/test_menu_single_source.py && git commit -m "feat(mobile): 전체 메뉴 — PC 메뉴와 단일 원천 공유"
```

---

## Task 5: 설치 안내 화면

**Files:**
- Create: `webapp/templates/mobile/install.html` (라우트는 Task 4 Step 3 에서 이미 추가함)
- Test: `tests/mobile/test_shell_pages.py` (추가)

- [ ] **Step 1: 실패하는 테스트를 더한다**

`tests/mobile/test_shell_pages.py` 끝에 추가:

```python
def test_설치안내_화면이_열린다(client):
    r = client.get('/mobile/install')
    assert r.status_code == 200


def test_아이폰은_사파리로만_된다는_것이_적혀있다(client):
    """크롬으로 시도하면 '홈 화면에 추가'가 없어서 사장님이 헤맨다."""
    html = client.get('/mobile/install').get_data(as_text=True)
    assert '사파리' in html
    assert '홈 화면에 추가' in html


def test_안드로이드_안내도_같이_있다(client):
    html = client.get('/mobile/install').get_data(as_text=True)
    assert '안드로이드' in html
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: FAIL — `TemplateNotFound: mobile/install.html`

- [ ] **Step 3: `webapp/templates/mobile/install.html` 을 만든다**

```html
{% extends "mobile/_base.html" %}
{% block title %}앱 설치{% endblock %}

{% block content %}
<div id="mobile-install">
  <div id="mi-done" class="m-card" style="padding:14px;margin-bottom:14px;display:none;background:#F0FDF4;border:1px solid #BBF7D0">
    <b style="color:#15803D">✅ 이미 앱으로 실행 중입니다</b>
    <div style="font-size:12px;color:var(--n600);margin-top:4px">설치가 끝났습니다. 홈 화면 아이콘으로 열고 계십니다.</div>
  </div>

  <div class="m-card" style="padding:16px;margin-bottom:12px">
    <div style="font-weight:800;font-size:16px;margin-bottom:10px">🍎 아이폰</div>
    <ol style="margin:0;padding-left:18px;font-size:14px;line-height:2">
      <li><b style="color:#DC2626">사파리</b>로 <code>mou-m.com</code> 접속<br>
        <span style="font-size:12px;color:var(--n500)">크롬으로 열면 '홈 화면에 추가'가 없습니다</span></li>
      <li>아래 가운데 <b>공유 버튼</b>(⬆️) 누르기</li>
      <li>목록을 내려 <b>"홈 화면에 추가"</b> 누르기</li>
      <li>오른쪽 위 <b>"추가"</b> 누르면 끝</li>
    </ol>
  </div>

  <div class="m-card" style="padding:16px;margin-bottom:12px">
    <div style="font-weight:800;font-size:16px;margin-bottom:10px">🤖 안드로이드</div>
    <ol style="margin:0;padding-left:18px;font-size:14px;line-height:2">
      <li>크롬으로 <code>mou-m.com</code> 접속</li>
      <li>아래에 <b>"앱 설치"</b> 안내가 저절로 뜨면 누르기</li>
      <li>안 뜨면 오른쪽 위 <b>⋮</b> → <b>"앱 설치"</b> 또는 <b>"홈 화면에 추가"</b></li>
    </ol>
    <button id="mi-prompt" class="m-action-btn primary" style="width:100%;margin-top:12px;display:none">
      지금 설치하기
    </button>
  </div>

  <p style="font-size:12px;color:var(--n500);line-height:1.8;padding:0 4px">
    설치하면 주소창 없이 앱처럼 열립니다. 팀원에게는 <b>이 주소</b>만 알려주면 됩니다.
  </p>
</div>
{% endblock %}

{% block extra_script %}
<script>
(function () {
  const standalone = window.matchMedia('(display-mode: standalone)').matches
                  || window.navigator.standalone === true;
  if (standalone) document.getElementById('mi-done').style.display = 'block';

  // 안드로이드 크롬 — 설치 배너를 우리 버튼으로 띄운다
  let deferred = null;
  const $btn = document.getElementById('mi-prompt');
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferred = e;
    if (!standalone) $btn.style.display = 'flex';
  });
  $btn.addEventListener('click', async () => {
    if (!deferred) return;
    deferred.prompt();
    await deferred.userChoice;
    deferred = null;
    $btn.style.display = 'none';
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/templates/mobile/install.html 프로그램/_시스템/tests/mobile/test_shell_pages.py && git commit -m "feat(mobile): 설치 안내 화면 — 아이폰 사파리·안드로이드 배너"
```

---

## Task 6: 하단 탭 4칸 (폰 전용 화면)

> 🔴🔴 **2026-08-04 추가 — 탭 목록을 여기서 새로 정의하지 말 것.**
> Task 4 가 `webapp/routes/mobile_shell.py` 에 **`PHONE_NATIVE_ROWS`** 를 만들었다(폰 전용 화면의 단일 원천,
> 각 항목에 `admin_only` 표시 포함). 탭 4칸의 주소·이름을 `_tabbar.html` 이나
> `mobile_shell.js` 에 **따로 적으면, 이 계획이 내내 막아온 「두 곳에 적기」가 폰 안에서 재발한다.**
> — 3단계에서 화면이 늘 때 메뉴엔 뜨는데 탭엔 없거나, 그 반대가 된다.
>
> - 탭 항목은 `PHONE_NATIVE_ROWS` 에서 **골라 쓴다**(탭에 올릴 것만 표시하는 필드를 더하는 방식 권장).
> - Task 4 가 넣은 **역방향 시험**(등록된 `/mobile/*` 라우트가 전부 목록에 있나)과
>   충돌하지 않는지 확인할 것.
> - 방식은 구현자가 정하되 **왜 그렇게 했는지 보고**할 것.

> 🔴 **2026-08-04 결정 — '크롤' 탭은 admin 에게만 보인다.**
> Task 2 에서 `/mobile/crawl/*` 이 admin 전용이 됐다. 탭을 그대로 두면 member 는
> **누르는 순간 403** 을 만난다 — 이 프로젝트가 제일 나쁘게 치는 "눌러도 아무 일 없는 버튼"이다.
>
> - `_tabbar.html` 에서 크롤 칸을 `{% if %}` 로 감싸 admin 일 때만 렌더한다.
>   (역할 속성 이름은 `webapp/auth/permissions.py` · `models.py` 를 **읽고** 확인할 것 — 추측 금지)
> - member 에게는 **3칸**(홈·작업·전체)이 된다. 빈 자리를 남기지 말고 3등분한다.
> - `static/mobile_shell.js` 의 `TABS` 배열(Task 7)도 같은 규칙을 따라야 한다 —
>   거긴 서버 템플릿이 아니므로, admin 여부를 `<body data-admin="1">` 같은 속성으로
>   내려보내 JS 가 읽게 한다(방식은 구현자가 정하고 보고).
> - **탭이 admin 에게만 보인다는 시험**을 넣는다.


**Files:**
- Create: `webapp/templates/mobile/_tabbar.html`
- Create: `webapp/static/mobile_shell.css`
- Modify: `webapp/templates/mobile/_base.html` (2줄)
- Test: `tests/mobile/test_shell_pages.py` (추가)

- [ ] **Step 1: 실패하는 테스트를 더한다**

```python
@pytest.mark.parametrize('path', ['/mobile', '/mobile/scan', '/mobile/inventory',
                                  '/mobile/menu', '/mobile/crawl/', '/mobile/install'])
def test_모든_폰_화면에_하단_탭이_있다(client, path):
    """어디에 있든 홈·작업·크롤로 한 번에 돌아올 수 있어야 한다."""
    html = client.get(path).get_data(as_text=True)
    assert 'ms-tabbar' in html, f'{path} 에 하단 탭이 없다'
    for href in ('/mobile', '/mobile/crawl/', '/mobile/menu'):
        assert href in html, f'{path} 탭에 {href} 가 없다'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: FAIL — `assert 'ms-tabbar' in html`

- [ ] **Step 3: `webapp/templates/mobile/_tabbar.html` 을 만든다**

```html
{# 하단 탭 4칸 — 폰 전용 화면용. PC 화면 위에는 static/mobile_shell.js 가 같은 모양을 주입한다. #}
<nav class="ms-tabbar" role="navigation">
  <a href="/mobile" class="ms-tab{% if tab == 'home' %} on{% endif %}"><span>⌂</span>홈</a>
  <a href="/mobile/scan" class="ms-tab{% if tab == 'work' %} on{% endif %}"><span>📷</span>작업</a>
  <a href="/mobile/crawl/" class="ms-tab{% if tab == 'crawl' %} on{% endif %}"><span>🛒</span>크롤</a>
  <a href="/mobile/menu" class="ms-tab{% if tab == 'menu' %} on{% endif %}"><span>≡</span>전체</a>
</nav>
```

- [ ] **Step 4: `webapp/static/mobile_shell.css` 를 만든다**

```css
/* 모바일 앱 껍데기 — 폰 전용 화면과 PC 폴백 화면이 같은 모양을 쓴다.
   PC 화면에서는 mobile_shell.js 가 <html>에 .ms-on 을 붙일 때만 적용된다. */
:root { --ms-tabbar-h: 56px; }

.ms-tabbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 2147483000;
  display: flex; background: var(--surface, #fff);
  border-top: 1px solid var(--n200, #E5E8EB);
  padding-bottom: env(safe-area-inset-bottom);
  font-family: var(--font, 'Pretendard', -apple-system, sans-serif);
}
.ms-tab {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; min-height: var(--ms-tabbar-h); text-decoration: none;
  font-size: 11px; font-weight: 600; color: var(--n500, #8B95A1);
  -webkit-tap-highlight-color: transparent;
}
.ms-tab span { font-size: 18px; line-height: 1; }
.ms-tab.on { color: var(--blue, #3182F6); }

body { padding-bottom: calc(var(--ms-tabbar-h) + env(safe-area-inset-bottom)); }

/* ── 아래는 PC 폴백 화면에서만 쓰인다 (mobile_shell.js 가 붙임) ── */
.ms-on .ms-topbar {
  position: sticky; top: 0; z-index: 2147482000;
  display: flex; align-items: center; gap: 8px;
  background: var(--surface, #fff); border-bottom: 1px solid var(--n200, #E5E8EB);
  padding: 10px 12px; padding-top: calc(10px + env(safe-area-inset-top));
  font-family: var(--font, 'Pretendard', -apple-system, sans-serif);
}
.ms-on .ms-back {
  width: 34px; height: 34px; border: 0; background: transparent;
  font-size: 20px; line-height: 1; color: var(--n900, #191F28); cursor: pointer;
}
.ms-on .ms-title { font-size: 15px; font-weight: 700; flex: 1; overflow: hidden;
                   text-overflow: ellipsis; white-space: nowrap; }
.ms-on .ms-notice {
  background: #FFFBEB; border-bottom: 1px solid #FDE68A;
  color: #92400E; font-size: 11.5px; padding: 6px 12px; line-height: 1.5;
}
```

- [ ] **Step 5: `_base.html` 에 끼운다**

`webapp/templates/mobile/_base.html` 의 `<link rel="stylesheet" ... toss.css ...>` (16행) **다음 줄**에:

```html
  <link rel="stylesheet" href="{{ url_for('static', filename='mobile_shell.css') }}">
```

같은 파일 `</main>` 뒤, `{% block extra_script %}` **앞**에:

```html
  {% include 'mobile/_tabbar.html' %}
```

- [ ] **Step 6: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: PASS (11 passed)

- [ ] **Step 7: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/templates/mobile/_tabbar.html 프로그램/_시스템/webapp/templates/mobile/_base.html 프로그램/_시스템/webapp/static/mobile_shell.css 프로그램/_시스템/tests/mobile/test_shell_pages.py && git commit -m "feat(mobile): 하단 탭 4칸 — 홈/작업/크롤/전체"
```

---

## Task 7: PC 화면 위에 껍데기 주입

**왜:** PC 화면 157개를 고치지 않으면서 뒤로가기·탭·안내 띠를 얹는다. `base.html` 에는 **2줄만** 넣고, 실제 판단은 브라우저에서 한다 — 설치된 앱 + 좁은 화면일 때만 켜지므로 **PC 에서는 아무 일도 일어나지 않는다.**

**Files:**
- Create: `webapp/static/mobile_shell.js`
- Modify: `webapp/templates/base.html` (2줄)
- Test: `tests/mobile/test_shell_pages.py` (추가)

- [ ] **Step 1: 실패하는 테스트를 더한다**

```python
def test_PC_화면에도_껍데기_스크립트가_실려있다(client):
    """169개 화면 중 157개가 PC 화면이다 — 여기에 뒤로가기·탭이 붙어야 길을 안 잃는다."""
    html = client.get('/').get_data(as_text=True)
    assert 'mobile_shell.js' in html
    assert 'mobile_shell.css' in html


def test_껍데기는_설치된_앱_좁은화면에서만_켜진다():
    """PC 브라우저에서 켜지면 잘 돌아가던 화면을 망친다."""
    from pathlib import Path
    import config
    src = (Path(config.PROJECT_ROOT) / 'webapp' / 'static' / 'mobile_shell.js').read_text(encoding='utf-8')
    assert 'display-mode: standalone' in src, '설치 여부를 안 본다'
    assert 'max-width' in src or 'innerWidth' in src, '화면 폭을 안 본다'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: FAIL — `assert 'mobile_shell.js' in html`

- [ ] **Step 3: `webapp/static/mobile_shell.js` 를 만든다**

```javascript
/**
 * 모바일 앱 껍데기 — PC 화면(157개) 위에 뒤로가기·하단 탭·안내 띠를 얹는다.
 *
 * 🔴 PC 템플릿은 한 줄도 고치지 않는다. 이 파일이 브라우저에서 판단해 주입한다.
 *    켜지는 조건: 홈화면에 설치된 앱으로 실행 + 화면 폭 768px 이하.
 *    → 일반 PC 브라우저에서는 아무 일도 일어나지 않는다.
 *
 * 폰 전용 화면(/mobile/*)은 자기 탭(templates/mobile/_tabbar.html)을 이미 갖고 있으므로
 * 여기서 건드리지 않는다 — 탭이 두 개 생기면 안 된다.
 */
(function () {
  'use strict';

  var TABS = [
    { href: '/mobile',        icon: '\u2302',   label: '홈'   },
    { href: '/mobile/scan',   icon: '\uD83D\uDCF7', label: '작업' },
    { href: '/mobile/crawl/', icon: '\uD83D\uDED2', label: '크롤' },
    { href: '/mobile/menu',   icon: '\u2261',   label: '전체' }
  ];

  function isInstalledApp() {
    return window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
  }

  function isNarrow() {
    return window.matchMedia('(max-width: 768px)').matches;
  }

  function isPhoneNativePage() {
    return window.location.pathname.indexOf('/mobile') === 0;
  }

  function screenTitle() {
    var h1 = document.querySelector('h1');
    if (h1 && h1.textContent.trim()) return h1.textContent.trim();
    return (document.title || '모음전').split('·')[0].split('|')[0].trim();
  }

  function buildTopbar() {
    var bar = document.createElement('div');
    bar.className = 'ms-topbar';

    var back = document.createElement('button');
    back.className = 'ms-back';
    back.type = 'button';
    back.setAttribute('aria-label', '뒤로');
    back.textContent = '\u2039';
    back.addEventListener('click', function () {
      if (window.history.length > 1) window.history.back();
      else window.location.href = '/mobile';
    });

    var title = document.createElement('div');
    title.className = 'ms-title';
    title.textContent = screenTitle();

    bar.appendChild(back);
    bar.appendChild(title);
    return bar;
  }

  function buildNotice() {
    var n = document.createElement('div');
    n.className = 'ms-notice';
    n.textContent = 'ⓘ PC용 화면입니다 · 폰을 옆으로 눕히면 보기 편합니다';
    return n;
  }

  function buildTabbar() {
    var nav = document.createElement('nav');
    nav.className = 'ms-tabbar';
    TABS.forEach(function (t) {
      var a = document.createElement('a');
      a.className = 'ms-tab';
      a.href = t.href;
      var ic = document.createElement('span');
      ic.textContent = t.icon;
      a.appendChild(ic);
      a.appendChild(document.createTextNode(t.label));
      nav.appendChild(a);
    });
    return nav;
  }

  function mount() {
    if (document.querySelector('.ms-tabbar')) return;   // 두 번 붙이지 않는다
    document.documentElement.classList.add('ms-on');
    var body = document.body;
    body.insertBefore(buildNotice(), body.firstChild);
    body.insertBefore(buildTopbar(), body.firstChild);
    body.appendChild(buildTabbar());
  }

  function start() {
    if (!isInstalledApp() || !isNarrow() || isPhoneNativePage()) return;
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', mount);
    } else {
      mount();
    }
  }

  start();
})();
```

- [ ] **Step 4: `base.html` 에 2줄 넣는다**

`webapp/templates/base.html` 의 `<meta name="viewport" ...>` (11행) **다음**:

```html
  <link rel="stylesheet" href="{{ url_for('static', filename='mobile_shell.css') }}">
```

`</body>` **바로 앞**:

```html
  <script defer src="{{ url_for('static', filename='mobile_shell.js') }}"></script>
```

⚠️ `mobile_shell.css` 의 `body { padding-bottom: ... }` 는 `.ms-on` 밖에 있어 PC 에도 적용된다.
**아래처럼 `.ms-on` 안으로 옮긴다** (`mobile_shell.css` 수정):

```css
/* 폰 전용 화면(mobile/_base.html)은 항상, PC 폴백 화면은 껍데기가 켜졌을 때만 */
body.m-body, .ms-on body { padding-bottom: calc(var(--ms-tabbar-h) + env(safe-area-inset-bottom)); }
```

그리고 `webapp/templates/mobile/_base.html` 의 `<body class="{{ design_body_class|default('') }}">` 를
`<body class="m-body {{ design_body_class|default('') }}">` 로 바꾼다.

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: PASS (13 passed)

- [ ] **Step 6: PC 화면이 안 망가졌는지 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest tests/design/ tests/catalog/test_sidebar_inject.py -q
```
Expected: origin/main 기준선과 **같은 결과**. 새로 깨진 것이 있으면 `base.html` 변경을 되돌리고 원인을 찾는다.
(기준선 확인: `git stash && python -m pytest tests/design/ -q && git stash pop`)

- [ ] **Step 7: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/static/mobile_shell.js 프로그램/_시스템/webapp/static/mobile_shell.css 프로그램/_시스템/webapp/templates/base.html 프로그램/_시스템/webapp/templates/mobile/_base.html 프로그램/_시스템/tests/mobile/test_shell_pages.py && git commit -m "feat(mobile): PC 화면 위 껍데기 주입 — 설치된 앱+좁은화면에서만"
```

---

## Task 7B: 홈 화면 — 크롤 상태 한 줄 + 최근 본 화면

> 🔴 **2026-08-04 갱신 — 홈의 크롤 줄은 admin 에게만 보인다.**
> Task 2 에서 `/mobile/crawl/*` 이 **admin 전용**으로 잠겼다(PC 의 자동화 설정과 같은 정책).
> 홈은 모든 사용자가 보는 화면이므로, 크롤 줄을 그대로 두면 member 에게는
> **매번 403 을 받아 "불러오지 못했습니다"** 가 뜬다 — 고칠 수도 없는 오류 문구다.
>
> 따라서:
> - 크롤 줄은 **admin 일 때만 렌더**한다. 템플릿에서 `{% if current_user.is_authenticated and current_user.role == 'admin' %}` 로 감싼다
>   (실제 역할 속성 이름은 `webapp/auth/models.py` 를 읽고 확인할 것 — 추측 금지).
> - member 홈에는 그 줄이 아예 없다. 빈 자리도 남기지 않는다.
> - 크롤 줄의 `fetch` 도 Task 3 과 같은 **content-type 검사**를 쓴다(인증 실패가 HTML 로 온다).
> - 하단 탭의 '크롤' 칸도 member 에게 보일지 여기서 함께 판단해 보고할 것 —
>   보이는데 눌러서 403 이면 "눌러도 아무 일 없는 버튼"이다.


**왜:** 설계서 §4.1 이 홈 탭에 요구한 것 중 아직 없는 두 가지. (요약 대시보드 본체는 2단계)

**Files:**
- Modify: `webapp/templates/mobile/home.html`
- Modify: `webapp/static/mobile_shell.js` (최근 본 화면 기록)
- Test: `tests/mobile/test_shell_pages.py` (추가)

- [ ] **Step 1: 실패하는 테스트를 더한다**

```python
def test_홈에_크롤_상태_한_줄이_있다(client):
    html = client.get('/mobile').get_data(as_text=True)
    assert 'mh-crawl' in html, '홈에 크롤 상태 자리가 없다'
    assert '/mobile/crawl/api/status' in html, '홈이 크롤 상태를 안 물어본다'


def test_홈에_최근_본_화면_자리가_있다(client):
    html = client.get('/mobile').get_data(as_text=True)
    assert 'mh-recent-pages' in html


def test_최근_본_화면은_폰에만_저장한다():
    """어느 화면을 봤는지는 서버로 보내지 않는다."""
    from pathlib import Path
    import config
    src = (Path(config.PROJECT_ROOT) / 'webapp' / 'static' / 'mobile_shell.js').read_text(encoding='utf-8')
    assert 'localStorage' in src, '폰 저장을 안 쓴다'
    assert 'ms-recent' in src
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: FAIL (3 failed)

- [ ] **Step 3: `home.html` 맨 위(`{% block content %}` 바로 다음)에 크롤 줄을 넣는다**

```html
<a id="mh-crawl" href="/mobile/crawl/" class="m-card"
   style="display:flex;align-items:center;gap:8px;padding:12px 14px;margin-bottom:12px;text-decoration:none;color:inherit">
  <span id="mh-crawl-dot" style="width:8px;height:8px;border-radius:50%;background:#D1D5DB"></span>
  <span id="mh-crawl-text" style="flex:1;font-size:14px;font-weight:600">크롤 상태 확인 중...</span>
  <span style="font-size:12px;color:var(--n500)">›</span>
</a>
```

- [ ] **Step 4: `home.html` 의 `{% block extra_script %}` 안, `loadRecent();` **앞**에 넣는다**

```javascript
  // 크롤 상태 한 줄 — 자세한 건 크롤 탭에서 본다
  async function loadCrawlLine() {
    try {
      const r = await fetch('/mobile/crawl/api/status', { cache: 'no-store' });
      const d = await r.json();
      const on = d.pc && d.pc.online;
      document.getElementById('mh-crawl-dot').style.background = on ? '#22C55E' : '#9CA3AF';
      document.getElementById('mh-crawl-text').textContent = on
        ? (d.auto_enabled ? 'PC 연결됨 · 대기 ' + d.waiting + '건' : 'PC 연결됨 · 멈춰 있음')
        : 'PC 꺼져 있음';
    } catch (e) {
      document.getElementById('mh-crawl-text').textContent = '크롤 상태를 불러오지 못했습니다';
    }
  }
  loadCrawlLine();
  setInterval(loadCrawlLine, 30000);

  // 최근 본 화면 — 폰에만 저장(mobile_shell.js 가 기록)
  (function renderRecentPages() {
    var box = document.getElementById('mh-recent-pages');
    var items = [];
    try { items = JSON.parse(localStorage.getItem('ms-recent') || '[]'); } catch (e) {}
    if (!items.length) { box.style.display = 'none'; return; }
    box.innerHTML = items.slice(0, 5).map(function (it) {
      return '<a href="' + it.url + '" class="mm-row" style="display:flex;align-items:center;'
           + 'padding:11px 14px;text-decoration:none;color:inherit;font-size:14px;'
           + 'border-bottom:1px solid var(--n100,#F2F4F6)">' + it.title + '</a>';
    }).join('');
  })();
```

- [ ] **Step 5: `home.html` 의 "최근 활동" 블록 **앞**에 최근 본 화면 자리를 넣는다**

```html
<div style="margin-top:20px">
  <h2 style="font-size:14px;font-weight:600;color:var(--n700);margin:0 0 8px;padding:0 4px">최근 본 화면</h2>
  <div id="mh-recent-pages" class="m-card" style="padding:0"></div>
</div>
```

- [ ] **Step 6: `mobile_shell.js` 의 `mount()` 안, 맨 끝에 기록을 더한다**

```javascript
    rememberPage();
```

그리고 같은 파일 `mount()` **위**에 함수를 더한다:

```javascript
  /** 최근 본 화면을 폰에만 저장한다 — 서버로 보내지 않는다. 최대 5개. */
  function rememberPage() {
    try {
      var url = window.location.pathname + window.location.search;
      var item = { url: url, title: screenTitle() };
      var list = JSON.parse(localStorage.getItem('ms-recent') || '[]');
      list = list.filter(function (it) { return it.url !== url; });
      list.unshift(item);
      localStorage.setItem('ms-recent', JSON.stringify(list.slice(0, 5)));
    } catch (e) { /* 저장 실패는 무시 — 기능이 아니라 편의다 */ }
  }
```

- [ ] **Step 7: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_shell_pages.py -v`
Expected: PASS (16 passed)

- [ ] **Step 8: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/templates/mobile/home.html 프로그램/_시스템/webapp/static/mobile_shell.js 프로그램/_시스템/tests/mobile/test_shell_pages.py && git commit -m "feat(mobile): 홈에 크롤 상태 한 줄 + 최근 본 화면(폰 저장)"
```

---

## Task 8: 오프라인 정책 — 돈 데이터 캐시 금지 (A안)

**왜:** 지금 `sw.js` 는 끊기면 마지막에 본 화면을 대신 보여준다. 어제 매입가 22,000원·재고 12개가 **티 없이** 뜬다. 프로젝트 규칙 1번이 "가격·재고 오류 = 금전 손실".

**Files:**
- Modify: `webapp/static/sw.js`
- Test: `tests/js/test_sw_no_money_cache.js`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/js/test_sw_no_money_cache.js`:

```javascript
// 오프라인일 때 낡은 가격·재고를 보여주면 안 된다 (설계서 §4.7 A안).
// 앱 껍데기(/static/*)만 캐시하고, 나머지는 인터넷이 있을 때만 보여준다.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

const sw = fs.readFileSync(
  path.join(__dirname, '..', '..', 'webapp', 'static', 'sw.js'), 'utf8');

console.log('sw.js — 돈 데이터 캐시 금지:');

t('networkFirst(캐시 폴백) 가 사라졌다', function () {
  assert.ok(!/networkFirst/.test(sw), 'networkFirst 가 남아있다 — 낡은 값이 나온다');
});

t('런타임 캐시에 쓰는 코드가 없다', function () {
  assert.ok(!/RUNTIME_CACHE/.test(sw), 'RUNTIME_CACHE 가 남아있다');
});

t('cache.put 은 정적 캐시에만 쓴다', function () {
  const puts = sw.split('\n').filter(function (ln) {
    return /cache\.put\(/.test(ln.replace(/\/\/.*$/, ''));
  });
  assert.ok(puts.length <= 1, 'cache.put 이 ' + puts.length + '곳 — 정적 1곳만 허용');
});

t('캐시 버전이 2026-05-17 에서 올라갔다', function () {
  assert.ok(!/modeumjeon-v1-2026-05-17/.test(sw),
    '버전이 그대로면 이미 깔린 낡은 캐시가 안 지워진다');
});

t('오프라인이면 캐시가 아니라 오프라인 응답을 준다', function () {
  assert.ok(/offline/i.test(sw), '오프라인 안내가 없다');
});

console.log('\n결과: ' + pass + ' passed, ' + fail + ' failed');
if (fail) process.exit(1);
```

- [ ] **Step 2: 실패를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && node tests/js/test_sw_no_money_cache.js
```
Expected: FAIL — 5개 중 최소 4개 실패

- [ ] **Step 3: `webapp/static/sw.js` 를 통째로 교체한다**

```javascript
/**
 * Service Worker — 모음전 PWA
 *
 * 🔴 캐시 정책 (설계서 2026-08-03 §4.7 · 사장님 확정 A안)
 *   - 앱 껍데기(/static/*) 만 저장한다 → 앱이 빨리 뜬다.
 *   - 가격·재고·주문·정산 등 **모든 데이터는 저장하지 않는다.**
 *     인터넷이 끊기면 낡은 값을 보여주는 대신 "연결이 안 됩니다"라고 말한다.
 *
 *   왜: 폰은 지하철·엘리베이터·지하 창고에서 수시로 끊긴다. 예전 정책(Network First +
 *   캐시 폴백)은 어제 매입가·재고를 **티 없이** 화면에 띄웠다. 그 숫자로 판매가를 정하면
 *   그대로 금전 손실이다. 이 프로젝트 규칙 1번이 "가격·재고 오류 = 금전 손실".
 */
const CACHE_VERSION = 'modeumjeon-v2-2026-08-03';
const STATIC_CACHE = `${CACHE_VERSION}-static`;

// 앱 셸 — 이것만 저장한다
const STATIC_ASSETS = [
  '/static/toss.css',
  '/static/mobile_shell.css',
  '/static/mobile_shell.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
];

// ─── 설치 ───
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      // 하나가 없어도 설치가 통째로 실패하지 않게 개별 처리
      Promise.all(STATIC_ASSETS.map((url) =>
        cache.add(new Request(url, { cache: 'reload' })).catch((e) => {
          console.warn('[SW] 캐시 건너뜀:', url, e);
        })
      ))
    ).then(() => self.skipWaiting())
  );
});

// ─── 활성화 + 옛 캐시 정리 ───
// 이전 버전이 남긴 런타임 캐시(낡은 가격·재고)를 여기서 통째로 지운다.
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => {
            console.log('[SW] 옛 캐시 삭제:', k);
            return caches.delete(k);
          })
      )
    ).then(() => self.clients.claim())
  );
});

const OFFLINE_HTML =
  '<html><head><title>연결 안 됨</title><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
  '<body style="font-family:Pretendard,-apple-system,sans-serif;text-align:center;padding:64px 24px;color:#4E5968">' +
  '<div style="font-size:44px">📡</div>' +
  '<h1 style="font-size:19px;color:#191F28;margin:14px 0 8px">연결이 안 됩니다</h1>' +
  '<p style="font-size:14px;line-height:1.7;margin:0">가격·재고는 <b>낡은 값을 보여드리지 않습니다.</b><br>연결되면 바로 나옵니다.</p>' +
  '<button onclick="location.reload()" style="margin-top:22px;padding:12px 26px;border:0;border-radius:10px;background:#3182F6;color:#fff;font-size:15px;font-weight:700">다시 시도</button>' +
  '</body></html>';

// ─── 요청 가로채기 ───
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;                       // 쓰기는 항상 네트워크
  if (url.origin !== self.location.origin) return;            // 남의 도메인은 안 건드림

  // sw.js / manifest 는 네트워크 only (업데이트 보장)
  if (url.pathname === '/static/sw.js' || url.pathname === '/static/manifest.json') return;

  // 앱 껍데기 → 저장본 우선 (여기가 유일하게 저장하는 곳)
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(shellFirst(request));
    return;
  }

  // 그 외 전부(HTML·API·데이터) → 네트워크만. 저장하지 않는다.
  event.respondWith(networkOnly(request));
});

async function shellFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) {
      const cache = await caches.open(STATIC_CACHE);
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (e) {
    return new Response('offline', { status: 503 });
  }
}

async function networkOnly(request) {
  try {
    return await fetch(request);
  } catch (e) {
    if (request.mode === 'navigate') {
      return new Response(OFFLINE_HTML, {
        status: 503,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }
    return new Response(JSON.stringify({ ok: false, offline: true, error: '연결이 안 됩니다' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
  }
}

// ─── 푸시 알림 (선택 단계에서 사용) ───
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || '모음전', {
      body: data.body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: data.url,
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data || '/mobile'));
});
```

- [ ] **Step 4: 통과를 확인한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && node tests/js/test_sw_no_money_cache.js
```
Expected: `결과: 5 passed, 0 failed`

- [ ] **Step 5: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/webapp/static/sw.js 프로그램/_시스템/tests/js/test_sw_no_money_cache.js && git commit -m "fix(mobile): 오프라인에 낡은 가격·재고를 보여주지 않는다 — 껍데기만 캐시"
```

---

## Task 9: 로그인 유지 90일

**Files:**
- Modify: `app.py` (`REMEMBER_COOKIE_DURATION`)
- Modify: `webapp/auth/forms.py` (기본 체크)
- Test: `tests/mobile/test_login_persistence.py`

⚠️ 이 설정은 **PC 에도 같이 적용된다.** flask_login 기본값이 365일이므로 90일은 **줄이는** 쪽이라 보안상 더 낫다. 사장님께 이 사실을 보고할 것.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/mobile/test_login_persistence.py`:

```python
# -*- coding: utf-8 -*-
"""폰에서 앱을 껐다 켤 때마다 비밀번호를 다시 묻지 않게."""
from datetime import timedelta

import pytest


def test_로그인_유지_기간이_90일이다(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    assert flask_app.config.get('REMEMBER_COOKIE_DURATION') == timedelta(days=90)


def test_로그인_유지_체크가_기본으로_켜져있다():
    from webapp.auth.forms import LoginForm
    field = LoginForm.remember
    assert field.kwargs.get('default') is True, '기본이 꺼져 있으면 매번 다시 묻는다'
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/mobile/test_login_persistence.py -v`
Expected: FAIL (2 failed)

- [ ] **Step 3: 구현한다**

`app.py` 의 `app.config["SECRET_KEY"] = Config.SECRET_KEY` (24행) **다음**:

```python
    # [모바일 1단계] 폰에서 앱을 열 때마다 비밀번호를 다시 묻지 않게.
    #   flask_login 기본값은 365일 — 90일로 줄인다(PC 에도 같이 적용됨).
    from datetime import timedelta as _td
    app.config["REMEMBER_COOKIE_DURATION"] = _td(days=90)
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
```

`webapp/auth/forms.py` 의 `remember = BooleanField("로그인 유지")` 를:

```python
    remember = BooleanField("로그인 유지", default=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python -m pytest tests/mobile/test_login_persistence.py -v`
Expected: PASS (2 passed)

(`LoginForm.remember` 는 UnboundField 이고 `.kwargs == {'default': True}` 로 읽힌다 — 실측 확인함)

- [ ] **Step 5: 커밋**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git add 프로그램/_시스템/app.py 프로그램/_시스템/webapp/auth/forms.py 프로그램/_시스템/tests/mobile/test_login_persistence.py && git commit -m "feat(auth): 로그인 유지 기본 켜기 + 90일 (기존 flask_login 기본 365일에서 축소)"
```

---

## Task 10: 전체 회귀 + 라이브 배포 + 실제 폰 검증

**왜:** 이 프로젝트의 검증 기준은 **"화면에서 보이는 것"** 이다. 코드가 맞다는 것으로 완료를 주장하지 않는다.

- [ ] **Step 1: 전체 테스트를 돌려 기준선과 비교한다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && python -m pytest -q 2>&1 | tail -25
```
Expected: 새로 깨진 것 0건. (origin/main 에도 원래 실패하는 테스트가 있으므로 **개수가 아니라 "새로 깨진 것"** 으로 판단한다. 기준선: `git stash && python -m pytest -q | tail -5 && git stash pop`)

- [ ] **Step 2: JS 테스트를 돌린다**

Run:
```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp/프로그램/_시스템" && node tests/js/test_sw_no_money_cache.js && node tests/js/test_pass_done_once_per_lap.js
```
Expected: 둘 다 `0 failed`

- [ ] **Step 3: 로컬에서 눈으로 확인한다**

`.claude/launch.json` 에 항목이 없으면 만든 뒤 preview 를 띄우고, 폰 크기(375×812)로 줄여 확인한다:
- `/mobile` → 하단 탭 4칸이 보이는가
- `/mobile/menu` → 항목 수가 PC 상단 메뉴와 같은가
- `/mobile/crawl/` → PC 꺼짐 상태에서 버튼이 **비활성**인가
- `/orders/?tab=list` → (설치 안 한 브라우저라) 껍데기가 **안 붙는** 게 정상

- [ ] **Step 4: PR 을 올린다**

```bash
cd "C:/dev/모음전 프로젝트/_wt_mobileapp" && git push -u origin feature/mobile-app-shell
```
그다음 `gh pr create` 로 PR 생성. **머지 전에 사장님께 보고한다.**

- [ ] **Step 5: 머지·배포 후 라이브에서 확인한다**

```bash
export MSYS_NO_PATHCONV=1
for p in /mobile /mobile/menu /mobile/crawl/ /mobile/install /static/sw.js /static/mobile_shell.js; do
  echo "$p -> $(curl -s -o /dev/null -w '%{http_code}' https://mou-m.com$p)"
done
curl -s https://mou-m.com/static/sw.js | grep -c "modeumjeon-v2-2026-08-03"
```
Expected: 전부 200, 마지막 줄 `1` (새 캐시 버전이 라이브에 올라갔다)

- [ ] **Step 6: 실제 폰 2대로 검증한다 (사장님과 함께 — 대신 해줄 수 없는 부분)**

브라우저 개발자도구 시뮬레이션은 증거로 인정하지 않는다. 실제 기기에서:

| # | 확인할 것 | 아이폰 | 안드로이드 |
|---|---|:--:|:--:|
| 1 | `mou-m.com` → 홈 화면에 추가 → 아이콘 생김 | ☐ | ☐ |
| 2 | 아이콘으로 열면 **주소창이 없다** | ☐ | ☐ |
| 3 | 하단 탭 4칸이 보이고 노치·홈바에 안 가린다 | ☐ | ☐ |
| 4 | "전체"에 메뉴 25줄 + 폰 전용 구역이 나온다 (PC 상단 메뉴와 개수 대조) | ☐ | ☐ |
| 5 | PC 화면(예: 마진 계산기)을 열면 **앱 안에서** 열리고 뒤로가기·탭·노란 띠가 있다 | ☐ | ☐ |
| 6 | PC 크롬 **켠** 상태 → 크롤 탭에 🟢 PC 연결됨 | ☐ | ☐ |
| 7 | "지금 한 바퀴" 를 누르면 **PC 에서 실제로 크롤이 시작된다** | ☐ | ☐ |
| 8 | PC 크롬 **끈** 상태 → ⚪ PC 꺼져 있음 + 버튼 **비활성** | ☐ | ☐ |
| 9 | 비행기모드 → 재고 화면에서 **낡은 숫자가 아니라** "연결이 안 됩니다" | ☐ | ☐ |
| 10 | 앱 껐다 켜도 로그인을 다시 묻지 않는다 | ☐ | ☐ |

- [ ] **Step 7: 7섹션 보고서를 쓴다**

`/ui-verify` 형식. **9번(오프라인)과 7번(실제 크롤 시작)은 통과 여부를 반드시 명시한다** — 이 둘이 1단계의 핵심 약속이다.

---

## 완료 기준

- [ ] pytest 새로 깨진 것 0건 · JS 테스트 통과
- [ ] 라이브 `/mobile`·`/mobile/menu`·`/mobile/crawl/`·`/mobile/install` 200
- [ ] 실제 폰 2대 검증표 10항목 전부 ☑
- [ ] 사장님께 보고할 것 3건:
  1. **진행률 퍼센트 막대를 뺐다** — 분모·분자 단위가 달라 정확히 낼 수 없어서(설계서 §4.4 대로 지어내지 않음). 대신 "대기 N건 · 오늘 N바퀴"
  2. **로그인 유지 90일이 PC 에도 적용된다** (기존 flask_login 기본 365일에서 축소 — 보안상 더 나음)
  3. **PC 화면 157개는 여전히 PC 모양이다** — 3단계에서 순차 해소
