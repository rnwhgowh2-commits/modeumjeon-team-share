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

## 3. 순서 (실측 크기 기준)

| 배치 | 화면 | 크기 | 방식 |
|---|---|---|---|
| **1** ✅ | 알림 설정(/alerts) · 휴지통(/trash · 짝 화면 /audit 포함) | 소 | retrofit — 패턴 확립. ⚠️소싱처 사전(/source-registry)은 **라우트 자체가 없다** — 2026-06-30 블루프린트 제거(routes/__init__.py:84, 크롤링 가이드로 통합)라 대상에서 뺌 |
| **2** ✅ | 마켓 상품 현황(/catalog/ — 탭 3개 partial 각각) · 데이터 가이드(/data-guide) · 노션 일일보고(/reports/notion-todo) · 실전송 테스트(/live-send-test) — **4개 전부 전환, 유예 0** | 소 | retrofit. 실측: catalog 1.3KB+partial 9~13KB·live-send 34KB·data-guide 46KB(문서형 — CSS 작업은 소)·notion-todo 는 **템플릿이 아니라 routes/notion_report.py 의 _CSS**(base.html 밖 독립 화면이라 띠는 원래 안 뜸 — READY 등록의 실효는 메뉴 배지). ⚠️ /catalog 탭은 물음표 뒤로 갈려 READY 에 탭 주소 3개를 따로 적어야 한다(same_screen 이 쿼리 보존) |
| **3** ✅ | 가격 정책(/templates) · 정책 생성(/policies) · 상품 정책 적용(/policies/apply) · 판매처 계정(/accounts/upload) — **4화면 전부 전환** | 중 | retrofit + 표 처리. 실측: templates 7KB·policies 17KB·apply 27KB·**upload 72KB(최대 retrofit — CSS만으로 전환 성공**: 사이드바→위쪽 가로 스크롤 줄·colgroup 고정폭(인라인+JS 복원값)은 `!important` 로만 이김·「소싱처 가이드 스케일」로 키운 PC 글꼴(td 24px)을 폰 크기로 되돌림·칼럼 끌기는 마우스 전용이라 그대로 둠). ⚠️ /policies 는 ?brand= 값이 임의라 READY 에 열거 불가 — 걸러진 주소에선 노란 띠가 다시 뜬다(껍데기 설계 한계, 기록만). ⚠️ 소싱처 가이드(/sourcing-guide/)는 이 배치 **미착수** — 배치4 로 넘김 |
| 4 | 소싱처 가이드(/sourcing-guide/ — 배치3 이월) · 모음전 상품관리(/bundles) · 옵션생성 3탭(/optgen) · 마켓 전송(/market-send) · 자동화(/automation) · 대량등록(/bulk/) · 재고관리(/inventory/) | 중~대 | 화면별 판단 |
| 5 | **주문 내역(/orders 4탭)** — 사용빈도 최고·31만 자 | 괴물 | **별도 설계**(2단계 홈 대시보드와 함께) |
| 6 | 매트릭스(/matrix)·마진(margin_embed)·크롤가이드 지도(map)·재고 items | 괴물 | 별도 설계 |

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

## 5. 이 문서가 곧 진행표다

배치가 끝나면 표의 해당 줄에 ✅와 PR 번호를 적는다. 어디서 멈춰도 그 시점까지가 완성품.
