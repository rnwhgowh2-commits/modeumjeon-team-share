# -*- coding: utf-8 -*-
"""가공 규칙 13항목 스키마 — 설계서 §7 이 정본.

사장님 1-3: "문서를 정확히 찾아봐라. 이미 논의했다." → 짐작하지 않고 §7 을 그대로 옮겼다.
"""
import pytest

from lemouton.registration.process_policy import ITEM_KEYS
from lemouton.registration.process_rule_schema import (
    SCHEMAS,
    all_schemas,
    default_config,
    schema_for,
    validate_config,
)


# ── 13항목이 다 있다 ────────────────────────────────────────────

def test_열세_항목이_전부_있다():
    assert len(SCHEMAS) == 13
    for k in ITEM_KEYS:
        assert k in SCHEMAS, f"{k} 스키마가 없다"


def test_항목마다_설계서_근거가_적혀_있다():
    """어느 조항에서 온 값인지 못 대면 나중에 못 고친다."""
    for k, sc in SCHEMAS.items():
        assert sc.spec_ref.startswith("§7"), f"{k} 에 설계서 근거가 없다"


def test_모르는_항목은_거부():
    with pytest.raises(ValueError):
        schema_for("nmae")


# ── 🔴 §7 확정값이 기본값으로 들어가 있다 ──────────────────────

def test_판매가_기준은_최종매입가():
    """사장님 확정 — 마진율은 최종매입가 기준."""
    sc = schema_for("price")
    assert "최종매입가" in sc.note
    rate = next(f for f in sc.fields if f.key == "margin_rate")
    assert "최종매입가" in rate.hint


def test_상품명_최대_100자():
    assert default_config("name")["max_len"] == 100


def test_반품_배송비_기본_5000원():
    """§7-10 — 기본 5,000원, 직접 입력 가능."""
    assert default_config("shipping")["return_fee"] == 5000


def test_제주_3000_도서산간_5000():
    c = default_config("shipping")
    assert c["jeju_extra"] == 3000
    assert c["island_extra"] == 5000


def test_출고_소요일_기본_3영업일():
    c = default_config("shipping")
    assert c["ship_days"] == 3
    assert next(f for f in schema_for("shipping").fields
                if f.key == "ship_days").unit == "영업일"


def test_묶음배송은_기본_안_함():
    """§7-10 — 묶음배송 안 함(개별배송)."""
    assert default_config("shipping")["bundle"] is False


def test_태그_기본_10개():
    """§7-11 — 마켓 한도까지(스스 10개)."""
    assert default_config("tags")["max_count"] == 10


def test_카테고리_실패는_보류():
    """§7-8 — 실패 = 보류 후 학습. 엉뚱한 카테고리로 올리면 노출이 죽는다."""
    assert default_config("category")["on_fail"] == "hold"


def test_품절_옵션은_등록_제외():
    """§7-9."""
    assert default_config("options")["exclude_soldout"] is True


def test_금지어는_2분류():
    """§7-1 — 수집 금지 / 마켓별 업로드 금지."""
    c = default_config("banned_words")
    assert "collect_banned" in c and "upload_banned" in c


def test_상세페이지는_3모드():
    """§7-4 — 이미지 재조합 / 원본 통째 / 프레임."""
    mode = next(f for f in schema_for("detail").fields if f.key == "mode")
    assert set(mode.choices) == {"recombine", "original", "frame"}


def test_이미지_제외_브랜드_칸이_있다():
    """§7-3 — 지재권 위험 브랜드는 이미지 제외."""
    assert "excluded_brands" in default_config("images")


def test_KC_인증번호_수집이_기본_켜짐():
    """§7-7 — 가져올 수 있으면 반드시 수집·저장."""
    assert default_config("kc")["collect_kc_no"] is True


# ── 검사 ────────────────────────────────────────────────────────

def test_빈_설정은_기본값으로_채운다():
    c = validate_config("shipping", {})
    assert c["return_fee"] == 5000


def test_준_값은_그대로_남는다():
    c = validate_config("shipping", {"return_fee": 3000})
    assert c["return_fee"] == 3000
    assert c["jeju_extra"] == 3000        # 나머지는 기본값


def test_모르는_칸은_거부():
    """오타로 만든 칸이 조용히 저장되면 '왜 안 먹지'가 된다."""
    with pytest.raises(ValueError) as e:
        validate_config("shipping", {"retrun_fee": 3000})
    assert "retrun_fee" in str(e.value)


def test_형이_틀리면_거부():
    with pytest.raises(ValueError):
        validate_config("shipping", {"return_fee": "오천원"})


def test_고를_수_없는_값은_거부():
    with pytest.raises(ValueError) as e:
        validate_config("detail", {"mode": "마음대로"})
    assert "고를 수 있는 값" in str(e.value)


def test_음수는_거부():
    """배송비 −5000 이 저장되면 판매가가 이상해진다."""
    with pytest.raises(ValueError):
        validate_config("shipping", {"return_fee": -5000})


def test_불리언을_숫자로_안_받는다():
    """True 가 1 로 새면 「배송비 1원」이 된다."""
    with pytest.raises(ValueError):
        validate_config("shipping", {"return_fee": True})


# ── 화면용 ──────────────────────────────────────────────────────

def test_화면이_폼을_그릴_수_있다():
    out = all_schemas()
    assert len(out) == 13
    for s in out:
        assert s["label"] and s["fields"]
        for f in s["fields"]:
            assert f["type"] in ("bool", "int", "text", "choice", "list")


# ── 저장 경로에 물려 있다 ───────────────────────────────────────

def test_set_rule_이_스키마로_검사한다():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from lemouton.registration.process_policy import create_policy, set_rule
    from shared.db import Base

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    try:
        p = create_policy(s, name="스키마검사")
        with pytest.raises(ValueError):
            set_rule(s, policy_id=p.id, item_key="shipping",
                     config={"retrun_fee": 3000})       # 오타
        r = set_rule(s, policy_id=p.id, item_key="shipping", config={"return_fee": 3000})
        s.flush()
        assert r.config["return_fee"] == 3000
        assert r.config["jeju_extra"] == 3000            # 기본값이 채워졌다
    finally:
        s.close()
