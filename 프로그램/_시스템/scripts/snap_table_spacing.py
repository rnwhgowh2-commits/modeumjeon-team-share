# -*- coding: utf-8 -*-
"""표 안쪽 여백·줄간격을 규칙값으로 맞춘다 (사장님 확정 「2-B」).

무엇을 하나
    표와 관련된 CSS 규칙(th·td·table·tr 이 든 선택자)만 골라,
    그 안의 padding / line-height 를 가장 가까운 규칙값으로 바꾼다.
        여백    → 0·4·8·12·16·24·32·48 (4의 배수 7단)
        줄간격  → 1.33 (표 안 글씨)

🔴 안전장치 (실제로 사고가 났던 자리다)
    · .html 은 <style>…</style> **안에서만** 고친다.
      예전에 파일 전체에 치환을 돌려 자바스크립트를 죽인 채 배포한 적이 있다.
    · 표와 무관한 선택자는 건드리지 않는다.
    · 이미 규칙값인 것은 손대지 않는다.
    · --sp-* 같은 변수로 쓴 값은 이미 규칙값이므로 건너뛴다.

쓰는 법
    python 프로그램/_시스템/scripts/snap_table_spacing.py            # 미리보기(안 고침)
    python 프로그램/_시스템/scripts/snap_table_spacing.py --적용     # 실제로 고침
"""
import io, os, re, sys, collections

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
TPL  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates')
CSS  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'static')

여백규칙 = [0, 4, 8, 12, 16, 24, 32, 48]
표줄간격 = 1.33

# 표와 관련된 선택자인가 — th·td·table·tr 이 낱말로 들어 있어야 한다
RE_표선택자 = re.compile(r'(?:^|[\s,>+~.#\[])(?:th|td|table|tr|thead|tbody|tfoot)\b', re.I)
RE_규칙     = re.compile(r'([^{}]+)\{([^{}]*)\}')
RE_STYLE    = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.I | re.S)
RE_PAD      = re.compile(r'\b(padding(?:-(?:top|right|bottom|left))?)\s*:\s*([^;{}]+)')
RE_LH       = re.compile(r'\b(line-height)\s*:\s*([^;{}]+)')
RE_PX       = re.compile(r'(\d+(?:\.\d+)?)px')

바뀜 = collections.Counter()
기록 = []


def 가까운여백(v):
    """가장 가까운 규칙값. 같은 거리면 작은 쪽(규칙서 「애매하면 작은 쪽」).
    ★ 단 있던 여백을 0 으로 없애지는 않는다 — 그건 「가깝게 맞추기」가 아니라
      칸을 붙여 버리는 것이라 화면이 눈에 띄게 달라진다(2px→0px 6곳에서 걸렸다)."""
    n = min(여백규칙, key=lambda x: (abs(x - v), x))
    if n == 0 and v > 0:
        return 4
    return n


def 여백고치기(값, 자리):
    """padding 값 문자열 안의 px 들을 규칙값으로."""
    if 'var(' in 값 or 'calc(' in 값 or '%' in 값 or 'em' in 값:
        return 값, False
    손댐 = [False]

    def 하나(m):
        v = float(m.group(1))
        if v > 48:                      # 아주 큰 값은 표 칸 여백이 아니다
            return m.group(0)
        n = 가까운여백(v)
        if abs(n - v) < 0.01:
            return m.group(0)
        손댐[0] = True
        바뀜['여백 %gpx → %dpx' % (v, n)] += 1
        기록.append((자리, '여백', '%gpx' % v, '%dpx' % n))
        return '%dpx' % n

    새값 = RE_PX.sub(하나, 값)
    return 새값, 손댐[0]


def 줄간격고치기(값, 자리):
    raw = 값.strip()
    if 'var(' in raw or raw.lower() in ('normal', 'inherit', 'unset', 'initial'):
        return 값, False
    m = re.match(r'^(\d+(?:\.\d+)?)(px|em|rem)?$', raw)
    if not m:
        return 값, False
    v = float(m.group(1))
    단위 = m.group(2)
    if 단위 == 'px':
        return 값, False                # px 줄간격은 글자 크기와 따로 논다 — 여기선 안 건드림
    if abs(v - 표줄간격) < 0.01:
        return 값, False
    if v < 1.0 or v > 2.2:
        return 값, False
    바뀜['줄간격 %g → %g' % (v, 표줄간격)] += 1
    기록.append((자리, '줄간격', str(v), str(표줄간격)))
    return 값.replace(m.group(0), str(표줄간격)), True


def CSS덩어리고치기(css, 파일):
    """CSS 문자열 하나를 규칙 단위로 훑는다."""
    손댐 = [False]

    def 규칙하나(m):
        선택자, 본문 = m.group(1), m.group(2)
        if not RE_표선택자.search(선택자):
            return m.group(0)
        자리 = '%s  {%s}' % (파일, 선택자.strip().splitlines()[-1].strip()[:46])
        새본문 = 본문

        def pad(mm):
            새, 바뀜여부 = 여백고치기(mm.group(2), 자리)
            if 바뀜여부:
                손댐[0] = True
            return '%s:%s' % (mm.group(1), 새)
        새본문 = RE_PAD.sub(pad, 새본문)

        def lh(mm):
            새, 바뀜여부 = 줄간격고치기(mm.group(2), 자리)
            if 바뀜여부:
                손댐[0] = True
            return '%s:%s' % (mm.group(1), 새)
        새본문 = RE_LH.sub(lh, 새본문)

        return '%s{%s}' % (선택자, 새본문)

    새 = RE_규칙.sub(규칙하나, css)
    return 새, 손댐[0]


def 스타일블록만_여백스냅(text, 이름=''):
    """HTML 문자열의 <style> 블록 **안에서만** 표 여백·줄간격을 규칙값으로 맞춘다.

    파일을 읽고 쓰는 `파일하나` 와 같은 일을 **순수 함수**로 한다.
    쓰는 곳: tools/build_margin_embed.py — 마진계산기 서빙본은 원본에서 빌드되는데,
    이 스윕이 서빙본에만 걸려 있어 재빌드하면 여백 통일이 통째로 되돌아갔다
    (2026-08-06 실측: 동치 가드 2건이 그 드리프트로 깨져 있었다).
    빌드가 이 함수를 같이 부르면 재빌드해도 안 잃는다.

    🔴 <style> 밖은 절대 안 건드린다 — 예전에 파일 전체 치환으로 JS 를 죽인 적이 있다.
    """
    def 스타일하나(m):
        안, _ = CSS덩어리고치기(m.group(2), 이름)
        return m.group(1) + 안 + m.group(3)
    return RE_STYLE.sub(스타일하나, text)


def 파일하나(path, 적용):
    rel = os.path.relpath(path, ROOT).replace('\\', '/')
    txt = io.open(path, encoding='utf-8').read()
    원본 = txt

    if path.endswith('.css'):
        txt, _ = CSS덩어리고치기(txt, rel)
    else:
        # 🔴 .html 은 <style> 안에서만
        def 스타일하나(m):
            안, _ = CSS덩어리고치기(m.group(2), rel)
            return m.group(1) + 안 + m.group(3)
        txt = RE_STYLE.sub(스타일하나, txt)

    if txt != 원본:
        if 적용:
            io.open(path, 'w', encoding='utf-8').write(txt)
        return True
    return False


def main():
    적용 = '--적용' in sys.argv
    고친파일 = []
    for base, dirs, names in os.walk(TPL):
        dirs[:] = [d for d in dirs if not d.startswith('_backup')]
        for n in sorted(names):
            if n.endswith('.html'):
                if 파일하나(os.path.join(base, n), 적용):
                    고친파일.append(os.path.relpath(os.path.join(base, n), ROOT))
    for n in sorted(os.listdir(CSS)):
        if n.endswith('.css') and n not in ('tokens.css', 'table_align.css'):
            if 파일하나(os.path.join(CSS, n), 적용):
                고친파일.append('static/' + n)

    print('=' * 60)
    print(' 표 안쪽 여백·줄간격 규칙값 맞추기 %s' % ('(실제 적용)' if 적용 else '(미리보기 — 안 고침)'))
    print('=' * 60)
    print(' 바뀐 곳 합계 : %s곳 / 파일 %d개' % (format(sum(바뀜.values()), ','), len(고친파일)))
    print('-' * 60)
    for k, v in 바뀜.most_common(20):
        print('   %-24s %5d곳' % (k, v))
    print('-' * 60)
    파일별 = collections.Counter(r[0].split('  ')[0] for r in 기록)
    print(' 많이 바뀐 파일 10개')
    for f, c in 파일별.most_common(10):
        print('   %5d곳  %s' % (c, f))
    if not 적용:
        print('-' * 60)
        print(' 실제로 고치려면: --적용')


if __name__ == '__main__':
    main()
