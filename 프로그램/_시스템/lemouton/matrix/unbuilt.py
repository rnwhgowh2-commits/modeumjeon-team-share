# -*- coding: utf-8 -*-
"""미구성 SKU — 「SKU 만 등록되고 옵션 매트릭스를 아직 안 짠 것」.

재고관리에서 제품을 하나 추가하면(「모음전으로도 판다」 체크 안 함) 옵션함이 하나
생기고 그 안에 SKU 가 딱 하나 들어간다. 축(색상·사이즈…)은 아직 아무것도 안 짠 상태다.
이걸 화면에서 골라내야 「나중에 이 SKU 를 어느 매트릭스에 넣을까」를 물어볼 수 있다.

🔴 앞글자(`단독_`)로 판정하면 안 된다 — 이게 이 파일이 존재하는 이유다.
   2026-08-06 사장님 확정 A안 이후로 **재고관리 제품 추가가 `단독_` 를 안 만든다.**
   `create_option_box()` 로 정식 옵션함(`U20260806-000001` 꼴)이 만들어진다
   (`webapp/routes/inventory/data.py` 의 「제품 추가」 경로 · 그 사실을
   `tests/test_standalone_to_option_box.py` 가 `단독_` 로 시작하지 **않음**으로 못 박고 있다).
   그러니 앞글자로 세면 **2026-08-06 이후에 생긴 미구성 SKU 를 전부 놓친다.**
   놓치면 화면에는 「미구성 0건」이라 뜨고, 사장님은 창고에만 있는 물건이 없는 줄 안다.
   → 이름이 아니라 **구조**로 판정한다.

왜 다른 후보를 안 골랐나 (다시 이 판정을 손대려는 사람에게)
  · `model_code LIKE '단독_%'`
      → 위에 적은 대로 2026-08-06 이후 것을 못 잡는다. 옛것만 잡는 반쪽 판정이다.
  · 축이 0개인 것 전부
      → 옵션이 여럿인데 축만 안 짠 것까지 잡힌다(마켓에서 들여온 묶음 등).
        그건 「짜다 만 매트릭스」라 W1 의 `draft` 로 가야 할 물건이지 미구성 SKU 가 아니다.
        미구성 SKU 는 **아직 아무것도 시작 안 한 낱개 하나**를 뜻한다.
  · `Option.matrix_option_id IS NULL`
      → 판정력이 0이다. `lemouton/matrix/owner_hook.py` 의 `before_flush` 가
        저장되는 순간 같은 `model_code` 의 원본 매트릭스를 찾아 자동으로 채운다.
        옵션함은 만들 때 원본 매트릭스를 항상 같이 만들므로(`service.create_option_box`)
        이 칸은 **언제나 채워져 있다**. 늘 False 를 내는 조건은 조건이 아니다.

🔴 「매트릭스에 편입했다」를 따로 저장하지 않는다.
   미구성인지 아닌지는 축 수·옵션 수에서 **그때그때 나오는 파생값**이다. 축이 생기거나
   옵션이 2개가 되는 순간 저절로 벗겨진다. 플래그 칸을 하나 만들면 그 순간부터 같은
   사실이 두 곳에 살고, 축을 지웠는데 플래그는 안 꺼지는 식으로 반드시 갈린다.
   (같은 사실을 두 곳에 두지 않는다 — `matrix/models.py` 머리말과 같은 규칙이다.)
"""
from __future__ import annotations


def is_unbuilt(*, is_option_box: bool, axes: int, options: int) -> bool:
    """미구성 SKU 인가 — 옵션함이면서 · 축 설계 0개 · 옵션 1개.

    세 조건이 **전부** 맞아야 한다. 하나씩 왜 필요한지:

    · `is_option_box` — 판매용 모델은 축 0·옵션 1이어도 미구성이 아니다.
      🔴 이 조건이 없으면 「옵션 하나만 파는 단품 상품」이 전부 미구성으로 잡혀,
         멀쩡히 팔고 있는 상품을 「아직 안 짠 것」이라며 편입하라고 권하게 된다.
    · `axes == 0` — 축을 하나라도 짰으면 이미 매트릭스를 짜기 시작한 것이다.
    · `options == 1` — 낱개 하나여야 한다.
      옵션 0개는 **빈 옵션함**이다. 편입할 SKU 자체가 없으니 미구성 SKU 가 아니다.
      옵션 2개 이상은 축만 안 짠 「짜다 만 매트릭스」다(W1 의 `draft`).

    셋 다 호출자가 이미 들고 있는 값이라 여기서는 조회를 하지 않는다.
    묶음으로 판정할 때는 `unbuilt_batch()` 를 쓴다.
    """
    return bool(is_option_box) and axes == 0 and options == 1


def unbuilt_batch(session, codes, *, option_counts=None, option_box=None) -> set[str]:
    """`codes` 중 미구성 SKU 인 `model_code` 집합.

    인자
      · `codes`        — 볼 모델 코드들. 비어 있으면 조회를 한 번도 안 한다.
      · `option_counts`— {model_code: 옵션 수}. 화면이 이미 세어 뒀으면 넘긴다
                         (`webapp/routes/optgen.py` 의 `_boxes()` 가 이미 센다).
                         안 넘기면 여기서 한 번 더 센다.
      · `option_box`   — {model_code: 옵션함인가}. 위와 같다.

    조회 수 — 축 수는 **항상 여기서 센다(묶음당 쿼리 1개)**. 나머지 둘은 넘기면 0개,
    안 넘기면 각각 1개씩 더. 어느 쪽이든 줄마다 묻지 않는 묶음 조회라 N+1 이 안 난다.

    🔴 코드가 많으면 **500개씩 잘라서** 묻는다 — 한 번에 다 넣으면 안 된다.
       IN 절에 넣는 값이 많아지면 DB 가 조회를 통째로 거부한다. 그런데 이건
       **옵션함이 그만큼 쌓인 날에만** 터진다 — 몇 개 심어 두고 개발할 땐 영영 멀쩡하고
       라이브에서만 어느 날 갑자기 화면이 죽는, 제일 늦게 발견되는 부류의 사고다.
       특히 `/optgen/api/unbuilt-skus`(`webapp/routes/optgen_sku.py`)는 **옵션함 전부**를
       넣고 부른다 — 개수 상한이 없는 길이라 여기서 안 자르면 막을 곳이 없다.
       자르는 크기는 형제 모듈 `readiness._CHUNK` **한 곳에서만** 정한다. 여기 숫자를
       또 적으면 한쪽만 고쳐졌을 때 두 화면이 서로 다른 크기로 묻게 되고,
       고친 줄 알았던 쪽만 라이브에서 계속 터진다.

    🔴 넘긴 표에 없는 코드는 「0개」·「옵션함 아님」으로 본다 — 즉 **미구성이 아니라고**
       판정한다. 일부러 이 방향으로 기울였다. 놓치면 배지가 하나 안 뜰 뿐이지만,
       반대로 판매용 상품을 미구성이라고 잘못 부르면 사장님이 팔고 있는 상품을
       다른 매트릭스에 편입시키게 된다. 덜 말하는 쪽이 안전한 자리다.

    옵션은 **줄 수를 그대로 센다** — `is_active` 로 거르지 않는다.
    미구성 여부는 「짰나 안 짰나」의 문제지 「지금 팔 수 있나」의 문제가 아니다.
    """
    from sqlalchemy import func

    codes = [c for c in (codes or []) if c]
    # 빈 목록이면 여기서 끝낸다 — 형제 모듈 `readiness.phase_batch` 와 같은 모양이다.
    # 🔴 정직하게 적어 둔다: 아래 쪼개기 반복문이 들어온 뒤로 **이 두 줄은 지워도
    #    동작이 안 바뀐다**(빈 목록이면 반복문이 한 번도 안 돌아 조회가 어차피 0개다).
    #    그러니 이 줄만 지우는 것은 어떤 시험도 못 잡는다. 시험이 지키는 것은 이 줄이
    #    아니라 「빈 목록이면 DB 를 한 번도 안 건드린다」는 **결과**이고, 그건 쪼개기를
    #    되돌려 `.in_(codes)` 로 한 번에 묻는 순간 빨간불이 된다(조회 3개가 나간다).
    if not codes:
        return set()

    # 🔴 자르는 크기는 형제 모듈 것을 그대로 쓴다 — 여기서 다시 정하지 않는다.
    #    (함수 안에서 읽는 이유: 저쪽 값이 바뀌면 다음 호출부터 바로 따라간다.
    #     `readiness` 는 이 모듈을 안 불러오므로 서로 물고 도는 일이 없다.)
    from lemouton.matrix.readiness import _CHUNK
    from lemouton.sourcing.models import BundleOptionStep, Model, Option

    axes: dict[str, int] = {}
    센_옵션수: dict[str, int] = {}
    센_옵션함: dict[str, bool] = {}

    for i in range(0, len(codes), _CHUNK):
        묶음 = codes[i:i + _CHUNK]

        # 축 설계 수 — 이 표에 줄이 하나라도 있으면 축을 짜기 시작한 것이다.
        axes.update(session.query(BundleOptionStep.model_code,
                                  func.count(BundleOptionStep.id))
                    .filter(BundleOptionStep.model_code.in_(묶음))
                    .group_by(BundleOptionStep.model_code).all())

        # 🔴 넘겨받은 표가 있으면 이 조회들은 아예 안 돈다. 「이미 센 것을 또 세지 않는다」가
        #    이 인자들의 존재 이유라, 자르기를 넣으면서도 그 약속은 그대로 지킨다.
        if option_counts is None:
            센_옵션수.update(session.query(Option.model_code,
                                        func.count(Option.canonical_sku))
                           .filter(Option.model_code.in_(묶음))
                           .group_by(Option.model_code).all())

        if option_box is None:
            센_옵션함.update(session.query(Model.model_code, Model.is_option_box)
                           .filter(Model.model_code.in_(묶음)).all())

    if option_counts is None:
        option_counts = 센_옵션수
    if option_box is None:
        option_box = 센_옵션함

    return {c for c in codes
            if is_unbuilt(is_option_box=bool(option_box.get(c)),
                          axes=int(axes.get(c) or 0),
                          options=int(option_counts.get(c) or 0))}
