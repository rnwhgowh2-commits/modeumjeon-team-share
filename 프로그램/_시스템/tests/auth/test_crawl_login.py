# -*- coding: utf-8 -*-
"""[TEST] 크롤 자동로그인 자격증명 — Fernet 암호화 저장/조회.

방식 A(완전자동): 판매자센터 비번을 저장하되 평문 금지 → Fernet 대칭 암호화.
키는 데이터(.env)와 분리. 키 없으면 자동 생성(별도 파일). 왕복·마스킹·상태 검증.
"""
import os
import importlib


def _fresh(monkeypatch, tmp_path, key=None):
    """crawl_login 모듈을 tmp 경로 + (선택)고정키로 재로드."""
    monkeypatch.setenv("MOUM_SECRETS_ENV", str(tmp_path / ".env"))
    monkeypatch.setenv("MOUM_CRAWL_LOGIN_KEY_FILE", str(tmp_path / ".crawl_key"))
    if key is None:
        monkeypatch.delenv("MOUM_CRAWL_LOGIN_KEY", raising=False)
    else:
        monkeypatch.setenv("MOUM_CRAWL_LOGIN_KEY", key)
    import lemouton.auth.crawl_login as cl
    importlib.reload(cl)
    return cl


class TestEncryptRoundtrip:
    def test_encrypt_then_decrypt_returns_plaintext(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        token = cl.encrypt_pw("s3cret!한글비번")
        assert token != "s3cret!한글비번"          # 평문 아님
        assert "s3cret" not in token                # 평문 노출 0
        assert cl.decrypt_pw(token) == "s3cret!한글비번"

    def test_empty_password_roundtrip(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        assert cl.decrypt_pw(cl.encrypt_pw("")) == ""

    def test_key_persisted_across_reload(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        token = cl.encrypt_pw("pw-1")
        cl2 = _fresh(monkeypatch, tmp_path)        # 같은 키파일 → 복호 가능
        assert cl2.decrypt_pw(token) == "pw-1"

    def test_key_file_separate_from_secrets_env(self, monkeypatch, tmp_path):
        """암호화 키는 시크릿 .env 와 다른 파일이어야 한다(.env 유출만으론 복호 불가)."""
        cl = _fresh(monkeypatch, tmp_path)
        cl.encrypt_pw("pw")
        keyfile = tmp_path / ".crawl_key"
        secrets_env = tmp_path / ".env"
        assert keyfile.exists()
        assert keyfile.resolve() != secrets_env.resolve()


class TestSaveLoad:
    def test_save_then_status_and_id(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        cl.save_login("LOTTEON_A", "lotte_brandA", "pw-A")
        st = cl.login_status("LOTTEON_A")
        assert st["saved"] is True
        assert st["login_id"] == "lotte_brandA"

    def test_get_password_decrypts(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        cl.save_login("LOTTEON_A", "id", "pw-secret")
        assert cl.get_password("LOTTEON_A") == "pw-secret"

    def test_unsaved_status(self, monkeypatch, tmp_path):
        cl = _fresh(monkeypatch, tmp_path)
        st = cl.login_status("LOTTEON_NONE")
        assert st["saved"] is False
        assert st.get("login_id") in (None, "")

    def test_password_stored_encrypted_not_plaintext(self, monkeypatch, tmp_path):
        """저장 파일에 비번 평문이 남지 않아야 한다."""
        cl = _fresh(monkeypatch, tmp_path)
        cl.save_login("LOTTEON_A", "id", "PLAINTEXT_PW_XYZ")
        raw = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "PLAINTEXT_PW_XYZ" not in raw       # 평문 저장 금지
        assert "LOTTEON_A_CRAWL_LOGIN_PW_ENC" in raw
