# -*- coding: utf-8 -*-
"""옥션·G마켓·11번가·롯데온 — 모델이 다른데 이름이 같아지면 막는다.

## 왜

이 네 마켓 컴파일러는 옵션 이름을 **색상·사이즈로만** 만든다
(`send_more.py` · `eleven11/products.py` · `lotteon/products.py`).
모델모음전 3축 옵션이 오면 「메이트 블랙 260」과 「스위트 블랙 260」이
둘 다 `블랙/260` 이 되어 **같은 이름 두 줄**이 올라간다.
11번가 문서는 「한 상품안에서 옵션값은 중복이 될수 없습니다」라고 못 박는다.
(나머지 3마켓의 실제 거절 여부는 미실측 — 확인불가)

## 오늘 도달 가능한 실경로다

모델명을 싣는 유일한 경로가 이 마켓들로 그대로 흐른다:
`policy/to_payload._options_json`(`model` 칸) → `send/as_draft.py` →
`send/runner.py` → `register_draft` → `MARKETS_MORE` → `compile_more`.

## 🔴 `options._normalize` 를 재사용하지 않은 까닭

거긴 중복을 **재고 거르기 전에** 센다. 그대로 쓰면
`[블랙/260 재고0, 블랙/260 재고5]`(품절 재입고를 두 줄로 적은 초안)이
**오늘은 되는데 내일 막힌다**(실측). 그래서 여기서는 팔 수 있는 줄만 보고,
모델이 실제로 갈릴 때만 막는다.
"""
import json

import pytest

from lemouton.registration.compile_more import _normalize_options
from lemouton.registration.compile_common import CompileError


class D:
    def __init__(self, opts):
        self.options_json = json.dumps(opts, ensure_ascii=False)


def _행(color, size, stock, model='', extra=0):
    return {'color': color, 'size': size, 'stock': stock,
            'extra_price': extra, 'sku': f'{model}{color}{size}', 'model': model}


def test_모델이_다른데_이름이_같으면_막는다():
    with pytest.raises(CompileError) as ei:
        _normalize_options(D([_행('블랙', '260', 3, '메이트'),
                              _행('블랙', '260', 2, '스위트')]), 10000)
    말 = str(ei.value)
    assert '모델이 다른 옵션' in 말, 말
    assert '메이트' in 말 and '스위트' in 말, 말
    assert '나눠서' in 말, 말          # 어떻게 풀지까지 알려 준다


def test_모델이_같으면_안_막는다():
    """같은 모델의 같은 색·사이즈가 두 줄이면 그건 다른 문제다 — 여기 몫이 아니다."""
    rows, _ = _normalize_options(D([_행('블랙', '260', 3, '메이트'),
                                    _행('블랙', '260', 2, '메이트')]), 10000)
    assert len(rows) == 2


def test_모델_칸이_없는_옛_옵션은_그대로_지나간다():
    """라이브 대부분이 이 길이다 — 회귀가 나면 안 된다."""
    rows, _ = _normalize_options(D([
        {'color': '블랙', 'size': '260', 'stock': 3, 'extra_price': 0, 'sku': 'A1'},
        {'color': '크림', 'size': '260', 'stock': 1, 'extra_price': 0, 'sku': 'A2'},
    ]), 10000)
    assert len(rows) == 2
    assert all(r['model'] == '' for r in rows)


def test_재고0_짝꿍은_오늘처럼_그대로_통과한다():
    """🔴 `options._normalize` 를 재사용했으면 여기서 깨졌다.

    품절 재입고를 두 줄로 적은 초안 — 재고 0 줄은 excluded 로 빠지고 한 줄만 남는다.
    이건 **오늘 멀쩡히 등록되는 모양**이다. 새 막이가 이걸 막으면 안 된다.
    """
    rows, excluded = _normalize_options(D([_행('블랙', '260', 0),
                                           _행('블랙', '260', 5)]), 10000)
    assert len(rows) == 1 and rows[0]['stock'] == 5
    assert len(excluded) == 1


def test_모델이_달라도_한_줄만_팔_수_있으면_안_막는다():
    """겹치지 않으면 이름도 안 겹친다 — 막을 까닭이 없다."""
    rows, excluded = _normalize_options(D([_행('블랙', '260', 0, '메이트'),
                                           _행('블랙', '260', 5, '스위트')]), 10000)
    assert len(rows) == 1 and rows[0]['model'] == '스위트'
    assert len(excluded) == 1


def test_색상_사이즈가_다르면_모델이_달라도_괜찮다():
    rows, _ = _normalize_options(D([_행('블랙', '260', 3, '메이트'),
                                    _행('크림', '260', 2, '스위트')]), 10000)
    assert len(rows) == 2
