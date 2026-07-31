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
FS   = {11, 12, 14, 17, 24, 32, 48}   # 전부 애플 공홈 실사용 값
FS_최소 = 11                          # 읽는 글의 하한(애플 실측: 법적 고지 11px)
SP   = {0, 4, 8, 12, 16, 24, 32, 48}
RAD  = {0, 8, 12, 18, 980, 9999}      # 애플 실측: 12px 최다, 18~20 큰카드, 980 알약
FW   = {400, 600, 700}
COLORS = {
    # 파랑 3역할 (애플 웹 실측 — iOS 의 #007AFF 와 다르다)
    '#0071e3',   # 버튼 배경
    '#0066cc',   # 링크 글자
    '#2997ff',   # 검정 구역 링크 · 포커스
    # 의미 색
    '#34c759', '#ff3b30', '#ff9500', '#5ac8fa',
    # 회색 (애플 실측 hex)
    '#fafafc', '#f5f5f7', '#e8e8ed', '#d2d2d7',
    '#86868b', '#6e6e73', '#424245', '#1d1d1f',
    '#ffffff', '#fff', '#000000', '#000',
    # 검정 구역 3층 (애플 실측: #000 → #1D1D1F → #2A2A2D)
    '#2a2a2d', '#c7c7cc',
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
# var(...) 호출 안(중첩 포함) — design_sweep 이 치환 결과에 항상 동반하는
# 예비값(`var(--ink,#191F28)`)이 여기 해당한다. 예비값은 `class="ds"` 가
# 없는 current 모드에서만 실제로 쓰이는 안전망이고, 그 자체가 "규칙에 없는
# 색을 새로 하드코딩한 것"이 아니라 스윕 전 원래 색을 보존한 것이므로
# 위반으로 세지 않는다. var() 의 첫 인자(커스텀 프로퍼티 이름)에는 애초에
# hex 처럼 생긴 문자열이 올 수 없으므로, var(...) 안의 hex 는 전부 예비값이다.
RE_DEF = re.compile(r'--([a-zA-Z0-9_-]+)\s*:')
# 애플은 3개 페이지 전부 box-shadow 가 0곳이었다 — 층은 선과 밝기로 만든다
RE_SHADOW = re.compile(r'box-shadow:\s*(?!none)(?!0 0 0 1px)[^;}\n]+')

# 한국어에서 애플은 자간을 건드리지 않는다(0). 음수 자간은 영문 헤드라인 관습.
RE_NEG_LS = re.compile(r'letter-spacing:\s*-(0?\.\d+)(em|px)')
RE_PX  = re.compile(r'(-?[\d.]+)px')
# class 에 num/숫자 가 있는데 정렬을 가운데로 준 경우
RE_NUM_CTR = re.compile(r'(?:td|th)\.(?:num|숫자)[^{]*\{[^}]*text-align:\s*center')

_VAR_CALL_RE = re.compile(r'\bvar\(', re.IGNORECASE)


def _var_구간(본문):
    """본문 안 모든 `var(...)` 호출의 [시작, 끝) 구간을 돌려준다(괄호 중첩 대응).

    design_sweep.py 의 `_보호구간`과 같은 방식의 괄호 매칭 — 여기서는
    var() 안의 hex 를 "예비값이라 위반이 아님"으로 걸러내는 데만 쓴다."""
    구간 = []
    n = len(본문)
    for m in _VAR_CALL_RE.finditer(본문):
        depth = 1
        j = m.end()
        while j < n and depth > 0:
            if 본문[j] == '(':
                depth += 1
            elif 본문[j] == ')':
                depth -= 1
            j += 1
        구간.append((m.start(), j))
    return 구간


def _구간안(구간들, pos):
    return any(s <= pos < e for s, e in 구간들)


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
        if v < FS_최소:
            # 규칙 밖인 데다 「너무 작아서 못 읽는」 것이라 따로 센다
            나온것.append(('너무 작은 글자', '%gpx' % v, 줄(m.start())))
        elif v not in FS:
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
    var_구간 = _var_구간(본문)
    for m in RE_HEX.finditer(본문):
        if _구간안(var_구간, m.start()):
            continue  # var(--토큰,#원래색) 의 예비값 — 위반이 아니다(Job 1)
        v = m.group(0).lower()
        if v not in COLORS:
            나온것.append(('색', v, 줄(m.start())))
    for m in RE_DEF.finditer(본문):
        if m.group(1) in 공용변수:
            나온것.append(('공용변수 재정의', '--' + m.group(1), 줄(m.start())))
    # 숫자칸을 가운데로 정렬하면 자릿수를 눈으로 셀 수 없다
    for m in RE_NUM_CTR.finditer(본문):
        나온것.append(('숫자칸 가운데정렬', m.group(0)[:40], 줄(m.start())))
    # 그림자 — 애플은 쓰지 않는다. 층은 1px 선과 배경 밝기로.
    for m in RE_SHADOW.finditer(본문):
        나온것.append(('그림자', m.group(0)[:34], 줄(m.start())))
    # 음수 자간 — 한글에서는 쓰지 않는다
    for m in RE_NEG_LS.finditer(본문):
        나온것.append(('음수 자간', '-' + m.group(1) + m.group(2), 줄(m.start())))
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
