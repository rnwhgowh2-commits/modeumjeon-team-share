// 2️⃣ 서버렌더 + 로그인 게이트 — 같은출처 fetch
// 언제: 로그인해야 보이는 문서(11번가 셀러 개발가이드). **사용자가 로그인한 탭**에서 실행.
// 근거·주의: 실측 **26/26 성공**(11번가). ⚠️`DEC`를 판별에서 나온 charset으로. `MATCH`만 마켓에 맞게.
// ⚠️ 자동생성 — 고치려면 webapp/data/api_ingest_paths.json 의 snippets[] 를 고치고 gen_doc.py 재실행

(async () => {
  const DEC   = new TextDecoder('euc-kr');   // ★판별 charset 그대로. utf-8이면 'utf-8'
  const MATCH = /OpenApiGuide\.tmall/i;      // ← 문서 URL 패턴
  const CAP   = 100000;
  const norm = h => { try { const u = new URL(h, location.href); u.hash=''; return u.href; } catch(e){ return null; } };
  const ok = h => { try { return new URL(h, location.href).origin === location.origin && MATCH.test(h); } catch(e){ return false; } };
  // 페이지에 구조화 스펙 객체가 있으면 통째로(표 파싱보다 정확) — 예: var jsonData = {...}
  const grabObj = (s, key) => { const i = s.indexOf(key); if (i < 0) return '';
    let j = s.indexOf('{', i); if (j < 0) return ''; let dep = 0;
    for (let k = j; k < s.length; k++) { const c = s[k];
      if (c === '{') dep++; else if (c === '}') { dep--; if (!dep) return s.slice(j, k+1); } } return ''; };
  let queue = [norm(location.href), ...[...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(ok).map(norm)];
  queue = [...new Set(queue.filter(Boolean))];
  const seen = new Set(), out = [], P = new DOMParser();
  while (queue.length && out.length < 300) {
    const url = queue.shift(); if (!url || seen.has(url)) continue; seen.add(url);
    try {
      const buf = await (await fetch(url, { credentials: 'include' })).arrayBuffer();
      const html = DEC.decode(buf);
      const d = P.parseFromString(html, 'text/html');
      [...d.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(ok).map(norm)
        .forEach(n => { if (n && !seen.has(n) && !queue.includes(n)) queue.push(n); });
      const tables = [...d.querySelectorAll('table')].map(t =>
        [...t.querySelectorAll('tr')].map(r => [...r.querySelectorAll('th,td')].map(c => (c.textContent||'').replace(/\s+/g,' ').trim())));
      out.push({ url, title: ((d.querySelector('title')||{}).textContent||'').trim(),
        spec: grabObj(html, 'var jsonData'),
        text: (d.body ? d.body.textContent : '').replace(/\s+/g,' ').trim().slice(0, CAP), tables });
    } catch (e) { out.push({ url, error: String(e) }); }
  }
  const b = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(b);
  a.download = 'docs_server.json'; document.body.appendChild(a); a.click();
  console.log(`✅ ${out.length}페이지 · 구조화spec ${out.filter(o=>o.spec).length} · 실패 ${out.filter(o=>o.error).length} → docs_server.json`);
  console.log('한글 확인:', (out[1]||out[0]||{}).text?.slice(0,60));
})();
