# -*- coding: utf-8 -*-
"""[TEST] Phase 1B M3-2 — 크롤 → 재계산 → 판정 → 전송 → 스냅샷 파이프라인.

이 테스트가 지키는 것(전부 '틀리면 돈이 나가는' 항목):
  ① 실전송 잠금이 꺼져 있으면 마켓 호출이 **한 번도** 일어나지 않는다.
  ② 스킵·보류도 스냅샷에 남는다(조용한 실패와 구분).
  ③ 전송 실패는 uploaded_at 이 비고, 다음 사이클에 **자동 재시도**된다.
     특히 재고 0→0 스킵 규칙이 이 재시도를 막지 않는다.
  ④ P0 가 P1·P2 보다 먼저 나간다.
  ⑤ 크롤 실패 시 기존 가격이 유지되고 추정가가 올라가지 않는다.
  ⑥ 역마진 미달은 보류되고, 품절은 그래도 통과한다.

라이브 마켓·소싱처에는 접속하지 않는다 — 어댑터와 최종매입가 계산은 전부 모킹.
"""
import pytest

from lemouton.uploader import reconcile as R
from lemouton.uploader.models import PriceSnapshot


# ─────────────────────────────────────────────────────────────────────────────
#  준비물
# ─────────────────────────────────────────────────────────────────────────────

class RecordingAdapter:
    """마켓 호출을 세는 가짜 어댑터. success 를 바꿔 실패도 흉내낸다."""

    def __init__(self, *, success=True, error=None, raises=None):
        self.calls = []
        self.success = success
        self.error = error
        self.raises = raises

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock):
        self.calls.append({"canonical_sku": canonical_sku,
                           "market_option_id": market_option_id,
                           "new_price": new_price, "new_stock": new_stock})
        if self.raises:
            raise self.raises
        from lemouton.uploader.adapters.base import UploadResult
        return UploadResult(market="smartstore", canonical_sku=canonical_sku,
                            success=self.success, http_status=200 if self.success else 500,
                            error=self.error)


@pytest.fixture
def session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    for _m in ("lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
               "lemouton.sources.models", "lemouton.templates.models",
               "lemouton.sets.models", "lemouton.uploader.models",
               "lemouton.pricing.settings", "lemouton.inventory.models"):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base

    engine = create_engine(f"sqlite:///{tmp_path/'rc.db'}", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True, expire_on_commit=False)()
    yield s
    s.close()


@pytest.fixture
def world(session):
    """소싱처 상품 1개 · 옵션 1개 · sku 1개 · 스마트스토어 채널 1개."""
    from lemouton.sources.models import SourceProduct, SourceOption, OptionSourceLink
    from lemouton.sets.models import SetChannel, SetChannelOption

    sp = SourceProduct(site="musinsa", url="https://www.musinsa.com/products/1")
    session.add(sp)
    session.flush()

    so = SourceOption(source_product_id=sp.id, color_text="BLACK", size_text="230",
                      current_price=100000, current_stock=5)
    session.add(so)
    session.flush()

    session.add(OptionSourceLink(canonical_sku="SKU-1", source_option_id=so.id))

    ch = SetChannel(set_id=1, market="smartstore", account_key="default",
                    market_product_id="PID-1", status="ok")
    session.add(ch)
    session.flush()
    session.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU-1",
                                 market_option_id="OPT-1", status="matched"))
    session.commit()
    return {"sp": sp, "so": so, "channel": ch}


@pytest.fixture
def fake_breakdown(monkeypatch):
    """compute_breakdown 을 모킹 — 최종매입가를 시험이 직접 정한다."""
    import webapp.routes.api_benefits as AB

    state = {"final_price": 90000,
             "steps": [{"name": "등급적립", "type": "rate", "value": 0.05,
                        "deduct": 5000, "base_after": 95000}]}

    def _fake(session, *, sku, source_id, sale_price, bundle_code=None,
              _cache=None, source_product_id=None):
        if state.get("raise"):
            raise RuntimeError("breakdown 실패")
        return {"sale_price": float(sale_price),
                "final_price": state["final_price"],
                "steps": state["steps"], "items_used": []}

    monkeypatch.setattr(AB, "compute_breakdown", _fake)
    return state


def _run(session, world, **kw):
    kw.setdefault("armed", True)
    kw.setdefault("min_margin_amount", 0)
    return R.reconcile_after_crawl(session, source_product=world["sp"], **kw)


def _snaps(session):
    return session.query(PriceSnapshot).order_by(PriceSnapshot.id).all()


def _confirm_upload(session, *, price, stock, market="smartstore"):
    """'마켓이 실제로 받았다'고 확정된 기준선 스냅샷을 심는다."""
    import datetime as dt
    session.add(PriceSnapshot(
        canonical_sku="SKU-1", market=market, account_key="default",
        upload_price=price, stock=stock, action="upload",
        uploaded_at=dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc)))
    session.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  ① 실전송 잠금 — OFF 면 마켓 호출 0
# ─────────────────────────────────────────────────────────────────────────────

def test_disarmed_never_calls_the_market(session, world, fake_breakdown):
    """잠금이 꺼져 있으면 어댑터를 넘겨줘도 **한 번도** 호출하지 않는다."""
    ad = RecordingAdapter()
    out = _run(session, world, armed=False, adapters={"smartstore": ad})

    assert ad.calls == []                 # ★ 실제 마켓 호출 0
    assert out["armed"] is False
    assert out["uploaded"] == 0
    assert out["held"] == 1


def test_disarmed_records_would_have_sent_without_uploaded_at(session, world,
                                                              fake_breakdown):
    """'보낼 뻔했다'는 남기되 uploaded_at 은 비운다 = 아직 안 올라갔다."""
    _run(session, world, armed=False, adapters={"smartstore": RecordingAdapter()})

    snap = _snaps(session)[0]
    assert snap.action == "hold"
    assert snap.reason_code == "live_send_disarmed"
    assert snap.uploaded_at is None
    assert snap.upload_price and snap.upload_price > 0   # 보낼 값은 계산돼 있다
    assert any("실전송 잠금" in w for w in snap.warnings_json)


def test_disarmed_then_armed_actually_sends(session, world, fake_breakdown):
    """잠금 상태의 hold 가 기준선이 되지 않으므로, 풀면 그때 나간다."""
    _run(session, world, armed=False, adapters={"smartstore": RecordingAdapter()})
    ad = RecordingAdapter()
    _run(session, world, armed=True, adapters={"smartstore": ad})
    assert len(ad.calls) == 1


def test_default_arm_flag_is_off(monkeypatch, session):
    """서버 열쇠 이름과 기본값(OFF) 을 못 박는다."""
    from lemouton.uploader.runtime import live_upload_enabled, real_upload_armed
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    assert live_upload_enabled() is False
    assert real_upload_armed(session) is False


def test_armed_requires_both_keys(monkeypatch, session):
    """서버 열쇠만으로는 안 된다 — 화면 열쇠(autosend_mode='real')도 필요."""
    from lemouton.uploader.runtime import real_upload_armed
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")
    assert real_upload_armed(session) is False        # autosend_mode 미설정
    from lemouton.pricing.settings import save_automation
    save_automation(session, {"autosend_mode": "real"})
    session.commit()
    assert real_upload_armed(session) is True


def test_no_adapter_registered_is_not_sent_elsewhere(session, world, fake_breakdown):
    """어댑터 없는 마켓을 임의의 다른 어댑터로 보내지 않는다."""
    out = _run(session, world, adapters={})
    assert out["uploaded"] == 0
    assert out["held"] == 1
    assert _snaps(session)[0].reason_code == "no_adapter"


# ─────────────────────────────────────────────────────────────────────────────
#  ② 스킵·보류도 스냅샷에 남는다
# ─────────────────────────────────────────────────────────────────────────────

def test_skip_is_recorded_with_reason(session, world, fake_breakdown):
    """가격·재고 무변동 스킵도 사유와 함께 1행 남는다."""
    from lemouton.pricing.unified import compute_market_price
    upload_price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=upload_price, stock=5)

    out = _run(session, world)
    assert out["skipped"] == 1 and out["uploaded"] == 0

    snap = _snaps(session)[-1]
    assert snap.action == "skip"
    assert snap.reason_code == "no_change"
    assert snap.reason and len(snap.reason) <= 200
    assert snap.uploaded_at is None


def test_every_outcome_writes_exactly_one_row(session, world, fake_breakdown):
    """업로드든 스킵이든 보류든 판정 1건 = 스냅샷 1행."""
    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad})       # 첫 업로드
    assert len(_snaps(session)) == 1
    _run(session, world, adapters={"smartstore": ad})       # 무변동 스킵
    assert len(_snaps(session)) == 2
    assert [s.action for s in _snaps(session)] == ["upload", "skip"]


def test_market_without_price_policy_is_skipped_not_guessed(session, world,
                                                            fake_breakdown):
    """가격 정책 없는 마켓을 스스 정책으로 대체 계산해 올리지 않는다.

    [2026-07-20] 롯데온·11번가·옥션·G마켓은 정책 일습을 갖춰 정식 지원으로 편입됐다.
    그래서 예시를 '정말 정책이 없는' 마켓으로 바꾼다 — 규칙 자체는 그대로다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = SetChannel(set_id=2, market="wemakeprice", account_key="acct2",
                    market_product_id="W-1", status="ok")
    session.add(ch)
    session.flush()
    session.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU-1",
                                 market_option_id="W-OPT", status="matched"))
    session.commit()

    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad, "wemakeprice": ad})

    other = [s for s in _snaps(session) if s.market == "wemakeprice"]
    assert len(other) == 1
    assert other[0].action == "skip"
    assert other[0].reason_code == "market_no_policy"
    assert other[0].upload_price is None                    # 값을 지어내지 않는다
    assert all(c["canonical_sku"] == "SKU-1" for c in ad.calls)
    assert len(ad.calls) == 1                               # 스마트스토어 1건만


def test_lotteon_now_gets_priced(session, world, fake_breakdown):
    """[2026-07-20] 4대 마켓 켬 — 롯데온도 이제 자기 정책으로 가격이 계산된다.

    이전엔 market_no_policy 로 스킵돼 자동 전송 대상이 아니었다.
    """
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = SetChannel(set_id=2, market="lotteon", account_key="acct2",
                    market_product_id="L-1", status="ok")
    session.add(ch)
    session.flush()
    session.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU-1",
                                 market_option_id="L-OPT", status="matched"))
    session.commit()

    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad, "lotteon": ad})

    lotte = [s for s in _snaps(session) if s.market == "lotteon"]
    assert len(lotte) == 1
    assert lotte[0].reason_code != "market_no_policy", "아직도 정책 없음으로 스킵된다"
    assert lotte[0].upload_price and lotte[0].upload_price > 0, "가격이 계산되지 않았다"


# ─────────────────────────────────────────────────────────────────────────────
#  ③ 전송 실패 → uploaded_at 비움 → 다음 사이클 재시도
# ─────────────────────────────────────────────────────────────────────────────

def test_failed_send_leaves_uploaded_at_null(session, world, fake_breakdown):
    ad = RecordingAdapter(success=False, error="HTTP 500 서버 오류")
    out = _run(session, world, adapters={"smartstore": ad})

    assert out["failed"] == 1 and out["uploaded"] == 0
    snap = _snaps(session)[-1]
    assert snap.action == "upload"
    assert snap.uploaded_at is None                 # ★ 아직 안 올라갔다
    assert any("전송 실패" in w for w in snap.warnings_json)


def test_exception_is_never_recorded_as_success(session, world, fake_breakdown):
    """어댑터가 던지면 성공으로 둔갑시키지 않는다(거짓 성공 금지)."""
    ad = RecordingAdapter(raises=RuntimeError("네트워크 끊김"))
    out = _run(session, world, adapters={"smartstore": ad})

    assert out["failed"] == 1 and out["uploaded"] == 0
    assert _snaps(session)[-1].uploaded_at is None


def test_failed_send_is_retried_next_cycle(session, world, fake_breakdown):
    """값이 그대로여도 마켓에 아직 안 갔으면 다시 보낸다."""
    bad = RecordingAdapter(success=False, error="500")
    _run(session, world, adapters={"smartstore": bad})
    assert len(bad.calls) == 1

    good = RecordingAdapter(success=True)
    _run(session, world, adapters={"smartstore": good})
    assert len(good.calls) == 1                     # ★ 재시도됨
    assert _snaps(session)[-1].uploaded_at is not None

    # 이제는 마켓이 받았으니 같은 값은 더 이상 안 보낸다.
    again = RecordingAdapter(success=True)
    _run(session, world, adapters={"smartstore": again})
    assert again.calls == []


def test_sold_out_retry_is_not_blocked_by_zero_to_zero_skip(session, world,
                                                            fake_breakdown):
    """재고 0→0 스킵 규칙이 '품절 전송 실패'의 재시도를 막지 않는다.

    ★ 이 파이프라인의 핵심 설계 근거.
      기준선을 '마지막 스냅샷'이 아니라 '마지막으로 **올라간** 스냅샷'으로 잡기
      때문에, 품절 전송이 실패하면 prev_stock 은 여전히 마켓이 들고 있는 5 다.
      따라서 다음 사이클도 5→0 = 품절(P0) 로 잡혀 재전송된다.
    """
    from lemouton.pricing.unified import compute_market_price
    price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=price, stock=5)

    world["so"].current_stock = 0          # 소싱처 품절
    session.commit()

    bad = RecordingAdapter(success=False, error="타임아웃")
    _run(session, world, adapters={"smartstore": bad})
    assert len(bad.calls) == 1
    assert bad.calls[0]["new_stock"] == 0

    # 값은 그대로 0→0 이지만 마켓엔 아직 반영 안 됨 → 재시도되어야 한다.
    retry = RecordingAdapter(success=True)
    _run(session, world, adapters={"smartstore": retry})
    assert len(retry.calls) == 1           # ★ 스킵되지 않고 재시도
    assert _snaps(session)[-1].reason_code == "sold_out"

    # 마켓이 0 을 받은 뒤에야 0→0 이 스킵된다.
    after = RecordingAdapter(success=True)
    _run(session, world, adapters={"smartstore": after})
    assert after.calls == []
    assert _snaps(session)[-1].reason_code == "no_change"


def test_pending_failed_send_is_detectable(session, world, fake_breakdown):
    """재시도 대상을 사람에게 보여줄 수 있어야 한다."""
    _run(session, world, adapters={"smartstore": RecordingAdapter(success=False)})
    assert R.has_pending_failed_send(
        session, canonical_sku="SKU-1", market="smartstore",
        account_key="default") is True

    _run(session, world, adapters={"smartstore": RecordingAdapter(success=True)})
    assert R.has_pending_failed_send(
        session, canonical_sku="SKU-1", market="smartstore",
        account_key="default") is False


# ─────────────────────────────────────────────────────────────────────────────
#  ④ P0 우선
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_is_planned_before_p1_and_p2(session, world, fake_breakdown, monkeypatch):
    """가격변동·품절(P0)이 재입고(P1)·무변동(P2)보다 앞선다."""
    from lemouton.sources.models import SourceOption, OptionSourceLink
    from lemouton.sets.models import SetChannel, SetChannelOption
    from lemouton.pricing.unified import compute_market_price

    price = compute_market_price(None, "ss", "sourcing", 90000).final_price

    # SKU-1 = 무변동(P2)  /  SKU-2 = 재입고(P1)  /  SKU-3 = 품절(P0)
    _confirm_upload(session, price=price, stock=5)
    for i, (sku, stock, prev_stock) in enumerate(
            [("SKU-2", 4, 0), ("SKU-3", 0, 5)], start=2):
        so = SourceOption(source_product_id=world["sp"].id, color_text=f"C{i}",
                          size_text="230", current_price=100000, current_stock=stock)
        session.add(so)
        session.flush()
        session.add(OptionSourceLink(canonical_sku=sku, source_option_id=so.id))
        ch = SetChannel(set_id=10 + i, market="smartstore", account_key="default",
                        market_product_id=f"PID-{i}", status="ok")
        session.add(ch)
        session.flush()
        session.add(SetChannelOption(channel_id=ch.id, canonical_sku=sku,
                                     market_option_id=f"OPT-{i}", status="matched"))
        session.commit()
        import datetime as dt
        session.add(PriceSnapshot(canonical_sku=sku, market="smartstore",
                                  account_key="default", upload_price=price,
                                  stock=prev_stock, action="upload",
                                  uploaded_at=dt.datetime(2026, 7, 18,
                                                          tzinfo=dt.timezone.utc)))
        session.commit()

    plans = R.plan_uploads(session, source_product=world["sp"], min_margin_amount=0)
    order = [(p.decision.priority, p.link.canonical_sku) for p in plans]

    assert order[0] == ("P0", "SKU-3")            # 품절이 맨 앞
    assert [p for p, _ in order] == sorted(
        [p for p, _ in order], key=lambda x: R.PRIORITY_RANK[x])


def test_p0_is_sent_before_p1(session, world, fake_breakdown):
    """계획 순서가 실제 전송 순서로 이어진다."""
    from lemouton.sources.models import SourceOption, OptionSourceLink
    from lemouton.sets.models import SetChannel, SetChannelOption

    so = SourceOption(source_product_id=world["sp"].id, color_text="C2",
                      size_text="230", current_price=100000, current_stock=4)
    session.add(so)
    session.flush()
    session.add(OptionSourceLink(canonical_sku="SKU-2", source_option_id=so.id))
    ch = SetChannel(set_id=99, market="smartstore", account_key="default",
                    market_product_id="PID-2", status="ok")
    session.add(ch)
    session.flush()
    session.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU-2",
                                 market_option_id="OPT-2", status="matched"))
    session.commit()

    from lemouton.pricing.unified import compute_market_price
    price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=price, stock=5)          # SKU-1 무변동(P2)
    import datetime as dt
    session.add(PriceSnapshot(canonical_sku="SKU-2", market="smartstore",
                              account_key="default", upload_price=price, stock=0,
                              action="upload",
                              uploaded_at=dt.datetime(2026, 7, 18,
                                                      tzinfo=dt.timezone.utc)))
    session.commit()
    world["so"].current_stock = 0                            # SKU-1 을 품절(P0)로
    session.commit()

    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad})
    assert [c["canonical_sku"] for c in ad.calls][0] == "SKU-1"   # P0 먼저


# ─────────────────────────────────────────────────────────────────────────────
#  ⑤ 크롤 실패 = 폴백 금지
# ─────────────────────────────────────────────────────────────────────────────

def test_crawl_failure_does_not_upload_a_guessed_price(session, world,
                                                       fake_breakdown):
    """표면가를 못 읽으면 추정가를 만들어 올리지 않는다."""
    world["so"].current_price = None
    world["so"].current_stock = None
    session.commit()

    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})

    assert ad.calls == []                       # 아무것도 안 나간다
    snap = _snaps(session)[-1]
    assert snap.action == "skip"
    assert snap.reason_code == "crawl_failed"
    assert snap.upload_price is None            # ★ 지어낸 값이 없다
    assert snap.final_purchase_price is None


def test_crawl_failure_is_not_counted_as_no_change(session, world, fake_breakdown):
    """실패를 '변동 없음'으로 세면 크롤 주기가 잘못 늘어난다."""
    world["so"].current_price = None
    world["so"].current_stock = -1              # 확인불가 센티넬
    session.commit()

    plans = R.plan_uploads(session, source_product=world["sp"], min_margin_amount=0)
    assert plans[0].decision.counts_as_no_change is False


def test_price_unknown_keeps_previous_price(session, world, fake_breakdown):
    """가격 축만 실패하면 기존 가격을 그대로 두고 그 축은 안 건드린다."""
    from lemouton.pricing.unified import compute_market_price
    price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=price, stock=5)

    fake_breakdown["raise"] = True              # 최종매입가 계산 실패
    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad})

    assert ad.calls == []
    snap = _snaps(session)[-1]
    assert snap.upload_price is None
    assert snap.action == "skip"
    # 마켓이 들고 있는 기준선은 그대로 살아 있다.
    last = R.last_confirmed_snapshot(session, canonical_sku="SKU-1",
                                     market="smartstore", account_key="default")
    assert last.upload_price == price


def test_zero_final_purchase_price_never_uploads_zero_won(session, world,
                                                          fake_breakdown):
    """최종매입가가 0/미상이면 0원짜리도, None 도 마켓에 넘기지 않는다.

    ★ 회귀 방어: 게이트는 기준선이 없으면 '첫 업로드'라며 올리라고 한다(재고는
      읽혔으므로 정당한 판정이다). 하지만 가격을 모르는 상태라 그대로 어댑터에
      넘기면 ``new_price=None`` 이 마켓으로 나간다. 실행 계층이 막아야 한다.
    """
    fake_breakdown["final_price"] = 0
    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})

    assert ad.calls == []                        # ★ None 가격이 마켓에 안 나간다
    assert out["held"] == 1
    snap = _snaps(session)[-1]
    assert snap.action == "hold"
    assert snap.reason_code == "send_value_unknown"
    assert snap.upload_price is None


def test_unknown_axis_reuses_the_value_the_market_already_holds(session, world,
                                                                fake_breakdown):
    """가격을 못 읽었지만 재고가 바뀌었으면, 가격은 마켓 현재값 그대로 두고 보낸다.

    '기존 값 유지'는 값을 지어내는 게 아니라 그 축을 안 건드리는 것이다.
    """
    from lemouton.pricing.unified import compute_market_price
    price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=price, stock=5)

    fake_breakdown["raise"] = True               # 가격 축 확인불가
    world["so"].current_stock = 0                # 재고 축은 읽혔다 — 품절
    session.commit()

    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad})

    assert len(ad.calls) == 1
    assert ad.calls[0]["new_price"] == price     # 마켓이 들고 있던 값 그대로
    assert ad.calls[0]["new_stock"] == 0         # 재고만 갱신
    assert _snaps(session)[-1].upload_price is None   # 이번엔 계산 못 했음을 기록


# ─────────────────────────────────────────────────────────────────────────────
#  ⑥ 역마진 가드
# ─────────────────────────────────────────────────────────────────────────────

def test_below_min_margin_is_held(session, world, fake_breakdown):
    """마진이 기준 미만이면 보류하고 판매중지 후보로 남긴다."""
    from lemouton.pricing.unified import compute_market_price
    old = compute_market_price(None, "ss", "sourcing", 50000).final_price
    _confirm_upload(session, price=old, stock=5)            # 가격변동을 만든다

    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad},
               min_margin_amount=10_000_000)                # 사실상 전부 미달

    assert ad.calls == []
    assert out["held"] == 1
    snap = _snaps(session)[-1]
    assert snap.action == "hold"
    assert snap.reason_code == "margin_below_min"
    assert snap.margin_amount is not None
    assert any("역마진" in w for w in snap.warnings_json)


def test_sold_out_passes_the_margin_guard(session, world, fake_breakdown):
    """품절 반영은 '파는 행위'가 아니라 '멈추는 행위'라 가드가 막지 않는다."""
    from lemouton.pricing.unified import compute_market_price
    price = compute_market_price(None, "ss", "sourcing", 90000).final_price
    _confirm_upload(session, price=price, stock=5)

    world["so"].current_stock = 0
    session.commit()

    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad},
               min_margin_amount=10_000_000)

    assert len(ad.calls) == 1                    # ★ 품절은 나간다
    assert ad.calls[0]["new_stock"] == 0
    assert out["uploaded"] == 1
    snap = _snaps(session)[-1]
    assert snap.action == "upload"
    assert snap.uploaded_at is not None


def test_margin_roundtrips_amount_mode(session):
    """마진금액 산출식이 집의 확정 규약(mode='amount')의 정확한 역함수인가.

    (원가+마진)/(1-수수료)+배송비 로 만든 가격을 되돌리면 마진이 그대로 나와야
    한다. 안 그러면 역마진 가드가 어느 정의로 걸린 건지 알 수 없어진다.
    """
    from lemouton.pricing.unified import compute_sale_price_unified

    for cost, target, fee, ship in [(90000, 5000, 0.06, 0),
                                    (120000, 12000, 0.1155, 3000),
                                    (30000, 0, 0.0945, 2500)]:
        pr = compute_sale_price_unified(cost, margin_rate=0.0, fee_rate=fee,
                                        shipping_fee=ship, rounding_unit=1,
                                        mode="amount", margin_amount=target)
        got = R.compute_margin_amount(pr, cost)
        assert abs(got - target) <= 1, (cost, target, fee, ship, got)


def test_margin_is_none_when_purchase_price_unknown(session):
    """모르면 None — 0 으로 채워 통과시키지도, '미달'로 단정하지도 않는다."""
    from lemouton.pricing.unified import compute_market_price
    pr = compute_market_price(None, "ss", "sourcing", 90000)
    assert R.compute_margin_amount(pr, None) is None


# ─────────────────────────────────────────────────────────────────────────────
#  배선 지점 — 크롤 저장 라우트가 파이프라인을 부르는가
# ─────────────────────────────────────────────────────────────────────────────

def test_crawl_result_route_calls_the_pipeline():
    """확장 크롤 저장(/sources/crawl-result) 이 커밋 뒤에 재계산을 잇는다."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "webapp" / "routes" / "api_pricing.py").read_text(encoding="utf-8")
    assert "from lemouton.uploader.reconcile import reconcile_after_crawl" in src
    assert "_touched_sp_ids" in src


def test_pipeline_does_not_reimplement_the_gate():
    """판정·계산은 호출만 한다 — 여기서 다시 짜면 두 진실 원천이 생긴다."""
    import pathlib
    src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    assert "from .upload_gate import decide_upload" in src
    assert "def decide_upload" not in src
    assert "def compute_final_price" not in src


# ─────────────────────────────────────────────────────────────────────────────
#  ⑦ 하루 상한 (2026-07-20 배선) — 상품당 하루 N회, 품절은 예외
#     사장님: "여유가 되면 바로바로. 다만 너무 많으면 상품별 하루 최대 2회까지."
#             "품절은 빠르게 무조건 빼야 함."
# ─────────────────────────────────────────────────────────────────────────────

def _used_up(session, *, n=2, market="smartstore"):
    """오늘 이미 n 번 나간 것으로 만든다 (한국 날짜 기준 '지금')."""
    import datetime as dt

    from lemouton.uploader.daily_cap_service import KST
    now_kst = dt.datetime.now(KST)
    at = now_kst.astimezone(dt.timezone.utc).replace(tzinfo=None)
    for _ in range(n):
        session.add(PriceSnapshot(canonical_sku="SKU-1", market=market,
                                  account_key="default", action="upload",
                                  upload_price=100000, stock=5, uploaded_at=at))
    session.commit()


def test_상한을_다_쓰면_마켓을_안_부른다(session, world, fake_breakdown):
    """★ 이게 이번 배선의 핵심 — 전에는 변동마다 전부 나갔다."""
    _used_up(session, n=2)
    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})
    assert ad.calls == []                    # 마켓 호출 0
    assert out["capped"] == 1
    assert out["uploaded"] == 0


def test_상한에_걸려도_버리지_않는다(session, world, fake_breakdown):
    """held 로 남아야 다음 슬롯에 최신 값으로 나간다."""
    _used_up(session, n=2)
    out = _run(session, world, adapters={"smartstore": RecordingAdapter()})
    assert out["held"] >= 1
    last = _snaps(session)[-1]
    assert last.action == "hold"
    assert last.reason_code == "daily_cap_reached"
    assert last.uploaded_at is None          # 안 나갔다


def test_상한_안이면_평소대로_나간다(session, world, fake_breakdown):
    _used_up(session, n=1)
    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})
    assert len(ad.calls) == 1
    assert out["capped"] == 0


def test_품절은_상한을_넘겨도_나간다(session, world, fake_breakdown):
    """계속 팔면 주문 받고 취소 → 마켓 페널티·고객 이탈."""
    _used_up(session, n=2)
    world["so"].current_stock = 0
    session.commit()
    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})
    assert len(ad.calls) == 1                # 뚫고 나갔다
    assert out["sold_out_exempt"] == 1


def test_어제_업로드는_상한을_안_먹는다(session, world, fake_breakdown):
    import datetime as dt

    from lemouton.uploader.daily_cap_service import KST
    yesterday = (dt.datetime.now(KST) - dt.timedelta(days=1))
    at = yesterday.astimezone(dt.timezone.utc).replace(tzinfo=None)
    for _ in range(5):
        session.add(PriceSnapshot(canonical_sku="SKU-1", market="smartstore",
                                  account_key="default", action="upload",
                                  upload_price=100000, stock=5, uploaded_at=at))
    session.commit()
    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad})
    assert len(ad.calls) == 1


def test_상한_0이면_무제한(session, world, fake_breakdown):
    """상한을 끄고 싶을 때 — 검사를 건너뛴다."""
    from lemouton.uploader.daily_cap import CapConfig
    _used_up(session, n=9)
    ad = RecordingAdapter()
    _run(session, world, adapters={"smartstore": ad},
         cap_config=CapConfig(max_per_day=0))
    assert len(ad.calls) == 1


def test_잠금이_걸린_건_상한을_안_먹는다(session, world, fake_breakdown):
    """★ 안 나간 건 상한을 쓴 게 아니다.

    잠금 상태로 여러 번 돌려도 hold 만 쌓인다. 잠금을 풀면 그때 나가야 한다.
    """
    for _ in range(5):
        _run(session, world, armed=False, adapters=None)
    ad = RecordingAdapter()
    out = _run(session, world, adapters={"smartstore": ad})
    assert len(ad.calls) == 1, "잠금 중 hold 가 상한을 먹었다"
    assert out["capped"] == 0


# ============ 4대 마켓 자동 가격계산 켬 (2026-07-20) ============

def test_priced_markets_covers_all_six():
    """롯데온·11번가·옥션·G마켓도 자동 가격계산 대상."""
    from lemouton.uploader.reconcile import PRICED_MARKETS
    for m in ("smartstore", "coupang", "lotteon", "eleven11", "auction", "gmarket"):
        assert m in PRICED_MARKETS, f"{m} 이 가격계산 대상에서 빠졌다"


def test_priced_markets_matches_upload_markets():
    """전송 대상과 가격계산 대상이 어긋나면 '올리는데 값이 없는' 마켓이 생긴다."""
    from lemouton.uploader.reconcile import PRICED_MARKETS
    from lemouton.uploader.orchestrator import UPLOAD_MARKETS
    assert set(PRICED_MARKETS) == set(UPLOAD_MARKETS)


def test_every_priced_market_has_engine_policy():
    """PRICED_MARKETS 에 있는데 엔진이 모르면 UnknownMarketPolicyError 로 죽는다.

    이 테스트가 깨지면 = 마켓을 켜놓고 정책 컬럼을 안 만든 것.
    """
    from lemouton.uploader.reconcile import PRICED_MARKETS, _MARKET_PREFIX
    from lemouton.pricing.unified import resolve_market_policy
    for m in PRICED_MARKETS:
        assert m in _MARKET_PREFIX, f"{m} 접두 매핑 없음"
        pol = resolve_market_policy(None, m, "sourcing")
        assert pol["fee_rate"] > 0, f"{m} 수수료율 0"


def test_market_prefix_agrees_with_engine():
    """reconcile 의 접두와 엔진의 접두가 달라지면 다른 마켓 정책으로 계산된다."""
    from lemouton.uploader.reconcile import _MARKET_PREFIX
    from lemouton.pricing.unified import _PREFIX_MAP
    for market, prefix in _MARKET_PREFIX.items():
        assert _PREFIX_MAP.get(market) == prefix, f"{market}: {prefix} != {_PREFIX_MAP.get(market)}"
