# -*- coding: utf-8 -*-
"""문단·카드 본문 줄 간격을 글자 크기별 규칙값으로 (사장님 확정 「A안」).

무엇을 하나
    규칙 밖 줄 간격 중 **문단·카드 본문(1.45 이상)만** 골라, 그 규칙에 적힌
    글자 크기에 맞는 값으로 바꾼다.
        11~12px → 1.33 · 14px → 1.57 · 17px → 1.59
        19~24px → 1.29 · 32px → 1.22 · 48px → 1.18
        글자 크기가 안 적혀 있으면 → 1.57 (본문 기본)

🔴 손대지 않는 것 (라이브 실측으로 갈라 둔 부류)
    · 1.25 이하 = 아이콘·배지·닫기 단추 109곳.
      줄 사이를 벌리면 **글자가 칸 가운데서 벗어난다.**
    · 1.26~1.44 = 제목·짧은 줄 34곳. 규칙값에 이미 가깝다.
    · px 로 준 값 18곳. 비율로 바꾸는 건 성격이 달라 따로 본다.
    · 표 안쪽은 이미 snap_table_spacing.py 가 처리했다.

🔴 .html 은 <style>…</style> **안에서만** 고친다
    (예전에 파일 전체에 치환을 돌려 자바스크립트를 죽인 채 배포한 적이 있다.)

쓰는 법
    python 프로그램/_시스템/scripts/snap_paragraph_lh.py         # 미리보기
    python 프로그램/_시스템/scripts/snap_paragraph_lh.py --적용   # 실제로 고침
"""
import io, os, re, sys, collections

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
TPL = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'templates')
CSS = os.path.join(ROOT, '프로그램', '_시스템', 'webapp', 'static')

문단하한 = 1.45        # 이 아래는 아이콘·제목 — 손대지 않는다
이미규칙 = {1.18, 1.22, 1.29, 1.33, 1.35, 1.5, 1.53, 1.57, 1.59, 1.6}

RE_규칙 = re.compile(r'([^{}]+)\{([^{}]*)\}')
RE_STYLE = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.I | re.S)
RE_LH = re.compile(r'\b(line-height)\s*:\s*([^;{}]+)')
RE_FS = re.compile(r'\bfont-size\s*:\s*([\d.]+)px')

바뀜 = collections.Counter()
미룸 = collections.Counter()   # 이번에 일부러 안 고친 것
기록 = []
작은글자포함 = False


def 규칙값(크기):
    """글자 크기에 맞는 줄 간격 (tokens.css 의 --lh-* 그대로)."""
    if 크기 is None:
        return 1.57                 # 본문 기본
    if 크기 <= 12.5:
        return 1.33
    if 크기 <= 15.5:
        return 1.57
    if 크기 <= 20:
        return 1.59
    if 크기 <= 27:
        return 1.29
    if 크기 <= 40:
        return 1.22
    return 1.18


def CSS덩어리(css, 파일):
    def 규칙하나(m):
        선택자, 본문 = m.group(1), m.group(2)
        if 'line-height' not in 본문:
            return m.group(0)
        fs = RE_FS.search(본문)
        크기 = float(fs.group(1)) if fs else None
        자리 = '%s  {%s}' % (파일, 선택자.strip().splitlines()[-1].strip()[:44])

        def 하나(mm):
            raw = mm.group(2).strip()
            low = raw.lower()
            if low.startswith('var(') or low in ('normal', 'inherit', 'unset', 'initial'):
                return mm.group(0)
            if not re.match(r'^\d+(\.\d+)?$', low):     # px·em 은 여기서 안 건드림
                return mm.group(0)
            v = float(low)
            if v < 문단하한:                             # 아이콘·제목 — 손대지 않는다
                return mm.group(0)
            if v in 이미규칙:
                return mm.group(0)
            새 = 규칙값(크기)
            if abs(새 - v) < 0.005:
                return mm.group(0)
            if 새 == 1.33 and not 작은글자포함:
                미룸['작은 글씨(11~12px) %g → 1.33' % v] += 1
                return mm.group(0)
            바뀜['%g → %g (글자 %s)' % (v, 새, ('%gpx' % 크기) if 크기 else '안 적힘')] += 1
            기록.append((파일, 자리, v, 새))
            return '%s:%g' % (mm.group(1), 새)

        return '%s{%s}' % (선택자, RE_LH.sub(하나, 본문))

    return RE_규칙.sub(규칙하나, css)


def 파일하나(path, 적용):
    rel = os.path.relpath(path, ROOT).replace('\\', '/')
    txt = io.open(path, encoding='utf-8').read()
    원본 = txt
    if path.endswith('.css'):
        txt = CSS덩어리(txt, rel)
    else:
        txt = RE_STYLE.sub(lambda m: m.group(1) + CSS덩어리(m.group(2), rel) + m.group(3), txt)
    if txt != 원본:
        if 적용:
            io.open(path, 'w', encoding='utf-8').write(txt)
        return True
    return False


def main():
    적용 = '--적용' in sys.argv
    global 작은글자포함
    # 🔴 사장님께 보여드린 시안은 **17px 문단**(1.7→1.59, 6px 줄어듦)이었다.
    #   11~12px 작은 글씨를 1.7→1.33 으로 조이는 건 **성격이 다른 변화**(22% 조임)라
    #   기본으로는 빼 둔다. 따로 보시고 정하실 일이다.
    작은글자포함 = '--작은글자포함' in sys.argv
    파일수 = 0
    for base, dirs, names in os.walk(TPL):
        dirs[:] = [d for d in dirs if not d.startswith('_backup')]
        for n in sorted(names):
            if n.endswith('.html') and 파일하나(os.path.join(base, n), 적용):
                파일수 += 1
    for n in sorted(os.listdir(CSS)):
        if n.endswith('.css') and n != 'tokens.css' and 파일하나(os.path.join(CSS, n), 적용):
            파일수 += 1

    print('=' * 62)
    print(' 문단·카드 줄 간격 규칙값 맞추기 %s' % ('(실제 적용)' if 적용 else '(미리보기 — 안 고침)'))
    print('=' * 62)
    print(' 바뀐 곳 : %s곳 / 파일 %d개' % (format(sum(바뀜.values()), ','), 파일수))
    print('-' * 62)
    for k, v in 바뀜.most_common(16):
        print('   %-30s %4d곳' % (k, v))
    print('-' * 62)
    파일별 = collections.Counter(r[0] for r in 기록)
    print(' 많이 바뀐 파일 8개')
    for f, c in 파일별.most_common(8):
        print('   %4d곳  %s' % (c, f.replace('프로그램/_시스템/webapp/', '')))
    if 미룸:
        print('-' * 62)
        print(' 이번에 일부러 **안** 고친 것 — 시안에서 안 보여드린 부류')
        print('   합계 %d곳 (11~12px 작은 글씨를 1.33 으로 조이는 건 22%% 조임이라 성격이 다르다)'
              % sum(미룸.values()))
        for k, v in 미룸.most_common(6):
            print('   %-34s %4d곳' % (k, v))
        print('   → 이것도 하려면: --작은글자포함')
    if not 적용:
        print('-' * 62)
        print(' 실제로 고치려면: --적용')


if __name__ == '__main__':
    main()
