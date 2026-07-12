# Task B — classifier.py 무수정 이식 (원본 1:1 클론 착수)

> **인수인계 정본:** `docs/superpowers/plans/2026-07-12-원본-마진계산기-1대1-클론-인수인계.md`
> **브랜치:** feature/margin-calculator (worktree `C:\dev\_wt_margin_calc`)
> **모든 명령:** `프로그램\_시스템` 에서 · `export PYTHONIOENCODING=utf-8` 먼저 · node v24
> **방식:** 서브에이전트 구동 + 태스크마다 2단 리뷰(스펙→품질) + 각 태스크 TDD + "원본 그대로"=동치 가드

---

## 전체 시퀀스 (B→검증) — 이 플랜은 B 상세, 나머지는 개요

| 태스크 | 내용 | 상태 |
|-------|------|------|
| **B** | classifier.py 무수정 이식 + verbatim 가드 + Plan A `_bucket` 실 classifier 재지정 | ← 이번 |
| 2(계약) | `/api/margin/analyze` 가 원본 `analysisData` 형태 반환 (classified 포함) + 계약 테스트 | 다음 |
| C | 원본 프런트 전체 이식 (index.html render+CSS+JS, ★`_getRowsByCardFilter_internal` 체인 그대로) | |
| D | 설정 5종 (DB 테이블 ①②③④ + ⑤ 기존 SourcingCredential 연결) | |
| E | 소싱처 자동확인 (서버 Playwright 제거 → 로컬 크롬확장 경유) | |
| 검증 | 실브라우저 ↔ 원본 스크린샷 탭별 1:1 (정상11·발송대기60·까대기91 카드 숫자·컬럼·색) | |

---

## Task B 상세

### 사실 관계 (코드 실측 완료)
- 원본 `C:\dev\대량등록 마진계산기\modules\classifier.py` = 565줄. 순수 pandas + config 상수 의존.
- 필요한 config 상수 18종 **전부** `lemouton/margin/config.py` 에 이미 존재 (golden test 통과분).
- 입력 공급자 `matcher.match_for_classifier`(matcher.py:374) → `{matched, mango_unmatched, shopmine_only}`.
  - matched 행에 `샵마인_{col}`·`샵마인_매칭`·`샵마인_정상건존재`·`샵마인_모든주문상태` 부착 (실측 442~446행).
  - classifier 가 읽는 `샵마인_주문상태`·`샵마인_매칭`·`샵마인_정상건존재` 전부 이 필드와 정합.
- **유일한 수정 = import 줄 1개**: `from config import (` → `from lemouton.margin.config import (`. 본문 나머지 바이트 동일.

### TDD 계획
- **RED** `tests/margin/test_classifier_verbatim.py` (matcher_verbatim 패턴 그대로):
  1. `test_public_api_present` — `classify`, `_determine_purchase_status`, `_determine_delivery_status`,
     `_determine_settlement_status`, `_assign_category`, `_cross_validate`, `_classify_shopmine_only` 존재.
  2. 기능 테스트 — 3축 상태기계 대표 케이스:
     - (O,O,O)→1-1 정상거래 / (O,O,X_취소)→1-4 / 발송대기(결제완료)→1-11 / 까대기(해외현지배송중)→1-12
     - 미매칭→X_미매칭 / shopmine_only 취소→5-7 / 철회복구→5-6.
  3. `test_source_is_verbatim_except_import_lines` — 원본과 diff 가 `config import` 줄뿐 (docstring 포함 전부 동일). 원본 부재 PC 는 `pytest.skip`.
  4. `test_original_path_guard_is_skippable` — 부재 시 error 아닌 skip 보장.
- **GREEN** `lemouton/margin/classifier.py` = 원본 복사 + import 줄만 재작성. `__init__.py` 필요 시 export.
- **검증** `pytest tests/margin/test_classifier_verbatim.py -v` + 전체 `pytest tests/margin/` 회귀 무결.

### Plan A 이월 (같은 태스크)
- `tests/margin/test_status_to_shopmine.py` 의 `_bucket` **프록시 → 실 classifier `_determine_settlement_status`** 로 재지정.
- 철회→취소완료·회수확정→반품완료 raw-누출 정밀 재검증 (현재 프록시 과매칭으로 약함).

### 2단 리뷰
1. **스펙 리뷰** — 이식본이 인수인계 §5·§7·본 플랜 계약(입력 필드·상세코드·verbatim)을 만족하는가.
2. **품질 리뷰** — code-reviewer 서브에이전트 (동치 가드가 진짜 동치를 증명하는지, skip 가드, 회귀).

### 완료 기준
- 신규 4테스트 통과 + `tests/margin/` 전체 통과 + verbatim 가드가 원본과 바이트 동치 증명 + Plan A `_bucket` 실 classifier 화.

---

## Task 2 (다음) — 데이터 계약 사전조사 결과 (원본 app.py /api/analyze 1313~1459 실측)

원본 프런트가 읽는 `analysisData` = `/api/analyze` 가 반환하는 단일 객체. 키:
- `matched` (list) · `unmatched_buy` (list — **raw 매입흔적 보강행 추가**: classified 미포함 + `_has_trace` 인 buy_df 행을 더망고만으로 합침, app.py 1336~1387) · `unmatched_sell`
- `classified` (list) = **`classifier.classify()` 결과** ← Task B 이식본이 채운다
- `blackspot_summary` = classifier `summary`
- `summary` = `_aggregate` 결과 + **`_compute_card_counts(matched, source='matched')` 로 card_* 덮어쓰기**(방안 A, 전체내역과 100% 일치) + `mango_total`(raw 행수)·`mango_with_order_no`(buy_valid)·`mango_with_trace`(=card_all) + `_issue_applied`(선택)
- `missing_order_no` = buy_missing_df records
- 그 외 `_aggregate` 의 모든 탭 집계(daily/monthly/brand/price_range/product/market/sourcing/card_*)

**Task 2 이식 대상 함수(원본 app.py):** `_run_full_pipeline`(matcher.match_for_classifier→classifier.classify 연결)·`_aggregate`·`_compute_card_counts`·buy_valid_df/buy_missing_df 산출. 현 worktree `api_margin.analyze` 는 `{**out, **agg}` 만 반환 → `classified`·`blackspot_summary`·card_* 미포함. **계약 테스트**로 원본 키 전량 고정.
**주의:** `_card_keywords`(카드 키워드) 주입은 Task D(설정) 소관 — Task 2 는 분류/집계 계약까지.

### Task 2 이월(follow-up) — 품질리뷰 지적 (비차단)
- **[아키텍처, 이월]** 현재 분류 호출(`split_by_site_order_no→match_for_classifier→classify`)이 라우트의 `_augment_blackspot` 안에 있다. 원본은 `_run_full_pipeline` 에서 매칭+분류를 함께 했다. `pipeline.run` 이 `classified`/`blackspot_summary` 를 직접 반환하도록 옮기면 응집도↑(라우트는 계약 글루만). 단 keeper `pipeline.run` 계약 변경 = 기존 172테스트 영향 → **전용 리팩터로 분리**(Task C 착수 전 또는 별도). 지금은 안 건드림.
- **[완료]** 1:1 가드(원본 1340 `and classified`) 추가 / inert `counter` 주석 명시.

---

## Task C — 원본 프런트 전량 이식 (사용자 확정 2026-07-12)

**확정 결정:** ① **iframe 임베드** (원본 index.html 을 bare SAMEORIGIN 라우트로 거의 그대로 서빙 → `/orders?tab=margin` 에서 iframe). ② **매입 엑셀 업로드 트리거 유지** (원본 UX 그대로, 서버가 매출은 마켓 API 로 = Task 2 /api/margin/upload+analyze 와 일치).

**원본 index.html = 10,819줄:** CSS 7~840 · margin_rules.js(외부, 이식됨) 841 · 거대 inline `<script>` 954~10769(≈9,800줄). **iframe 이므로 렌더 함수·CSS·`_getRowsByCardFilter_internal` 전부 verbatim** — 손대는 곳만:

**엔드포인트 재배선 지도(원본 fetch → 모음전):**
- 지금 배선(C): `/api/upload`→`/api/margin/upload`(+`/upload-shopmine` 선택) · `/api/analyze`→`/api/margin/analyze` · `/api/download`→`/api/margin/export`
- 우아한 no-op(C, 크래시 금지): `/api/open-profile`·`/api/data-files`·`/api/cookie-status/all`·`/api/load-data-file`·`/api/check-login`·`/api/open-order`·`/api/report-misjudgment`·`/api/issue_upload` (단독앱 로컬파일/쿠키/프로필 기능 — 모음전 무관)
- Task D 이월: `/api/keywords`·`/api/settings` (설정 5종) — 단 C 에서 카드키워드 **기본값 주입**해 카드 렌더 (`_getCardKeywords` 5698)
- Task E 이월: `/api/check-sourcing`·`/api/sourcing-sites`·`/api/blackspot/fetch_order_no` (서버 Playwright→로컬 확장)
- 후속: `/api/blackspot/manual_order_no`

**C 서브태스크:** C1+C2 = bare 라우트에 원본 페이지 verbatim 서빙 + 위 재배선(업로드→분석→전탭 렌더 실동작) → C3 = `/orders?tab=margin` iframe 임베드(548줄 재구현본 `_margin.html`/`margin_app.js`/`margin_render.js`/`margin.css` 폐기, `margin_rules.js` 유지) → C4 = 원본 스크린샷 탭별 1:1 검증(★사용자 제공 블랙스팟 3장 필요).

**C1+C2 완료(커밋 `6c9ee491`, 185 passed, verbatim 9심 diff·스펙✅·품질Approve).** bare 라우트 `GET /orders/margin-embed`(SAMEORIGIN, base.html 미상속). 리뷰 후속 = 빌드스크립트 in-repo 커밋 + `test_margin_embed_verbatim.py` 동치 가드(진행중).

### C3/C4 이월 (C1+C2 구현자 자진 신고 — 설계상 이월)
- **[C3 필수]** `updateAnalyzeBtn()` 이 `buyLoaded && sellLoaded` 게이트 → 모음전은 매출=마켓 API(업로드 아님)라 **매입만 업로드해도 "분석 시작" 활성화**되도록 C3에서 수정(현재 sell/샵마인 업로드 안 하면 버튼 비활성 위험). iframe 배선과 함께 처리.
- **[export 후속]** `/api/margin/export` 는 저장 payload 만 내보냄 → 원본의 화면상 제외(excluded_ids)·수정 matched·price_ranges 미반영. 실계약 갭.
- **[Task D 연동]** analyze 가 `price_ranges` 무시(DEFAULT 사용) → 금액대별 탭 사용자 커스텀 미반영. 설정(D)과 함께.
- **[저impact]** 매입 다중파일 업로드는 첫 파일만 읽음(더망고 매입은 보통 단일).

---

## Task D — 설정 5종 (팀 DB / 기존 SourcingCredential 연결)

원본 설정 저장(실측): ①카드키워드=`/api/keywords` GET/POST(card_keywords.json, 구조 `{cards:{name:{memo[],mg[],mk_sync[],sub_rtn[],sub_ex[],label}}}`) · ②③고마진·효율1=localStorage `margin_user_settings` · ④금액대=in-memory `priceRanges`(휘발) · ⑤소싱처계정=`/api/settings` GET/POST(settings.json 평문, `{accounts:{site:[{id,pw}]}}`, PW 마스킹)+`/api/sourcing-sites`.

**D 서브태스크:**
- **D1** ① 카드키워드 → 팀 DB 테이블 + 모음전 `/api/keywords` GET/POST 구현. **페이지 세임 불필요**(iframe 페이지가 이미 /api/keywords 호출; C1+C2에서 기본값 렌더 확인). store 패턴=`lemouton/margin/store.py`+`shared/db.py SessionLocal`. Alembic 없음→create_all.
- **D2** ②③④ 사용자설정(고마진·효율1·금액대) → **원본 그대로 localStorage 유지**(사용자 2026-07-12 못박음: 원본 따라가라). 원본이 `margin_user_settings`·`priceRanges` 를 브라우저 localStorage 로 저장하므로 모음전도 동일 → **verbatim 이식(C1+C2)으로 이미 동작. 추가 작업·팀DB·페이지 세임 없음.** [[feedback_replicate_original_dont_ask_approach]]
- **D3** ⑤ 소싱처계정 → 모음전 기존 `SourcingCredential` DB 연결(§6: 모델 `lemouton/sourcing/models_v2.py:129`, 스토어 `lemouton/auth/sourcing_credentials.py:161`, 라우트 `accounts.py:1612/1695`). **평문 settings.json 재이식 금지.** `/api/settings`·`/api/sourcing-sites` 를 이 DB에 매핑. Task E(소싱처 자동확인)와 인접.

---

## Task E — 소싱처 자동확인 (서버 Playwright → 로컬 크롬확장)

**원본:** `/api/check-sourcing`·`/api/sourcing-login`·`/api/blackspot/fetch_order_no` 전부 `@require_local` + Playwright(원본은 로컬앱). 모음전=서버앱 → crawl=local 원칙상 **서버 Playwright 금지**, 로컬 크롬확장(moum-crawler) 경유.

**아키텍처:**
- 브리지 `webapp/static/ext_bridge.js` = `window.MoumExt.send(type,payload)` ↔ 확장 `{__moum:"page",type,payload,reqId}` postMessage, 응답 `{__moum:"ext",reqId,ok,resp,error}`. 확장 감지 = `documentElement[data-moum-ext]`.
- **신규 메시지 타입** `sourcing.check-order` {url, account_id, site_name} → 확장이 로컬 브라우저로 소싱처 주문페이지 열어 주문상태 추출 → resp. (원본 `check_order_sync` 등가.)
- **iframe 경계:** 마진 페이지는 iframe, MoumExt 는 부모. → (a) content_mou 가 all_frames 면 iframe 에 ext_bridge 직접 로드(세임), (b) 아니면 부모↔iframe postMessage 릴레이. 구현 전 manifest 확인 필수.
- **UI 계약 §5 유지:** fetch_order_no 응답 `{success, order_no, site_name, source, logs[], error, matched_count, missing_count}`.

**★재발견(코드 실측):** `sourcing_parser.fetch_order_no` = **순수 파싱(브라우저X)** — 메모 텍스트 regex + URL 템플릿 역매칭으로 주문번호 추출. 핸드오프 §5의 "fetch_order_no→Playwright→확장"은 혼동. 따라서 fetch_order_no 는 **확장 불필요·서버 검증가능**. 확장 필요한 건 **check-sourcing(주문 STATUS)** = `check_order_sync` 가 소싱처 사이트를 실제 탐색.

**E 분해(정정):**
- **E1 주문번호 추출(지금, 완전 검증가능):** `sourcing_parser`(extract_memo_info·detect_order_no_from_url·fetch_order_no) + `sourcing_checker.SOURCING_SITES`(order_detail_url 템플릿) 무수정 이식 + `/api/blackspot/fetch_order_no` 라우트(모음전 stateless — 메모/행을 페이지가 전달). 페이지 `fetchOrderNoFromSource` 가 이미 호출. **확장 없이 동작·TDD.**
- **E2 주문상태 확인(확장·E-live):** check-sourcing → 확장 브리지(`sourcing.check-order` 신규 타입) 릴레이+세임+degradation+스켈레톤(지금, 검증가능) / 소싱처별 실 주문상태 추출·실검증(확장 로드+실 로그인 필요, **날조 금지**). [[project_crawl_is_local_pc_principle]] [[reference_loaded_extension_path]]

---
*폐기: `docs/superpowers/plans/2026-07-11-마진계산기-화면-B레이아웃.md` (원본 1:1 방향에서 무효).*
