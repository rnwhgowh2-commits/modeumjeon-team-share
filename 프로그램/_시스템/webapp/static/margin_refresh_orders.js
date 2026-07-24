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

  /* 며칠치를 다시 훑을지 — 마켓마다 다르다.
     🔴 2026-07-24 실측 사고: 2일만 훑었더니 7/19~7/22 롯데온 주문 35건이 「출고지시·송장
        미입력」으로 굳어 있었다. 롯데온엔 송장이 정상적으로 들어가 있었는데, **우리 저장분이
        낡아서** 마진계산기가 옛 상태를 보고 있었던 것이다(재수집하니 배송완료+송장번호로 바뀜).
        ★주문 상태는 며칠에 걸쳐 계속 바뀐다 — '한 번 수집했으니 끝'이 아니다.
     ⚠️ 그렇다고 무작정 늘리면 안 된다. 옥션은 5일치가 58초라 서버 자체 컷(50초)을 넘고,
        롯데온은 7일치가 500 으로 죽는다(실측). 그래서 마켓별로 실측 안전선을 쓴다. */
  var DAYS_BY_MARKET = {
    auction: 2, gmarket: 2,     /* ESM 은 느리다 — 5일치 58초(서버 컷 50초 초과) */
    lotteon: 5,                 /* 7일치는 500 으로 죽는다(실측) */
    smartstore: 5, coupang: 5, eleven11: 5,
  };
  var DAYS_DEFAULT = 2;

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
          body: JSON.stringify({ market: m.key,
                                 days: DAYS_BY_MARKET[m.key] || DAYS_DEFAULT,
                                 allow_unverified: true }),
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
