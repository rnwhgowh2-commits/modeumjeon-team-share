# LIGHT_SPEC.md — 정책→5마켓 등록 연동 (코드 관점)

## 🔴 착수 전 안전 선결 조건

`service.py:_send_live`는 **스마트스토어만** 등록 직후 `mark_suspension()`으로 자동 판매중지 전환한다(서버가 `SUSPENSION` 요청을 무시하고 항상 `SALE`로 등록하기 때문). **G마켓·옥션·11번가·롯데온 4개 마켓은 이 자동 안전장치가 없다** — 실등록 테스트를 하면 그 상품이 실제로 판매중 상태로 노출된 채 남는다.

→ 각 마켓 실등록 테스트를 시작하기 **직전에** 그 마켓의 판매상태 변경 API(`change_status` 계열, `docs/markets/{market}.yaml`의 `endpoints.change_status` 참고)로 즉시 중지 전환하는 로직을 `service.py:_send_live`에 스마트스토어와 같은 패턴으로 추가한다. G마켓·옥션·11번가·롯데온 각각 자체 태스크로 넣는다(마켓 진행 순서와 동일하게).

## 마켓별 작업 (완성도 순)

### 1. G마켓·옥션 (ESM)
- 안전: `change_status` 자동전환 추가
- 버그: `fields.py: EXTRA_ITEMS`의 `_site_discount`가 `only=['gmarket','lotteon']`로 옥션이 빠짐 → `only=['gmarket','auction','lotteon']`로 수정 (required.py 지도가 이미 "옥션도 필수"라고 명시)
- 검증(`TO_VERIFY_BY_LIVE`): auction KC 칸, auction 태그 칸 — 문서에 없으니 실등록으로 확인 후 required.py에서 항목 삭제
- 카테고리 1~2개 실등록 → 상품ID 수령 확인

### 2. 스마트스토어
- 🟢 **정정(계획 작성 중 재확인, 08-20)**: 애초에 지목했던 `lemouton/registration/smartstore.py:_build_default_shoes_notice` 하드코딩은 **정책생성→마켓전송 경로가 쓰는 코드가 아니다** — 그 함수는 별개의 구 "모음전 경로"(`register_bundle_to_smartstore`, Model/PriceTemplate 기반 다른 기능) 전용. 실제 정책 경로는 `compile_smartstore.py`→`notice.py:build_notice`(4유형 지원, 공식문구 검증)를 쓰고, `notice_type` 자동판정(`notice_type_guess.py`)이 **오늘 아침 이미 merge·배선완료**(`send/as_draft.py:147-148`, 테스트 존재) — 고시유형 버그는 **이미 없음**
- 남은 일: 위 판정이 실제로 맞는지 확인 테스트 1개(RED 기대 없이 현재 GREEN 확인) + `TO_VERIFY_BY_LIVE`: 배송정보 미전송 시 결과 확인
- 카테고리 1~2개(신발·의류 등 다른 유형 섞어서) 실등록 → 상품ID 수령 + 고시유형이 맞게 나갔는지 확인

### 3. 11번가
- 안전: `change_status` 자동전환 추가
- 버그: `send_more.py:366-370` 고시정보 코드표 임시 우회값 → 정식 코드표로 교체(공식문서에 없으면 카테고리별 실등록으로 코드값 확정)
- 검증(`TO_VERIFY_BY_LIVE`): KC 칸 카테고리별 필요 여부 (기존엔 없이도 성공한 사례 있음 — 카테고리 의존인지 확인)
- 카테고리 1~2개 실등록 → 상품ID 수령 확인

### 4. 롯데온
- 안전: `change_status` 자동전환 추가
- **등록 메커니즘 자체는 이미 라이브 검증됨**(2026-07-21, LO2729045338, 본보기 상품 복사 방식) — 새로 뚫을 것 없음
- 검증(`TO_VERIFY_BY_LIVE`): 13항목 전체를 실등록으로 하나씩 확인(문서가 요약본이라 이 방법뿐 — 2026-08-02 확정 방법론: "일부러 그 칸만 비우고 등록 시도 → 결과 확인 → 즉시 판매중지")
- 카테고리 1~2개 실등록 → 상품ID 수령 확인 + 13항목 매핑표를 `docs/markets/lotteon.yaml`에 채움

## 실등록 테스트 공통 절차

1. 로컬 개발서버에서 `LIVE_REGISTER_ARMED=1` (운영 GH 변수는 안 건드림)
2. `webapp/routes/live_send_test.py`에 `arm=1`로 개별 호출
3. 등록 성공 → 상품ID 확인 → (구현한) 자동 판매중지 전환 확인
4. `TO_VERIFY_BY_LIVE` 대상 칸이 있으면 그 칸만 비운 버전으로 1회 더 등록해 결과 관찰
5. 확인된 항목은 `required.py`의 `TO_VERIFY_BY_LIVE`에서 제거, `docs/markets/{market}.yaml` 갱신

## 사이클 종료 조건

5마켓 전부 위 항목 통과 → 운영 GitHub 저장소 변수 `LIVE_REGISTER_ARMED`를 0→1로 전환(사용자 승인 필요, 배포 파이프라인 변경이라 명시적 확인 대상).
