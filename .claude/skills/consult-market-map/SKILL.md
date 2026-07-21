---
name: consult-market-map
description: 판매처(마켓) API 관련 개발·수정 시작 시 강제 발동 — 데이터 코드 지도 전수정독 게이트. Triggers — "쿠팡/스마트스토어/롯데온/11번가/옥션/G마켓" + "가격/재고/주문/정산/클레임/송장/등록/전환/연동/API" 조합의 개발 발화, "마켓 API 붙여줘", "판매처 기능 만들어줘". 소싱처(크롤링)는 add-source 영역이라 제외. 이 관문 통과 전 마켓 API 코드 작성 금지.
---

# 판매처 지도 전수정독 게이트 (consult-market-map)

판매처(마켓) API 기능을 개발·수정할 때, 코드를 만지기 **전에** 데이터 코드 지도를 전수정독한다.
목적: 지도에 이미 있는 정보를 F12로 재발견하는 노가다와, 탭 몇 개만 보고 헤매는 것(삥삥)의 종식.

<HARD-GATE>
아래 0~4단계를 통과하기 전에는 마켓 API 코드를 작성·수정하지 않는다.
"간단한 수정이라 괜찮다"는 예외 사유가 아니다 — 과거이력·idTraps 미확인이 곧 사고 원인이었다.
</HARD-GATE>

## 6단계

0. **멈춤** — 발화에서 대상 마켓 id(coupang/smartstore/lotteon/eleven11/auction/gmarket)와 기능을 확정. TodoWrite(또는 TaskCreate)로 1~5단계 체크리스트 생성.
1. **전수 정독** — 마켓 브리핑 한 장을 Read:
   - 라이브: `https://mou-m.com/marketplace-guide/map-brief?market=<id>` (기본=축약. 특정 API를 실구현할 땐 그 API의 생략된 필드를 `?full=1`로 확보)
   - 로컬 저장소: `프로그램/_시스템/webapp/market_brief.py`의 `build_brief("<id>")` 실행 결과
   섹션 1~9를 **전부** 읽었는지 체크: ①개발환경 ②API 카탈로그 ③정산 ④주문상태 전환 ⑤상태 전이 ⑥문서 수집법 ⑦과거이력 ⑧어댑터 yaml ⑨요약.
   특히 **⑦과거이력**(같은 함정 재발 방지)과 API 항목의 **idTraps**는 건너뛰기 금지.
2. **브리핑 작성** — 이번 기능에 필요한 API만 추려 표로 정리: method·URL·요청필드·응답필드·에러코드·ID모델·인증·상태(st).
3. **갭 선순환** — 필요한 칸이 비어 있으면(st=off/todo·필드 불명):
   ① `docs/markets/_API문서수집법.md`(인앱 📘 탭과 동일) 플레이북 순서(A→A-2→robots→H→F→C→I)로 스스로 확보.
   ② 확보한 내용을 `프로그램/_시스템/webapp/data/marketplace_api_map.json`에 되채움 — `validate_map` 통과 필수. 다음번엔 지도에 이미 있게 된다.
   ③ 그래도 못 구한 칸은 **"확인불가"**로 명시(날조·추정 절대 금지. 폴백 금지).
4. **라이브 대조** — `/marketplace-guide/map` 팝업의 해당 마켓 탭을 열어 브리핑과 화면 일치(항목 수·상태색) 확인.
5. **개발 착수** — 이제 코드. TDD(superpowers:test-driven-development) 등 해당 작업 스킬로 진행.

## 완성 게이트

- 필요한 각 API가 "채워짐" 또는 "확인불가" 둘 중 하나로 명시되기 전에는 5단계 진입 금지.
- 3-②로 JSON을 고쳤으면 그 변경도 같은 브랜치에 커밋한다(지도 선순환 — 이것이 이 스킬의 존재 이유).
