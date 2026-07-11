/* margin_render.js — 서버가 준 분석 JSON 을 탭별로 그린다. 재집계 없음. */
(function (root) {
  'use strict';
  function won(v){ var n=Number(String(v==null?0:v).replace(/,/g,'')); return (isFinite(n)?n:0).toLocaleString('en-US'); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];}); }

  var PIE = ['#3182F6','#12B886','#F59F00','#F03E3E','#7048E8','#1098AD','#E8590C','#868E96'];
  function pieSlices(rows, key){
    var tot = (rows||[]).reduce(function(a,r){return a+Math.max(0,Number(r[key])||0);},0);
    if (tot<=0) return [];
    var acc=0, out=[];
    (rows||[]).forEach(function(r){
      var v=Math.max(0,Number(r[key])||0); var start=acc/tot*360; acc+=v; var end=acc/tot*360;
      out.push({start:start,end:end,v:v});
    });
    return out;
  }
  function pieSvg(rows, key, labelKey){
    var s=pieSlices(rows,key); if(!s.length) return '<div class="mg-hint">데이터 없음</div>';
    var cx=70,cy=70,r=60, paths=s.map(function(sl,i){
      var a0=(sl.start-90)*Math.PI/180, a1=(sl.end-90)*Math.PI/180;
      var x0=cx+r*Math.cos(a0), y0=cy+r*Math.sin(a0), x1=cx+r*Math.cos(a1), y1=cy+r*Math.sin(a1);
      var large=(sl.end-sl.start)>180?1:0;
      if (sl.end-sl.start>=359.999) return '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="'+PIE[i%PIE.length]+'"/>';
      return '<path d="M'+cx+','+cy+' L'+x0+','+y0+' A'+r+','+r+' 0 '+large+' 1 '+x1+','+y1+' Z" fill="'+PIE[i%PIE.length]+'"/>';
    }).join('');
    var legend=(rows||[]).map(function(rw,i){
      return '<div class="mg-leg"><span class="mg-dot" style="background:'+PIE[i%PIE.length]+'"></span>'
        + esc(rw[labelKey]) + ' <b>'+won(rw[key])+'</b></div>';
    }).join('');
    return '<div class="mg-pie"><svg viewBox="0 0 140 140" width="140" height="140">'+paths+'</svg><div class="mg-legs">'+legend+'</div></div>';
  }

  function renderSummary(d){
    var s=d.summary||{}, c=d.counts||{};
    // 분류 카운트(정상/고마진/의심손실/계산불가)는 서버 summary 에 없다 → 규칙 모듈로
    // matched 행에서 직접 집계한다(조용한 0 차단, 손실 신호 복원). MR = margin_rules.js.
    var MR = root.MR;
    var hasCls = !!(MR && MR.summarize);
    var cls = hasCls ? MR.summarize(d.matched||[]) : {};
    var kpis=[['총매출',s.총매출],['총정산',s.총정산],['총매입',s.총매입],['총순마진',s.총순마진,'hl'],['평균 마진율',(s.평균마진율||0),'pct']];
    var kpiHtml=kpis.map(function(k){
      var val=k[2]==='pct'?((Number(k[1])||0).toFixed(1)+'<span class="u"> %</span>'):(won(k[1])+'<span class="u"> 원</span>');
      return '<div class="mg-kpi '+(k[2]==='hl'?'hl':'')+'"><div class="k">'+k[0]+'</div><div class="v">'+val+'</div></div>';
    }).join('');
    var minis=[['정상',cls.정상,''],['고마진',cls.고마진,'g'],['의심손실',cls.의심손실,'r'],['계산불가',cls.계산불가,'a']];
    var miniHtml=minis.map(function(m){
      var mv = hasCls ? (m[1]||0) : '—';
      return '<div class="mg-mini '+m[2]+'"><span class="k">'+m[0]+'</span><span class="v">'+mv+'</span></div>';
    }).join('');
    var estNote = c.settle_estimated ? '<div class="mg-hint" style="margin-top:6px">※ 정산 미확정(추정) '+esc(c.settle_estimated)+'건 포함</div>' : '';
    return '<div class="mg-kpis">'+kpiHtml+'</div><div class="mg-minis">'+miniHtml+'</div>'+estNote
      + '<div class="mg-charts"><div class="mg-chart"><div class="mg-ct">마켓별 매출</div>'+pieSvg(d.market,'매출','마켓')+'</div>'
      + '<div class="mg-chart"><div class="mg-ct">마켓별 순마진</div>'+pieSvg(d.market,'순마진','마켓')+'</div></div>';
  }

  function rowClass(r){
    var MR = root.MR; if (!MR) return '';
    var c = MR.classify(r);
    return c==='loss'?'mg-loss':c==='highmargin'?'mg-high':c==='uncomputable'?'mg-uncomp':'';
  }
  // aggregator._classify(판매가) 를 그대로 재현 — 매칭행에 없는 금액대를 클라에서 재계산.
  // config.DEFAULT_PRICE_RANGES 와 경계·라벨 1:1 일치 (low<=x<high). 값 없음/숫자아님 → ''.
  var PRICE_RANGES = [[0,10000,'~1만'],[10000,30000,'1~3만'],[30000,50000,'3~5만'],
                      [50000,100000,'5~10만'],[100000,Infinity,'10만~']];
  function priceBucket(r){
    var raw = r ? r['판매가'] : null;
    if (raw==null || raw==='') return '';
    var n = Number(String(raw).replace(/,/g,''));
    if (!isFinite(n)) return '';
    for (var i=0;i<PRICE_RANGES.length;i++){
      if (n>=PRICE_RANGES[i][0] && n<PRICE_RANGES[i][1]) return PRICE_RANGES[i][2];
    }
    return '';
  }
  function renderAll(d){
    var f = d.filters||{};
    function opts(arr){ return ['<option value="">전체</option>'].concat((arr||[]).map(function(x){return '<option>'+esc(x)+'</option>';})).join(''); }
    var bar = '<div class="mg-filter">'
      + '<select data-f="마켓">'+opts(f.markets)+'</select>'
      + '<select data-f="브랜드">'+opts(f.brands)+'</select>'
      + '<select data-f="금액대">'+opts(f.priceRange)+'</select>'
      + '<button class="mg-xlsx" data-export="detail_filtered">필터 결과 엑셀</button></div>';
    var head = '<tr><th>주문일</th><th>마켓</th><th>상품 · 옵션</th><th class="num">판매가</th>'
      + '<th class="num">정산예정</th><th class="num">매입</th><th class="num">순마진</th>'
      + '<th class="num">마진율</th><th class="ctr">매칭</th></tr>';
    var body = (d.matched||[]).map(function(r){
      return '<tr class="'+rowClass(r)+'" data-mk="'+esc(r.마켓)+'" data-br="'+esc(r.브랜드)+'" data-pr="'+esc(priceBucket(r))+'">'
        + '<td>'+esc(r.주문일).slice(0,10)+'</td><td class="ctr">'+esc(r.마켓)+'</td>'
        + '<td>'+esc(r.상품명)+' · '+esc(r.옵션_매출)+'</td>'
        + '<td class="num">'+won(r.판매가)+'</td><td class="num">'+won(r.정산예상금액)+'</td>'
        + '<td class="num">'+won(r.구매가격)+'</td><td class="num">'+won(r.순마진)+'</td>'
        + '<td class="num">'+(Number(r.마진율)||0).toFixed(1)+'</td><td class="ctr">'+esc(r.매칭타입)+'</td></tr>';
    }).join('');
    return bar + '<div class="mg-tblwrap"><table class="mg-tbl"><thead>'+head+'</thead><tbody>'+body+'</tbody></table></div>';
  }

  root.MG_RENDERERS = { summary: renderSummary, all: renderAll, __won: won, __esc: esc, __pieSvg: pieSvg };
  var api = { pieSlices: pieSlices, won: won, rowClass: rowClass, priceBucket: priceBucket };
  if (typeof module!=='undefined'&&module.exports) module.exports={__test:api};
})(typeof window!=='undefined'?window:globalThis);
