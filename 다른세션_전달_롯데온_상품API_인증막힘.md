# [해결됨] 롯데온 상품 목록 조회 — pageNo·rowsPerPage 누락이었다 (2026-07-20)

> ⚠️ 이 문서의 **이전 버전은 결론이 틀렸다**("키에 상품 API 권한이 없다").
> 다른 세션이 뚫었고, 실제 원인은 **페이징 파라미터 누락**이었다. 아래가 정정본이다.

---

## 한 줄 요약

`POST /v1/openapi/product/v1/product/list` 에 **`pageNo` 와 `rowsPerPage` 가 필수**다.
이 둘이 없으면 `returnCode 9000`("처리 중 오류")이 나는데, 이게 권한 문제처럼 보여
오진하기 쉽다. **롯데온에 문의할 필요 없다.**

## 검증된 요청·응답

요청 body:
```json
{"trGrpCd":"SR","trNo":"<계정 trNo>",
 "regStrtDttm":"YYYYMMDDHHMMSS","regEndDttm":"YYYYMMDDHHMMSS",
 "pageNo":1,"rowsPerPage":100}
```
응답:
```json
{"returnCode":"0000","message":"조회완료되었습니다.","dataCount":13883,
 "data":[{"trGrpCd":"SR","trNo":"LO10161083","spdNo":"LO2727500650", ...}]}
```
상품 **13,883건** 조회 성공. `data[].spdNo` = 판매자상품번호 = 연동에 쓸 상품번호.

## 확정된 사실

| 항목 | 값 |
|---|---|
| `pageNo` · `rowsPerPage` | **필수** (`rowsPerPage` MAX 100) |
| 날짜 형식 | **14자리 `YYYYMMDDHHMMSS`** (8자리 → `INVALID_INPUT`) |
| `trGrpCd` | **`SR`** (일반셀러). `ST`/`SE` 는 `9999` 인증 불일치 |
| 상품번호 필드 | `data[].spdNo` (예: `LO2727500650`) |
| 키 권한 | **문제 없음** — 상품 API 정상 접근 가능 |

같은 롯데온 목록 API 인 `product/qna/list` 도 `pageNo*`·`rowsPerPage*`(MAX 100) 필수 →
**롯데온 목록 계열 API 는 페이징이 필수**로 보는 게 안전하다.

## 왜 오진했나 (같은 실수 방지)

1. **지도에 접수된 params 목록에 `pageNo`·`rowsPerPage` 가 없었다.**
   `res` 가 `{"note":"전체 스펙 롯데ON apiNo=93"}` 플레이스홀더라 응답 스펙 미확보 상태였고,
   요청 params 도 완전하지 않았다. → **지도의 params 를 '전부'로 믿으면 안 된다.**
2. 6변형 시험을 하면서 페이징 변형에 파라미터 이름을 **`pageSize` 로 추측**해 넣었다.
   실제 이름은 `rowsPerPage`. **이름을 지어낸 것이 결정적 실수.**
   → 같은 마켓의 다른 목록 API(`product/qna/list`)를 먼저 봤어야 했다.
3. `identity` 도 9000 이라 "API 전체가 막혔다"고 결론냈다. 그러나 `identity` 실패는
   별개 사안이며, `product/list` 성공이 그 추론을 무효화한다.
   → **한 호출의 실패로 계층 전체를 단정하지 말 것.**

## 코드 반영 상태

| 파일 | 내용 |
|---|---|
| `shared/platforms/__init__.py` | `LOTTEON["paths"]["list"]` |
| `shared/platforms/lotteon/products.py` | `list_products(page_no=1, rows_per_page=100)` — 페이징 필수 반영 |
| `webapp/routes/live_send_test.py` | `GET /api/live-send-test/product-list` (읽기 전용) |

진단 호출:
```
/api/live-send-test/product-list?market=lotteon&days=30
/api/live-send-test/product-list?market=lotteon&all=1     # 계정 전수
```

## 다음 할 일

1. **지도에 실측 요청·응답 기록** — `product/list` 의 params 에 `pageNo`·`rowsPerPage` 추가,
   `res` 를 실응답으로 교체, 상태를 `검증대기` → `검증완료(ok)` 로.
2. **4대 마켓 판매처 연동** — 이제 상품번호를 가져올 수 있으므로 진행 가능.
   `spdNo` 하나 골라 `product/detail` 로 옵션 읽고 → 모음전 옵션과 매칭 → SetChannel 저장.
3. **11번가·옥션·G마켓 목록 조회** — 같은 패턴으로 연결.
   ※ 이 마켓들도 페이징 필수 여부를 **지도의 다른 목록 API 와 대조**해서 먼저 확인할 것.
4. **지도 응답 스펙 빈칸 46건** (롯데온 41 · 옥션 2 · G마켓 2 · 쿠팡 1) 중
   조회(`recv`) 29건은 실호출로 채울 수 있음. 등록·수정(`send`) 17건은 실호출 금지.
