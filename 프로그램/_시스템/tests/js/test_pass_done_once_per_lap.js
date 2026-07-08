// test_pass_done_once_per_lap.js
//  [2026-07-08 재설계] 회차 중복 근본해결 = 신고자를 '확장 하나'로 단일화.
//  한 바퀴 완료(pass-done)를 페이지(crawl_log.js)와 확장(background.js)이 둘 다 보내면
//  같은 순간(~100ms) 두 신고가 도착해 서버가 회차를 2개 박았다(중복쌍). 그래서 페이지
//  신고자를 제거하고, 확장 runQueueBG 만 유일 신고자로 남긴다. 본 테스트는 소스에서
//  그 불변식(페이지=신고 안 함 / 확장=신고 함)을 못 박는다(재도입 방지).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
let pass = 0, fail = 0;
function t(name, fn) { try { fn(); console.log('  ✅ ' + name); pass++; } catch (e) { console.log('  ❌ ' + name + ' — ' + e.message); fail++; } }

const sys = path.join(__dirname, '..', '..');
const crawlLog = fs.readFileSync(path.join(sys, 'webapp', 'static', 'crawl_log.js'), 'utf8');
const bg = fs.readFileSync(path.join(sys, 'extension', 'moum-crawler', 'background.js'), 'utf8');

// 소스에서 pass-done POST 호출만 뽑기(라인 주석 제외).
function postsPassDone(src) {
  return src.split('\n').some(function (ln) {
    const code = ln.replace(/\/\/.*$/, '');
    return /fetch\(\s*["'`]\/api\/crawl\/pass-done/.test(code)
        || /bgFetch\(\s*["'`]\/api\/crawl\/pass-done/.test(code);
  });
}

console.log('pass-done 신고자 단일화 (확장만):');

t('페이지(crawl_log.js)는 pass-done 을 보내지 않는다 (중복원 제거)', function () {
  assert.strictEqual(postsPassDone(crawlLog), false, 'crawl_log.js 에 pass-done POST 가 남아있음');
});

t('페이지에 passDoneDecision/passPosted 잔재 없음', function () {
  assert.ok(!/passDoneDecision|passPosted/.test(crawlLog), '옛 페이지 신고 로직 잔재');
});

t('확장(background.js)은 pass-done 을 보낸다 (유일 신고자 유지)', function () {
  assert.strictEqual(postsPassDone(bg), true, 'background.js 의 유일 신고자가 사라짐');
});

console.log('\n결과: ' + pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
