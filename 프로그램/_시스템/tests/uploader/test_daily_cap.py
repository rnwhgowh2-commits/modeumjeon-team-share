"""업로드 상한 — 상품당 하루 2회 · 품절은 예외 · 막혀도 버리지 않음.

설계서: docs/superpowers/specs/2026-07-19-크롤주기-변동주기-등급-design.md §5-1 · §5-1-1
사장님 확정:
  - "여유가 되면 가격/재고 변동되면 바로바로 업로드. 다만 업로드할 게 너무 많으면
     상품별로 하루에 최대 2회까지만."
  - "품절은 빠르게 무조건 빼야 함."
"""
import pytest

from lemouton.uploader.daily_cap import (
    CapConfig,
    coalesce_pending,
    decide_cap,
)


# ── 기본 상한 ───────────────────────────────────────────────────

def test_상한_미만이면_그냥_통과():
    d = decide_cap(used_today=0, is_sold_out=False)
    assert d.allowed is True
    assert d.exempt is False
    assert d.held is False


def test_한_번_썼어도_아직_통과():
    d = decide_cap(used_today=1, is_sold_out=False)
    assert d.allowed is True


def test_상한을_다_쓰면_막힌다():
    d = decide_cap(used_today=2, is_sold_out=False)
    assert d.allowed is False
    assert d.reason_code == "daily_cap_reached"


def test_막혀도_버리지_않고_대기시킨다():
    """설계서 §5-1: 마지막 값만 들고 있다가 다음 슬롯에 최신 상태로 올린다."""
    d = decide_cap(used_today=2, is_sold_out=False)
    assert d.allowed is False
    assert d.held is True, "막힌 건은 버리는 게 아니라 대기 상태여야 한다"


# ── 품절 예외 (사장님: 무조건 빠르게) ────────────────────────────

def test_품절이면_상한을_넘겨도_통과한다():
    d = decide_cap(used_today=5, is_sold_out=True)
    assert d.allowed is True
    assert d.exempt is True
    assert d.reason_code == "sold_out_exempt"


def test_품절_예외로_통과해도_상한초과_사실은_남긴다():
    """카운터를 아예 안 세면 얼마나 초과했는지 모르게 된다 (설계서 §5-1-1 구현 주의)."""
    d = decide_cap(used_today=5, is_sold_out=True)
    assert d.over_limit is True
    assert d.used == 5
    assert d.limit == 2


def test_품절이_상한_안이면_초과표시는_안_한다():
    d = decide_cap(used_today=0, is_sold_out=True)
    assert d.allowed is True
    assert d.over_limit is False
    assert d.exempt is False, "상한에 안 걸렸으면 예외를 쓴 게 아니다"


def test_재입고는_품절이_아니라서_상한이_적용된다():
    """면제는 '재고 0' 에만. 재입고·재고 증감은 늦어도 손해가 없다."""
    d = decide_cap(used_today=2, is_sold_out=False)
    assert d.allowed is False


def test_품절_예외를_끌_수_있다():
    cfg = CapConfig(exempt_on_sold_out=False)
    d = decide_cap(used_today=2, is_sold_out=True, config=cfg)
    assert d.allowed is False


# ── 재고 확인불가 = 품절 아님 (조용한 실패 방지) ──────────────────

def test_재고를_모르면_품절로_치지_않는다():
    """크롤 실패로 재고를 못 읽은 걸 '품절'로 오인하면 멀쩡한 상품을 내린다.

    이 프로젝트의 확립된 원칙 — 파싱 실패는 0 이 아니라 '확인 불가'.
    """
    d = decide_cap(used_today=5, is_sold_out=None)
    assert d.allowed is False
    assert d.exempt is False


# ── 사장님 설정 ─────────────────────────────────────────────────

def test_사장님이_상한을_바꿀_수_있다():
    cfg = CapConfig(max_per_day=6)
    assert decide_cap(used_today=5, is_sold_out=False, config=cfg).allowed is True
    assert decide_cap(used_today=6, is_sold_out=False, config=cfg).allowed is False


def test_상한_0은_품절만_나가게_한다():
    cfg = CapConfig(max_per_day=0)
    assert decide_cap(used_today=0, is_sold_out=False, config=cfg).allowed is False
    assert decide_cap(used_today=0, is_sold_out=True, config=cfg).allowed is True


def test_음수_상한은_거부():
    with pytest.raises(ValueError):
        CapConfig(max_per_day=-1)


def test_음수_사용량은_거부():
    with pytest.raises(ValueError):
        decide_cap(used_today=-1, is_sold_out=False)


# ── 합치기 (coalesce) ───────────────────────────────────────────

def _item(sku, market, acct, value):
    return {"canonical_sku": sku, "market": market, "account_key": acct, "value": value}


def test_같은_상품_같은_마켓은_마지막_것만_남는다():
    items = [
        _item("A", "smartstore", "acc1", 100),
        _item("A", "smartstore", "acc1", 110),
        _item("A", "smartstore", "acc1", 105),
    ]
    out = coalesce_pending(items)
    assert len(out) == 1
    assert out[0]["value"] == 105, "가장 마지막(최신) 값이 남아야 한다"


def test_마켓이_다르면_따로_남는다():
    items = [
        _item("A", "smartstore", "acc1", 100),
        _item("A", "coupang", "acc1", 100),
    ]
    assert len(coalesce_pending(items)) == 2


def test_계정이_다르면_따로_남는다():
    items = [
        _item("A", "smartstore", "acc1", 100),
        _item("A", "smartstore", "acc2", 100),
    ]
    assert len(coalesce_pending(items)) == 2


def test_상품이_다르면_따로_남는다():
    items = [
        _item("A", "smartstore", "acc1", 100),
        _item("B", "smartstore", "acc1", 100),
    ]
    assert len(coalesce_pending(items)) == 2


def test_처음_나온_순서를_지킨다():
    """우선순위 정렬은 다른 단계에서 한다. 여기서 순서를 흔들면 예측이 어려워진다."""
    items = [
        _item("A", "smartstore", "acc1", 1),
        _item("B", "smartstore", "acc1", 2),
        _item("A", "smartstore", "acc1", 3),
    ]
    out = coalesce_pending(items)
    assert [o["canonical_sku"] for o in out] == ["A", "B"]
    assert out[0]["value"] == 3


def test_빈_목록은_빈_목록():
    assert coalesce_pending([]) == []


def test_객체도_받는다():
    class P:
        def __init__(self, sku, market, acct, value):
            self.canonical_sku = sku
            self.market = market
            self.account_key = acct
            self.value = value

    out = coalesce_pending([P("A", "smartstore", "acc1", 1),
                            P("A", "smartstore", "acc1", 2)])
    assert len(out) == 1
    assert out[0].value == 2


def test_하루_6번_바뀐_상품은_상한만큼만_나간다():
    """설계서 §5-3: 상한에 걸린 상품은 하루 6번 바뀌어도 최대 2건."""
    sent = 0
    used = 0
    for _ in range(6):
        d = decide_cap(used_today=used, is_sold_out=False)
        if d.allowed:
            sent += 1
            used += 1
    assert sent == 2
