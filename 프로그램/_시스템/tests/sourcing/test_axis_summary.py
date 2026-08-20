# -*- coding: utf-8 -*-
"""[TEST] 옵션 매트릭스 목록의 「축 요약」 — 순서·종류·조회 수를 못 박는다.

여기서 지키는 것 세 가지
  ① **축 순서**  — `step_no` 순. 정렬을 빠뜨리면 「모델 × 색상」이 어느 날
     「색상 × 모델」로 보인다. 에러가 안 나므로 시험이 없으면 아무도 모른다.
     그래서 일부러 **뒤섞어 심고** 라벨을 본다.
  ② **종류 판정** — 축에 「모델」이 있으면 모델모음전(`AXIS_PRESETS` 주석의 규칙).
     종류는 저장돼 있지 않으니, 판정이 틀리면 화면이 통째로 다른 상품처럼 보인다.
     이름(`kind_label`)도 프리셋 것과 **같은지** 본다 — 여기 하드코딩하면
     만들기 화면에서 이름을 바꿔도 목록만 옛 이름으로 남는다.
  ③ **조회 1개**  — 줄 수와 무관해야 한다. 줄마다 조회하면 상품이 늘수록 느려지다
     어느 날 목록이 안 열린다.

🔴 시험용 DB 에 대상이 없으면 시험은 아무것도 안 본다 — 그래서 매번 심고,
   심은 것이 실제로 잡히는지(`axis_names` 가 비지 않는지) 먼저 확인한다.
"""
import json
import uuid

import pytest


@pytest.fixture
def s():
    """빈 임시 SQLite 위의 세션. 심은 것은 시험이 끝나면 치운다."""
    from shared.db import Base, SessionLocal, engine
    Base.metadata.create_all(engine)
    session = SessionLocal()
    codes: list[str] = []
    yield session, codes
    from lemouton.sourcing.models import BundleOptionStep, Model
    session.rollback()
    if codes:
        (session.query(BundleOptionStep)
         .filter(BundleOptionStep.model_code.in_(codes))
         .delete(synchronize_session=False))
        (session.query(Model).filter(Model.model_code.in_(codes))
         .delete(synchronize_session=False))
        session.commit()
    session.close()


def _seed(s, steps, *, code=None):
    """모음전 하나를 심는다. `steps` = [(step_no, 축이름, 값목록 또는 생 JSON), ...].

    `_seed` 가 준 순서 그대로 넣는다 — 시험이 일부러 뒤섞어 넣을 수 있어야 한다.
    """
    session, codes = s
    from lemouton.sourcing.models import BundleOptionStep, Model
    code = code or ('U-축요약-' + uuid.uuid4().hex[:8])
    codes.append(code)
    session.add(Model(model_code=code, model_name_raw=code,
                      model_name_display=code, is_option_box=True))
    for step_no, axis_name, values in steps:
        raw = values if isinstance(values, str) else json.dumps(values,
                                                                ensure_ascii=False)
        session.add(BundleOptionStep(model_code=code, step_no=step_no,
                                     axis_name=axis_name, values_json=raw))
    session.commit()
    return code


# ── ① 축 구성·종류 ─────────────────────────────────────────────────────

def test_3축_모델모음전은_모델로_판정되고_모델명이_나온다(s):
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '모델', ['메이트', '스위트']),
                     (2, '색상', ['블랙', '화이트']),
                     (3, '사이즈', ['250', '260'])])

    got = axis_batch(session, [code])[code]

    assert got['axis_names'] == ['모델', '색상', '사이즈'], '심은 축이 안 잡혔다'
    assert got['axis_label'] == '모델 × 색상 × 사이즈'
    assert got['kind'] == 'model'
    assert got['model_names'] == ['메이트', '스위트']
    assert got['empty_axes'] == 0
    assert got['axis_counts'] == [2, 2, 2], '옵션축 칸(모델2×색상2×사이즈2) 숫자가 안 맞는다'


def test_축마다_서로_다른_값_개수가_따로_쌓인다(s):
    """🔴 옵션축 칸(「모델 1개 × 색상 4개 × 사이즈 3개」)이 읽는 숫자다.

    세 축의 값 개수를 일부러 다르게 심어 섞이지 않는지 본다.
    """
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '모델', ['메이트']),
                     (2, '색상', ['블랙', '화이트', '네이비', '베이지']),
                     (3, '사이즈', ['250', '260', '270'])])

    got = axis_batch(session, [code])[code]

    assert got['axis_counts'] == [1, 4, 3]
    assert len(got['axis_counts']) == len(got['axis_names']), '축 이름·개수 길이가 안 맞는다'


def test_2축_색상모음전은_모델명이_비어_있다(s):
    """🔴 여기서 모델명이 나오면 색상모음전에 없는 모델을 지어낸 것이다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '색상', ['블랙']), (2, '사이즈', ['250'])])

    got = axis_batch(session, [code])[code]

    assert got['axis_label'] == '색상 × 사이즈'
    assert got['kind'] == 'color'
    assert got['model_names'] == []


def test_축이_없으면_모른다로_돌려준다(s):
    """축 0개는 「색상 모음전」이 아니라 **아직 모른다**(None)."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [])

    got = axis_batch(session, [code])[code]

    assert got == {'axis_names': [], 'axis_label': None, 'kind': None,
                   'kind_label': None, 'model_names': [], 'empty_axes': 0,
                   'axis_counts': []}


def test_물어본_코드는_없어도_전부_돌려준다(s):
    """화면이 「없으면 이렇게」 폴백을 따로 짜면 그 폴백이 여기와 갈린다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    없는코드 = 'U-없는-' + uuid.uuid4().hex[:8]

    got = axis_batch(session, [없는코드])

    assert 없는코드 in got
    assert got[없는코드]['axis_label'] is None


# ── ② 순서 — 이 파일의 존재 이유 ────────────────────────────────────────

def test_step_no를_뒤섞어_심어도_라벨_순서가_맞는다(s):
    """🔴 정렬을 빠뜨리면 「모델 × 색상 × 사이즈」가 어느 날 뒤집힌다.

    심는 순서를 3 → 1 → 2 로 일부러 어긋나게 넣는다. 정렬이 없으면 DB 가
    돌려주는 순서(대개 넣은 순서)가 그대로 라벨이 되어 눈에 띄지 않게 틀린다.
    """
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(3, '사이즈', ['250', '260']),
                     (1, '모델', ['메이트']),
                     (2, '색상', ['블랙', '화이트', '네이비'])])

    got = axis_batch(session, [code])[code]

    assert got['axis_names'] == ['모델', '색상', '사이즈']
    assert got['axis_label'] == '모델 × 색상 × 사이즈'
    assert got['model_names'] == ['메이트'], '축 순서가 어긋나면 모델명도 어긋난다'
    assert got['axis_counts'] == [1, 3, 2], '심은 순서(사이즈·모델·색상)를 따라가면 [2,1,3]이 되어 틀린다'


# ── 값이 빈 축 ─────────────────────────────────────────────────────────

def test_값이_빈_축을_센다(s):
    """축은 만들었는데 값을 안 채운 것 — 화면이 「값 없음」으로 알려야 한다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '모델', ['메이트']),
                     (2, '색상', []),
                     (3, '사이즈', ['', '  '])])

    got = axis_batch(session, [code])[code]

    assert got['empty_axes'] == 2
    assert got['axis_label'] == '모델 × 색상 × 사이즈', '값이 없어도 축은 축이다'
    assert got['axis_counts'] == [1, 0, 0], '값이 빈 축은 0개여야지 없는 셈 치면 안 된다'


def test_깨진_JSON은_터지지_않고_값없음으로_센다(s):
    """🔴 한 줄이 깨졌다고 목록 100줄이 통째로 안 열리면 사고 대응이 막힌다.

    다만 **조용히 삼키지는 않는다** — `empty_axes` 에 잡혀 화면에 드러난다.
    """
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '색상', '{이건 JSON 이 아니다'),
                     (2, '사이즈', '"리스트가 아님"')])

    got = axis_batch(session, [code])[code]

    assert got['empty_axes'] == 2
    assert got['kind'] == 'color'
    assert got['axis_label'] == '색상 × 사이즈'


def test_값에_None이_있어도_None이라는_글자가_안_나온다(s):
    """없는 값을 지어내지 않는다 — 화면에 'None' 이 찍히면 안 된다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '모델', '["메이트", null, "스위트"]')])

    got = axis_batch(session, [code])[code]

    assert got['model_names'] == ['메이트', '스위트']


# ── 종류 이름은 프리셋 것을 빌려 쓴다 ───────────────────────────────────

def test_종류_이름은_만들기_화면_프리셋과_같다(s):
    """여기 하드코딩하면 만들기 화면에서 이름을 바꿔도 목록만 옛 이름으로 남는다."""
    from webapp.routes.optgen import AXIS_PRESETS

    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    preset = {p['kind']: p['label'] for p in AXIS_PRESETS}
    모델 = _seed(s, [(1, '모델', ['메이트'])])
    색상 = _seed(s, [(1, '색상', ['블랙'])])

    got = axis_batch(session, [모델, 색상])

    assert got[모델]['kind_label'] == preset['model']
    assert got[색상]['kind_label'] == preset['color']


def test_모델_별칭도_모델모음전으로_잡힌다(s):
    """판정은 `axis_slot.is_model_axis` 하나뿐 — 여기서 글자를 다시 비교하지 않는다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    code = _seed(s, [(1, '모델명', ['메이트']), (2, '색상', ['블랙'])])

    got = axis_batch(session, [code])[code]

    assert got['kind'] == 'model'
    assert got['model_names'] == ['메이트']


# ── ③ 조회 수 ──────────────────────────────────────────────────────────

def _count_queries(fn):
    """`fn()` 이 도는 동안 실제로 나간 SQL 문장 수를 센다."""
    from sqlalchemy import event

    from shared.db import engine
    box = {'n': 0}

    def _tick(*a, **k):
        box['n'] += 1

    event.listen(engine, 'before_cursor_execute', _tick)
    try:
        fn()
    finally:
        event.remove(engine, 'before_cursor_execute', _tick)
    return box['n']


def test_조회_수는_줄_수와_무관하게_1개다(s):
    """🔴 줄마다 조회하면 상품이 늘수록 느려지다 어느 날 목록이 안 열린다."""
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    codes = [_seed(s, [(1, '모델', ['메이트']), (2, '색상', ['블랙'])])
             for _ in range(6)]
    session.commit()            # 남은 쓰기가 조회 중에 튀어나오지 않게

    한줄 = _count_queries(lambda: axis_batch(session, codes[:1]))
    여섯줄 = _count_queries(lambda: axis_batch(session, codes))

    assert 한줄 == 1, f'한 줄에 조회가 {한줄}개'
    assert 여섯줄 == 1, f'여섯 줄에 조회가 {여섯줄}개 — 줄마다 돌고 있다'


def test_코드가_없으면_조회를_아예_안_한다(s):
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    session.commit()
    n = _count_queries(lambda: axis_batch(session, []))
    assert n == 0


def test_코드가_많으면_잘라_돌리고_합친다(s):
    """🔴 IN 절에 한 번에 넣는 값 개수에는 DB 상한이 있다 — 넘기면 목록이 통째로 실패한다.

    상한이 정확히 얼마인지는 `readiness._CHUNK` 옆에 실측으로 적어 뒀다
    (예전에 여기 적혀 있던 「999」는 SQLite 3.32 이전 기본값이라 틀린 근거였다).
    """
    from lemouton.matrix import readiness
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    real = _seed(s, [(1, '모델', ['메이트'])])
    codes = ['U-빈칸-%04d' % i for i in range(readiness._CHUNK + 100)] + [real]
    session.commit()

    n = _count_queries(lambda: axis_batch(session, codes))
    got = axis_batch(session, codes)

    assert n == 2, f'{len(codes)}개를 조회 {n}번에 나눠 돌렸다 — 두 묶음이어야 한다'
    assert len(got) == len(codes)
    assert got[real]['kind'] == 'model', '잘라 돌린 뒤 합치면서 값을 잃었다'


def test_자르는_크기는_한_곳에서만_정한다(s):
    """🔴 500 이라는 숫자를 이 모듈이 또 적으면 안 된다.

    형제 모듈(`matrix/readiness`)의 값을 바꿨을 때 여기 조회 수가 **따라 바뀌어야** 한다.
    안 따라오면 숫자가 두 곳에 사는 것이고, 언젠가 한쪽만 고쳐져 그쪽만 계속 터진다.
    (`tests/matrix/test_unbuilt.py` 가 형제 모듈에 대해 거는 것과 같은 시험이다.)
    """
    from lemouton.matrix import readiness
    from lemouton.sourcing.axis_summary import axis_batch
    session, _ = s
    codes = ['U-크기-%04d' % i for i in range(6)]
    session.commit()

    def 재기():
        return _count_queries(lambda: axis_batch(session, codes))

    assert 재기() == 1, '6개는 한 묶음이라 조회 1개여야 한다'

    원래 = readiness._CHUNK
    readiness._CHUNK = 2                # 2개씩 자르면 6개 → 묶음 3개
    try:
        assert 재기() == 3, '형제 모듈의 크기를 바꿨는데 안 따라온다 — 숫자를 여기 또 적었다'
    finally:
        readiness._CHUNK = 원래
    assert 재기() == 1, '되돌린 뒤에도 그대로여야 한다'
