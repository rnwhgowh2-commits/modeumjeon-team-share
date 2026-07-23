# -*- coding: utf-8 -*-
"""가공 규칙 — **목록형 칸 편집**(치환표·금지어·고정태그·상세 이미지…).

여태 화면에 「N개 — 목록 편집은 다음 단계입니다」만 떠서 §7-1 의 핵심인
치환표·금지어를 사장님이 넣을 방법이 없었다. 이 테스트가 그 구멍을 막는다.

━━ 이 파일이 지키는 약속 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ① 검사 규칙은 **서버 한 벌**(validate_config)뿐이다. 화면은 그 답을 보여주기만 한다.
  ② 사장님이 넣은 값을 프로그램이 마음대로 정렬·변형하지 않는다.
     앞뒤 공백·빈 줄만 지우고, **지웠으면 지웠다고 알린다**(notices).
  ③ 같은 말이 두 번 있어도 막지 않는다 — 알리기만 한다(사장님 의도일 수 있다).
"""
import json
import os
import shutil
import subprocess
import uuid

import pytest

from lemouton.registration.process_rule_schema import (
    SCHEMAS,
    all_schemas,
    schema_for,
    validate_config,
)

_MARK = "목록편집"

_HERE = os.path.dirname(os.path.abspath(__file__))
_JS = os.path.normpath(os.path.join(
    _HERE, "..", "..", "webapp", "static", "process_list_editor.js"))


# ── ① 어떤 칸이 목록형인지 스키마가 스스로 말한다 ────────────────

def _list_fields():
    return [(k, f) for k, sc in SCHEMAS.items() for f in sc.fields if f.type == "list"]


def test_목록형_칸이_빠짐없이_모양을_갖는다():
    """화면이 「1열 목록」인지 「2열 표」인지 알아야 편집칸을 그린다."""
    fields = _list_fields()
    assert fields, "목록형 칸이 하나도 없다 — 스키마가 바뀌었나?"
    for item_key, f in fields:
        assert f.item_shape in ("text", "pair"), f"{item_key}.{f.key} 에 모양이 없다"


def test_목록형_칸_목록이_설계서와_같다():
    """새 목록칸이 생기면 편집 UI 도 같이 만들라고 여기서 걸린다."""
    got = {f"{k}.{f.key}" for k, f in _list_fields()}
    assert got == {
        "name.token_order",        # 상품명 조립 순서
        "name.replacements",       # 치환표 (2열)
        "images.excluded_brands",  # 이미지 제외 브랜드
        "detail.top_images",       # 상세 상단 이미지
        "detail.bottom_images",    # 상세 하단 이미지
        "tags.fixed_tags",         # 고정 태그
        "banned_words.collect_banned",
        "banned_words.upload_banned",
    }


def test_치환표만_2열이고_열_이름이_있다():
    f = next(x for x in schema_for("name").fields if x.key == "replacements")
    assert f.item_shape == "pair"
    assert f.columns == ("찾을 말", "바꿀 말")
    # 나머지는 전부 1열
    for k, other in _list_fields():
        if f"{k}.{other.key}" != "name.replacements":
            assert other.item_shape == "text"


def test_화면이_받는_스키마에도_모양이_실린다():
    """화면은 /bulk/api/process/schema 하나만 보고 폼을 그린다."""
    for it in all_schemas():
        for f in it["fields"]:
            if f["type"] == "list":
                assert f["item_shape"] in ("text", "pair")
                assert isinstance(f["columns"], list)


# ── ② 1열 목록 검사 ─────────────────────────────────────────────

def test_1열_목록은_넣은_순서_그대로_남는다():
    """정렬해서 덮어쓰면 사장님이 정한 우선순위가 사라진다."""
    c = validate_config("banned_words", {"collect_banned": ["짝퉁", "가품", "A급"]})
    assert c["collect_banned"] == ["짝퉁", "가품", "A급"]


def test_빈_줄과_앞뒤_공백은_지우고_지웠다고_알린다():
    noti = []
    c = validate_config("banned_words",
                        {"collect_banned": ["  짝퉁 ", "", "   ", "가품"]}, notices=noti)
    assert c["collect_banned"] == ["짝퉁", "가품"]
    assert any("공백" in n for n in noti), noti
    assert any("빈 줄" in n for n in noti), noti


def test_고칠_게_없으면_알림도_없다():
    noti = []
    validate_config("banned_words", {"collect_banned": ["짝퉁", "가품"]}, notices=noti)
    assert noti == []


def test_같은_말이_두_번이면_막지_않고_알린다():
    noti = []
    c = validate_config("tags", {"fixed_tags": ["세일", "신상", "세일"]}, notices=noti)
    assert c["fixed_tags"] == ["세일", "신상", "세일"]      # 그대로 저장된다
    assert any("세일" in n and "2번" in n for n in noti), noti


def test_글자가_아닌_항목은_사유와_함께_거부():
    with pytest.raises(ValueError) as e:
        validate_config("tags", {"fixed_tags": ["세일", 3]})
    assert "2번째" in str(e.value)


def test_목록_자리에_목록이_아닌_값은_거부():
    with pytest.raises(ValueError):
        validate_config("tags", {"fixed_tags": "세일"})


# ── ③ 치환표(2열) 검사 ──────────────────────────────────────────

def test_치환표는_찾을말_바꿀말_두_칸():
    c = validate_config("name", {"replacements": [["화이트 블랙", "팬다"], ["재킷", "자켓"]]})
    assert c["replacements"] == [["화이트 블랙", "팬다"], ["재킷", "자켓"]]


def test_치환표_바꿀말은_비어도_된다():
    """빈 칸 = 「그 말을 지운다」 는 뜻이라 정상이다."""
    c = validate_config("name", {"replacements": [["[단독]", ""]]})
    assert c["replacements"] == [["[단독]", ""]]


def test_치환표_찾을말이_비면_사유와_함께_거부():
    with pytest.raises(ValueError) as e:
        validate_config("name", {"replacements": [["", "팬다"]]})
    assert "찾을 말" in str(e.value)


def test_치환표_아무것도_안_적은_행은_빼고_알린다():
    """「행 추가」만 누르고 안 적은 줄이 조용히 저장되면 안 된다 — 빼고 알린다."""
    noti = []
    c = validate_config("name",
                        {"replacements": [["재킷", "자켓"], ["", ""], ["  ", " "]]},
                        notices=noti)
    assert c["replacements"] == [["재킷", "자켓"]]
    assert any("빈 줄" in n for n in noti), noti


def test_치환표_칸수가_안_맞으면_거부():
    with pytest.raises(ValueError) as e:
        validate_config("name", {"replacements": [["재킷"]]})
    assert "두 칸" in str(e.value)


def test_치환표_같은_찾을말이_두_번이면_알린다():
    noti = []
    c = validate_config("name",
                        {"replacements": [["재킷", "자켓"], ["재킷", "JK"]]}, notices=noti)
    assert len(c["replacements"]) == 2
    assert any("재킷" in n and "2번" in n for n in noti), noti


# ── ④ 저장 API 왕복 ─────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.process_policy import ProcessPolicy
    s = SessionLocal()
    try:
        for p in s.query(ProcessPolicy).all():
            if p.name and p.name.startswith(_MARK):
                s.delete(p)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()


def _policy(client):
    nm = f"{_MARK}-{uuid.uuid4().hex[:8]}"
    return client.post('/bulk/api/process/policies', json={"name": nm}).get_json()["id"]


def test_치환표를_저장하면_새로_읽어도_남아_있다(client):
    pid = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/rules', json={
        "item_key": "name",
        "config": {"replacements": [["재킷", "자켓"], ["화이트 블랙", "팬다"]]}})
    assert r.status_code == 200, r.get_data(as_text=True)
    got = client.get(f'/bulk/api/process/policies/{pid}/rules').get_json()
    assert got["rules"]["name"]["replacements"] == [["재킷", "자켓"], ["화이트 블랙", "팬다"]]


def test_금지어_목록도_왕복한다(client):
    pid = _policy(client)
    client.post(f'/bulk/api/process/policies/{pid}/rules', json={
        "item_key": "banned_words",
        "config": {"collect_banned": ["짝퉁", "가품"], "upload_banned": ["단독"]}})
    r = client.get(f'/bulk/api/process/policies/{pid}/rules').get_json()["rules"]
    assert r["banned_words"]["collect_banned"] == ["짝퉁", "가품"]
    assert r["banned_words"]["upload_banned"] == ["단독"]


def test_저장_응답이_손댄_내용을_알려준다(client):
    """조용한 실패·조용한 수정 금지 — 지운 게 있으면 화면에 뜬다."""
    pid = _policy(client)
    j = client.post(f'/bulk/api/process/policies/{pid}/rules', json={
        "item_key": "banned_words",
        "config": {"collect_banned": [" 짝퉁 ", "", "짝퉁"]}}).get_json()
    assert j["ok"] is True
    assert j["notices"], "무엇을 지웠는지 알려주지 않는다"
    assert any("빈 줄" in n for n in j["notices"])
    assert any("2번" in n for n in j["notices"])


def test_손댄_게_없으면_알림도_비어_있다(client):
    pid = _policy(client)
    j = client.post(f'/bulk/api/process/policies/{pid}/rules', json={
        "item_key": "tags", "config": {"fixed_tags": ["세일"]}}).get_json()
    assert j["notices"] == []


def test_잘못된_치환표는_400과_사유(client):
    pid = _policy(client)
    r = client.post(f'/bulk/api/process/policies/{pid}/rules', json={
        "item_key": "name", "config": {"replacements": [["", "팬다"]]}})
    assert r.status_code == 400
    assert "찾을 말" in r.get_json()["error"]


# ── ⑤ 화면 ──────────────────────────────────────────────────────

def test_상세화면에_목록_편집기가_실린다(client):
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    assert 'process_list_editor.js' in html
    assert '아직 등록된 치환 규칙이 없습니다' in html


def test_다음_단계입니다_라는_변명이_사라졌다(client):
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    assert '목록 편집은 다음 단계입니다' not in html


def test_자동완성이_값을_덮어쓰지_못하게_막았다(client):
    """크롬은 autocomplete=off 를 무시한다 — 고유 name + readonly 해제까지 필요."""
    html = client.get(f'/bulk/process/policy/{_policy(client)}').get_data(as_text=True)
    assert 'autocomplete="off"' in html
    assert "removeAttribute('readonly')" in html
    assert '_nofill' in html          # 칸마다 고유한 name


# ── ⑥ 엑셀 붙여넣기 (화면 스크립트) ──────────────────────────────

def _js(fn, arg):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 가 없어 붙여넣기 해석을 못 돌린다")
    code = ("const m=require(process.argv[1]);"
            "process.stdout.write(JSON.stringify(m[process.argv[2]](JSON.parse(process.argv[3]))));")
    p = subprocess.run([node, "-e", code, _JS, fn, json.dumps(arg)],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_엑셀에서_두_열을_복사해_붙이면_여러_행이_된다():
    """엑셀 복사 = 열은 탭, 행은 줄바꿈. 이게 실제 클립보드 모양이다."""
    pasted = "재킷\t자켓\r\n화이트 블랙\t팬다\r\n"
    assert _js("parseTable", pasted) == [["재킷", "자켓"], ["화이트 블랙", "팬다"]]


def test_한_열만_복사하면_바꿀말은_빈_칸():
    assert _js("parseTable", "[단독]\r\n[정품]\r\n") == [["[단독]", ""], ["[정품]", ""]]


def test_엑셀이_따옴표로_감싼_칸도_읽는다():
    """쉼표·따옴표가 든 칸은 엑셀이 "..." 로 감싸서 내보낸다."""
    assert _js("parseTable", '"재킷, 자켓"\t"팬""다"') == [["재킷, 자켓", '팬"다']]


def test_붙여넣기_해석은_빈_줄을_버린다():
    assert _js("parseTable", "재킷\t자켓\n\n\n") == [["재킷", "자켓"]]


def test_1열_목록_붙여넣기():
    assert _js("parseLines", "짝퉁\r\n 가품 \r\n\r\n") == ["짝퉁", "가품"]


def test_한_칸짜리_붙여넣기는_그냥_평범한_붙여넣기():
    """단어 하나 붙일 땐 표로 쪼개면 안 된다 — 커서 자리에 그대로 들어가야 한다."""
    assert _js("looksTabular", "짝퉁") is False
    assert _js("looksTabular", "짝퉁\r\n") is False      # 엑셀 한 칸 복사
    assert _js("looksTabular", "재킷\t자켓") is True
    assert _js("looksTabular", "짝퉁\n가품") is True
