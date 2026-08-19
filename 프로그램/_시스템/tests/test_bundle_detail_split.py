"""회귀 방지 가드 — 「모음전 상세」 4조각 분리 (설계서 §4 · 2026-08-02).

한 화면에 섞여 있던 가격·크롤·옵션·기본정보를 노션 8분류대로 나눠 열게 했다.
🔴 템플릿을 물리적으로 자르지 않는다 — `_matrix_v3.html` 의 6,000줄짜리 <script>
   한 덩어리가 트리·격자·크롤 카드를 한꺼번에 그리므로, 잘라 옮기면 서로를 못 찾아
   죽는다. 그래서 DOM 은 다 싣고 `data-piece` 로 **보여줄 조각만 고른다**.

이 테스트가 지키는 것 = 「어느 조각이 어느 메뉴 것인가」의 배정.
누가 나중에 템플릿을 손보다 data-piece 를 떨어뜨리면 즉시 빨갛게 만든다.
화면(UI)은 건드리지 않는 순수 구조 가드.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDIT = ROOT / "webapp" / "templates" / "bundles" / "edit.html"
MTX = ROOT / "webapp" / "templates" / "bundles" / "_matrix_v3.html"
ROUTES = ROOT / "webapp" / "routes" / "bundles.py"


def _edit() -> str:
    return EDIT.read_text(encoding="utf-8")


def _mtx() -> str:
    return MTX.read_text(encoding="utf-8")


def _routes() -> str:
    return ROUTES.read_text(encoding="utf-8")


# ── 조각 배정표 — 설계서 §4 그대로. 여기가 단일 진실 원천이다. ──────────────
#   (마커, 어느 조각 것인가, 어느 파일에 있는가)
ASSIGNMENT = [
    ('id="sec-basic"',                   'home',  'edit'),
    ('id="sec-combo"',                   'home',  'edit'),
    ('id="sec-market"',                  'price', 'edit'),   # 마켓 등록·업로드
    ('id="sec-runs"',                    'crawl', 'edit'),   # 실행 이력
    # [2026-08-13 사장님 확정] 「마켓 옵션 축 구성(고급)」 패널은 지웠다 —
    #   고르셔도 마켓에 나가는 것이 한 글자도 안 바뀌었다(저장만 됨).
    #   축은 상품가공 「옵션 축 구성」 한 곳에서만 정한다.
    ('id="bulk-policy-bar"',             'price', 'mtx'),    # 가격 템플릿·사올 때·팔 때
    ('id="global-actions"',              'crawl', 'mtx'),    # 전체 크롤 CTA
    ('id="sm-side-h"',                   'crawl', 'mtx'),    # 소싱처 진행 카드·최저가 1위
    ('id="cluster-panel"',               'opt',   'mtx'),
    ('id="price-bulk-bar"',              'opt',   'mtx'),
    ('id="matrix-v9-layout"',            'opt',   'mtx'),    # 옵션 트리·실제 매입가 격자
]


def test_모든_조각이_제_메뉴에_배정돼_있다():
    """설계서 §4 배정표대로 data-piece 가 붙어 있어야 한다."""
    texts = {'edit': _edit(), 'mtx': _mtx()}
    for marker, piece, where in ASSIGNMENT:
        t = texts[where]
        i = t.find(marker)
        assert i >= 0, f"{marker} 가 사라졌다 ({where})"
        # 같은 여는 태그 안에 data-piece 가 있어야 한다
        tag_end = t.find('>', i)
        tag = t[t.rfind('<', 0, i):tag_end]
        m = re.search(r'data-piece="([^"]+)"', tag)
        assert m, f"{marker} 에 data-piece 가 없다 — 조각 배정이 빠졌다"
        assert piece in m.group(1).split(), (
            f"{marker} 는 '{piece}' 조각이어야 하는데 '{m.group(1)}' 로 돼 있다")


def test_조각을_고르는_스위치가_살아있다():
    """data-piece 를 실제로 켜고 끄는 코드가 있어야 한다 — 속성만 남으면 무용지물."""
    t = _edit()
    assert 'BUNDLE_PIECE' in t, "조각 스위치(BUNDLE_PIECE)가 사라짐"
    assert "querySelectorAll('[data-piece]')" in t, "조각 필터가 사라짐"
    assert '.piece-off' in t, "감추는 클래스(.piece-off) 정의가 사라짐"


def test_감추기는_important_라야_한다():
    """🔴 이 화면의 JS 가 sm-side-h 등에 인라인 display 를 직접 찍는다.
    !important 가 없으면 크롤이 끝나는 순간 감춰둔 조각이 되살아난다."""
    t = _edit()
    m = re.search(r'\.piece-off\s*\{([^}]*)\}', t)
    assert m, ".piece-off 규칙을 못 찾음"
    assert '!important' in m.group(1), (
        ".piece-off 에 !important 가 없다 — JS 가 찍는 인라인 display 를 못 이긴다")


def test_조각_모드에선_옛_3단계_탭이_안_뜬다():
    """탭과 조각이 같이 뜨면 둘이 서로 덮어써 화면이 널뛴다."""
    t = _edit()
    assert '{% if not piece %}' in t, "조각 모드에서 3단계 탭을 감추는 조건이 사라짐"
    assert 'if (BUNDLE_PIECE) return;' in t, "조각 모드에서 showTab 이 안 멈춘다"


def test_네_입구가_다_있다():
    """메뉴마다 제 조각으로 들어가는 URL 이 있어야 한다."""
    t = _routes()
    for rule, piece in [("'/bundles/<code>'", "'home'"),
                        ("'/policies/product/<code>'", "'price'"),
                        ("'/automation/product/<code>'", "'crawl'"),
                        ("'/matrix/product/<code>'", "'opt'")]:
        assert rule in t, f"입구 {rule} 가 없다"
        assert piece in t, f"조각 {piece} 를 부르는 곳이 없다"


def test_나누기_전_화면도_남아있다():
    """되돌아볼 자리 — 한 장에 전부 보는 URL 은 지우지 않는다."""
    assert "'/bundles/<code>/all'" in _routes(), "한 장에 전부 보기(/all) 가 사라짐"


def test_옵션_고치는_입구는_하나다():
    """[규칙 12] 옵션을 짜는 곳은 📥 옵션생성 한 곳뿐.
    모음전 상세가 모달을 또 띄우면 같은 일을 하는 문이 둘이 된다."""
    t = _edit()
    assert 'data-action="step-design"' not in t, (
        "모음전 상세에 옛 입구(옵션 조합 모달)가 되살아났다 — 규칙 12 위반")
    assert '/optgen/box/' in t, "새 입구(/optgen/box/) 링크가 없다"
