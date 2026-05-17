# Day 3 — 변경 이력 (updated_by) 전략

> 팀공유 환경 핵심 — "누가 언제 수정했는지" 추적.
> 사용자 결정 필요. 컷오버 전 확정.

---

## 📋 사용자 결정: "팀 전체가 같은 데이터 공유 (옵션 A)"

이 결정으로 `user_id` per-row 분리는 불필요. 단, **변경 감사 (audit)** 는 여전히 필요. 핵심 질문:

> *"이 가격 어제까지 5만원이었는데, 누가 4만원으로 바꿨지?"*

---

## 🔀 3가지 접근법

### 접근 A. 핵심 테이블에만 `updated_by` 컬럼 (최소 침투)

```python
# 변경되는 핵심 모델에만 추가
class Option(Base):
    ...
    updated_by_id: Optional[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at:    Optional[datetime] = mapped_column(DateTime, onupdate=datetime.utcnow)
```

**대상 (변경 빈도 높음 + 영향 큼)**:
- `options` (가격·재고 변경)
- `models` (모음전 자동화 ON/OFF 토글)
- `option_price_config` (가격 정책)
- `option_source_links` (소싱 매핑)
- `bundle_groups` (모음전 그룹)
- `purchase_orders`, `sales_orders`, `return_orders` (전표)
- `inventory_txs` (재고 트랜잭션 — 이미 created_by 비슷한 게 있을 가능성)

→ ~8 테이블에 컬럼 추가. 기존 `_apply_lightweight_migrations()` 패턴 그대로 ALTER TABLE.

**장점**: 단순, 코드 침투 최소
**단점**: 라우트마다 `updated_by_id = current_user.id` 명시 필요. 누락 위험.

### 접근 B. SQLAlchemy event hook (자동 채움)

```python
from sqlalchemy import event

@event.listens_for(Session, "before_flush")
def _set_updated_by(session, flush_context, instances):
    from flask_login import current_user
    if not current_user or not current_user.is_authenticated:
        return
    for obj in session.dirty | session.new:
        if hasattr(obj, "updated_by_id"):
            obj.updated_by_id = current_user.id
```

**장점**: 라우트별 명시 불필요. 모든 변경에 자동 적용.
**단점**: SQLAlchemy 이벤트 디버깅 어려움. Flask context 결합.

### 접근 C. audit_log 테이블만 활용 (이미 존재 — 39 rows)

```python
# 이미 SQLite 에 audit_log 테이블 + audit/models.py 존재.
# 변경 이벤트를 audit_log 에 row 추가 (현재 컬럼 그대로 활용)
```

기존 `audit_log` 테이블 스키마 확인 후 결정. 이미 39 rows 가 있으므로 **현재도 일부 동작 중일 가능성**.

**장점**: 신규 컬럼 추가 없음. 별도 테이블에 누적 → 이력 검색 가능.
**단점**: per-row 현재 소유자 조회 시 매번 JOIN. UI 표시 시 부담.

---

## 🎯 추천: **하이브리드 (A + C)**

- **A** 핵심 8 테이블에 `updated_by_id` + `updated_at` 추가 → UI 에 "마지막 수정자" 즉시 표시
- **C** 모든 중요 변경은 audit_log 에도 row 누적 → 시계열 이력 조회

```
"이 옵션 누가 마지막에 바꿨어?" → options.updated_by_id (빠름)
"이 옵션 가격 변경 이력 보여줘"   → audit_log 조회 (시계열)
```

---

## 📋 적용 단계 (사용자 승인 후)

### 1단계: 모델에 컬럼 정의 (코드)
8개 모델에 `updated_by_id` (FK users.id, nullable) + `updated_at` 추가.

### 2단계: ALTER TABLE 멱등 추가 (`shared/db.py`)
`migrations` 리스트에 8개 컬럼 추가. dialect-agnostic 패치 덕에 SQLite/PostgreSQL 양쪽 동작.

### 3단계: 자동 채움 — SQLAlchemy event (접근 B 의 hook 만 차용)
모든 라우트 안 건드리고 1곳에서 자동 처리.

### 4단계: audit_log 활용 강화
기존 audit_log 스키마 + 작성 패턴 분석 → 표준 헬퍼 함수화.

### 5단계: UI — 핵심 화면에 "최종 수정: 홍길동 (1시간 전)" 노출

---

## ⚠️ 사용자 결정 필요

1. **접근법 채택**: A / B / C / 하이브리드 (추천) 중 어떤 거?
2. **백필 (backfill)**: 기존 row 의 `updated_by_id` 는 NULL 시작. 또는 "system" 가상 사용자 (id=0) 로 채울지?
3. **UI 노출**: 모든 row 에 마지막 수정자 표시? 아니면 hover 시?
4. **audit_log 정책**: 모든 변경 기록? 핵심 8 테이블만 기록?

답 받으면 Day 3-3 실제 적용 + 마이그레이션 + UI 패치.
