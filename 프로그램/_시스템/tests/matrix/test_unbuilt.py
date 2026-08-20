# -*- coding: utf-8 -*-
"""미구성 SKU 판정 — 앞글자가 아니라 **구조**로 가른다.

이 시험이 지키는 것 (하나라도 깨지면 화면이 거짓말을 한다):
  ① 판매용 모델은 축 0·옵션 1이어도 미구성이 아니다 — 팔고 있는 상품을 편입 대상으로
     내밀면 안 된다.
  ② 옛 「단독_」 이든 2026-08-06 이후 정식 옵션함(`U…`)이든 **똑같이** 잡힌다.
     🔴 후자가 이 모듈의 존재 이유다 — 앞글자로 세면 그날 이후 것을 전부 놓친다.
  ③ 축이 생기거나 옵션이 2개가 되면 저절로 미구성에서 빠진다(저장하는 값이 아니다).
  ④ 🔴 조회 **개수** 계약 — 코드가 비면 한 번도 안 묻고, 많으면 500개씩 잘라서 묻는다.
     이 둘은 값으로는 안 보이는 계약이라 **나간 쿼리 수를 직접 센다**.
     값만 보면 막이를 없애도·안 잘라도 시험이 전부 초록불이 된다(실제로 그랬다).
"""
import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    import shared.display_no          # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _모델(session, code, *, box):
    """모델 한 줄 심기 — 옵션함인지 아닌지만 다르다."""
    from lemouton.sourcing.models import Model
    session.add(Model(model_code=code, model_name_raw=code,
                      model_name_display=code, brand='TEST', is_option_box=box))
    session.flush()


def _옵션(session, code, sku, *, color='블랙', size='250'):
    from lemouton.sourcing.models import Option
    session.add(Option(canonical_sku=sku, model_code=code,
                       color_code=color, size_code=size))
    session.flush()


def _축(session, code, step_no, name, values='[]'):
    from lemouton.sourcing.models import BundleOptionStep
    session.add(BundleOptionStep(model_code=code, step_no=step_no,
                                 axis_name=name, values_json=values))
    session.flush()


# ══════════════════════════════════════════════════════════════════
#  1) is_unbuilt — 진리표 전수 (옵션함 여부 × 축 0/1 × 옵션 1/2)
# ══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('box,axes,options,기대', [
    # 옵션함 — 축 0 · 옵션 1 일 때만 미구성
    (True,  0, 1, True),
    (True,  0, 2, False),   # 축만 안 짠 「짜다 만 매트릭스」 = W1 의 draft
    (True,  1, 1, False),   # 축을 짜기 시작함
    (True,  1, 2, False),
    # 판매용 모델 — 어떤 조합이어도 미구성이 아니다
    (False, 0, 1, False),
    (False, 0, 2, False),
    (False, 1, 1, False),
    (False, 1, 2, False),
])
def test_진리표_전수(box, axes, options, 기대):
    from lemouton.matrix.unbuilt import is_unbuilt
    assert is_unbuilt(is_option_box=box, axes=axes, options=options) is 기대


def test_판매용_모델은_축0_옵션1이어도_미구성이_아니다():
    """🔴 옵션 하나짜리 단품 상품이 전부 편입 대상으로 잡히는 사고를 막는다.

    이 한 줄이 없으면 「멀쩡히 팔고 있는 상품을 다른 매트릭스에 넣으세요」라고
    권하게 된다. 진리표에도 있지만, 뜻이 무거워서 따로 남긴다.
    """
    from lemouton.matrix.unbuilt import is_unbuilt
    assert is_unbuilt(is_option_box=False, axes=0, options=1) is False
    assert is_unbuilt(is_option_box=True, axes=0, options=1) is True


def test_옵션이_0개인_빈_옵션함은_미구성이_아니다():
    """편입할 SKU 자체가 없다 — 「아직 안 짠 낱개」와는 다른 상태다."""
    from lemouton.matrix.unbuilt import is_unbuilt
    assert is_unbuilt(is_option_box=True, axes=0, options=0) is False


# ══════════════════════════════════════════════════════════════════
#  2) unbuilt_batch — 진짜 DB 로. 심은 것이 실제로 잡히는지 본다
# ══════════════════════════════════════════════════════════════════

def test_2026_08_06_이후_정식_옵션함이_잡힌다(session):
    """🔴 **이 모듈의 존재 이유.**

    재고관리 「제품 추가」(모음전 체크 안 함)는 그날 이후 `단독_` 를 안 만들고
    `create_option_box()` 로 `U…` 옵션함을 만든다. 앞글자로 세면 여기가 0건이 된다.
    실제 그 길(`create_option_box`)을 그대로 태워서 확인한다.
    """
    from lemouton.matrix.service import create_option_box
    from lemouton.matrix.unbuilt import unbuilt_batch

    mo = create_option_box(session, name='A안시험제품', brand='TEST')
    code = mo.model_code
    assert not code.startswith('단독_'), '전제가 깨졌다 — 아직 단독_ 를 만든다'
    assert code.startswith('U'), f'정식 옵션함 번호가 아니다: {code}'
    _옵션(session, code, 'SKU-NEW00001')

    assert unbuilt_batch(session, [code]) == {code}


def test_옛_단독_코드도_앞글자를_안_보고_잡힌다(session):
    """레거시도 같은 규칙으로 잡힌다 — 앞글자를 보지 않는데도 잡힌다는 뜻."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    code = '단독_SKU-OLD00001'
    _모델(session, code, box=True)
    _옵션(session, code, 'SKU-OLD00001')

    assert unbuilt_batch(session, [code]) == {code}


def test_판정에_앞글자를_쓰지_않는다(session):
    """🔴 「둘 다 잡힌다」만으로는 앞글자를 안 본다는 증거가 안 된다.

    앞글자만 **바꿔서** 심어도 결과가 같아야 한다. 만약 어딘가에서 `단독_` 를
    보고 있었다면 이 두 줄의 판정이 갈린다.
    """
    from lemouton.matrix.unbuilt import unbuilt_batch
    _모델(session, '단독_SKU-AAA', box=True)
    _옵션(session, '단독_SKU-AAA', 'SKU-AAA')
    _모델(session, 'U20260813-000099', box=True)
    _옵션(session, 'U20260813-000099', 'SKU-BBB')

    assert unbuilt_batch(session, ['단독_SKU-AAA', 'U20260813-000099']) == {
        '단독_SKU-AAA', 'U20260813-000099'}


def test_판매용_모음전은_안_섞인다(session):
    """축 0·옵션 1이어도 판매용이면 미구성이 아니다 — DB 를 거쳐서도 그렇다."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    _모델(session, 'SELL-0001', box=False)
    _옵션(session, 'SELL-0001', 'SKU-SELL0001')

    assert unbuilt_batch(session, ['SELL-0001']) == set()


def test_축이_생기면_미구성에서_빠진다(session):
    """저장하는 값이 아니라 파생값이다 — 축 한 줄이 생기면 바로 벗겨진다."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    code = 'U20260813-000001'
    _모델(session, code, box=True)
    _옵션(session, code, 'SKU-AXIS0001')
    assert unbuilt_batch(session, [code]) == {code}, '축 짜기 전엔 미구성이어야 한다'

    _축(session, code, 1, '색상', '["블랙","화이트"]')
    assert unbuilt_batch(session, [code]) == set()


def test_옵션이_2개가_되면_미구성에서_빠진다(session):
    """축만 안 짠 「짜다 만 매트릭스」다 — 그건 W1 의 draft 이지 미구성 SKU 가 아니다."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    code = 'U20260813-000002'
    _모델(session, code, box=True)
    _옵션(session, code, 'SKU-TWO00001')
    assert unbuilt_batch(session, [code]) == {code}

    _옵션(session, code, 'SKU-TWO00002', color='화이트')
    assert unbuilt_batch(session, [code]) == set()


def test_주인칸은_판정에_못_쓴다(session):
    """🔴 `matrix_option_id IS NULL` 을 후보에서 뺀 근거를 못 박아 둔다.

    `owner_hook` 의 before_flush 가 저장되는 순간 자동으로 채운다. 옵션함은 만들 때
    원본 매트릭스를 항상 같이 만들므로 이 칸은 **미구성 SKU 에서도 채워져 있다**.
    늘 채워지는 칸으로는 아무것도 가를 수 없다.
    """
    from lemouton.matrix.owner_hook import install
    from lemouton.matrix.service import create_option_box
    from lemouton.matrix.unbuilt import unbuilt_batch
    from lemouton.sourcing.models import Option

    install()
    mo = create_option_box(session, name='주인칸시험', brand='TEST')
    _옵션(session, mo.model_code, 'SKU-OWN00001')
    session.flush()

    got = session.get(Option, 'SKU-OWN00001')
    assert got.matrix_option_id == mo.id, \
        '주인칸이 안 채워졌다 — 이 시험의 전제(owner_hook 이 늘 채운다)가 깨졌다'
    # 주인칸은 채워져 있는데 미구성이다 → 그 칸으로는 못 가른다
    assert unbuilt_batch(session, [mo.model_code]) == {mo.model_code}


# ══════════════════════════════════════════════════════════════════
#  3) 호출 규약 — 화면이 이미 센 값을 넘길 수 있어야 한다
# ══════════════════════════════════════════════════════════════════

def _쿼리_수를_세며(session, fn):
    """fn() 을 돌리는 동안 실제로 나간 SQL 개수를 센다.

    🔴 `tests/matrix/test_readiness.py` 의 같은 이름 도우미와 **같은 방식**이다.
       쿼리 수를 세는 방법을 여기서 새로 만들면, 두 시험이 서로 다른 것을 세면서
       같은 말을 하게 된다.
    """
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


def test_코드가_비면_조회를_안_한다(session):
    """🔴 **돌려받은 값이 아니라 「쿼리가 나갔는지」를 센다.**

    예전엔 `unbuilt_batch(session, []) == set()` 만 봤다. 그런데 그건 아무것도 안 보는
    시험이었다 — 심은 줄이 없으니 조회가 세 개 나가든 하나도 안 나가든 결과는 똑같이
    빈 집합이라, 시험이 언제나 초록불이었다. 화면을 열 때마다 아무 뜻도 없는 조회가
    세 개씩 늘어도 아무도 모른다.

    🔴 이 시험이 잡는 것과 못 잡는 것을 정직하게 적어 둔다.
      · 잡는다 — 500개 쪼개기를 되돌려 `.in_(codes)` 로 한 번에 물으면 빈 목록에도
        조회가 3개 나간다 → 빨간불. (실제로 깨서 확인했다.)
      · 못 잡는다 — `if not codes: return set()` **두 줄만** 지우는 것.
        쪼개기 반복문이 빈 목록에서 한 번도 안 돌아 조회가 어차피 0개라, 지워도 동작이
        같다. 그 두 줄은 이제 「먼저 빠져나가는 길」일 뿐 결과를 바꾸지 않는다.
        시험이 지켜야 하는 것은 그 줄이 아니라 **결과**(0개 조회)라서 이대로 둔다.
    """
    from lemouton.matrix.unbuilt import unbuilt_batch

    빈목록 = _쿼리_수를_세며(session, lambda: unbuilt_batch(session, []))
    assert 빈목록 == 0, f'빈 목록인데 조회가 {빈목록}개 나갔다 — 막이가 사라졌다'

    없음 = _쿼리_수를_세며(session, lambda: unbuilt_batch(session, None))
    assert 없음 == 0, f'None 인데 조회가 {없음}개 나갔다'

    빈문자 = _쿼리_수를_세며(session, lambda: unbuilt_batch(session, ['', None]))
    assert 빈문자 == 0, f'빈 값만 걸러내면 남는 게 없는데 조회가 {빈문자}개 나갔다'

    # 값도 여전히 빈 집합이어야 한다(위 셋이 0이어도 값이 틀리면 소용없다).
    assert unbuilt_batch(session, []) == set()
    assert unbuilt_batch(session, None) == set()


def test_화면이_센_값을_넘기면_그걸_쓴다(session):
    """`optgen._boxes()` 는 옵션 수를 이미 세어 뒀다 — 두 번 세지 않게 한다."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    code = 'U20260813-000003'
    _모델(session, code, box=True)
    _옵션(session, code, 'SKU-PASS0001')

    assert unbuilt_batch(session, [code],
                         option_counts={code: 1}, option_box={code: True}) == {code}
    # 넘긴 값이 실제로 쓰인다 — 옵션 2개라고 넘기면 미구성이 아니게 된다
    assert unbuilt_batch(session, [code],
                         option_counts={code: 2}, option_box={code: True}) == set()


def test_넘긴_표에_없는_코드는_미구성이_아니라고_본다(session):
    """🔴 모를 때는 덜 말하는 쪽으로 기운다.

    배지 하나 안 뜨는 건 불편할 뿐이지만, 판매용 상품을 미구성이라 부르면
    팔고 있는 상품을 남의 매트릭스에 편입시키게 된다.
    """
    from lemouton.matrix.unbuilt import unbuilt_batch
    code = 'U20260813-000004'
    _모델(session, code, box=True)
    _옵션(session, code, 'SKU-MISS0001')

    assert unbuilt_batch(session, [code], option_box={}) == set()
    assert unbuilt_batch(session, [code], option_counts={}) == set()


def test_여러_개를_섞어_넣어도_미구성만_돌려준다(session):
    """실제 화면은 섞여 있다 — 골라내는 게 이 함수의 일이다."""
    from lemouton.matrix.unbuilt import unbuilt_batch
    _모델(session, 'U-MIX-01', box=True)          # 미구성
    _옵션(session, 'U-MIX-01', 'SKU-MIX01')
    _모델(session, 'U-MIX-02', box=True)          # 축을 짬
    _옵션(session, 'U-MIX-02', 'SKU-MIX02')
    _축(session, 'U-MIX-02', 1, '색상')
    _모델(session, 'U-MIX-03', box=True)          # 옵션 2개
    _옵션(session, 'U-MIX-03', 'SKU-MIX03A')
    _옵션(session, 'U-MIX-03', 'SKU-MIX03B', color='화이트')
    _모델(session, 'U-MIX-04', box=True)          # 빈 옵션함
    _모델(session, 'SELL-MIX', box=False)         # 판매용
    _옵션(session, 'SELL-MIX', 'SKU-MIX05')
    _모델(session, '단독_SKU-MIX06', box=True)     # 레거시 미구성
    _옵션(session, '단독_SKU-MIX06', 'SKU-MIX06')

    codes = ['U-MIX-01', 'U-MIX-02', 'U-MIX-03', 'U-MIX-04',
             'SELL-MIX', '단독_SKU-MIX06']
    assert unbuilt_batch(session, codes) == {'U-MIX-01', '단독_SKU-MIX06'}


# ══════════════════════════════════════════════════════════════════
#  4) 🔴 줄이 많은 날에만 터지는 사고 — 500개씩 잘라서 묻는다
# ══════════════════════════════════════════════════════════════════

def test_500개를_넘으면_잘라서_묻는다(session):
    """🔴 한 번에 다 넣으면 옵션함이 쌓인 날 조회가 통째로 거부된다.

    `/optgen/api/unbuilt-skus` 는 **옵션함 전부**를 넣고 이 함수를 부른다(개수 상한 없음).
    개발할 땐 몇 개뿐이라 영영 멀쩡하고, 라이브에서만 어느 날 갑자기 죽는다.

    600개면 묶음 2개. 넘긴 표가 없으니 묶음당 3쿼리(축·옵션 수·옵션함) → 6개다.
    """
    from lemouton.matrix.unbuilt import unbuilt_batch

    codes = [f'U-MANY-{i:04d}' for i in range(600)]
    # 🔴 두 묶음 **양쪽**에 진짜 미구성 SKU 를 하나씩 심는다. 아무것도 안 심으면
    #    「둘째 묶음을 아예 안 물었다」와 「물었는데 없었다」가 똑같이 빈 집합으로 보여
    #    쪼개기가 실제로 도는지 아무것도 못 본다.
    _모델(session, codes[0], box=True)
    _옵션(session, codes[0], 'SKU-MANY-FIRST')
    _모델(session, codes[-1], box=True)
    _옵션(session, codes[-1], 'SKU-MANY-LAST')

    n = _쿼리_수를_세며(session, lambda: unbuilt_batch(session, codes))
    assert n == 6, f'묶음 2개면 쿼리 6개여야 한다 — 안 자르고 통째로 물었다 (실제 {n})'

    # 쪼개 놓고도 판정은 그대로여야 한다 — 둘째 묶음 것이 빠지면 여기서 걸린다.
    assert unbuilt_batch(session, codes) == {codes[0], codes[-1]}


def test_넘긴_표가_있어도_남은_조회를_자른다(session):
    """축 조회 하나만 남아도 자른다 — 세 조회 중 하나만 자르면 나머지가 터진다.

    600개·표를 다 넘기면 축 조회만 남으니 묶음당 1쿼리 → 2개.
    (6 = 3×2 와 견주면, 세 조회가 **각각** 잘리고 있다는 뜻이 된다.
     하나라도 안 잘렸으면 6이 아니라 4나 5가 나온다.)
    """
    from lemouton.matrix.unbuilt import unbuilt_batch

    codes = [f'U-PASS-{i:04d}' for i in range(600)]
    _모델(session, codes[-1], box=True)
    _옵션(session, codes[-1], 'SKU-PASS-LAST')

    표_옵션수 = {c: 1 for c in codes}
    표_옵션함 = {c: True for c in codes}
    n = _쿼리_수를_세며(session, lambda: unbuilt_batch(
        session, codes, option_counts=표_옵션수, option_box=표_옵션함))
    assert n == 2, f'축 조회만 남으면 묶음당 1개씩 2개여야 한다 (실제 {n})'


def test_자르는_크기는_한_곳에서만_정한다(session):
    """🔴 500 이라는 숫자를 이 모듈이 또 적으면 안 된다.

    형제 모듈(`readiness`)의 값을 바꿨을 때 여기 조회 수가 **따라 바뀌어야** 한다.
    안 따라오면 숫자가 두 곳에 사는 것이고, 언젠가 한쪽만 고쳐져 그쪽만 계속 터진다.
    """
    from lemouton.matrix import readiness
    from lemouton.matrix.unbuilt import unbuilt_batch

    codes = [f'U-ONE-{i:04d}' for i in range(6)]
    표 = ({c: 1 for c in codes}, {c: True for c in codes})

    def 재기():
        return _쿼리_수를_세며(session, lambda: unbuilt_batch(
            session, codes, option_counts=표[0], option_box=표[1]))

    assert 재기() == 1, '6개는 한 묶음이라 축 조회 1개여야 한다'

    원래 = readiness._CHUNK
    readiness._CHUNK = 2            # 2개씩 자르면 6개 → 묶음 3개
    try:
        assert 재기() == 3, '형제 모듈의 크기를 바꿨는데 안 따라온다 — 숫자를 여기 또 적었다'
    finally:
        readiness._CHUNK = 원래
    assert 재기() == 1, '되돌린 뒤에도 그대로여야 한다'
