# -*- coding: utf-8 -*-
"""소싱처 URL 집계(`lemouton/sourcing/source_url_stats.py`) 시험.

지켜야 할 것:
  · 원천은 `bundle_source_urls` + `option_source_url_links` (큰 창이 쓰는 표)
  · 🔴 URL 0개 = 「모른다」(None) — 완료로도 미완료로도 세지 않는다
  · 한 소싱처에 URL 이 여럿이면 **합집합** — SKU 가 어느 URL 에 붙었든 연결로 친다
  · 소싱처 하나라도 덜 됐으면 미완료, 그때 화면 분수도 「덜 된 쪽」을 말한다
  · 🔴 쿼리 수가 모델 줄 수와 무관하게 고정 (3줄이든 30줄이든 1개)
  · 🔴 코드가 아주 많으면 **잘라서** 묻는다 — 자르는 크기는 형제 모듈 한 곳에서만 온다
  · 🔴 분자는 분모를 못 넘는다 — 넘으면 잘라서 보이되 **조용히 넘어가지 않는다**
  · `source_labels` 는 세션을 안 받는다 (안 쓰는 인자를 받으면 거짓말이 된다)
"""
import inspect
import logging

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from shared.db import Base

# create_all 이 FK 타겟 테이블을 전부 찾도록 모델 등록 (tests/conftest 와 같은 이유)
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.matrix.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sourcing.source_url_stats import (
    mapping_coverage, source_labels, url_counts_by_source,
)


class _쿼리세기:
    """이 블록 안에서 실제로 나간 SQL 개수 (before_cursor_execute)."""

    def __init__(self, session):
        self.engine = session.get_bind()
        self.count = 0

    def _on_exec(self, *a, **k):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._on_exec)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._on_exec)
        return False


def _모델(db, code, sku수):
    db.add(M.Model(model_code=code, model_name_raw=code))
    skus = []
    for i in range(sku수):
        sku = f"{code}-블랙-{250 + i * 10}"
        db.add(M.Option(canonical_sku=sku, model_code=code,
                        color_code="블랙", size_code=str(250 + i * 10)))
        skus.append(sku)
    db.flush()
    return skus


def _url(db, code, source_key, url):
    u = M.BundleSourceUrl(model_code=code, source_key=source_key, url=url,
                          url_type="단품", sort_order=0)
    db.add(u)
    db.flush()
    return u


def _붙임(db, url_row, skus):
    for sku in skus:
        db.add(M.OptionSourceUrlLink(option_canonical_sku=sku,
                                     bundle_source_url_id=url_row.id))
    db.flush()


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


@pytest.fixture
def 심은세상(db):
    """소싱처 2곳 · URL 3개 · SKU 5개.

    · 무신사 — URL 2개. SKU 3개는 첫 URL, 2개는 둘째 URL → 합쳐서 5개 전부 (완료)
    · SSF   — URL 1개. SKU 2개만 (미완료)
    """
    skus = _모델(db, "AF", 5)
    u1 = _url(db, "AF", "musinsa", "https://musinsa.com/all")
    u2 = _url(db, "AF", "musinsa", "https://musinsa.com/gray")
    u3 = _url(db, "AF", "ssf", "https://ssfshop.com/x")
    _붙임(db, u1, skus[:3])
    _붙임(db, u2, skus[3:])
    _붙임(db, u3, skus[:2])
    db.commit()
    return {"code": "AF", "skus": skus}


def test_심은것이_실제로_잡힌다(db, 심은세상):
    """시험용 DB 에 대상이 정말 들어갔는지 먼저 확인 — 안 그러면 아래 시험은 아무것도 안 본다."""
    assert db.query(M.BundleSourceUrl).filter_by(model_code="AF").count() == 3
    assert db.query(M.OptionSourceUrlLink).count() == 7
    assert db.query(M.Option).filter_by(model_code="AF").count() == 5


def test_소싱처별_URL수를_센다(db, 심은세상):
    got = url_counts_by_source(db, ["AF"])
    assert got["AF"] == [("musinsa", 2), ("ssf", 1)]      # source_key 오름차순 고정


def test_URL없는_모델도_빈목록으로_들어있다(db, 심은세상):
    _모델(db, "NEW", 3)
    db.commit()
    got = url_counts_by_source(db, ["AF", "NEW", "없는코드"])
    assert got["NEW"] == []
    assert got["없는코드"] == []


def test_맵핑_분수가_맞는다(db, 심은세상):
    """소싱처 2곳 중 무신사만 5·5 → 1·2 곳, 분수는 덜 된 SSF 기준 2·5."""
    got = mapping_coverage(db, ["AF"], {"AF": 5})["AF"]
    assert got["sources"] == 2
    assert got["sources_done"] == 1          # 🔴 SSF 는 2개만 붙었다
    assert got["skus"] == 5
    assert got["skus_done"] == 2             # 「가장 덜 된 소싱처」의 숫자
    assert got["complete"] is False          # 🔴 None 이 아니라 False


def test_URL이_여러개면_합집합으로_친다(db, 심은세상):
    """무신사는 SKU 가 두 URL 에 나뉘어 붙었지만 「최소 1개」 규칙으로 완료다.

    SSF 에도 남은 3개를 붙이면 두 소싱처 모두 완료 → complete True.
    """
    u3 = (db.query(M.BundleSourceUrl)
          .filter_by(model_code="AF", source_key="ssf").one())
    _붙임(db, u3, 심은세상["skus"][2:])
    db.commit()

    got = mapping_coverage(db, ["AF"], {"AF": 5})["AF"]
    assert got["sources"] == 2
    assert got["sources_done"] == 2
    assert got["skus_done"] == 5
    assert got["complete"] is True


def test_URL이_0개면_모른다(db):
    """🔴 완료(True)도 미완료(False)도 아니다 — 확인 불가(None)."""
    _모델(db, "EMPTY", 4)
    db.commit()

    got = mapping_coverage(db, ["EMPTY"], {"EMPTY": 4})["EMPTY"]
    assert got["complete"] is None
    assert got["complete"] is not False       # 「아니다」로 새지 않았는지 못 박는다
    assert got["sources"] == 0
    assert got["skus"] == 4
    assert got["skus_done"] == 0


def test_URL은_있는데_아무것도_안붙었으면_미완료(db):
    """소싱처 줄은 남아야 한다 — 안쪽 조인으로 사라지면 「전부 완료」로 둔갑한다."""
    _모델(db, "URLONLY", 2)
    _url(db, "URLONLY", "lotteon", "https://lotteon.com/x")
    db.commit()

    got = mapping_coverage(db, ["URLONLY"], {"URLONLY": 2})["URLONLY"]
    assert got["sources"] == 1
    assert got["sources_done"] == 0
    assert got["skus_done"] == 0
    assert got["complete"] is False


def test_SKU가_0개면_모른다(db):
    """🔴 0·0 을 「다 됐다」로 적으면 빈 매트릭스가 초록불이 된다."""
    db.add(M.Model(model_code="NOSKU", model_name_raw="NOSKU"))
    db.flush()
    _url(db, "NOSKU", "musinsa", "https://musinsa.com/y")
    db.commit()

    got = mapping_coverage(db, ["NOSKU"], {"NOSKU": 0})["NOSKU"]
    assert got["complete"] is None
    assert got["skus"] == 0


def test_남의_모델_옵션은_분자에_안_들어간다(db, 심은세상):
    """다른 모델 SKU 가 이 URL 에 붙어 있어도 「7·5」 같은 분수가 되면 안 된다."""
    남 = _모델(db, "OTHER", 2)
    u1 = (db.query(M.BundleSourceUrl)
          .filter_by(model_code="AF", source_key="musinsa")
          .order_by(M.BundleSourceUrl.id).first())
    _붙임(db, u1, 남)
    db.commit()

    got = mapping_coverage(db, ["AF"], {"AF": 5})["AF"]
    assert got["skus_done"] == 2              # SSF 기준 그대로
    assert got["sources_done"] == 1           # 무신사는 여전히 5·5 (7·5 아님)


def test_쿼리수는_줄수와_무관하게_1개다(db, 심은세상):
    """🔴 N+1 방지가 이 모듈의 핵심 계약 — 3줄이든 30줄이든 같아야 한다."""
    codes = ["AF"]
    for i in range(30):
        code = f"BULK{i:02d}"
        skus = _모델(db, code, 3)
        u = _url(db, code, "musinsa", f"https://musinsa.com/{i}")
        _붙임(db, u, skus[:2])
        codes.append(code)
    db.commit()
    총계 = {c: 3 for c in codes}
    총계["AF"] = 5

    with _쿼리세기(db) as c3:
        url_counts_by_source(db, codes[:3])
    with _쿼리세기(db) as c30:
        url_counts_by_source(db, codes[:30])
    assert c3.count == c30.count == 1

    with _쿼리세기(db) as m3:
        got3 = mapping_coverage(db, codes[:3], 총계)
    with _쿼리세기(db) as m30:
        got30 = mapping_coverage(db, codes[:30], 총계)
    assert m3.count == m30.count == 1

    # 세는 김에 값도 맞는지 — 쿼리 1개로 줄여 놓고 답이 틀리면 의미가 없다
    assert len(got3) == 3 and len(got30) == 30
    assert got30["BULK00"]["skus_done"] == 2
    assert got30["BULK00"]["complete"] is False


# ── 🔴 IN 절 자르기 ─────────────────────────────────────────────────────────
#   이 화면(`webapp/routes/optgen.py:_box_facts`)은 옵션함을 **전부** 넘긴다 — 상한이
#   없다. 안 자르면 옵션함이 쌓인 날에만 조회가 통째로 실패한다: 개발할 땐 영영
#   멀쩡하고 라이브에서만 어느 날 갑자기 목록이 안 열리는, 제일 늦게 발견되는 사고다.

def _많은코드(db, 접두: str) -> tuple[list[str], str]:
    """묶음이 반드시 2개가 되는 코드 목록 + 값이 실제로 심긴 코드 하나.

    실물 하나를 섞는 이유 — 잘라 돌린 뒤 **합치면서 값을 잃지 않았는지**까지 봐야
    한다. 빈 코드만 세면 「조회 2번 나갔다」는 것만 알고 답이 맞는지는 못 본다.
    """
    from lemouton.matrix import readiness
    skus = _모델(db, f"{접두}-실물", 2)
    u = _url(db, f"{접두}-실물", "musinsa", f"https://musinsa.com/{접두}")
    _붙임(db, u, skus)
    codes = [f"{접두}-빈칸-{i:05d}" for i in range(readiness._CHUNK + 100)]
    codes.append(f"{접두}-실물")
    db.commit()
    return codes, f"{접두}-실물"


def test_코드가_많으면_잘라서_묻는다(db):
    """🔴 한 번의 IN 절에 넣는 값 개수에는 DB 상한이 있다 — 넘기면 목록이 통째로 실패한다.

    상한이 실제로 얼마인지와 「그런데 왜 그보다 훨씬 작게 자르는가」는
    `lemouton/matrix/readiness._CHUNK` 옆에 실측과 함께 적혀 있다. 여기서는
    **정말로 잘려 나가는지**만 조회 수로 못 박는다(묶음 2개 → 조회 2개).
    """
    codes, 실물 = _많은코드(db, "CUT")

    with _쿼리세기(db) as c:
        got_url = url_counts_by_source(db, codes)
    assert c.count == 2, f"{len(codes)}개를 조회 {c.count}번에 넣었다 — 안 잘리고 있다"

    with _쿼리세기(db) as m:
        got_map = mapping_coverage(db, codes, {실물: 2})
    assert m.count == 2, f"{len(codes)}개를 조회 {m.count}번에 넣었다 — 안 잘리고 있다"

    # 잘라 돌린 뒤 합치면서 값을 잃지 않았는지 — 조회만 늘고 답이 틀리면 의미가 없다
    assert len(got_url) == len(codes) and len(got_map) == len(codes)
    assert got_url[실물] == [("musinsa", 1)]
    assert got_map[실물]["complete"] is True and got_map[실물]["skus_done"] == 2
    assert got_url[codes[0]] == [] and got_map[codes[0]]["complete"] is None


def test_자르는_크기는_한_곳에서만_정한다(db, 심은세상):
    """🔴 500 이라는 숫자를 이 모듈이 또 적으면 안 된다.

    형제 모듈(`matrix/readiness`)의 값을 바꿨을 때 여기 조회 수가 **따라 바뀌어야**
    한다. 안 따라오면 숫자가 두 곳에 사는 것이고, 언젠가 한쪽만 고쳐져 그쪽 화면만
    라이브에서 계속 터진다.
    """
    from lemouton.matrix import readiness
    codes = ["AF"] + [f"CNT-{i:02d}" for i in range(5)]      # 6개

    def 재기(fn):
        with _쿼리세기(db) as c:
            fn()
        return c.count

    assert 재기(lambda: url_counts_by_source(db, codes)) == 1, "6개는 한 묶음이다"
    assert 재기(lambda: mapping_coverage(db, codes, {"AF": 5})) == 1

    원래 = readiness._CHUNK
    readiness._CHUNK = 2                    # 2개씩 자르면 6개 → 묶음 3개
    try:
        n1 = 재기(lambda: url_counts_by_source(db, codes))
        n2 = 재기(lambda: mapping_coverage(db, codes, {"AF": 5}))
    finally:
        readiness._CHUNK = 원래
    assert n1 == 3, f"형제 모듈 크기를 바꿨는데 안 따라온다 (실제 {n1}) — 숫자를 여기 또 적었다"
    assert n2 == 3, f"형제 모듈 크기를 바꿨는데 안 따라온다 (실제 {n2}) — 숫자를 여기 또 적었다"

    # 잘라도 답은 그대로여야 한다 — 크기를 줄인 채로 한 번 더 확인한다
    readiness._CHUNK = 2
    try:
        assert url_counts_by_source(db, codes)["AF"] == [("musinsa", 2), ("ssf", 1)]
        assert mapping_coverage(db, codes, {"AF": 5})["AF"]["skus_done"] == 2
    finally:
        readiness._CHUNK = 원래


def test_소싱처_이름표는_키가_없으면_키를_그대로_낸다(db):
    """없는 이름을 지어내지 않는다."""
    got = source_labels(["musinsa", "듣도보도못한곳"])
    assert got["musinsa"] == "무신사"
    assert got["듣도보도못한곳"] == "듣도보도못한곳"


# ── 지적 2 · 죽은 인자 ────────────────────────────────────────────────────────

def test_소싱처_이름표는_세션을_안_받는다():
    """🔴 안 쓰는 세션을 받아 놓으면 부르는 쪽이 「내 세션 안에서 돈다」고 잘못 읽는다.

    그렇게 읽으면 아직 커밋 안 한 소싱처 이름이 여기 보일 거라 기대하는데, 실제로는
    속의 `source_registry.get_all_sources()` 가 **항상 새 세션을 연다**(그 독스트링에
    「session 인자는 무시, 항상 새 session」이라 못 박혀 있다). 기대와 사실이 갈리면
    「이름 고쳤는데 화면이 그대로다」를 영영 못 찾는다.
    """
    params = list(inspect.signature(source_labels).parameters)
    assert "session" not in params, f"세션 인자가 아직 남아 있다: {params}"


def test_이름표에_세션을_넘기면_바로_알려준다(db):
    """🔴 `source_labels(db)` 는 막이가 없으면 **조용히 빈 답**을 낸다 — 그래서 막는다.

    왜 헷갈리나 — 같은 파일의 형제 둘(`url_counts_by_source` · `mapping_coverage`)은
    첫 인자가 세션이다. 그 흐름대로 `source_labels(db)` 라고 쓰면 세션이 `keys` 자리로
    들어간다. 그런데 SQLAlchemy 세션은 「하나씩 꺼내 볼 수 있는 것」이라 `_dedup(db)` 가
    에러 없이 빈 목록을 내고, 결과는 **`{}`** 다(막이를 빼고 직접 재서 확인했다).
    화면엔 소싱처 이름이 하나도 안 뜨는데 에러는 어디에도 안 남아, 원인을 못 찾는다.

    🔴 인자를 **하나만** 넘겨야 이 막이를 본다. 두 개(`source_labels(db, ["musinsa"])`)로
       부르면 함수 안에 들어가기도 전에 파이썬이 「인자 개수가 안 맞는다」며 TypeError 를
       낸다 — 그걸 잡는 시험은 **우리 코드를 한 줄도 안 보는 시험**이라, 막이를 통째로
       지워도 그대로 초록불이다. 그래서 오류 문구가 우리 것인지까지 확인한다.
    """
    with pytest.raises(TypeError) as e:
        source_labels(db)
    assert "소싱처키" in str(e.value), \
        f"우리 막이가 아니라 파이썬이 낸 오류를 잡고 있다: {e.value}"


# ── 지적 1 · 분수의 분자에 상한이 없다 ──────────────────────────────────────

@pytest.fixture
def 분모가작은세상(db):
    """SKU 5개가 무신사 URL 1개에 전부 붙었는데, 호출자가 분모를 3이라고 준 상황."""
    skus = _모델(db, "SMALL", 5)
    u = _url(db, "SMALL", "musinsa", "https://musinsa.com/small")
    _붙임(db, u, skus)
    db.commit()
    return {"code": "SMALL", "skus": skus}


def test_분자가_분모를_넘지_않는다(db, 분모가작은세상):
    """🔴 화면에 「SKU 5·3」 같은 말이 안 되는 분수가 찍히면 안 된다."""
    got = mapping_coverage(db, ["SMALL"], {"SMALL": 3})["SMALL"]
    assert got["skus"] == 3
    assert got["skus_done"] <= got["skus"], f"분자가 분모를 넘었다: {got}"
    assert got["skus_done"] == 3


def test_분모를_넘긴_소싱처는_미완료로_찍히지_않는다(db, 분모가작은세상):
    """🔴 「SKU 3·3」인데 「소싱처 0·1 · 미완료」면 숫자와 판정이 서로 다른 말을 한다."""
    got = mapping_coverage(db, ["SMALL"], {"SMALL": 3})["SMALL"]
    assert got["sources"] == 1
    assert got["sources_done"] == 1
    assert got["complete"] is True


def test_분모초과는_결과에_남는다(db, 분모가작은세상):
    """🔴 조용히 자르면 「분모가 틀렸다」는 사고 신호가 사라져 원인을 영영 못 찾는다."""
    got = mapping_coverage(db, ["SMALL"], {"SMALL": 3})["SMALL"]
    assert got["over_total"] == 5, f"실제로 센 5를 안 남겼다: {got}"


def test_분모초과가_없으면_0이다(db, 심은세상):
    """정상 상황에서 0 이어야 화면이 애먼 경고를 띄우지 않는다."""
    got = mapping_coverage(db, ["AF"], {"AF": 5})["AF"]
    assert got["over_total"] == 0

    # URL 이 아예 없는 모델(빈 껍데기)도 같은 칸을 가져야 호출자가 KeyError 를 안 만난다
    _모델(db, "NONE", 2)
    db.commit()
    assert mapping_coverage(db, ["NONE"], {"NONE": 2})["NONE"]["over_total"] == 0


def test_분모초과는_로그로도_알린다(db, 분모가작은세상, caplog):
    """화면이 그 칸을 안 읽어도 서버 로그에는 남아야 원인을 찾을 수 있다."""
    with caplog.at_level(logging.WARNING, logger="lemouton.sourcing.source_url_stats"):
        mapping_coverage(db, ["SMALL"], {"SMALL": 3})
    합 = "\n".join(r.getMessage() for r in caplog.records)
    assert "SMALL" in 합 and "3" in 합 and "5" in 합, f"경고가 안 남았다: {합!r}"


def test_SKU총계를_0으로_줬는데_붙어있으면_분모초과다(db):
    """🔴 「잴 대상이 없다」는데 실제로는 붙어 있다 — 분모가 틀렸다는 같은 신호다."""
    skus = _모델(db, "ZERO", 2)
    u = _url(db, "ZERO", "ssf", "https://ssfshop.com/zero")
    _붙임(db, u, skus)
    db.commit()

    got = mapping_coverage(db, ["ZERO"], {"ZERO": 0})["ZERO"]
    assert got["complete"] is None        # 잴 대상이 없다는 판정 자체는 그대로
    assert got["skus_done"] == 0
    assert got["over_total"] == 2         # 하지만 「0이라더니 2개 붙어 있다」를 남긴다
