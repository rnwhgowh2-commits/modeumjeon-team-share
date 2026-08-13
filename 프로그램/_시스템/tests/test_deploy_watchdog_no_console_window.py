"""tests/test_deploy_watchdog_no_console_window.py — 배포 감시견이 검은 콘솔 창을
띄우지 않도록 잠근다.

2026-08-13 실사고: 감시견은 예약 작업에서 pythonw.exe(= 콘솔이 아예 없는 파이썬)로
10분마다 돈다. 부모에 콘솔이 없으면 윈도우는 자식 콘솔 앱(gh.exe·git.exe)마다
**새 콘솔 창을 띄운다**. 한 번 돌 때 gh·git 을 예닐곱 번 부르니 화면에 검은 창이
계속 튀어나왔다. `capture_output=True` 는 stdio 파이프일 뿐 콘솔 할당과 무관해서
이걸 막지 못한다 — CREATE_NO_WINDOW 가 있어야 한다.

아래 두 번째 시험이 핵심이다. **부모를 pythonw 로 띄워** 실제 조건을 그대로 만든다.
그냥 pytest 안에서 `_run` 을 부르면 부모(python.exe)의 콘솔을 물려받아,
고장 난 상태로도 초록불이 뜬다.
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "deploy_watchdog.py"


def _load_watchdog():
    spec = importlib.util.spec_from_file_location("deploy_watchdog_under_test", WATCHDOG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_passes_no_window_flag_on_windows_and_nothing_elsewhere(monkeypatch):
    """윈도우면 CREATE_NO_WINDOW 를 붙이고, 리눅스면 아예 안 붙인다.

    리눅스는 `creationflags` 를 넘기기만 해도 ValueError 라, 무조건 붙이면 CI 가 깨진다.
    """
    mod = _load_watchdog()
    seen: dict = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    mod._run(["gh", "run", "list"])

    assert seen, "subprocess.run 이 불리지 않았다 — 이 시험은 아무것도 검사하지 않았다"
    if os.name == "nt":
        assert seen.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW, (
            "gh·git 이 검은 창을 띄운다 — CREATE_NO_WINDOW 가 빠졌다"
        )
    else:
        assert "creationflags" not in seen, (
            "리눅스에서 creationflags 를 넘기면 ValueError 로 감시견이 죽는다"
        )


@pytest.mark.skipif(os.name != "nt", reason="콘솔 창 증상은 윈도우 전용")
def test_child_gets_no_visible_window_when_parent_has_no_console(tmp_path):
    """예약 실행과 똑같이 pythonw(콘솔 없음)를 부모로 세우고, 자식이 스스로
    「내 콘솔 창이 보이나」를 보고하게 한다. timing 에 기대지 않는 참/거짓."""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pytest.skip("pythonw.exe 를 찾지 못했다")

    report = tmp_path / "child_window.txt"

    # 자식(콘솔 서브시스템 = gh.exe 와 같은 조건)이 자기 콘솔 창의 가시성을 적는다.
    # 코드를 -c 문자열에 끼워 넣지 않고 파일로 둔다 — 따옴표를 겹치면 경로의 `\U`(C:\Users)
    # 가 유니코드 이스케이프로 먹혀 시험이 단언이 아니라 SyntaxError 로 죽는다.
    reporter_py = tmp_path / "reporter.py"
    reporter_py.write_text(
        "import ctypes, sys\n"
        "h = ctypes.windll.kernel32.GetConsoleWindow()\n"
        "v = ctypes.windll.user32.IsWindowVisible(h) if h else 0\n"
        "open(sys.argv[1], 'w', encoding='utf-8').write(str(int(v)))\n",
        encoding="utf-8",
    )
    driver = (
        "import importlib.util;"
        "spec=importlib.util.spec_from_file_location('w', r'{wd}');"
        "m=importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(m);"
        "m._run([r'{py}', r'{rep}', r'{out}'])"
    ).format(wd=WATCHDOG, py=sys.executable, rep=reporter_py, out=report)

    subprocess.run([str(pythonw), "-c", driver], timeout=120)

    if not report.exists():
        # pythonw 는 오류를 조용히 삼킨다 — 같은 코드를 콘솔 파이썬으로 돌려 이유를 드러낸다.
        echo = subprocess.run(
            [sys.executable, "-c", driver], capture_output=True, text=True, timeout=120
        )
        pytest.fail(
            "자식이 보고를 못 남겼다 — 시험이 아무것도 검사하지 않았다.\n"
            f"rc={echo.returncode}\nstderr={echo.stderr[-1500:]}"
        )
    assert report.read_text(encoding="utf-8").strip() == "0", (
        "콘솔 없는 부모에서 자식이 보이는 창을 띄웠다 — 사장님 화면에 검은 창이 뜬다"
    )
