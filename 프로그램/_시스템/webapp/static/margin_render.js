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

  root.MG_RENDERERS = { summary: renderSummary, __won: won, __esc: esc, __pieSvg: pieSvg };
  var api = { pieSlices: pieSlices, won: won };
  if (typeof module!=='undefined'&&module.exports) module.exports={__test:api};
})(typeof window!=='undefined'?window:globalThis);
