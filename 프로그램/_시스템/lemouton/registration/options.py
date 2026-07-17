# -*- coding: utf-8 -*-
"""옵션(색상×사이즈) → 마켓별 옵션 구조.

스스 공식 규격 (marketplace_api_map.json → smartstore.create-product-product):
    optionCombinationGroupNames: {optionGroupName1..4}
    optionCombinations: [{optionName1..4, stockQuantity, price, usable, sellerManagerCode}]
    · price 는 '옵션가'(추가금)지 절대 판매가가 아니다.
    · 조합형 옵션 그룹은 최대 3개.
    · optionInfo: 표준형·단독형·조합형·직접입력형 중 최소 한 개는 입력해야 한다.
      서로 배타적일 뿐 조합형이 금지된 게 아니다 — 우리는 조합형을 쓴다.

쿠팡은 옵션가 개념이 없어 items[] 마다 절대가(salePrice)를 싣는다.

[재고 규칙 — 프로젝트 원칙]
    stock > 0  → 등록
    stock == 0 → 품절 → 등록 제외 (설계서 §7-9)
    stock < 0  → '확인불가' → 등록 제외. 999 같은 폴백을 넣지 않는다 (오버셀 방지).
    stock 없음 → '재고미입력' → 등록 제외. **0(품절)과 다른 상태다.**
      (집 관례: lemouton/sources/lap_report.py:43 — 0=품절 / -1=확인불가 / None=미크롤)
      `or 0` 로 뭉개면 배선 버그(예: 폼이 stock 대신 qty 를 보냄)가 '전부 품절' 이라는
      거짓 업무 메시지로 둔갑한다.

[제외는 보고한다 — 조용한 실패 금지]
    사용자가 폼에 직접 입력한 행이다. 9개 중 8개가 빠졌는데 '성공' 이라고 답하면 안 된다.
    두 빌더 모두 excluded 목록을 함께 돌려주고, 상위(컴파일러)가 사용자에게 보여준다.

[입력 경계]
    opts 는 ProductDraft.options_json — 결국 UI 폼에서 온 자유형 JSON 이다.
    타입을 믿지 않는다. 숫자 사이즈(250), 문자 재고('3.0') 가 정상 입력이다.
    AttributeError·bare ValueError 는 상위 except 를 그냥 통과해 500 이 되므로
    전부 OptionError 하위로 바꿔서 던진다.
"""
# [2026-07-17] 대량등록 Phase 1A Task 4

import math

_SIZE_GROUP = '사이즈'
_COLOR_GROUP = '색상'

# 알파 사이즈 순서.
# ★ 이 배열 순서가 곧 구매자가 보는 드롭다운 순서다 — optionCombinationSortType 을
#   보내지 않으면 스스 기본값이 등록순(CREATE) 이기 때문. 문자 정렬에 맡기면
#   ['XL','S','M','L','XS'] 가 L,M,S,XL,XS 로 나온다 (의류에서 매번 발생).
_ALPHA_SIZE_ORDER = ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL')
_ALPHA_SIZE_RANK = {name: i for i, name in enumerate(_ALPHA_SIZE_ORDER)}

# 제외 사유 (사용자에게 그대로 보여줄 말)
REASON_SOLD_OUT = '품절'
REASON_UNKNOWN = '확인불가'
REASON_NO_STOCK = '재고미입력'


class OptionError(ValueError):
    """옵션 처리 실패 — 상위(컴파일러)가 이 하나만 잡으면 된다."""


class NoSellableOption(OptionError):
    """판매 가능한 옵션이 하나도 없음. 빈 옵션 목록을 조용히 보내지 않는다."""


class OptionValueInvalid(OptionError):
    """옵션 입력값이 잘못됨. 추측해서 고치지 않고 실패시킨다 (폴백 금지)."""


def _text(raw) -> str:
    """자유형 JSON 입력값 → 문자열. int 250 · None 이 와도 터지지 않게.

    AttributeError 는 ValueError 가 아니라서 상위 핸들러를 그냥 통과해 500 이 된다.
    None 이 문자열 'None' 으로 둔갑하지 않게 먼저 걸러낸다.
    """
    if raw is None:
        return ''
    return str(raw).strip()


def _num(raw, field: str):
    """자유형 JSON 숫자 → int. 미입력(None·빈칸)은 None.

    폼·엑셀 붙여넣기·JS toFixed 는 3, '3', '3.0', 3.0 을 다 보낸다. 전부 3 이다.
    읽을 수 없는 값을 조용히 0 으로 만들지 않는다 (재고 0 = 품절 = 오판).
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # 파이썬에서 True == 1 이라 그냥 두면 재고 1개로 등록된다.
        raise OptionValueInvalid(f'{field} 값에 참/거짓이 왔습니다: {raw!r}')
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        f = raw
    else:
        s = _text(raw)
        if not s:
            return None
        try:
            f = float(s.replace(',', ''))
        except ValueError:
            raise OptionValueInvalid(
                f'{field} 값을 숫자로 읽을 수 없습니다: {raw!r}') from None
    if not math.isfinite(f):
        # nan·inf. int(nan)=ValueError, int(inf)=OverflowError 라 둘 다 새어나간다.
        raise OptionValueInvalid(f'{field} 값이 숫자가 아닙니다: {raw!r}')
    if f != int(f):
        raise OptionValueInvalid(f'{field} 값은 정수여야 합니다: {raw!r}')
    return int(f)


def _size_key(size):
    """사이즈 정렬 키 — 숫자 > 알파(XS→XXXL) > 나머지(문자순).

    구매자 드롭다운 순서가 되므로 정렬이 곧 UX 다.

    Raises:
        OptionValueInvalid: nan·inf 사이즈
    """
    s = _text(size)
    try:
        num = float(s.replace(',', ''))
    except ValueError:
        pass
    else:
        if not math.isfinite(num):
            # 'nan' 은 비교가 전부 False 라 정렬을 조용히 뒤섞는다.
            raise OptionValueInvalid(f'사이즈 값이 숫자가 아닙니다: {size!r}')
        return (0, num, '')
    rank = _ALPHA_SIZE_RANK.get(s.upper())
    if rank is not None:
        return (1, float(rank), '')
    return (2, 0.0, s)


def _normalize(opts):
    """자유형 입력 → 검증된 행 목록. 값이 이상하면 여기서 전부 실패시킨다."""
    rows = []
    seen = {}
    for i, o in enumerate(opts):
        color = _text(o.get('color'))
        size = _text(o.get('size'))
        if not color or not size:
            # 스스 optionName1/2 · 쿠팡 attributeValueName 전부 필수. 빈 값을 실어보내면
            # 마켓이 불투명한 400 을 준다. 단일축 상품은 별도 설계 대상 (여기선 범위 밖).
            raise OptionValueInvalid(
                f'{i + 1}번째 옵션에 색상·사이즈가 비어 있습니다 (둘 다 필수). '
                f'색상={color!r} 사이즈={size!r}')
        _size_key(size)  # 정렬 시점 말고 여기서 먼저 터지게 (nan 조기 차단)

        key = (color, size)
        if key in seen:
            # 재고를 합치지 않는다 — 사용자가 표현한 적 없는 의도를 지어내는 셈이다.
            raise OptionValueInvalid(
                f'같은 옵션이 두 번 들어왔습니다: {color}/{size} '
                f'({seen[key] + 1}번째 · {i + 1}번째). 어느 쪽이 맞는지는 사용자만 압니다.')
        seen[key] = i

        extra = _num(o.get('extra_price'), '옵션 추가금')
        rows.append({
            'color': color,
            'size': size,
            'stock': _num(o.get('stock'), '재고'),
            'extra_price': 0 if extra is None else extra,
            'sku': _text(o.get('sku')),
        })
    return rows


def _split(rows):
    """행 목록 → (판매가능 정렬본, 제외 목록).

    Raises:
        NoSellableOption: 판매 가능한 옵션 0개
    """
    sellable, excluded = [], []
    for r in rows:
        stock = r['stock']
        if stock is None:
            reason = REASON_NO_STOCK
        elif stock > 0:
            sellable.append(r)
            continue
        elif stock == 0:
            reason = REASON_SOLD_OUT
        else:
            reason = REASON_UNKNOWN
        excluded.append({'color': r['color'], 'size': r['size'],
                         'stock': stock, 'reason': reason})

    if not sellable:
        # 사유를 지어내지 않는다 — 실제로 무엇 때문에 비었는지 그대로 센다.
        if not excluded:
            raise NoSellableOption('판매 가능한 옵션이 없습니다 — 옵션 목록이 비어 있습니다.')
        counts = {}
        for e in excluded:
            counts[e['reason']] = counts.get(e['reason'], 0) + 1
        detail = ', '.join(f'{k} {v}개' for k, v in counts.items())
        raise NoSellableOption(f'판매 가능한 옵션이 없습니다 ({detail}).')

    sellable.sort(key=lambda r: (r['color'], _size_key(r['size'])))
    return sellable, excluded


def build_smartstore_options(opts):
    """옵션 목록 → (optionCombinationGroupNames, optionCombinations, excluded).

    excluded: [{'color','size','stock','reason'}] — 등록에서 빠진 행.
              상위가 사용자에게 보여줘야 한다 (조용한 실패 금지).

    Raises:
        OptionValueInvalid: 입력값이 잘못됨 (읽을 수 없는 재고·중복 옵션·빈 색상 …)
        NoSellableOption: 판매 가능한 옵션 0개
        (둘 다 OptionError 하위 — 상위에서 OptionError 하나만 잡으면 된다)
    """
    rows, excluded = _split(_normalize(opts))
    groups = {'optionGroupName1': _COLOR_GROUP, 'optionGroupName2': _SIZE_GROUP}
    combos = []
    for o in rows:
        combo = {
            'optionName1': o['color'],
            'optionName2': o['size'],
            'stockQuantity': o['stock'],
            'price': o['extra_price'],
            'usable': True,
        }
        if o['sku']:
            combo['sellerManagerCode'] = o['sku']
        combos.append(combo)
    return groups, combos, excluded


def build_coupang_items(opts, *, sale_price, image_url):
    """옵션 목록 → (쿠팡 items[], excluded). 옵션 추가금은 절대가에 가산한다.

    Raises:
        OptionValueInvalid: 입력값이 잘못됨
        NoSellableOption: 판매 가능한 옵션 0개
    """
    base = _num(sale_price, '판매가')
    if base is None:
        raise OptionValueInvalid('판매가가 없습니다.')
    rows, excluded = _split(_normalize(opts))
    items = []
    for o in rows:
        price = base + o['extra_price']
        images = ([{'imageOrder': 0, 'imageType': 'REPRESENTATION',
                    'vendorPath': image_url}]
                  if image_url else [])
        items.append({
            'itemName': f"{o['color']}-{o['size']}",
            'originalPrice': price,
            'salePrice': price,
            'maximumBuyCount': o['stock'],
            'externalVendorSku': o['sku'],
            'images': images,
            'attributes': [
                {'attributeTypeName': '색상', 'attributeValueName': o['color']},
                {'attributeTypeName': '사이즈', 'attributeValueName': o['size']},
            ],
        })
    return items, excluded
