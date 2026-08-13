# -*- coding: utf-8 -*-
"""모음전 전송은 **옵션 이름을 마켓에 보내지 않는다.**

## 이 파일이 있는 까닭

2026-08-13, 나는 여기에 `option_name_collision` 막이를 넣었다 —
「모델모음전 3축은 옵션 이름(색상+사이즈)이 겹치니 그 옵션만 전송 보류」.
**두 가지가 다 틀렸다.** 같은 실수를 다음 사람이 반복하지 않게 근거를 시험으로 남긴다.

### ① 겹쳐도 사고가 안 난다 — 이름은 안 나간다

`formatter/{smartstore,coupang,esm,lotteon}.py` 가 만드는 `option_name` 을
**읽는 코드가 0곳**이다. 전송은 `uploader/orchestrator._extract_uploads` 가 하는데
그것은 `option_id`·`add_price`·`stock` 만 읽는다.
그리고 `platforms/smartstore/edit_product.py` 는 「None 인 인자는 손대지 않는다」라
마켓에 있던 옵션 이름이 그대로 보존된다.

### ② 막이가 되레 라이브 전송을 통째로 멈출 수 있었다

`uploader/dryrun.py` 가

    warnings = len([a for a in alerts if a['level'] != 'info']) + len(alerts)

로 **warning 레벨을 두 번 센다.** 임계는 `orchestrator.py` 의 `warnings_threshold=5`.
→ 겹치는 묶음 **3개**면 6 > 5 → `should_hold` → **전 마켓·전 상품 `uploaded=0`.**
틀린 값을 막으려다 맞는 값까지 못 나가게 하는 막이였다.

## 진짜 막힘은 연동(linker)에 있다

3축으로 등록한 상품은 `platforms/smartstore/get_options.py` 가 `optionName3` 을 버려서
`uploader/linker.py` 가 못 짝지어 `unmatched` 가 되고, 가격·재고가 **에러 없이** 안 나간다.
그건 이 파일이 아니라 연동 시험이 다룬다.
"""
import inspect

from lemouton.formatter import pipeline as PIPE
from lemouton.uploader import orchestrator as ORCH


def test_전송은_옵션_이름을_안_읽는다():
    """🔴 막이의 전제가 거짓이었음을 못 박는다.

    `_extract_uploads` 가 만드는 dict 의 키에 이름이 없다 = 마켓에 이름이 안 나간다.
    """
    c_output = {'smartstore': {'M1': {
        'product_id': 'P1', 'base_price': 10000,
        'options': [
            {'option_id': 'O1', 'option_name': '블랙 250', 'add_price': 0, 'stock': 3},
            {'option_id': 'O2', 'option_name': '블랙 250', 'add_price': 0, 'stock': 2},
        ]}}}
    sku_by_option = {('smartstore', 'O1'): 'SKU-A', ('smartstore', 'O2'): 'SKU-B'}
    uploads = ORCH._extract_uploads(c_output, sku_by_option)

    assert len(uploads) == 2, '이름이 겹친다고 빠지면 안 된다'
    for u in uploads:
        assert 'option_name' not in u, f'이름이 전송에 실렸다: {u}'
    # 서로 다른 것으로 이어지는 열쇠는 **옵션 ID** 다.
    assert {u['market_option_id'] for u in uploads} == {'O1', 'O2'}
    assert {u['canonical_sku'] for u in uploads} == {'SKU-A', 'SKU-B'}


def test_이름이_겹쳐도_보류하지_않는다():
    """🔴 막이를 되살리면 여기서 잡힌다.

    `pipeline.py` 본문에 이름 기반 보류가 없어야 한다. 있으면 warning 이 쌓여
    `dryrun` 의 이중 계수 × 임계 5 에 걸려 **전 사이클이 멈춘다.**
    """
    본문 = inspect.getsource(PIPE)
    코드 = '\n'.join(l for l in 본문.splitlines() if not l.lstrip().startswith('#'))
    assert 'option_name_collision' not in 코드, (
        '이름 겹침 막이가 되살아났다 — 이 파일 맨 위 설명을 읽어라. '
        '이름은 마켓에 안 나가고, 이 알림은 전 사이클을 멈출 수 있다.')


def test_보류_임계가_warning_을_두_번_센다는_사실을_고정한다():
    """🔴 이건 **기존 배선**이다(내가 만든 게 아니다). 고치면 이 시험이 빨개진다 — 의도된 신호.

    warning 알림 한 건이 2로 세어지므로 **3건이면 6 > 5** 로 전 사이클이 멈춘다.
    formatter 에 warning 알림을 새로 넣으려는 사람은 이 값을 먼저 봐야 한다.
    """
    from lemouton.uploader.dryrun import compute_dryrun_summary
    alerts = [{'type': 't%d' % i, 'level': 'warning'} for i in range(3)]
    s = compute_dryrun_summary([], alerts, 5, 30.0)
    assert s.should_hold, (
        'warning 3건으로 안 멈춘다 — 이중 계수가 고쳐졌다면 이 시험과 '
        'pipeline.py 주석을 같이 갱신하라')

    # info 만으로도 6건이면 멈춘다 — 이것도 기존 배선이다.
    infos = [{'type': 'i%d' % i, 'level': 'info'} for i in range(6)]
    assert compute_dryrun_summary([], infos, 5, 30.0).should_hold, (
        'info 6건으로 안 멈춘다 — 계수 규칙이 바뀌었다')


def test_옵션_이름에_None_이_안_섞인다():
    """🔴 잠복 결함 — `d.get('color_display', d.get('color_code',''))` 는
    키가 **있고 값이 None** 이면 기본값이 안 나와 이름이 「None None」 이 된다.
    `merged` 는 `color_display` 키를 항상 만들고 값이 None 일 수 있다.
    지금은 이름을 아무도 안 읽어 무해하지만, 읽기 시작하는 날 터진다.
    """
    from lemouton.formatter import coupang as CP, esm as ESM, lotteon as LO, smartstore as SS
    for mod in (CP, ESM, LO, SS):
        src = inspect.getsource(mod)
        assert 'd.get("color_display", d.get(' not in src, (
            f'{mod.__name__}: 값이 None 이면 기본값이 안 나온다 — '
            f'`(d.get("color_display") or d.get("color_code") or "")` 로 쓸 것')
        assert 'd.get("size_display", d.get(' not in src, (
            f'{mod.__name__}: 사이즈도 같은 결함')
