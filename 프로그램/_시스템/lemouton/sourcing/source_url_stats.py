# -*- coding: utf-8 -*-
"""소싱처 URL 집계 — 「이 모델, 소싱처별로 주소 몇 개 · 맵핑 다 됐나」.

매트릭스 목록·판에서 한 줄에 「무신사 3 · SSF 1 / 맵핑 2·5 SKU」처럼 보여주기
위한 숫자를 **줄 수와 무관하게 쿼리 1개**로 만든다.

🔴 원천 — `bundle_source_urls` + `option_source_url_links` 만 쓴다.
   이 저장소엔 소싱처 URL 표가 두 벌 있다. `option_source_urls` + `source_registry`
   쪽을 베끼면, 같은 매트릭스를 두고 **목록과 「축 만들기」 큰 창이 서로 다른 숫자를
   말한다**(큰 창 `/api/bundles/<code>/source-urls` 가 여기 쓰는 표를 읽는다).
   화면끼리 숫자가 갈리면 사장님은 어느 쪽을 믿을지 알 수 없다.

🔴 「모른다」와 「아니다」를 가른다 — URL 이 한 개도 없으면 맵핑 완료 여부는
   `None`(확인 불가)이다. `False`(미완료)로 적으면 「할 일이 남았다」는 거짓 신호가
   되고, `True` 로 적으면 안 한 일이 끝난 걸로 둔갑한다.
   같은 규칙을 `webapp/routes/matrix.py:_index_stats` 도 재고에 쓴다
   (「모르는 것(None)은 품절이 아니라 확인 불가 — 여기 안 센다」).

── 왜 `matrix.py:_index_stats()` 를 재사용하지 않고 새로 만드나 ────────────────
  리뷰에서 「합쳐라」로 뒤집힐 수 있는 판단이라 근거를 남긴다.
  1) **열쇠가 다르다.** 저쪽은 `MatrixOption.id` 로 모으고, 여기는 `model_code` 다.
     URL 은 모델에 붙으므로(BundleSourceUrl.model_code) 모델 단위가 원천이다.
  2) **분해 축이 없다.** 저쪽 `src` 는 「소싱처 몇 곳」 한 숫자뿐이라
     `source_key` 별 URL 수·맵핑 분수를 뽑을 수 없다.
  3) **딸려 오는 값이 너무 많다.** 저쪽은 마켓 등록·품절·색상 수까지 한 번에
     만드느라 쿼리를 10개 돈다. 여기 필요한 건 두 표뿐이다.
  → 그래서 `_index_stats` 는 **한 줄도 건드리지 않는다**
    (`tests/matrix/test_index_panel.py` 가 그 동작을 지킨다).
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


def _dedup(codes) -> list[str]:
    """중복·빈 값을 걷어내되 **넣어 준 순서**를 지킨다.

    호출자가 화면 순서대로 넘긴 목록을 그대로 되돌려 줘야 렌더가 안 흔들린다.
    """
    out, seen = [], set()
    for c in codes or ():
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _chunked(codes: list[str]):
    """코드 목록을 「한 번의 IN 절에 넣어도 되는 크기」로 잘라 내놓는다.

    🔴 **왜 자르나** — 이 모듈을 부르는 `webapp/routes/optgen.py:_box_facts()` 는
       옵션함을 **전부** 넘긴다(목록에 상한이 없다). 안 자르면 옵션함이 쌓인 날에만
       조회가 통째로 실패한다. 개발할 땐 영영 멀쩡하고 라이브에서만 어느 날 갑자기
       목록이 안 열리는, 제일 늦게 발견되는 부류의 사고다.

    🔴 **자르는 크기는 `matrix/readiness._CHUNK` 한 곳에서만 정한다.** 여기 숫자를
       또 적으면 한쪽만 고쳐졌을 때 그쪽 화면만 계속 터진다. 진짜 한도가 얼마인지와
       「그런데 왜 그보다 훨씬 작게 자르는지」도 그 옆에 실측과 함께 적혀 있다 —
       여기에 옮겨 적지 않는다(같은 사실을 두 곳에 두면 언젠가 갈린다).
       값은 **부를 때마다** 읽는다. 모듈 맨 위에서 당겨 오면 그 순간 값이 굳어
       저쪽을 고쳐도 안 따라온다.

    🔴 **잘라도 답이 안 변하는 이유** — 아래 두 조회는 `model_code` 로 거르고
       `model_code` 를 묶음 열쇠(GROUP BY)에 넣는다. 그래서 한 모델의 줄이 두 묶음에
       나뉘는 일이 없고, 묶음별 결과를 그냥 이어 붙이면 된다. 🔴 나중에 모델을 가로질러
       합치는 집계(전체 합·순위 등)를 여기 넣으면 이 전제가 깨진다 — 그때는 자르는
       것만으로 안 되고 파이썬에서 다시 합쳐야 한다.
    """
    from lemouton.matrix.readiness import _CHUNK      # 자르는 크기의 단일 진실 원천

    for i in range(0, len(codes), _CHUNK):
        yield codes[i:i + _CHUNK]


def url_counts_by_source(session, codes: list[str]) -> dict[str, list[tuple[str, int]]]:
    """모델별 「소싱처키 → 등록된 URL 수」.

    반환: `{model_code: [(source_key, url수), …]}` — source_key 오름차순 고정.
      · 순서를 고정하는 이유: 화면이 다시 그릴 때마다 소싱처 자리가 바뀌면
        사장님이 「방금 있던 게 없어졌다」고 읽는다.
      · 요청한 코드는 URL 이 하나도 없어도 **빈 목록으로 반드시 들어 있다** —
        호출자가 `KeyError` 를 신경 쓰지 않게, 그리고 「0 곳」이 명시되게.

    조회는 **묶음당 1개**다 — 모델 수가 3이든 30이든 같고, 아주 많으면
    `_chunked` 가 정한 크기로 잘려 그 개수만큼만 늘어난다
    (GROUP BY model_code, source_key).
    """
    from sqlalchemy import func

    from lemouton.sourcing.models import BundleSourceUrl

    codes = _dedup(codes)
    out: dict[str, list[tuple[str, int]]] = {c: [] for c in codes}
    if not codes:
        return out

    rows = []
    for 묶음 in _chunked(codes):
        rows += (session.query(BundleSourceUrl.model_code,
                               BundleSourceUrl.source_key,
                               func.count(BundleSourceUrl.id))
                 .filter(BundleSourceUrl.model_code.in_(묶음))
                 .group_by(BundleSourceUrl.model_code, BundleSourceUrl.source_key)
                 .all())
    for code, sk, cnt in rows:
        if code in out:
            out[code].append((sk, int(cnt or 0)))
    for pairs in out.values():
        pairs.sort(key=lambda p: p[0])
    return out


def mapping_coverage(session, codes: list[str],
                     sku_total: dict[str, int]) -> dict[str, dict]:
    """모델별 맵핑 진척 — 「소싱처 n·m 곳 / SKU N·M 개 / 완료?」.

    반환: `{model_code: {'sources': m, 'sources_done': n,
                         'skus': M, 'skus_done': N, 'complete': True|False|None,
                         'over_total': 0|실제로_센_수}}`

    ── 「맵핑 완료」의 뜻 (사장님 확정) ────────────────────────────────
      **소싱처마다**, 그 소싱처가 가진 URL 중 **최소 1개**에 연결된 SKU 수가
      그 모델의 전체 SKU 수와 같아야 그 소싱처가 완료다.
      (한 소싱처에 URL 이 2개면, SKU 가 어느 쪽에 붙었든 상관없다 — 합집합으로 센다.
       「통합 모음전 + 단품 그레이」 두 페이지로 나눠 붙이는 게 정상 사용법이다.)
      모든 소싱처가 완료여야 `complete=True`.

    ── 🔴 `None` 을 내는 두 자리 (지어내지 않는다) ──────────────────────
      · URL 이 0개 — 아직 주소를 안 붙였다. 완료도 미완료도 아닌 **확인 불가**.
      · SKU 가 0개 — 잴 대상이 없다. 0/0 을 「다 됐다」로 적으면 빈 매트릭스가
        초록불이 되어 할 일이 사라진다.

    ── `skus_done` 은 왜 「가장 덜 된 소싱처」의 숫자인가 ────────────────
      아무 소싱처에나 한 번이라도 붙은 SKU 를 세면(합집합), 무신사만 5/5 이고
      SSF 는 2/5 인 상태에서 화면에 **「SKU 5·5」와 「미완료」가 나란히** 찍힌다.
      숫자와 판정이 서로 다른 말을 하는 화면은 안 만든다. 그래서 소싱처들 중
      가장 적게 연결된 곳의 숫자를 낸다 — 이러면 `skus_done == skus` 인 것과
      `complete is True` 인 것이 항상 같은 뜻이 된다.

    🔴 `sku_total` 은 호출자가 주는 「그 모델의 전체 SKU 수」다. 분모를 여기서
       따로 세지 않는 이유는 위·아래 화면이 각자 센 숫자로 갈리지 않게 하기 위함이다
       (같은 사실을 두 곳에서 만들지 않는다). 대신 분자는 **그 모델에 속한 옵션만**
       세도록 조건을 건다 — 안 그러면 남의 모델 옵션이 이 URL 에 붙어 있을 때
       분수가 「7·5」처럼 말이 안 되는 값이 된다.

    ── 🔴 `over_total` — 분모가 틀렸다는 사고 신호 ──────────────────────
      분모(`sku_total`)를 호출자가 만들기 때문에, 그 숫자가 실제 옵션 수보다 작게
      들어오는 사고가 난다(옵션을 늘려 놓고 총계를 다시 안 센 경우 등). 그러면
      **분자가 분모를 넘어** 화면에 「SKU 5·3」 같은 말이 안 되는 분수가 찍힌다.

      그래서 분자를 분모로 자른다. 다만 **조용히 자르지 않는다** — 잘랐다는 것은
      「호출자가 준 분모가 틀렸다」는 뜻이고, 그건 고쳐야 할 사고이기 때문이다.
      조용히 넘어가면 화면은 멀쩡해 보이는데 어디서 분모가 틀어졌는지 영영 못 찾는다.
      · `over_total` = 0 → 정상.
      · `over_total` = n(>0) → 실제로 센 최대 연결 SKU 수가 n 인데 분모는 그보다 작다.
        (분자 대신 이 값을 남기는 이유: 「잘렸다」는 사실만으로는 얼마나 어긋났는지
         모르고, 그러면 분모를 만든 쪽을 찾아갈 단서가 없다.)
      · 같은 사실을 **경고 로그로도** 남긴다 — 화면이 이 칸을 안 읽어도 서버 로그엔
        남아야 한다. 잘라 놓고 아무 데도 안 적으면 그게 곧 「조용한 실패」다.

      분모를 넘긴 소싱처는 **완료로 친다**(`d >= total`). 「분모보다 더 많이 붙었는데
      미완료」는 잘라 보여 준 분수(3·3)와 판정(미완료)이 서로 다른 말을 하는 화면이다.

    조회는 **묶음당 1개**다 — 모델 수와 무관하고, 아주 많으면 `_chunked` 가 정한
    크기로 잘려 그 개수만큼만 늘어난다.
    """
    from sqlalchemy import and_, func

    from lemouton.sourcing.models import (
        BundleSourceUrl, Option, OptionSourceUrlLink,
    )

    codes = _dedup(codes)
    sku_total = sku_total or {}

    def _blank(code: str) -> dict:
        total = int(sku_total.get(code) or 0)
        return {'sources': 0, 'sources_done': 0,
                'skus': total, 'skus_done': 0, 'complete': None,
                'over_total': 0}

    out: dict[str, dict] = {c: _blank(c) for c in codes}
    if not codes:
        return out

    # URL 을 왼쪽에 두고 바깥 조인 — 아직 SKU 가 하나도 안 붙은 소싱처도
    # 「소싱처 1곳, 연결 0」으로 남아야 분모(sources)가 맞는다.
    # 안쪽 조인으로 바꾸면 그 소싱처가 통째로 사라져 「전부 완료」로 둔갑한다.
    rows = []
    for 묶음 in _chunked(codes):
        rows += (session.query(BundleSourceUrl.model_code,
                               BundleSourceUrl.source_key,
                               func.count(func.distinct(Option.canonical_sku)))
                 .outerjoin(OptionSourceUrlLink,
                            OptionSourceUrlLink.bundle_source_url_id == BundleSourceUrl.id)
                 .outerjoin(Option,
                            and_(Option.canonical_sku == OptionSourceUrlLink.option_canonical_sku,
                                 Option.model_code == BundleSourceUrl.model_code))
                 .filter(BundleSourceUrl.model_code.in_(묶음))
                 .group_by(BundleSourceUrl.model_code, BundleSourceUrl.source_key)
                 .all())

    per_code: dict[str, list[int]] = {}
    for code, _sk, done in rows:
        if code in out:
            per_code.setdefault(code, []).append(int(done or 0))

    for code, dones in per_code.items():
        st = out[code]
        total = st['skus']
        st['sources'] = len(dones)

        # 🔴 분자가 분모를 넘었다 = 호출자가 준 분모가 틀렸다.
        #    아래에서 분수를 잘라 화면은 말이 되게 만들되, 잘랐다는 사실은 반드시
        #    남긴다(결과 칸 + 경고 로그). 조용히 자르면 원인을 영영 못 찾는다.
        over = max(dones) if dones else 0
        if over > total:
            st['over_total'] = over
            _log.warning(
                "소싱처 맵핑 집계 — 모델 %s: 호출자가 준 SKU 총계는 %s 인데 "
                "실제로 연결된 SKU 가 %s 개다. 화면 분수는 %s 로 잘라서 보여 주지만, "
                "총계를 만든 쪽이 틀렸을 가능성이 크니 확인이 필요하다.",
                code, total, over, total,
            )

        if total <= 0:
            # 잴 대상이 없다 — 분자도 0, 판정은 「모른다」로 둔다.
            # (붙은 SKU 가 있는데 총계가 0 이면 위에서 이미 over_total 로 알렸다.)
            st['sources_done'] = 0
            st['skus_done'] = 0
            st['complete'] = None
            continue
        # `>=` 인 이유: 분모를 넘긴 소싱처를 미완료로 세면, 잘라 보여 준 분수(3·3)와
        # 판정(미완료)이 한 화면에서 서로 다른 말을 하게 된다.
        st['sources_done'] = sum(1 for d in dones if d >= total)
        st['skus_done'] = min(min(dones), total)
        st['complete'] = (st['sources_done'] == st['sources'])
    return out


def source_labels(keys=None) -> dict[str, str]:
    """소싱처키 → 사람이 읽는 이름 (`musinsa` → `무신사`).

    🔴 **세션을 받지 않는다** — 위 두 함수와 달리 이 함수는 호출자의 세션 밖에서 돈다.
       속의 `source_registry.get_labels()` → `get_all_sources()` 가 **언제나 자기 세션을
       새로 연다**(그쪽 독스트링에 「session 인자는 backward-compat — 무시, 항상 새
       session」이라 못 박혀 있다). 그래서 세션을 받아 봐야 쓸 데가 없다.

       그런데도 `session` 인자를 받아 두면 부르는 쪽이 「내 세션 안에서 도는구나」라고
       읽는다. 그러면 방금 고치고 **아직 커밋 안 한 소싱처 이름**이 여기 보일 거라
       기대하는데 실제로는 안 보인다 — 「이름을 고쳤는데 화면이 그대로다」가 되고,
       에러가 하나도 안 나므로 원인을 영영 못 찾는다. 그래서 인자를 없앴다.
       (반대로 「세션을 실제로 쓰도록」 고치는 길은 `source_registry` 를 쓰는 전 화면을
        같이 바꿔야 하는 일이라 이 모듈 혼자 결정할 수 없다.)

    🔴 **요청당 한 번만** 부른다. 속에서 DB 를 한 번 치기 때문에(빌트인 명부 위에
       사용자가 고친 이름을 덮어쓴다), 줄마다 부르면 그게 곧 N+1 이다.
       위 두 함수의 반환값이 라벨이 아니라 **키**인 이유가 이것이다 —
       라벨을 섞어 내보내면 호출자가 「한 번만」을 지킬 방법이 없어진다.

    이름을 못 찾으면 키를 그대로 돌려준다 — 없는 이름을 지어내지 않는다.
    `keys` 를 주면 그것만, 안 주면 아는 것 전부.
    """
    from lemouton.sourcing import source_registry

    # 🔴 `source_labels(db)` 로 잘못 부르면 세션이 `keys` 자리로 들어온다.
    #    이 파일의 형제 둘은 첫 인자가 세션이라(`url_counts_by_source(db, codes)`)
    #    같은 흐름으로 쓰기 쉬운데, 이건 세션을 안 받는다.
    #    막이가 없으면 무슨 일이 나나 — 실제로 재 봤다. 세션은 「하나씩 꺼내 볼 수 있는
    #    것」이라 아래 `_dedup(세션)` 이 **에러 없이 빈 목록**을 내고 결과가 `{}` 가 된다.
    #    화면엔 소싱처 이름이 하나도 안 뜨는데 로그엔 아무것도 안 남는다.
    if keys is not None and hasattr(keys, 'query'):
        raise TypeError(
            "source_labels 는 세션을 받지 않는다 — 소싱처키 목록만 넘겨라. "
            "예: source_labels(['musinsa', 'ssf'])"
        )

    try:
        known = source_registry.get_labels() or {}
    except Exception:
        known = {}
    if keys is None:
        return dict(known)
    return {k: (known.get(k) or k) for k in _dedup(keys)}
