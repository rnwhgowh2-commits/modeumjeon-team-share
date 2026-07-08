# -*- coding: utf-8 -*-
"""옥션·G마켓(ESM 2.0 · 이베이코리아) 통합 셀러 API 클라이언트.

인증 = JWT(HmacSHA256) — auth.build_headers. 주문조회 = orders.iter_orders.
옥션·G마켓은 같은 ESM+ 마스터 계정(master_id·secret_key 공통), site_id·seller_id 만 다름.
근거 스펙: docs/markets/auction.yaml · gmarket.yaml (etapi.gmarket.com 공개문서 실측).
"""
