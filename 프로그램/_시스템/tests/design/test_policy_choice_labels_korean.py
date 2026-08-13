# -*- coding: utf-8 -*-
"""정책 선택지가 **사장님 눈에 영어로 보이지 않는지.**

## 발견 (2026-08-13)

3갈래 옵션 축을 열고 나서, 정작 사장님이 고르는 화면에는
`one` · `two` · `three` 가 **영어 그대로** 나오고 있었다. 전수로 세니 **13개**였다 —
`WON` · `PERCENT` · `cheapest` · `priciest` · `average` · `max` · `min` ·
`margin_amount` · `fixed_price` · `into_price` 까지.

## 왜 샜나 — 라벨 표가 **화면 안에** 있었다

- `bulk/policy_detail.html` 의 JS `CHOICE_LABEL` 에만 목록이 있었다.
  스키마에 선택지를 새로 넣어도 이 목록을 같이 안 고치면 `cl(v)` 가 값을 그대로 찍는다.
- 그리고 **또 다른 화면**(`policy/detail.html`)은 아예 `{{ c }}` 로 생짜를 찍고 있었다.

🔴 이 시험의 첫 판은 `bulk/policy_detail.html` **한 곳만** 봤다. 그래서
「초록불인데 다른 화면엔 영어」가 될 뻔했다 — 감시 범위를 좁게 잡으면
「안 봤다」가 초록불이 된다.

## 그래서 지금 구조

라벨의 단일 원천 = `process_rule_schema.CHOICE_LABELS`.
스키마가 `to_dict()` 에 `choice_labels` 로 실어 보내고, **두 화면이 그걸 쓴다.**
"""
import io
import os
import re

_뿌리 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')


def _읽기(*조각):
    with io.open(os.path.join(_뿌리, *조각), encoding='utf-8') as f:
        return f.read()


def _영문_선택지():
    """스키마의 `choices` 중 **값이 한글이 아닌 것**. 한글 값은 라벨이 필요 없다."""
    from lemouton.registration.process_rule_schema import all_schemas
    값 = set()
    for it in all_schemas():
        for f in it.get('fields') or []:
            for c in f.get('choices') or []:
                if c and not re.search(r'[가-힣]', c):
                    값.add(c)
    return 값


def test_선택지가_전부_우리말_라벨을_갖는다():
    from lemouton.registration.process_rule_schema import CHOICE_LABELS
    빠짐 = sorted(_영문_선택지() - set(CHOICE_LABELS))
    assert not 빠짐, (
        f'화면에 영어로 보일 선택지 {len(빠짐)}개: {빠짐}\n'
        f'  → process_rule_schema.CHOICE_LABELS 에 우리말을 넣어라.\n'
        f'  뜻은 그 칸의 hint 원문을 그대로 옮길 것 — 지어내지 말 것.')


def test_스키마가_라벨을_실어_보낸다():
    """화면이 스스로 목록을 들고 있으면 또 갈린다 — 서버가 실어 줘야 한다."""
    from lemouton.registration.process_rule_schema import all_schemas
    축 = [f for it in all_schemas() if it['key'] == 'options'
          for f in it['fields'] if f['key'] == 'axis']
    assert 축, '옵션 축 칸이 사라졌다'
    라벨 = 축[0].get('choice_labels') or {}
    assert 라벨.get('three') == '모델명 · 색상 · 사이즈', 라벨
    assert 라벨.get('two') == '색상 · 사이즈', 라벨


def test_두_화면_모두_그_라벨을_쓴다():
    """🔴 한 곳만 고치면 나머지에서 영어가 샌다 — 실제로 그랬다."""
    대량 = _읽기('webapp', 'templates', 'bulk', 'policy_detail.html')
    assert 'f.choice_labels' in 대량, (
        'bulk/policy_detail.html 이 스키마 라벨을 안 쓴다 — 사본을 들고 있으면 갈린다')

    정책 = _읽기('webapp', 'templates', 'policy', 'detail.html')
    assert 'choice_labels' in 정책, (
        'policy/detail.html 이 스키마 라벨을 안 쓴다 — 여기가 생짜로 찍던 곳이다')
    assert '>{{ c }}<' not in 정책, (
        'policy/detail.html 이 선택지를 생짜(`{{ c }}`)로 찍는다 — 영어가 그대로 보인다')


def test_고르는_말과_구매자가_보는_말이_같다():
    """🔴 화면에서 「모델명 · 색상 · 사이즈」를 고르면 마켓에도 그 이름이 나가야 한다.

    두 곳이 갈리면 사장님이 고른 것과 손님이 보는 것이 달라진다.
    """
    from lemouton.registration.process_rule_schema import CHOICE_LABELS
    옵 = _읽기('lemouton', 'registration', 'options.py')
    for 이름 in ('모델명', '색상', '사이즈'):
        assert f"= '{이름}'" in 옵, f'options.py 의 그룹 이름 「{이름}」 이 바뀌었다'
    assert CHOICE_LABELS['three'] == '모델명 · 색상 · 사이즈'


def test_라벨이_비어_나오는_선택지가_없다():
    """표에 있든 없든 화면에 **빈 칸**이 뜨면 안 된다.

    ★ 빈 문자열 선택지(`size_unify` 의 「통일 안 함」)는 화면이 따로
      `— 안 정함 —` 으로 그린다 — 여기 셈에서 뺀다.
    """
    from lemouton.registration.process_rule_schema import all_schemas
    for it in all_schemas():
        for f in it.get('fields') or []:
            for c in f.get('choices') or []:
                if not c:
                    continue
                assert (f.get('choice_labels') or {}).get(c, c), (
                    f'{it["key"]}.{f["key"]} 의 「{c}」 라벨이 빈 칸이다')


def test_마켓_전용_항목의_한글_선택지는_라벨_없이_지나간다():
    """🔴 값 자체가 한글인 것까지 표에 넣으라고 하면 안 된다.

    「따라가지 않음」·「최저가 −1원」 같은 쿠팡 전용 선택지는
    `lemouton/policy/fields.py` 의 `EXTRA_ITEMS` 에 손으로 적혀 있고
    `choice_labels` 가 아예 없다. 화면은 `.get(c, c)` 로 값 그대로 보여 준다.
    """
    from lemouton.policy.fields import EXTRA_ITEMS
    한글 = {c for it in EXTRA_ITEMS for f in (it.get('fields') or [])
            for c in (f.get('choices') or []) if c and re.search(r'[가-힣]', c)}
    assert 한글, 'EXTRA_ITEMS 에 한글 선택지가 없다 — 시험 전제가 낡았다'
    없는것 = [it for it in EXTRA_ITEMS
              for f in (it.get('fields') or []) if 'choice_labels' not in f]
    assert 없는것, 'EXTRA_ITEMS 에도 라벨이 붙었다면 이 시험을 갱신하라'
    # 화면 쪽 폴백이 살아 있는지 — 두 화면 모두 `.get(c, c)` 형태여야 한다.
    정책 = _읽기('webapp', 'templates', 'policy', 'detail.html')
    assert '.get(c, c)' in 정책, 'policy/detail.html 의 폴백이 사라졌다'
