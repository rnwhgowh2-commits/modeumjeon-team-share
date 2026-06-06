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
      fields[tr.dataset.field]={method:tr.querySelector('.sg-method').value,
        locator:tr.querySelector('.sg-loc').value, status:tr.querySelector('.sg-fstatus').value, note:''};
    });
    base.fields = fields;
    base.pricing = base.pricing || {base_label:'표면 노출가', benefit_collection:'per_product', benefits:[], note:''};
    base.pricing.benefits = [...document.querySelectorAll('#sg-benefits tr[data-apply]')].map(tr=>(
      {name:tr.querySelector('.sg-name').textContent.trim(), apply:tr.dataset.apply,
       rule:tr.querySelector('.sg-rule').textContent.trim(), status:tr.dataset.status}));
    return base;
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
