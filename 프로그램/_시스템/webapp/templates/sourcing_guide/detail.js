(function(){
  const root = document.querySelector('.sg-wrap');
  const sid = root.dataset.sid;
  document.querySelectorAll('.sg-sub button').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.sg-sub button').forEach(x=>x.classList.toggle('on',x===b));
    document.getElementById('sub-sample').classList.toggle('on', b.dataset.sub==='sample');
    document.getElementById('sub-new').classList.toggle('on', b.dataset.sub==='new');
  }));

  function collect(){
    const base = (window.__guideInit ? JSON.parse(JSON.stringify(window.__guideInit)) : {version:2, pricing:{}});
    base.version = 2;
    base.sample_urls = [...document.querySelectorAll('#sg-urls .sg-urlrow')].map(r=>(
      {url:r.dataset.url, is_lead:!!r.querySelector('.tagk')}));
    const fields={};
    document.querySelectorAll('#sg-fields tr[data-field]').forEach(tr=>{
      const noteEl = tr.nextElementSibling && tr.nextElementSibling.classList.contains('note-row')
        ? tr.nextElementSibling.querySelector('.sg-note') : null;
      // 수집 방식·인증·상태는 Claude가 채운 배지(읽기용) → data 속성에서 그대로 보존.
      // 위치(셀렉터)·비고만 화면에서 편집 가능.
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
    base.pricing = base.pricing || {base_label:'표면 노출가', benefit_collection:'per_product', benefits:[], note:''};
    const kchips=(el,kind)=>[...el.querySelectorAll('.bkw[data-kind="'+kind+'"] .kc')].map(k=>(k.firstChild?k.firstChild.textContent:'').trim()).filter(Boolean);
    const benefits=[];
    document.querySelectorAll('#sg-inc .bcard').forEach(c=>{
      const name=c.querySelector('.bn').value.trim();
      if(!name) return;
      const m=c.querySelector('.bcrit input[type=radio]:checked');
      benefits.push({name, apply:c.dataset.apply,
        method:c.querySelector('.s-m').value,
        base:c.querySelector('.s-b').value,
        status:c.querySelector('.s-s').value,
        freq:c.querySelector('.s-c').value,
        rule:c.querySelector('.brule').value.trim(),
        triggers:kchips(c,'inc'),
        match:m?m.value:'any'});
    });
    base.pricing.benefits = benefits;
    const excludes=[];
    document.querySelectorAll('#sg-exlist .exrule').forEach(r=>{
      const word=r.querySelector('.exw').value.trim();
      if(!word) return;
      excludes.push({word, 'with':kchips(r,'with'), 'except':kchips(r,'except')});
    });
    base.exclude_keywords = excludes;
    return base;
  }

  // ③ 포함(혜택 카드)/제외(공통) — 추가·삭제·키워드 칩
  const _M=['정률(%)','정액(원)','정액·정률','적립(%→원)','고정액','옵션(개월)'];
  const _B=['표면 노출가','베이스금액①','베이스금액②','—'];
  const _F=['무제한','정기','1회성'];
  const _S=[['always','상시'],['conditional','조건부'],['optional','선택'],['planned','예정']];
  const _opt=a=>a.map(x=>`<option>${x}</option>`).join('');
  const _optS=()=>_S.map(([v,l])=>`<option value="${v}">${l}</option>`).join('');
  let _ridx=10000;
  function kchip(w,kind){
    const cls=kind==='with'?'dn':kind==='except'?'nx':'inc';
    const s=document.createElement('span'); s.className='kc '+cls;
    s.appendChild(document.createTextNode(w));
    const i=document.createElement('i'); i.textContent='×'; s.appendChild(i);
    return s;
  }
  function newCard(apply,color){
    const id=++_ridx;
    const d=document.createElement('div'); d.className='bcard'; d.dataset.apply=apply; d.style.borderLeft='3px solid '+color;
    d.innerHTML=`<div class="bch"><input class="bn" placeholder="혜택명"><button type="button" class="bdel" title="삭제">×</button></div>`+
      `<input class="brule" placeholder="계산 규칙 (예: 베이스금액① × 10%)">`+
      `<div class="battrs"><span class="pill"><em>방식</em><select class="s-m">${_opt(_M)}</select></span>`+
      `<span class="pill"><em>기준</em><select class="s-b">${_opt(_B)}</select></span>`+
      `<span class="pill"><em>상시</em><select class="s-s">${_optS()}</select></span>`+
      `<span class="pill"><em>횟수</em><select class="s-c">${_opt(_F)}</select></span></div>`+
      `<div class="bkwl">포함 키워드</div><div class="bkw" data-kind="inc"><input class="kin" data-kind="inc" placeholder="단어 추가"></div>`+
      `<div class="bcrit"><em class="cl">혜택 적용 기준</em><div class="copts"><label><input type="radio" name="mt${id}" value="any" checked><span>키워드 1개 이상 포함</span></label><label><input type="radio" name="mt${id}" value="all"><span>키워드 모두 포함</span></label></div></div>`;
    return d;
  }
  function newEx(){
    const d=document.createElement('div'); d.className='exrule';
    d.innerHTML=`<div class="exrh"><input class="exw" placeholder="제외 단어"><button type="button" class="exdel" title="삭제">×</button></div>`+
      `<div class="exl">함께 <em>이 단어와 같이 있으면 제외</em></div><div class="bkw" data-kind="with"><input class="kin" data-kind="with" placeholder="단어 추가"></div>`+
      `<div class="exl">예외 <em>이 단어와 같이 있으면 포함</em></div><div class="bkw" data-kind="except"><input class="kin" data-kind="except" placeholder="단어 추가"></div>`;
    return d;
  }
  const incEl=document.getElementById('sg-inc');
  if(incEl){
    incEl.querySelectorAll('.addb').forEach(btn=>btn.addEventListener('click',()=>{
      btn.closest('.cat').querySelector('.cardlist').appendChild(newCard(btn.dataset.apply,btn.dataset.color));
    }));
    incEl.addEventListener('click',e=>{ if(e.target.classList.contains('bdel')) e.target.closest('.bcard').remove(); });
  }
  const exlist=document.getElementById('sg-exlist');
  const addexBtn=document.querySelector('.addex');
  if(addexBtn&&exlist){
    addexBtn.addEventListener('click',()=>exlist.appendChild(newEx()));
    exlist.addEventListener('click',e=>{ if(e.target.classList.contains('exdel')) e.target.closest('.exrule').remove(); });
  }
  // 키워드 칩: Enter 추가 / × 삭제
  document.addEventListener('keydown',e=>{
    if(e.target.classList&&e.target.classList.contains('kin')&&e.key==='Enter'){
      e.preventDefault(); const v=e.target.value.trim(); if(!v) return;
      const box=e.target.closest('.bkw'); box.insertBefore(kchip(v,e.target.dataset.kind), e.target); e.target.value='';
    }
  });
  document.addEventListener('click',e=>{
    if(e.target.tagName==='I'&&e.target.parentElement&&e.target.parentElement.classList.contains('kc')) e.target.parentElement.remove();
  });

  document.getElementById('sg-save').addEventListener('click', async ()=>{
    const res=await fetch(`/sourcing-guide/api/${sid}`,{method:'PUT',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(collect())});
    const j=await res.json();
    alert(j.ok? '저장됨':('저장 실패: '+(j.message||j.error)));
  });

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

  // 🔑 키워드 게이트 검증 — 크롤된 혜택 라인 + ③ 저장된 포함/제외 키워드 → 영수증
  const kwBtn=document.getElementById('sg-kw-btn');
  const kwRes=document.getElementById('sg-kw-result');
  // 크롤 금액(없으면 매입가 계산 생략). 실제 크롤 dynamic_benefits 값이 들어갈 자리.
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
        window.__lastGate = j.ok ? j : null;   // 저장에 사용
        kwRes.innerHTML = j.ok ? kwReceipt(j) : `<div class="muted">검증 실패: ${j.message||j.error||''}</div>`;
      }catch(err){ kwRes.innerHTML=`<div class="muted">오류: ${err}</div>`; }
    });
  }

  // ✓ 저장 — 검증 결과를 '저장된 검증' 리스트(우측)에 누적 + ① 동시 등록 (시안 2-C)
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
        // 우측 '저장된 검증' 리스트 맨 위에 추가
        const list=document.getElementById('sg-saved-list');
        const empty=document.querySelector('.sg-saved-empty'); if(empty) empty.style.display='none';
        if(list){
          const item=document.createElement('div'); item.className='sg-saved-item'; item.dataset.url=url||'';
          const price=(g.final_price!=null)? `<b>${g.final_price.toLocaleString()}원</b> · ` : '';
          item.innerHTML=`<div class="nm">${nameFromUrl(url)}</div><div class="meta">${price}${summary} · 방금</div>`;
          // 같은 URL 기존 항목 제거 후 prepend
          [...list.querySelectorAll('.sg-saved-item')].forEach(it=>{ if(url && it.dataset.url===url) it.remove(); });
          list.insertBefore(item, list.firstChild);
        }
        btn.textContent='✓ 저장됨';
        if(msg) msg.textContent = j.added_to_samples ? '저장된 검증 + ① 기준 샘플 URL 등록 완료.' : '저장된 검증에 추가 (① 이미 등록됨).';
      } else { btn.disabled=false; if(msg) msg.textContent='저장 실패: '+(j.message||j.error||''); }
    }catch(err){ btn.disabled=false; if(msg) msg.textContent='오류: '+err; }
  });

  // ④ 예제 기준 스크린샷 — 드래그앤드랍 업로드 (리사이즈 → data URL → 저장)
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

  // ④ 예제 기준 스크린샷 — 서버 자동 캡처 (Playwright → R2)
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
