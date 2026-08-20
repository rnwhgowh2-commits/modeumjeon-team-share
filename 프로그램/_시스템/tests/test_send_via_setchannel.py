# -*- coding: utf-8 -*-
"""「상품수집&전송」 보내기가 후보 0건이던 것 — 구성(SetChannel) 기준 조립 회귀 시험.

실측 사고(2026-08-06)
  등록은 마켓 상품번호를 **SetChannel.market_product_id** 에 쓰는데, 전송 페이로드를
  만드는 `formatter/pipeline` 은 **Model.*_product_id** 를 읽고 없으면 그 모델을 통째로
  뺐다. 그 컬럼을 채우는 코드가 이 경로엔 없어서 라이브 미리보기가 전 마켓 **0건**이었다.

왜 formatter 를 안 고쳤나
  full_cycle 과 공유물이고, payload 가 모델당 1개라 **한 모델에 구성이 여럿이면
  어느 상품번호인지 모호**해진다(구성 A의 가격이 구성 B로 나갈 수 있다).
  그래서 이 경로만 구성 기준으로 따로 조립한다 — 그 사실을 여기서 못 박는다.
"""
import pytest


@pytest.fixture()
def seeded():
    """구성 1개 + 스마트스토어 채널(상품번호 있음) + matched 옵션 2개."""
    from shared.db import Base, SessionLocal, engine
    from lemouton.sets.models import (ProductSet, SetChannel, SetChannelOption,
                                      SetOption, SetProduct)
    from lemouton.sourcing.models import Model, Option
    Base.metadata.create_all(engine)
    CODE = "전송시험모델"
    with SessionLocal() as s:
        # 정리
        old = s.query(ProductSet).filter_by(name="전송시험구성").first()
        if old:
            for sp in s.query(SetProduct).filter_by(set_id=old.id).all():
                s.query(SetOption).filter_by(set_product_id=sp.id).delete(
                    synchronize_session=False)
                s.delete(sp)
            for ch in s.query(SetChannel).filter_by(set_id=old.id).all():
                s.query(SetChannelOption).filter_by(channel_id=ch.id).delete(
                    synchronize_session=False)
                s.delete(ch)
            s.delete(old)
        s.query(Option).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.query(Model).filter_by(model_code=CODE).delete(synchronize_session=False)
        s.commit()

        s.add(Model(model_code=CODE, model_name_raw=CODE, model_name_display=CODE,
                    brand="TEST"))
        for color, size in (("블랙", "250"), ("화이트", "260")):
            s.add(Option(canonical_sku=f"SKU-SEND{size}", model_code=CODE,
                         color_code=color, size_code=size))
        ps = ProductSet(name="전송시험구성", model_code=CODE)
        s.add(ps)
        s.flush()
        sp = SetProduct(set_id=ps.id, model_code=CODE)
        s.add(sp)
        s.flush()
        for size in ("250", "260"):
            s.add(SetOption(set_product_id=sp.id, canonical_sku=f"SKU-SEND{size}"))
        ch = SetChannel(set_id=ps.id, market="smartstore", account_key="default",
                        market_product_id="99999", status="linked")
        s.add(ch)
        s.flush()
        for size, oid in (("250", "OPT-250"), ("260", "OPT-260")):
            s.add(SetChannelOption(channel_id=ch.id, canonical_sku=f"SKU-SEND{size}",
                                   market_option_id=oid, status="matched"))
        s.commit()
        return {"set_id": ps.id, "channel_id": ch.id, "code": CODE}


def _values_stub(monkeypatch, values):
    """보낼 값(가격·재고)은 매트릭스 원천에서 온다 — 시험에선 그 자리만 갈아끼운다."""
    import webapp.routes.sets_api as sa
    monkeypatch.setattr(sa, "_new_values_for_options",
                        lambda model_codes, skus, market: values)


def test_구성_상품번호로_payload_가_만들어진다(seeded, monkeypatch):
    """🔴 이 시험이 깨지면 보내기가 다시 후보 0건이 된다."""
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {
        "SKU-SEND250": {"price": 50000, "stock": 5},
        "SKU-SEND260": {"price": 52000, "stock": 3},
    })
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    assert "smartstore" in c and c["smartstore"], "전송 후보가 0건이다"
    payload = list(c["smartstore"].values())[0]
    assert payload["product_id"] == "99999"          # Model 이 아니라 SetChannel 값
    assert payload["base_price"] == 50000            # 스스는 기준가 + 가산금액
    got = {o["option_id"]: (o["add_price"], o["stock"]) for o in payload["options"]}
    assert got == {"OPT-250": (0, 5), "OPT-260": (2000, 3)}


def test_채널키가_구성별로_갈린다(seeded, monkeypatch):
    """한 모델에 구성이 여럿이어도 서로 안 덮어쓴다 — 이 함수가 생긴 이유."""
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {"SKU-SEND250": {"price": 50000, "stock": 5}})
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    key = list(c["smartstore"].keys())[0]
    assert f"set{seeded['set_id']}" in key and f"ch{seeded['channel_id']}" in key


def test_재고_확인불가면_그_옵션만_빠지고_알림이_남는다(seeded, monkeypatch):
    """0(품절)으로 단정해 보내지 않는다."""
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {
        "SKU-SEND250": {"price": 50000, "stock": None},   # 확인 불가
        "SKU-SEND260": {"price": 52000, "stock": 3},
    })
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    ids = [o["option_id"] for o in list(c["smartstore"].values())[0]["options"]]
    assert ids == ["OPT-260"]
    assert any(a["type"] == "option_value_unknown" for a in c["alerts"])


def test_상한_100_이_적용된다(seeded, monkeypatch):
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {"SKU-SEND250": {"price": 50000, "stock": 900}})
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    assert list(c["smartstore"].values())[0]["options"][0]["stock"] == 100


def test_가격을_못_정하면_보내지_않는다(seeded, monkeypatch):
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {"SKU-SEND250": {"price": None, "stock": 5}})
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    assert not c.get("smartstore")
    assert any(a["type"] == "option_value_unknown" for a in c["alerts"])


def test_선택_안_한_마켓은_안_섞인다(seeded, monkeypatch):
    from shared.db import SessionLocal
    from lemouton.uploader.scoped_send import build_c_output_for_set
    _values_stub(monkeypatch, {"SKU-SEND250": {"price": 50000, "stock": 5}})
    with SessionLocal() as s:
        c = build_c_output_for_set(s, seeded["set_id"], ["coupang"])
    assert not c.get("smartstore")


def test_상품번호_없는_채널은_후보에서_빠지고_알린다(seeded):
    """등록 전 구성 — 조용히 0건이 아니라 이유를 말해야 한다."""
    from shared.db import SessionLocal
    from lemouton.sets.models import SetChannel
    from lemouton.uploader.scoped_send import build_c_output_for_set
    with SessionLocal() as s:
        ch = s.get(SetChannel, seeded["channel_id"])
        ch.market_product_id = None
        s.commit()
        c = build_c_output_for_set(s, seeded["set_id"], ["smartstore"])
    assert not c.get("smartstore")
    assert any(a["type"] == "set_no_channel" for a in c["alerts"])
