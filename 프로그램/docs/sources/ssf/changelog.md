# SSF샵 변경기록

---

## 2026-05-17 [방 최초 생성] by claude+rnwhgowh2

### 무엇
- `docs/sources/ssf/` 폴더 신설 (네 번째 소싱처 방)
- 파일: profile.yaml · selectors.yaml · pricing_policy.yaml · login.md · env.example · README.md · changelog.md · _demo_smoke.py

### 코드 분석 결과
- 어댑터: `_시스템/lemouton/sourcing/crawlers/ssf.py` (~460줄)
- 사이트: `www.ssfshop.com/{BRAND}/{GOODSCD}/good`
- 추출: `curl_cffi chrome120` + BeautifulSoup + raw HTML 정규식
- 회원가: 없음 — sale_price 만
- 컬러: 단일 (다른 색상은 별도 GRG 코드 → multi-fetch + merge)
- 기프트포인트·포인트적립: 멤버십 변동값 (raw HTML 정규식)
- auto_card_discount: 현대카드 2.73%
- Fail-safe: sale_price > 0

### 무신사 vs 르무통 vs SSF 비교
| 항목 | 무신사 | 르무통 공홈 | SSF |
|---|---|---|---|
| 회원가 | 9가격항목 | 없음 | 없음 |
| 추출 | Playwright JS | requests+Playwright | curl_cffi + BS4 + regex |
| 멀티 색상 | API variants | DOM (한 페이지) | URL multi-fetch (GRG) |
| 변동 혜택 | 9개 가격항목 | 자동 카드만 | 기프트포인트·포인트 (raw HTML regex) |

### 라이브 검증 결과 (2026-05-17)
- URL: DB models — GRG424102517741 (LEMOUTON 클래식2)
- sale_price = **109,900원**
- 옵션 36개 — **multi-color GRG 자동 발견 정상** (1 URL → 다른 GRG 페이지들 자동 fetch)
- point_rate = 0.005 (멤버십 0.5%, 549P 정상 추출) ✅
- gift_point = null (해당 상품 미노출 — 정상)
- discount_info = 빈 결과 (.tip-txt/.discount 셀렉터 미매칭 — 해당 상품에 노출 없음)
- ✅ 정상 동작

### 관련 메모리
- `project_benefit_spec.md` (④ SSF 항목)

---

(다음 변경 기록은 이 줄 위에 추가)
