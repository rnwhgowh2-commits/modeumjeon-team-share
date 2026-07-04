(function(){
  const root = document.querySelector('.sg-wrap');
  const sid = root.dataset.sid;
  document.querySelectorAll('.sg-sub button').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.sg-sub button').forEach(x=>x.classList.toggle('on',x===b));
    document.getElementById('sub-sample').classList.toggle('on', b.dataset.sub==='sample');
    document.getElementById('sub-new').classList.toggle('on', b.dataset.sub==='new');
  }));

  // ── collect() — ①URL + ②fields + ③benefits (새 2축 모델) ──────────────────
  function collect(){
    const base = (window.__guideInit ? JSON.parse(JSON.stringify(window.__guideInit)) : {version:2, pricing:{}});
    base.version = 2;

    // ① 기준 샘플 URL
    base.sample_urls = [...document.querySelectorAll('#sg-urls .sg-urlrow')].map(r=>(
      {url:r.dataset.url, is_lead:!!r.querySelector('.tagk')}));

    // ② 크롤 구조 분석 필드
    const fields={};
    document.querySelectorAll('#sg-fields tr[data-field]').forEach(tr=>{
      const noteEl = tr.nextElementSibling && tr.nextElementSibling.classList.contains('note-row')
        ? tr.nextElementSibling.querySelector('.sg-note') : null;
      fields[tr.dataset.field]={
        method: tr.dataset.method || 'none',
        mechanism: tr.dataset.mechanism || 'none',
        auth: tr.dataset.auth || 'open',
        locator: tr.querySelector('.sg-loc').value,
        status: tr.dataset.status || 'none',
        note: noteEl ? noteEl.value : ''
      };
    });
    base.fields = fields;

    // ③ 혜택 — 2축 모델 (value_source / status / triggers / excludes)
    base.pricing = base.pricing || {base_label:'표면 노출가', benefit_collection:'per_product', benefits:[], note:''};
    const origBenefits = (window.__guideInit && window.__guideInit.pricing && window.__guideInit.pricing.benefits) || [];
    const benefits = [];
    document.querySelectorAll('#sg-inc .bcard').forEach((c, idx)=>{
      const name = c.querySelector('.bn').value.trim();
      if(!name) return;
      const vs = c.dataset.vs || 'fixed';   // fixed | crawl
      const valEl = c.querySelector('.bval');
      const valRaw = valEl ? valEl.value.replace(/,/g,'').trim() : '';
      const value = (vs === 'fixed' && valRaw !== '') ? (parseFloat(valRaw) || null) : null;
      // 적용 상태: 고정값→always 강제, 크롤값→조건부 토글에서 읽기
      const status = (vs === 'fixed') ? 'always'
        : (c.querySelector('.ctg.on') ? 'conditional' : 'always');
      // 조건부일 때 triggers/excludes/match 수집
      const isConditional = (status === 'conditional');
      const chipTexts = (el, cls) => [...(el ? el.querySelectorAll('.chip'+cls) : [])].map(ch=>{
        // chip 내부 i 태그 제외하고 텍스트만
        return [...ch.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim();
      }).filter(Boolean);
      const trigChips = chipTexts(c.querySelector('.trig-chips'), '.i');
      const exclChips = chipTexts(c.querySelector('.excl-chips'), '.e');
      const tmEl = c.querySelector('.tm.on');
      const emEl = c.querySelector('.em.on');
      // 기존 benefit 원본 merge (미편집 필드 보존: base, freq, method, rule 등)
      const orig = origBenefits[idx] || {};
      benefits.push({
        ...orig,          // base/freq/rule/apply 등 미편집 필드 보존
        name,
        value_source: vs,
        value: value,
        method: c.querySelector('.b-ty') ? c.querySelector('.b-ty').value : (orig.method || '정률(%)'),
        status,
        triggers: isConditional ? trigChips : (orig.triggers || []),
        match: (isConditional && tmEl) ? tmEl.dataset.m : (orig.match || 'any'),
        excludes: isConditional ? exclChips : (orig.excludes || []),
        exclude_match: (isConditional && emEl) ? emEl.dataset.m : (orig.exclude_match || 'any'),
      });
    });
    base.pricing.benefits = benefits;
    // exclude_keywords(소싱처 공통제외) — 이 페이지에서 UI 없음, 원본 보존
    base.exclude_keywords = (window.__guideInit && window.__guideInit.exclude_keywords) || [];
    return base;
  }

  // ── 시안2 v3 카드 상호작용 ─────────────────────────────────────────────────
  const incEl = document.getElementById('sg-inc');

  // 값출처 세그 클릭 — 고정↔크롤 전환
  function setVs(card, vs){
    card.dataset.vs = vs;
    card.querySelectorAll('.vseg b').forEach(b=>{
      const isCrawl = b.dataset.v === 'crawl';
      b.classList.toggle('on', b.dataset.v === vs);
      if(isCrawl) b.classList.toggle('crawl', vs === 'crawl');
    });
    const valInput = card.querySelector('.bval');
    const crawlBadge = card.querySelector('.bcrawl');
    const alwaysBadge = card.querySelector('.always');
    const ctgToggle = card.querySelector('.ctg');
    if(vs === 'fixed'){
      // 고정값: 값 입력칸 노출, 크롤값 badge 숨김
      if(valInput) valInput.style.display = '';
      if(crawlBadge) crawlBadge.style.display = 'none';
      // 적용: 상시 배지 노출, 조건부 토글 숨김 + status → always 강제
      if(alwaysBadge) alwaysBadge.style.display = '';
      if(ctgToggle){ ctgToggle.style.display = 'none'; ctgToggle.classList.remove('on'); }
      card.dataset.status = 'always';
      // 조건 패널 닫기
      const condEl = card.querySelector('.cond');
      if(condEl) condEl.style.display = 'none';
    } else {
      // 크롤값: 크롤값 badge 노출, 값 입력칸 숨김
      if(valInput) valInput.style.display = 'none';
      if(crawlBadge) crawlBadge.style.display = '';
      // 적용: 상시 배지 숨김, 조건부 토글 노출
      if(alwaysBadge) alwaysBadge.style.display = 'none';
      if(ctgToggle) ctgToggle.style.display = '';
    }
  }

  // 조건부 토글 클릭
  function toggleCtg(card){
    const ctg = card.querySelector('.ctg');
    if(!ctg) return;
    const on = !ctg.classList.contains('on');
    ctg.classList.toggle('on', on);
    card.dataset.status = on ? 'conditional' : 'always';
    const condEl = card.querySelector('.cond');
    if(condEl) condEl.style.display = on ? 'grid' : 'none';
    updateCsum(card);
  }

  // 조건 요약 줄 갱신
  function updateCsum(card){
    const csumEl = card.querySelector('.csum');
    if(!csumEl) return;
    const trigs = [...card.querySelectorAll('.trig-chips .chip.i')].map(ch=>[...ch.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim()).filter(Boolean);
    const excls = [...card.querySelectorAll('.excl-chips .chip.e')].map(ch=>[...ch.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim()).filter(Boolean);
    const tm = (card.querySelector('.tm.on')||{}).dataset||{m:'any'};
    const em = (card.querySelector('.em.on')||{}).dataset||{m:'any'};
    let s = '';
    if(trigs.length) s += `적용: "${trigs.join('", "')}" ${tm.m==='all'?'모두':'하나라도'} 포함`;
    if(excls.length) s += (s?'  /  ':'') + `제외: "${excls.join('", "')}" ${em.m==='all'?'모두':'하나라도'} 포함`;
    csumEl.textContent = s || '';
  }

  // 칩 생성
  function makeChip(text, cls){
    const sp = document.createElement('span');
    sp.className = 'chip ' + cls;
    sp.appendChild(document.createTextNode(text));
    const i = document.createElement('i');
    i.textContent = '×'; i.dataset.role = 'del';
    sp.appendChild(i);
    return sp;
  }

  // 새 카드 생성 (+ 혜택 추가 버튼용)
  let _ridx = 50000;
  function newCard(){
    const card = document.createElement('div');
    card.className = 'bcard GR';
    card.dataset.vs = 'fixed';
    card.dataset.status = 'always';
    card.innerHTML =
      `<input class="bn" placeholder="혜택명">` +
      `<div class="vseg"><b class="vs-fixed on" data-v="fixed">고정값</b><b class="vs-crawl" data-v="crawl">크롤값</b></div>` +
      `<div class="val-cell"><input class="bval" type="number" step="any" placeholder="0"><div class="bcrawl" style="display:none">크롤값 ⟳</div></div>` +
      `<select class="b-ty"><option>정률(%)</option><option>정액(원)</option><option>정액·정률</option><option>적립(%→원)</option><option>고정액</option><option>옵션(개월)</option></select>` +
      `<div class="apply-cell"><div class="always">✓ 상시</div><div class="ctg" style="display:none"><span class="sw"><i></i></span>조건부</div></div>` +
      `<button type="button" class="bdel" title="삭제">×</button>` +
      `<div class="cond" style="display:none;grid-column:1/-1">` +
        `<div><div class="clab i">적용 키워드 <span class="modeg"><b class="tm on" data-m="any">하나라도</b><b class="tm" data-m="all">모두</b></span></div>` +
        `<div class="chips trig-chips"><input class="cin trig-in" placeholder="키워드 추가…"></div></div>` +
        `<div><div class="clab e">제외 키워드 <span class="modeg"><b class="em on" data-m="any">하나라도</b><b class="em" data-m="all">모두</b></span></div>` +
        `<div class="chips excl-chips"><input class="cin excl-in" placeholder="제외 키워드 추가…"></div>` +
        `<div class="kw-hint">여러 개는 쉼표로 한 번에</div></div>` +
        `<div class="csum"></div>` +
      `</div>`;
    return card;
  }

  if(incEl){
    // 이벤트 위임 — 클릭
    incEl.addEventListener('click', e=>{
      const card = e.target.closest('.bcard');
      if(!card) return;
      // 삭제
      if(e.target.classList.contains('bdel')){ card.remove(); return; }
      // 값출처 세그
      if(e.target.closest('.vseg') && e.target.dataset.v){ setVs(card, e.target.dataset.v); return; }
      // 조건부 토글
      if(e.target.closest('.ctg')){ toggleCtg(card); return; }
      // 하나라도/모두 토글 (적용 키워드)
      if(e.target.classList.contains('tm')){
        card.querySelectorAll('.tm').forEach(b=>b.classList.toggle('on', b===e.target));
        updateCsum(card); return;
      }
      // 하나라도/모두 토글 (제외 키워드)
      if(e.target.classList.contains('em')){
        card.querySelectorAll('.em').forEach(b=>b.classList.toggle('on', b===e.target));
        updateCsum(card); return;
      }
      // 칩 삭제
      if(e.target.dataset.role === 'del' && e.target.parentElement.classList.contains('chip')){
        e.target.parentElement.remove();
        updateCsum(card); return;
      }
    });

    // 쉼표(,/，) 기준으로 여러 키워드 분리 — 빈 토큰 제거
    const splitKeywords = (raw) => raw.split(/[,，]/).map(s=>s.trim()).filter(Boolean);

    // 여러 키워드를 한 번에 칩으로 추가 (기존 makeChip 재사용)
    function addChips(card, chipsEl, refInput, cls, raw){
      const words = splitKeywords(raw);
      words.forEach(w=> chipsEl.insertBefore(makeChip(w, cls), refInput));
      if(words.length) updateCsum(card);
      return words.length > 0;
    }

    // 칩 Enter 추가 (쉼표로 구분된 여러 단어 = 여러 칩)
    incEl.addEventListener('keydown', e=>{
      if(e.key !== 'Enter') return;
      const t = e.target;
      const card = t.closest('.bcard');
      if(!card) return;
      e.preventDefault();
      const v = t.value.trim(); if(!v) return;
      if(t.classList.contains('trig-in')){
        const chips = card.querySelector('.trig-chips');
        if(addChips(card, chips, t, 'i', v)) t.value = '';
      } else if(t.classList.contains('excl-in')){
        const chips = card.querySelector('.excl-chips');
        if(addChips(card, chips, t, 'e', v)) t.value = '';
      }
    });

    // 쉼표 포함 텍스트 붙여넣기 → 여러 칩으로 분리
    incEl.addEventListener('paste', e=>{
      const t = e.target;
      if(!t.classList || !(t.classList.contains('trig-in') || t.classList.contains('excl-in'))) return;
      const text = (e.clipboardData || window.clipboardData).getData('text');
      if(!text || text.indexOf(',') === -1 && text.indexOf('，') === -1) return; // 쉼표 없으면 기본 붙여넣기 동작 유지
      e.preventDefault();
      const card = t.closest('.bcard');
      if(!card) return;
      if(t.classList.contains('trig-in')){
        const chips = card.querySelector('.trig-chips');
        addChips(card, chips, t, 'i', text);
      } else {
        const chips = card.querySelector('.excl-chips');
        addChips(card, chips, t, 'e', text);
      }
      t.value = '';
    });
  }

  // + 혜택 추가 버튼
  const addBtn = document.querySelector('.inc-add');
  if(addBtn){ addBtn.addEventListener('click', ()=>{ incEl.appendChild(newCard()); }); }

  // ── 저장 버튼 ──────────────────────────────────────────────────────────────
  var cb=document.getElementById('aa-confirm'), btn=document.getElementById('aa-btn'), toast=document.getElementById('aa-toast');
  if(cb&&btn){
    cb.addEventListener('change',()=>{
      btn.disabled=!cb.checked;
      btn.style.background=cb.checked?'#E0392B':'#F4C7CB';
      btn.style.cursor=cb.checked?'pointer':'not-allowed';
      btn.textContent=cb.checked?'🔓 따라쓰기 실행':'🔒 따라쓰기 (잠김)';
    });
    btn.addEventListener('click',async ()=>{
      if(!cb.checked) return;
      const payload=collect();
      const valued=((payload.pricing&&payload.pricing.benefits)||[]).filter(b=>
        b.value!=null && !(String(b.method||'').indexOf('개월')>=0));
      if(valued.length){
        const names=valued.map(b=>b.name).join(', ');
        const ok=confirm('저장하면 이 소싱처 혜택 기본값('+valued.length+'개: '+names+')이\n'+
          '전(全) 모음전에 덮어써집니다. 모음전별로 따로 수정한 값은 사라지며 되돌릴 수 없습니다.\n\n계속할까요?');
        payload.apply_to_bundles = ok;
      }
      const res=await fetch(`/api/source-benefits/templates/${sid}/apply-to-all`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const j=await res.json();
      if(!j.ok){ if(toast){toast.textContent='따라쓰기 실패: '+(j.message||j.error);toast.style.display='block';} return; }
      if(toast){toast.textContent='따라쓰기 완료';toast.style.color='#0E7C3A';toast.style.display='block';}
      // E: 다른 탭에 열린 매트릭스 자동 갱신 신호
      try{ localStorage.setItem('moum_matrix_stale', String(Date.now())); }catch(e){}
    });
  }

  document.getElementById('sg-save').addEventListener('click', async ()=>{
    const payload=collect();
    const res=await fetch(`/sourcing-guide/api/${sid}`,{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const j=await res.json();
    if(!j.ok){ alert('저장 실패: '+(j.message||j.error)); return; }
    let msg='저장됨';
    if(j.benefits_synced) msg+=' · 기본셋팅 '+j.benefits_synced+'개 반영';
    if(j.bundles_applied) msg+=' · 모음전 '+j.bundles_applied+'개 덮어씀';
    // E: 다른 탭에 열린 매트릭스 자동 갱신 신호
    try{ localStorage.setItem('moum_matrix_stale', String(Date.now())); }catch(e){}
    alert(msg);
  });

  // ── ④ 가격 검증 ────────────────────────────────────────────────────────────
  const stEl=document.getElementById('sg-verify-status');
  const msgEl=document.getElementById('sg-verify-msg');
  const resEl=document.getElementById('sg-verify-result');
  function receipt(c){
    const f=(c.flags||{});
    const chk=(k)=> f[k]==='warn'? '<span class="sg-vchk warn">⚠️</span>':'<span class="sg-vchk ok">✅</span>';
    return `<div class="fxpop" style="margin-top:14px;"><div class="body"><div class="cf-receipt">
      <div class="cf-rc-ln"><span class="lbl">표면 노출가</span><span class="num">${c.surface_price}원 ${chk('surface_price')}</span></div>
      <div class="cf-rc-ln disc"><span class="lbl">적용 혜택</span><span class="num">${c.benefit_total}원 ${chk('benefit')}</span></div>
      <div class="cf-rc-div"></div>
      <div class="cf-rc-ln fin"><span class="lbl">최종 매입가</span><span class="num">${c.final_price}원</span></div>
      <div class="cf-rc-div"></div>
      <div class="cf-rc-ln"><span class="lbl">옵션·재고</span><span class="num">${c.option_stock||''} ${chk('option_stock')}</span></div>
    </div></div></div>`;
  }
  let pollTimer=null;
  async function poll(jobId){
    const res=await fetch(`/sourcing-guide/api/${sid}/verify/${jobId}`);
    const j=await res.json();
    const job=j.job||{};
    msgEl.textContent = ({pending:'대기 중(온라인 워커 대기)',claimed:'워커 선점됨',
      running:`크롤 중 · 워커 ${job.worker_name||''}`,done:'완료',failed:'실패'})[job.status]||job.status;
    if(job.status==='done' && job.result){ clearInterval(pollTimer); resEl.innerHTML=receipt(job.result); }
    else if(job.status==='failed'){ clearInterval(pollTimer); resEl.innerHTML=`<div class="muted">검증 실패: ${job.error||''}</div>`; }
  }
  document.getElementById('sg-verify-btn').addEventListener('click', async ()=>{
    const url=document.getElementById('sg-verify-url').value.trim();
    if(!url) return;
    const res=await fetch(`/sourcing-guide/api/${sid}/verify`,{method:'POST',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({url})});
    const j=await res.json();
    if(!j.ok){ alert('검증 요청 실패: '+(j.message||j.error)); return; }
    stEl.style.display='inline-flex'; resEl.innerHTML='';
    if(pollTimer) clearInterval(pollTimer);
    poll(j.job_id); pollTimer=setInterval(()=>poll(j.job_id), 2500);
  });

  // 🔑 키워드 게이트 검증
  const kwBtn=document.getElementById('sg-kw-btn');
  const kwRes=document.getElementById('sg-kw-result');
  const KW_AMOUNTS={
    "등급 할인":{type:"amount",value:0}, "상품 쿠폰":{type:"amount",value:5000},
    "구매적립":{type:"rate",value:0.10}, "후기 적립":{type:"rate",value:0.01},
    "결제 적립":{type:"rate",value:0.0},
  };
  function kwReceipt(j){
    const rows=(j.gated||[]).map(g=>{
      const mark = g.applied
        ? '<span style="color:#22A06B;font-weight:800;">● 적용</span>'
        : ((g.excluded&&g.excluded.length)
            ? '<span style="color:#E5484D;font-weight:800;">✕ 제외</span>'
            : '<span style="color:#8B95A1;font-weight:700;">○ 미적용</span>');
      return `<div class="cf-rc-ln"><span class="lbl">${g.name} &nbsp;${mark}</span>`+
             `<span class="num" style="font-size:11px;color:#6B7684;font-weight:600;">${g.reason}</span></div>`;
    }).join('');
    const price=(j.final_price!=null)
      ? `<div class="cf-rc-div"></div><div class="cf-rc-ln"><span class="lbl">표면 노출가</span><span class="num">${(j.base_price||0).toLocaleString()}원</span></div>`+
        `<div class="cf-rc-div"></div><div class="cf-rc-ln fin"><span class="lbl">최종 매입가</span><span class="num">${j.final_price.toLocaleString()}원</span></div>`
      : '';
    const save=`<div style="margin-top:11px;display:flex;align-items:center;gap:10px;">`+
      `<button id="sg-kw-save" style="background:#191F28;color:#fff;border:none;border-radius:8px;padding:8px 14px;font-size:12px;font-weight:700;cursor:pointer;">✓ 이 검증 결과 저장</button>`+
      `<span id="sg-kw-save-msg" style="font-size:11.5px;color:#6B7684;"></span></div>`;
    return `<div class="fxpop" style="margin-top:13px;"><div class="body"><div class="cf-receipt">${rows}${price}</div></div></div>${save}`;
  }
  if(kwBtn){
    kwBtn.addEventListener('click', async ()=>{
      const lines=document.getElementById('sg-kw-lines').value.split('\n').map(s=>s.trim()).filter(Boolean);
      if(!lines.length){ alert('크롤된 혜택 라인을 입력하세요 (한 줄에 하나).'); return; }
      const base=parseFloat(document.getElementById('sg-kw-base').value)||0;
      const body={benefit_lines:lines};
      if(base>0){ body.base_price=base; body.amounts=KW_AMOUNTS; }
      kwRes.innerHTML='<div class="muted" style="margin-top:10px;">검증 중…</div>';
      try{
        const r=await fetch(`/sourcing-guide/api/${sid}/gate-preview`,{method:'POST',
          headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const j=await r.json();
        window.__lastGate = j.ok ? j : null;
        kwRes.innerHTML = j.ok ? kwReceipt(j) : `<div class="muted">검증 실패: ${j.message||j.error||''}</div>`;
      }catch(err){ kwRes.innerHTML=`<div class="muted">오류: ${err}</div>`; }
    });
  }

  // 🟢🔴 시안 2 — 키워드 실시간 하이라이트
  const kwHl=document.getElementById('sg-kw-hl');
  const kwLinesEl=document.getElementById('sg-kw-lines');
  function _esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
  function _kwSets(){
    // 현재 카드에서 실시간으로 triggers/excludes 읽기
    const triggers=[], excludes=[];
    document.querySelectorAll('#sg-inc .bcard').forEach(card=>{
      [...card.querySelectorAll('.trig-chips .chip.i')].forEach(ch=>{
        const t=[...ch.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim();
        if(t && !triggers.includes(t)) triggers.push(t);
      });
      [...card.querySelectorAll('.excl-chips .chip.e')].forEach(ch=>{
        const t=[...ch.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim();
        if(t && !excludes.includes(t)) excludes.push(t);
      });
    });
    // fallback to __guideInit
    if(!triggers.length && !excludes.length){
      const init=window.__guideInit||{};
      const benefits=(init.pricing&&init.pricing.benefits)||[];
      benefits.forEach(b=>{ (b.triggers||[]).forEach(t=>{if(t&&!triggers.includes(t)) triggers.push(t);}); });
      benefits.forEach(b=>{ (b.excludes||[]).forEach(t=>{if(t&&!excludes.includes(t)) excludes.push(t);}); });
    }
    return {inc:triggers, exc:excludes};
  }
  function renderHl(){
    if(!kwHl||!kwLinesEl) return;
    const {inc,exc}=_kwSets();
    const lines=kwLinesEl.value.split('\n').filter(l=>l.trim());
    if(!lines.length){ kwHl.innerHTML='<span class="muted" style="font-size:11.5px;">위에 문구를 붙여넣으면 ③ 키워드가 어디에 걸리는지 색으로 표시됩니다.</span>'; return; }
    kwHl.innerHTML=lines.map(line=>{
      const exHit=exc.find(k=>k&&line.includes(k));
      if(exHit) return `<div class="ln"><span class="hit-exc">${_esc(line)}</span><span class="why exc">← 제외 '${_esc(exHit)}'</span></div>`;
      let h=_esc(line), incHit=null;
      inc.forEach(k=>{ if(k&&line.includes(k)){ if(!incHit) incHit=k; h=h.split(_esc(k)).join(`<span class="hit-inc">${_esc(k)}</span>`); }});
      return `<div class="ln">${h}${incHit?` <span class="why inc">← 포함 '${_esc(incHit)}'</span>`:''}</div>`;
    }).join('');
  }
  if(kwLinesEl){ kwLinesEl.addEventListener('input', renderHl); renderHl(); }
  document.querySelector('.sg-go3')?.addEventListener('click', e=>{ e.preventDefault();
    const el=document.getElementById('sg-inc'); if(el) el.scrollIntoView({behavior:'smooth',block:'start'}); });

  // ✓ 저장 — 검증 결과를 '저장된 검증' 리스트에 누적
  function nameFromUrl(u){ const m=(u||'').match(/\/products\/(\d+)/); return m? ('상품 '+m[1]) : (u||'검증'); }
  document.addEventListener('click', async e=>{
    if(!e.target || e.target.id!=='sg-kw-save') return;
    const btn=e.target, msg=document.getElementById('sg-kw-save-msg');
    const url=document.getElementById('sg-verify-url').value.trim();
    const g=window.__lastGate;
    if(!g){ if(msg) msg.textContent='먼저 키워드 게이트 검증을 실행하세요.'; return; }
    const applied=(g.gated||[]).filter(x=>x.applied).length;
    const excluded=(g.gated||[]).filter(x=>x.excluded&&x.excluded.length).length;
    const summary=`적용 ${applied} · 제외 ${excluded}`;
    btn.disabled=true; if(msg) msg.textContent='저장 중…';
    try{
      const res=await fetch(`/sourcing-guide/api/${sid}/save-check`,{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({url, name:nameFromUrl(url), final_price:(g.final_price!=null?g.final_price:null), summary})});
      const j=await res.json();
      if(j.ok){
        const list=document.getElementById('sg-saved-list');
        const empty=document.querySelector('.sg-saved-empty'); if(empty) empty.style.display='none';
        if(list){
          const item=document.createElement('div'); item.className='sg-saved-item'; item.dataset.url=url||'';
          const price=(g.final_price!=null)? `<b>${g.final_price.toLocaleString()}원</b> · ` : '';
          item.innerHTML=`<div class="nm">${nameFromUrl(url)}</div><div class="meta">${price}${summary} · 방금</div>`;
          [...list.querySelectorAll('.sg-saved-item')].forEach(it=>{ if(url && it.dataset.url===url) it.remove(); });
          list.insertBefore(item, list.firstChild);
        }
        btn.textContent='✓ 저장됨';
        if(msg) msg.textContent = j.added_to_samples ? '저장된 검증 + ① 기준 샘플 URL 등록 완료.' : '저장된 검증에 추가 (① 이미 등록됨).';
      } else { btn.disabled=false; if(msg) msg.textContent='저장 실패: '+(j.message||j.error||''); }
    }catch(err){ btn.disabled=false; if(msg) msg.textContent='오류: '+err; }
  });

  // ④ 예제 기준 스크린샷 — 드래그앤드랍 업로드
  function resizeImg(file,maxW,q){return new Promise((res,rej)=>{const r=new FileReader();r.onerror=rej;r.onload=()=>{const im=new Image();im.onload=()=>{const sc=Math.min(1,maxW/im.width);const c=document.createElement('canvas');c.width=Math.round(im.width*sc);c.height=Math.round(im.height*sc);c.getContext('2d').drawImage(im,0,0,c.width,c.height);res(c.toDataURL('image/jpeg',q));};im.onerror=rej;im.src=r.result;};r.readAsDataURL(file);});}
  document.querySelectorAll('.exshot').forEach(zone=>{
    zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('drag');});
    zone.addEventListener('dragleave',e=>{if(!zone.contains(e.relatedTarget))zone.classList.remove('drag');});
    zone.addEventListener('drop',async e=>{
      e.preventDefault();zone.classList.remove('drag');
      const f=[...((e.dataTransfer&&e.dataTransfer.files)||[])].find(x=>x.type&&x.type.indexOf('image/')===0);
      if(!f){alert('이미지 파일을 드래그해 주세요.');return;}
      zone.classList.add('busy');
      try{
        const dataUrl=await resizeImg(f,640,0.82);
        if(dataUrl.length>600000){alert('이미지가 너무 큽니다. 더 작은 영역을 캡처해 주세요.');zone.classList.remove('busy');return;}
        const res=await fetch(`/sourcing-guide/api/${sid}/example-shot`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:+zone.dataset.exIndex,image:dataUrl})});
        const j=await res.json();
        if(j.ok){ zone.innerHTML='<a class="exshot-link" href="'+dataUrl+'" target="_blank"><img src="'+dataUrl+'"></a>'; }
        else alert('업로드 실패: '+(j.message||j.error));
      }catch(err){ alert('이미지 처리 실패: '+err); }
      zone.classList.remove('busy');
    });
  });

  // ④ 예제 기준 스크린샷 — 서버 자동 캡처
  document.querySelectorAll('.shot-auto').forEach(btn=>{
    btn.addEventListener('click',async e=>{
      e.preventDefault();e.stopPropagation();
      const zone=btn.closest('.exshot'); const idx=+btn.dataset.exIndex;
      if(!zone) return;
      zone.classList.add('capturing');
      try{
        const res=await fetch(`/sourcing-guide/api/${sid}/example-shot/auto`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:idx})});
        const j=await res.json();
        if(j.ok&&j.url){ zone.innerHTML='<a class="exshot-link" href="'+j.url+'" target="_blank"><img src="'+j.url+'"></a>'; }
        else alert('자동 캡처 실패: '+(j.message||j.error||'알 수 없는 오류'));
      }catch(err){ alert('자동 캡처 오류: '+err); }
      zone.classList.remove('capturing');
    });
  });
})();
