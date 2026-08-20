// 0️⃣ 판별 (제일 먼저 · 1줄)
// 언제: 스니펫 쓰기 전 **무조건 먼저**. 이 결과로 아래 어느 템플릿을 쓸지 갈린다.
// 근거·주의: 정적/SSR이면 `staticLike:true` · SPA면 `spa:true`(→스니펫 금지, 경로 C) · `charset`이 euc-kr이면 디코더 필요
// ⚠️ 자동생성 — 고치려면 webapp/data/api_ingest_paths.json 의 snippets[] 를 고치고 gen_doc.py 재실행

(async () => {
  const r = await fetch(location.href, { credentials: 'include' });
  const ct = r.headers.get('content-type') || '';
  const buf = await r.arrayBuffer();
  const guess = /charset=([\w-]+)/i.exec(ct);
  const cs = (guess ? guess[1] : 'utf-8').toLowerCase();
  const html = new TextDecoder(cs).decode(buf);
  const spa = /<app-root|<div id="?__nuxt|<div id="?root"?><\/div>/i.test(html) && html.length < 12000;
  const gen = (/<meta name="?generator"? content="?([^">]+)/i.exec(html) || [])[1] || '';
  console.log({
    charset: cs,
    length: html.length,
    generator: gen,
    spa,
    staticLike: !spa && html.length > 12000,
    nuxt: !!window.$nuxt,
    sitemap: location.origin + '/sitemap.xml',
    docLinks: document.querySelectorAll('a[href]').length
  });
  console.log('👉 staticLike=true → 템플릿1(정적) · charset=euc-kr 또는 로그인문서 → 템플릿2(서버렌더) · spa/nuxt=true → 스니펫 금지, 경로 C(실크롬)');
})();
