from lemouton.sources.failure_classify import classify_crawl_failure, FAILURE_TYPES


def _t(msg, status="error"):
    return classify_crawl_failure(status, msg)["type"]


def test_ok_status_is_not_a_failure():
    assert classify_crawl_failure("ok", None) is None
    assert classify_crawl_failure("ok", "") is None


def test_block():
    assert _t("WAF 차단됨") == "block"
    assert _t("403 Forbidden") == "block"
    assert _t("bot blocked by captcha") == "block"


def test_login():
    assert _t("로그인 필요") == "login"
    assert _t("session expired (401)") == "login"
    assert _t("회원 인증 실패") == "login"


def test_parse():
    assert _t("옵션 파싱 실패") == "parse"
    assert _t("옵션없음 — 옵션 li 없음") == "parse"
    assert _t("inventory 매핑 미매칭") == "parse"


def test_network():
    assert _t("요청 타임아웃") == "network"
    assert _t("network error: ECONNREFUSED") == "network"
    assert _t("응답 없음 (timed out)") == "network"


def test_uncategorized_is_etc():
    # 어느 유형에도 안 걸리면 '유형 외'
    assert _t("알 수 없는 이상한 오류 zzz") == "etc"
    assert _t(None) == "etc"      # 에러인데 메시지 없음 → 유형 외
    assert _t("") == "etc"


def test_returns_label_and_emoji():
    r = classify_crawl_failure("error", "403 차단")
    assert r["type"] == "block"
    assert r["label"] == "차단"
    assert r["emoji"] == "🚫"
    # 모든 유형이 라벨·이모지를 가진다
    for t, meta in FAILURE_TYPES.items():
        assert meta["label"] and meta["emoji"]
