# -*- coding: utf-8 -*-
"""SKU 번호 세 가지(품번·바코드·GTIN) — 방금 만든 것만 최소로 확인한다.

이 시험이 지키는 것 (하나라도 깨지면 격자가 거짓말을 한다):
  ① 공란은 저장해도 공란으로 남는다 — 빈 문자열이 아니라 `None`(아직 안 적음).
  ② 안 보낸 칸은 안 건드린다 — 한 칸만 보내도 나머지 두 칸이 지워지면 안 된다.
  ③ 바코드·GTIN 은 겹치면 그 칸만 거부된다(같은 묶음 안에서 · 다른 묶음과도).
  ④ 자체 바코드 생성은 서버가 만들기만 하고, 「빈 것만 채운다」 판정은 화면 몫이다
     (`gen_barcodes` 는 준 목록에 대해서만 서로 안 겹치는 번호를 만든다).
  ⑤ 진척(`counts_batch`)은 SKU 가 0개거나 칸이 없는 DB 에서는 0 이 아니라 `None`
     (「—」로 보여야 할 자리)을 낸다.
"""
import pytest

from shared.db import Base


@pytest.fixture
def session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import lemouton.sourcing.models   # noqa: F401
    import lemouton.matrix.models     # noqa: F401
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _모델(session, code, *, box=True):
    from lemouton.sourcing.models import Model
    session.add(Model(model_code=code, model_name_raw=code,
                      model_name_display=code, brand='TEST', is_option_box=box))
    session.flush()


def _옵션(session, code, sku, *, color='블랙', size='250'):
    from lemouton.sourcing.models import Option
    session.add(Option(canonical_sku=sku, model_code=code,
                       color_code=color, size_code=size))
    session.flush()


# ══════════════════════════════════════════════════════════════════
#  1) save — 격자 저장 · 공란 유지 · 안 보낸 칸은 안 건드림
# ══════════════════════════════════════════════════════════════════

def test_저장한_값이_그대로_읽힌다(session):
    from lemouton.matrix.sku_info import rows_of, save
    _모델(session, 'U-SKU-01')
    _옵션(session, 'U-SKU-01', 'SKU-01-A')

    res = save(session, 'U-SKU-01', [
        {'sku': 'SKU-01-A', 'article_no': 'ABC-123', 'barcode': '2008226560115', 'gtin': ''},
    ])
    session.commit()

    assert res['ok'] if 'ok' in res else True  # ok 는 창구(라우트)가 붙인다
    assert res['rejected'] == []
    assert res['saved'] == 2   # article_no · barcode 두 칸만 바뀜(gtin 은 공란→공란)

    rows = rows_of(session, 'U-SKU-01')
    assert rows[0]['article_no'] == 'ABC-123'
    assert rows[0]['barcode'] == '2008226560115'
    assert rows[0]['gtin'] is None, '공란은 빈 문자열이 아니라 None(아직 안 적음)이어야 한다'


def test_공란으로_보내면_공란으로_남는다(session):
    """🔴 미입력 허용 — 값이 없다고 저장을 막지 않는다."""
    from lemouton.matrix.sku_info import rows_of, save
    _모델(session, 'U-SKU-02')
    _옵션(session, 'U-SKU-02', 'SKU-02-A')

    res = save(session, 'U-SKU-02', [{'sku': 'SKU-02-A', 'article_no': '', 'barcode': '', 'gtin': ''}])
    session.commit()
    assert res['rejected'] == []
    assert res['saved'] == 0   # 원래도 비어 있었으니 바뀐 칸이 없다

    rows = rows_of(session, 'U-SKU-02')
    assert rows[0]['article_no'] is None
    assert rows[0]['barcode'] is None
    assert rows[0]['gtin'] is None


def test_안_보낸_칸은_안_건드린다(session):
    """🔴 `{'sku': X}` = 이번엔 아무것도 안 건드린다. `{'sku': X, 'barcode': ''}` 과 다르다."""
    from lemouton.matrix.sku_info import rows_of, save
    _모델(session, 'U-SKU-03')
    _옵션(session, 'U-SKU-03', 'SKU-03-A')

    save(session, 'U-SKU-03', [{'sku': 'SKU-03-A', 'article_no': 'FIRST'}])
    session.commit()

    # 두 번째 저장 — article_no 칸을 아예 안 보낸다(barcode 만 채움)
    res = save(session, 'U-SKU-03', [{'sku': 'SKU-03-A', 'barcode': '2008226560115'}])
    session.commit()
    assert res['rejected'] == []

    rows = rows_of(session, 'U-SKU-03')
    assert rows[0]['article_no'] == 'FIRST', '안 보낸 칸이 지워졌다 — 격자 저장이 서로를 덮었다'
    assert rows[0]['barcode'] == '2008226560115'


def test_같은_묶음_안에서_겹치면_뒤에_온_줄만_거부된다(session):
    from lemouton.matrix.sku_info import save
    _모델(session, 'U-SKU-04')
    _옵션(session, 'U-SKU-04', 'SKU-04-A')
    _옵션(session, 'U-SKU-04', 'SKU-04-B', color='화이트')

    res = save(session, 'U-SKU-04', [
        {'sku': 'SKU-04-A', 'barcode': '2008226560115'},
        {'sku': 'SKU-04-B', 'barcode': '2008226560115'},
    ])
    session.commit()
    assert res['saved'] == 1
    assert len(res['rejected']) == 1
    assert res['rejected'][0]['sku'] == 'SKU-04-B'
    assert '겹' in res['rejected'][0]['reason']


def test_다른_묶음이_이미_쓰는_번호도_거부된다(session):
    """🔴 겹침 검사는 묶음 안이 아니라 `options` 표 전체에서 본다."""
    from lemouton.matrix.sku_info import save
    _모델(session, 'U-SKU-05A')
    _옵션(session, 'U-SKU-05A', 'SKU-05-A')
    _모델(session, 'U-SKU-05B')
    _옵션(session, 'U-SKU-05B', 'SKU-05-B')

    save(session, 'U-SKU-05A', [{'sku': 'SKU-05-A', 'barcode': '2008226560115'}])
    session.commit()

    res = save(session, 'U-SKU-05B', [{'sku': 'SKU-05-B', 'barcode': '2008226560115'}])
    session.commit()
    assert res['saved'] == 0
    assert len(res['rejected']) == 1
    assert 'SKU-05-A' in res['rejected'][0]['reason']


def test_남의_묶음_SKU는_저장되지_않고_unknown으로_돌아온다(session):
    from lemouton.matrix.sku_info import save
    _모델(session, 'U-SKU-06')
    _옵션(session, 'U-SKU-06', 'SKU-06-A')
    _모델(session, 'U-SKU-06X')
    _옵션(session, 'U-SKU-06X', 'SKU-06-X')

    res = save(session, 'U-SKU-06', [{'sku': 'SKU-06-X', 'article_no': 'HACK'}])
    session.commit()
    assert res['saved'] == 0
    assert res['unknown'] == ['SKU-06-X']


def test_형식이_틀린_칸만_거부되고_맞는_칸은_저장된다(session):
    """🔴 하나가 틀렸다고 격자 전체가 되돌아가면 안 된다."""
    from lemouton.matrix.sku_info import save
    _모델(session, 'U-SKU-07')
    _옵션(session, 'U-SKU-07', 'SKU-07-A')

    res = save(session, 'U-SKU-07', [
        {'sku': 'SKU-07-A', 'article_no': 'OK-123', 'barcode': '123'},  # barcode 자리수 부족
    ])
    session.commit()
    assert res['saved'] == 1
    assert len(res['rejected']) == 1
    assert res['rejected'][0]['field'] == 'barcode'

    from lemouton.matrix.sku_info import rows_of
    rows = rows_of(session, 'U-SKU-07')
    assert rows[0]['article_no'] == 'OK-123', '맞는 칸까지 되돌리면 안 된다'
    assert rows[0]['barcode'] is None


# ══════════════════════════════════════════════════════════════════
#  2) gen_barcodes — 서버는 「만들기」만, 「빈 것만」은 화면 몫
# ══════════════════════════════════════════════════════════════════

def test_준_목록에_대해서만_서로_안_겹치는_번호를_만든다(session):
    from lemouton.matrix.sku_info import gen_barcodes
    _모델(session, 'U-SKU-08')
    _옵션(session, 'U-SKU-08', 'SKU-08-A')
    _옵션(session, 'U-SKU-08', 'SKU-08-B', color='화이트')

    out = gen_barcodes(session, ['SKU-08-A', 'SKU-08-B'])
    assert set(out.keys()) == {'SKU-08-A', 'SKU-08-B'}
    assert out['SKU-08-A'] != out['SKU-08-B']
    from shared.sku_format import is_valid_barcode
    assert is_valid_barcode(out['SKU-08-A'])


def test_이미_DB에_있는_바코드와도_안_겹친다(session):
    from lemouton.matrix.sku_info import gen_barcodes, save
    _모델(session, 'U-SKU-09')
    _옵션(session, 'U-SKU-09', 'SKU-09-A')
    _옵션(session, 'U-SKU-09', 'SKU-09-B', color='화이트')
    save(session, 'U-SKU-09', [{'sku': 'SKU-09-A', 'barcode': '2008226560115'}])
    session.commit()

    out = gen_barcodes(session, ['SKU-09-B'])
    assert out['SKU-09-B'] != '2008226560115'


# ══════════════════════════════════════════════════════════════════
#  3) counts_batch — 진척 · 「모른다」는 0 이 아니라 None
# ══════════════════════════════════════════════════════════════════

def test_진척이_필드별로_따로_세어진다(session):
    from lemouton.matrix.sku_info import counts_batch, save
    _모델(session, 'U-SKU-10')
    _옵션(session, 'U-SKU-10', 'SKU-10-A')
    _옵션(session, 'U-SKU-10', 'SKU-10-B', color='화이트')
    save(session, 'U-SKU-10', [{'sku': 'SKU-10-A', 'article_no': 'A1', 'barcode': '2008226560115'}])
    session.commit()

    out = counts_batch(session, ['U-SKU-10'], {'U-SKU-10': 2})
    row = out['U-SKU-10']
    assert row == {'total': 2, 'article_no': 1, 'barcode': 1, 'gtin': 0}


def test_SKU가_0개인_묶음은_못_센다_0이_아니라_None(session):
    from lemouton.matrix.sku_info import counts_batch
    _모델(session, 'U-SKU-11')

    out = counts_batch(session, ['U-SKU-11'], {'U-SKU-11': 0})
    row = out['U-SKU-11']
    assert row['total'] == 0
    assert row['article_no'] is None
    assert row['barcode'] is None
    assert row['gtin'] is None


def test_빈_문자열도_안_적음으로_센다(session):
    """옛 경로가 남긴 빈 문자열이 있어도 진척 숫자가 부풀면 안 된다."""
    from lemouton.matrix.sku_info import counts_batch
    from lemouton.sourcing.models import Option
    _모델(session, 'U-SKU-12')
    _옵션(session, 'U-SKU-12', 'SKU-12-A')
    session.query(Option).filter_by(canonical_sku='SKU-12-A').update({'article_no': '   '})
    session.commit()

    out = counts_batch(session, ['U-SKU-12'], {'U-SKU-12': 1})
    assert out['U-SKU-12']['article_no'] == 0
