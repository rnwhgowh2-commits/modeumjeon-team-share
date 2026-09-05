/* margin_analyze_poll.js — 대용량 매입 엑셀에서 「분석 시작」·업로드가 100초/자원
   벽에 걸리는 것 방지
   ─────────────────────────────────────────────────────────────
   2026-09-05: 매입 12,949행짜리 더망고 엑셀에서 동기 POST /api/margin/analyze 가
   Cloudflare 의 100초 게이트웨이 제한(524)에 걸려 "서버 오류"가 났다. 원인은
   matcher.match_data(원본 무수정 이식, 손대지 않는다)가 매입행 수에 비례해 매출
   전체를 훑는 알고리즘이라 대용량 파일에서 항상 그 벽에 걸린다는 것 — 기간을
   좁혀도 동일하다(매입행 전체를 한 번에 훑기 때문).
   2026-09-06: 업로드(파싱+주문내역 매칭)도 자원이 빠듯한 서버에서 간헐적으로
   45초+ 걸리다 502 로 죽는 게 라이브에서 관측돼 같은 패턴을 걸었다.

   서버는 /api/margin/analyze·/api/margin/upload(둘 다 동기, 기존 그대로) 옆에
   각각 /start(즉시 job_id 반환) + /status/<job_id>(폴링) 를 새로 뒀다.
   화면(margin_embed.html) 은 손대지 않는다 — 본문의 fetch('/api/margin/analyze',
   {method:'POST',...})·fetch('/api/margin/upload', {method:'POST',...}) 호출들이
   전부 그대로 남아 있고, 이 파일이 본문 스크립트보다 먼저 실려 window.fetch 를
   두 지점(analyze·upload)에서만 감싼다 — 그 URL 요청만 start+poll 로 바꿔치기
   하고 그 외 모든 요청은 원래 fetch 그대로 통과시킨다.

   별도 파일인 이유: margin_embed.html 은 원본에서 씨앗(seam)만 바꿔 생성하는
   파일이라(tools/build_margin_embed.py + 동치 가드 테스트) 본문에 로직을 넣지
   않는다. margin_refresh_orders.js 와 같은 패턴. */
(function () {
  'use strict';

  var _nativeFetch = window.fetch.bind(window);
  var POLL_MS = 3000;

  function _sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function _jsonResponse(status, obj) {
    return new Response(JSON.stringify(obj), {
      status: status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  /* statusUrl(jobId) → 폴링 URL. errLabel 은 네트워크 실패 메시지 접두어뿐 —
     기능은 analyze/upload 둘 다 동일(running 이면 계속, error 면 재시도 안내,
     done 이면 job 객체를 넘긴다). */
  async function _pollJob(statusUrl, errLabel) {
    while (true) {
      await _sleep(POLL_MS);
      var statusRes;
      try {
        statusRes = await _nativeFetch(statusUrl);
      } catch (e) {
        return { response: _jsonResponse(502, { error: errLabel + ' 진행 확인 실패: ' + e.message }) };
      }
      if (!statusRes.ok) return { response: statusRes };
      var job = await statusRes.json();
      if (job.status === 'running') continue;
      if (job.status === 'error') {
        return { response: _jsonResponse(job.http_status || 500, { error: job.error || '서버 오류' }) };
      }
      return { job: job };
    }
  }

  async function _pollAnalyzeUntilDone(jobId) {
    var r = await _pollJob('/api/margin/analyze/status/' + jobId, '분석');
    if (r.response) return r.response;
    var job = r.job;
    // done — payload 본체(matched/summary/market/daily/...)는 이미 DB 에 저장돼
    // 있으니 /api/margin/analyses/<id> 로 가져오고, meta(counts 등)와 합쳐
    // 동기 /api/margin/analyze 응답과 같은 모양으로 되돌린다.
    var fullRes;
    try {
      fullRes = await _nativeFetch('/api/margin/analyses/' + job.analysis_id);
    } catch (e) {
      return _jsonResponse(502, { error: '분석 결과 로드 실패: ' + e.message });
    }
    if (!fullRes.ok) return fullRes;
    var full = await fullRes.json();
    var merged = Object.assign(
      { analysis_id: job.analysis_id }, job.meta || {}, full.payload || {});
    return _jsonResponse(200, merged);
  }

  async function _pollUploadUntilDone(jobId) {
    var r = await _pollJob('/api/margin/upload/status/' + jobId, '업로드');
    if (r.response) return r.response;
    // 업로드는 결과 전체(rows/markets/period_from/period_to/shared)가 이미
    // job.meta 에 다 있다 — 별도로 다시 가져올 게 없다(analyze 와 다른 점).
    return _jsonResponse(200, r.job.meta || {});
  }

  window.fetch = function (input, init) {
    var url = (typeof input === 'string') ? input : (input && input.url);
    var method = (init && init.method) || 'GET';
    if (method === 'POST' && url === '/api/margin/analyze') {
      return _nativeFetch('/api/margin/analyze/start', init).then(function (startRes) {
        if (!startRes.ok) return startRes;
        return startRes.json().then(function (data) { return _pollAnalyzeUntilDone(data.job_id); });
      });
    }
    if (method === 'POST' && url === '/api/margin/upload') {
      return _nativeFetch('/api/margin/upload/start', init).then(function (startRes) {
        if (!startRes.ok) return startRes;
        return startRes.json().then(function (data) { return _pollUploadUntilDone(data.job_id); });
      });
    }
    return _nativeFetch(input, init);
  };
})();
