# -*- coding: utf-8 -*-
"""화면 파일의 자바스크립트 문법 · CSS 괄호 검사.

★ 왜 있나 (2026-08-01 실사고)
  CSS 괄호를 자동으로 고치는 스크립트를 파일 **전체**에 돌렸다가, <style> 밖의
  자바스크립트 `})));` 까지 `}));` 로 줄여 **라이브 화면의 정책 붙이기/떼기가
  죽은 채로 배포**됐다. 문법 검사가 없어 테스트도 통과했다.

  자동 일괄수정은 앞으로도 돈다(scripts/design_sweep.py 계열). 그때마다
  같은 사고가 나지 않게, 문법 자체를 검사한다.
"""
import os
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: [2026-08-01] **전 화면**으로 넓혔다. 상품 가공 몇 개만 보던 사이,
#:   같은 종류의 깨짐이 다른 화면 8곳에 있었다(소싱처 로그인·재고 목록 3개·
#:   매트릭스 상세·가격 정책·모바일 스캔·옵션생성 삭제). 전부 자동 일괄수정이
#:   괄호를 하나 더 붙인 것이고, 라이브에서 그 화면 동작이 죽어 있었다.
def _watched():
    out = []
    for root, _, files in os.walk(os.path.join(_ROOT, 'webapp', 'templates')):
        for f in files:
            if f.endswith('.html'):
                out.append(os.path.relpath(os.path.join(root, f), _ROOT).replace(os.sep, '/'))
    return sorted(out)


WATCHED = _watched()


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _js_blocks(html):
    """<script> 안쪽만. Jinja 자리는 더미로 바꾼다 — 문법만 보면 된다.

    ★ `{% for %}` 로 배열·객체를 찍어내는 블록은 건너뛴다. Jinja 를 지우면
      `{a:0}{b:0}` 처럼 남아 **없는 문법 오류**를 만든다(2026-08-01 실측:
      inventory/barcode.html 의 라벨 규격표).
    """
    for b in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
        if re.search(r'\{%\s*for\b', b):
            continue
        js = re.sub(r'\{\{.*?\}\}', '0', b, flags=re.S)
        js = re.sub(r'\{%.*?%\}', '', js, flags=re.S)
        if js.strip():
            yield js


@pytest.mark.skipif(shutil.which('node') is None, reason='node 가 없어 문법 검사 불가')
@pytest.mark.parametrize('rel', WATCHED)
def test_자바스크립트_문법이_깨지지_않았다(rel):
    for i, js in enumerate(_js_blocks(_read(rel))):
        path = os.path.join(tempfile.gettempdir(), f'syntax_check_{os.getpid()}_{i}.js')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(js)
        try:
            r = subprocess.run(['node', '--check', path],
                               capture_output=True, timeout=30)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        assert r.returncode == 0, (
            f'{rel} 의 script[{i}] 문법이 깨졌습니다:\n'
            + r.stderr.decode('utf-8', 'replace'))


@pytest.mark.parametrize('rel', WATCHED)
def test_CSS_괄호가_맞는다(rel):
    """`var(--A, var(--B,#hex)}` 처럼 `)` 가 모자라면 닫히지 않은 괄호가 `}` 를
    삼켜 **뒤따르는 규칙까지** 무효가 된다 — 화면에서 색이 통째로 안 먹는다."""
    bad = []
    for block in re.findall(r'<style>(.*?)</style>', _read(rel), re.S):
        for n, line in enumerate(block.splitlines(), 1):
            if 'var(' in line and line.count('(') != line.count(')'):
                bad.append(f'  {n}행: {line.strip()[:100]}')
    assert not bad, f'{rel} 의 CSS 괄호가 안 맞습니다:\n' + '\n'.join(bad)
