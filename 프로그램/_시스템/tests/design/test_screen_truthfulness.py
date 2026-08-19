# -*- coding: utf-8 -*-
"""모순 감시기 — 화면이 하는 말이 데이터와 어긋나면 배포를 막는다.

■ 왜 필요한가 (2026-08-06)
  「판매 중 90」이 90개 전부 거짓이었는데 **시험 916개가 통과**하고 CI 도 초록이었다.
  그걸 찾은 건 사장님이 화면을 보고 「이건 아닌 것 같다」고 하신 것뿐이다.

  지금 시험들은 **함수가 도는지**를 본다. 여기 시험은 **화면이 사실을 말하는지**를 본다.
  사람 눈에 의존하지 않게 하는 게 목적이다.

■ 오늘 실제로 나온 거짓말 4종을 그대로 시험으로 박는다
  ① 마켓에 하나도 안 올라갔는데 「판매중」이라고 함
  ② 나눠 센 숫자의 합이 전체와 안 맞음 (막대와 목록이 어긋남)
  ③ 같은 뜻을 두 화면이 다른 말·다른 색으로 부름
  ④ 이미 만들었는데 「아직 안 만듦」이라고 함

■ 시험을 쓸 때 지킬 것 (오늘 두 번 데임)
  · 대상 데이터를 **직접 심고** 본다 — 없으면 아무것도 검사 안 하고 통과한다
  · 「없어야 한다」는 **눈에 보이는 글자**로 본다 — 원시 HTML 은 링크 주소까지 걸린다
  · 데이터 **양에 기대지 않는다** — 시험용 DB 는 거의 비어 있다
"""
import re
import uuid

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('MOUM_LIVE_UPLOAD', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


def _visible(html: str) -> str:
    """눈에 보이는 글자만 — 태그·스크립트·속성을 걷어낸다."""
    return re.sub(r'<[^>]*>', ' ',
                  re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', html))


@pytest.fixture
def 네상태표본():
    """4가지 상태를 **직접 심는다**.

    🔴 안 심으면 시험이 헛돈다. 실제로 이 파일 첫 판이 그랬다 — 옛 판정으로
       되돌려도 **그냥 통과**했다(검사할 상품이 없어서). 오늘만 세 번째다.

    ★ 넷 다 **상품번호(display_no)를 준다** — 옛 판정은 「상품번호가 있으면 판매중」
      이었으므로, 번호를 안 주면 옛 판정으로 되돌려도 결과가 같아 못 잡는다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.policy.models import BundlePolicyLink, MarketPolicy
    from lemouton.sourcing.models import Model, Option
    from lemouton.uploader.models import MarketRegistration

    tag = uuid.uuid4().hex[:6]
    plan = [(f'감시1_{tag}', False, False), (f'감시2_{tag}', True, False),
            (f'감시4_{tag}', False, True), (f'감시3_{tag}', True, True)]
    s = SessionLocal()
    pol = None
    codes, skus = [t[0] for t in plan], []
    try:
        pol = MarketPolicy(name=f'감시정책_{tag}')
        s.add(pol)
        s.flush()
        for i, (code, has_pol, has_mkt) in enumerate(plan):
            sku = f'SKU-W{tag.upper()}{i}'
            skus.append(sku)
            s.add(Model(model_code=code, model_name_raw=code,
                        model_name_display=code, brand=f'감시브랜드_{tag}',
                        display_no=f'M20260806-99{i:04d}'))
            s.add(Option(canonical_sku=sku, model_code=code,
                         color_code='블랙', size_code='250'))
            if has_pol:
                s.add(BundlePolicyLink(model_code=code, policy_id=pol.id))
            if has_mkt:
                s.add(MarketRegistration(canonical_sku=sku, market='coupang',
                                         market_product_id=f'CP-{tag}-{i}',
                                         status='synced'))
            # 🔴 매트릭스 줄도 심는다 — 없으면 옵션 목록·옵션관리 화면이 **비어서**
            #    사이드바 자체가 안 그려지고 시험이 헛돈다(실제로 그렇게 실패했다).
            s.add(MatrixOption(model_code=code, display_no=f'U-{tag}{i}',
                               name=code, kind=KIND_ORIGIN))
        s.commit()
        _캐시비우기()
        yield {'tag': tag, 'codes': codes}
    finally:
        s.rollback()
        s.query(MarketRegistration).filter(
            MarketRegistration.canonical_sku.in_(skus)).delete()
        s.query(BundlePolicyLink).filter(
            BundlePolicyLink.model_code.in_(codes)).delete()
        s.query(MatrixOption).filter(MatrixOption.model_code.in_(codes)).delete()
        s.query(Option).filter(Option.model_code.in_(codes)).delete()
        s.query(Model).filter(Model.model_code.in_(codes)).delete()
        if pol is not None:
            s.query(MarketPolicy).filter(MarketPolicy.id == pol.id).delete()
        s.commit()
        s.close()
        _캐시비우기()


def _캐시비우기():
    from webapp.routes import bundles_tower as T
    with T._cache_lock:
        T._sales_cache.clear()
        T._price_cache = None


# ═══════════════════════════════════════════════════════════════════════════
#  ① 마켓에 안 올라갔는데 「판매중」이라고 하지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_판매중은_마켓에_올라간_것만(client, 네상태표본):
    """🔴 되돌아오면 안 되는 원형 — 「판매 중 90」이 90개 전부 거짓이던 그 버그."""
    html = client.get('/bundles').get_data(as_text=True)
    assert 네상태표본['tag'] in html, '심은 표본이 목록에 없다 — 시험이 헛돈다'
    # 🔴 여는 태그까지 통째로 잡는다 — `data-stage` 는 <tr …> **속성**이라
    #    안쪽 내용만 잡으면 영영 못 찾아서 시험이 늘 통과한다(실제로 그랬다).
    rows = re.findall(r'(?s)(<tr class="row".*?</tr>)', html)
    거짓 = []
    for r in rows:
        stage = (re.search(r'data-stage="(\d+)"', r) or [None, ''])[1]
        올라간마켓 = len(re.findall(r'twr-mk y', r))
        code = (re.search(r'data-code="([^"]*)"', r) or [None, '?'])[1]
        # 3·4번 = 판매중. 마켓이 0인데 판매중이면 거짓말.
        if stage in ('3', '4') and 올라간마켓 == 0:
            거짓.append(f'{code}: 마켓 0개인데 {stage}번(판매중)')
        # 거꾸로 — 마켓이 있는데 1·2번(안 파는 것)이라 해도 거짓말.
        if stage in ('1', '2') and 올라간마켓 > 0:
            거짓.append(f'{code}: 마켓 {올라간마켓}개인데 {stage}번(판매 전)')
    assert not 거짓, '화면이 사실과 다르게 말한다:\n  ' + '\n  '.join(거짓[:10])


def test_판정은_정책과_마켓_두_사실로만(client):
    """상품번호(display_no) 같은 다른 것이 판정에 끼어들면 안 된다."""
    from webapp.routes.bundles_tower import (
        STAGE_MADE, STAGE_NOPOLICY_SELL, STAGE_POLICY, STAGE_SELLING, stage_of,
    )
    assert stage_of(False, False) == STAGE_MADE
    assert stage_of(True, False) == STAGE_POLICY
    assert stage_of(False, True) == STAGE_NOPOLICY_SELL
    assert stage_of(True, True) == STAGE_SELLING


# ═══════════════════════════════════════════════════════════════════════════
#  ② 나눠 센 숫자의 합이 전체와 맞는다 (막대 ↔ 목록)
# ═══════════════════════════════════════════════════════════════════════════

def test_네_상태_합이_전체와_표_행수와_모두_같다(client, 네상태표본):
    """🔴 막대는 12, 서랍은 9＋3 으로 갈렸던 그 문제."""
    html = client.get('/bundles').get_data(as_text=True)
    assert 네상태표본['tag'] in html, '심은 표본이 목록에 없다 — 시험이 헛돈다'
    블록 = re.search(r'(?s)<div class="stg-block".*?<div class="twr-card">', html)
    assert 블록, '「어디까지 왔나」 판을 못 찾음 — 화면 구조가 바뀌었나?'
    숫자 = [int(n.replace(',', '')) for n in
            re.findall(r'<span class="n">[^<]*?([\d,]+)\s*</span>', 블록.group(0))]
    assert len(숫자) >= 6, f'줄이 모자란다(전체+4상태+손볼것): {숫자}'
    전체, 네상태 = 숫자[0], 숫자[1:5]
    표행수 = len(re.findall(r'<tr class="row"', html))
    assert sum(네상태) == 전체 == 표행수, (
        f'합 {sum(네상태)} · 전체 {전체} · 표 {표행수} — 서로 안 맞는다')
    # 막대 토막도 목록과 같은 순서·같은 몫이어야 한다.
    #   상품이 0개면 폭이 전부 0% 라 style 이 안 붙는다 — 그건 어긋남이 아니다.
    막대 = [float(w) for w in
            re.findall(r'<i class="g\d"\s+style="width:\s*([\d.]+)%', 블록.group(0))]
    if 전체:
        assert len(막대) == 4, f'막대 토막이 4개가 아니다: {막대}'
        기대 = [round(n * 100.0 / 전체, 1) for n in 네상태]
        assert 막대 == 기대, f'막대가 목록과 다른 몫을 그린다: {막대} vs {기대}'


# ═══════════════════════════════════════════════════════════════════════════
#  ③ 같은 뜻은 두 화면이 같은 말·같은 색으로 부른다
# ═══════════════════════════════════════════════════════════════════════════

def test_상태_이름과_색은_한_곳에서만_온다():
    """🔴 초록이 두 화면에서 달랐던 그 문제 — 정의가 두 벌이면 반드시 갈린다."""
    from webapp.routes.bundles_tower import (
        STAGE_CLS, STAGE_LABEL, STAGE_LABEL_MATRIX, STAGES,
    )
    for st in STAGES:
        assert st in STAGE_LABEL and st in STAGE_LABEL_MATRIX and st in STAGE_CLS
    # 색은 두 화면이 **같은 것**을 써야 한다(한 벌)
    assert len(set(STAGE_CLS.values())) == len(STAGES), '두 상태가 같은 색을 쓴다'
    # 옵션매트릭스 말은 상품관리 말의 「적용」 판 — 뜻이 어긋나면 안 된다
    for st in STAGES:
        보통, 매트릭스 = STAGE_LABEL[st], STAGE_LABEL_MATRIX[st]
        꼬리 = 보통.split('상품 생성', 1)[-1]
        assert 매트릭스.endswith(꼬리), f'{st}번 말이 두 화면에서 갈린다: {보통} / {매트릭스}'


def test_옵션매트릭스가_옛말을_쓰지_않는다(client):
    """예전 「판매 중」·「아직 판매 안 함」은 마켓을 안 보고 하던 말이라 되살아나면 안 된다."""
    visible = _visible(client.get('/optgen/?tab=product').get_data(as_text=True))
    for 옛말 in ('아직 판매 안 함',):
        assert 옛말 not in visible, f'옛말이 되살아났다: {옛말}'


# ═══════════════════════════════════════════════════════════════════════════
#  ④ 이미 만들었으면 「아직 안 만듦」이라고 하지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_만든_묶음을_아직_안_만듦이라_하지_않는다(client):
    """🔴 그대로 두면 같은 묶음으로 상품을 두 번 만든다."""
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, BundleMatrixLink, MatrixOption
    from lemouton.sourcing.models import Model, Option

    tag = uuid.uuid4().hex[:8]
    box, made = f'감시상자_{tag}', f'감시상품_{tag}'
    s = SessionLocal()
    mo = None
    try:
        s.add(Model(model_code=box, model_name_raw=box, model_name_display=box,
                    brand='르무통', is_option_box=True))
        s.add(Option(canonical_sku=f'SKU-G{tag.upper()}', model_code=box,
                     color_code='블랙', size_code='250'))
        mo = MatrixOption(model_code=box, display_no=f'U-{tag}', name=box,
                          kind=KIND_ORIGIN)
        s.add(mo)
        s.add(Model(model_code=made, model_name_raw='감시 상품',
                    model_name_display='감시 상품', brand='르무통',
                    display_no='M20260806-999001'))
        s.flush()
        s.add(BundleMatrixLink(model_code=made, matrix_option_id=mo.id,
                               copied_count=1))
        s.commit()

        html = client.get('/optgen/?tab=product').get_data(as_text=True)
        줄 = re.search(r'(?s)<tr class="og-row"[^>]*data-find="U-%s.*?</tr>' % tag, html)
        assert 줄, '심은 묶음이 목록에 없다 — 시험이 헛돈다'
        본문 = 줄.group(0)
        assert '아직 상품 생성 안 함' not in 본문, '만들었는데 안 만들었다고 한다'
        assert '감시 상품' in 본문, '만든 상품을 안 알려 준다'
    finally:
        s.rollback()
        if mo is not None:
            s.query(BundleMatrixLink).filter(
                BundleMatrixLink.matrix_option_id == mo.id).delete()
            s.query(MatrixOption).filter(MatrixOption.model_code == box).delete()
        s.query(Option).filter(Option.model_code == box).delete()
        s.query(Model).filter(Model.model_code.in_([box, made])).delete()
        s.commit()
        s.close()


# ═══════════════════════════════════════════════════════════════════════════
#  ⑤ 화면이 가리키는 곳은 실제로 열린다 (링크가 헛도는 것 금지)
# ═══════════════════════════════════════════════════════════════════════════

def test_0건일_때_왜_0인지_말한다(client, 네상태표본):
    """🔴 「모음전 상품 0」만 띄우면 사장님이 「없다」로 읽고 같은 상품을 또 만든다.

    실제로 그럴 뻔했다 — 「상품 생성」으로 거른 채 새로 만든 상품(「＋정책 적용」)을
    찾다가 0건이 떠서 「아직 없나?」 하고 물으셨다.

    화면에 ① 왜 0인지 적을 자리 ② 거르기만 푸는 단추 가 있어야 한다.

    ⚠️ 표본을 **심어야** 한다 — 상품이 0개면 화면이 「아직 등록한 상품이 없어요」
       쪽으로 갈라져 이 자리가 아예 안 그려지고, 시험이 헛돈다(실제로 그랬다).
    """
    html = client.get('/bundles').get_data(as_text=True)
    assert 네상태표본['tag'] in html, '심은 표본이 목록에 없다 — 시험이 헛돈다'
    for 표식 in ('id="twr-zero"', 'id="twr-zero-why"', 'id="twr-zero-clear"'):
        assert 표식 in html, f'0건 안내 자리가 없다: {표식}'
    assert 'zeroHint' in html, '0건일 때 이유를 채우는 코드가 없다'
    # 「거르기 풀고 다시 찾기」는 **찾는 말을 지우면 안 된다** — 다시 쳐야 하니까
    풀기 = re.search(r"(?s)zc\.addEventListener\('click'.*?\}\);", html)
    assert 풀기, '거르기 푸는 단추에 동작이 안 붙었다'
    assert 'state.q' not in 풀기.group(0), '거르기를 풀면서 찾던 말까지 지운다'


def test_상품관리_서랍의_링크가_실제로_열린다(client):
    """🔴 「→ 그 상품으로」라고 해놓고 안 가던 링크가 있었다(내가 만들었다).

    글자가 맞는지가 아니라 **눌러서 도착하는지**를 본다.
    """
    # 🔴 <script> 를 먼저 걷어낸다 — JS 안의 `'/optgen/product/' + id` 같은 **조각**이
    #    href 처럼 잡혀 없는 주소를 두드리게 된다(내 첫 시험이 그렇게 헛짚었다).
    html = re.sub(r'(?s)<script\b.*?</script>', ' ',
                  client.get('/bundles').get_data(as_text=True))
    링크 = set(re.findall(r'<a[^>]+href="(/[^"#?][^"]*)"', html))
    죽은링크 = []
    for href in sorted(링크)[:25]:            # 목록 화면의 붙박이 링크만(상품 90개 제외)
        if href.startswith(('/static/', '/api/')) or "'" in href or '+' in href:
            continue
        r = client.get(href)
        if r.status_code >= 400:
            죽은링크.append(f'{href} → {r.status_code}')
    assert not 죽은링크, '눌러도 안 열리는 링크:\n  ' + '\n  '.join(죽은링크)


# ═══════════════════════════════════════════════════════════════════════════
#  ⑥ 두 화면의 사이드바가 **같은 판**이다 (사장님 첫 지시 「사이드바에도 구분하자」)
# ═══════════════════════════════════════════════════════════════════════════
#  🔴 [이슈 #1090] 「옵션 목록」(/optgen/?tab=product)은 이 판에서 **빠졌다** —
#     사장님 확정으로 이 화면은 이제 위상과 무관하게 모든 옵션매트릭스를 늘
#     보여줘야 해서(파생으로 상품을 여러 번 만들 수 있어야 함), 위상별로 좁혀
#     보는 「어디까지 왔나」 판 자체가 그 목적과 안 맞는다. 대신 그 화면은
#     「상품&정책 연결상태」 칼럼(막대 채우기)으로 바뀌었고, 그 칼럼은
#     `tests/catalog/test_optgen_product_panel.py` 가 지킨다. 여기 두 화면
#     (상품관리·옵션관리)은 여전히 같은 판을 써야 하므로 계속 지킨다.

def test_두_화면_사이드바가_같은_판이다(client, 네상태표본):
    """🔴 상품관리에만 넣고 옵션관리 쪽엔 안 넣어 반쪽이었다 — 되풀이 금지.

    두 화면이 같은 모양·같은 말이어야 오가며 봐도 안 헷갈린다.
    """
    화면 = {'상품관리': '/bundles',
            '옵션관리': '/matrix/'}
    빠진곳 = []
    for 이름, url in 화면.items():
        html = client.get(url).get_data(as_text=True)
        # 🔴 그냥 'stg-block' 을 찾으면 **CSS 규칙에도 그 글자가 있어** 판을 빼도
        #    통과한다(실제로 그렇게 새어 나갔다). 스타일을 걷어낸 **마크업**으로 센다.
        몸통 = re.sub(r'(?s)<style\b.*?</style>', ' ', html)
        if 'class="stg-block' not in 몸통:
            빠진곳.append(f'{이름}({url}): 「어디까지 왔나」 판 없음')
            continue
        if '어디까지 왔나' not in 몸통:
            빠진곳.append(f'{이름}: 판 제목 없음')
        if 'class="stg-bar' not in 몸통:
            빠진곳.append(f'{이름}: 막대 없음')
        # 4가지 상태가 **실제 줄**로 있어야 한다
        줄 = set(re.findall(r'class="stg-row t(\d)"', 몸통))
        if not {'1', '2', '3', '4'} <= 줄:
            빠진곳.append(f'{이름}: 4상태 줄이 모자람 {sorted(줄)}')
        # 숫자 알약 — 「눌러도 되는 줄」 신호(시안 v12 5안 확정). 이건 CSS 규칙이 맞다.
        if '.stg-row .n{background:var(--ap-g1' not in html:
            빠진곳.append(f'{이름}: 숫자 알약 규칙 없음')
    assert not 빠진곳, '사이드바가 화면마다 다르다:\n  ' + '\n  '.join(빠진곳)


# 🔴 [이슈 #1090] 옛 `test_옵션_두_화면이_같은_말을_쓴다`(옵션 목록·옵션관리가
#    「상품 생성 적용」계열 라벨을 같이 쓰는지)는 지웠다 — 「옵션 목록」
#    (/optgen/?tab=product)이 그 라벨 계열(STAGE_LABEL_MATRIX)을 더는 안 쓰게
#    되면서 비교할 두 번째 화면이 없어졌다(옵션관리 혼자 남아 "두 화면이 같다"는
#    이 시험의 전제 자체가 성립하지 않는다). 「옵션 목록」이 지금 실제로 쓰는
#    말(상품 생성 N개·정책 적용 M/N)은 `tests/catalog/test_optgen_product_panel.py`
#    가 지킨다.


def test_옵션관리_판_숫자가_보이는_수와_같다(client, 네상태표본):
    """🔴 판이 「89」라 해놓고 눌러도 3개만 나왔다 — 숨긴 묶음을 같이 셌기 때문.

    판 숫자는 **화면에 실제로 보이는 것**만 세야 한다. 숨긴 묶음(단독_·빈 묶음)은
    기본으로 안 보이므로 기본 숫자에서 빠지고, 「숨긴 묶음 보기」를 켰을 때만 들어간다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Model, Option

    # 🔴 **숨긴 묶음을 반드시 심는다.** 없으면 「숨긴 것까지 세도」 차이가 안 나
    #    옛 방식으로 되돌려도 그냥 통과한다(실제로 그렇게 새어 나갔다 — 오늘 다섯 번째).
    tag = 네상태표본['tag']
    숨김코드 = f'단독_SKU-HID{tag.upper()}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=숨김코드, model_name_raw=숨김코드,
                    model_name_display=숨김코드, brand='르무통'))
        s.add(Option(canonical_sku=f'SKU-HID{tag.upper()}', model_code=숨김코드,
                     color_code='블랙', size_code='250'))
        s.add(MatrixOption(model_code=숨김코드, display_no=f'U-HID{tag}',
                           name=숨김코드, kind=KIND_ORIGIN))
        s.commit()

        html = client.get('/matrix/').get_data(as_text=True)
        몸통 = re.sub(r'(?s)<style\b.*?</style>', ' ', html)
        assert 네상태표본['tag'] in 몸통, '심은 표본이 목록에 없다 — 시험이 헛돈다'
        assert 'data-hid="1"' in 몸통, '숨긴 묶음이 하나도 없다 — 이 시험이 헛돈다'
        _판_숫자_대조(몸통, html)
    finally:
        s.rollback()
        s.query(MatrixOption).filter(MatrixOption.model_code == 숨김코드).delete()
        s.query(Option).filter(Option.model_code == 숨김코드).delete()
        s.query(Model).filter(Model.model_code == 숨김코드).delete()
        s.commit()
        s.close()


def _판_숫자_대조(몸통, html):

    # 화면에 실제로 그려진 줄 중 「숨김이 아닌 것」을 상태별로 센다
    보임 = {}
    for tr in re.findall(r'(?s)<tr class="glr".*?</tr>', 몸통):
        if re.search(r'data-hid="1"', tr):
            continue
        st = (re.search(r'data-stage="([^"]*)"', tr) or [None, ''])[1]
        보임[st] = 보임.get(st, 0) + 1

    판 = {}
    블록 = re.search(r'(?s)<div class="stg-block" id="mx-stages">.*?\n      </div>', 몸통)
    assert 블록, '「어디까지 왔나」 판을 못 찾음'
    for row in re.findall(r'(?s)<div class="stg-row[^>]*data-s="([^"]*)"[^>]*data-n="(\d+)"',
                          블록.group(0)):
        판[row[0]] = int(row[1])
    assert 판, '판 줄에 숫자가 안 실렸다'

    어긋남 = []
    for key, n in 판.items():
        if key == '':                       # 머리줄 = 전체
            if n != sum(보임.values()):
                어긋남.append(f'전체: 판 {n} · 보임 {sum(보임.values())}')
        elif n != 보임.get(key, 0):
            어긋남.append(f'{key}번: 판 {n} · 보임 {보임.get(key, 0)}')
    assert not 어긋남, '판 숫자와 실제 보이는 수가 다르다:\n  ' + '\n  '.join(어긋남)

    # 「숨긴 묶음 보기」를 켰을 때 쓸 숫자(data-nh)도 실려 있어야 한다
    assert 'data-nh=' in 블록.group(0), '숨김 포함 숫자가 없어 토글해도 안 바뀐다'
    # 🔴 이름만 찾으면 `syncStageCountsX` 같은 **부분 일치**로 통과한다(실제로 그랬다).
    #    「숨김 토글이 눌렸을 때 실제로 부른다」는 배선을 본다.
    assert re.search(r"c\.addEventListener\('change',\s*function\s*\(\)\s*\{\s*"
                     r"syncStageCounts\(\);\s*apply\(\);", html), \
        '숨김 토글에 숫자 갱신(syncStageCounts)이 안 붙었다'
    assert re.search(r'function syncStageCounts\(\)\s*\{', html), \
        'syncStageCounts 함수가 없다'


@pytest.fixture
def 옵션함인데_마켓등록():
    """라이브에서 잡힌 그 상황 — **옵션함인데 그 코드가 마켓에 올라가 있다.**

    2026-08-07 실측: 「르무통 스위트 메리제인」·「SKU-484B2862」 두 줄이
    표에는 「아직 상품 생성 안 함」인데 판은 `stage`(마켓 등록·판매중)로 세었다.
    둘 다 상품관리에는 없는 물건이라 표가 맞고 판이 틀렸다.
    """
    import app as appmod                     # noqa: F401
    from shared.db import SessionLocal, init_db
    init_db()
    from lemouton.matrix.models import KIND_ORIGIN, MatrixOption
    from lemouton.sourcing.models import Model, Option
    from lemouton.uploader.models import MarketRegistration

    tag = uuid.uuid4().hex[:6]
    code = f'옵션함_{tag}'
    s = SessionLocal()
    try:
        s.add(Model(model_code=code, model_name_raw=f'옵션함표본_{tag}',
                    model_name_display=f'옵션함표본_{tag}',
                    brand='감시', is_option_box=True, display_no=f'N{tag}'))
        s.add(Option(canonical_sku=f'SKU_{tag}', model_code=code,
                     color_code='블랙', size_code='250'))
        s.add(MatrixOption(model_code=code, name=f'옵션함표본_{tag}',
                           kind=KIND_ORIGIN, display_no=f'U{tag}'))
        s.add(MarketRegistration(canonical_sku=f'SKU_{tag}', market='smartstore',
                                 market_product_id=f'MP{tag}', status='synced'))
        s.commit()
        yield {'code': code, 'tag': tag}
    finally:
        s.query(MarketRegistration).filter(
            MarketRegistration.canonical_sku == f'SKU_{tag}').delete(synchronize_session=False)
        for 표 in (MatrixOption, Option, Model):
            s.query(표).filter(표.model_code == code).delete(synchronize_session=False)
        s.commit()
        s.close()


def _글자만(h: str) -> str:
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', h)
    return re.sub(r'<[^>]*>', ' ', h)


def test_옵션생성_판이_표에_적힌_글자를_센다(client, 옵션함인데_마켓등록):
    """🔴 판은 `stage` 로 세는데 표는 「옵션함인가」로 글자를 골라 서로 다른 말을 했다.

    판에 「아직 상품 생성 안 함 0」인데 표에는 그 글자가 52줄이었다(라이브 실측).
    세는 기준과 보여주는 기준이 한 벌이어야 한다.
    """
    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    assert 옵션함인데_마켓등록['tag'] in html, '심은 표본이 화면에 없다 — 시험이 헛돈다'

    # 표에 실제로 그려진 배지 글자를 센다(속성·CSS 아닌 **보이는 글자**)
    배지 = re.findall(r'<span class="og-badge[^"]*stgb[^"]*">([^<]+)</span>', html)
    보임 = {}
    for b in 배지:
        보임[b.strip()] = 보임.get(b.strip(), 0) + 1
    assert 보임, '표에 상태 배지가 하나도 없다 — 시험이 헛돈다'

    # 판 줄: 글자 → 숫자
    판 = dict(re.findall(
        r'<div class="stg-row[^"]*" data-s="[^"]*">\s*'
        r'<span class="lb">([^<]+)</span><span class="n">(\d+)</span>', html))

    어긋남 = [f'「{글}」: 판 {수} · 표 {보임.get(글, 0)}'
              for 글, 수 in 판.items() if int(수) != 보임.get(글, 0)]
    assert not 어긋남, '판 숫자와 표에 적힌 글자 수가 다르다:\n  ' + '\n  '.join(어긋남)


def test_옵션함은_판매중으로_세지_않는다(client, 옵션함인데_마켓등록):
    """옵션함은 상품관리에 없다 — 그런데 「판매중」으로 세면 없는 물건이 판매중이 된다."""
    from webapp.routes.bundles_tower import STAGE_LABEL_MATRIX, SELLING_STAGES
    html = client.get('/optgen/?tab=product').get_data(as_text=True)
    글 = _글자만(html)
    tag = 옵션함인데_마켓등록['tag']
    assert tag in 글, '심은 표본이 화면 글자에 없다 — 시험이 헛돈다'
    판 = dict(re.findall(
        r'<div class="stg-row[^"]*" data-s="[^"]*">\s*'
        r'<span class="lb">([^<]+)</span><span class="n">(\d+)</span>', html))
    for st in SELLING_STAGES:
        assert int(판.get(STAGE_LABEL_MATRIX[st], 0)) == 0, (
            f'옵션함뿐인데 「{STAGE_LABEL_MATRIX[st]}」 가 {판.get(STAGE_LABEL_MATRIX[st])} 이다')


def _템플릿(path: str) -> str:
    """템플릿 원문 — 화면 CSS 를 그대로 읽는다."""
    import pathlib
    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    return (뿌리 / path).read_text(encoding='utf-8')


def test_단계판_사이드바가_글자를_안_자른다():
    """🔴 「한 줄로 보이게」(사장님 지시)라 라벨에 `nowrap` 을 걸었는데, 사이드바 폭이
       **고정**이면 긴 라벨이 숫자를 덮고 카드 밖으로 삐져나온다.

    2026-08-07 라이브 실측(사장님 화면 1870px): 옵션매트릭스 사이드바 240px 인데
    「상품 생성 적용 + 마켓 등록 (판매중) ※ 정책 미적용」 은 256px → **142px 삐져나옴**.
    상품관리는 폭을 풀어 뒀는데 나머지 두 화면에 안 해서 거기만 깨졌다
    — 같은 함정을 한 곳만 막으면 남은 곳이 터진다.
    """
    자리 = (('webapp/templates/bundles/tower.html', '.twr-sb{'),
            ('webapp/templates/matrix/index.html', '.gl-sb{'),
            ('webapp/templates/optgen/index.html', '.og-rail{'))
    안된곳 = []
    for path, 선택자 in 자리:
        css = _템플릿(path)
        i = css.find(선택자)
        assert i >= 0, f'{path} 에 {선택자} 규칙이 없다 — 시험이 헛돈다'
        규칙 = css[i:i + 400]
        if 'width:max-content' not in 규칙.replace(' ', ''):
            안된곳.append(f'{path} {선택자} — 폭이 글자에 안 맞춰진다')
    assert not 안된곳, '사이드바가 고정폭이라 긴 라벨이 잘린다:\n  ' + '\n  '.join(안된곳)

    # 바깥 격자도 같이 풀려 있어야 max-content 가 실제로 넓어진다
    격자 = (('webapp/templates/bundles/tower.html', '.twr-app{'),
            ('webapp/templates/matrix/index.html', '.gl-app{'),
            ('webapp/templates/optgen/index.html', '.og-wrap{'))
    고정 = []
    for path, 선택자 in 격자:
        css = _템플릿(path)
        i = css.find(선택자)
        assert i >= 0, f'{path} 에 {선택자} 가 없다 — 시험이 헛돈다'
        규칙 = css[i:i + 200].replace(' ', '')
        if 'grid-template-columns:autominmax(0,1fr)' not in 규칙:
            고정.append(f'{path} {선택자} — 첫 칸이 고정폭이라 사이드바가 못 넓어진다')
    assert not 고정, '\n  '.join(고정)


# ── [2026-08-13] 한 화면 안에서 가로 상한이 갈리면 오른쪽 끝이 어긋난다 ──────

def test_한_화면_안에서_가로_상한이_안_갈린다():
    """🔴 검색카드·표·안내상자가 **같은 줄에 세로로 쌓이는데** 상한이 다르면
       오른쪽 끝이 어긋나 보인다.

    실제로 두 번 겪었다:
      · 처음 — 검색창 1100 · 표 1452 (표는 내용이 길면 상한을 넘는다) → 352 어긋남
      · 고친 뒤 — 카드·목록만 1700 으로 올리고 「찾은 상품이 없습니다」 상자를
        1100 에 두고 가서, **결과가 0건일 때** 최대 600px 어긋남(창 1920 실측).

    그래서 이 화면들엔 **박아 넣은 1100 이 하나도 없어야** 한다 — 공용 값을 쓴다.
    """
    import pathlib
    import re

    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    for 경로 in ('webapp/templates/optgen/_market_pane.html',
                 'webapp/templates/optgen/index.html'):
        css = (뿌리 / 경로).read_text(encoding='utf-8')
        박힌것 = re.findall(r'max-width:\s*1100px', css)
        assert not 박힌것, (
            f'{경로} 에 박아 넣은 가로 상한 1100 이 {len(박힌것)}곳 남아 있다 — '
            '한 화면 안에서 오른쪽 끝이 어긋난다. 공용 값(--화면-상한)을 쓸 것')


def test_화면_가로_상한이_한_곳에서_정해진다():
    """상한을 파일마다 박으면 다음에 또 갈린다 — 공용 값 한 곳에서 정한다."""
    import pathlib

    뿌리 = pathlib.Path(__file__).resolve().parents[2]
    토큰 = (뿌리 / 'webapp/static/tokens.css').read_text(encoding='utf-8')
    assert '--화면-상한:' in 토큰, '공용 가로 상한 값이 없다'
    for 경로 in ('webapp/templates/optgen/_market_pane.html',
                 'webapp/templates/optgen/index.html'):
        css = (뿌리 / 경로).read_text(encoding='utf-8')
        assert 'var(--화면-상한)' in css, f'{경로} 가 공용 상한을 안 쓴다'
