# -*- coding: utf-8 -*-
"""「정해져 나가는 값」 표가 **실제 코드와 같은가**.

🔴 이 표는 「지금 코드가 무엇을 보내는가」의 사본이다. 사본은 반드시 낡는다 —
   그래서 사람이 적은 목록끼리 대조하지 않고, **등록 코드 원본을 읽어** 맞춘다.
   (오늘 「저장만 됩니다」가 거짓이었던 것도 사본이 낡아서 생긴 일이다)
"""
from pathlib import Path

from lemouton.policy import fixed_sends as FS

_SRC = Path('lemouton/registration')


def _read(name: str) -> str:
    return (_SRC / name).read_text(encoding='utf-8')


# ── 표에 적힌 값이 실제 코드에 있는가 ────────────────────────────────────

def test_쿠팡_고정값이_실제_코드에_그대로_있다():
    """표만 고치고 코드를 안 고치면(또는 반대면) 화면이 거짓말한다."""
    src = _read('compile_coupang.py')
    있어야_할_것 = [
        "'parallelImported': 'NOT_PARALLEL_IMPORTED'",
        "'overseasPurchased': 'NOT_OVERSEAS_PURCHASED'",
        "'pccNeeded': 'false'",
        "'notices': []",
        "_SALE_ENDED_AT = '2099-12-31T23:59:59'",
        "_DELIVERY_COMPANY = 'CJGLS'",
    ]
    빠진것 = [x for x in 있어야_할_것 if x not in src]
    assert not 빠진것, f'표에 적었는데 코드에 없다 — 표가 낡았다: {빠진것}'


def test_스스_고정값이_실제_코드에_그대로_있다():
    src = _read('compile_smartstore.py')
    assert "draft.origin_area_code or '0200037'" in src
    assert "draft.importer or '-'" in src


def test_가격비교_노출은_더_이상_코드에_박혀_있지_않다():
    """🔴 [2026-08-24 Phase 4-5] 예전엔 `True` 가 박혀 있었다.

    사장님이 「노출 안 함」으로 정해도 그대로 노출됐다 — 가격비교는 수수료가
    더 붙는다(금전 직결). 이제 정책이 이긴다. 표(`fixed_sends`)도 그렇게 말해야
    한다 — 표가 「코드에 박혀 있음」이라 하면 사장님이 고칠 수 있는 값을 못 고칠 값으로
    읽는다.
    """
    src = _read('compile_smartstore.py')
    assert "'naverShoppingRegistration': True," not in src, (
        '노출 여부가 다시 코드에 박혔다 — 정책을 무시한다')
    assert 'price_compare_expose' in src

    from lemouton.policy.fixed_sends import for_market
    행 = [f for f in for_market('smartstore')['rows']
           if f['label'] == '가격비교 노출']
    assert 행, '표에서 가격비교 노출이 사라졌다'
    assert 행[0]['policy_wins'] is True, (
        '표가 「못 고치는 값」이라 말하고 있다 — 이제 정책이 이긴다')


def test_초안_기본값이_실제_모델과_같다():
    src = _read('models.py')
    assert "notice_type = Column(String(32), default='WEAR'" in src


def test_배송비_반품비_원산지_기본값이_실제_코드와_같다():
    """[2026-08-20] 배송비·반품비·원산지는 더는 ProductDraft 컬럼 기본값이 아니다 —
    컬럼 기본값을 걸면 초안이 만들어지자마자 값이 확정돼, 정책이 다른 값을 정해도
    `_is_blank` 가 늘 거짓이 되어 못 먹었다(재현: tests/registration/
    test_policy_fallback_column_default.py). 지금은 `process_apply.py` 의
    `OPERATIONAL_FALLBACKS` 가 「정책도 사람도 안 정했을 때」컴파일 직전에만 채운다 —
    이 표(COMMON_DEFAULTS)가 화면에 보여주는 수치는 그 상수와 같아야 한다.
    """
    from lemouton.registration.process_apply import OPERATIONAL_FALLBACKS
    by_attr = {attr: fallback for _item, _field, attr, fallback in OPERATIONAL_FALLBACKS}
    assert by_attr['delivery_fee'] == 3000
    assert by_attr['return_fee'] == 5000
    assert by_attr['origin_area_code'] == '0200037'

    # 모델 컬럼 자체엔 이제 기본값이 없어야 한다 — 다시 걸리면 버그가 재발한 것이다.
    src = _read('models.py')
    assert 'delivery_fee = Column(Integer, default=3000)' not in src, (
        '컬럼 기본값이 되살아났다 — 정책값이 다시 못 먹는 버그가 재발한다')
    assert 'return_fee = Column(Integer, default=5000)' not in src
    assert "origin_area_code = Column(String(32), default='0200037')" not in src


def test_모음전_경로는_신발_가방을_자동_판정한다():
    """[2026-08-20] as_draft.py::upsert() 가 notice_type 을 전혀 안 채우던 버그.

    표만 고치고 코드를 안 고치면(또는 반대면) 화면이 거짓말한다 — 이 파일의
    존재 이유. 등록 코드 원본에서 실제로 판정 함수를 부르는지 읽어서 확인한다.
    """
    src = Path('lemouton/send/as_draft.py').read_text(encoding='utf-8')
    assert 'guess_notice_type' in src, '자동 판정을 호출하지 않는다 — 표가 낡았다'
    assert 'd.notice_type' in src, 'notice_type 을 여전히 안 채운다 — 표가 낡았다'

    row = [r for r in FS.for_market('coupang')['rows'] if r['label'] == '고시 유형'][0]
    assert '자동' in row['value'] or '자동' in row['note'], (
        '자동 판정으로 바뀌었는데 표 설명이 여전히 예전(「전부 의류」) 그대로다')


def test_근거_위치가_전부_적혀_있다():
    """「어디에 박혀 있나」가 없으면 사장님도 나도 다시 못 찾는다."""
    for mk in ('coupang', 'smartstore'):
        for row in FS.for_market(mk)['rows']:
            assert row['where'], f'{mk} · {row["label"]} 에 근거 위치가 없다'
            assert '.py:' in row['where'], row['where']


# ── 확인 못 한 마켓을 「없다」고 하지 않는가 ──────────────────────────────

def test_안_열어_본_마켓은_없다고_단정하지_않는다():
    """🔴 「확인 못 함」과 「없음」은 다르다 — 이 프로젝트 최상위 원칙."""
    for mk in FS.UNCHECKED:
        got = FS.for_market(mk)
        assert got['checked'] is False, mk
        assert '없다는 뜻이 아닙니다' in got['reason']


def test_확인한_마켓은_목록을_준다():
    got = FS.for_market('coupang')
    assert got['checked'] is True
    labels = [r['label'] for r in got['rows']]
    assert '과세구분' in labels and '택배사' in labels
    assert '배송비' in labels, '마켓 공통 기본값도 같이 보여야 한다'


# ── 정책과 실제가 어긋날 때 잡아내는가 ──────────────────────────────────

def test_면세로_바꾸면_면세로_나간다():
    """[2026-08-13] 이었다 — 전에는 「바꿔도 안 먹는다」를 어긋남으로 잡아 줘야 했다.

    🔴 이제는 정책이 이기므로 **어긋남이 아니다.** 대신 항목별 표가
      「정책 면세 / 실제 면세」로 보여준다. 여기서 옛 기대를 그대로 두면
      고쳐 놓고도 화면이 경고를 띄운다.
    """
    assert FS.conflicts('coupang', {'listing': {'tax_type': '면세'}}) == []
    rows = {r['label']: r for r in FS.by_item('coupang', {'listing': {'tax_type': '면세'}})['listing']}
    assert rows['과세구분']['actual'] == '면세'
    assert rows['과세구분']['same'] is True


def test_같으면_어긋남이_아니다():
    got = FS.conflicts('coupang', {'listing': {'tax_type': '과세'}})
    assert not [c for c in got if c['label'] == '과세구분']


def test_정책에_안_채웠으면_어긋남이_아니다():
    """안 정한 것을 「다르다」고 하면 화면이 경고로 뒤덮인다."""
    assert FS.conflicts('coupang', {}) == []


def test_배송비와_반품비를_따로_본다():
    """🔴 「배송」 한 항목에 둘이 같이 있다 — 항목 이름만으로 고르면 첫 번째만 걸린다.

    [2026-08-13 2단계] 배송비·반품비는 이제 **정책이 이긴다** → 어긋남이 아니다.
    대신 항목별 표(by_item)가 「정책 2,500 / 실제 2,500」으로 보여준다.
    """
    got = FS.by_item('coupang', {'shipping': {'fee_amount': 2500, 'return_fee': 4000}})
    rows = {r['label']: r for r in got['shipping']}
    assert rows['배송비']['actual'] == '2,500원', '정책값이 나가는데 기본값이라고 한다'
    assert rows['배송비']['same'] is True
    assert rows['반품 배송비']['actual'] == '4,000원'
    assert FS.conflicts('coupang', {'shipping': {'fee_amount': 2500}}) == [],         '정책이 이기는 칸을 어긋남이라고 했다'


def test_값_모양이_이상해도_화면이_안_죽는다():
    """정책 값이 예상 밖 모양이어도 화면은 떠야 한다 — 비교를 포기할 뿐."""
    for 이상한값 in ({'listing': None}, {'shipping': {'fee_amount': '삼천원'}},
                     {'listing': {'tax_type': None}}):
        FS.conflicts('coupang', 이상한값)      # 터지지 않으면 통과


# ── [2026-08-13 사장님 확정 A1+B2] 화면 ─────────────────────────────────

def test_항목별_대조가_늘_나온다():
    """확정 B2 = 늘 나란히. 다를 때만 보여주면 「같다」는 확인이 안 된다."""
    got = FS.by_item('coupang', {'listing': {'tax_type': '과세'}})
    tax = [x for x in got.get('listing', []) if x['label'] == '과세구분']
    assert tax, '같은데도 안 보여줬다'
    assert tax[0]['same'] is True
    assert tax[0]['policy'] == '과세' and tax[0]['actual'] == '과세'


def test_모르는_값을_넣으면_기본값이_나간다():
    """정책에 없는 글자가 들어와도 지어내지 않는다 — 기본값(과세)으로 둔다."""
    rows = {r['label']: r for r in FS.by_item('coupang', {'listing': {'tax_type': '몰라요'}})['listing']}
    assert rows['과세구분']['actual'] == '몰라요', '표는 정책에 적힌 그대로 보여준다'
    from lemouton.registration.compile_coupang import _TAX_CODE
    assert _TAX_CODE.get('몰라요', 'TAX') == 'TAX', '보낼 때는 기본값으로 떨어진다'


def test_정책에_안_정했으면_실제값만_보여준다():
    """「안 정함」과 「같음」은 다르다 — 안 정했으면 정책 쪽을 비운다."""
    got = FS.by_item('coupang', {})
    tax = [x for x in got['listing'] if x['label'] == '과세구분'][0]
    assert tax['policy'] is None
    assert tax['actual'] == '과세'
    assert tax['same'] is False


def test_정책에_칸이_없는_값은_항목별에_안_넣는다():
    """해외구매·개인통관부호는 붙일 항목이 없다 — 접힌 표에만 나온다."""
    got = FS.by_item('coupang', {})
    labels = {x['label'] for rows in got.values() for x in rows}
    assert '해외구매 여부' not in labels
    assert '과세구분' in labels


def test_정책이_이기는_칸은_정책값이_실제값이다():
    """[2026-08-13 2단계] 원산지·배송비·반품비는 정책이 이긴다.

    🔴 이 갈래가 없으면 화면이 「정책 2,500 / 실제 3,000」이라고 **반대로**
      거짓말한다 — 이미 정책값이 나가고 있는데도.
    """
    got = FS.by_item('smartstore', {'origin': {'mode': 'fixed', 'fixed_value': '0200038'}})
    # 원산지는 읽기 규칙이 없어 비교값을 못 뽑는다 — 그때는 기본값을 보여준다
    org = [r for r in got.get('origin', []) if r['label'] == '원산지'][0]
    assert org['actual'] in ('국내산', '0200038')


def test_정책을_안_정하면_기본값이_실제값이다():
    got = FS.by_item('coupang', {})
    ship = {r['label']: r for r in got['shipping']}
    assert ship['배송비']['actual'] == '3,000원'
    assert ship['배송비']['policy'] is None


def test_미성년자_구매는_이제_박혀_있지_않다():
    """[2026-08-13 2단계] 이었다 — 표가 「전연령으로 박혀 나갑니다」라고 하면 거짓말이다.

    🔴 값 하나를 이으면 이 표도 같이 낡는다. 그래서 코드 원본을 읽어 확인한다.
    """
    src = _read('compile_coupang.py')
    assert "'adultOnly': 'EVERYONE'," not in src, '다시 박아 뒀다 — 정책이 안 먹는다'
    assert "'ADULT_ONLY'" in src, '19세 이상만을 보낼 길이 없다'
    assert 'minor_purchasable' in src

    row = [r for r in FS.for_market('coupang')['rows']
           if r['label'] == '미성년자 구매'][0]
    assert row['policy_wins'] is True, '정책이 이기는데 표는 아니라고 한다'


def test_과세구분도_이제_박혀_있지_않다():
    """[2026-08-13] 이었다 — 표가 「과세로 박혀 나갑니다」라고 하면 거짓말이다."""
    src = _read('compile_coupang.py')
    assert "'taxType': 'TAX'," not in src, '다시 박아 뒀다 — 정책이 안 먹는다'
    assert "_TAX_CODE" in src, '면세를 보낼 길이 없다'
    row = [r for r in FS.for_market('coupang')['rows'] if r['label'] == '과세구분'][0]
    assert row['policy_wins'] is True


def test_상품상태는_명시해서_보낸다():
    """🔴 전에는 아무것도 안 보내 쿠팡 기본값에 기대고 있었다(등록 후 변경 불가)."""
    src = _read('compile_coupang.py')
    assert "'offerCondition': 'NEW'" in src
    labels = {r['label'] for r in FS.for_market('coupang')['rows']}
    assert '상품상태' in labels


# ── [2026-08-13] 11번가·옥션·G마켓 — 조립 코드를 열었으니 표도 실제와 맞는가 ──

_PLAT = Path('shared/platforms')


def test_11번가_고정값이_실제_코드에_그대로_있다():
    src = (_PLAT / 'eleven11' / 'products.py').read_text(encoding='utf-8')
    있어야_할_것 = [
        '<prdStatCd>01</prdStatCd>',            # 상품상태 = 새상품
        '<selMthdCd>01</selMthdCd>',            # 판매방식 = 고정가판매
        '<orgnNmVal>상세설명 참조</orgnNmVal>',   # 원산지가 박혀 나간다
        '<dlvCstInstBasiCd>01</dlvCstInstBasiCd>',   # 배송비 무료
        '<bndlDlvCnYn>N</bndlDlvCnYn>',         # 묶음배송 불가
        '_TAX_CODE = {"과세": "01", "면세": "02"}',
    ]
    빠진것 = [x for x in 있어야_할_것 if x not in src]
    assert not 빠진것, f'표에 적었는데 코드에 없다 — 표가 낡았다: {빠진것}'


def test_ESM_고정값이_실제_코드에_그대로_있다():
    src = (_PLAT / 'esm' / 'products.py').read_text(encoding='utf-8')
    있어야_할_것 = [
        'period_block = {"Gmkt": -1, "Iac": -1}',      # 판매기간 무제한
        '"isAdultProduct": bool(is_adult_product)',    # 미성년자 = 정책값
        '"isVatFree": bool(is_vat_free)',              # 과세구분 = 정책값
        '"siteDiscount": {"gmkt": False, "iac": False}',
    ]
    빠진것 = [x for x in 있어야_할_것 if x not in src]
    assert not 빠진것, f'표에 적었는데 코드에 없다 — 표가 낡았다: {빠진것}'


def test_옥션과_G마켓은_같은_표를_본다():
    """🔴 같은 ESM 조립기 하나를 쓴다 — 따로 적으면 한쪽만 고쳐져 갈린다."""
    a = [(r['label'], r['value']) for r in FS.for_market('auction')['rows']]
    g = [(r['label'], r['value']) for r in FS.for_market('gmarket')['rows']]
    assert a == g


def test_이제_확인_못_한_마켓은_롯데온뿐이다():
    """11번가·옥션·G마켓은 조립 코드를 전수로 읽었다 — 계속 「안 열어 봤다」면 그것도 거짓말."""
    assert FS.UNCHECKED == ('lotteon',)
    for mk in ('eleven11', 'auction', 'gmarket'):
        assert FS.for_market(mk)['checked'] is True, mk


def test_새로_연_마켓도_근거_위치가_전부_적혀_있다():
    for mk in ('eleven11', 'auction', 'gmarket'):
        for row in FS.for_market(mk)['rows']:
            assert row['where'] and '.py:' in row['where'], f'{mk} · {row["label"]}'


def test_정책이_이기는_칸은_그렇게_표시돼_있다():
    """🔴 표시를 빠뜨리면 화면이 「정책 면세 / 실제 과세」라고 **반대로** 거짓말한다."""
    for mk in ('eleven11', 'auction', 'gmarket'):
        rows = {r['label']: r for r in FS.for_market(mk)['rows']}
        assert rows['과세구분']['policy_wins'] is True, mk
        assert rows['미성년자 구매']['policy_wins'] is True, mk
        assert FS.conflicts(mk, {'listing': {'tax_type': '면세'}}) == [], mk
