// 1️⃣ 정적 문서 (Docusaurus 등) — iframe 렌더
// 언제: 판별에서 `staticLike:true` · 본문이 **클라이언트 위젯으로 렌더**되는 경우(스스 openapi-explorer)도 이걸로 뚫린다.
// 근거·주의: 실측 **157/157 성공·에러 0**(스마트스토어). `SITEMAP`·`FILTER`만 마켓에 맞게 수정.
// ⚠️ 자동생성 — 고치려면 webapp/data/api_ingest_paths.json 의 snippets[] 를 고치고 gen_doc.py 재실행

(async () => {
  const SITEMAP = location.origin + '/docs/sitemap.xml';   // ← 마켓에 맞게
  const FILTER  = u => u.includes('/docs/') && !u.includes('/schemas/');  // ← 대상 선별
  const CAP     = 100000;   // ★30,000은 대형페이지 절단됨. 넉넉히.
  const sm = await (await fetch(SITEMAP)).text();
  const urls = [...sm.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]).filter(FILTER);
  console.log(`▶ ${urls.length}개 렌더 시작 — 약 ${Math.ceil(urls.length*2.5/60)}분. 탭 닫지 마세요.`);
  const ifr = document.createElement('iframe');
  ifr.style.cssText = 'position:fixed;left:-99999px;top:0;width:1280px;height:1000px;border:0';
  document.body.appendChild(ifr);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const out = [];
  for (let i = 0; i < urls.length; i++) {
    try {
      await new Promise((res, rej) => { const t = setTimeout(() => rej(new Error('timeout')), 20000);
        ifr.onload = () => { clearTimeout(t); res(); }; ifr.src = urls[i]; });
      let d, w = 0;
      while (w < 9000) { d = ifr.contentDocument;
        if (!d.querySelector('.openapi-skeleton,[class*=skeleton]') &&
            d.querySelector('[class*=schema],[class*=openapi],table,article')) break;
        await sleep(250); w += 250; }
      await sleep(250); d = ifr.contentDocument;
      const art = d.querySelector('article,main') || d.body;
      out.push({ url: urls[i], title: ((d.querySelector('h1')||{}).textContent||'').trim(),
        text: (art.textContent||'').replace(/\s+/g,' ').trim().slice(0, CAP),
        hydrated: !d.querySelector('[class*=skeleton]') });
    } catch (e) { out.push({ url: urls[i], error: String(e) }); }
    if (i % 10 === 9 || i === urls.length-1) console.log(`  ${i+1}/${urls.length} …`);
  }
  ifr.remove();
  const b = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(b);
  a.download = 'docs_static.json'; document.body.appendChild(a); a.click();
  console.log(`✅ ${out.length}페이지 · 렌더성공 ${out.filter(o=>o.hydrated).length} · 실패 ${out.filter(o=>o.error).length} → docs_static.json`);
})();
