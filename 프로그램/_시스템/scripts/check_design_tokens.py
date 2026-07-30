# -*- coding: utf-8 -*-
"""디자인 규칙 검사 — 규칙에 없는 크기·여백·색·굵기를 찾아낸다.

정본 규칙 : docs/디자인-규칙.md
실제 값   : 프로그램/_시스템/webapp/static/tokens.css

쓰는 법
    python 프로그램/_시스템/scripts/check_design_tokens.py            # 전체 요약
    python 프로그램/_시스템/scripts/check_design_tokens.py --기준저장  # 지금 상태를 기준선으로
    python 프로그램/_시스템/scripts/check_design_tokens.py --화면 orders   # 한 화면만
    python 프로그램/_시스템/scripts/check_design_tokens.py --자세히 20     # 위반 위치 보기

기준선(_design_baseline.json)보다 위반이 늘면 종료코드 1 을 낸다.
→ 이미 있는 6천 곳을 당장 다 고치라는 게 아니라, 「더 나빠지지 않게」 막는 장치다.
"""
import io, os, re, sys, json, collections

# 윈도우 기본 콘솔(cp949)에서 한글·기호가 깨지지 않게 고정
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# 이 파일: <ROOT>/프로그램/_시스템/scripts/check_design_tokens.py → 네 단계 위가 ROOT
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
TPL  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates')
assert os.path.isdir(TPL), '템플릿 폴더를 못 찾았습니다: %s' % TPL
BASE = os.path.join(ROOT, '_design_baseline.json')

# ── 규칙 (docs/디자인-규칙.md 와 같아야 한다) ─────────────────────────
FS   = {11, 12, 14, 17, 22, 32, 64}
SP   = {0, 4, 8, 12, 16, 24, 32, 48}
RAD  = {0, 6, 10, 16, 980, 9999}
FW   = {400, 600, 700}
COLORS = {
    '#007aff', '#34c759', '#ff3b30', '#ff9500', '#5ac8fa',
    '#f5f5f7', '#e8e8ed', '#d2d2d7', '#86868b', '#424245', '#1d1d1f',
    '#ffffff', '#fff', '#000000', '#000', '#fbfbfd',
}
# 화면마다 다시 정의하면 안 되는 공용 변수
공용변수 = {'ink', 'sub', 'faint', 'line', 'line2', 'bg', 'surface',
            'blue', 'red', 'green', 'amber', 'primary', 'mono',
            'n100', 'n200', 'n300', 'n500', 'n600', 'n700'}

RE_FS  = re.compile(r'font-size:\s*([\d.]+)px')
RE_SP  = re.compile(r'(?:padding|margin|gap)(?:-(?:top|right|bottom|left))?:\s*([^;"\'}\n]+)')
RE_RAD = re.compile(r'border-radius:\s*([\d.]+)px')
RE_FW  = re.compile(r'font-weight:\s*(\d{3})')
RE_HEX = re.compile(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b')
RE_DEF = re.compile(r'--([a-zA-Z0-9_-]+)\s*:')
RE_PX  = re.compile(r'(-?[\d.]+)px')


def 검사(경로, 본문):
    """한 파일의 위반을 (종류, 값, 줄번호) 목록으로 돌려준다."""
    나온것 = []
    줄시작 = [0]
    for i, ch in enumerate(본문):
        if ch == '\n':
            줄시작.append(i + 1)

    def 줄(pos):
        lo, hi = 0, len(줄시작) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if 줄시작[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for m in RE_FS.finditer(본문):
        v = float(m.group(1))
        if v not in FS:
            나온것.append(('글자크기', '%gpx' % v, 줄(m.start())))
    for m in RE_RAD.finditer(본문):
        v = float(m.group(1))
        if v not in RAD:
            나온것.append(('둥근모서리', '%gpx' % v, 줄(m.start())))
    for m in RE_FW.finditer(본문):
        v = int(m.group(1))
        if v not in FW:
            나온것.append(('굵기', str(v), 줄(m.start())))
    for m in RE_SP.finditer(본문):
        덩어리 = m.group(1)
        if 'var(' in 덩어리 or 'calc(' in 덩어리:
            continue
        for px in RE_PX.findall(덩어리):
            v = abs(float(px))
            if v not in SP:
                나온것.append(('여백', '%gpx' % v, 줄(m.start())))
    for m in RE_HEX.finditer(본문):
        v = m.group(0).lower()
        if v not in COLORS:
            나온것.append(('색', v, 줄(m.start())))
    for m in RE_DEF.finditer(본문):
        if m.group(1) in 공용변수:
            나온것.append(('공용변수 재정의', '--' + m.group(1), 줄(m.start())))
    return 나온것


def 훑기(필터=None):
    결과 = {}
    for dp, _, fns in os.walk(TPL):
        for fn in fns:
            if not fn.endswith('.html'):
                continue
            경로 = os.path.join(dp, fn)
            상대 = os.path.relpath(경로, ROOT).replace('\\', '/')
            if 필터 and 필터 not in 상대:
                continue
            try:
                본문 = io.open(경로, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            나온것 = 검사(경로, 본문)
            if 나온것:
                결과[상대] = 나온것
    return 결과


def main():
    인자 = sys.argv[1:]
    필터 = None
    if '--화면' in 인자:
        필터 = 인자[인자.index('--화면') + 1]
    자세히 = 0
    if '--자세히' in 인자:
        자세히 = int(인자[인자.index('--자세히') + 1])

    결과 = 훑기(필터)
    종류별 = collections.Counter()
    값별 = collections.defaultdict(collections.Counter)
    총계 = 0
    for 상대, 목록 in 결과.items():
        for 종, 값, _ln in 목록:
            종류별[종] += 1
            값별[종][값] += 1
            총계 += 1

    print('=' * 62)
    print(' 디자인 규칙 검사 — 규칙: docs/디자인-규칙.md')
    print('=' * 62)
    print(' 검사한 화면 : %d개 파일 (위반이 있는 것만)' % len(결과))
    print(' 위반 합계   : %s곳' % format(총계, ','))
    print('-' * 62)
    for 종, n in 종류별.most_common():
        상위 = ', '.join('%s×%s' % (v, format(c, ',')) for v, c in 값별[종].most_common(5))
        print(' %-14s %8s곳   자주 나온 값: %s' % (종, format(n, ','), 상위))
    print('-' * 62)
    print(' 위반이 많은 화면 10개')
    for 상대, 목록 in sorted(결과.items(), key=lambda x: -len(x[1]))[:10]:
        print('   %6s곳  %s' % (format(len(목록), ','), 상대))

    if 자세히:
        print('-' * 62)
        print(' 위반 위치 %d개' % 자세히)
        n = 0
        for 상대, 목록 in sorted(결과.items(), key=lambda x: -len(x[1])):
            for 종, 값, ln in 목록:
                print('   %s:%d  [%s] %s' % (상대, ln, 종, 값))
                n += 1
                if n >= 자세히:
                    break
            if n >= 자세히:
                break

    if '--기준저장' in 인자:
        io.open(BASE, 'w', encoding='utf-8').write(
            json.dumps({'총계': 총계, '종류별': dict(종류별)}, ensure_ascii=False, indent=2))
        print('-' * 62)
        print(' 기준선 저장 완료 : %s (%s곳)' % (os.path.basename(BASE), format(총계, ',')))
        return 0

    if os.path.exists(BASE) and not 필터:
        기준 = json.loads(io.open(BASE, encoding='utf-8').read())
        전 = 기준.get('총계', 0)
        print('-' * 62)
        차 = 총계 - 전
        if 차 > 0:
            print(' ❌ 기준선보다 %s곳 늘었습니다 (%s → %s)'
                  % (format(차, ','), format(전, ','), format(총계, ',')))
            print('    규칙에 있는 값으로 바꾸거나, 정말 필요하면 규칙을 먼저 고치세요.')
            return 1
        print(' ✅ 기준선 %s곳 대비 %s곳 (늘지 않았습니다)'
              % (format(전, ','), format(총계, ',')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
