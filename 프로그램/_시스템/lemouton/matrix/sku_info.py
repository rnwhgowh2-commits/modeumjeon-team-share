# -*- coding: utf-8 -*-
"""SKU 하나하나의 번호 세 가지 — 품번 · 바코드 · GTIN (단일 진실 원천).

무엇을 하는 곳인가
  옵션(SKU) 한 줄마다 붙는 세 가지 번호를 **읽고 · 세고 · 저장하는** 규칙이 여기 다 있다.
  · 화면 입력 격자 — 「옵션 조합 생성 및 수정」 창 (`webapp/static/option_url_modal.js`)
  · 목록의 「SKU 정보 상태」 칸 — `webapp/templates/optgen/index.html`
  · 두 화면이 쓰는 창구 — `webapp/routes/optgen_sku.py`
  세 곳이 각자 판정을 적으면 같은 SKU 가 화면마다 다른 상태로 보인다. 그래서 판정은
  이 파일 하나에만 둔다.

🔴 **NULL 은 「아직 안 적음」이다.** 빈 문자열이 아니다.
   저장할 때 공란은 반드시 `None` 으로 바꿔 넣는다. 빈 문자열을 넣으면
   「적었다 지운 것」과 「아직 안 적은 것」이 같은 모습이 되고, 진척(「품번 12/15」)이
   안 채운 것을 채운 걸로 센다. 반대로 셀 때는 `NULL` 과 공백뿐인 값을 **둘 다**
   「안 적음」으로 센다 — 옛 경로가 남긴 빈 문자열이 있어도 숫자가 안 틀리게.

🔴 **못 세는 것은 0 이 아니라 「모른다」(`None`)다.**
   SKU 가 0개인 묶음은 분모가 없어 「0/0 다 됐다」도 「0/0 못 했다」도 거짓이다.
   칸 자체가 아직 없는 낡은 DB 도 마찬가지다 — 그때는 0 이 아니라 `None` 을 낸다.
   (`source_url_stats.mapping_coverage` 가 같은 규칙을 맵핑에 쓴다.)

🔴 **바코드·GTIN 은 겹치면 안 된다.** 두 SKU 가 같은 번호를 달고 마켓에 나가면
   마켓 쪽에서 두 상품이 한 상품으로 묶여 재고·주문이 뒤섞인다. 되돌리려면 마켓에
   올라간 상품을 손으로 고쳐야 한다 — 그래서 저장 창구에서 막는다.
   품번(`article_no`)은 겹침을 막지 않는다. 브랜드가 색상 여러 개에 같은 품번을
   매기는 일이 실제로 있고, 그건 우리가 판정할 사실이 아니다.

🔴 **형식이 틀린 값은 그 칸만 거부한다 — 저장 전체를 막지 않는다.**
   옵션이 20~30개인 격자에서 하나가 틀렸다고 전부 되돌리면, 사장님이 한참 채운 것이
   통째로 날아간다. 그렇다고 틀린 값을 조용히 넣으면 「적었으니 됐다」가 되어
   라벨 인쇄·마켓 전송에서 그제야 터진다. 그래서 **맞는 칸은 저장하고, 틀린 칸은
   왜 안 됐는지 문장으로 돌려준다**(`save()` 의 `rejected`).
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

#: 세 가지 번호 — **순서가 곧 화면 순서**다(품번 · 바코드 · GTIN).
#: 화면에서 순서를 또 적지 않도록 여기서 한 번만 정한다.
FIELDS: tuple[str, ...] = ('article_no', 'barcode', 'gtin')

#: 사람이 읽는 이름. 화면·에러 문구가 전부 이걸 쓴다.
LABELS: dict[str, str] = {
    'article_no': '품번',
    'barcode': '바코드',
    'gtin': 'GTIN',
}

#: 겹치면 안 되는 것 — 왜인지는 이 파일 맨 위에 적혀 있다.
UNIQUE_FIELDS: frozenset[str] = frozenset({'barcode', 'gtin'})


def normalize(raw) -> str | None:
    """화면에서 온 값 → 저장할 값. **공란은 `None`**(아직 안 적음).

    🔴 여기서 `'-'` 같은 대신값을 넣지 않는다. `shared/sku_format.clean_article_no`
       는 모델 품번용이라 빈 값을 `'-'` 로 바꾸는데, 그 규칙을 여기 가져오면
       「안 적음」이 `'-'` 라는 **적은 값**으로 둔갑해 진척이 전부 채워진 것으로 보인다.
    """
    if raw is None:
        return None
    t = str(raw).strip()
    return t or None


def validate(field: str, value: str | None) -> str | None:
    """형식 검사 — 맞으면 `None`, 틀리면 **왜 안 되는지 한국어 한 문장**.

    공란(`None`)은 언제나 통과다. 「아직 안 적음」은 잘못이 아니다.
    """
    if value is None:
        return None
    from shared import sku_format

    if field == 'article_no':
        if len(value) > 64:
            return '품번이 너무 깁니다 (64자까지)'
        if not sku_format.is_valid_article_no(value):
            if sku_format.has_korean(value):
                return '품번에 한글은 쓸 수 없습니다 (영문·숫자·- ·_ 만)'
            if value.startswith('SKU-'):
                return '품번을 SKU 번호 형식으로 적을 수 없습니다'
            return '품번은 영문·숫자와 - ·_ 만 쓸 수 있습니다'
        return None

    if field == 'barcode':
        if not value.isdigit():
            return '바코드는 숫자만 적습니다 (EAN-13, 13자리)'
        if len(value) != 13:
            return f'바코드는 13자리여야 합니다 (지금 {len(value)}자리)'
        if not sku_format.is_valid_barcode(value):
            return '바코드 검사숫자가 안 맞습니다 — 한 자리를 잘못 옮겨 적었을 수 있습니다'
        return None

    if field == 'gtin':
        if not value.isdigit():
            return 'GTIN 은 숫자만 적습니다 (8·12·13·14자리)'
        if len(value) not in (8, 12, 13, 14):
            return f'GTIN 은 8·12·13·14자리여야 합니다 (지금 {len(value)}자리)'
        if not sku_format.is_valid_gtin(value):
            return 'GTIN 검사숫자가 안 맞습니다 — 한 자리를 잘못 옮겨 적었을 수 있습니다'
        # 🔴 막지는 않고 알려만 준다 — 우리가 만든 번호(200~)는 가게 안에서만 쓰는
        #    번호라 세계에서 유일하지 않다. 그래도 브랜드가 준 값이 그 대역일 수도
        #    있으므로 판단은 사장님 몫이다. 판정은 `is_internal_barcode` 한 곳뿐이다.
        return None

    return f'모르는 칸입니다: {field}'


def warn(field: str, value: str | None) -> str | None:
    """막지는 않지만 알려야 할 것 — 맞으면 `None`, 아니면 한국어 한 문장.

    지금은 하나뿐이다: **우리가 만든 번호를 GTIN 칸에 적은 경우.**
    형식은 멀쩡하지만 그 번호는 세계에서 유일하지 않아, 마켓에 「표준상품코드」로
    보내면 남의 가게 물건과 같은 번호가 될 수 있다.
    """
    if value is None or field != 'gtin':
        return None
    from shared import sku_format
    if sku_format.is_internal_barcode(value):
        return ('이 번호는 가게 안에서만 쓰는 대역(200~299 등)입니다 — '
                '마켓에 표준상품코드로 보내면 다른 가게 물건과 겹칠 수 있습니다')
    return None


# ────────────────────────────────────────────────────────────────
#  세기 — 목록의 「SKU 정보 상태」 칸
# ────────────────────────────────────────────────────────────────

def _dedup(codes) -> list[str]:
    """중복·빈 값을 걷어내되 넣어 준 순서를 지킨다 (`source_url_stats._dedup` 과 같은 뜻)."""
    out, seen = [], set()
    for c in codes or ():
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _blank(total: int) -> dict:
    """못 잰 줄 한 벌 — 셋 다 「모른다」."""
    return {'total': int(total or 0),
            'article_no': None, 'barcode': None, 'gtin': None}


def counts_batch(session, codes: list[str],
                 sku_total: dict[str, int]) -> dict[str, dict]:
    """묶음별 「셋을 각각 몇 개나 채웠나」.

    반환: `{model_code: {'total': M, 'article_no': n|None,
                         'barcode': n|None, 'gtin': n|None}}`

    · `total` 은 **호출자가 이미 센 SKU 수**를 그대로 쓴다. 여기서 다시 세면
      화면의 「SKU 구성수」와 이 칸의 분모가 갈릴 수 있다(같은 사실을 두 곳에서
      만들지 않는다 — `source_url_stats.mapping_coverage` 와 같은 이유).

    · 🔴 `None` 을 내는 자리는 둘이다. **0 이 아니다.**
        ① SKU 가 0개 — 분모가 없어 잴 대상이 없다.
        ② 칸이 아직 없는 낡은 DB — 조회 자체가 실패한다. 이때 0 으로 적으면
          화면이 「하나도 안 채웠다」고 **거짓말**을 한다(사실은 모르는 것이다).

    조회는 묶음당 1개다 — 줄 수가 3이든 300이든 같다.
    """
    from sqlalchemy import and_, case, func

    from lemouton.sourcing.models import Option

    codes = _dedup(codes)
    sku_total = sku_total or {}
    out: dict[str, dict] = {c: _blank(sku_total.get(c, 0)) for c in codes}
    if not codes:
        return out

    def _filled(col):
        """「적혀 있다」 = NULL 도 아니고 공백뿐도 아니다."""
        return func.count(case(
            (and_(col.isnot(None), func.trim(col) != ''), 1)))

    rows = []
    try:
        for 묶음 in _chunked(codes):
            rows += (session.query(Option.model_code,
                                   _filled(Option.article_no),
                                   _filled(Option.barcode),
                                   _filled(Option.gtin))
                     .filter(Option.model_code.in_(묶음))
                     .group_by(Option.model_code)
                     .all())
    except Exception as e:
        # 🔴 조용히 0 으로 떨어뜨리지 않는다. 칸이 아직 없는 DB 에서 0 을 보이면
        #    사장님은 「다 지워졌다」로 읽는다. 「모른다」로 두고 로그에 까닭을 남긴다.
        _log.warning('SKU 정보 상태를 세지 못했다 (칸이 아직 없거나 조회 실패) — %s', e)
        return out

    for code, a, b, g in rows:
        if code not in out:
            continue
        st = out[code]
        if st['total'] <= 0:
            continue                      # 분모가 없다 — 「모른다」 그대로 둔다
        st['article_no'] = min(int(a or 0), st['total'])
        st['barcode'] = min(int(b or 0), st['total'])
        st['gtin'] = min(int(g or 0), st['total'])
    return out


def _chunked(codes: list[str]):
    """IN 절에 한 번에 넣어도 되는 크기로 자른다.

    🔴 자르는 크기는 `matrix/readiness._CHUNK` 한 곳에서만 정한다 — 여기 숫자를 또
       적으면 한쪽만 고쳐졌을 때 이 화면만 라이브에서 터진다. **부를 때마다** 읽는다.
       잘라도 답이 안 변하는 이유: 아래 조회가 `model_code` 로 거르고 같은 열쇠로
       묶어서, 한 묶음의 줄이 두 덩이에 나뉠 수 없다.
    """
    from lemouton.matrix.readiness import _CHUNK

    for i in range(0, len(codes), _CHUNK):
        yield codes[i:i + _CHUNK]


# ────────────────────────────────────────────────────────────────
#  읽기 — 격자 · 호버 카드
# ────────────────────────────────────────────────────────────────

def rows_of(session, code: str) -> list[dict]:
    """묶음 하나의 SKU 줄 목록 — 격자와 호버 카드가 같이 쓴다.

    한 줄: `{sku, no, label, article_no, barcode, gtin, active}`
      · `no`    — 옵션번호(`display_no`). 없으면 `None` (지어내지 않는다)
      · `label` — 「블랙 260」처럼 축 값을 이어 붙인 이름. 사람이 줄을 알아보는 유일한 단서다.
      · 세 번호는 **안 적었으면 `None`** 이다. 빈 문자열로 바꾸지 않는다 —
        화면이 「—(안 적음)」과 「빈 칸」을 갈라 보여줘야 한다.

    🔴 화면 순서는 `sort_order` → `canonical_sku` 다. 매트릭스 창이 옵션을 내리는
       순서(`webapp/routes/bundles.py:api_list_source_urls`)와 **같아야** 격자 줄과
       매트릭스 칸이 서로 어긋나 보이지 않는다.
    """
    from lemouton.sourcing.models import Option
    from lemouton.sourcing.option_combo import option_axis_values

    opts = (session.query(Option)
            .filter(Option.model_code == code)
            .order_by(Option.sort_order, Option.canonical_sku)
            .all())
    out = []
    for o in opts:
        vals = [str(v).strip() for v in option_axis_values(o)]
        out.append({
            'sku': o.canonical_sku,
            'no': o.display_no or None,
            'label': ' '.join(v for v in vals if v),
            'article_no': normalize(getattr(o, 'article_no', None)),
            'barcode': normalize(getattr(o, 'barcode', None)),
            'gtin': normalize(getattr(o, 'gtin', None)),
            'active': bool(getattr(o, 'is_active', True)),
        })
    return out


# ────────────────────────────────────────────────────────────────
#  저장
# ────────────────────────────────────────────────────────────────

def _dup_owner(session, field: str, values: dict[str, str]) -> dict[str, str]:
    """`{값: 이미_그_값을_쓰는_SKU}` — 저장 대상이 **아닌** SKU 중에서만 찾는다.

    🔴 **묶음 안에서만 보면 안 된다.** 마켓은 우리 묶음 구분을 모른다 —
       다른 매트릭스의 SKU 와 번호가 겹쳐도 똑같이 상품이 뒤섞인다.
       그래서 `options` 표 **전체**에서 찾는다.
    """
    from lemouton.sourcing.models import Option

    if not values:
        return {}
    col = getattr(Option, field)
    keep = set(values.keys())          # 지금 저장하려는 SKU 는 자기 값과 안 부딪힌다
    out: dict[str, str] = {}
    wanted = {v for v in values.values() if v}
    if not wanted:
        return out
    for sku, val in (session.query(Option.canonical_sku, col)
                     .filter(col.in_(sorted(wanted)))
                     .all()):
        if sku in keep:
            continue
        if val:
            out[str(val)] = sku
    return out


def save(session, code: str, items: list[dict]) -> dict:
    """격자에서 온 값을 저장한다 — **맞는 칸만 넣고, 틀린 칸은 까닭을 돌려준다.**

    Args:
        code: 묶음(model_code). 남의 묶음 SKU 를 이 창구로 고치지 못하게 거른다.
        items: `[{'sku': …, 'article_no': …, 'barcode': …, 'gtin': …}, …]`
            🔴 **없는 열쇠는 안 건드린다.** `{'sku': X, 'barcode': ''}` 는
               「바코드를 지운다」이고, `{'sku': X}` 는 「바코드는 이번에 안 건드린다」다.
               둘을 뭉개면 화면이 한 칸만 보내도 나머지 두 칸이 지워진다.

    Returns:
        `{'saved': 바뀐칸수, 'rejected': [{sku, field, value, reason}, …],
          'warnings': [{sku, field, value, reason}, …], 'unknown': [모르는 SKU, …]}`

    🔴 되돌리기(rollback)를 안 한다 — 맞는 칸은 넣는다. 까닭은 이 파일 맨 위에 있다.
       커밋은 부르는 쪽(창구)이 한다.
    """
    from lemouton.sourcing.models import Option

    items = items or []
    rejected: list[dict] = []
    warnings: list[dict] = []
    unknown: list[str] = []

    # ① 이 묶음의 SKU 만 상대한다. 남의 SKU 는 조용히 넘기지 않고 이름을 돌려준다.
    mine = {o.canonical_sku: o for o in
            session.query(Option).filter(Option.model_code == code).all()}

    # ② 값 정리 + 형식 검사. 여기서 걸린 칸은 아래 겹침 검사·저장에 아예 안 올린다.
    #    `pending[field][sku] = value` — 겹침 검사가 칸 단위로 한 번에 묻기 위함이다.
    pending: dict[str, dict[str, str | None]] = {f: {} for f in FIELDS}
    for it in items:
        sku = (it or {}).get('sku')
        sku = str(sku).strip() if sku else ''
        if not sku:
            continue
        if sku not in mine:
            unknown.append(sku)
            continue
        for f in FIELDS:
            if f not in (it or {}):
                continue                      # 안 보낸 칸 = 안 건드린다
            v = normalize(it.get(f))
            bad = validate(f, v)
            if bad:
                rejected.append({'sku': sku, 'field': f,
                                 'value': it.get(f), 'reason': bad})
                continue
            w = warn(f, v)
            if w:
                warnings.append({'sku': sku, 'field': f, 'value': v, 'reason': w})
            pending[f][sku] = v

    # ③ 겹침 검사 — 바코드·GTIN 만. 두 군데를 본다.
    #    (가) 이번에 보낸 것끼리 겹치나  (나) 이미 다른 SKU 가 쓰고 있나
    for f in FIELDS:
        if f not in UNIQUE_FIELDS:
            continue
        보낸값 = {s: v for s, v in pending[f].items() if v}
        # (가) 같은 값을 여러 SKU 에 적었다 — 먼저 온 줄만 남기고 나머지를 막는다.
        처음쓴줄: dict[str, str] = {}
        for sku in sorted(보낸값):
            v = 보낸값[sku]
            if v in 처음쓴줄:
                rejected.append({
                    'sku': sku, 'field': f, 'value': v,
                    'reason': (f'같은 {LABELS[f]} 를 {처음쓴줄[v]} 에도 적었습니다 — '
                               '번호가 겹치면 마켓에서 두 상품이 하나로 묶입니다')})
                pending[f].pop(sku, None)
            else:
                처음쓴줄[v] = sku
        # (나) 이미 다른 SKU 가 쓰는 번호
        임자 = _dup_owner(session, f, {s: v for s, v in pending[f].items() if v})
        for sku in list(pending[f]):
            v = pending[f][sku]
            if v and v in 임자:
                rejected.append({
                    'sku': sku, 'field': f, 'value': v,
                    'reason': (f'이 {LABELS[f]} 는 이미 {임자[v]} 가 쓰고 있습니다 — '
                               '번호가 겹치면 마켓에서 두 상품이 하나로 묶입니다')})
                pending[f].pop(sku, None)

    # ④ 쓰기 — 바뀐 것만. 같은 값을 다시 쓰면 「저장했다」 숫자가 부풀어
    #    사장님이 「고친 게 없는데 3칸 저장됐다」로 읽는다.
    saved = 0
    for f in FIELDS:
        for sku, v in pending[f].items():
            o = mine[sku]
            if getattr(o, f, None) != v:
                setattr(o, f, v)
                saved += 1

    if unknown:
        _log.warning('SKU 정보 저장 — 묶음 %s 에 없는 SKU %s개를 보내왔다: %s',
                     code, len(unknown), unknown[:5])
    return {'saved': saved, 'rejected': rejected,
            'warnings': warnings, 'unknown': unknown}


def gen_barcodes(session, skus: list[str]) -> dict[str, str]:
    """빈 바코드를 채울 번호를 SKU 개수만큼 만든다 — **저장은 안 한다.**

    🔴 만들기만 하고 저장은 평소 저장 길(`save`)로 보낸다. 만드는 자리에서 바로
       DB 에 넣으면 겹침 검사가 **두 곳**에 살게 되고, 한쪽만 고쳤을 때 겹친 번호가
       조용히 들어간다.

    🔴 「빈 것만」을 여기서 판정하지 않는다 — 화면이 지금 손에 든(아직 저장 안 한)
       값까지 알고 있어야 「든 값은 안 덮는다」를 지킬 수 있다. 서버는 화면이 준
       SKU 목록에 대해서만 번호를 만든다.

    만든 번호는 서로 겹치지 않고, `options.barcode` 에 이미 있는 번호와도 안 겹친다.
    """
    from shared.sku_format import gen_barcode

    from lemouton.sourcing.models import Option

    skus = [s for s in (skus or []) if s]
    if not skus:
        return {}
    쓰는중 = {str(v) for (v,) in
             session.query(Option.barcode).filter(Option.barcode.isnot(None)).all()
             if v}
    out: dict[str, str] = {}
    for sku in skus:
        for _ in range(50):
            b = gen_barcode()
            if b not in 쓰는중:
                쓰는중.add(b)
                out[sku] = b
                break
        else:
            # 🔴 못 만들었으면 **말한다.** 조용히 빠뜨리면 화면은 「채웠다」고 보이는데
            #    그 줄만 비어 있게 된다.
            _log.error('바코드를 새로 만들지 못했다 (50번 시도) — SKU %s', sku)
    return out
