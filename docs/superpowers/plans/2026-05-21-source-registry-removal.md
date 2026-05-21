# 소싱처 사전 제거 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `source_registry` 테이블·`/source-registry` 페이지·"소싱처 사전" 메뉴를
제거하고, 소싱처 식별자를 builtin 키 기반 레지스트리 하나로 통일한다.

**Architecture:** `OptionSourceUrl.source_id`(정수 FK) → `source_key`(문자열) 로
스키마를 바꾸고, `SourceRegistry` 테이블 쿼리를 `source_registry.py` 모듈의
`get_all_sources()` 호출로 교체한다. 가격 매트릭스 화면·동작은 사용자 눈에 동일.

**Tech Stack:** Flask, SQLAlchemy, SQLite, Python 3.14, Playwright(검증)

**참조 설계:** `docs/superpowers/specs/2026-05-21-source-registry-removal-design.md`

---

## id → key 매핑 (전 작업 공통 상수)

```
1 = 르무통 공홈  → lemouton
2 = 스스 르무통  → ss_lemouton
3 = 무신사       → musinsa
4 = SSF          → ssf
5 = 롯데온       → lotteon
```

매핑은 `name` 기준으로 검증한다 (id 순서에 의존하지 않음).
근거: `scripts/migrate_pricing_v3.py` 의 `LEGACY_URL_MAP`.

## 작업 순서 원칙

신규 시스템(`C:\dev\모음전 프로젝트`)에서 전 작업을 먼저 완성·검증한 뒤,
동일 코드 변경을 기존 시스템에 복제한다 (Task 14). DB 마이그레이션은 각
시스템 DB 에 따로 실행한다. 코드·DB 모두 신규에서 검증 끝난 것만 기존에 적용.

---

## Task 1: DB 백업 + 마이그레이션 스크립트 작성

**Files:**
- Create: `프로그램/_시스템/scripts/migrate_drop_source_registry.py`

- [ ] **Step 1: 신규 DB 파일 경로 확인**

Run: `cd 프로그램/_시스템 && python -c "import config; print(config.DATABASE_URL)"`
Expected: `sqlite:///...` 경로 출력. 그 .db 파일을 백업 대상으로 기록.

- [ ] **Step 2: 마이그레이션 스크립트 작성**

```python
# 프로그램/_시스템/scripts/migrate_drop_source_registry.py
# -*- coding: utf-8 -*-
"""소싱처 사전 제거 마이그레이션.

option_source_urls.source_id(정수 FK→source_registry) → source_key(문자열).
source_registry 테이블 drop. 멱등(idempotent) — 이미 source_key 면 skip.
"""
import sys
import sqlalchemy as sa
from shared.db import SessionLocal

NAME_TO_KEY = {
    '르무통 공홈': 'lemouton',
    '스스 르무통': 'ss_lemouton',
    '스마트스토어 르무통': 'ss_lemouton',
    '무신사': 'musinsa',
    'SSF': 'ssf',
    'SSF샵': 'ssf',
    '롯데온': 'lotteon',
}


def _columns(conn, table):
    return [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))]


def run(dry_run: bool = False):
    s = SessionLocal()
    conn = s.connection()
    cols = _columns(conn, 'option_source_urls')
    if 'source_key' in cols and 'source_id' not in cols:
        print('이미 마이그레이션 완료 — skip')
        return
    if 'source_id' not in cols:
        print('ERROR: option_source_urls 에 source_id 없음', file=sys.stderr)
        sys.exit(1)

    # 1) id → key 매핑 (source_registry 의 실제 name 기준)
    id_to_key = {}
    for row in conn.execute(sa.text('SELECT id, name FROM source_registry')):
        sid, name = row[0], (row[1] or '').strip()
        key = NAME_TO_KEY.get(name)
        if not key:
            print(f'ERROR: 매핑 불가 소싱처 name={name!r} id={sid}', file=sys.stderr)
            sys.exit(1)
        id_to_key[sid] = key
    print(f'· id→key 매핑: {id_to_key}')

    # 2) 모든 option_source_urls.source_id 가 매핑 가능한지 검증
    osu_rows = list(conn.execute(sa.text(
        'SELECT id, source_id FROM option_source_urls')))
    before_cnt = len(osu_rows)
    for oid, sid in osu_rows:
        if sid not in id_to_key:
            print(f'ERROR: option_source_urls.id={oid} source_id={sid} 매핑 없음',
                  file=sys.stderr)
            sys.exit(1)
    print(f'· option_source_urls {before_cnt}행 — 전부 매핑 가능 확인')

    if dry_run:
        print('[DRY] 여기서 중단 — 실제 변경 없음')
        return

    # 3) 테이블 재생성 (SQLite 안전 패턴: new table → copy → drop → rename)
    conn.execute(sa.text('''
        CREATE TABLE option_source_urls_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_sku VARCHAR(128) NOT NULL,
            source_key VARCHAR(32) NOT NULL,
            product_url TEXT NOT NULL,
            price_cached INTEGER,
            stock_cached INTEGER,
            last_checked_at DATETIME,
            created_at DATETIME,
            updated_at DATETIME,
            FOREIGN KEY(canonical_sku) REFERENCES options(canonical_sku)
                ON DELETE CASCADE,
            CONSTRAINT uq_option_source_urls_v3 UNIQUE (canonical_sku, source_key)
        )
    '''))
    conn.execute(sa.text('''
        INSERT INTO option_source_urls_new
            (id, canonical_sku, source_key, product_url, price_cached,
             stock_cached, last_checked_at, created_at, updated_at)
        SELECT id, canonical_sku,
               CASE source_id
                   {cases}
               END,
               product_url, price_cached, stock_cached,
               last_checked_at, created_at, updated_at
        FROM option_source_urls
    '''.format(cases='\n'.join(
        f"WHEN {sid} THEN '{key}'" for sid, key in id_to_key.items()))))
    conn.execute(sa.text('DROP TABLE option_source_urls'))
    conn.execute(sa.text(
        'ALTER TABLE option_source_urls_new RENAME TO option_source_urls'))
    conn.execute(sa.text(
        'CREATE INDEX ix_option_source_urls_v3_sku '
        'ON option_source_urls (canonical_sku)'))
    conn.execute(sa.text(
        'CREATE INDEX ix_option_source_urls_v3_src '
        'ON option_source_urls (source_key)'))

    # 4) 검증 — 행 수 보존 + source_key 전부 유효
    after_cnt = conn.execute(sa.text(
        'SELECT COUNT(*) FROM option_source_urls')).scalar()
    bad = conn.execute(sa.text(
        "SELECT COUNT(*) FROM option_source_urls "
        "WHERE source_key NOT IN ('lemouton','ss_lemouton','musinsa','ssf','lotteon')"
    )).scalar()
    if after_cnt != before_cnt:
        print(f'ERROR: 행 수 불일치 {before_cnt} → {after_cnt}', file=sys.stderr)
        s.rollback(); sys.exit(1)
    if bad:
        print(f'ERROR: 잘못된 source_key {bad}건', file=sys.stderr)
        s.rollback(); sys.exit(1)

    # 5) source_registry 테이블 drop
    conn.execute(sa.text('DROP TABLE IF EXISTS source_registry'))

    s.commit()
    print(f'· 완료 — {after_cnt}행 이전, source_registry drop')


if __name__ == '__main__':
    run(dry_run='--dry-run' in sys.argv)
```

- [ ] **Step 3: 커밋**

```bash
git add 프로그램/_시스템/scripts/migrate_drop_source_registry.py
git commit -m "feat: 소싱처 사전 제거 DB 마이그레이션 스크립트"
```

---

## Task 2: 모델 변경 — OptionSourceUrl

**Files:**
- Modify: `프로그램/_시스템/lemouton/sourcing/models_pricing.py`

- [ ] **Step 1: `SourceRegistry` 클래스 삭제** (21-37행 블록 전체 제거, docstring 의 SourceRegistry 줄도 정리)

- [ ] **Step 2: `OptionSourceUrl` 의 `source_id` → `source_key` 교체**

`source_id` 컬럼 정의를 다음으로 교체:
```python
    source_key = Column(String(32), nullable=False)    # 'musinsa' 등
```
`__table_args__` 의 `UniqueConstraint("canonical_sku", "source_id", ...)` 를
`"canonical_sku", "source_key"` 로, `Index(... "source_id")` 를
`"source_key"` 로 변경.

- [ ] **Step 3: 커밋**

```bash
git add 프로그램/_시스템/lemouton/sourcing/models_pricing.py
git commit -m "refactor: OptionSourceUrl source_id→source_key, SourceRegistry 모델 제거"
```

---

## Task 3: api_pricing.py 매트릭스 빌드 repoint

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/api_pricing.py`

- [ ] **Step 1: import 변경** — `from lemouton.sourcing.models_pricing import (SourceRegistry, OptionSourceUrl, ...)` 에서 `SourceRegistry` 제거. 파일 상단에
`from lemouton.sourcing.source_registry import get_all_sources` 추가.

- [ ] **Step 2: 매트릭스 소싱처 목록 (158-164행)** 교체:
```python
        # 소싱처 — builtin 레지스트리
        sources = get_all_sources()
        source_dict = {src['key']: {'key': src['key'], 'name': src['label'],
                                    'main_url': ''} for src in sources}
```

- [ ] **Step 3: `sku_to_sources` dict (235-237행)** — `link.source_id` →
`link.source_key`, `source_dict.get(link.source_id, ...)` →
`source_dict.get(link.source_key, ...)`, 키 이름 `'source_id'` → `'source_key'`.

- [ ] **Step 4: `resolve_card_enabled` 호출 (224행)** — `source_id=link.source_id`
→ `source_key=link.source_key` (Task 6 에서 함수 시그니처도 변경).

- [ ] **Step 5: 엔드포인트 source_id → source_key** — `bulk_set_source_urls`(580),
`set_single_source_url`(636), `delete_source_link`(680) 의 요청 파라미터
`source_id`/`src_id` 를 `source_key` 로. `delete_source_link` 라우트의
`<int:src_id>` → `<src_key>`. `SourceRegistry` 조회(598행) 제거 →
`get_all_keys()` 로 유효성 검사. `_auto_crawl_after_url_save` 의 `source_id`
인자도 `source_key` 로.

- [ ] **Step 6: 나머지 source_id 참조** — 933행·1208행 부근 `OptionSourceUrl`
쿼리의 `source_id` → `source_key`. `grep -n source_id api_pricing.py` 로 잔여
0건 확인.

- [ ] **Step 7: 검증·커밋**

Run: `cd 프로그램/_시스템 && python -c "import webapp.routes.api_pricing"`
Expected: import 에러 없음.
```bash
git add 프로그램/_시스템/webapp/routes/api_pricing.py
git commit -m "refactor: api_pricing 소싱처 키 기반 전환"
```

---

## Task 4: bundles.py repoint

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/bundles.py`

- [ ] **Step 1: import (196행)** — `from lemouton.sourcing.models_pricing import
OptionSourceUrl, SourceRegistry` → `OptionSourceUrl` 만.

- [ ] **Step 2: 소싱처별 URL 카운트 (217-228행)** — `SourceRegistry` 조인을
제거하고 `source_key` 로 group by. `get_labels()` 로 key→표시명 변환:
```python
        from lemouton.sourcing.source_registry import get_labels
        labels = get_labels()
        rows = (
            s.query(OptionSourceUrl.source_key,
                    func.count(OptionSourceUrl.id).label('cnt'))
            .filter(OptionSourceUrl.canonical_sku.in_(sku_list))
            .group_by(OptionSourceUrl.source_key)
            .all()
        )
        src_dist = [{'name': labels.get(k, k), 'count': cnt} for k, cnt in rows]
```

- [ ] **Step 3: 무신사 매직넘버 (256, 272행)** — `OptionSourceUrl.source_id == 3`
→ `OptionSourceUrl.source_key == 'musinsa'`, `filter_by(source_id=3, ...)` →
`filter_by(source_key='musinsa', ...)`.

- [ ] **Step 4: 검증·커밋**

Run: `cd 프로그램/_시스템 && python -c "import webapp.routes.bundles"`
Expected: import 에러 없음.
```bash
git add 프로그램/_시스템/webapp/routes/bundles.py
git commit -m "refactor: bundles 소싱처 키 기반 전환"
```

---

## Task 5: api.py — 번들 url_* 전파 repoint

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/api.py`

- [ ] **Step 1: `_URL_FIELD_TO_SOURCE_NAME` (49-55행)** → `_URL_FIELD_TO_SOURCE_KEY`:
```python
_URL_FIELD_TO_SOURCE_KEY = {
    'url_lemouton': 'lemouton',
    'url_ss_lemouton': 'ss_lemouton',
    'url_musinsa': 'musinsa',
    'url_ssf': 'ssf',
    'url_lotteon': 'lotteon',
}
```

- [ ] **Step 2: `_propagate_bundle_urls_to_options` (58-118행)** — `SourceRegistry`
import·`src_by_name` 룩업 제거. `src_id = src_by_name.get(src_name)` 로직을
`src_key = _URL_FIELD_TO_SOURCE_KEY[url_field]` 직접 사용으로 교체.
`OptionSourceUrl(... source_id=src_id ...)` → `source_key=src_key`,
`filter_by(... source_id=src_id)` → `source_key=src_key`. `skipped_no_source`
카운트는 항상 0 이므로 제거 가능.

- [ ] **Step 3: 검증·커밋**

Run: `cd 프로그램/_시스템 && python -c "import webapp.routes.api"`
Expected: import 에러 없음.
```bash
git add 프로그램/_시스템/webapp/routes/api.py
git commit -m "refactor: api 번들 url 전파 소싱처 키 기반 전환"
```

---

## Task 6: home.py + api_benefits.py repoint

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/home.py`
- Modify: `프로그램/_시스템/webapp/routes/api_benefits.py`

- [ ] **Step 1: home.py (41행)** — `filter_by(source_id=3, product_url=sp.url)`
→ `filter_by(source_key='musinsa', product_url=sp.url)`.

- [ ] **Step 2: api_benefits.py `resolve_card_enabled`** — 함수 시그니처의
`source_id` 파라미터를 `source_key` 로, 본문의 `OptionSourceUrl` 쿼리(377-379행)
`source_id` 참조를 `source_key` 로. 호출처는 api_pricing.py Task 3 Step 4 에서
이미 맞춤.

- [ ] **Step 3: 검증·커밋**

Run: `cd 프로그램/_시스템 && python -c "import webapp.routes.home, webapp.routes.api_benefits"`
Expected: import 에러 없음.
```bash
git add 프로그램/_시스템/webapp/routes/home.py 프로그램/_시스템/webapp/routes/api_benefits.py
git commit -m "refactor: home·api_benefits 소싱처 키 기반 전환"
```

---

## Task 7: 파이프라인 스크립트 점검

**Files:**
- Modify (필요 시): `프로그램/_시스템/scripts/push_per_option_cheapest.py`,
  `프로그램/_시스템/scripts/run_full_pipeline.py`

- [ ] **Step 1: source_id 참조 확인**

Run: `cd 프로그램/_시스템 && grep -n "source_id" scripts/push_per_option_cheapest.py scripts/run_full_pipeline.py`
Expected: `OptionSourceUrl` 관련 `source_id` 참조가 있으면 `source_key` 로 수정.
없으면 (URL/sku 기준 조회만) 변경 불필요.

- [ ] **Step 2: 변경 시 커밋**

```bash
git add 프로그램/_시스템/scripts/push_per_option_cheapest.py 프로그램/_시스템/scripts/run_full_pipeline.py
git commit -m "refactor: 파이프라인 스크립트 소싱처 키 기반 전환"
```

---

## Task 8: 프론트엔드 — _matrix_v3.html repoint

**Files:**
- Modify: `프로그램/_시스템/webapp/templates/bundles/_matrix_v3.html`

- [ ] **Step 1: source_id 참조 전수 확인**

Run: `cd 프로그램/_시스템 && grep -n "source_id\|source-registry\|소싱처 사전" webapp/templates/bundles/_matrix_v3.html`

- [ ] **Step 2: JS 의 `source_id` → `source_key`** — 매트릭스 데이터 객체·
fetch body (`bulk_set_source_urls`/`set_single_source_url` 호출)·
`delete_source_link` URL 경로의 `source_id` 를 전부 `source_key` 로. 백엔드
계약(Task 3 Step 5)과 일치시킴.

- [ ] **Step 3: `/source-registry/api` fetch (5446행)** — 이 호출이 향하는
엔드포인트를 확인. `source_registry.py` 제거(Task 11) 후에도 동작해야 하면
api_pricing.py 의 소싱처 생성 엔드포인트로 연결. builtin 5개 고정이라 신규
소싱처 생성 UI 자체가 불필요하면 해당 "+추가" 경로 제거.

- [ ] **Step 4: UI 문구** — "소싱처 사전에서…" "소싱처 사전 비었음" 등(3736,
4129, 5389, 5391, 5452행) "소싱처" 로 정리.

- [ ] **Step 5: 커밋**

```bash
git add 프로그램/_시스템/webapp/templates/bundles/_matrix_v3.html
git commit -m "refactor: 가격 매트릭스 프론트 소싱처 키 기반 전환"
```

---

## Task 9: 소싱처 사전 라우트·블루프린트 제거

**Files:**
- Delete: `프로그램/_시스템/webapp/routes/source_registry.py`
- Delete: `프로그램/_시스템/webapp/templates/source_registry/list.html`
- Modify: `프로그램/_시스템/webapp/routes/__init__.py`

- [ ] **Step 1: 블루프린트 등록 제거** — `__init__.py` 23행
(`from webapp.routes.source_registry import bp as source_registry_bp`) 와
44행 (`app.register_blueprint(source_registry_bp)`) 삭제.

- [ ] **Step 2: 파일 삭제** — `source_registry.py`, `templates/source_registry/`
디렉터리.

- [ ] **Step 3: 잔여 참조 확인**

Run: `cd 프로그램/_시스템 && grep -rn "source_registry_bp\|routes.source_registry\|source_registry/list" webapp/`
Expected: 0건.

- [ ] **Step 4: 커밋**

```bash
git add -A 프로그램/_시스템/webapp/routes/ 프로그램/_시스템/webapp/templates/
git commit -m "refactor: 소싱처 사전 라우트·페이지 제거"
```

---

## Task 10: 사이드바 메뉴 제거

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/api_sidebar.py`
- Modify: `프로그램/_시스템/data/sidebar_layout.json`

- [ ] **Step 1: `_default_layout()` (api_sidebar.py 37-38행)** — `i_src_dict`
("소싱처 사전") 항목 dict 삭제.

- [ ] **Step 2: `sidebar_layout.json`** — `active_key: "source_registry"` /
`url: "/source-registry"` 항목을 stages 배열에서 삭제. JSON 유효성 유지.

- [ ] **Step 3: 검증·커밋**

Run: `cd 프로그램/_시스템 && python -c "import json; json.load(open('data/sidebar_layout.json', encoding='utf-8')); print('json ok')"`
Expected: `json ok`
```bash
git add 프로그램/_시스템/webapp/routes/api_sidebar.py 프로그램/_시스템/data/sidebar_layout.json
git commit -m "refactor: 사이드바에서 소싱처 사전 메뉴 제거"
```

---

## Task 11: migrate_pricing_v3.py obsolete 처리

**Files:**
- Modify: `프로그램/_시스템/scripts/migrate_pricing_v3.py`

- [ ] **Step 1:** `SourceRegistry` import·`ensure_source_registry` 등 의존부가
`source_registry` 테이블이 사라진 환경에서 실행 시 에러나므로, 파일 상단
docstring 에 "OBSOLETE — 소싱처 사전 제거(2026-05-21)로 무효" 명시하고,
`if __name__ == '__main__':` 진입부에서 `print` 후 `sys.exit(0)` 으로 가드.

- [ ] **Step 2: 커밋**

```bash
git add 프로그램/_시스템/scripts/migrate_pricing_v3.py
git commit -m "chore: migrate_pricing_v3 obsolete 처리"
```

---

## Task 12: 신규 DB 마이그레이션 실행 + 검증

- [ ] **Step 1: 신규 DB 백업**

Run: Task 1 Step 1 에서 확인한 .db 파일을 `<db>.bak.20260521` 로 복사.

- [ ] **Step 2: dry-run**

Run: `cd 프로그램/_시스템 && python scripts/migrate_drop_source_registry.py --dry-run`
Expected: `id→key 매핑` 출력 + `38행 — 전부 매핑 가능 확인` + `[DRY] 중단`.

- [ ] **Step 3: 실제 실행**

Run: `cd 프로그램/_시스템 && python scripts/migrate_drop_source_registry.py`
Expected: `완료 — 38행 이전, source_registry drop`.

- [ ] **Step 4: 검증**

Run:
```
cd 프로그램/_시스템 && python -c "
import sqlalchemy as sa
from shared.db import SessionLocal
s=SessionLocal()
print('osu rows:', s.execute(sa.text('SELECT COUNT(*) FROM option_source_urls')).scalar())
print('keys:', s.execute(sa.text('SELECT DISTINCT source_key FROM option_source_urls')).fetchall())
print('source_registry:', s.execute(sa.text(\"SELECT name FROM sqlite_master WHERE type='table' AND name='source_registry'\")).fetchall())
"
```
Expected: `osu rows: 38`, keys 가 5개 키 부분집합, `source_registry: []` (테이블 없음).

---

## Task 13: 신규 시스템 브라우저 검증

- [ ] **Step 1: 데모 서버 재시작** — preview_stop 후 preview_start
(`modeumjeon-regtab-demo`, 포트 5099).

- [ ] **Step 2: 가격 매트릭스 페이지** — 매트릭스가 있는 모음전 페이지 접속,
소싱처 5개 컬럼·가격·재고가 마이그레이션 전과 동일하게 표시되는지 확인
(preview_snapshot / 스크린샷).

- [ ] **Step 3: 사이드바** — "소싱처 사전" 메뉴 사라짐, "소싱처 운영센터"·
"소싱처 계정" 등 나머지 정상.

- [ ] **Step 4: 회귀** — 홈 화면, 모음전 상품관리 페이지 500 에러 없음
(preview_console_logs / preview_logs error 확인).

- [ ] **Step 5: `/source-registry` 접속 시 404** 확인.

---

## Task 14: 기존 시스템 반영 + 양쪽 배포

- [ ] **Step 1:** Task 2~11 의 코드 변경을 기존 시스템
(`C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템`)
의 동일 파일에 복제. 마이그레이션 스크립트도 복사.

- [ ] **Step 2:** 기존 DB 백업 후
`python scripts/migrate_drop_source_registry.py` 실행 (기존 DB 기준).
dry-run 먼저.

- [ ] **Step 3:** `cd C:\dev\모음전 프로젝트 && python 프로그램/sync.py` 실행 —
기존→신규 동기화. 신규가 이미 동일하므로 diff 없음 확인 (divergence 점검).

- [ ] **Step 4:** 양쪽 라이브 서버 재시작.

- [ ] **Step 5:** 기존 시스템에서도 가격 매트릭스·사이드바 검증 (Task 13 반복).

---

## 자체 리뷰 메모

- 스펙 §2 마이그레이션 → Task 1, 12, 14. §3 코드 repoint → Task 3~8.
  §4 제거 → Task 9, 10, 11. §5 양쪽 반영 → Task 14. §6 검증 → Task 12, 13.
- 리스크: Task 8 (_matrix_v3.html 5000줄) 이 가장 큼 — source_id 전수 grep 필수.
- Task 14 는 기존(운영 중) 시스템 수정 — DB 백업·dry-run 게이트 필수.
