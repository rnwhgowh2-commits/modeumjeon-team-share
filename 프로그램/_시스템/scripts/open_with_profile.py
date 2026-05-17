"""대표 크롤 계정 프로필로 URL 을 새 Chromium 창에 열기.

사용법:
  python -m scripts.open_with_profile <profile_dir> <url>

webapp 의 /api/options/<sku>/sources/<src_id>/open-with-profile 엔드포인트가
subprocess.Popen 으로 detach 실행. 사용자가 창을 닫을 때까지 살아있음.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m scripts.open_with_profile <profile_dir> <url>")
        sys.exit(1)
    profile_dir = sys.argv[1]
    url = sys.argv[2]

    if not Path(profile_dir).exists():
        print(f"[ERROR] 프로필 디렉터리 없음: {profile_dir}")
        sys.exit(2)

    print(f"[OPEN] profile={profile_dir}")
    print(f"[OPEN] url={url}")

    with sync_playwright() as pw:
        # headless=False — 사용자에게 보임. 영구 프로필 = 로그인 상태 유지
        # ★ Chrome 우선 — scrapers/base.py 의 로그인 마법사가 channel="chrome" 으로 쿠키 저장하므로
        #    같은 채널로 띄워야 prefs/Local State 100% 호환
        # → Edge 폴백 (Chrome 미설치 환경)
        # → bundled chromium 최후 폴백
        common_args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ]
        context = None
        last_err = None
        for channel in ("chrome", "msedge", None):
            try:
                kwargs = dict(
                    user_data_dir=str(profile_dir),
                    headless=False,
                    args=common_args,
                    no_viewport=True,
                )
                if channel:
                    kwargs["channel"] = channel
                context = pw.chromium.launch_persistent_context(**kwargs)
                print(f"[OPEN] 채널: {channel or 'bundled chromium'}")
                break
            except Exception as e:
                last_err = e
                print(f"[WARN] 채널 {channel or 'bundled'} 실패: {e}")
        if context is None:
            print(f"[ERROR] 모든 채널 실패: {last_err}")
            sys.exit(3)
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            print(f"[OPEN] 페이지 로드 완료. 사용자가 창을 닫을 때까지 대기...")
            # 사용자가 창 닫을 때까지 대기
            try:
                page.wait_for_event("close", timeout=0)
            except Exception:
                pass
        except KeyboardInterrupt:
            print("[OPEN] 인터럽트됨")
        finally:
            try: context.close()
            except Exception: pass
    print("[OPEN] 종료")


if __name__ == "__main__":
    main()
