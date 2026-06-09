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
    const benefits=[];
    document.querySelectorAll('#sg-moa .bgroup').forEach(g=>{
      const apply=g.dataset.apply;
      g.querySelectorAll('.bitem').forEach(it=>{
        const name=it.querySelector('.bn').value.trim();
        if(!name) return;
        const tEl=it.querySelector('.btrig-in');
        const triggers=(tEl?tEl.value:'').split(',').map(s=>s.trim()).filter(Boolean);
        benefits.push({name, apply,
          method:it.querySelector('.s-m').value,
          base:it.querySelector('.s-b').value,
          status:it.querySelector('.s-s').value,
          freq:it.querySelector('.s-c').value,
          rule:it.querySelector('.bcond').value.trim(),
          triggers});
      });
    });
    base.pricing.benefits = benefits;
    return base;
  }

  // 혜택 모아보기 — 추가/삭제
  const _M=['정률(%)','정액(원)','정액·정률','적립(%→원)','고정액','옵션(개월)'];
  const _B=['표면 노출가','베이스금액①','베이스금액②','—'];
  const _F=['무제한','정기','1회성'];
  const _S=[['always','상시'],['conditional','조건부'],['optional','선택'],['planned','예정']];
  const _opt=a=>a.map(x=>`<option>${x}</option>`).join('');
  const _optS=()=>_S.map(([v,l])=>`<option value="${v}">${l}</option>`).join('');
  function newCard(){
    const d=document.createElement('div'); d.className='bitem';
    d.innerHTML=`<div class="bih"><input class="bn" placeholder="혜택명"><button type="button" class="bdel" title="삭제">×</button></div>`+
      `<div class="bq"><textarea class="bcond" rows="1" placeholder="계산 규칙·조건 (예: 베이스금액① × 10%)"></textarea></div>`+
      `<div class="bsel"><span class="cs">방식<select class="s-m">${_opt(_M)}</select></span>`+
      `<span class="cs">기준<select class="s-b">${_opt(_B)}</select></span>`+
      `<span class="cs">상시<select class="s-s">${_optS()}</select></span>`+
      `<span class="cs">횟수<select class="s-c">${_opt(_F)}</select></span></div>`+
      `<div class="btrig"><span class="tlbl">적용 문구</span><input class="btrig-in" placeholder="크롤 감지 문구 (쉼표, 예: 기프트포인트, 멤버십)"></div>`;
    return d;
  }
  function autoGrow(ta){ ta.style.height='auto'; ta.style.height=(ta.scrollHeight)+'px'; }
  const moa=document.getElementById('sg-moa');
  if(moa){
    moa.querySelectorAll('textarea.bcond').forEach(autoGrow);
    moa.querySelectorAll('.addb').forEach(btn=>btn.addEventListener('click',()=>{
      const card=newCard();
      btn.closest('.bgroup').querySelector('.blist').appendChild(card);
      const ta=card.querySelector('textarea.bcond'); if(ta) autoGrow(ta);
    }));
    moa.addEventListener('input',e=>{ if(e.target.classList.contains('bcond')) autoGrow(e.target); });
    moa.addEventListener('click',e=>{
      if(e.target.classList.contains('bdel')) e.target.closest('.bitem').remove();
    });
  }

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
})();
