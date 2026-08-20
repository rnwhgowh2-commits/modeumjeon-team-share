# -*- coding: utf-8 -*-
"""화면 디자인은 화이트 하나뿐 — 고르는 기능이 되살아나지 못하게 못 박는다.

[2026-08-02 사장님 확정] 기존·검정A·검정B 와 오른쪽 위 고르는 단추를 지웠다.
    예전 이 파일은 「네 타입이 있고 기존이 안전망이다」를 지키는 검사였다.
    이제 지킬 것이 정반대다 — **하나뿐이어야 하고, 고르는 통로가 없어야 한다.**

    ★ 왜 검사로 남기나 — 지운 것은 조용히 되살아난다. 누가 타입을 다시 추가하거나
      드롭버튼을 되살리면 여기서 걸린다.
    ★ 가장 무서운 실수는 **표시(ds ds-light)가 빈 값이 되는 것**이다. 그러면 지금까지
      고친 것(배지 색·팝업·정렬·달력 그림…)이 통째로 잠들어 옛 색으로 돌아간다.
      에러도 안 나고 화면만 조용히 달라지므로, 여기서 못 박아 둔다.
"""
import io
import os

import pytest

from webapp.design_mode import MODES, DEFAULT_MODE, normalize, body_class

_시스템 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')


def test_타입은_화이트_하나뿐이다():
    assert list(MODES.keys()) == ['light']
    assert MODES['light'][0] == '화이트 타입'


def test_기본값은_화이트다():
    assert DEFAULT_MODE == 'light'


@pytest.mark.parametrize('넣은값', [None, '', 'current', 'mono', 'layer', 'light',
                                    '아무거나', 123, '  ', 'MONO'])
def test_무엇이_들어와도_화이트다(넣은값):
    """예전 사람들 계정에 'mono' 같은 옛 값이 남아 있어도 화이트로 본다."""
    assert normalize(넣은값) == 'light'


@pytest.mark.parametrize('넣은값', [None, 'current', 'mono', 'layer', 'light'])
def test_화면_표시는_늘_같다(넣은값):
    assert body_class(넣은값) == 'ds ds-light'


def test_표시가_비면_안_된다():
    assert body_class().strip() != ''
    assert 'ds' in body_class().split()
    assert 'ds-light' in body_class().split()


def test_어두운_표시는_다시_생기면_안_된다():
    붙는것 = body_class()
    for 옛것 in ('ds-dark', 'ds-mono', 'ds-layer'):
        assert 옛것 not in 붙는것, f'{옛것} 이 되살아났다'


def test_고르는_단추가_화면에_없다():
    부품 = os.path.join(_시스템, 'webapp', 'templates', 'partials', 'design_mode_menu.html')
    assert not os.path.exists(부품), '고르는 단추 부품이 되살아났다'
    for 이름 in ('base.html', os.path.join('auth', '_base_auth.html')):
        본문 = io.open(os.path.join(_시스템, 'webapp', 'templates', 이름),
                       encoding='utf-8').read()
        assert 'design_mode_menu' not in 본문, f'{이름} 에 고르는 단추가 다시 들어왔다'


def test_타입_저장_통로가_없다():
    os.environ.setdefault('ENVIRONMENT', 'team-share-dev')
    from app import create_app
    길들 = {str(r.rule) for r in create_app().url_map.iter_rules()}
    assert '/auth/design-mode' not in 길들, '타입 저장 통로가 아직 있다'


def test_화면_바깥상자에_표시가_붙는다():
    본문 = io.open(os.path.join(_시스템, 'webapp', 'templates', 'base.html'),
                   encoding='utf-8').read()
    assert 본문.count('design_body_class') >= 2, '<html> 과 앱 상자 두 곳에 붙어야 한다'


def test_사용자_칸은_그대로_둔다():
    """users.design_mode 칸은 DB 에 남겨 둔다 — 안 읽으면 아무 일도 안 일어난다.

    표를 건드리는 것이 더 위험하므로 일부러 남긴다(사장님 확정 2026-08-02).
    """
    from webapp.auth.models import User
    assert 'design_mode' in User.__table__.c, '칸을 지우면 옛 자료 읽기가 깨진다'
