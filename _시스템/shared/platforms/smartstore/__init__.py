# -*- coding: utf-8 -*-
"""
스마트스토어 커머스 API 연동 모듈.

역할 경계 (CLAUDE.md):
- 판매처 업로드/조회 전용. 소싱처 수집 로직 금지.
- 모든 설정값은 config.SMARTSTORE 참조.
- 가격·재고 처리 전 validator.py 통과 필수.
"""
