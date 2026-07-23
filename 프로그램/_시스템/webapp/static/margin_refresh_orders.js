/* margin_refresh_orders.js — 마진계산기 「최신까지 불러오기」
   ─────────────────────────────────────────────────────────────
   마진 분석은 **이미 저장된 주문만** 읽는다(빠름). 최신 주문이 필요할 때 이 버튼이
   적재를 갱신한다.

   🔴 반드시 마켓을 **1개씩** 부른다.
      2026-07-23 라이브 실측 — 최근 5일 조회 소요:
        옥션 58.1초 · G마켓 46.5초 · 스스 26.4초 · 쿠팡 11.5초 · 11번가 8.3초 · 롯데온 4.1초
        6마켓을 한 요청에 묶으면 61.7초 → 서버 상한을 넘겨 워커가 죽고, 응답이 JSON 이
        아니게 되어 화면엔 "서버 오류"만 뜬다(실제로 분석이 매번 실패했다).
      주문내역 탭이 멀쩡한 이유도 마켓을 나눠 부르기 때문이다. 같은 방식을 따른다.

   서버(/api/orders-ingest/run-sync)는 자체적으로 50초에 끊고 사유를 JSON 으로 준다 —
   그래서 이 호출들은 서버 상한에 걸리지 않는다.

   별도 파일인 이유: margin_embed.html 은 원본에서 씨앗(seam)만 바꿔 생성하는 파일이라
   (tools/build_margin_embed.py + 동치 가드 테스트) 본문에 로직을 넣지 않는다.
   margin_ext_check.js 와 같은 패턴. */
(function () {
  'use strict';

  var MARKETS = [
    { key: 'auction',    name: '옥션' },
    { key: 'gmarket',    name: 'G마켓' },
    { key: 'smartstore', name: '스마트스토어' },
    { key: 'coupang',    name: '쿠팡' },
    { key: 'eleven11',   name: '11번가' },
    { key: 'lotteon',    name: '롯데온' },
  ];

  /* days=2: 적재는 스케줄러가 20분마다 채우므로 최근 이틀이면 충분하고, 그래야 각
     호출이 서버의 50초 컷 안에 끝난다(가장 느린 옥션 기준). */
  var DAYS = 2;

  /* opts.keepMessage=true : 「분석 시작」이 먼저 부르는 경우. 끝 인사("이제 분석
     시작을 눌러 주세요")를 남기지 않는다 — 바로 분석이 이어지므로 틀린 안내가 된다.
     실패 목록은 이 경우에도 남긴다(조용한 실패 금지). */
  async function refreshOrdersToNow(opts) {
    opts = opts || {};
    var btn = document.getElementById('refreshOrdersBtn');
    var msg = document.getElementById('analyzeMsg');
    var total = MARKETS.length;
    var done = 0;
    var failed = [];

    if (btn) btn.disabled = true;
    if (msg) msg.textContent = '최근 주문 불러오는 중… 0/' + total;

    await Promise.all(MARKETS.map(async function (m) {
      try {
        var res = await fetch('/api/orders-ingest/run-sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market: m.key, days: DAYS, allow_unverified: true }),
        });
        var j = null;
        try { j = await res.json(); } catch (_) { j = null; }
        if (!res.ok || !j || !j.ok) {
          /* 실패를 삼키지 않는다 — 어느 마켓이 왜 안 들어왔는지 그대로 보여준다. */
          failed.push(m.name + (j && j.error ? ' (' + j.error + ')' : ' (' + res.status + ')'));
        }
      } catch (e) {
        failed.push(m.name + ' (' + (e && e.message ? e.message : e) + ')');
      }
      done++;
      if (msg) msg.textContent = '최근 주문 불러오는 중… ' + done + '/' + total;
    }));

    if (btn) btn.disabled = false;
    if (msg) {
      if (failed.length) {
        msg.textContent = '일부 마켓을 못 불러왔어요: ' + failed.join(' · ')
          + ' — 나머지 마켓은 최신입니다.';
      } else if (!opts.keepMessage) {
        msg.textContent = '최신까지 불러왔어요. 이제 「분석 시작」을 눌러 주세요.';
      }
    }
    return { failed: failed, total: total };
  }

  window.refreshOrdersToNow = refreshOrdersToNow;
})();
