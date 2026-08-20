# -*- coding: utf-8 -*-
"""시안 조립기 2 — 문단·카드 줄 간격 전/후.

★ 원본을 손으로 옮기지 않는다. 파일에서 잘라 넣고, 들어갔는지 기계로 대조한다.
"""
import io, os, re, sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
TPL = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates')
OV = os.path.join(TPL, 'sourcing_guide', 'overview.html')
OUT = os.path.join(os.path.expanduser('~'), 'Desktop', '모음전 시안 v2 — 문단 줄 간격 전후.html')

원본 = io.open(OV, encoding='utf-8').read().split('\n')


def 자르기(a, b):
    return '\n'.join(원본[a - 1:b])


# ── 원본 조각 (파일에서 직접) ────────────────────────────────────────
무결성_CSS = 자르기(138, 138)      # .nsg-integrity  (17px / 1.75)
QA_CSS     = 자르기(140, 147)      # .nsg-qa 계열     (17px / 1.7·1.75)
칩_CSS     = 자르기(551, 557)      # .nsg-st-chip 계열 (17px / 1.7)
무결성_HTML = 자르기(352, 352)     # 실제 화면에 있는 그 문단 통째로

조각들 = {
    '무결성 카드 CSS(138행)': 무결성_CSS,
    'QA 문단 CSS(140~147행)': QA_CSS,
    '수집방식 칩 CSS(551~557행)': 칩_CSS,
    '무결성 카드 글(352행)': 무결성_HTML,
}

# 칩·QA 는 자바스크립트가 그리므로, 원본이 만드는 것과 같은 뼈대로 채운다
칩_HTML = (
    '<div class="nsg-st-chip html"><div class="nm">HTML 그대로 읽기</div>'
    '<div class="def">상품 페이지를 받아 그 안에 적힌 값을 그대로 읽는다. '
    '로그인이 필요 없고 가장 빠르지만, 화면을 열어야 값이 채워지는 사이트에서는 빈칸이 나온다.</div></div>'
    '<div class="nsg-st-chip api"><div class="nm">사이트가 주는 자료로 읽기</div>'
    '<div class="def">사이트가 자기 화면을 채우려고 내부에서 부르는 자료를 같이 받아 쓴다. '
    '값이 정확하고 빠르지만 주소가 바뀌면 한 번에 끊긴다.</div></div>'
)
QA_HTML = (
    '<div class="nsg-qa"><div class="blk">'
    '<div class="role">재고는 세 갈래로만 적는다 — 품절 · 한정수량 · 표식없음.</div>'
    '<div class="abbr">한정수량은 「잔여」·「N개 남음」·「마지막」·「품절임박」이 전부 같은 뜻이다.</div>'
    '<div class="ex">한 가지만 적고 나머지를 빠뜨리면 한정재고가 「재고있음」으로 둔갑한다.</div>'
    '</div></div>'
)

HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>모음전 시안 v2 — 문단 줄 간격 전후</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<style>
:root{
  --글꼴:'Pretendard','Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Segoe UI',system-ui,sans-serif;
  --ink:#1D1D1F; --sub:#6E6E73; --line:#D2D2D7; --line2:#E8E8ED;
  --bg:#F5F5F7; --surface:#FFFFFF; --blue:#0071E3;
  --soft:#F5F7F9; --navy:#1D1D1F; --n100:#F5F7F9;
  --연한-주황:#FFF4E6; --연한-빨강:#FFECEE;
  --글자-기본:#555E6B; --글자-초록:#15a06e; --글자-파랑:#3182f6; --글자-주황:#d98300;
  --green:#15a06e; --primary:#3182f6; --amber:#d98300; --line2b:#EDF0F3;
}
*{box-sizing:border-box}
body{margin:0;background:#F5F5F7;font-family:var(--글꼴);color:var(--ink);
     line-height:1.57;-webkit-font-smoothing:antialiased}
.page{max-width:1920px;margin:0 auto;padding:24px 32px 80px}
h1{font-size:32px;font-weight:600;line-height:1.22;margin:0 0 8px}
.lead{font-size:14px;color:var(--sub);margin:0 0 24px;line-height:1.57}
.note{background:#fff;border:1px solid var(--line);border-radius:12px;
      padding:16px 20px;margin-bottom:24px;font-size:14px;line-height:1.57}
.note b{font-weight:600}
.note ul{margin:8px 0 0;padding-left:20px}
.note li{margin:4px 0}
.chk{background:#FFF8E1;border-color:#F0C36D}
.warn{background:#FFECEE;border-color:#F5B5BC}

.vtabs{position:sticky;top:0;z-index:30;display:flex;gap:8px;background:#F5F5F7;
       padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:20px}
.vtab{flex:1;text-align:left;background:#fff;border:1px solid var(--line);
      border-radius:12px;padding:12px 16px;cursor:pointer;font-family:inherit;
      transition:border-color .24s cubic-bezier(.4,0,.6,1)}
.vtab.on{border-color:var(--blue);border-width:2px;padding:11px 15px}
.v-name{font-size:14px;font-weight:600;line-height:1.35}
.v-desc{font-size:12px;color:var(--sub);line-height:1.33;margin-top:2px}
.v-key{display:inline-block;background:var(--line2);border-radius:4px;
       padding:0 5px;font-size:11px;color:var(--sub);margin-right:4px}
.pane{display:none}.pane.on{display:block}

.mock-win{background:#fff;border:1px solid var(--line);border-radius:10px;
          overflow:hidden;margin-bottom:16px}
.mock-bar{background:#F5F5F7;padding:10px 16px;font-size:12px;color:var(--sub);
          border-bottom:1px solid var(--line2);display:flex;align-items:center;gap:8px}
.mock-bar .url{background:#fff;padding:4px 12px;border-radius:5px;
               font-family:ui-monospace,monospace;font-size:11.5px;flex:1}
.mock-content{padding:24px 28px;background:#fff}
.cap{font-size:12px;color:var(--sub);line-height:1.33;margin:0 0 12px}
.cap b{color:var(--ink);font-weight:600}
.tag{display:inline-block;background:var(--line2);color:var(--sub);
     border-radius:980px;padding:2px 10px;font-size:11px;font-weight:600;
     line-height:1.33;margin-bottom:8px}
.tag.new{background:rgba(0,113,227,.10);color:var(--blue)}
h4.sec{font-size:17px;font-weight:600;line-height:1.35;margin:0 0 12px}

/* ══ 원본 코드 — sourcing_guide/overview.html 에서 그대로 잘라 넣은 것 ══ */
__무결성_CSS__
__QA_CSS__
__칩_CSS__

/* ── 안 A : 글자 크기별 규칙값 (17px 문단 → 1.59) ── */
.v-A .nsg-integrity,.v-A .nsg-qa .role,.v-A .nsg-qa .abbr,.v-A .nsg-qa .ex,
.v-A .nsg-st-chip .def{line-height:1.59}
/* ── 안 B : 전부 한 값(1.57) ── */
.v-B .nsg-integrity,.v-B .nsg-qa .role,.v-B .nsg-qa .abbr,.v-B .nsg-qa .ex,
.v-B .nsg-st-chip .def{line-height:1.57}
/* ── 지금 : 원본 그대로 (1.7 · 1.75) ── */

/* 아이콘·배지는 손대지 않는다는 것을 눈으로 보이기 */
.icons{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
.ic{width:33px;height:33px;border-radius:50%;background:var(--navy);color:#fff;
    font-size:17px;text-align:center;line-height:33px}
.bdg{background:var(--연한-빨강);color:#B91C1C;font-size:11px;font-weight:600;
     border-radius:6px;padding:5px 8px;line-height:1.4}
.xbtn{width:22px;height:22px;border:1px solid var(--line);border-radius:6px;
      background:#fff;font-size:13px;line-height:1;cursor:pointer;color:var(--sub)}
</style></head><body>
<div class="page">
<h1>문단·카드 줄 간격 — 전/후</h1>
<p class="lead">「소싱처 안내」 화면의 실제 문단을 그대로 가져왔습니다. 글자·내용은 손대지 않고 줄 사이만 달라집니다.</p>

<div class="note warn">
  <b>먼저 말씀드릴 것 — 「351곳 전부」는 잘못된 목표입니다</b>
  <ul>
    <li><b>109곳은 아이콘·배지·닫기 단추</b>입니다. 줄 사이를 벌리면 <b>글자가 칸 가운데서 벗어납니다.</b> 손대면 안 됩니다.</li>
    <li>실제로 손볼 <b>문단·카드 본문은 190곳</b>입니다. 이 시안이 그 190곳입니다.</li>
    <li>나머지 = 제목·짧은 줄 34곳 · 글자 크기 안 따라오는 값 18곳.</li>
  </ul>
</div>

<div class="note chk">
  <b>눈으로 확인해 주실 것</b>
  <ul>
    <li>① 줄 사이가 <b>답답하지 않은지</b> (좁히는 방향입니다)</li>
    <li>② 글 덩어리가 짧아져 <b>한 화면에 더 들어오는지</b></li>
    <li>③ 맨 아래 <b>아이콘·배지</b>가 세 안 모두 똑같은지 (안 건드립니다)</li>
  </ul>
</div>

<div class="vtabs">
  <button class="vtab on" data-v="now"><div class="v-name">지금</div>
    <div class="v-desc"><span class="v-key">1</span>1.7 · 1.75 로 흩어져 있음</div></button>
  <button class="vtab" data-v="va"><div class="v-name">A. 글자 크기별 규칙값</div>
    <div class="v-desc"><span class="v-key">2</span>17px 문단 → 1.59 · 추천</div></button>
  <button class="vtab" data-v="vb"><div class="v-name">B. 전부 한 값</div>
    <div class="v-desc"><span class="v-key">3</span>크기와 무관하게 1.57</div></button>
</div>

<div class="pane on" id="now">
  <span class="tag">지금</span>
  <p class="cap"><b>무결성 카드 1.75 · 물음답 1.7~1.75 · 수집방식 1.7</b> — 같은 화면 안에서도 값이 다릅니다.</p>
  __NOW_MOCK__
</div>
<div class="pane" id="va">
  <span class="tag new">A안 — 글자 크기별 규칙값</span>
  <p class="cap">17px 문단은 <b>1.59</b>. 큰 글씨는 조금 넉넉하게, 작은 글씨는 조금 촘촘하게 — 크기마다 다른 값입니다.</p>
  __A_MOCK__
</div>
<div class="pane" id="vb">
  <span class="tag new">B안 — 전부 한 값</span>
  <p class="cap">글자 크기와 상관없이 <b>1.57</b> 하나. 규칙은 단순해지지만 큰 글씨가 조금 답답해집니다.</p>
  __B_MOCK__
</div>

</div>
<script>
var tabs=document.querySelectorAll('.vtab'),panes=document.querySelectorAll('.pane');
function go(t){tabs.forEach(function(b){b.classList.toggle('on',b.dataset.v===t);});
 panes.forEach(function(p){p.classList.toggle('on',p.id===t);});}
tabs.forEach(function(b){b.addEventListener('click',function(){go(b.dataset.v);});});
document.addEventListener('keydown',function(e){
 var o=[].slice.call(tabs).map(function(t){return t.dataset.v;});
 var i=o.indexOf(document.querySelector('.vtab.on').dataset.v);
 if(/^[123]$/.test(e.key)&&o[+e.key-1])go(o[+e.key-1]);
 else if(e.key==='ArrowRight'&&o[i+1])go(o[i+1]);
 else if(e.key==='ArrowLeft'&&o[i-1])go(o[i-1]);});
</script></body></html>"""

주소 = 'mou-m.com/sourcing-guide/ — 소싱처 안내'


def mock(덧):
    안 = ('<h4 class="sec">STEP 5 · 검증 체크리스트 — 수집 · 가공 · 전송 (무결성)</h4>'
          + 무결성_HTML
          + '<h4 class="sec" style="margin-top:24px">재고 세 갈래</h4>' + QA_HTML
          + '<h4 class="sec" style="margin-top:24px">수집 방식</h4>' + 칩_HTML
          + '<div class="icons"><span class="ic">1</span><span class="ic">2</span>'
            '<span class="bdg">실패 3건</span><button class="xbtn">×</button>'
            '<span style="font-size:12px;color:var(--sub)">← 아이콘·배지는 세 안 모두 그대로</span></div>')
    return ('<div class="mock-win"><div class="mock-bar"><span>●●●</span>'
            '<span class="url">%s</span></div><div class="mock-content %s">%s</div></div>'
            % (주소, 덧, 안))


치환 = {'__무결성_CSS__': 무결성_CSS, '__QA_CSS__': QA_CSS, '__칩_CSS__': 칩_CSS,
        '__NOW_MOCK__': mock(''), '__A_MOCK__': mock('v-A'), '__B_MOCK__': mock('v-B')}
out = HTML
for k, v in 치환.items():
    assert k in out, '자리표시자 없음: %s' % k
    out = out.replace(k, v)

print('=' * 58)
print(' 원본 보존 대조 (자기 보고 아님 — 문자열 포함 여부)')
print('=' * 58)
누락 = 0
for 이름, 조각 in 조각들.items():
    있 = 조각 in out
    print(' %-26s %s (%s자)' % (이름, '통째로 들어감 ✅' if 있 else '빠짐 ❌', format(len(조각), ',')))
    if not 있:
        누락 += 1

잔글씨 = ['100% 일치', '수집 → 가공 → 전송', '둔갑 없이', '한정수량 N이 매트릭스 표시까지',
          '로그인 세션/확장 경로']
빠짐 = [s for s in 잔글씨 if s not in out]
print(' %-26s %d개 중 %d개 빠짐' % ('잔글씨(강조·근거)', len(잔글씨), len(빠짐)))
누락 += len(빠짐)
print('-' * 58)
if 누락:
    print(' ❌ 누락 %d건 — 시안을 쓰지 않고 멈춥니다.' % 누락)
    sys.exit(1)
print(' ✅ 누락 0 — 시안을 씁니다.')
io.open(OUT, 'w', encoding='utf-8').write(out)
print(' 저장: %s' % OUT)
