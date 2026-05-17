"""SSG 로그인 1회 — 브라우저 자동 열림. 로그인 완료 시 세션 자동 저장.

저장 경로: data/auth/ssg_ditodalal.json
이후 SSG 모든 페치는 이 세션 재사용 (반복 로그인 불필요).
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from lemouton.sourcing.auth import save_state_after_manual_login

ok = save_state_after_manual_login(
    source='ssg',
    account_name='ditodalal',
    login_url='https://www.ssg.com/login.ssg',
    headless=False,
)
print('✅ 세션 저장 완료' if ok else '❌ 세션 저장 실패')
