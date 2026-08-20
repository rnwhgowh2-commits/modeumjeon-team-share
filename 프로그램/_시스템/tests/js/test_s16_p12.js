const assert = require('assert');
let pass=0, fail=0;
function t(name, fn){ try{ fn(); console.log('  ✅ '+name); pass++; }catch(e){ console.log('  ❌ '+name+' — '+e.message); fail++; } }

// ===== S16: 무신사 재고 stock 계산 (background.js 배포 로직 복제) =====
function stockOf(inv, invOk){
  if (inv) return inv.outOfStock ? 0 : (inv.remainQuantity == null ? 999 : Math.max(0, inv.remainQuantity));
  return invOk ? 999 : -1;
}
console.log('S16 — 무신사 재고 API 실패가드:');
t('API 전체실패(invOk=false)+옵션 맵에 없음 → -1(불명), 999 금지', ()=> assert.strictEqual(stockOf(undefined,false), -1));
t('API 성공(invOk=true)+맵에 없음 → 999 (happy-path 불변)', ()=> assert.strictEqual(stockOf(undefined,true), 999));
t('옵션 존재+수량 5 → 5', ()=> assert.strictEqual(stockOf({remainQuantity:5},true), 5));
t('옵션 존재+품절 → 0', ()=> assert.strictEqual(stockOf({outOfStock:true},true), 0));
t('옵션 존재+수량 null → 999 (기존)', ()=> assert.strictEqual(stockOf({remainQuantity:null},true), 999));
t('수량 0 → 0 (음수 방지)', ()=> assert.strictEqual(stockOf({remainQuantity:0},true), 0));

// ===== P12: 축값 rename 키 마이그레이션 (option_url_modal.js 배포 로직 복제) =====
function parseValues(text){ const out=[]; (text||'').split(',').forEach(raw=>{const v=raw.trim(); if(v&&out.indexOf(v)<0)out.push(v);}); return out; }
function migrate(state){
  const snap=state._valSnap;
  if(!snap||snap.length!==state.axes.length) return;
  const renames={};
  for(let ai=0;ai<state.axes.length;ai++){
    const ov=parseValues(snap[ai]||''), nv=parseValues(state.axes[ai].values||'');
    if(ov.length!==nv.length) continue;
    const diff=[]; for(let j=0;j<ov.length;j++) if(ov[j]!==nv[j]) diff.push(j);
    if(diff.length===1){const o=ov[diff[0]],n=nv[diff[0]]; if(o&&n) renames[ai]={o,n};}
  }
  const ais=Object.keys(renames); if(!ais.length) return;
  const remapKey=(k)=>{let arr;try{arr=JSON.parse(k);}catch(e){return k;} if(!Array.isArray(arr))return k; let ch=false; ais.forEach(ai=>{if(arr[ai]===renames[ai].o){arr[ai]=renames[ai].n;ch=true;}}); return ch?JSON.stringify(arr):k;};
  const remapSet=(set)=>{if(!set)return; const nx=new Set(); set.forEach(k=>nx.add(remapKey(k))); set.clear(); nx.forEach(k=>set.add(k));};
  remapSet(state.selected); remapSet(state.seen); remapSet(state.invMappedKeys); remapSet(state.mappedOff);
  Object.keys(state.urls||{}).forEach(sk=>{(state.urls[sk]||[]).forEach(u=>{if(u.option_keys&&u.option_keys.length)u.option_keys=u.option_keys.map(remapKey);});});
}
const K=(...v)=>JSON.stringify(v);
console.log('P12 — 축값 rename 매핑키 마이그레이션:');
t('순수 rename(블랙→블랙ZZ): selected·urls 키 보존(old→new)', ()=>{
  const st={ axes:[{values:'블랙ZZ,그레이'},{values:'220,230'}], _valSnap:['블랙,그레이','220,230'],
    selected:new Set([K('블랙','220'),K('그레이','230')]), seen:new Set([K('블랙','220')]),
    invMappedKeys:new Set([K('블랙','230')]), mappedOff:new Set(),
    urls:{s1:[{option_keys:[K('블랙','220'),K('그레이','230')]}]} };
  migrate(st);
  assert(st.selected.has(K('블랙ZZ','220')),'selected 블랙ZZ 보존');
  assert(!st.selected.has(K('블랙','220')),'옛 블랙 키 제거');
  assert(st.selected.has(K('그레이','230')),'무관 키 유지');
  assert(st.invMappedKeys.has(K('블랙ZZ','230')),'재고매핑 키 보존');
  assert.strictEqual(st.urls.s1[0].option_keys[0], K('블랙ZZ','220'),'URL 매핑 키 보존');
});
t('값 추가(블랙,그레이→블랙,그레이,옐로우): 마이그레이션 안 함(길이 다름)', ()=>{
  const st={ axes:[{values:'블랙,그레이,옐로우'},{values:'220'}], _valSnap:['블랙,그레이','220'],
    selected:new Set([K('블랙','220')]), seen:new Set(), invMappedKeys:new Set(), mappedOff:new Set(), urls:{} };
  migrate(st);
  assert(st.selected.has(K('블랙','220')),'키 그대로');
});
t('스냅샷 없음(첫 호출): no-op (안전)', ()=>{
  const st={ axes:[{values:'블랙'}], selected:new Set([K('블랙')]), urls:{} };
  migrate(st);
  assert(st.selected.has(K('블랙')),'변화 없음');
});
t('2축 사이즈 rename(220→225)도 해당 축 위치만 치환', ()=>{
  const st={ axes:[{values:'블랙'},{values:'225,230'}], _valSnap:['블랙','220,230'],
    selected:new Set([K('블랙','220'),K('블랙','230')]), seen:new Set(), invMappedKeys:new Set(), mappedOff:new Set(), urls:{} };
  migrate(st);
  assert(st.selected.has(K('블랙','225')),'사이즈 225 보존');
  assert(st.selected.has(K('블랙','230')),'230 유지');
  assert(!st.selected.has(K('블랙','220')),'옛 220 제거');
});

console.log('\n결과: '+pass+' passed, '+fail+' failed');
process.exit(fail?1:0);
