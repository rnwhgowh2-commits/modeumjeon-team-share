// test_pass_done_once_per_lap.js
//  [2026-07-08] 자동화 '오늘 N바퀴' 로그가 한 바퀴에 모음전 개수(x)만큼 뛰던 버그의 회귀 테스트.
//  근본원인: crawl_log.js renderHeader 가 '선택(selected) 모음전' 하나가 100%/done 될 때마다
//    /api/crawl/pass-done 를 발사했다. selected 는 크롤 중 모음전을 자동 추종하므로
//    한 패스(전체 큐)에 모음전이 x개면 pass-done 이 x번 나가 CrawlLapRun 이 x행 생겼다.
//    (서버 20초 디듀프는 모음전 완료 간격이 그보다 커서 못 막음.)
//  수정: 실행 전체가 끝난 순간(도는/대기 모음전 0 + done ≥1 + stop 0)에만 딱 1회 발사.
//  본 파일은 배포 로직(passDoneDecision)을 복제해, 한 패스 = pass-done 1회임을 못박는다.
const assert = require('assert');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

// ── 배포 로직 복제 (crawl_log.js renderHeader 의 pass-done 판정) ──────────
//   statuses = 이번 실행의 모음전 상태 배열(order.map(status)).
//   prevPosted = 직전 passPosted 플래그. 반환 {post, posted}.
function passDoneDecision(statuses, prevPosted) {
  var pending = false, done = 0, stopped = 0;
  for (var i = 0; i < statuses.length; i++) {
    var s = statuses[i];
    if (s === 'run' || s === 'pause' || s === 'wait') pending = true;   // 큐 미소진
    else if (s === 'done') done++;
    else if (s === 'stop') stopped++;
  }
  if (pending) return { post: false, posted: false };                    // 진행 중 → 재무장
  if (done > 0 && stopped === 0 && !prevPosted) return { post: true, posted: true };
  return { post: false, posted: prevPosted };
}

// 상태 시퀀스를 순서대로 흘려 pass-done 발사 횟수를 센다(renderHeader 반복 호출 모사).
function countPosts(sequence) {
  var posted = false, posts = 0;
  sequence.forEach(function (statuses) {
    var d = passDoneDecision(statuses, posted);
    posted = d.posted;
    if (d.post) posts++;
  });
  return posts;
}

// 큐 N개(모두 wait 로 선등록) 를 하나씩 크롤하는 현실적 상태 시퀀스 생성.
function passSequence(n) {
  var seq = [];
  var st = [];
  for (var i = 0; i < n; i++) st.push('wait');
  for (var i = 0; i < n; i++) {
    st = st.slice(); st[i] = 'run'; seq.push(st.slice());       // i 시작
    seq.push(st.slice());                                        // 진행 렌더(중복 호출)
    st = st.slice(); st[i] = 'done'; seq.push(st.slice());       // i 완료
  }
  seq.push(st.slice());                                          // 큐 비움 정착 렌더
  return seq;
}

console.log('pass-done 발사 = 패스당 1회 (오늘 바퀴 +1):');

t('모음전 5개 한 패스 → pass-done 딱 1회 (버그: 5회였음)', function () {
  assert.strictEqual(countPosts(passSequence(5)), 1);
});

t('모음전 1개 한 패스 → 1회', function () {
  assert.strictEqual(countPosts(passSequence(1)), 1);
});

t('모음전 10개 한 패스 → 1회 (개수 무관)', function () {
  assert.strictEqual(countPosts(passSequence(10)), 1);
});

t('연속 2패스 → 2회 (패스마다 정확히 +1)', function () {
  var seq = passSequence(3).concat(passSequence(3));   // 두 번째 패스는 새 run 이 플래그 재무장
  assert.strictEqual(countPosts(seq), 2);
});

t('중지된 패스(일부 stop) → 0회 (확장 !wasStopped 와 동일, 가짜 바퀴 금지)', function () {
  var seq = [['run', 'wait'], ['done', 'run'], ['done', 'stop']];
  assert.strictEqual(countPosts(seq), 0);
});

t('전부 실패로 done 0 → 0회 (spurious 바퀴 방지)', function () {
  var seq = [['run'], ['stop']];
  assert.strictEqual(countPosts(seq), 0);
});

t('패스 진행 중(대기 모음전 남음)엔 발사 안 함 — 모음전 사이 조기발사 금지', function () {
  // b1 done 이지만 b2 아직 wait → pending, 발사 0
  assert.strictEqual(countPosts([['run', 'wait'], ['done', 'wait']]), 0);
});

// ── 버그 재현 대조군: 옛 '선택 모음전 단위' 로직은 x회 발사 (수정 전 동작) ──
function oldPerBundlePosts(n) {
  // 옛 로직: 각 모음전이 done 되는 순간(선택 추종) __passPosted 없으면 1회. → n회.
  var posts = 0, flags = {};
  for (var i = 0; i < n; i++) {
    if (!flags[i]) { flags[i] = true; posts++; }   // 모음전 i 완료 → 발사
  }
  return posts;
}
t('[대조] 옛 로직은 모음전 5개 → 5회 (버그 재현 — 이 테스트가 회귀를 막음)', function () {
  assert.strictEqual(oldPerBundlePosts(5), 5);
  assert.notStrictEqual(oldPerBundlePosts(5), countPosts(passSequence(5)));  // 5 ≠ 1
});

console.log('\n결과: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
