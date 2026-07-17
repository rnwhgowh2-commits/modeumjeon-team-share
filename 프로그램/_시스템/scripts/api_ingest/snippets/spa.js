// 3️⃣ SPA (Nuxt/Vue/Angular) — ⛔ 스니펫 쓰지 마라
// 언제: 판별에서 `spa:true` 또는 `nuxt:true`.
// 근거·주의: 실측 **0/115 전멸**(롯데온). iframe·링크클릭·`$router.push` **3방식 모두 실패** — 앱이 fresh 컨텍스트에서 `getApiServiceData: null`로 자멸하고 링크 textContent도 빈값. **경로 C(실크롬)로 1API/1콜**이 유일한 길(느려도 그게 된다).
// ⚠️ 자동생성 — 고치려면 webapp/data/api_ingest_paths.json 의 snippets[] 를 고치고 gen_doc.py 재실행

// ⛔ SPA 문서에는 콘솔 스니펫을 쓰지 않는다 (실측 0/115).
// → 경로 C(실크롬): 문서 URL로 navigate → 1초 대기 → DOM/테이블 추출 → 다음 API.
//   느리지만 앱 상태가 살아있어 유일하게 동작한다. (롯데온 109/115 이 방식으로 접수)
