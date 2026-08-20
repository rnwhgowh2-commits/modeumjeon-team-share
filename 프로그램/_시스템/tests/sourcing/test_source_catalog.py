# -*- coding: utf-8 -*-
"""신규 소싱처 추가 — 소싱처 카탈로그(크롤링 가이드 기준) SSOT + 추가 API 가드 테스트.

검증 대상:
  ① 카탈로그가 크롤링 가이드의 소싱처를 빠짐없이/중복없이 담는다 (데이터 무결성).
  ② 추가 API 가 builtin/미존재 key 를 거부한다 (중복·오추가 차단).
  - 롯데아이몰은 어댑터 미보유(has_adapter=False)로 '크롤 미지원' 상태가 정상.
"""
import pytest

from lemouton.sourcing import source_registry as SR

# 크롤링 가이드 §1·§2 에 등재된 소싱처 (단일 진실 원천 대조)
GUIDE_KEYS = {
    'lemouton', 'musinsa', 'ssf', 'ssg', 'lotteon', 'ss_lemouton',
    'lotteimall', 'hmall',
}


# ─── ① 카탈로그 SSOT ───

def test_catalog_covers_guide_sources():
    keys = {c['key'] for c in SR.get_catalog()}
    assert keys == GUIDE_KEYS, f"카탈로그 ≠ 가이드: {keys ^ GUIDE_KEYS}"


def test_catalog_no_duplicate_keys():
    keys = [c['key'] for c in SR.get_catalog()]
    assert len(keys) == len(set(keys)), "카탈로그에 중복 key 존재 (무결성 위반)"


def test_catalog_builtin_six_match_registry():
    builtins = {c['key'] for c in SR.get_catalog() if SR.is_builtin_key(c['key'])}
    assert builtins == set(SR.get_keys()), "builtin 6 이 SOURCES 와 불일치"


def test_lotteimall_hmall_addable():
    """롯데아이몰·현대H몰 = builtin 아님(카탈로그 '추가' 대상)."""
    for key, label in (('lotteimall', '롯데아이몰'), ('hmall', '현대H몰')):
        e = SR.get_catalog_entry(key)
        assert e is not None
        assert SR.is_builtin_key(key) is False    # builtin 아님 → 카탈로그 '추가' 대상
        assert e['label'] == label


def test_hmall_lotteimall_verified():
    """현대H몰·롯데아이몰 둘 다 라이브 검증 완료 → has_adapter True(크롤 지원)."""
    assert SR.get_catalog_entry('hmall')['has_adapter'] is True
    assert SR.get_catalog_entry('lotteimall')['has_adapter'] is True


def test_catalog_entries_have_required_fields():
    for c in SR.get_catalog():
        for f in ('key', 'label', 'glyph', 'logo_color', 'domain',
                  'crawl_method', 'stock_rule', 'benefit', 'has_adapter'):
            assert f in c, f"{c.get('key')} 누락 필드: {f}"


def test_get_catalog_returns_copy():
    """get_catalog() 반환값 변경이 원본 SOURCE_CATALOG 를 오염시키지 않는다."""
    cat = SR.get_catalog()
    cat[0]['label'] = 'XXX'
    assert SR.get_catalog()[0]['label'] != 'XXX'


def test_unknown_key_returns_none():
    assert SR.get_catalog_entry('29cm') is None


# ─── ② 추가 API 가드 (DB 미접근 분기) ───

@pytest.fixture
def client(monkeypatch):
    """api 블루프린트만 띄운 테스트 클라이언트. import 실패 시 skip."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    try:
        from flask import Flask
        from webapp.routes import api as api_mod
    except Exception as e:  # 무거운 의존성 등 — 가드 테스트는 건너뜀
        pytest.skip(f"api blueprint import 불가: {e}")
    app = Flask(__name__)
    app.register_blueprint(api_mod.bp)
    return app.test_client()


def test_add_rejects_builtin(client):
    r = client.post('/api/sources/catalog/add', json={'key': 'musinsa'})
    body = r.get_json()
    assert body['ok'] is False
    assert '기본 제공' in body['error']


def test_add_rejects_unknown(client):
    r = client.post('/api/sources/catalog/add', json={'key': 'no_such_src'})
    body = r.get_json()
    assert body['ok'] is False
    assert '카탈로그에 없는' in body['error']
