# 소싱처별 OK캐시백 · 카드 청구할인 시드표

> **계층**: 프로젝트 데이터 문서
> **책임**: 소싱처별 매입가 혜택(OK캐시백 적립율 · 카드 청구할인)의 값·출처·매핑 근거
> **단일 진실 원천(코드)**: `프로그램/_시스템/lemouton/sourcing/source_benefit_seed.py`
> **상위 의존**: `docs/superpowers/specs/2026-06-07-최종매입가-계산엔진-design.md`
> **작성**: 2026-07-19 (대량등록 Phase 1B M1-5)

---

## 1. 저장 방식 — 신규 테이블 없음

소싱처별 혜택은 전부 기존 `source_benefit_templates` (`SourceBenefitTemplate`) 행이다.

| 종류 | apply_mode | pay_method | benefit_type | value | base_ratio | category |
|---|---|---|---|---|---|---|
| OK캐시백 | `cashback` | `NULL` | `rate` | 적립율(0.02 = 2%) | 0.9 또는 1.0 | `캐시백` |
| 카드 청구할인 | `payment` | `PurchaseCard.key` | `rate` | 할인율(0.07 = 7%) | (미사용, 1.0) | `결제` |

- `source_id` 는 **`source_registry.id`** 다 (`SourcingSource.id` 가 아니다).
  이 표엔 key 컬럼이 없어 소싱처 key → id 는 **`main_url` 도메인 매칭**으로 푼다.
- `pay_method` 는 **VARCHAR(16)** — `PurchaseCard.key` 는 이미 16자 이하다. 새 키를 만들지 않는다.
- `base_ratio` 는 **FLOAT DEFAULT 1.0** — `shared/db.py::_apply_lightweight_migrations()` 에
  ADD COLUMN 등록되어 있다(`create_all` 은 기존 테이블에 컬럼을 추가하지 않는다).
  `SourceBenefitTemplate` · `OptionBenefitOverride` **양쪽 모두**에 있다.

---

## 1-2. 캐시백 기준금액 계수(`base_ratio`) — 사장님 확정 2026-07-19

캐시백 사이트는 결제 **전액**이 아니라 **부가세를 뺀 공급가**에 적립해 준다.

```
캐시백 적립 = 기준금액 × 0.9 × 적립율      ← 기본
캐시백 적립 = 기준금액 × 1.0 × 적립율      ← SSG · 신세계쇼핑 · CJ (전액 기준 예외 3사)
```

**예외 3사 = SSG · 신세계쇼핑 · CJ.** 근거는 엑셀 `L`열 수식 원문이다:

```
- ( K * IF(OR(G="SSG", G="신세계쇼핑", G="CJ"), 1, 0.9) * VLOOKUP(G, 캐시백표, 2) )
```

이 중 **신세계쇼핑(3%) · CJ(1.5%) 는 우리 소싱처 명부에 없어 시드 대상이 아니다.**
나중에 소싱처로 추가되면 `base_ratio = 1.0` 으로 넣어야 한다 — 0.9 로 넣으면
캐시백이 10% 덜 깎여 매입가가 과대해진다(안전 방향이지만 틀린 값).

> ⚠️ **적립율에 0.9 를 미리 곱해 넣지 말 것.** 1.1% → 0.99% 로 뭉개면 화면에서
> "왜 1.1%인데 0.99%로 나오지?" 가 되고 근거가 사라진다. 계수는 `base_ratio`
> 컬럼에 따로 두고, 엔진(`final_price._base_ratio`)이 **기준금액 쪽**에만 곱한다.
> 영수증에는 `적립율 1.1%` + `공급가 기준 · 97,270원 × 90% × 1.10% = 962원` 이 함께 뜬다.

계수는 **캐시백 항목에만** 붙는다. 판정은 엔진의 `_is_cashback()` 을 그대로
재사용하므로 카드 청구할인·적립에는 절대 걸리지 않는다.

---

## 2. OK캐시백 — 시드한 값 (영빈 「대량위탁」 엑셀 확정값)

| 엑셀 사이트명 | 적립율 | `base_ratio` | 우리 소싱처 key | 시드 | 근거 |
|---|---|---|---|---|---|
| SSG | 2.0% | **1.0** (전액 예외) | `ssg` | ✅ 시드함 | 도메인 `ssg.com` 1:1. 크롤가이드에도 `OK캐시백 = 베이스금액② × 2%` 로 이미 기재 |
| 롯데온 | 1.1% | **0.9** (공급가) | `lotteon` | ✅ 시드함 | 도메인 `lotteon.com` 1:1 |
| 신세계쇼핑 | 3.0% | **1.0** (전액 예외) | — | ❌ 미시드 | 소싱처 명부에 없음. **추가 시 반드시 1.0** |
| CJ | 1.5% | **1.0** (전액 예외) | — | ❌ 미시드 | 소싱처 명부에 없음. **추가 시 반드시 1.0** |
| H몰(현대H몰) | 2.7% | 0.9 | `hmall` | ⛔ 보류 | 사장님 보류 지시. (추가로 이 소싱처는 매트릭스가 `key:hmall` 문자열 source_id 를 써서 정수 컬럼에 넣을 방법 자체가 없음) |
| 롯데홈쇼핑 | 2.5% | 0.9 | `lotteimall`(추정) | ⛔ 보류 | 사장님 보류 지시. 엑셀 '롯데홈쇼핑' ↔ 우리 `lotteimall`(롯데아이몰) 이 같은 대상인지도 **미확인** |
| 더현대 | 3.0% | 0.9 | — | ❌ 미시드 | 우리 소싱처 명부에 대응 소싱처 없음 |
| GS샵 | 1.6% | 0.9 | — | ❌ 미시드 | 소싱처 명부에 없음 |
| 롯데백화점 | 1.1% | 0.9 | — | ❌ 미시드 | 소싱처 명부에 없음. `lotteon`·`lotteimall` 과 혼동 금지 |
| 11번가 | 0.8% | 0.9 | — | ❌ 미시드 | 우리 시스템에서 **판매처(마켓)**. 소싱처가 아님 |
| 옥션 | 0.5% | 0.9 | — | ❌ 미시드 | 판매처(마켓) |
| 지마켓 | 0.5% | 0.9 | — | ❌ 미시드 | 판매처(마켓) |
| 해당없음 | 0% | — | — | ❌ 미시드 | 0원 차감 행만 늘어남 |

> **애매하면 시드하지 않는다.** 엉뚱한 소싱처에 붙은 혜택은 매입가를 실제보다 낮게
> 잡고(마진 과대) 그대로 판매가 오설정 = 금전 손실이다. 안 넣어서 생기는 손해는
> 매입가 과대(안전 방향)뿐이다.

---

## 3. 카드 청구할인 — 사장님이 채울 빈 표

현재 시드된 행 **0건**. 확인된 값이 없어서 비워 뒀다 (추정치 금지).

`lemouton/sourcing/source_benefit_seed.py` 의 `CARD_DISCOUNT_SEED` 에
`(소싱처 key, PurchaseCard.key, 표시 이름, 할인율)` 로 한 줄씩 추가하면 된다.

| 소싱처 | 소싱처 key | 카드 | PurchaseCard.key | 청구할인율 | 확인 상태 |
|---|---|---|---|---|---|
| 롯데홈쇼핑 | `lotteimall` | 삼성셀렉트 | `samsung_select` | **0.07 (7%)** | 라이브 확인됨 — **단 소싱처가 보류라 시드 안 함** |
| 무신사 | `musinsa` | ? | ? | ? | ❓ 미확인 |
| SSF샵 | `ssf` | ? | ? | ? | ❓ 미확인 |
| 롯데온 | `lotteon` | ? | ? | ? | ❓ 미확인 |
| SSG | `ssg` | ? | ? | ? | ❓ 미확인 |
| 르무통 공홈 | `lemouton` | ? | ? | ? | ❓ 미확인 |
| 스마트스토어 르무통 | `ss_lemouton` | ? | ? | ? | ❓ 미확인 |
| 현대H몰 | `hmall` | ? | ? | ? | ❓ 미확인 (소싱처 보류) |

사용 가능한 `PurchaseCard.key` 17종 (적립율은 카드 마스터가 단일 진실 원천):
`nexon_hyundai`(2.7%) · `lotte_prof`(2%) · `lotte_liiv`(1.5%) · `kbank`(1.1%) ·
`samsung_select`(1%) · `bc_baro`(1%) · `musinsa_hyundai` · `shinhan` · `hana` ·
`kookmin` · `kb_pay` · `kakao_money` · `toss_money` · `mus_money` ·
`mus_money_black` · `mus_money_dia` · `mus_money_plgold`

---

## 4. ✅ 이 시드는 들어가는 순간 가격을 실제로 낮춘다 (정정 2026-07-22 — 스펙 §4-1)

> **종전 문구("시드는 가격을 1원도 바꾸지 않는다 — 캐시백이 택1에서 현대카드에
> 진다")는 낡은 기록이다.** `_compute_legacy` 가 결제 택1 후보에서 캐시백을
> 제외하도록 교정된 뒤(`final_price.py:241~242` · 스펙 §4-1: 캐시백=유입경로 축,
> 카드와 동시 차감)로는 legacy 경로에서도 캐시백과 현대카드 플로어가 **둘 다**
> 차감된다. 고정 테스트: `tests/pricing/test_cashback_axis_separate.py::`
> `test_cashback_coexists_with_hyundai_floor`.

`compute_breakdown` 실측 결과 (표면가 100,000원 · 2026-07-22 재측정):

| 소싱처 | 시드 전 최종매입가 | 시드 후 최종매입가 | OK캐시백 |
|---|---|---|---|
| 롯데온 | 97,200 | **96,300** | 활성 — int(100,000×0.9×1.1%)=989 차감 → 잔액 99,011 → 현대카드 int(99,011×2.73%)=2,703 → 96,308 → 백원버림 |
| SSG | 97,200 | **95,300** | 활성 — int(100,000×1.0×2%)=2,000 차감 → 잔액 98,000 → 현대카드 int(98,000×2.73%)=2,675 → 95,325 → 백원버림 |

카드 청구할인 행이 1건이라도 들어오면 그 소싱처는 tagged 경로(최유리 카드 자동
선택)로 넘어간다 — 캐시백 동시 차감이라는 사실은 tagged 에서도 동일하다.
실측(가정값 삼성카드 7% 를 시드 규약대로 sort_order=60 으로 주입 시 롯데온,
2026-07-22 — 캐시백 sort_order=50 이 앞이라 캐시백부터 차감):

```
OK캐시백 1.1%             -989 → 99,011   (공급가 기준: int(100,000×0.9×1.1%))
삼성카드 청구할인 7%    -6,930 → 92,081   (int(99,011×7%))
삼성셀렉트 적립 1%        -920 → 91,161   최종매입가 91,100 (백원 버림)
```

> ⚠️ 혜택 행을 감싸는 프록시(`card_candidates.TaggedProxy` · 수기입력의
> `bulk/margin._Choice`)는 캐시백 행의 `base_ratio` 를 반드시 함께 옮긴다 —
> 안 옮기면 캐시백이 전액 기준으로 계산돼 10% 과다 차감(매입가 과소 = 위험 방향).
> 고정 테스트: `tests/pricing/test_card_candidates.py::`
> `test_cashback_base_ratio_survives_tagged_proxy` ·
> `test_proxy_slots_carry_every_engine_read_attr`(슬롯 패리티) ·
> `tests/registration/test_manual_margin.py::test_cashback_base_ratio_survives_choice_proxy`.

---

## 5. 멱등 시드 규약

`lemouton/sourcing/source_benefit_seed.py` — `init_db()` 가 부팅마다 호출.

- **(source_id, benefit_name) insert-if-missing.** 기존 행은 절대 덮지 않는다
  → 화면에서 고친 적립율이 재부팅으로 원복되지 않는다.
  (코드베이스 관례: `seed_purchase_cards` key 단위 / `seed_builtins` source_key skip)
- **캐시백 중복 가드**: 그 소싱처에 `apply_mode='cashback'` · `category='캐시백'` ·
  이름에 '캐시백' 인 행이 **하나라도** 있으면 통째로 skip. 이름만 다른 기존 행과
  나란히 들어가 **이중 차감**되는 사고를 막는다.
- `SourceRegistry` 행이 없거나 도메인 매칭이 모호(2건 이상)하면 **만들지 않고 skip**.

---

## 6. 알려진 주의점

1. **`_SITE_BY_SRC` 하드코딩** — `api_benefits.py` 는 `{1:lemouton, 2:ss_lemouton,
   3:musinsa, 4:ssf, 5:lotteon, 6:ssg}` 로 SourceRegistry **id 를 하드코딩**해 사이트를
   판정한다. 라이브 id 배치가 이와 다르면 현대카드 플로어·동적혜택이 엉뚱한 소싱처에
   걸린다. 시드 자체는 도메인 매칭이라 영향받지 않지만, 이 하드코딩은 별도 확인 필요.
2. **크롤가이드 sync 와의 이름 충돌** — `sync_templates_from_crawl_guide()` 는
   `benefit_name` 기준 **upsert** 라, 크롤가이드 혜택 카드에 이름 `OK캐시백` +
   값이 입력되면 이 시드 행의 `value`·`apply_mode`·`enabled` 를 **덮어쓴다**
   (`pay_method`·`category` 는 보존). 가이드 쪽에 OK캐시백 값을 넣을 때 주의.
3. **라이브 미확인** — 이 워크트리는 SQLite 폴백이라 라이브(Supabase)의 기존
   `source_benefit_templates` 행을 볼 수 없다. §5 의 중복 가드가 그 위험에 대한 방어다.
