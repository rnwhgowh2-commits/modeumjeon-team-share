# -*- coding: utf-8 -*-
"""[TEST] 옥션·G마켓(ESM 2.0) 판매처 추가 — 계정등록·키입력 스켈레톤 배선.

범위 = 판매처관리 온보딩(자격증명 스키마·키 입력칸·계정 생성·플랫폼 설정)만.
실 주문/정산 조회 배선은 스펙 확보+검증 후(order_export.SUPPORTED 미포함) — 여기서 검증 안 함.
근거 스펙: docs/markets/auction.yaml · gmarket.yaml (ESM 2.0 JWT/HmacSHA256).
"""
import pytest


# ── secrets 스키마 (ESM 공통) ──
class TestEsmSecrets:
    @pytest.mark.parametrize("market", ["auction", "gmarket"])
    def test_registered(self, market):
        from lemouton.auth import secrets as S
        assert market in S.supported_markets()
        assert S.MARKET_SCHEMAS[market] is S.EsmCredentials

    def test_load_credentials_ok(self, monkeypatch):
        from lemouton.auth import secrets as S
        monkeypatch.setenv("AUCTION_TEST_MASTER_ID", "esmmaster01")
        monkeypatch.setenv("AUCTION_TEST_SECRET_KEY", "s3cr3t-signing-key")
        monkeypatch.setenv("AUCTION_TEST_SELLER_ID", "auction_seller01")
        creds = S.load_credentials(market="auction", env_prefix="AUCTION_TEST")
        assert isinstance(creds, S.EsmCredentials)
        assert creds.master_id == "esmmaster01"
        assert creds.seller_id == "auction_seller01"
        assert "s3cr3t-signing-key" not in repr(creds)      # 시크릿 마스킹

    def test_missing_key_raises(self, monkeypatch):
        from lemouton.auth import secrets as S
        for suf in ("MASTER_ID", "SECRET_KEY", "SELLER_ID"):
            monkeypatch.delenv(f"GMARKET_NOPE_{suf}", raising=False)
        with pytest.raises(S.SecretsMissingError):
            S.load_credentials(market="gmarket", env_prefix="GMARKET_NOPE")


# ── 판매처관리 키 입력칸·라벨·상태 ──
class TestAccountsWiring:
    @pytest.mark.parametrize("market", ["auction", "gmarket"])
    def test_key_suffixes_and_labels(self, market):
        from webapp.routes import accounts as A
        sufs = A.MARKET_KEY_SUFFIXES[market]
        assert sufs == ["MASTER_ID", "SECRET_KEY", "SELLER_ID"]
        for s in sufs:                                       # 모든 suffix 에 UI 라벨 존재
            assert s in A.KEY_LABELS
        # 자격증명 필드명(대문자) == suffix (load_credentials 매핑 규칙)
        from lemouton.auth.secrets import EsmCredentials
        assert [f.upper() for f in EsmCredentials.model_fields] == sufs

    @pytest.mark.parametrize("market", ["eleven11", "auction", "gmarket"])
    def test_status_ready_for_onboarding(self, market):
        from webapp.routes import accounts as A
        # ready = 계정추가 모달 노출(키 입력 가능). 실전송/조회는 별도 게이트.
        assert A.MARKET_METADATA[market]["status"] == "ready"

    @pytest.mark.parametrize("market", ["auction", "gmarket"])
    def test_secret_field_is_sensitive(self, market):
        from webapp.routes import accounts as A
        assert A.KEY_LABELS["SECRET_KEY"][1] is True         # 비밀번호 필드로 가림
        assert A.KEY_LABELS["MASTER_ID"][1] is False
        assert A.KEY_LABELS["SELLER_ID"][1] is False


# ── 플랫폼 설정(ESM 공통·site 구분) ──
class TestPlatformConfig:
    def test_auction_gmarket_configs(self):
        from shared.platforms import AUCTION, GMARKET
        assert AUCTION["site_id"] == "A" and GMARKET["site_id"] == "G"
        assert AUCTION["auth_audience"] == "sa.esmplus.com"
        assert AUCTION["auth_alg"] == "HS256"
        # 주문·정산·상품/가격/재고 모두 공개문서 확보(etapi.gmarket.com, 2026-07-09) → 경로 세팅.
        assert AUCTION["paths"]["orders"] == "/shipping/v1/Order/RequestOrders"
        assert GMARKET["paths"]["orders"] == "/shipping/v1/Order/RequestOrders"
        assert GMARKET["paths"]["settlement"] == "/account/v1/settle/getsettleorder"
        assert GMARKET["paths"]["detail"] == "/item/v1/goods/{goodsNo}"
        assert GMARKET["paths"]["price_change"] == "/item/v1/goods/{goodsNo}/price"
        assert GMARKET["paths"]["stock_change"] == "/item/v1/goods/{goodsNo}/stock"
        assert GMARKET["paths"]["options"] == "/item/v1/goods/{goodsNo}/recommended-options"

    def test_paths_match_permission_application(self):
        """경로는 권한신청서(도쿄산쵸메, 2026-07-20)에 실재하는 것만 — 추측 경로 금지.

        요약본 PDF 에 없다는 이유로 경로를 지우거나 "없는 API" 로 판단한 적이 있어(2026-07-21)
        정본을 신청서로 못 박는다. 여기 값을 고치려면 신청서 표부터 확인할 것.
        """
        from shared.platforms import AUCTION
        p = AUCTION["paths"]
        assert p["sell_status"] == "/item/v1/goods/{goodsNo}/sell-status"
        assert p["convert_legacy"] == "/item/v1/goods/convert-legacy-goods"
        assert p["site_goods_map"] == "/item/v1/site-goods/{siteGoodsNo}/goods-no"
        assert p["site_goods_of"] == "/item/v1/goods/{goodsNo}/status"
        assert p["search"] == "/item/v1/goods/search"
        # 신청서에 없는 API 를 몰래 끼워넣지 않았는지 — 후원/나눔쇼핑은 신청 X 이고
        # 마켓 공지(2026-04-16)로 서비스 자체가 종료됐다. 되살아나면 실패한다.
        assert not any("sponsorship" in v for v in p.values())

    def test_esm_not_in_supported_yet(self):
        # 옥션·G마켓은 키+실호출 검증 전이라 주문 엑셀 미노출(거짓 주문 방지).
        # (11번가는 2026-07-08 서버 실호출 검증 완료 → SUPPORTED 포함)
        from lemouton.markets import order_export as oe
        assert "auction" not in oe.SUPPORTED
        assert "gmarket" not in oe.SUPPORTED
        # 잠금은 이제 라이브 검증 기록으로 열린다 — 기록 없으면 실효 게이트도 잠김.
        assert "auction" not in oe.supported_markets()
        assert "gmarket" not in oe.supported_markets()
