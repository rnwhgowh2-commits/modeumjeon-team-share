# -*- coding: utf-8 -*-
"""M4-3 상품고시정보 기본값 — 저장소·병합(순수) + 라우트 + 등록/점검 배선.

이 기능이 지켜야 하는 두 가지:
  ① 저장된 드래프트는 **절대 안 바뀐다** — 병합은 컴파일에 넘길 사본에서만.
  ② 기본값이 없는 칸은 **비운 채로 둔다** — 지어내면 실제 판매 상품에 가짜 고시가 올라간다.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration import notice_defaults as ND
from lemouton.registration.models import ProductDraft
from lemouton.registration.notice import NOTICE_TYPES, build_notice


def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


# ── 폼에 그릴 칸 목록은 notice.py 를 **읽어서** 만든다 ─────────────────────

def test_필수칸_목록은_notice_규격에서_나온다():
    from lemouton.registration import notice as N
    for nt in NOTICE_TYPES:
        keys = ND.field_keys(nt)
        # 공통 7 전부 + 그 유형의 유형별 필수 전부
        assert set(N._COMMON_IN_KEY.values()) <= set(keys)
        assert set(N._PER_TYPE_REQUIRED[nt]) <= set(keys)
        # 선택 필드(굽높이·제조연월)는 기본값이 성립하지 않아 들어가지 않는다
        for snake, _camel in N._PER_TYPE_OPTIONAL[nt]:
            assert snake not in keys


def test_사장님이_꼭_채워야_하는_칸은_공식문구가_없는_두_칸():
    """네이버 공식 문구가 있는 칸은 미입력이어도 notice.py 가 채운다 → 화면 표시가 달라야 한다."""
    must = [f['key'] for f in ND.field_specs('WEAR')
            if f['group'] == 'common' and not f['has_official_default']]
    assert set(must) == {'warranty_policy', 'after_service_director'}


def test_모르는_고시유형과_스코프는_거부한다():
    with pytest.raises(ND.NoticeDefaultsError):
        ND.field_specs('HAT')
    with pytest.raises(ND.NoticeDefaultsError):
        ND.parse_scope('musinsa')       # 'source:' 접두사 없음
    with pytest.raises(ND.NoticeDefaultsError):
        ND.parse_scope('source:')       # 소싱처 비어 있음
    assert ND.parse_scope('source:musinsa') == ('source', 'musinsa')
    assert ND.parse_scope('global') == ('global', None)


# ── 저장 ────────────────────────────────────────────────────────────────────

def test_저장은_빈칸을_버리고_모르는_키는_거부한다():
    s = _mem()
    clean = ND.save_values(s, 'global', 'WEAR', {
        'warranty_policy': '구매일로부터 1년',
        'after_service_director': '홍길동 02-000-0000',
        'material': '   ',          # 공백만 = 설정 안 함
    })
    s.commit()
    assert clean == {'warranty_policy': '구매일로부터 1년',
                     'after_service_director': '홍길동 02-000-0000'}
    assert ND.get_values(s, 'global', 'WEAR') == clean

    with pytest.raises(ND.NoticeDefaultsError):
        ND.save_values(s, 'global', 'WEAR', {'heel_height': '5cm'})


def test_같은_스코프_유형은_한_행으로_덮어쓴다():
    s = _mem()
    ND.save_values(s, 'global', 'WEAR', {'warranty_policy': 'A'})
    s.commit()
    ND.save_values(s, 'global', 'WEAR', {'warranty_policy': 'B'})
    s.commit()
    assert s.query(ND.NoticeDefault).count() == 1
    assert ND.get_values(s, 'global', 'WEAR') == {'warranty_policy': 'B'}


def test_스코프와_유형이_다르면_서로_안_섞인다():
    s = _mem()
    ND.save_values(s, 'global', 'WEAR', {'material': '면 100%'})
    ND.save_values(s, 'source:musinsa', 'WEAR', {'material': '나일론'})
    ND.save_values(s, 'global', 'SHOES', {'material': '소가죽'})
    s.commit()
    assert ND.get_values(s, 'global', 'WEAR')['material'] == '면 100%'
    assert ND.get_values(s, 'source:musinsa', 'WEAR')['material'] == '나일론'
    assert ND.get_values(s, 'global', 'SHOES')['material'] == '소가죽'


def test_깨진_기본값_JSON_은_기본값_없음으로_본다():
    """자유 텍스트 컬럼이라 깨질 수 있다 — 깨진 값으로 고시를 채우지 않는다(빈 것과 같은 취급)."""
    s = _mem()
    s.add(ND.NoticeDefault(scope='global', notice_type='WEAR', values_json='{깨짐'))
    s.commit()
    assert ND.get_values(s, 'global', 'WEAR') == {}


# ── 병합 우선순위 ───────────────────────────────────────────────────────────

def test_우선순위는_드래프트_소싱처_전역_순():
    merged, filled = ND.merge_values(
        'WEAR', {'material': '드래프트 소재'},
        source_values={'material': '소싱처 소재', 'color': '소싱처 색상'},
        source_id='musinsa',
        global_values={'material': '전역 소재', 'color': '전역 색상',
                       'warranty_policy': '전역 보증'})
    assert merged['material'] == '드래프트 소재'      # 드래프트 값은 절대 안 덮인다
    assert merged['color'] == '소싱처 색상'           # 소싱처가 전역보다 우선
    assert merged['warranty_policy'] == '전역 보증'   # 소싱처에 없으면 전역
    assert filled == {'color': 'source:musinsa', 'warranty_policy': 'global'}
    assert 'material' not in filled


def test_기본값이_없으면_비운_채로_둔다():
    """폴백 금지 — 없는 값을 지어내지 않는다. 그래서 컴파일은 여전히 실패해야 한다."""
    merged, filled = ND.merge_values('WEAR', {}, global_values={'warranty_policy': 'X'})
    assert 'material' not in merged and 'material' not in filled
    with pytest.raises(Exception):
        build_notice('WEAR', merged)


def test_병합본은_실제로_고시를_완성시킨다():
    merged, _ = ND.merge_values('WEAR', {'color': '블랙', 'size': '95'}, global_values={
        'material': '면 100%', 'manufacturer': '르무통', 'caution': '단독세탁',
        'warranty_policy': '구매일로부터 1년', 'after_service_director': '홍길동 02-000-0000',
    })
    body = build_notice('WEAR', merged)
    assert body['wear']['material'] == '면 100%'
    assert body['wear']['color'] == '블랙'


# ── 드래프트 적용 — 저장값 불변 ─────────────────────────────────────────────

def _draft(s, **over):
    kw = dict(name='테스트 자켓', sale_price=39000, notice_type='WEAR',
              notice_json=json.dumps({'color': '블랙'}, ensure_ascii=False))
    kw.update(over)
    d = ProductDraft(**kw)
    s.add(d)
    s.commit()
    return d


def test_적용은_저장된_드래프트를_바꾸지_않는다():
    s = _mem()
    d = _draft(s, source_site='musinsa')
    ND.save_values(s, 'global', 'WEAR', {'material': '면 100%'})
    s.commit()

    view, filled = ND.apply_notice_defaults(s, d)
    assert filled == {'material': 'global'}
    assert json.loads(view.notice_json)['material'] == '면 100%'
    # ★ 저장값은 그대로 — 사장님이 넣은 것만 남아야 한다
    s.expire_all()
    assert json.loads(s.query(ProductDraft).one().notice_json) == {'color': '블랙'}


def test_소싱처_기본값은_그_소싱처_드래프트에만_붙는다():
    s = _mem()
    mine = _draft(s, source_site='musinsa')
    other = _draft(s, source_site='ssf')
    manual = _draft(s)                       # 수기 = 소싱처 없음
    ND.save_values(s, 'source:musinsa', 'WEAR', {'manufacturer': '무신사 제조사'})
    s.commit()

    assert ND.apply_notice_defaults(s, mine)[1] == {'manufacturer': 'source:musinsa'}
    assert ND.apply_notice_defaults(s, other)[1] == {}
    assert ND.apply_notice_defaults(s, manual)[1] == {}


def test_기본값이_없으면_원본_드래프트를_그대로_돌려준다():
    s = _mem()
    d = _draft(s)
    got, filled = ND.apply_notice_defaults(s, d)
    assert got is d and filled == {}


def test_사본은_읽기전용이라_실수로_저장되지_않는다():
    s = _mem()
    d = _draft(s)
    ND.save_values(s, 'global', 'WEAR', {'material': '면 100%'})
    s.commit()
    view, _ = ND.apply_notice_defaults(s, d)
    assert view.name == '테스트 자켓' and view.sale_price == 39000   # 나머지는 그대로 비친다
    with pytest.raises(AttributeError):
        view.name = '바뀌면 안 됨'


def test_깨진_notice_json_은_손대지_않는다():
    """컴파일러가 「고시 JSON 이 깨졌다」고 말하게 둔다 — 여기서 덮으면 원인이 숨는다."""
    s = _mem()
    d = _draft(s, notice_json='{깨짐')
    ND.save_values(s, 'global', 'WEAR', {'material': '면 100%'})
    s.commit()
    got, filled = ND.apply_notice_defaults(s, d)
    assert got is d and filled == {}


def test_아는_소싱처_목록은_우리DB_가_실제로_본_것만():
    s = _mem()
    _draft(s, source_site='musinsa')
    ND.save_values(s, 'source:ssf', 'SHOES', {'material': '소가죽'})
    s.commit()
    assert ND.known_source_ids(s) == ['musinsa', 'ssf']
