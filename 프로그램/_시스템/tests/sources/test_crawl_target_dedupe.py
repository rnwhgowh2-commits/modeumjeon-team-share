"""크롤 대상 중복 제거 — 같은 소싱처의 같은 상품은 한 랩에 한 번만.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §2-2
사장님 확정: "소싱처에서 같은 상품 URL은 수집되지 않도록. 타 소싱처에서의 동일 상품은 괜찮음."
"""
import pytest

from lemouton.sources.crawl_target_dedupe import CrawlTarget, dedupe_targets


def T(source, pid, weight=1.0, composition="기본"):
    return CrawlTarget(source_key=source, product_id=pid, weight=weight,
                       composition=composition)


# ── 같은 소싱처 안에서 합친다 ────────────────────────────────────

def test_같은_소싱처_같은_상품은_한_건으로_합쳐진다():
    out = dedupe_targets([
        T("musinsa", "DD1391-100", composition="무신사>나이키"),
        T("musinsa", "DD1391-100", composition="무신사>스니커즈"),
    ])
    assert len(out) == 1
    assert out[0].source_key == "musinsa"
    assert out[0].product_id == "DD1391-100"


def test_합칠_때_계수는_높은_쪽을_따른다():
    out = dedupe_targets([
        T("musinsa", "DD1391-100", weight=1.0, composition="무신사>스니커즈"),
        T("musinsa", "DD1391-100", weight=2.0, composition="무신사>나이키"),
    ])
    assert out[0].weight == pytest.approx(2.0)


def test_합쳐도_어느_구성에서_왔는지_전부_남는다():
    """통계는 원래 구성마다 각각 기록해야 어느 구성이 바쁜지 알 수 있다."""
    out = dedupe_targets([
        T("musinsa", "DD1391-100", composition="무신사>나이키"),
        T("musinsa", "DD1391-100", composition="무신사>스니커즈"),
    ])
    assert set(out[0].compositions) == {"무신사>나이키", "무신사>스니커즈"}


def test_세_구성에_걸쳐도_한_건():
    out = dedupe_targets([
        T("musinsa", "X", weight=1.0, composition="A"),
        T("musinsa", "X", weight=3.0, composition="B"),
        T("musinsa", "X", weight=2.0, composition="C"),
    ])
    assert len(out) == 1
    assert out[0].weight == pytest.approx(3.0)
    assert len(out[0].compositions) == 3


# ── 타 소싱처는 합치지 않는다 (사장님 명시) ──────────────────────

def test_소싱처가_다르면_같은_상품이어도_각각_크롤한다():
    """소싱처마다 가격·혜택·재고가 다르므로 둘 다 필요하다."""
    out = dedupe_targets([
        T("musinsa", "DD1391-100", composition="무신사>나이키"),
        T("ssg", "DD1391-100", composition="SSG>나이키"),
    ])
    assert len(out) == 2
    assert {o.source_key for o in out} == {"musinsa", "ssg"}


# ── 상품 id 를 모르면 합치지 않는다 (조용한 실패 방지) ────────────

def test_상품id가_없으면_합치지_않는다():
    """id 가 None 인 것들을 한 덩어리로 합치면 **서로 다른 상품이 사라진다.**

    모르면 합치지 않는 쪽이 안전하다 — 중복 크롤은 낭비지만, 잘못 합치면 상품이 누락된다.
    """
    out = dedupe_targets([
        T("musinsa", None, composition="A"),
        T("musinsa", None, composition="B"),
    ])
    assert len(out) == 2


def test_빈_문자열_상품id도_합치지_않는다():
    out = dedupe_targets([
        T("musinsa", "", composition="A"),
        T("musinsa", "   ", composition="B"),
    ])
    assert len(out) == 2


def test_id있는_것과_없는_것은_섞이지_않는다():
    out = dedupe_targets([
        T("musinsa", "X", composition="A"),
        T("musinsa", None, composition="B"),
        T("musinsa", "X", composition="C"),
    ])
    assert len(out) == 2
    merged = [o for o in out if o.product_id == "X"][0]
    assert set(merged.compositions) == {"A", "C"}


# ── 정규화 ──────────────────────────────────────────────────────

def test_상품id_앞뒤_공백은_같은_것으로_본다():
    out = dedupe_targets([
        T("musinsa", "DD1391-100", composition="A"),
        T("musinsa", " DD1391-100 ", composition="B"),
    ])
    assert len(out) == 1


def test_소싱처키_대소문자는_같은_것으로_본다():
    out = dedupe_targets([
        T("MUSINSA", "X", composition="A"),
        T("musinsa", "X", composition="B"),
    ])
    assert len(out) == 1


def test_상품id_대소문자는_구분한다():
    """소싱처 상품코드는 대소문자가 의미를 가질 수 있어 함부로 접지 않는다."""
    out = dedupe_targets([
        T("musinsa", "abc", composition="A"),
        T("musinsa", "ABC", composition="B"),
    ])
    assert len(out) == 2


# ── 순서·기타 ───────────────────────────────────────────────────

def test_처음_나온_순서를_지킨다():
    out = dedupe_targets([
        T("musinsa", "A", composition="c1"),
        T("musinsa", "B", composition="c1"),
        T("musinsa", "A", composition="c2"),
    ])
    assert [o.product_id for o in out] == ["A", "B"]


def test_빈_목록은_빈_목록():
    assert dedupe_targets([]) == []


def test_중복이_없으면_그대로():
    src = [T("musinsa", "A"), T("musinsa", "B"), T("ssg", "A")]
    assert len(dedupe_targets(src)) == 3


def test_원본_참조를_들고_있다():
    """실제 크롤은 SourceProduct 객체가 필요하다. 계수가 높은 쪽 원본을 남긴다."""
    lo, hi = object(), object()
    out = dedupe_targets([
        CrawlTarget("musinsa", "X", weight=1.0, composition="A", ref=lo),
        CrawlTarget("musinsa", "X", weight=5.0, composition="B", ref=hi),
    ])
    assert out[0].ref is hi


def test_절감량을_셀_수_있다():
    """화면에 '중복 제거로 N회 아꼈습니다' 를 보이려면 원본 건수를 알아야 한다."""
    src = [T("musinsa", "X", composition="A"),
           T("musinsa", "X", composition="B"),
           T("musinsa", "Y", composition="A")]
    out = dedupe_targets(src)
    assert len(src) - len(out) == 1
