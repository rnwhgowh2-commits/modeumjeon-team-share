# 다중 워커 크롤 시스템 — 설계서

> 상태: 구현 중 (브랜치 `feature/crawl-worker-queue`)
> 작성: 2026-06-06 / live-browser 검증으로 "서버가 크롤 중·무신사·롯데온 실패" 확인 후 착수
> 관계: 프로젝트 CLAUDE.md(데이터 무결성) 종속. 메모리 [[project_live_crawl_server_side]] 근거.

---

## 1. 배경 (왜)

라이브(mou-m.com) 검증 결과, '전체 크롤' 버튼·자동 스케줄러가 **AWS 서버에서 직접 크롤**하고 있었다.
- 정상 4: 르무통공홈·스마트스토어·SSF·SSG (HTTP/API → 서버 OK)
- 실패 2: **무신사**(`LoginExpiredError` — 서버에 로그인 세션 없음), **롯데온**(`playwright chromium 미설치`)
- 서버 크롤이 공용 Supabase 에 error 를 덮어써, 로컬 크롤 성공분도 다음 스케줄러 사이클이 무효화.

→ **누가 트리거하든 실제 크롤은 항상 팀 로컬 PC(실Chrome+로그인)에서** 실행하도록 전환한다.

## 2. 핵심 구조

```
[트리거] 서버 스케줄러 / '전체 크롤' 버튼  →  crawl_jobs 에 잡 등록만 (서버는 크롤 ❌)
                                               ↓ 30초 폴링 (여러 PC 동시)
[워커]   팀 로컬 PC 에이전트 — 우선순위·온라인·로그인 보유 1대가 원자적 선점
                                               ↓
         크롤 실행(실Chrome+로그인) → 결과 Supabase 푸시 → status=done
```

## 3. 확정 정책 (사용자 결정)

| # | 결정 | 값 |
|---|---|---|
| ① PC 식별 | **별명만** (중복 불가). IP 는 선택 보조 | `crawl_workers.name` UNIQUE |
| ② 우선순위 | **숫자 낮을수록 먼저** | `priority` ASC |
| ③ 잡 배정 | **로그인 있는 PC만** | `required_login` ∈ worker `logins_json` |
| ④ 수동 버튼 | **내 PC 고정(pinned)**. 내 PC 오프라인 → 물어보고 다른 PC(큐 폴백) | `routing='pinned'`, `assigned_worker` |
| ⑤ 자동 스케줄러 | **큐(우선순위 경쟁)** | `routing='queue'` |
| ⑥ IP(선택) | 등록 시 그 IP 접속자는 자동으로 그 PC=내 PC 인식. 미등록이면 수동 선택 | `ip_address` nullable |
| ⑦ UI | **시안 A(테이블)** + IP(선택) 컬럼 | — |

## 4. 데이터 모델 (Supabase, `create_all` 자동생성·비파괴)

### crawl_workers — 등록 PC
| 컬럼 | 타입 | 의미 |
|---|---|---|
| name | str UNIQUE | 별명 = 식별자 |
| owner | str | 소유 팀원 |
| enabled | bool=true | 활성/비활성 |
| priority | int=100 | 낮을수록 먼저 |
| logins_json | text=`[]` | 보유 로그인 `["musinsa",...]` |
| ip_address | str? | 선택 — 내 PC 자동인식 |
| last_heartbeat_at | datetime? | ON/OFF 판정(≤90초=온라인) |
| registered_at | datetime | 등록 시각 |

### crawl_jobs — 잡 큐
| 컬럼 | 타입 | 의미 |
|---|---|---|
| model_code | str? idx | NULL=전체 번들 |
| phase | str=crawl | |
| status | str=pending | pending→claimed→running→done\|failed\|expired\|canceled |
| routing | str=queue | queue \| pinned |
| required_login | str? | 'musinsa' 등 / NULL=아무 워커 |
| priority | int=100 | 잡 우선순위 |
| assigned_worker | str? | pinned 대상 별명 |
| worker_name | str? idx | 실제 선점 워커 |
| attempts | int=0 | 재시도 |
| triggered_by | str | scheduler/manual |
| claimed_at / lease_expires_at | datetime? | 선점·리스만료(좀비 방지) |
| started_at / finished_at | datetime? | |
| result_json / error | text? | 결과·에러 |
| created_at | datetime idx | |

## 5. 데이터 무결성 장치 (CLAUDE.md 중복·모순 금지)

1. **원자적 선점** — Postgres `... FOR UPDATE SKIP LOCKED`. 한 잡 = 1대만. 중복 크롤·가격 모순 차단.
2. **하트비트 리스 만료** — 워커 30초 하트비트. 리스(기본 5분) 만료 시 claimed/running → pending(attempts++). 좀비 'running' 재발 방지.
3. **우선순위+ON/OFF 결합** — 워커가 `(priority-1)×지연초` 만큼 늦게 선점 시도 → 1순위 온라인 PC 우선, 꺼지면 2순위 자동 승계. 조율 서버 불필요.
4. **capability 라우팅** — `required_login` 보유 워커만 선점.

## 6. 단계 (마일스톤)

- **Phase 1** — DB 테이블 2개 + 서버 스케줄러/버튼을 "잡 등록만"으로 전환 + 좀비 'running' 정리. ⚠️ 단독 배포 금지(Phase 2 워커 없으면 잡이 안 돌음) — Phase 2 와 함께 배포.
- **Phase 2** — 로컬 워커 에이전트(등록·하트비트·원자적 선점·크롤 실행·결과 푸시·리스 reaper).
- **Phase 3** — 관리 UI(시안 A): 현황·ON/OFF·활성토글·우선순위·IP(선택) + 잡 큐 대시보드.
- **Phase 4** — 다PC 통합검증(중복 선점 0·우선순위·리스만료) + /ui-verify.

## 7. 검증 기준

- 2대 동시 크롤 → 같은 잡 중복 선점 0건 (SQL).
- 1순위 PC 끔 → 2순위 승계.
- 크롤 중 PC 강제종료 → 리스 만료 후 재선점.
- 관리 UI 토글·우선순위 변경이 실제 선점에 반영.

## verify 잡 계약 (가이드 ④ 가격 검증)

- 잡: `crawl_jobs` 에 `phase="verify"`, `verify_url=<대상 URL>`, `required_login=<소싱처 소문자>`, `priority=50` 으로 등록(`crawl_queue.enqueue_verify`). 같은 URL 미완 verify 잡은 재사용(dedup).
- 워커는 verify 잡 선점 시 단건 URL 을 크롤해 아래 `result_json` 을 기록하고 `status="done"`:
  ```json
  {"url":"...","surface_price":42000,"benefit_total":-2100,"final_price":39900,
   "option_stock":"그레이/250 재고○",
   "flags":{"surface_price":"ok","benefit":"warn","final_price":"warn","option_stock":"ok"}}
  ```
- `flags` 는 사니티 가드(`lemouton/sourcing/crawlers/pricing_policy.py::sanity_check`) 결과 기반: 의심 항목 `warn`, 정상 `ok`.
- 실패 시 `status="failed"`, `error=<사유>`. 서버 폴링(`GET /sourcing-guide/api/<id>/verify/<job_id>`)이 done 결과를 `crawl_guide.verification.last_new_check` 에 병합 저장.
- 워커가 아직 verify 미지원이면 잡은 `pending` 유지 → UI 가 "대기 중(온라인 워커 대기)" 표시.
