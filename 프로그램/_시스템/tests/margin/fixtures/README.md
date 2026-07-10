# 골든테스트 baseline 픽스처 (마진계산기 회귀 동치)

## 무엇인가

`<date>_baseline.json` (또는 `.json.gz`) 은 **옛 마진계산기**
(`C:\dev\대량등록 마진계산기`, READ-ONLY)를 그 날짜의 더망고·샵마인 엑셀 쌍으로
구동해 뽑은 **cycle ① 매칭·집계 결과**의 고정 스냅샷이다.

골든테스트(`tests/margin/test_golden_regression.py`)는 이 baseline 과, 신코드
(`parse_buy → from_shopmine_excel → pipeline.run → aggregator.aggregate`)의
출력을 필드 단위로 대조한다. 어긋나면 **신코드(이식 모듈)가 틀린 것**이다 —
baseline 은 진실이므로 손대지 않는다.

매출원을 **샵마인 엑셀로 고정**(API·네트워크 없음)했기 때문에, 차이는 오직
"포팅 결함"만 남는다. (API 어댑터 동치는 Task 16 에서 별도로 검증.)

## 담긴 것 / 안 담긴 것

담긴 것 (순수 cycle ①):
`matched`, `unmatched_buy`, `unmatched_sell`, `buy_missing`, `summary`,
`market/daily/monthly/brand/priceRange/product`, `filters`.

**안 담긴 것 (cycle ② = 블랙스팟 분류기, 이 포트 범위 밖):** 옛 `/api/analyze`
응답에는 아래가 섞여 있으나, 신코드가 재현하지 않으므로 baseline 에서 제외했다.
- `summary.card_*` 를 `_compute_card_counts`(분류기)로 **덮어쓴 값**
- `summary.mango_total / mango_with_order_no / mango_with_trace`
- `unmatched_buy` 를 raw 더망고 '매입흔적' 행으로 **augment 한 결과**
- top-level `classified` / `blackspot_summary` / `missing_order_no`

그래서 baseline 은 라우트 응답을 그대로 저장하지 않고, 옛 앱을 in-process 로
구동한 뒤 `store['matched']` + `_aggregate(...)` 의 순수 산출물을 뽑는다.
(baseline 의 `summary.card_*` 는 `_aggregate` 자체가 내는 값 — 신 aggregator 와 동일.)

## 개인정보 마스킹

응답에 고객명이 실린다. `{수령인, 수령인명, 수취고객명}` 키의 값을 재귀적으로
`"***"` 로 치환한 뒤 저장한다. 테스트는 **신코드 출력에도 동일 마스크**를 적용해
비교하므로(대칭), 마스킹이 차이를 가리지 못한다.

**원본 엑셀(.xls)은 커밋하지 않는다** — 고객명·주소가 들어 있다. baseline JSON
(마스킹됨)만 커밋한다.

## 사용 가능한 쌍

`C:\dev\대량등록 마진계산기\데이터\` 아래 `260629 / 260630 / 260704 / 260706`
각 폴더에 `*더망고*.xls` + `*샵마인*.xls` 한 쌍씩. 골든테스트는 현재
`260704`(작은 케이스) 와 `260706`(matched 595·주문미이행 244 포함 큰 케이스)를 쓴다.

## 재생성

```bash
cd 프로그램/_시스템
export PYTHONIOENCODING=utf-8
python scripts/margin_capture_baseline.py 260704
python scripts/margin_capture_baseline.py 260706
```

5MB 를 넘는 baseline 은 자동으로 `.json.gz` 로 저장된다(테스트가 자동 인식).
CI 에는 데이터 폴더/픽스처가 없으므로 골든테스트는 `pytest.skip` 된다.
