# 모바일 3단계 — PC 화면 전수 모바일화

> **작성**: 2026-08-04 · **확정**: 사장님 "전수 시작해줘"
> **전제**: 1단계(앱 껍데기) 라이브 배포 완료. 브랜치 `stage3/mobile-conversion` (origin/main 기준)

## 1. 전환 방식 — 한 벌 유지가 원칙

**반응형 덧붙임(retrofit)** 을 기본으로 한다. 화면마다 폰 전용 사본을 만들면
25개 × 두 벌 유지가 되고, 그건 이 프로젝트가 내내 싸워온 "같은 사실 두 곳에 적기"의
화면판이다. 대신:

- 각 템플릿의 **기존 `<style>` 블록 안에만** `@media (max-width: 768px)` 규칙을 **덧붙인다**.
  블록이 아예 없는 템플릿은 **@media 만 담은 새 `<style>` 블록 하나**를 추가한다(배치1 선례).
  🔴 HTML 구조 재작성 금지 · `<style>` 밖 일괄치환 금지 (2026-08-01 실사고: 파일 전체에
  치환을 돌려 JS 죽인 채 배포).
- 표는 ①가로 스크롤 컨테이너(첫 열 sticky) 또는 ②칸수가 적으면 카드 접힘 — 화면별 판단.
- 터치 목표 44px 이상, 글자 최소 14px, 가로 넘침 0 (body 가로 스크롤 금지).
- PC 렌더는 **1px 도 안 바뀐다** — @media 밖 규칙 추가 금지. tests/design 회귀로 못 박음.
- **괴물 화면**(orders/index 31만·margin_embed 64만·_matrix_v3 47만·sourcing_guide/map 20만·
  inventory/data/items 12만)은 retrofit 불가 — **별도 설계**(폰에서 뭘 보여줄지부터). 마지막 순번.

## 2. "폰 대응 완료" 표시 — 단일 원천

전환이 끝난 화면은 껍데기의 노란 안내 띠("PC용 화면입니다")가 **안 떠야** 한다.
- `webapp/routes/mobile_shell.py` 에 `MOBILE_READY_URLS`(전환 완료 PC 주소 집합) 신설.
- 껍데기 JSON(base.html 의 ms-tabs-data)에 실어 내려보내고 `mobile_shell.js` 가 읽어
  해당 경로에서 안내 띠 생략. **JS 에 주소 하드코딩 금지.**
- 메뉴 배지: `PHONE_NATIVE_BADGE_URLS` 에 같은 주소 추가 → "폰 전용" 배지.
  (mobile_shell.py:46 의 기존 지침 그대로 — 정규화 함수 통과 확인)
- 전환 화면마다 이 두 집합에 넣는 것까지가 "완료"다 — 역방향 시험이 이미 지킨다.
- **[배치4a] `MOBILE_READY_PATH_ONLY`** — 쿼리가 데이터 필터일 뿐(같은 템플릿)인 화면은
  경로 일치만으로 띠를 생략한다(예: `/policies?brand=임의값`). **opt-in 부분집합**이다 —
  🔴 전역 금지: /orders 처럼 탭(?tab=)마다 다른 템플릿을 그리는 화면은 탭 주소 열거를 유지.

## 3. 순서 (실측 크기 기준)

| 배치 | 화면 | 크기 | 방식 |
|---|---|---|---|
| **1** ✅ | 알림 설정(/alerts) · 휴지통(/trash · 짝 화면 /audit 포함) | 소 | retrofit — 패턴 확립. ⚠️소싱처 사전(/source-registry)은 **라우트 자체가 없다** — 2026-06-30 블루프린트 제거(routes/__init__.py:84, 크롤링 가이드로 통합)라 대상에서 뺌 |
| **2** ✅ | 마켓 상품 현황(/catalog/ — 탭 3개 partial 각각) · 데이터 가이드(/data-guide) · 노션 일일보고(/reports/notion-todo) · 실전송 테스트(/live-send-test) — **4개 전부 전환, 유예 0** | 소 | retrofit. 실측: catalog 1.3KB+partial 9~13KB·live-send 34KB·data-guide 46KB(문서형 — CSS 작업은 소)·notion-todo 는 **템플릿이 아니라 routes/notion_report.py 의 _CSS**(base.html 밖 독립 화면이라 띠는 원래 안 뜸 — READY 등록의 실효는 메뉴 배지). ⚠️ /catalog 탭은 물음표 뒤로 갈려 READY 에 탭 주소 3개를 따로 적어야 한다(same_screen 이 쿼리 보존) |
| **3** ✅ | 가격 정책(/templates) · 정책 생성(/policies) · 상품 정책 적용(/policies/apply) · 판매처 계정(/accounts/upload) — **4화면 전부 전환** | 중 | retrofit + 표 처리. 실측: templates 7KB·policies 17KB·apply 27KB·**upload 72KB(최대 retrofit — CSS만으로 전환 성공**: 사이드바→위쪽 가로 스크롤 줄·colgroup 고정폭(인라인+JS 복원값)은 `!important` 로만 이김·「소싱처 가이드 스케일」로 키운 PC 글꼴(td 24px)을 폰 크기로 되돌림·칼럼 끌기는 마우스 전용이라 그대로 둠). ⚠️ /policies 는 ?brand= 값이 임의라 READY 에 열거 불가 — 걸러진 주소에선 노란 띠가 다시 뜬다(껍데기 설계 한계, 기록만). ⚠️ 소싱처 가이드(/sourcing-guide/)는 이 배치 **미착수** — 배치4 로 넘김 |
| **4a** ✅ | 마켓 전송(/market-send) · 자동화(/automation) · 대량등록(/bulk/ — 탭 9개 partial 각각) — **3화면 전부 전환** + 파서 보강·PATH_ONLY | 중 | retrofit. 실측: market-send 22KB·automation 89KB(대부분 JS — CSS만으로 성립: `zoom:1.3` 해제·2단→1단·표 4벌 스크롤·보고서 팝업 `zoom:1.4` 해제)·bulk index 0.9KB+partial 3.5~74KB(그중 _settings 74KB 도 CSS 작업은 소). /bulk/ 는 catalog 처럼 **탭 주소 10개를 READY 에 열거**(원천 bulk.SUBTABS 와 시험이 대조). bulk 왼쪽 240px 사이드바는 위쪽 가로 스크롤 줄로(sidebar_bulk.html 자체 블록 — index 의 `.app` 세로 전환과 한 몸). ⚠️ /automation/weights(크롤 계수 상세)는 별도 화면 — **미전환**(다음 배치). 🔧 배치3 검토 반영: ① 선택자 파서 `\b`→`(?<![\w-])` 경계 강화 + base.html 상속 화면은 base 마크업 합류(`.main` 정당 통과·`up-main` 헛통과 차단) ② `MOBILE_READY_PATH_ONLY` 신설 — /policies?brand=임의값 도 띠 생략(경로 일치 opt-in, 🔴전역 금지 — /orders 는 탭마다 템플릿이 다르다) → 배치3의 「?brand= 설계 한계」 해소 ③ apply.html 체크칸 22px 을 `#screen-policy-apply` 로 스코프 |
| **4b** ✅ | 소싱처 가이드(/sourcing-guide/ — 배치3 이월) · 모음전 상품관리(/bundles) · 옵션생성 3탭(/optgen) · 재고관리(/inventory/) · 자동화 계수(/automation/weights — 4a 이월) — **5화면 전부 전환, retrofit 완결** | 중~대 | retrofit. 실측: overview 59KB(「E안 2배 확대」 24px 글자를 폰 크기로 되돌림·감싼 카드의 **인라인 overflow:hidden 이 표 스크롤을 조용히 죽여** `!important` 로 이김)·bundles/list 60KB(12열 표 — 첫 열이 체크칸이라 **이름 열(2번째)을 붙박이**·브랜드 nav 는 위쪽 가로 줄)·optgen index 11KB+market 탭 partial 16KB(**탭 주소 3개 READY 열거** — 원천 optgen.SUBTABS 와 시험이 대조. market 탭만 조각이 달라 PATH_ONLY 금지)·inventory/home 57KB(**규칙이 전부 인라인 style** — 걸 자리가 없어 iv-* id 훅 6개만 달고 `!important` 로 이김·PC 에서 그 id 를 읽는 규칙·JS 0곳)·weights 27KB(5열 밀러 컬럼 → 세로 1열, `#cw-finder` id 로 `.c5/.c4/.c3` 를 이김). **부분 전환 0** — 5화면 전부 완전 전환. 🔧 4a 검토 Minor 반영: ① PATH_ONLY **기계 문지기** — 엉뚱한 쿼리(?zzz=1)로도 같은 템플릿인지 template_rendered 신호로 검사(라우트가 쿼리로 템플릿을 갈면 빨강 — 실변조로 확인) + PATH_ONLY 에 /bundles·/inventory/·/sourcing-guide/ 추가(전부 쿼리=데이터 필터. /inventory/?sku= 는 **행만 눌러도 붙는 주소**라 없으면 띠가 되살아난다) ② 파서 — base 마크업 합류 전 `{{…}}` 제거(`.default`·`.design_body_class` 유령 토큰 헛통과 차단·실변조로 `.default` 도 이제 빨강·`.ghost` 는 여전히 빨강=약화 없음) + extends 따옴표 두 벌(`"base.html"`) 인식 ③ 가로 탭 줄(sidebar_bulk·optgen 탭·bundles 브랜드 nav) — **오른쪽 끝 흐림**(mask-image 그라데이션, CSS 만·JS 0줄)으로 「더 있음」 힌트 |
| 5 🚧 | **주문 내역 폰 전용 화면** — 사장님 시안 확정(2026-08-04): **1-C**(2줄 압축 줄+오른쪽 금액열·tabular-nums·상태 배지 앞) + **2-A**(위쪽 알약 칩 4개, 개수 배지 — 목록·송장·CS·마진) + **3-C**(요약 KPI 3칸=신규·오늘매출·품절위험은 **주문 화면 상단에만**, 홈에는 「주문 보러 가기」 바로가기만 — 같은 숫자 두 곳 금지). 시안 파일=바탕화면 「모음전 폰 주문화면 시안 v1.html」, **시안=코드**(그 배치 그대로 구현). **1차 ✅**(PR#759 — 뼈대+목록 칩) · **2차 ✅**(송장 A-1+A-4·CS B-2·마진 C-4 알약 채움 — 확정 내용·정직 편차는 §6 표) | 괴물 | 폰 전용 신축(/mobile/orders) — retrofit 아님. 기존 주문 API 재사용, 새 집계 발명 금지 |
| 6 | 매트릭스(/matrix — **D-1 ✅** 폰 신축 /mobile/matrix, 아래 §6 D 참조)·마진(margin_embed — **E-1 ✅** 폰 신축 /mobile/settle, 아래 §6 E 참조)·크롤가이드 지도(map — **F-2 ✅** 폰 신축 /mobile/guide, 아래 §6 F 참조)·재고 items(**G ✅** 2026-08-05 시안 확정 A4·B1·C1+C4 — 기존 /mobile/inventory 확장, 아래 §6 G 참조) | 괴물 | 별도 설계 |

> ✅ **retrofit 전수 완료(2026-08-04 배치4b)** — 배치1~4b 로 retrofit 가능한 화면은
> **전부 전환됐다.** 남은 것은 **괴물 4벌뿐**(배치5 /orders · 배치6 matrix·margin_embed·
> sourcing_guide/map·inventory/data/items) — 전부 「폰에서 뭘 보여줄지」부터 정하는
> **별도 설계** 대상이라 @media 덧붙임 방식은 여기서 끝난다.

> 🔴 **2026-08-04 정정(배치1 검토 Important#1)**: 원래 적혀 있던 /queue·/dlq·/sources·/mapping/ 은
> **라우트가 이미 삭제된 화면**(routes/__init__.py:85-88, 2026-07-30)이라 표에서 뺐다. 위 표는
> **라이브 메뉴 실측 25줄** 기준. 각 배치 착수 시 라우트 실존을 다시 확인할 것(스펙도 썩는다).

각 배치 = 구현 → 명세검토 → 품질검토 → 수정 → 커밋. 배치 끝날 때마다 머지 가능 상태 유지.

## 4. 화면별 완료 기준 (전 배치 공통)

1. 375px 폭에서 가로 넘침 0 · 본문 글자 ≥14px · 터치 목표 ≥44px
2. PC(1280px) 렌더 변화 0 — @media 밖 규칙 diff 0
3. `MOBILE_READY_URLS` + 배지 등록 (노란 띠 사라짐 · 메뉴 배지 "폰 전용")
4. 시험: 뷰포트별 CSS 규칙 존재 + 등록 여부 + tests/design 회귀 0
5. 함정 4종 점검(낱말 헛통과 · 빨간 기준선 · 주석 과장 · 눈에 안 보이는 잠금)

> 📏 **결과 기록 — 실브라우저 감사 1회차(2026-08-05, 라이브 mou-m.com 375×812 계산값 실측)**
> 발견 7건 전부 수정 완료:
> **F1(전 화면 공통)** retrofit 전 화면 문서폭 496~511 — 범인은 본문이 아니라
> **PC 상단 메뉴**(.tn-tabs 의 justify-content:center: 탭 8개가 칸보다 넓으면 가운데
> 기준 양쪽으로 삐져나가 왼쪽 -109px·오른쪽 511px). 고침 = topnav.css 끝
> `@media ≤768px`(탭 줄 자체 가로 스크롤 + 오른쪽 흐림 힌트 + 펼침 판 fixed 전개)
> — PC 는 @media 밖 diff 0. 설치된 앱 껍데기(`.ms-on`)에서는 상단 메뉴 통째 숨김
> (껍데기가 자기 상단바·하단탭을 그린다).
> **F2** 칩 실측 31px(orders)·33px(settle) → min-height 44 · **F3** 크롤 자동 토글 26px
> → 44px 라벨 감쌈 · **F4** 단위 <small> 9.17px(settle, .l 11px×브라우저 기본 0.833em)·
> 10px(orders) → ≥11px · **F5** 메뉴 배지 10→11px · **F6** 뒤로/홈 32~36px → 44px ·
> **F7** 홈 「데스크탑 버전」 링크 14px → inline-block+패딩 16px.
> 비발견(그대로 둠): 폰 신축 화면 body 넘침 0 · 가이드 줄간 1.8 · 메타 11px(사장님
> 승인 시안 크기 — 올리지 않음). 고정 핀 = tests/design/test_topnav.py §4 ·
> tests/mobile/test_phone_375_audit.py (CSS 원문 핀 — 한계 정직 표기, 변이 2종 빨강 확인).

## 5. 이 문서가 곧 진행표다

배치가 끝나면 표의 해당 줄에 ✅와 PR 번호를 적는다. 어디서 멈춰도 그 시점까지가 완성품.

> 🏁 **사장님 확정 화면 전수 완료(2026-08-05, F-2 로 종결)** — §6 일괄 시안에서
> 확정된 6벌(A 송장·B CS·C 마진 칩·D 매트릭스·E 마진 계산기·F 크롤가이드)이
> **전부 구현·시험 완료**됐다. retrofit 전수(배치1~4b)도 이미 끝났으므로, 남은
> 미전환은 **재고 items(inventory/data/items) 하나뿐**이고 이것은 시안 확정
> 대상이 아니었다(폰에서 뭘 보여줄지 미정 — 착수하려면 시안부터).
> → **2026-08-05 해소**: 「모음전 폰 제품화면 시안 v1」로 사장님 확정(A4·B1·C1+C4),
> §6 G 로 구현 완료 — **이로써 미전환 0**.

## 6. 일괄 시안 확정 (사장님, 2026-08-04 저녁 — 「모음전 폰 화면 일괄 시안 v1.html」)

| 항목 | 확정 | 내용 |
|---|---|---|
| A 송장 | **A-1 + A-4 합침** ✅ | 위 = 현황 3칸 · 아래 = 대기 목록, 줄 누르면 그 자리에서 택배사+송장번호 입력·저장. **저장 = 기존 `/orders/invoice/send` 그대로**(payload 도 PC invSend 와 동일 — 시험이 주소·키를 못 박음). 정직 편차 2건: ① 셋째 칸 「미매칭」→**「송장 없음」** — 미매칭은 택배사 엑셀 대조(PC 전용 흐름)의 개념이라 폰(엑셀 없음)엔 원천이 없다. 대신 실원천이 있는 「배송중·완료인데 송장 미기록」(송장 스윕이 채우는 그 갭, `_SHIPPED_STATES` 서버 주입)을 센다. ② 「오늘 발송」= flow-daily(적재분) 원천 — 발송처리일을 주는 마켓(스스·롯데온·11번가)만 셀 수 있고, 못 세는 건수(쿠팡·옥션·G마켓)는 `+?` 로 드러낸다(숨김 금지) |
| B CS | **B-2** ✅ | 유형 칩(전체·취소·반품·교환·문의)로 거르는 목록 — cs/claims.json + cs/inquiries.json 배선(서버 기본 7일 창 = PC CS 탭과 동일). **CS 수의 단일 정의 = 이 목록(claims 3단계 + 문의 2상태 합침)의 길이** — 위 알약 개수·전체 칩·목록이 전부 한 함수(csItems)에서 나온다. 1차의 rows 상태 정규식 수(csN)는 문의를 못 세 판과 다른 답을 내므로 **제거**. 알약 개수는 CS 판을 처음 열기 전 '-'(마켓 문의 API 를 화면 열 때마다 치지 않는다 — 열 때 1회). 클레임·문의 한쪽 실패 시 전체·해당 유형 '-'(부분합을 전체인 척 금지) |
| C 마진 칩 | **C-4** ✅ | 기간 칩(오늘/7일/이번달) + 숫자 6칸(매출·마진·마진율·주문·취소·적자). 오늘·7일 = **목록이 이미 불러온 rows + price-diff**(새 집계 0·추가 마켓 호출 0), 매출 산식 = 3-C 「오늘 매출」과 같은 함수(salesOf — 한 화면 두 산식 금지). 마진·마진율·적자 = 원가를 아는 행만으로 계산하고 일부만 알면 「N/M건 기준」 표시, price-diff 실패면 '-'. **「이번 달」은 숫자 미제공** — 실측 근거: 6마켓 7일 한 요청 61.7초(2026-07 실측)라 월(~31일)은 수 분 규모로 폰 칩엔 불가. 적재분(order_store) 원천은 존재하나 최근분 신선도가 라이브 7일 창과 갈라져 「이번달 < 7일」 모순이 한 화면에 뜰 수 있어 배제. 칩은 살아 있되(죽은 버튼 금지) 이유+PC 마진 계산기 링크를 그린다. month 갈래에서 합계 계산 자체를 시험이 금지 |
| D 매트릭스 | **D-1** ✅ | 검색 → 옵션 카드(소싱처별 가격·재고). 폰 화면 신축 `/mobile/matrix`(routes/mobile_matrix.py + templates/mobile/matrix.html). **데이터 = PC /matrix 와 같은 함수**(`matrix._rows_for` — 표면가·최종매입가·재고 단일 원천, 새 집계 0). 검색 = 낱말 AND(모음전 이름·모델번호·SKU·옵션번호·색·사이즈 — 시안 예시 「니트 블랙 M」 성립), 2글자 문턱·디바운스 300ms·loadSeq·최근 검색 localStorage. 🔴 재고 배지는 **서버가 판정**(`_stock_badge`: None·음수→확인불가 / 0→품절 / 999센티넬→「재고 있음」— 센티넬 원천 guide_url_result 상수 import, 시험이 정본 `_stock_label` 과 전 구간 대조) — 폰 JS 는 그대로 그린다(같은 판정 두 곳 금지, JS 에 판정 낱말이 생기면 시험이 빨강). 가격 = final 우선·없으면 surface 에 「표면」 표를 밝힘·둘 다 없으면 '-'(폴백 발명 금지). 돌연변이 6종(둔갑·배선 끊기·가격 0 지어내기·'-' 갈래 제거·JS 재판정·메뉴줄 삭제) 전부 빨강 확인 |
| E 마진 계산기 | **E-1** ✅ | 기간 요약(정산 예정/확정 + 마켓별 막대). 폰 화면 신축 `/mobile/settle`(routes/mobile_settle.py + templates/mobile/settle.html). **데이터 = 재사용 사슬 3개, 새 집계 0**: ① 행=`order_store.load`(**주문일 기준** 저장분 — PC 주문내역 90일 초과가 쓰는 같은 길, 마켓 호출 0) ② 보강=`order_export.enrich_stored_rows`(라이브와 같은 수준·읽기 전용) ③ 정산액·근거=`sell_source._settlement_for`(**마진계산기 정산=주문내역 단일원천** 그 함수 — monkeypatch 시험이 재유도를 막음). 분류(확정/추정/취소/미확인)=`pipeline._TAG_RANK` 서열에서 유도(사본 금지). **「이번 달」 제공** — C-4 가 월을 뺀 근거(마켓 라이브 61.7초/7일)는 라이브 조회 얘기고, 여기는 세 기간 전부 저장분 DB 읽기라 그 제약이 없고 원천 모순도 없다(한 화면 한 원천). 정직 편차 1건: 둘째 KPI 「정산 완료」→**「정산 확정」** — 저장분엔 입금(지급) 사실이 없고 마켓 정산 API 가 금액을 확정한 것(`real`/`store`)까지만 안다(PC 정산 색칩 margin_settle_cell.js 「실정산 확정」과 같은 어휘). 미확인(none) 행은 금액을 몰라 **건수로만**(0 둔갑 금지) · 취소(zero_cancel)는 정산 0 건수 · 저장분 전무=store_empty→'-'+이유 · 저장분 없는 지원 마켓=missing 명시(부분합을 전체인 척 금지). 막대=마켓별 예정+확정 합, **상대 눈금(가장 큰 마켓=100%)을 화면 캡션으로 명시**+막대마다 실금액(폭 하드코딩 금지, 시험이 Math.max 계산을 못 박음). 폴링 없음·ISO Date 파싱 없음(기간 표기=서버 포맷 문자열). 돌연변이 8종(추정→확정 둔갑·period 무시·_settlement_for 우회·미확인 0 둔갑·'-' 갈래 제거·막대 폭 하드코딩·주소 drift·메뉴줄 삭제) 전부 빨강 확인 |
| F 크롤가이드 | **F-2** ✅ | 읽기용 목차 → 절 읽기. 폰 화면 신축 `/mobile/guide`(routes/mobile_guide.py + templates/mobile/guide_toc.html·guide_section.html). **admin 전용** — PC 원천(/sourcing-guide/*)이 team-share-dev 에서 admin 게이트(sourcing_guide._admin_only)라 동일 정책(시험이 메뉴 표시와 실게이트를 묶음). **내용 = 정본 `docs/크롤링-가이드.md` 를 렌더 시점에 읽는다(문장 사본 0·경로 원천도 sourcing_guide._GUIDE_MD 하나)** — md 가 바뀌면 폰 화면도 0수정 동행(시험이 정본 경로 갈아끼우기로 못 박음 + 템플릿에 가이드 본문 글자 0줄 시험). 목차 = md `## ` 헤딩에서 유도, 절 주소 키 = 헤딩의 § 토큰(`/mobile/guide/s/2-b`)이라 절 순서가 바뀌어도 주소가 안 썩고, 한 줄 요약도 각 절 첫 산문에서 유도(지어 적지 않음). 정직 기록 1건: **재사용할 md→HTML 파이프라인이 저장소에 없었다** — PC /sourcing-guide/map 의 「보기」는 손으로 지은 203KB HTML(정본과는 drift 검사로 동기화)이고 「원문」 토글은 평문 표시뿐 → 표시용 최소 변환기(제목·코드 펜스·표·인용·목록·굵게·인라인 코드, 원문 전부 이스케이프)를 mobile_guide 에 새로 둠(내용 로직 0). 검색 = **목차(제목·요약) 클라이언트 필터**(fetch 0 — 본문 전문검색은 범위 밖이고, 그 범위를 화면 글자로 밝힘·0건 갈래 있음). 읽기 규칙: 본문 15px·코드/표는 자기 그릇 안 overflow-x 스크롤·목차 줄 44px. 돌연변이 7종(경로 사본·절 빼먹기·표 그릇 제거·이스케이프 제거·메뉴줄 삭제·게이트 무력화·검색 배선 끊기) 전부 빨강 확인 |

| G 재고 목록 제품 상세 | **A4·B1·C1+C4** ✅ | (사장님 확정 2026-08-05, 「모음전 폰 제품화면 시안 v1.html」) 기존 폰 「재고 목록」(/mobile/inventory) 확장 — 새 화면 신설 없음(B1 한 문). ① **B1 카드 인라인 펼침**: 카드(뼈대 유지 — 사진48+이름+오른쪽 숫자)를 누르면 바로 아래 상세 시트, 다시 누르면 접힘(한 번에 하나). 기존 카드의 /mobile/sku/<sku> 이동은 시트 안 「입고·출고」 단추로 보존. ② **C1 시트 내용**: 브랜드·모델·품번(Model)+바코드·평균매입가(Option) — 새 GET `/mobile/api/product/<sku>` 가 PC data_items rows 와 **같은 원천 필드**(값 대조 시험이 drift 를 지킴)·위치별 재고(기존 /mobile/api/stock). ③ **C4 색상×사이즈 미니표**: 같은 model_code 활성 옵션 전체의 SSOT 재고, 0=회색 0 / 조합 없음=「—」(null — 0 과 구분, 모순 표기 금지), 표가 넘치면 **표 그릇만** overflow-x 스크롤. ④ **A4 위치 이동**(폰의 유일한 쓰기): 새 POST `/mobile/api/transfer` — **데스크탑 create_move(inbound.py) 그대로 호출**(발명 0: tx_type='move'·qty 양수·location_id=출발·location_to_id=도착 1건 1커밋, SSOT `_stock_expr` 가 출발-·도착+ 합산), 검증=양수만·같은 위치 거부·출발지 SSOT 재고 부족 거부, 응답에 양쪽 위치 갱신 재고. ⑤ **KPI 3칸**: `shared.inventory_stock.master_kpi`(PC data_items 무필터 kpi 계산을 그대로 옮긴 공용 함수) — 폰·PC 값 대조 시험. **정직 편차 1건**: 시안 A4 의 「모음전 적용」 **스위치는 실데이터에 없다** — PC items.html 실렌더 확인 결과 실체는 usage_map(OptionProductLink 역참조 개수) 읽기전용 배지 → 폰도 같은 의미의 **읽기전용 「모음전 연결 N곳」** 으로 구현(켜고 끄기 발명 금지 — 스위치 부품이 생기면 시험이 빨강). 🔧 겸사 수정: /mobile/api/stock·/mobile/api/options 의 재고가 **raw sum(qty)** 였다 — 저장 규약(qty 양수, 부호는 tx_type)상 out/move 를 더해 버려 데스크탑과 다른 숫자를 말하던 모순 → SSOT(get_stock_batch 부류)로 교체(응답 모양 불변). 변이 3종(null→0 둔갑·재고부족 가드 제거·「—」 갈래 제거) 전부 빨강 확인 |

시안=코드: 갤러리 파일의 해당 프레임 마크업 구조를 그대로 따른다.
순서: 2차(A·B·C = /mobile/orders 알약 채우기) → D → E → F.
🔴 C-4 「이번달」: 마켓 라이브 회수 한도(쿠팡~4개월·스스~5개월)와 조회 무게 실측 후,
무거우면 저장분 원천을 쓰거나 기간을 정직하게 제한(지어내기 금지 — 구현자가 조사·보고).
🔴 A 송장 저장: 반드시 기존 PC 송장 저장·전송 엔드포인트 재사용(새 쓰기 경로 발명 금지).
