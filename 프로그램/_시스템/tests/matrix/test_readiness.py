# -*- coding: utf-8 -*-
"""옵션함 위상 판정 — 「상품 만들 준비 됐나」.

이 파일이 지키는 것 네 가지:
  ① 🔴 **축이 0개인데 「준비 완료」가 되면 안 된다**(공허참 함정).
     「모든 축에 값이 있나」만 물으면 축이 하나도 없을 때 참이 되어,
     빈 옵션함에 초록불이 뜨고 옵션 0개짜리 상품이 만들어진다.
  ② 🔴 **줄이 몇 개든 쿼리 수가 같아야 한다**(N+1 방지).
     줄마다 한 번씩 물으면 옵션함 200개 화면이 200쿼리가 된다.
     이 계약이 이 모듈의 존재 이유라, 시험으로 못 박아 둔다.
  ③ 🔴 **「값이 빈 축」 규칙은 축 요약(`axis_summary`) 한 벌뿐이다.**
     두 벌이던 시절 공백만 든 축(`["", "  "]`)을 두고 축 요약은 「값 없음」,
     위상 판정은 「값 있음」이라 해서 배지가 초록불로 튀었다(2026-08-14 검수).
  ④ 🔴 **파생 매트릭스로 만든 상품도 「사용됨」이다.**
     파생은 `model_code` 가 비어 있어서, 원본 코드로 접지 않으면 상품을 이미
     만든 옵션함에 초록불이 켜지고 같은 상품을 두 번 만들게 된다.
"""
import json

import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models  # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# ═══════════════════════════════════════════════════════════════════════════
#  phase_of — 네 조건을 하나씩 빼 본다
# ═══════════════════════════════════════════════════════════════════════════

def _다_채운_입력(**over):
    """네 조건을 전부 만족하는 입력. 시험마다 여기서 하나씩만 뺀다."""
    kw = dict(options=4, axes=2, empty_axes=0, urls=1,
              mapped_full=True, used=False)
    kw.update(over)
    return kw


def test_네_조건_다_채우면_준비완료():
    from lemouton.matrix.readiness import PHASE_READY, phase_of
    위상, 사유 = phase_of(**_다_채운_입력())
    assert 위상 == PHASE_READY
    assert 사유 == [], f'준비 완료인데 사유가 남았다: {사유}'


def test_옵션이_없으면_미완료():
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(options=0))
    assert 위상 == PHASE_DRAFT
    assert '옵션 없음' in 사유


def test_축이_0개면_준비완료가_되면_안_된다():
    """🔴 공허참 함정 — 이 시험이 이 파일의 첫 번째 이유다.

    축이 없으면 「값이 빈 축」도 0개라, 「빈 축이 없다」는 조건만 보면 통과해 버린다.
    그러면 아무것도 안 짠 옵션함이 초록불로 뜬다.
    """
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(axes=0, empty_axes=0))
    assert 위상 == PHASE_DRAFT, '축이 하나도 없는데 준비 완료라고 한다'
    assert '축 없음' in 사유


def test_값이_빈_축이_있으면_미완료():
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(axes=2, empty_axes=1))
    assert 위상 == PHASE_DRAFT
    assert '값이 빈 축 1개' in 사유, f'몇 개가 비었는지 안 알려 준다: {사유}'


def test_소싱처_URL_이_없으면_미완료():
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(urls=0))
    assert 위상 == PHASE_DRAFT
    assert '소싱처 URL 없음' in 사유


def test_맵핑이_덜_됐으면_미완료():
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(mapped_full=False))
    assert 위상 == PHASE_DRAFT
    assert '소싱처 맵핑 미완료' in 사유


def test_이미_상품을_만들었으면_사용됨이_이긴다():
    """준비가 덜 됐든 다 됐든, 이미 쓴 것은 「사용됨」이다."""
    from lemouton.matrix.readiness import PHASE_USED, phase_of
    assert phase_of(**_다_채운_입력(used=True))[0] == PHASE_USED
    # 덜 갖춰진 채로 만든 옛 옵션함도 사용됨이다(그게 사실이니까)
    위상, 사유 = phase_of(**_다_채운_입력(used=True, axes=0, empty_axes=0))
    assert 위상 == PHASE_USED
    assert '축 없음' in 사유, '뒷정리 거리를 화면이 못 보여 준다'


# ── 🔴 「모른다」와 「아니다」 가르기 ────────────────────────────────────────

def test_URL_이_0개면_맵핑_사유가_중복되지_않는다():
    """🔴 URL 이 0개면 이을 대상 자체가 없다 → mapped_full 은 None(모름).

    이때 「소싱처 URL 없음」과 「소싱처 맵핑 …」이 같이 뜨면 손볼 곳이 두 군데인 줄 안다.
    실제로 손볼 곳은 URL 붙이기 하나뿐이다.
    """
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(urls=0, mapped_full=None))
    assert 위상 == PHASE_DRAFT
    assert 사유 == ['소싱처 URL 없음'], f'사유가 중복되거나 늘었다: {사유}'


def test_URL_은_있는데_맵핑을_모르면_확인불가로_남는다():
    """🔴 모르는 것을 「안 됐다」로 단정하지 않는다. 다만 모르는 채로 초록불도 아니다."""
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_of
    위상, 사유 = phase_of(**_다_채운_입력(urls=1, mapped_full=None))
    assert 위상 == PHASE_DRAFT, '모르는데 준비 완료라고 한다'
    assert '소싱처 맵핑 확인 불가' in 사유
    assert '소싱처 맵핑 미완료' not in 사유, '모름을 「아님」으로 뭉갰다'


# ═══════════════════════════════════════════════════════════════════════════
#  라벨·색 — 한 곳에서만 온다
# ═══════════════════════════════════════════════════════════════════════════

def test_세_위상_모두_이름과_색이_있다():
    from lemouton.matrix.readiness import PHASE_CLS, PHASE_LABEL, PHASES
    assert len(PHASES) == 3
    for p in PHASES:
        assert p in PHASE_LABEL and p in PHASE_CLS
    assert len(set(PHASE_CLS.values())) == len(PHASES), '두 위상이 같은 색을 쓴다'


def test_세_위상_모두_아이콘이_있고_이름이_실제_목록에_있다():
    """🔴 이름이 틀리면 화면에서 빈칸으로 조용히 사라진다 — 실제 Phosphor Light 목록과 대조."""
    import os
    import urllib.request
    from lemouton.matrix.readiness import PHASE_ICON, PHASES

    assert len(PHASE_ICON) == len(PHASES)
    for p in PHASES:
        assert p in PHASE_ICON and PHASE_ICON[p], f'{p} 에 아이콘 이름이 없다'

    url = 'https://unpkg.com/@phosphor-icons/web@2.1.1/src/light/style.css'
    try:
        css = urllib.request.urlopen(url, timeout=5).read().decode('utf-8')
    except Exception:
        pytest.skip('오프라인 환경 — 실제 아이콘 목록과 대조 못 함(CI/네트워크 있는 곳에서 다시 확인)')
    for p, name in PHASE_ICON.items():
        assert f'.ph-light.ph-{name}:before' in css, (
            f'{p} 아이콘 "{name}" 이 Phosphor Light 목록에 없다 — 화면에서 빈칸이 된다')


def test_판매상품_상태_이름과_겹치지_않는다():
    """🔴 옵션함과 판매 상품은 다른 것이다 — 이름이 겹치면 화면이 거짓말을 한다."""
    from lemouton.matrix.readiness import PHASE_LABEL
    from webapp.routes.bundles_tower import STAGE_LABEL, STAGE_LABEL_MATRIX
    겹침 = set(PHASE_LABEL.values()) & (set(STAGE_LABEL.values())
                                       | set(STAGE_LABEL_MATRIX.values()))
    assert not 겹침, f'판매 상품 상태와 같은 말을 쓴다: {겹침}'


def test_색_이름_체계는_디자인_기준_한_벌에_있는_것만_쓴다():
    """🔴 [2026-08-19 디자인 통일] 색 이름은 `ds.css` 의 `.ds-st--*` 다섯 가지 중에서만
    고른다 — 새 이름을 만들면 CSS 가 없어 화면에서 조용히 기본색(검정)으로 빠진다.

    예전엔 `bundles_tower.STAGE_CLS`(wait/mid/sale)와 같은 이름을 쓰는지를 봤다.
    이 화면이 새 기준(딱지 없이 아이콘+색 글자)을 먼저 입으면서 그 대조는 끝났다 —
    옛 이름 체계와 다른 것이 이번엔 **의도**다. 대신 새 단일 진실 원천과 대조한다.
    """
    from lemouton.matrix.readiness import PHASE_CLS
    허용 = {'ok', 'idle', 'no', 'unk', 'est'}   # ds.css 의 .ds-st--* 다섯 가지
    낯선이름 = set(PHASE_CLS.values()) - 허용
    assert not 낯선이름, f'ds.css 에 없는 색 이름을 쓴다(화면에서 빈 색으로 빠진다): {낯선이름}'


# ═══════════════════════════════════════════════════════════════════════════
#  phase_batch — 실제 줄을 읽고, 쿼리는 고정 2개
# ═══════════════════════════════════════════════════════════════════════════

def _옵션함(session, code, 축들):
    """옵션함 모델 + 축(단계) 줄을 심는다. 축들 = [(축이름, [값...] 또는 생 JSON), ...]

    생 JSON 문자열도 받는다 — 깨진 JSON·공백만 든 값처럼 **저장된 그대로**를
    심어야 하는 시험이 있기 때문이다(`json.dumps` 를 거치면 그 모양이 사라진다).
    """
    from lemouton.sourcing.models import BundleOptionStep, Model
    session.add(Model(model_code=code, model_name_raw=code, brand='르무통',
                      is_option_box=True))
    for i, (이름, 값들) in enumerate(축들, start=1):
        raw = 값들 if isinstance(값들, str) else json.dumps(값들, ensure_ascii=False)
        session.add(BundleOptionStep(model_code=code, step_no=i, axis_name=이름,
                                     values_json=raw))


def _상품으로_썼다(session, 옵션함코드, 상품코드):
    """이 옵션함의 **원본** 매트릭스로 상품을 만든 기록을 남긴다."""
    from lemouton.matrix.models import KIND_ORIGIN, BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import Model
    mo = MatrixOption(name=옵션함코드, kind=KIND_ORIGIN, model_code=옵션함코드)
    session.add(mo)
    session.flush()
    session.add(Model(model_code=상품코드, model_name_raw=상품코드, brand='르무통'))
    session.add(BundleMatrixLink(model_code=상품코드, matrix_option_id=mo.id,
                                 copied_count=2))


def _파생으로_상품을_썼다(session, 옵션함코드, 상품코드):
    """옵션함 → 원본 → **파생** → 상품. 실제 경로 그대로 심는다.

    🔴 파생은 `model_code` 가 비어 있고 `origin_id` 만 있다
       (`matrix/service.py` 의 `create_derived`). 원본만 심는 도우미로는 이 경로가
       영영 안 잡혀서, 결함이 있어도 시험이 전부 초록불이었다.
    """
    from lemouton.matrix.models import (
        KIND_DERIVED, KIND_ORIGIN, BundleMatrixLink, MatrixOption,
    )
    from lemouton.sourcing.models import Model
    원본 = MatrixOption(name=옵션함코드, kind=KIND_ORIGIN, model_code=옵션함코드)
    session.add(원본)
    session.flush()
    파생 = MatrixOption(name=f'{옵션함코드} 일부', kind=KIND_DERIVED, origin_id=원본.id)
    session.add(파생)
    session.flush()
    # 🔴 파생에 model_code 가 들어가 버리면 이 시험은 아무것도 안 보게 된다.
    assert 파생.model_code is None, '파생에 코드가 박혔다 — 시험이 헛돈다'
    session.add(Model(model_code=상품코드, model_name_raw=상품코드, brand='르무통'))
    session.add(BundleMatrixLink(model_code=상품코드, matrix_option_id=파생.id,
                                 copied_count=2))


def _원본만_있다(session, 옵션함코드):
    """상품은 아직 안 만들고 **원본 매트릭스만** 붙어 있는 옵션함.

    실제로 옵션함은 만들어질 때 원본이 같이 생긴다(`service.ensure_origin`).
    이 줄이 있어야 「조인이 헐거워 엉뚱한 옵션함까지 사용됨으로 번지는」 사고를
    시험이 잡을 수 있다 — 매트릭스가 아예 없으면 무슨 조인을 써도 안 걸린다.
    """
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    session.add(MatrixOption(name=옵션함코드, kind=KIND_ORIGIN,
                             model_code=옵션함코드))
    session.flush()


def _위상(session, codes, **kw):
    """축 요약을 받아 `phase_batch` 에 그대로 넘긴다 — 화면이 할 일과 같은 순서다.

    🔴 축을 읽는 곳은 `axis_summary.axis_batch` 하나뿐이다. 시험도 같은 길로
       불러야, 「위상 판정이 축을 몰래 다시 읽는」 회귀가 여기서 걸린다.
    """
    from lemouton.matrix.readiness import phase_batch
    from lemouton.sourcing.axis_summary import axis_batch
    return phase_batch(session, codes, axes=axis_batch(session, codes), **kw)


@pytest.fixture
def 심은_세션(session):
    _옵션함(session, '옵션함_준비완료', [('색상', ['블랙', '화이트']), ('사이즈', ['250'])])
    _원본만_있다(session, '옵션함_준비완료')     # 매트릭스는 있고 상품은 아직 없다
    _옵션함(session, '옵션함_빈축', [('색상', ['블랙']), ('사이즈', [])])
    _옵션함(session, '옵션함_축없음', [])
    _옵션함(session, '옵션함_사용됨', [('색상', ['블랙'])])
    _상품으로_썼다(session, '옵션함_사용됨', '르무통_메이트')
    _옵션함(session, '옵션함_파생사용됨', [('색상', ['블랙'])])
    _파생으로_상품을_썼다(session, '옵션함_파생사용됨', '르무통_스위트')
    session.commit()
    return session


def test_심은_것이_실제로_DB_에_있다(심은_세션):
    """🔴 시험용 DB 에 대상이 없으면 뒤 시험들은 아무것도 안 본다 — 먼저 확인한다."""
    from lemouton.matrix.models import KIND_DERIVED, BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import BundleOptionStep
    assert 심은_세션.query(BundleOptionStep).filter_by(
        model_code='옵션함_준비완료').count() == 2
    assert 심은_세션.query(BundleOptionStep).filter_by(
        model_code='옵션함_축없음').count() == 0
    assert 심은_세션.query(BundleMatrixLink).count() == 2
    # 파생이 진짜 파생 모양(코드 없음 + 원본 가리킴)으로 심겼는지 — 아니면 ④가 헛돈다.
    파생 = 심은_세션.query(MatrixOption).filter_by(kind=KIND_DERIVED).one()
    assert 파생.model_code is None and 파생.origin_id


def test_phase_batch_가_다섯_옵션함을_제대로_가른다(심은_세션):
    from lemouton.matrix.readiness import PHASE_DRAFT, PHASE_READY, PHASE_USED
    코드 = ['옵션함_준비완료', '옵션함_빈축', '옵션함_축없음', '옵션함_사용됨',
          '옵션함_파생사용됨']
    결과 = _위상(
        심은_세션, 코드,
        options={c: 4 for c in 코드},
        urls={c: 1 for c in 코드},
        mapped={c: True for c in 코드},
    )
    assert set(결과) == set(코드), '물어본 코드가 빠졌다 — 화면에 구멍이 생긴다'
    assert 결과['옵션함_준비완료']['phase'] == PHASE_READY
    assert 결과['옵션함_준비완료']['missing'] == []
    assert 결과['옵션함_빈축']['phase'] == PHASE_DRAFT
    assert '값이 빈 축 1개' in 결과['옵션함_빈축']['missing']
    assert 결과['옵션함_축없음']['phase'] == PHASE_DRAFT
    assert '축 없음' in 결과['옵션함_축없음']['missing']
    assert 결과['옵션함_사용됨']['phase'] == PHASE_USED
    assert 결과['옵션함_파생사용됨']['phase'] == PHASE_USED


def test_라벨과_색도_같이_돌려준다(심은_세션):
    """화면이 글자를 또 적지 않아도 되게 — 적으면 두 벌이 되어 갈린다."""
    from lemouton.matrix.readiness import PHASE_CLS, PHASE_LABEL
    한줄 = _위상(심은_세션, ['옵션함_준비완료'],
               options={'옵션함_준비완료': 2},
               urls={'옵션함_준비완료': 1},
               mapped={'옵션함_준비완료': True})['옵션함_준비완료']
    assert 한줄['label'] == PHASE_LABEL[한줄['phase']]
    assert 한줄['cls'] == PHASE_CLS[한줄['phase']]


def test_안_넘어온_맵핑은_모름이지_아님이_아니다(심은_세션):
    """🔴 기본값을 False 로 두면 안 넘어온 것을 「안 이어졌다」로 단정하게 된다."""
    사유 = _위상(심은_세션, ['옵션함_준비완료'],
               options={'옵션함_준비완료': 2},
               urls={'옵션함_준비완료': 1},
               mapped={})['옵션함_준비완료']['missing']
    assert '소싱처 맵핑 확인 불가' in 사유
    assert '소싱처 맵핑 미완료' not in 사유


def test_빈_목록이면_쿼리도_안_돈다(session):
    from lemouton.matrix.readiness import phase_batch
    assert phase_batch(session, [], options={}, urls={}, mapped={}, axes={}) == {}
    assert phase_batch(session, [None, ''],
                       options={}, urls={}, mapped={}, axes={}) == {}


# ═══════════════════════════════════════════════════════════════════════════
#  ③ 「값이 빈 축」 규칙은 축 요약 한 벌뿐이다
# ═══════════════════════════════════════════════════════════════════════════

def test_값이_빈_축_세는_규칙이_축_요약과_한_벌이다(session):
    """🔴 예전엔 두 모듈이 같은 표를 각자 읽어 **다른 숫자**를 냈다(2026-08-14 검수).

    공백만 든 값·None 만 든 값·깨진 JSON — 축 요약은 「값 없음」으로 세는데
    위상 판정은 「값 있음」으로 세어, 목록 글자는 「값 없음」인데 배지는
    **초록불(준비 완료)** 이었다. 사장님이 그 초록불을 믿고 상품을 만들면
    옵션이 텅 빈 상품이 나온다.
    """
    from lemouton.matrix.readiness import PHASE_DRAFT
    from lemouton.sourcing.axis_summary import axis_batch
    _옵션함(session, '옵션함_공백값', [
        ('색상', ['블랙']),
        ('사이즈', '["", "  "]'),        # 공백만 — 사람 눈엔 빈 축이다
        ('재질', '[null]'),              # None 만
        ('패턴', '{이건 JSON 이 아니다'),  # 깨진 JSON
    ])
    session.commit()

    요약 = axis_batch(session, ['옵션함_공백값'])['옵션함_공백값']
    결과 = _위상(session, ['옵션함_공백값'], options={'옵션함_공백값': 4},
              urls={'옵션함_공백값': 1}, mapped={'옵션함_공백값': True})['옵션함_공백값']

    assert 요약['empty_axes'] == 3, '축 요약 쪽이 먼저 바뀌었다 — 기준이 흔들린다'
    assert 결과['phase'] == PHASE_DRAFT, '값이 빈 축이 셋인데 초록불이 켜졌다'
    assert f"값이 빈 축 {요약['empty_axes']}개" in 결과['missing'], (
        f"두 모듈이 다른 숫자를 낸다: 축 요약 {요약['empty_axes']}개 / "
        f"위상 판정 {결과['missing']}")


def test_축_요약_대신_숫자를_넘기면_조용히_넘어가지_않는다(session):
    """🔴 예전 모양(축 개수 숫자)을 넘기면 축 0개로 읽혀 전부 「축 없음」이 된다.

    에러가 안 나면 화면만 조용히 틀리고, 사장님은 다 채운 옵션함을 계속 들여다본다.
    """
    from lemouton.matrix.readiness import phase_batch
    _옵션함(session, '옵션함_모양틀림', [('색상', ['블랙'])])
    session.commit()
    with pytest.raises(TypeError) as e:
        phase_batch(session, ['옵션함_모양틀림'], options={'옵션함_모양틀림': 1},
                    urls={'옵션함_모양틀림': 1}, mapped={'옵션함_모양틀림': True},
                    axes={'옵션함_모양틀림': 1})
    assert 'axis_batch' in str(e.value), '무엇을 넘겨야 하는지 안 알려 준다'


def test_축_요약에_없는_코드는_미완료쪽으로_떨어진다(session):
    """모르는 채로 초록불이 켜지면 안 된다 — 「미완료」가 안전한 쪽이다."""
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_batch
    결과 = phase_batch(session, ['옵션함_요약없음'], options={'옵션함_요약없음': 3},
                     urls={'옵션함_요약없음': 1}, mapped={'옵션함_요약없음': True},
                     axes={})['옵션함_요약없음']
    assert 결과['phase'] == PHASE_DRAFT
    assert '축 없음' in 결과['missing']


# ═══════════════════════════════════════════════════════════════════════════
#  ④ 파생 매트릭스 경유 — used 를 놓치면 같은 상품을 두 번 만든다
# ═══════════════════════════════════════════════════════════════════════════

def test_파생으로_만든_상품도_사용됨이다(심은_세션):
    """🔴 파생은 `model_code` 가 비어 있다 — 원본 코드로 접지 않으면 안 걸린다.

    안 고치면: 이미 상품을 만든 옵션함에 「상품생성 준비 완료」 초록불이 켜져
    사장님이 같은 옵션함으로 상품을 **또** 만드시고, 마켓에 같은 상품이 두 번 올라간다.
    """
    from lemouton.matrix.readiness import PHASE_USED
    결과 = _위상(심은_세션, ['옵션함_파생사용됨'],
               options={'옵션함_파생사용됨': 1},
               urls={'옵션함_파생사용됨': 1},
               mapped={'옵션함_파생사용됨': True})['옵션함_파생사용됨']
    assert 결과['phase'] == PHASE_USED, (
        '파생으로 상품을 만들었는데 초록불이 켜진다 — 같은 상품을 두 번 만들게 된다')


def test_원본이든_파생이든_같은_판정이_나온다(심은_세션):
    """같은 행위(상품 만들기)가 어디서 했느냐로 갈리면 그건 결정이 아니라 사고다."""
    결과 = _위상(심은_세션, ['옵션함_사용됨', '옵션함_파생사용됨'],
               options={'옵션함_사용됨': 1, '옵션함_파생사용됨': 1},
               urls={'옵션함_사용됨': 1, '옵션함_파생사용됨': 1},
               mapped={'옵션함_사용됨': True, '옵션함_파생사용됨': True})
    assert 결과['옵션함_사용됨']['phase'] == 결과['옵션함_파생사용됨']['phase'], (
        '원본에서 만들면 사용됨, 파생에서 만들면 준비 완료 — 조인이 흘린 것이다')


def test_상품을_안_만든_옵션함까지_사용됨으로_번지지_않는다(심은_세션):
    """🔴 원본 코드로 접는 조인이 헐거우면 **엉뚱한 옵션함**까지 사용됨이 된다.

    반대 방향 사고다 — 아직 안 쓴 옵션함이 「이미 썼다」가 되면 사장님이
    만들어야 할 상품을 안 만드신다.

    「옵션함_준비완료」는 **원본 매트릭스까지 붙어 있고 상품만 없는** 줄이다.
    매트릭스가 아예 없는 줄로 재면 무슨 조인을 써도 안 걸려 시험이 헛돈다.
    """
    from lemouton.matrix.models import MatrixOption
    from lemouton.matrix.readiness import PHASE_READY, PHASE_USED
    assert 심은_세션.query(MatrixOption).filter_by(
        model_code='옵션함_준비완료').count() == 1, '원본이 안 심겼다 — 시험이 헛돈다'
    결과 = _위상(심은_세션, ['옵션함_준비완료', '옵션함_빈축'],
               options={'옵션함_준비완료': 4, '옵션함_빈축': 4},
               urls={'옵션함_준비완료': 1, '옵션함_빈축': 1},
               mapped={'옵션함_준비완료': True, '옵션함_빈축': True})
    assert all(v['phase'] != PHASE_USED for v in 결과.values())
    assert 결과['옵션함_준비완료']['phase'] == PHASE_READY


# ── 🔴 N+1 방지 계약 ────────────────────────────────────────────────────────

def _쿼리_수를_세며(session, fn):
    """fn() 을 돌리는 동안 실제로 나간 SQL 개수를 센다."""
    from sqlalchemy import event
    통 = {'n': 0}

    def _count(*a, **k):
        통['n'] += 1

    engine = session.get_bind()
    event.listen(engine, 'before_cursor_execute', _count)
    try:
        fn()
    finally:
        event.remove(engine, 'before_cursor_execute', _count)
    return 통['n']


def test_줄이_3개든_30개든_쿼리_수가_같다(session):
    """🔴 이 모듈의 핵심 계약 — 줄마다 묻기 시작하면 화면이 눈에 띄게 느려진다.

    줄 수를 열 배로 늘려도 쿼리가 안 늘어야 한다. 늘면 N+1 이 들어온 것이다.

    🔴 예산이 2 → **1** 로 줄었다(2026-08-14). 축 조회를 `axis_summary` 로 옮겼기
       때문이지 사라진 게 아니다 — 그래서 아래에서 **둘을 합친 값(2)** 도 같이 못
       박는다. 합계를 안 재면 「readiness 는 1개」라고 말하면서 축 쪽이 줄마다
       도는 것을 못 본다.
    """
    from lemouton.matrix.readiness import phase_batch
    from lemouton.sourcing.axis_summary import axis_batch

    코드들 = [f'옵션함_{i:02d}' for i in range(30)]
    for c in 코드들:
        _옵션함(session, c, [('색상', ['블랙', '화이트']), ('사이즈', ['250'])])
    session.commit()

    def 돌리기(codes):
        # 축 요약은 미리 받아 둔다 — 여기서 세는 것은 위상 판정의 쿼리뿐이다.
        축 = axis_batch(session, codes)
        return lambda: phase_batch(session, codes,
                                   options={c: 6 for c in codes},
                                   urls={c: 1 for c in codes},
                                   mapped={c: True for c in codes},
                                   axes=축)

    적게 = _쿼리_수를_세며(session, 돌리기(코드들[:3]))
    많이 = _쿼리_수를_세며(session, 돌리기(코드들))
    assert 적게 == 많이 == 1, f'쿼리가 줄 수를 따라 늘었다 (3줄 {적게} · 30줄 {많이})'

    # 축 요약까지 합쳐서도 줄 수와 무관해야 한다 — 화면이 실제로 치르는 값이다.
    합계 = _쿼리_수를_세며(session, lambda: _위상(
        session, 코드들, options={c: 6 for c in 코드들},
        urls={c: 1 for c in 코드들}, mapped={c: True for c in 코드들}))
    assert 합계 == 2, f'축 요약 1 + 위상 판정 1 이어야 한다 (실제 {합계})'

    # 🔴 시험이 헛돌지 않았는지 — 30줄이 실제로 판정됐는지 같이 확인한다.
    from lemouton.matrix.readiness import PHASE_READY
    결과 = _위상(session, 코드들,
              options={c: 6 for c in 코드들},
              urls={c: 1 for c in 코드들},
              mapped={c: True for c in 코드들})
    assert len(결과) == 30
    assert all(v['phase'] == PHASE_READY for v in 결과.values())


def test_500개를_넘으면_잘라서_묻는다(session):
    """한 번의 IN 절에 넣는 값 개수에는 DB 상한이 있다 — 넘기면 조회가 통째로 터진다.

    🔴 [2026-08-14 실측으로 바로잡음] 여기 적혀 있던 「SQLite 는 999개를 넘으면
       터진다」는 **틀린 근거**였다. 999 는 SQLite 3.32 **이전**의 기본값이다.
       진짜 한도와 「그런데 왜 그보다 훨씬 작은 500 에서 자르는가」는
       `lemouton/matrix/readiness._CHUNK` 옆에 실측과 함께 적어 뒀다 —
       여기 옮겨 적지 않는다(같은 사실이 두 곳에 살면 한쪽만 고쳐진다).
       틀린 숫자를 근거로 남기면 다음 사람이 그걸 믿고 잘못 판단한다.

    이 시험이 보는 것은 「진짜로 잘려 나가는가」 하나뿐이다 —
    600줄이면 묶음 2개 → 위상 판정 쿼리 2개(묶음당 1개). 그리고 **터지지 않아야** 한다.
    """
    from lemouton.matrix.readiness import PHASE_DRAFT, phase_batch
    코드들 = [f'옵션함_많음_{i:04d}' for i in range(600)]
    n = _쿼리_수를_세며(session, lambda: phase_batch(
        session, 코드들, options={}, urls={}, mapped={}, axes={}))
    assert n == 2, f'묶음 2개면 쿼리 2개여야 한다 (실제 {n})'
    결과 = phase_batch(session, 코드들, options={}, urls={}, mapped={}, axes={})
    assert len(결과) == 600
    # 아무것도 안 심었으니 전부 미완료다 — 판정이 실제로 돌았다는 증거.
    assert 결과['옵션함_많음_0599']['phase'] == PHASE_DRAFT
