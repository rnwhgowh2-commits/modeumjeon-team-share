# -*- coding: utf-8 -*-
"""미구성 SKU 편입 — 낱개로 등록된 SKU 를 **기존 옵션 매트릭스의 축 값 자리로 이사**시킨다.

무슨 일을 하나
  재고관리에서 제품을 추가하면(「모음전으로도 판다」 체크 안 함) 옵션함이 하나 생기고
  그 안에 SKU 가 딱 하나 들어간다. 축(색상·사이즈)은 아직 아무것도 안 짠 상태 —
  이걸 「미구성 SKU」라 부른다(판정은 `lemouton/matrix/unbuilt.py` 한 곳뿐).
  나중에 그 물건을 모음전으로 팔기로 하면, 이미 짜 둔 매트릭스의 빈 조합 자리
  (예: 「블랙 · 260」)로 옮겨 넣어야 한다. 그 이사를 하는 창구가 여기다.

[중요] 이사는 **옮기는 것이지 새로 만드는 것이 아니다.**
   `canonical_sku` 를 그대로 두는 것이 이 파일의 첫 번째 규칙이다. 그 열쇠 하나로
   재고 이력·소싱처 URL 매핑·마켓 등록 기록이 전부 자동으로 따라온다.
   새 SKU 를 발급하고 값을 복사하는 방식이었다면 저 셋을 손으로 옮겨야 하고,
   `inventory_txs.option_canonical_sku` 는 **정식으로 묶여 있지 않은 그냥 문자열 칸**이라
   (webapp/routes/optgen.py 의 `_purge_option_traces` 참고) 빠뜨려도 아무 에러가 안 난다.
   재고 이력만 옛 SKU 에 남아 유령이 되고, 화면 재고는 조용히 0 이 된다.

왜 화면(옵션 목록)이 아니라 별도 창구인가
  옵션함 목록 화면(`webapp/routes/optgen.py`)은 「무엇이 있나」를 보여주는 곳이고,
  여기는 「그 물건을 어디로 옮길까」를 처리하는 곳이다. 옮기기는 손댈 곳이 일곱 군데라
  (아래 `api_adopt_sku` 참조) 목록 화면에 섞으면 한 군데를 빠뜨리기 쉽다.
"""
from flask import Blueprint, jsonify, request

from shared.db import SessionLocal

bp = Blueprint('optgen_sku', __name__, url_prefix='/optgen')

#: 한 번에 내주는 최대 줄 수 — 화면이 큰 값을 보내도 서버가 통째로 퍼내지 않게 막는다.
#: 🔴 이 값을 올리려면 `lemouton/matrix/readiness._CHUNK`(=500)도 같이 봐야 한다.
#:    잘라 낸 한 쪽(`page`)으로 묻는 아래 조회 셋(모델·옵션·재고)은 **안 자르고**
#:    한 번에 묻는다. 여기가 그 크기보다 커지면 그 셋이 IN 절 상한에 걸린다.
_LIMIT_MAX = 500
_LIMIT_DEFAULT = 50


def _err(message: str, status: int = 400):
    """실패는 **왜 안 되는지**를 한국어로 돌려준다 — 조용히 넘어가지 않는다.

    사장님은 개발자가 아니다. 화면에 그대로 띄워도 뜻이 통하는 문장이어야 한다.
    """
    return jsonify({'ok': False, 'error': message}), status


def _why_not_unbuilt(session, model_code: str) -> str:
    """「미구성이 아니다」의 이유를 **실제 숫자로** 만든다 — 지어내지 않는다.

    판정(`is_unbuilt`)이 보는 세 가지를 그대로 다시 세어 어느 조건이 어긋났는지 말한다.
    「안 됩니다」만 돌려주면 사장님이 무엇을 고쳐야 할지 알 수 없다.
    """
    from lemouton.sourcing.models import BundleOptionStep, Model, Option

    m = session.query(Model).filter_by(model_code=model_code).first()
    if m is None:
        return '어느 묶음에 들어 있는지 알 수 없습니다'
    if not m.is_option_box:
        return '이미 판매용 모음전의 옵션입니다'
    axes = (session.query(BundleOptionStep)
            .filter_by(model_code=model_code).count())
    if axes:
        return f'이미 축을 {axes}개 짜 둔 묶음의 옵션입니다'
    n = session.query(Option).filter_by(model_code=model_code).count()
    if n != 1:
        return f'그 묶음에 옵션이 {n}개 있습니다 (낱개 하나여야 합니다)'
    return '미구성 판정 조건에 맞지 않습니다'


@bp.get('/api/unbuilt-skus')
def api_unbuilt_skus():
    """편입할 수 있는 미구성 SKU 목록 — `?q=&brand=&limit=50`

    응답: `{ok, items: [{sku, name, brand, code, stock}], total}`
      · `code`  = 지금 그 SKU 가 들어 있는 옵션함 코드(편입하면 여기서 떠난다)
      · `total` = 자른(limit) 앞의 전체 건수. 화면 머리줄 숫자가 상한값을
        전체인 양 보여주는 거짓말을 막는다(`optgen._boxes` 가 겪었던 그 사고).

    [중요] 재고는 **원장 합계**(`shared/inventory_stock.get_stock_batch`)로 읽는다.
       `Option.boxhero_stock_total` 은 캐시 칸이라 갱신을 빠뜨린 경로가 있어
       화면 숫자와 실재고가 갈린다. 편입 화면에서 재고를 잘못 보면 「빈 자리인 줄 알고」
       엉뚱한 물건을 옮기게 된다. (`webapp/routes/optgen.py` 의 `box()` 가 같은 이유로
        같은 함수를 쓴다 — 두 화면이 다른 숫자를 보이면 안 된다.)

    [중요] 판정은 여기서 다시 적지 않는다 — `lemouton/matrix/unbuilt.py` 하나뿐이다.
       거르는 조건을 SQL 로 한 번 더 적으면(예: `HAVING count = 1`) 그 순간
       같은 규칙이 두 곳에 살고, 한쪽만 고쳐도 아무 에러 없이 목록만 달라진다.
    """
    from sqlalchemy import or_, select

    from lemouton.matrix.unbuilt import unbuilt_batch
    from lemouton.sourcing.models import Model, Option
    from lemouton.sourcing.option_brand import effective_option_brand
    from shared.inventory_stock import get_stock_batch
    from webapp.routes.optgen import display_name

    q = (request.args.get('q') or '').strip()
    brand = (request.args.get('brand') or '').strip()
    try:
        limit = int(request.args.get('limit') or _LIMIT_DEFAULT)
    except (TypeError, ValueError):
        limit = _LIMIT_DEFAULT
    limit = max(1, min(limit, _LIMIT_MAX))

    s = SessionLocal()
    try:
        # ① 후보 좁히기 — 찾는 말(q)·브랜드는 여기서 건다.
        #    🔴 `q` 를 옵션 조회에 직접 걸면 안 된다. 「옵션이 1개인가」를 셀 때
        #       찾는 말에 맞는 옵션만 세어져, 옵션이 여럿인 묶음이 1개로 보인다.
        #       그래서 SKU 로 찾는 것은 **어느 묶음인지만** 알아내는 데 쓴다.
        base = s.query(Model.model_code).filter(Model.is_option_box.is_(True))
        if brand:
            base = base.filter(Model.brand == brand)
        if q:
            like = f'%{q}%'
            base = base.filter(or_(
                Model.model_code.ilike(like),
                Model.model_name_display.ilike(like),
                Model.model_name_raw.ilike(like),
                Model.model_code.in_(select(Option.model_code)
                                     .where(Option.canonical_sku.ilike(like))),
            ))
        codes = [c for (c,) in base.all()]

        picked = unbuilt_batch(s, codes)          # ② 판정 — 단일 원천 호출
        if not picked:
            return jsonify({'ok': True, 'items': [], 'total': 0})

        # ③ 최근 만든 순 — 옵션함 목록(`optgen._boxes`)과 같은 순서라야 두 화면이 안 어긋난다.
        #
        # 🔴 여기도 **잘라서** 물어야 한다. `unbuilt_batch` 는 제 안에서 자르는데 이 줄만
        #    안 자르면, 옵션함이 많이 쌓인 날 **같은 요청 안에서 여기서** 조회가 통째로
        #    실패한다(IN 절에 넣는 값 개수에 DB 상한이 있다). 이 창구는 옵션함을 **전부**
        #    넣고 부르는 길이라 개수 상한이 없다 — 여기서 안 자르면 막을 곳이 없다.
        #    자르는 크기는 `readiness._CHUNK` 한 곳에서만 정한다(숫자를 여기 또 안 적는다).
        #
        # 🔴 잘라서 물으면 SQL 의 `ORDER BY` 는 **묶음 안에서만** 맞다. 묶음들을 이어 붙이면
        #    전체 순서가 깨져 첫 화면(`limit`)에 엉뚱한 줄이 올라온다 — 에러는 안 나고
        #    화면만 틀리는 종류다. 그래서 세우는 일은 SQL 에서 빼고 **아래에서 한 번만** 한다.
        from lemouton.matrix.readiness import _CHUNK
        고른코드 = sorted(picked)
        rows = []
        for i in range(0, len(고른코드), _CHUNK):
            rows += (s.query(Model.model_code, Model.created_at)
                     .filter(Model.model_code.in_(고른코드[i:i + _CHUNK])).all())

        # 만든 날짜가 있는 것 먼저(최근 순), 날짜가 없는 옛 줄은 뒤로. 날짜가 같으면
        # 코드 내림차순 — `optgen._boxes` 의 `order_by` 와 같은 규칙이다.
        # 파이썬 정렬은 **안정 정렬**이라, 코드로 먼저 세운 뒤 날짜로 다시 세우면
        # 날짜가 같은 줄끼리는 방금 세운 코드 순서가 그대로 남는다.
        def _때(row):
            # 시간대가 붙은 값과 안 붙은 값은 파이썬에서 **서로 비교가 안 된다**(TypeError).
            # 저장은 항상 UTC 한 가지라 지금은 섞일 일이 없지만, 섞이는 날 이 목록이
            # 통째로 500 이 되므로 세울 때만 시간대를 떼고 같은 자로 잰다.
            ts = row[1]
            return ts.replace(tzinfo=None) if getattr(ts, 'tzinfo', None) else ts

        날짜있음 = [r for r in rows if r[1] is not None]
        날짜없음 = [r for r in rows if r[1] is None]
        날짜있음.sort(key=lambda r: r[0], reverse=True)
        날짜있음.sort(key=_때, reverse=True)
        날짜없음.sort(key=lambda r: r[0], reverse=True)
        ordered = [c for c, _ts in 날짜있음 + 날짜없음]
        total = len(ordered)
        page = ordered[:limit]

        # 모델을 **객체로** 읽어 둔다 — 브랜드 상속(effective_option_brand)이
        # `option.model` 을 보므로, 안 읽어 두면 줄마다 조회가 한 번씩 더 나간다.
        models = {m.model_code: m for m in
                  s.query(Model).filter(Model.model_code.in_(page)).all()}
        opts = {o.model_code: o for o in
                s.query(Option).filter(Option.model_code.in_(page)).all()}
        stock = get_stock_batch(s, [o.canonical_sku for o in opts.values()])

        items = []
        for c in page:
            o, m = opts.get(c), models.get(c)
            if o is None or m is None:
                continue            # 그 사이에 지워졌다 — 없는 것을 지어내지 않는다
            nm = m.model_name_display or m.model_name_raw or c
            items.append({
                'sku': o.canonical_sku,
                # 「단독_」 앞글자는 화면에서 감춘다 — 규칙은 optgen.display_name 하나뿐.
                'name': display_name(nm, c),
                # 옵션에 브랜드가 없으면 모델에서 상속. 없으면 **None(미지정)** —
                # 「르무통」을 자동으로 박지 않는다(엉뚱한 브랜드로 잡히면 정책이 어긋난다).
                'brand': effective_option_brand(o),
                'code': c,
                'stock': int(stock.get(o.canonical_sku) or 0),
            })
    finally:
        s.close()
    return jsonify({'ok': True, 'items': items, 'total': total})


@bp.post('/api/box/<path:code>/adopt-sku')
def api_adopt_sku(code: str):
    """미구성 SKU 를 옵션함의 축 값 자리로 이사시킨다.

    body: `{"sku": "SKU-…", "axis_values": ["블랙", "260"]}`
    응답: `{ok, sku, moved_from, display_no, axis_values}`

    [중요] 손댈 곳이 일곱 군데다. **하나라도 빠지면 에러 없이 데이터만 조용히 깨진다.**
      ① 대상이 진짜 옵션함인가 · SKU 가 진짜 미구성인가
      ② 축 값 개수가 대상 축 수와 같은가 · 각 값이 그 축에 실제로 있는가
      ③ 그 조합에 이미 옵션이 있지 않은가 (한 조합에 옵션은 하나뿐)
      ④ `model_code` 를 대상으로 교체
      ⑤ `matrix_option_id` 를 **명시적으로 비우기** — `lemouton/matrix/owner_hook.py` 의
         before_flush 는 **None 인 것만** 채운다. 안 비우면 옵션이 **옛 매트릭스를
         계속 가리키고 아무도 모른다**(화면은 새 묶음에 있는데 속은 옛 주인).
      ⑥ 축 값 재배정 — `axis_values_json` · `color_code` · `size_code`
         [중요] 빠뜨리면 옵션은 있는데 **조합 격자에서 사라진다.** 큰 창
            (`webapp/static/option_url_modal.js`)이 축 수와 값 수가 다른 옵션을 버린다.
      ⑦ 표시번호 재발급 — 번호는 「매트릭스번호 + 순번」이라 이사하면 반드시 바뀐다.

    [중요] 하지 **않는** 것도 규칙이다.
      · `canonical_sku` 를 안 바꾼다 (이 파일 머리말 참조 — 재고 이력이 유령이 된다)
      · 텅 빈 원래 옵션함을 **안 지운다.** 되돌릴 수 있어야 한다.
        옵션 0개짜리 옵션함은 현행 `hid` 규칙이 이미 화면에서 감춘다(`optgen._boxes`).
    """
    import json

    from lemouton.matrix.option_no import number_options
    from lemouton.matrix.service import ensure_origin
    from lemouton.matrix.unbuilt import unbuilt_batch
    from lemouton.sourcing.axis_slot import legacy_pair
    from lemouton.sourcing.models import BundleOptionStep, Model, Option
    from lemouton.sourcing.option_orphans import axes_of

    body = request.get_json(silent=True) or {}
    sku = str(body.get('sku') or '').strip()
    raw_values = body.get('axis_values')
    if not sku:
        return _err('편입할 SKU 를 골라 주세요.')
    if not isinstance(raw_values, list):
        return _err('축 값(axis_values)을 목록으로 보내 주세요. 예: ["블랙", "260"]')
    values = [str(v).strip() for v in raw_values]

    s = SessionLocal()
    try:
        # ── ① 대상·SKU 가 자격이 되나 ────────────────────────────────────
        target = s.query(Model).filter_by(model_code=code).first()
        if target is None:
            return _err(f'그런 옵션함이 없습니다: {code}', 404)
        if not target.is_option_box:
            return _err('판매용 모음전에는 여기서 넣을 수 없습니다. '
                        '아직 판매 안 하는 옵션함에만 편입할 수 있습니다.')

        opt = s.get(Option, sku)
        if opt is None:
            return _err(f'그런 SKU 가 없습니다: {sku}', 404)
        moved_from = opt.model_code
        if moved_from == code:
            return _err('이미 이 옵션함에 들어 있는 SKU 입니다.')
        # 판정은 `lemouton/matrix/unbuilt.py` 하나뿐 — 여기서 조건을 다시 적지 않는다.
        if not unbuilt_batch(s, [moved_from]):
            return _err(f'미구성 SKU 가 아닙니다: {sku} — '
                        f'{_why_not_unbuilt(s, moved_from)}')

        # ── ② 축 값이 대상의 축 설계와 맞나 ─────────────────────────────
        steps = (s.query(BundleOptionStep).filter_by(model_code=code)
                 .order_by(BundleOptionStep.step_no).all())
        if not steps:
            # 축이 없는 옵션함은 그 자체로 미구성이다. 넣으면 「옵션 2개 · 축 0개」가 돼
            # 미구성도 아니고 매트릭스도 아닌 어중간한 묶음이 된다.
            return _err('대상 옵션함에 축(색상·사이즈…)이 아직 없습니다. '
                        '축을 먼저 만든 뒤에 편입할 수 있습니다.')
        if len(values) != len(steps):
            return _err(f'축이 {len(steps)}개인데 값을 {len(values)}개 주셨습니다 — '
                        f'축 순서: {" · ".join(st.axis_name for st in steps)}')
        for st, v in zip(steps, values):
            try:
                allowed = [str(x) for x in (json.loads(st.values_json or '[]') or [])]
            except (ValueError, TypeError):
                allowed = []
            if v not in allowed:
                # 🔴 없는 값을 그냥 받아 주면 축 설계에 없는 유령 조합이 생긴다.
                #    그 옵션은 격자에도 안 뜨고 전송 목록에서도 빠져 조용히 사라진다.
                return _err(f'「{st.axis_name}」 축에 없는 값입니다: '
                            f'{v or "(빈 값)"} — 있는 값: '
                            f'{" · ".join(allowed) or "(아직 없음)"}')

        # ── ③ 그 조합이 이미 차 있지 않나 ───────────────────────────────
        combo = tuple(values)
        for o in s.query(Option).filter_by(model_code=code).all():
            if axes_of(o) == combo:
                return _err(f'이미 같은 조합의 옵션이 있습니다: {o.canonical_sku} '
                            f'({" ".join(values)}) — 한 조합에 옵션은 하나뿐입니다.')

        # ── ④~⑥ 이사 ────────────────────────────────────────────────────
        axis_names = [st.axis_name for st in steps]
        # 새 주인이 될 원본 매트릭스를 먼저 보장한다. 「원본 보장」 규칙은
        # `ensure_origin` 하나뿐이라 여기서 다시 만들지 않는다.
        mo = ensure_origin(s, target)

        opt.model_code = code
        # 🔴 ⑤ — 반드시 **비우고** flush 해야 길목 장치가 새 주인을 채운다(위 독스트링).
        opt.matrix_option_id = None
        # 번호도 같이 비운다 — `number_options` 는 **비어 있는 것만** 새로 붙인다.
        #   안 비우면 옛 매트릭스 번호(U…-01)를 단 채 새 묶음에 앉아 있게 된다.
        opt.display_no = None
        opt.axis_values_json = json.dumps(values, ensure_ascii=False)
        # 🔴 옛 칸은 **축 이름**으로 정한다 — 「몇 번째 축인가」로 채우면 모델을 1축에 둔
        #    순간 `color_code` 에 모델명이 들어간다. 규칙은 axis_slot.py 한 곳뿐이며
        #    `legacy_pair` 가 그 안의 `storage_slots` 를 그대로 쓴다.
        opt.color_code, opt.size_code = legacy_pair(axis_names, values)
        # 🔴 낱개 시절의 표시 이름은 **지운다.** 재고관리에서 적어 둔 「블랙」이 남은 채
        #    사이즈 자리로 옮겨 가면, 화면은 `color_display or color_code` 를 보므로
        #    새 축 값과 다른 글자를 보여준다(에러 없이 화면만 거짓말).
        #    비우면 화면이 방금 정한 `color_code`·`size_code` 로 떨어진다 —
        #    매트릭스에서 태어난 옵션들도 이 칸이 비어 있다(option_service 와 같은 모양).
        opt.color_display = None
        opt.size_display = None
        s.flush()          # ← 이 flush 에서 owner_hook 이 새 주인·번호를 채운다

        if opt.matrix_option_id is None:
            # 안전망 — 길목 장치를 안 건 환경(모델만 import 한 스크립트 등)에서도
            # 주인 없는 옵션을 남기지 않는다. 새 규칙이 아니라 위에서 이미 보장해 둔
            # 바로 그 원본 매트릭스를 쓴다(같은 사실을 두 번 계산하지 않는다).
            opt.matrix_option_id = mo.id
            s.flush()

        # ── ⑦ 표시번호 재발급 (규칙은 option_no.number_options 하나뿐 · 멱등) ──
        number_options(s, [opt])
        display_no = opt.display_no
        s.commit()
    except ValueError as e:
        s.rollback()
        return _err(str(e))
    except Exception as e:                              # noqa: BLE001
        s.rollback()
        return _err(str(e)[:300], 500)
    finally:
        s.close()
    return jsonify({'ok': True, 'sku': sku, 'moved_from': moved_from,
                    'display_no': display_no, 'axis_values': values})


# ════════════════════════════════════════════════════════════════
#  SKU 별 번호 세 가지 — 품번 · 바코드 · GTIN
#
#  판정·규칙은 **여기 없다.** 전부 `lemouton/matrix/sku_info.py` 한 곳이다.
#  이 아래는 창구일 뿐이다 — 받고, 부르고, 돌려준다.
#  🔴 창구에 검사를 한 줄이라도 베껴 오면 안 된다. 화면 격자와 목록 칸이 같은 규칙을
#     써야 「12/15」와 「저장 거부」가 서로 다른 말을 하지 않는다.
# ════════════════════════════════════════════════════════════════

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

    [중요] `ok` 는 **거부가 하나도 없을 때만** True 다. 거부가 있는데 True 를 내면 화면이
       「저장 완료」라고 말하고, 사장님은 안 들어간 칸을 들어간 줄 안다.
       그렇다고 **맞는 칸까지 되돌리지는 않는다** — 까닭은 `sku_info` 머리말에 있다.

    [중요] 안 보낸 칸은 안 건드린다. `{"sku": X, "barcode": ""}` = 「바코드를 지운다」,
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

    [중요] 「빈 것만 채운다」는 판정을 서버가 못 한다. 사장님이 방금 손으로 적고 아직
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


# ════════════════════════════════════════════════════════════════
#  SKU 연결상태 — SKU 하나하나가 누구인가(번호·브랜드·모델명·색상·사이즈)
#
#  판정은 여기 없다 — 전부 `lemouton/matrix/sku_identity.py` 한 곳이다.
#  품번·바코드·GTIN(위 sku-info)과는 다른 물음이라 창구도 따로 둔다.
# ════════════════════════════════════════════════════════════════

@bp.get('/api/sku-identity/<path:code>')
def api_sku_identity(code: str):
    """묶음 하나의 SKU 줄 목록 — 목록의 「SKU 연결상태」 호버 카드가 쓴다.

    응답: `{ok, code, rows: [{sku, no, brand, model_name, color, size}]}`
      · `size` 는 매트릭스 전체가 사이즈 1개뿐이면 「FREE」로 나온다.
      · 값이 없는 칸은 `null` — 지어내지 않는다.
    """
    from lemouton.matrix.sku_identity import rows_of
    from lemouton.sourcing.models import Model

    s = SessionLocal()
    try:
        if s.query(Model.model_code).filter_by(model_code=code).first() is None:
            return _err(f'그런 묶음이 없습니다: {code}', 404)
        rows = rows_of(s, code)
    finally:
        s.close()
    return jsonify({'ok': True, 'code': code, 'rows': rows})
