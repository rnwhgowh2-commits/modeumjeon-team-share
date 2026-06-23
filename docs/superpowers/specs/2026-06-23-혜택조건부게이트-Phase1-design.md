# 혜택 조건부 게이트 Phase 1 — 설계 (1a UI + 1b 무신사 게이트)

> **작성**: 2026-06-23 · 가격엔진 정밀 탐색 기반
> **상위**: [[project_crawl_guide_unified_redesign]] C·D 후속. [`docs/크롤링-가이드.md`](../../../프로그램/_시스템/docs/크롤링-가이드.md) 정본.
> **결정(사용자)**: 편집=상세페이지(8탭 제거), 키워드 UI=시안2, 조건 실배선 끝까지, **단계 진행(1a→1b→2)**.

---

## 0. 배경 — 왜 단계인가 (탐색 결론)

조건부 키워드가 실제 최종매입가에 먹으려면 **상품마다 "페이지에 떴던 혜택 문구(텍스트 라인)"를 저장**해뒀다가, 가격계산 때 키워드를 대조해야 한다. 그런데:
- 혜택 문구는 **어디에도 저장 안 됨**(금액·수치만). `gate_benefits`(benefit_gate.py)는 미리보기에서만 호출.
- 크롤러 중 **무신사(확장 crawl-result 경로, api_pricing.py:1144)만 `benefit_lines`를 갖고 있음**. SSF/SSG/navGrab 경로는 라인 미반환.
- `compute_breakdown`(api_benefits.py:406)에 SSG MONEY·기프트포인트 등 **조건 하드코딩** 존재.

→ 전 소싱처 동시 배선은 크롤러+저장+엔진 동시 수술 = 금전위험 과대. **무신사부터 end-to-end 완성·검증 후 확장.**

---

## 1a. UI — 상세페이지 키워드 편집 복원(시안2) + 8탭 제거

### 1a-1. 8번째 탭 제거
`map.html`의 8번째 gtab + `#s8` 섹션 + 혜택설정 JS + `/map` 라우트 `sources` 전달 제거(C·D에서 추가한 것 되돌림). 키보드 regex `[1-8]`→`[1-7]`.

### 1a-2. 상세페이지 혜택 편집기 복원 + 시안2 키워드 UI
`detail.html`/`detail.js`의 ③ 혜택 편집기를 **복원**(C·D Task4에서 제거했던 `#sg-inc` 카드·저장)하되, **기존 키워드 UI(트리거 칩 + sg3-side 공통 제외 패널)는 제거하고 시안2로 교체**:

각 혜택 카드 = `[혜택명][값][유형][조건부 토글][삭제]` + 조건부 ON 시 펼침(**시안2: 적용·제외 2열**):
- **적용**(초록): 키워드 칩 + `하나라도 / 모두` 토글 → `triggers[]` + `match`
- **제외**(빨강): 키워드 칩 + `하나라도 / 모두` 토글 → **신규** `excludes[]` + `exclude_match`
- 맨 아래 평문 요약 1줄.

저장 = 기존 `PUT /sourcing-guide/api/<sid>`(detail.js) 재사용. 읽기전용 요약표·URL·검증은 유지. "모든 모음전 따라쓰기"(aa-btn)도 복원.

### 1a-3. 스키마 — 혜택별 제외 추가
`lemouton/sourcing/crawl_guide.py`:
- `BENEFIT_MATCH = {"any","all"}` 재사용.
- `validate_guide`의 `clean_benefits.append`(:303)에 추가: `"excludes": _strlist(b.get("excludes")), "exclude_match": ("all" if b.get("exclude_match")=="all" else "any")`.
- `empty_skeleton` benefit 기본에도 동일 키(빈 리스트/"any").
- 기존 `triggers`/`match` 유지. 공통 `exclude_keywords`(소싱처 레벨)는 보존하되 UI에선 숨김(하위호환; 게이트는 둘 다 적용).

### 1a-4. ⭐ 기존 혜택 보존 = 상시 적용 (사용자 안전 요구 2026-06-23)
사용자가 이미 URL 조사로 정리해둔 **기존 혜택들은 전부 "상시 적용(status='always', 조건없음)"으로 보존**한다. 마이그레이션/저장 시:
- 기존 benefit 데이터(name/value/method/triggers 등) **무파괴 유지**(collectBenefits 원본 merge 패턴 — C·D에서 검증됨).
- status가 'conditional'이 아닌(또는 비어있는) 기존 혜택은 **'always'로 간주** → 게이트 대상 아님.
- 조건부는 **사용자가 명시적으로 토글 ON + 키워드를 넣은 혜택만**.
- UI: 카드 로드 시 status='conditional' & (triggers 또는 excludes 있음)일 때만 조건부 토글 ON으로 펼침. 그 외 전부 OFF(상시).

**1a는 가격로직 무변경** — 조건 정의·저장까지. 단독 배포 가능.

---

## 1b. 게이트 실배선 — 무신사 (조건이 실제 최종가에 먹음)

### 1b-1. 게이트 함수 — 혜택별 제외 추가
`lemouton/pricing/benefit_gate.py`:
```python
def line_excluded_by_benefit(line, excludes, exclude_match) -> bool:
    kws = [e for e in (excludes or []) if e]
    if not kws: return False
    if exclude_match == "all": return all(k in (line or '') for k in kws)
    return any(k in (line or '') for k in kws)
```
`gate_benefit`(:80) 루프에서 기존 `line_excluded(line, exclude_rules)`(공통) **+** `line_excluded_by_benefit(line, b_excludes, b_exmatch)`(혜택별) 둘 중 하나라도 걸리면 veto. 순수함수 — 유닛테스트.

### 1b-2. 혜택 문구 저장 — 무신사 crawl-result
`webapp/routes/api_pricing.py`(:1128~1162, 무신사 확장 crawl-result): 이미 있는 `benefit_lines`를 `sp.dynamic_benefits_json['_benefit_lines'] = lines`로 **영속**(금액 추출과 병행). 키 `_benefit_lines`(언더바=메타, 금액키와 구분).

### 1b-3. compute_breakdown 게이트 적용 (무신사 한정)
`webapp/routes/api_benefits.py` `compute_breakdown`, `effective` 조립 후 `compute_final_price` 호출(:817) **직전**:
```
if _site_for == 'musinsa':
    lines = _dynamic_benefits.get('_benefit_lines') or []
    if lines:
        guide = _load_guide_benefits(source_id)   # SourceRegistry.crawl_guide 1회(캐시)
        # ⭐ 오직 status=='conditional' 혜택만 게이트 대상. 상시 혜택은 절대 제외 안 함.
        cond = [b for b in guide['benefits'] if b.get('status')=='conditional']
        gated = gate_benefits(cond, lines, guide['exclude_keywords'])
        off = {g['name'] for g in gated if not g['applied']}
        for (kind, item) in effective:
            if getattr(item,'benefit_name','') in off:
                item.enabled = False   # 조건부인데 키워드 미매칭 → 차감 제외
```
**적용 범위 = 가이드에 status='conditional'로 명시된 혜택(이름 매칭)만.** ⭐ **상시(always) 혜택·하드코딩 동적조건은 절대 불변**(라인이 없거나 매칭 실패해도 상시 혜택은 무조건 유지 — 사용자가 정리해둔 기존 혜택 보호). 이름 매칭 = `benefit_name`(유일 키; sync_templates가 가이드 name으로 template 생성하므로 일치).
- `_load_guide_benefits`: `SourceRegistry`에서 crawl_guide 로드, `pricing.benefits`(status='conditional'인 것의 triggers/excludes/match) + `exclude_keywords` 반환. `_cache`에 소싱처별 캐싱.
- **무신사 외 소싱처는 게이트 미적용**(현행 유지) — Phase 2.

### 1b-4. ⚠️ 금전 검증 (필수)
- 유닛: gate(혜택별 excludes) 통과/veto 케이스.
- 라이브: 무신사 한 혜택에 조건부(적용 "후기" / 제외 "불가") 설정 → "후기" 있는 상품엔 적용·"불가" 있는 상품엔 미적용 → **최종매입가가 조건대로 달라지는지** 영수증 단계 실대조. status=always 혜택은 영향 0 확인. 폴백가 안 뜸.

---

## 2. 영향 파일

| 파일 | 1a | 1b |
|---|---|---|
| `webapp/templates/sourcing_guide/map.html` | 8탭 제거 | — |
| `webapp/routes/sourcing_guide.py` | `/map` sources 제거 | — |
| `webapp/templates/sourcing_guide/detail.html`+`detail.js` | 편집기 복원+시안2 키워드 | — |
| `lemouton/sourcing/crawl_guide.py` | excludes/exclude_match 스키마 | — |
| `lemouton/pricing/benefit_gate.py` | — | line_excluded_by_benefit |
| `webapp/routes/api_pricing.py` | — | _benefit_lines 저장(무신사) |
| `webapp/routes/api_benefits.py` | — | compute_breakdown 게이트 적용 |

---

## 3. 무결성·리스크
- **이름 매칭 한계**: 가이드 benefit.name ↔ template.benefit_name 불일치 시 게이트 누락(조용한 실패). → 1b 검증서 실제 적용 확인. 매칭 실패 시 로그/경고.
- **하드코딩 동적조건 공존**: 게이트는 가이드 conditional 혜택만 OFF. 하드코딩(SSG MONEY 등)은 무신사 게이트와 무관(무신사엔 해당 하드코딩 없음). Phase 2서 정책 재검토.
- **폴백가 금지 원칙 유지**: 게이트 OFF는 그 혜택만 차감 제외, 가격 자체는 정상(가격없음 폴백 아님).

---

## 4. 결정 사항 (2026-06-23 사용자)
1. 편집=상세페이지(시안2), 8탭 제거. 2. 조건 실배선 끝까지(목표). 3. **단계: 1a+1b(무신사) 먼저 → 2(확장)**.
