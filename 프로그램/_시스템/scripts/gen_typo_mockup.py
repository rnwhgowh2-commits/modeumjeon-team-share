# -*- coding: utf-8 -*-
"""시안 조립기 — 원본 코드를 파일에서 잘라내 시안 HTML 에 그대로 넣는다.

★ 손으로 옮기지 않는다. 원본이 바뀌면 다시 돌리면 된다.
★ 조립 후 「원본 문자열이 시안 안에 통째로 들어갔는지」를 기계로 대조하고,
   하나라도 빠지면 파일을 쓰지 않고 멈춘다.
"""
import io, os, re, sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
SRC  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates', 'orders', 'margin_embed.html')
OUT  = os.path.join(os.path.expanduser('~'), 'Desktop', '모음전 시안 v1 — 폰트·줄간격·정렬 통일.html')

원본 = io.open(SRC, encoding='utf-8').read().split('\n')


def 잘라내기(시작, 끝):
    """margin_embed.html 의 시작~끝 줄을 그대로 (1-based, 끝 포함)."""
    return '\n'.join(원본[시작 - 1:끝])


# ── 원본 조각 (파일에서 직접 잘라낸다 — 손으로 적지 않는다) ─────────────
표_CSS    = 잘라내기(362, 397)   # .table-wrap ~ tbody tr:hover
정렬_CSS  = 잘라내기(946, 946)   # [모음전 정렬 2026-08-02] 한 줄 <style>
정렬_본문 = re.sub(r'^\s*<style>|</style>\s*$', '', 정렬_CSS).strip()
헤더_CSS  = 잘라내기(366, 377)   # .table-header ~ h3

조각들 = {'표 CSS(362~397행)': 표_CSS, '정렬 CSS(946행)': 정렬_본문}

# ── 화면에 실제로 보이는 값 (사장님 화면 캡처 그대로) ────────────────────
행들 = [
    ('2026-07-26', '1,861,249', '1,549,885', '179,431', '9.6%', '35'),
    ('2026-07-27', '2,275,286', '1,930,738', '160,572', '7.1%', '42'),
    ('2026-07-28', '1,630,220', '1,373,161', '134,205', '8.2%', '27'),
    ('2026-07-29', '1,826,700', '1,606,879', '114,687', '6.3%', '27'),
    ('2026-07-30', '1,964,520', '1,673,141', '186,457', '9.5%', '31'),
    ('2026-07-31', '1,801,740', '1,545,896', '145,053', '8.1%', '29'),
    ('2026-08-01', '896,109',   '743,480',   '93,637',  '10.4%', '15'),
    ('2026-08-02', '1,014,986', '811,490',   '113,309', '11.2%', '12'),
]


def 표(th_클래스, td건수_클래스=''):
    """원본 aggTable(margin_embed.html:4284) 과 같은 뼈대.
       th_클래스 = '' 이면 원본 그대로(머리글에 표시 없음)."""
    c = (' class="%s"' % th_클래스) if th_클래스 else ''
    h = ['<div class="table-wrap">',
         '<div class="table-header"><h3>일별 마진 (8일)</h3>',
         '<button class="btn btn-outline btn-sm">엑셀 다운로드</button></div>',
         '<table><thead><tr>',
         '<th>일자</th><th%s>매출</th><th%s>매입</th><th%s>순마진</th>'
         '<th%s>마진율</th><th%s>건수</th>' % (c, c, c, c, c),
         '</tr></thead><tbody>']
    for d, a, b, n, p, cnt in 행들:
        tc = (' class="%s"' % td건수_클래스) if td건수_클래스 else ''
        h.append('<tr><td style="font-weight:600">%s</td>'
                 '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>'
                 '<td class="num">%s</td><td%s>%s</td></tr>' % (d, a, b, n, p, tc, cnt))
    h.append('</tbody></table></div>')
    return '\n'.join(h)


현재표 = 표('')                 # 지금 화면 — 머리글에 아무 표시가 없다
A표    = 표('num', 'num')       # 머리글도 값을 따라 오른쪽 + 건수도 숫자칸으로
B표    = 표('ctr', 'num')       # 머리글만 가운데
C표    = 표('ctr', 'ctr')       # 머리글·값 둘 다 가운데 (사장님 지시)


def mock(제목, 주소, 안, 덧붙임=''):
    return ('<div class="mock-win"><div class="mock-bar"><span>●●●</span>'
            '<span class="url">%s</span></div>'
            '<div class="mock-content %s">%s</div></div>' % (주소, 덧붙임, 안))


HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>모음전 시안 v1 — 폰트·줄간격·정렬 통일</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link rel="stylesheet" href="https://rsms.me/inter/inter.css">
<style>
:root{
  --글꼴:'Pretendard','Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Segoe UI',system-ui,sans-serif;
  --ink:#1D1D1F; --sub:#6E6E73; --line:#D2D2D7; --line2:#E8E8ED;
  --bg:#F5F5F7; --surface:#FFFFFF; --blue:#0071E3; --red:#FF3B30;
  --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px;
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

/* ── 결정 탭 (위) ── */
.dtabs{position:sticky;top:0;z-index:30;display:flex;gap:8px;background:#F5F5F7;
       padding:12px 0;border-bottom:1px solid var(--line);margin-bottom:20px}
.dtab{flex:1;text-align:left;background:#fff;border:1px solid var(--line);
      border-radius:12px;padding:12px 16px;cursor:pointer;font-family:inherit;
      transition:border-color .24s cubic-bezier(.4,0,.6,1)}
.dtab.on{border-color:var(--blue);border-width:2px;padding:11px 15px}
.d-name{font-size:14px;font-weight:600;line-height:1.35}
.d-desc{font-size:12px;color:var(--sub);line-height:1.33;margin-top:2px}
.d-key{display:inline-block;background:var(--line2);border-radius:4px;
       padding:0 5px;font-size:11px;color:var(--sub);margin-right:4px}

/* ── 변형 탭 (안) ── */
.vtabs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.vtab{background:#fff;border:1px solid var(--line);border-radius:980px;
      padding:8px 16px;cursor:pointer;font-family:inherit;font-size:13px;
      line-height:1.33;transition:all .24s cubic-bezier(.4,0,.6,1)}
.vtab.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.vtab .rec{font-size:11px;color:#34C759;font-weight:600;margin-left:4px}
.vtab.on .rec{color:#7CE29B}

.dpane,.vpane{display:none}
.dpane.on,.vpane.on{display:block}

/* ── 미리보기 창 (1920 기준) ── */
.mock-win{background:#fff;border:1px solid var(--line);border-radius:10px;
          overflow:hidden;margin-bottom:16px}
.mock-bar{background:#F5F5F7;padding:10px 16px;font-size:12px;color:var(--sub);
          border-bottom:1px solid var(--line2);display:flex;align-items:center;gap:8px}
.mock-bar .url{background:#fff;padding:4px 12px;border-radius:5px;
               font-family:ui-monospace,monospace;font-size:11.5px;flex:1}
.mock-content{padding:24px 28px;background:#fff}

.cap{font-size:12px;color:var(--sub);line-height:1.33;margin:0 0 12px}
.cap b{color:var(--ink);font-weight:600}

/* ══ 원본 코드 — margin_embed.html 에서 그대로 잘라 넣은 것 ══ */
__표_CSS__

/* margin_embed.html:946 (한 줄 style) 그대로 */
__정렬_CSS__

/* 원본에 없어 시안에서 보태는 부품만 아래에 둔다 */
.btn{border:1px solid var(--line);background:#fff;border-radius:8px;
     padding:8px 14px;font-size:13px;font-family:inherit;cursor:pointer;line-height:1.33}

/* ── 결정 1 — 머리글 정렬 ── */
.v-A .table-wrap th.num{text-align:right}
.v-B .table-wrap th.ctr{text-align:center}
.v-B .table-wrap td.num{text-align:right}
/* C — 머리글·값 둘 다 가운데 (사장님 지시).
   ★ 값 칸은 원본이 .num(오른쪽)으로 굳어 있다 → .v-C 안에서 그 규칙을 덮어야 한다.
     (처음에 머리글만 가운데로 가고 값은 오른쪽에 남던 결함 — 렌더 실측에서 잡힘)
   자릿수 폭은 고정해 둔다(tabular-nums) — 가운데라도 숫자 폭이 들쭉날쭉하면 더 삐뚤어 보인다. */
.v-C .table-wrap th.ctr,.v-C .table-wrap td.ctr,
.v-C .table-wrap th.num,.v-C .table-wrap td.num{text-align:center}
.v-C .table-wrap td.ctr,.v-C .table-wrap td.num{font-variant-numeric:tabular-nums}
.v-C .table-wrap td:first-child,.v-C .table-wrap th:first-child{text-align:center}

/* ── 결정 2 — 줄간격·줄여백 ── */
/* A 전면 반올림 : 규칙 7단(4의 배수)으로 */
.v2-A .table-wrap th{padding:var(--sp-2) var(--sp-3)}
.v2-A .table-wrap td{padding:var(--sp-2) var(--sp-3)}
.v2-A .table-wrap table{font-size:14px;line-height:1.33}
.v2-A .table-header{margin-bottom:var(--sp-2)}
.v2-A .table-wrap{margin-bottom:var(--sp-5)}
/* B 표·목록만 : 표 안쪽만 규칙값, 바깥 여백은 원본 유지 */
.v2-B .table-wrap th{padding:var(--sp-2) var(--sp-3)}
.v2-B .table-wrap td{padding:var(--sp-2) var(--sp-3)}
.v2-B .table-wrap table{line-height:1.33}
/* C 값만 통일 : 화면은 한 픽셀도 안 바뀐다 (원본 그대로) */

/* ── 결정 3 — 글꼴 ──
   ★ 클래스가 .mock-content 자신에 붙는다 → 자손 선택(.v3-A .mock-content)이 아니라
     같은 요소 선택(.mock-content.v3-A)이라야 걸린다. 렌더 실측에서 잡힌 결함. */
.mock-content.v3-A{font-family:var(--글꼴)}
.mock-content.v3-B{font-family:var(--글꼴)}
.v3-B .table-wrap td.num,.v3-B .table-wrap th.num{font-family:'Inter',var(--글꼴)}
/* 지금(참고) — stripe.css 가 --font 를 Inter 먼저로 덮어쓴 상태 그대로 */
.mock-content.v3-now{font-family:'Inter','Pretendard',-apple-system,system-ui,sans-serif}

/* 두 표를 위아래로 붙여 비교 */
.stack .mock-win{margin-bottom:8px}
.now-tag{display:inline-block;background:var(--line2);color:var(--sub);
         border-radius:980px;padding:2px 10px;font-size:11px;font-weight:600;
         line-height:1.33;margin-bottom:8px}
.new-tag{background:rgba(0,113,227,.10);color:var(--blue)}
table{font-variant-numeric:normal}
</style></head><body>
<div class="page">
<h1>폰트·줄간격·정렬 통일</h1>
<p class="lead">보내주신 「일별 마진」 화면을 원본 코드 그대로 가져와, 결정할 3가지를 각각 비교합니다.
숫자·글자는 사장님 화면에 보이던 값 그대로입니다.</p>

<div class="note chk">
  <b>눈으로 확인해 주실 것</b>
  <ul>
    <li>① 「매출」 글자와 그 아래 숫자가 한 줄로 맞는가</li>
    <li>② 「건수」 칸 숫자가 다른 숫자들과 같은 쪽에 붙었는가</li>
    <li>③ 자릿수가 세로로 가지런한가 (1,861,249 ↔ 896,109)</li>
  </ul>
</div>

<div class="note">
  <b>원본에서 바뀐 곳</b>
  <ul>
    <li>표의 생김새(칸 크기·선·색·글자)는 <b>margin_embed.html 362~397행·946행을 그대로</b> 넣었습니다 — 손대지 않았습니다.</li>
    <li>얹은 것은 <b>머리글에 붙는 표시 한 가지</b>뿐입니다. 칸을 새로 만들거나 자리를 옮기지 않았습니다.</li>
  </ul>
</div>

<div class="dtabs">
  <button class="dtab on" data-d="d1"><div class="d-name">1. 머리글 정렬</div>
    <div class="d-desc"><span class="d-key">1</span>「매출」과 숫자가 양끝으로 갈라진 것</div></button>
  <button class="dtab" data-d="d2"><div class="d-name">2. 줄간격·줄여백</div>
    <div class="d-desc"><span class="d-key">2</span>규칙 밖 값 2,478곳을 어디까지 모을지</div></button>
  <button class="dtab" data-d="d3"><div class="d-name">3. 글꼴</div>
    <div class="d-desc"><span class="d-key">3</span>지금 Inter 로 그려지는 것을 되돌릴지</div></button>
  <button class="dtab" data-d="d4"><div class="d-name">4. 합친 안 (최종)</div>
    <div class="d-desc"><span class="d-key">4</span>둘 다 가운데 + 표 여백 + Pretendard</div></button>
</div>

<!-- ══ 결정 1 ══ -->
<div class="dpane on" id="d1">
  <p class="cap"><b>지금 화면</b> — 머리글은 왼쪽 끝, 숫자는 오른쪽 끝. 한 칸 안에서 양끝으로 갈라져 있습니다.</p>
  <span class="now-tag">지금</span>
  __현재표_MOCK__
  <div class="vtabs">
    <button class="vtab on" data-v="v1c">C. 머리글·내용 둘 다 가운데<span class="rec">사장님 지시</span></button>
    <button class="vtab" data-v="v1a">A. 둘 다 오른쪽</button>
    <button class="vtab" data-v="v1b">B. 머리글만 가운데</button>
  </div>
  <div class="vpane on" id="v1c">
    <span class="now-tag new-tag">C안 — 둘 다 가운데</span>
    <p class="cap">머리글과 숫자가 칸 한가운데에서 같은 축으로 맞습니다. 숫자 폭은 고정해 뒀습니다.<br>
       <b>같이 봐 주실 것</b> — 자릿수가 다른 줄(1,861,249 ↔ 896,109)의 <b>끝자리가 세로로 맞는지</b>.</p>
    __C표_MOCK__
  </div>
  <div class="vpane" id="v1a">
    <span class="now-tag new-tag">A안 — 둘 다 오른쪽</span>
    <p class="cap">머리글이 숫자를 따라 오른쪽으로 옵니다. 끝자리가 세로로 딱 맞습니다.</p>
    __A표_MOCK__
  </div>
  <div class="vpane" id="v1b">
    <span class="now-tag new-tag">B안 — 머리글만 가운데</span>
    <p class="cap">머리글만 한가운데. 지금보다는 가깝지만 숫자와 완전히 맞지는 않습니다.</p>
    __B표_MOCK__
  </div>
</div>

<!-- ══ 결정 2 ══ -->
<div class="dpane" id="d2">
  <p class="cap"><b>지금 화면</b> — 칸 안 여백이 11·12·14px 입니다(규칙은 4의 배수 7단).</p>
  <span class="now-tag">지금</span>
  __현재표_MOCK2__
  <div class="vtabs">
    <button class="vtab" data-v="v2a">A. 전면 반올림</button>
    <button class="vtab on" data-v="v2b">B. 표·목록만 먼저<span class="rec">추천</span></button>
    <button class="vtab" data-v="v2c">C. 값만 통일</button>
  </div>
  <div class="vpane" id="v2a">
    <span class="now-tag new-tag">A안 — 전면 반올림</span>
    <p class="cap">글자·여백·줄간격을 전부 규칙값으로. 한 번에 통일되지만 표가 조금 촘촘해집니다.</p>
    __A2표_MOCK__
  </div>
  <div class="vpane on" id="v2b">
    <span class="now-tag new-tag">B안 — 표·목록만 먼저</span>
    <p class="cap">표 안쪽 여백·줄간격만 규칙값으로. 카드·제목 등 바깥은 지금 그대로 둡니다.</p>
    __B2표_MOCK__
  </div>
  <div class="vpane" id="v2c">
    <span class="now-tag new-tag">C안 — 값만 통일</span>
    <p class="cap"><b>화면은 한 픽셀도 안 바뀝니다.</b> 규칙 문서와 검사기만 맞추고 화면은 나중에.</p>
    __C2표_MOCK__
  </div>
</div>

<!-- ══ 결정 3 ══ -->
<div class="dpane" id="d3">
  <p class="cap"><b>지금 화면</b> — 숫자·영문이 Inter, 한글이 Pretendard 로 나뉘어 그려집니다.
     1과 7, 쉼표 모양을 위아래로 견줘 보세요.</p>
  <span class="now-tag">지금 (Inter)</span>
  __현재표_MOCK3__
  <div class="vtabs">
    <button class="vtab on" data-v="v3a">A. Pretendard 한 벌<span class="rec">추천</span></button>
    <button class="vtab" data-v="v3b">B. 숫자만 Inter</button>
  </div>
  <div class="vpane on" id="v3a">
    <span class="now-tag new-tag">A안 — Pretendard 한 벌</span>
    <p class="cap">한글·숫자·영문이 같은 글꼴이 됩니다. 규칙서가 정한 글꼴입니다.</p>
    __A3표_MOCK__
  </div>
  <div class="vpane" id="v3b">
    <span class="now-tag new-tag">B안 — 숫자만 Inter</span>
    <p class="cap">숫자만 Inter 로 남깁니다. 숫자 폭은 고르지만 한글과 획 굵기가 계속 다릅니다.</p>
    __B3표_MOCK__
  </div>
</div>

<!-- ══ 결정 4 — 합친 안 ══ -->
<div class="dpane" id="d4">
  <div class="note">
    <b>합친 안 = 1번 C + 2번 B + 3번 A</b>
    <ul>
      <li>표 머리글·내용을 <b>둘 다 가운데</b>로 (사장님 지시)</li>
      <li>표 안쪽 <b>여백·줄간격만</b> 규칙값으로 — 카드·제목 등 바깥은 지금 그대로</li>
      <li>글꼴을 <b>Pretendard 한 벌</b>로 (Inter 걷어냄)</li>
    </ul>
  </div>
  <span class="now-tag">지금</span>
  __현재표_MOCK4__
  <span class="now-tag new-tag">합친 안</span>
  <p class="cap">이 모양으로 프로그램 전체 표에 적용합니다.</p>
  __최종표_MOCK__
</div>

</div>
<script>
function pick(sel, on, paneSel){
  document.querySelectorAll(sel).forEach(function(b){
    b.addEventListener('click', function(){
      var grp = b.parentElement;
      grp.querySelectorAll(sel.split(' ').pop()).forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      var id = b.dataset.d || b.dataset.v;
      var host = b.dataset.d ? document : grp.parentElement;
      host.querySelectorAll(paneSel).forEach(function(p){p.classList.toggle('on', p.id===id);});
    });
  });
}
pick('.dtab', 'on', '.dpane');
pick('.vtab', 'on', '.vpane');
document.addEventListener('keydown', function(e){
  if(/^[1234]$/.test(e.key)){ var t=document.querySelectorAll('.dtab')[+e.key-1]; if(t) t.click(); }
  var tabs=[].slice.call(document.querySelectorAll('.dtab'));
  var i=tabs.findIndex(function(t){return t.classList.contains('on');});
  if(e.key==='ArrowRight'&&tabs[i+1]) tabs[i+1].click();
  if(e.key==='ArrowLeft'&&tabs[i-1]) tabs[i-1].click();
});
</script></body></html>"""

주소 = 'mou-m.com/orders/?tab=margin — 통계·분석 › 일별'
치환 = {
    '__표_CSS__': 표_CSS,
    '__정렬_CSS__': 정렬_본문,
    '__현재표_MOCK__':  mock('', 주소, 현재표),
    '__A표_MOCK__':     mock('', 주소, A표, 'v-A'),
    '__B표_MOCK__':     mock('', 주소, B표, 'v-B'),
    '__C표_MOCK__':     mock('', 주소, C표, 'v-C'),
    '__현재표_MOCK4__': mock('', 주소, 현재표, 'v3-now'),
    '__최종표_MOCK__':  mock('', 주소, C표, 'v-C v2-B v3-A'),
    '__현재표_MOCK2__': mock('', 주소, 현재표),
    '__A2표_MOCK__':    mock('', 주소, A표, 'v-A v2-A'),
    '__B2표_MOCK__':    mock('', 주소, A표, 'v-A v2-B'),
    '__C2표_MOCK__':    mock('', 주소, A표, 'v-A'),
    '__현재표_MOCK3__': mock('', 주소, 현재표, 'v3-now'),
    '__A3표_MOCK__':    mock('', 주소, A표, 'v-A v3-A'),
    '__B3표_MOCK__':    mock('', 주소, A표, 'v-A v3-B'),
}
out = HTML
for k, v in 치환.items():
    assert k in out, '자리표시자를 못 찾음: %s' % k
    out = out.replace(k, v)

# ── 보존 증명 — 원본 문자열이 통째로 들어갔는지 기계로 대조 ────────────
print('=' * 58)
print(' 원본 보존 대조 (자기 보고 아님 — 문자열 포함 여부)')
print('=' * 58)
누락 = 0
for 이름, 조각 in 조각들.items():
    있음 = 조각 in out
    print(' %-22s %s  (%s자)' % (이름, '통째로 들어감 ✅' if 있음 else '빠짐 ❌', format(len(조각), ',')))
    if not 있음:
        누락 += 1

# 잔글씨 — 원본 표의 값·머리글이 한 개도 안 빠졌는지
잔글씨 = ['일자', '매출', '매입', '순마진', '마진율', '건수', '엑셀 다운로드']
for _r in 행들:
    잔글씨.extend(_r)
빠진잔글씨 = [s for s in 잔글씨 if s not in out]
print(' %-22s %d개 중 %d개 빠짐' % ('잔글씨(머리글·값)', len(잔글씨), len(빠진잔글씨)))
if 빠진잔글씨:
    print('   빠진 것:', ', '.join(빠진잔글씨))
    누락 += len(빠진잔글씨)

print('-' * 58)
if 누락:
    print(' ❌ 누락 %d건 — 시안을 쓰지 않고 멈춥니다.' % 누락)
    sys.exit(1)
print(' ✅ 누락 0 — 시안을 씁니다.')
io.open(OUT, 'w', encoding='utf-8').write(out)
print(' 저장: %s' % OUT)
