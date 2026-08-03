# -*- coding: utf-8 -*-
"""글꼴·줄간격·정렬 검사 — check_design_tokens.py 가 안 보던 4가지를 본다.

기존 check_design_tokens.py 가 보는 것 : 글자크기·여백·둥근모서리·굵기·색·그림자
이 검사가 보는 것(겹치지 않음)      : ① 글꼴  ② 줄간격  ③ 정렬(헤더↔값)  ④ 숫자 자릿수

쓰는 법
    python 프로그램/_시스템/scripts/check_typography.py             # 요약
    python 프로그램/_시스템/scripts/check_typography.py --자세히 30  # 위치 보기
    python 프로그램/_시스템/scripts/check_typography.py --기준저장    # 지금을 기준선으로
"""
import io, os, re, sys, json, collections

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
TPL  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates')
CSS  = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'static')
assert os.path.isdir(TPL), '템플릿 폴더를 못 찾았습니다: %s' % TPL
BASE = os.path.join(ROOT, '_typography_baseline.json')

# ── 규칙 (tokens.css 와 같아야 한다) ────────────────────────────────
# 줄간격 — 애플 실측값. 이 목록 밖 값은 화면마다 제각각이 된다.
LH_OK = {1.18, 1.22, 1.29, 1.33, 1.35, 1.5, 1.53, 1.57, 1.59, 1.6}
LH_허용키워드 = {'normal', 'inherit', 'unset', 'initial'}

# 글꼴 — 프로젝트 글꼴은 Pretendard 한 벌. 코드용 monospace 만 예외.
#
# ★ 「var(--font) 를 쓰는 것」 자체는 위반이 아니다. 그 이름이 **무엇을 가리키냐**가 문제다.
#   실제로 겪은 일 : stripe.css 가 `--font: 'Inter', 'Pretendard', …` 로 다시 정해
#   toss.css 의 Pretendard 를 덮었고, 그 이름을 쓰는 63곳이 전부 Inter 로 그려졌다.
#   → 이름을 쓰는 자리가 아니라 **이름을 정하는 자리**를 봐야 한다.
글꼴_허용 = ('inherit', 'pretendard', 'monospace', 'ui-monospace',
             'sf mono', 'sfmono', 'menlo', 'consolas', 'd2coding', 'courier',
             '-apple-system', 'system-ui', 'blinkmacsystemfont', 'apple sd gothic neo',
             'segoe ui', 'sans-serif', 'serif')
# 글꼴 이름을 새로 정하는 자리 (--font: … / --mono: … / --글꼴: …)
# ※ --fs-mono 처럼 「크기」를 담는 이름은 뺀다(이름에 mono 가 들어갈 뿐 글꼴이 아니다).
RE_글꼴정의 = re.compile(r'--((?!fs-|size|weight)[\w가-힣-]*(?:font|mono|글꼴)[\w가-힣-]*)\s*:\s*([^;{}\n]+)')

# 숫자를 담는 칸으로 보이는 클래스 이름 (프로젝트 전체에서 실제로 쓰이는 것)
숫자칸_클래스 = ('num', '숫자', 'amount', 'price', 'qty', 'cnt', 'money', 'val')

RE_LH      = re.compile(r'line-height:\s*([^;"\'}\n]+)')
RE_FF      = re.compile(r'font-family:\s*([^;"\'}\n]+)')
RE_TA      = re.compile(r'text-align:\s*(left|right|center|start|end)')
# <th ...> / <td ...> 를 문자열 조립(JS) 안에서도 잡는다
RE_TH      = re.compile(r"<th\b([^>]*)>", re.I)
RE_TD      = re.compile(r"<td\b([^>]*)>", re.I)
RE_CLASS   = re.compile(r'class\s*=\s*[\'"\\]*([^\'">\\]*)', re.I)

# 「표 하나」 단위로 자르기 — <table ...> ... </table> (JS 문자열 조립 포함)
RE_TABLE   = re.compile(r"<table\b.*?</table>", re.I | re.S)


def 파일들():
    for base, dirs, names in os.walk(TPL):
        dirs[:] = [d for d in dirs if not d.startswith('_backup')]
        for n in sorted(names):
            if n.endswith('.html'):
                yield os.path.join(base, n)
    for n in sorted(os.listdir(CSS)):
        if n.endswith('.css'):
            yield os.path.join(CSS, n)


def 상대(p):
    return os.path.relpath(p, ROOT).replace('\\', '/')


def 줄번호(txt, pos):
    return txt.count('\n', 0, pos) + 1


def 클래스들(속성문자열):
    m = RE_CLASS.search(속성문자열 or '')
    if not m:
        return set()
    return set(w.strip() for w in m.group(1).split() if w.strip())


def 숫자칸인가(클래스집합, 속성문자열):
    for c in 클래스집합:
        low = c.lower()
        for k in 숫자칸_클래스:
            if low == k or low.endswith('-' + k) or low.startswith(k + '-'):
                return True
    if re.search(r'text-align:\s*right', 속성문자열 or '', re.I):
        return True
    return False


def 검사(자세히=0):
    위반 = collections.defaultdict(list)   # 종류 -> [(파일, 줄, 값)]

    for path in 파일들():
        try:
            txt = io.open(path, encoding='utf-8').read()
        except Exception:
            continue
        rel = 상대(path)
        is_tokens = rel.endswith('static/tokens.css')

        # 🔴 주석은 규칙이 아니다 — 빼고 본다.
        #   설명글에 적어 둔 `font-family:…` 나 `line-height:1.6` 이 위반으로 잡혔다
        #   (font_unify.css 의 「왜 만들었나」 설명이 그대로 걸렸다).
        #   줄 수는 그대로 두려고 같은 길이의 빈칸으로 바꾼다(위치 보고가 안 어긋나게).
        def _주석지우기(m):
            return re.sub(r'[^\n]', ' ', m.group(0))
        txt = re.sub(r'/\*.*?\*/', _주석지우기, txt, flags=re.S)
        if not path.endswith('.css'):
            txt = re.sub(r'\{#.*?#\}', _주석지우기, txt, flags=re.S)
            txt = re.sub(r'<!--.*?-->', _주석지우기, txt, flags=re.S)

        # ── ① 글꼴 ────────────────────────────────────────────────────
        # ①-1 글꼴 이름을 정하는 자리 — 맨 앞 글꼴이 규칙 밖이면 그 이름을 쓰는
        #      모든 자리가 통째로 규칙 밖이 된다 (Inter 사고가 바로 이것).
        for m in RE_글꼴정의.finditer(txt):
            if is_tokens:
                continue
            맨앞 = m.group(2).split(',')[0].strip().strip('\'"').lower()
            if 맨앞.startswith('var('):
                continue
            if any(k in 맨앞 for k in 글꼴_허용):
                continue
            위반['글꼴'].append((rel, 줄번호(txt, m.start()),
                               '--%s 를 %s 로 정함' % (m.group(1), 맨앞[:20])))

        # ①-2 글꼴을 직접 쓰는 자리 — 규칙 밖 글꼴 이름을 그대로 박은 곳
        for m in RE_FF.finditer(txt):
            val = m.group(1).strip().lower()
            if is_tokens or val.startswith('var('):
                continue
            맨앞 = val.split(',')[0].strip().strip('\'"')
            if not 맨앞 or any(k in 맨앞 for k in 글꼴_허용):
                continue
            위반['글꼴'].append((rel, 줄번호(txt, m.start()), 맨앞[:30]))

        # ── ② 줄간격 — 규칙에 없는 값 ──────────────────────────────────
        for m in RE_LH.finditer(txt):
            raw = m.group(1).strip()
            if is_tokens:
                continue
            low = raw.lower()
            if low in LH_허용키워드 or low.startswith('var('):
                continue
            # px/em 로 준 줄간격은 글자 크기가 바뀌면 안 따라온다 → 전부 위반
            if re.match(r'^[\d.]+(px|em|rem)$', low):
                위반['줄간격'].append((rel, 줄번호(txt, m.start()), raw))
                continue
            try:
                v = round(float(low), 2)
            except ValueError:
                continue
            if v not in LH_OK:
                위반['줄간격'].append((rel, 줄번호(txt, m.start()), raw))

        # ── ③ 정렬 — 한 표 안에서 머리글과 값의 정렬이 다른 자리 ─────────
        for t in RE_TABLE.finditer(txt):
            블록 = t.group(0)
            바닥줄 = 줄번호(txt, t.start())
            ths = [(mm.group(1), mm.start()) for mm in RE_TH.finditer(블록)]
            tds = [(mm.group(1), mm.start()) for mm in RE_TD.finditer(블록)]
            if not ths or not tds:
                continue
            # 값 칸 중 숫자칸이 있는데, 머리글 칸에는 숫자칸 표시가 하나도 없다
            숫자td = [x for x in tds if 숫자칸인가(클래스들(x[0]), x[0])]
            숫자th = [x for x in ths if 숫자칸인가(클래스들(x[0]), x[0])]
            if 숫자td and not 숫자th:
                위반['정렬-머리글'].append(
                    (rel, 바닥줄 + 블록.count('\n', 0, ths[0][1]),
                     '값 %d칸은 오른쪽인데 머리글은 왼쪽' % len(숫자td)))

        # ── ④ 숫자 자릿수 — 오른쪽 정렬인데 자릿수 고정이 없는 규칙 ───────
        # CSS 규칙 하나(선택자{...}) 단위로 본다
        for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', txt):
            선택자, 본문 = m.group(1), m.group(2)
            if 'text-align:' not in 본문:
                continue
            if not re.search(r'text-align:\s*right', 본문, re.I):
                continue
            if 'tabular-nums' in 본문 or 'font-variant-numeric' in 본문:
                continue
            if is_tokens:
                continue
            sel = 선택자.strip().splitlines()[-1].strip()[:52]
            위반['숫자자릿수'].append((rel, 줄번호(txt, m.start()), sel))

    return 위반


def 출력(위반, 자세히=0):
    print('=' * 62)
    print(' 글꼴·줄간격·정렬 검사 — 규칙: static/tokens.css')
    print('=' * 62)
    총 = sum(len(v) for v in 위반.values())
    print(' 위반 합계 : %s곳' % format(총, ','))
    print('-' * 62)
    이름 = {'글꼴': '글꼴(폰트)', '줄간격': '줄간격', '정렬-머리글': '정렬 — 머리글↔값',
            '숫자자릿수': '숫자 자릿수 고정 없음'}
    for k in ['글꼴', '줄간격', '정렬-머리글', '숫자자릿수']:
        rows = 위반.get(k, [])
        if not rows:
            continue
        cnt = collections.Counter(r[2] for r in rows)
        자주 = ', '.join('%s×%d' % (v[:26], c) for v, c in cnt.most_common(5))
        print(' %-18s %6s곳   자주 나온 값: %s' % (이름[k], format(len(rows), ','), 자주))
    print('-' * 62)
    파일별 = collections.Counter()
    for rows in 위반.values():
        for r in rows:
            파일별[r[0]] += 1
    print(' 위반이 많은 파일 10개')
    for f, c in 파일별.most_common(10):
        print('   %6s곳  %s' % (format(c, ','), f))
    if 자세히:
        print('-' * 62)
        for k in ['글꼴', '줄간격', '정렬-머리글', '숫자자릿수']:
            rows = 위반.get(k, [])[:자세히]
            if not rows:
                continue
            print(' [%s]' % 이름[k])
            for f, ln, v in rows:
                print('   %s:%d  %s' % (f, ln, v))
    return 총


if __name__ == '__main__':
    자세히 = 0
    if '--자세히' in sys.argv:
        i = sys.argv.index('--자세히')
        자세히 = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 15
    위반 = 검사(자세히)
    총 = 출력(위반, 자세히)
    print('-' * 62)
    if '--기준저장' in sys.argv:
        json.dump({'total': 총}, io.open(BASE, 'w', encoding='utf-8'))
        print(' 기준선 저장: %s곳' % format(총, ','))
        sys.exit(0)
    if os.path.exists(BASE):
        old = json.load(io.open(BASE, encoding='utf-8')).get('total', 0)
        if 총 > old:
            print(' ❌ 기준선 %s곳 → 지금 %s곳 (늘었습니다)' % (format(old, ','), format(총, ',')))
            sys.exit(1)
        print(' ✅ 기준선 %s곳 대비 %s곳 (늘지 않았습니다)' % (format(old, ','), format(총, ',')))
    else:
        print(' (기준선 없음 — --기준저장 으로 지금 상태를 기준선으로 삼을 수 있습니다)')
