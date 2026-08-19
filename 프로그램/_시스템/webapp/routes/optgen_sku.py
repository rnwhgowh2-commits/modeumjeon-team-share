# -*- coding: utf-8 -*-
"""SKU 별 번호 세 가지 — 품번 · 바코드 · GTIN.

판정·규칙은 **여기 없다.** 전부 `lemouton/matrix/sku_info.py` 한 곳이다.
이 아래는 창구일 뿐이다 — 받고, 부르고, 돌려준다.
🔴 창구에 검사를 한 줄이라도 베껴 오면 안 된다. 화면 격자와 목록 칸이 같은 규칙을
   써야 「12/15」와 「저장 거부」가 서로 다른 말을 하지 않는다.
"""
from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

bp = Blueprint('optgen_sku', __name__, url_prefix='/optgen')


def _err(message: str, status: int = 400):
    """실패는 **왜 안 되는지**를 한국어로 돌려준다 — 조용히 넘어가지 않는다."""
    return jsonify({'ok': False, 'error': message}), status


@bp.get('/api/sku-info/<path:code>')
def api_sku_info(code: str):
    """묶음 하나의 SKU 줄 목록 — 격자와 목록 호버 카드가 같이 쓴다.

    응답: `{ok, code, fields, labels, rows: [{sku, no, label, article_no, barcode, gtin, active}]}`
      · `fields`·`labels` 도 같이 내린다 — 화면이 「품번·바코드·GTIN」 순서와 이름을
        또 적지 않게 하기 위함이다(순서를 두 곳에 적으면 언젠가 갈린다).
      · 세 번호가 `null` 이면 **아직 안 적음**이다. 빈 문자열로 바꿔 내리지 않는다.
    """
    from lemouton.matrix.sku_info import FIELDS, LABELS, rows_of
    from lemouton.sourcing.models import Model

    s = SessionLocal()
    try:
        if s.query(Model.model_code).filter_by(model_code=code).first() is None:
            return _err(f'그런 묶음이 없습니다: {code}', 404)
        rows = rows_of(s, code)
    finally:
        s.close()
    return jsonify({'ok': True, 'code': code, 'fields': list(FIELDS),
                    'labels': dict(LABELS), 'rows': rows})


@bp.post('/api/sku-info/<path:code>')
def api_sku_info_save(code: str):
    """격자에서 온 값을 저장한다.

    body: `{"items": [{"sku": "SKU-…", "article_no": "…", "barcode": "…", "gtin": "…"}, …]}`
    응답: `{ok, saved, rejected: [{sku, field, value, reason}], warnings: […], unknown: […]}`

    🔴 `ok` 는 **거부가 하나도 없을 때만** True 다. 거부가 있는데 True 를 내면 화면이
       「저장 완료」라고 말하고, 사장님은 안 들어간 칸을 들어간 줄 안다.
       그렇다고 **맞는 칸까지 되돌리지는 않는다** — 까닭은 `sku_info` 머리말에 있다.

    🔴 안 보낸 칸은 안 건드린다. `{"sku": X, "barcode": ""}` = 「바코드를 지운다」,
       `{"sku": X}` = 「이번엔 아무것도 안 건드린다」. 이 둘을 뭉개면 화면이 한 칸만
       보내도 나머지 두 칸이 조용히 지워진다.
    """
    from lemouton.matrix.sku_info import save
    from lemouton.sourcing.models import Model

    body = request.get_json(silent=True) or {}
    items = body.get('items')
    if not isinstance(items, list):
        return _err('items 를 목록으로 보내 주세요.')

    s = SessionLocal()
    try:
        if s.query(Model.model_code).filter_by(model_code=code).first() is None:
            return _err(f'그런 묶음이 없습니다: {code}', 404)
        res = save(s, code, items)
        s.commit()
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return _err(str(e)[:300], 500)
    finally:
        s.close()
    res['ok'] = not res['rejected']
    return jsonify(res)


@bp.post('/api/sku-info/<path:code>/gen-barcodes')
def api_sku_info_gen_barcodes(code: str):
    """빈 바코드를 채울 번호를 만들어 돌려준다 — **저장은 안 한다.**

    body: `{"skus": ["SKU-…", …]}` — 화면이 「지금 비어 있는 줄」만 골라 보낸다.
    응답: `{ok, barcodes: {sku: 번호}}`

    🔴 「빈 것만 채운다」는 판정을 서버가 못 한다. 사장님이 방금 손으로 적고 아직
       저장 안 한 값은 화면에만 있기 때문이다. 서버가 DB 만 보고 빈 줄을 고르면
       **방금 적은 값을 덮어쓴다.** 그래서 고르는 일은 화면이 하고, 서버는 준 목록에
       대해서만 겹치지 않는 번호를 만든다.
    """
    from lemouton.matrix.sku_info import gen_barcodes
    from lemouton.sourcing.models import Model, Option

    body = request.get_json(silent=True) or {}
    skus = body.get('skus')
    if not isinstance(skus, list):
        return _err('skus 를 목록으로 보내 주세요.')
    skus = [str(x).strip() for x in skus if str(x or '').strip()]

    s = SessionLocal()
    try:
        if s.query(Model.model_code).filter_by(model_code=code).first() is None:
            return _err(f'그런 묶음이 없습니다: {code}', 404)
        # 남의 묶음 SKU 에 번호를 만들어 주지 않는다 — 화면이 실수로 다른 창의
        # 목록을 보내면 엉뚱한 상품에 번호가 붙는다.
        mine = {x for (x,) in s.query(Option.canonical_sku)
                .filter(Option.model_code == code).all()}
        골라낸 = [x for x in skus if x in mine]
        out = gen_barcodes(s, 골라낸)
    finally:
        s.close()
    return jsonify({'ok': True, 'barcodes': out})
