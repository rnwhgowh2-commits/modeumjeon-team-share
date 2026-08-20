# -*- coding: utf-8 -*-
"""현대H몰 — **화면이 아니라 받은 글(HTML)에서 읽어야** 한다.

━━ 라이브에서 드러난 것 (2026-08-08) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 프로그램에서 H몰에 **6쪽**을 시켰는데 결과가 **36개**였다(1쪽 분량).
`page=` 는 서버가 제대로 받는데도 그랬다.

`page=3` 을 열어 재 보니 —

    화면(DOM `[data-slitm-cd]`)  36개 · 앞 2개 = 2138715579, 2251878555
    받은 글(HTML `"slitmCd":`)   36개 · 앞 2개 = 2252212725, 2252481390
    **겹침 0**

즉 **서버는 3쪽을 보내는데 화면은 1쪽을 그린다.** 브라우저 안에서 앱이 다시
1쪽을 불러 화면을 덮어쓰기 때문이다. 그래서 6쪽을 열어도 화면은 늘 같은 36개였다.

━━ 그래서 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
H몰은 **받은 글에서 바로** 상품번호를 뽑는다(`html_scan`). 화면을 안 본다.

★ 왜 다른 곳은 그대로 두나 — 화면에서 읽는 편이 **눈에 보이는 것과 같다**는
  큰 장점이 있다(광고·배너가 화면에 없으면 안 걷힌다). H몰만 화면이 거짓말을
  하므로 H몰만 바꾼다. 🔴 추측으로 다른 곳까지 바꾸면 안 보이던 배너가 딸려 온다.
"""
from lemouton.sources.listing_discover import dom_rule_for, extract_product_urls


# 화면엔 없고 받은 글에만 있는 모양 — 우리 규칙이 이걸 읽어야 한다.
HMALL_HTML = '''
{"list":[{"slitmCd":"2252212725","name":"A"},{"slitmCd":"2252481390","name":"B"}]}
<div data-slitm-cd="2138715579">화면에 그려진 1쪽 상품 — 이건 3쪽이 아니다</div>
'''


def test_H몰은_받은_글에서_읽는다():
    r = dom_rule_for('hmall')

    assert r.get('html_scan') is True, r


def test_H몰_규칙이_JSON_속_상품번호를_잡는다():
    urls = extract_product_urls(HMALL_HTML, source_key='hmall')

    assert 'https://www.hmall.com/md/pda/itemPtc?slitmCd=2252212725' in urls, urls
    assert 'https://www.hmall.com/md/pda/itemPtc?slitmCd=2252481390' in urls, urls


def test_다른_곳은_화면에서_읽는다():
    """🔴 추측으로 바꾸면 화면에 없던 배너·광고가 딸려 온다.
    화면에서 읽는 편이 「눈에 보이는 것과 같다」는 장점이 있다.

    🔴 [2026-08-13] **`ssg` 를 이 목록에서 뺐다.** 이 시험을 쓸 때는 SSG 검색 화면을
      아무도 못 봤고(정책 차단), 「모르니까 화면에서 읽는다」로 두었을 뿐이다.
      라이브 실측이 그 전제를 뒤집었다 — **화면 상품 0개 / 받은 글 57개**
      (확장 0.7.96 진단). 근거는 `test_ssg_html_scan.py` 에 있다.

    ★ 통과하는 시험이 **「예전에 참이던 것」을 잠가 둘 수 있다.** 목록을 손으로 박아
      둘 때는 「무엇을 근거로 넣었나」를 함께 적어야 나중에 갱신 여부를 판단할 수 있다.
    """
    for key in ('musinsa', 'lotteon', 'lotteimall', 'ssf', 'lemouton'):
        assert dom_rule_for(key).get('html_scan') is not True, key
