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

---
*폐기: `docs/superpowers/plans/2026-07-11-마진계산기-화면-B레이아웃.md` (원본 1:1 방향에서 무효).*
