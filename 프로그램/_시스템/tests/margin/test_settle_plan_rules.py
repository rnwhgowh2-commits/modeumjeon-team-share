"""정산예정금액 탭 — 규칙표 저장소.

기본값 로드·저장 왕복·깨진 파일 복구·빠른정산 계정 스위치.
규칙표가 데이터인 이유: 마켓 정산 정책은 바뀐다(스펙 §3-3).
"""
import importlib


def _reload_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    from lemouton.margin import settle_plan_rules as R
    importlib.reload(R)
    return R


def test_기본_규칙에_6마켓이_전부_있다(tmp_path, monkeypatch):
    R = _reload_rules(tmp_path, monkeypatch)
    rules = R.load_rules()
    for mk in ("coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"):
        assert mk in rules["markets"], mk
        m = rules["markets"][mk]
        assert m["auto_confirm_days"] >= 0
        assert m["cycle_days"] >= 0
    assert rules["markets"]["coupang"]["split_ratio"] == 0.7
    assert rules["fast_accounts"] == {}          # 기본: 빠른정산 미지정


def test_저장하면_다음_로드에_반영(tmp_path, monkeypatch):
    R = _reload_rules(tmp_path, monkeypatch)
    rules = R.load_rules()
    rules["fast_accounts"] = {"smartstore": ["본계정"], "coupang": ["쿠팡1"]}
    rules["markets"]["lotteon"]["cycle_days"] = 9
    R.save_rules(rules)
    again = R.load_rules()
    assert again["fast_accounts"]["smartstore"] == ["본계정"]
    assert again["markets"]["lotteon"]["cycle_days"] == 9


def test_저장본에_없는_마켓과_키는_기본값으로_채운다(tmp_path, monkeypatch):
    R = _reload_rules(tmp_path, monkeypatch)
    import json
    with open(R._rules_path(), "w", encoding="utf-8") as f:
        json.dump({"markets": {"lotteon": {"cycle_days": 11, "몰래키": 1}}}, f)
    rules = R.load_rules()
    assert rules["markets"]["lotteon"]["cycle_days"] == 11
    assert "몰래키" not in rules["markets"]["lotteon"]      # 아는 키만
    assert rules["markets"]["coupang"]["split_ratio"] == 0.7  # 누락 마켓 보충


def test_깨진_파일이면_기본값으로_복구(tmp_path, monkeypatch):
    R = _reload_rules(tmp_path, monkeypatch)
    with open(R._rules_path(), "w", encoding="utf-8") as f:
        f.write("{깨짐")
    rules = R.load_rules()
    assert "coupang" in rules["markets"]
