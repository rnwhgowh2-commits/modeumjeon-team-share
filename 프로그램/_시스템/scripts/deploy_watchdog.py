# -*- coding: utf-8 -*-
"""배포 감시견 — GitHub Actions 가 죽어도 main 이 라이브에 반드시 반영되게 만든다.

왜 만들었나 (2026-08-06 실제 사고):
    GitHub Actions 대형 장애로 **웹훅이 15% 만 처리**됐다. 그래서 main 에 push 를 해도
    워크플로 런이 **아예 안 만들어졌다**. 실패한 게 아니라 "없었다" — 빨간불도 안 뜨니
    아무도 몰랐고, 6시간 동안 #885·#881·#887 이 라이브에 못 나갔다.
    반면 `workflow_dispatch`(수동 실행)는 장애 중에도 **정상 동작했다**
    (실증: run 31128513825, 21:44 UTC 시작 → 22:02 무중단 배포 성공).
    Git 자체(push/fetch)와 REST API 도 내내 operational 이었다.
    → 그러니 "푸시가 런을 못 만들었으면, 내가 대신 만들어 준다"가 이 감시견이다.

두 번째 사고 (같은 날, 아슬아슬하게 막음):
    15:52 에 걸려 있던 **묵은 대기 런**(옛 커밋 4366f15a)이 6시간 뒤 되살아나
    최신 코드(160309d9)를 옛 코드로 **되돌리기 직전**까지 갔다.
    → 그래서 "main 보다 뒤처진 런"은 배포 단계에 들어가기 전에 취소한다.
    🔴 단, `deploy` 잡이 이미 돌기 시작했으면 취소하지 않는다 —
       SSH·docker 빌드 중간을 끊으면 서버가 깨진다(워크플로 주석의 경고와 같은 이유).

무엇을 근거로 판단하나:
    Actions API 가 아니라 **git ls-remote**(=Git 서비스)로 main 의 진짜 머리를 읽는다.
    장애 때 죽은 건 Actions 였고 Git 은 살아 있었다. 죽은 것에게 죽었냐고 묻지 않는다.

쓰는 법:
    python scripts/deploy_watchdog.py --report     # 상태만 보기 (아무것도 안 건드림)
    python scripts/deploy_watchdog.py --dry-run    # 무엇을 할지만 출력
    python scripts/deploy_watchdog.py              # 실제 조치 (예약 실행용)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKFLOW = "aws-lightsail-deploy.yml"
BRANCH = "main"
DEPLOY_JOB = "deploy"          # 이 잡이 시작됐으면 취소 금지 (SSH 중단 = 서버 파손)

# main 이 이만큼 지나도 성공 배포가 없으면 손으로 밀어 넣는다.
# 정상일 때 배포는 8~12분이라, 그보다 넉넉히 잡아 "느린 것"과 "안 걸린 것"을 구분한다.
GRACE_MIN = 20
# 같은 커밋을 이 시간 안에 두 번 밀어 넣지 않는다 (같은 실패를 무한 반복하지 않기).
COOLDOWN_MIN = 30
# 묵은 런을 되돌리기 위험으로 판정하기까지의 최소 나이.
STALE_MIN = 20

STATE = Path.home() / ".moum_deploy_watchdog.json"
LOG = Path.home() / ".moum_deploy_watchdog.log"


# 예약 실행은 pythonw.exe(콘솔 없는 파이썬)로 돈다. 부모에 콘솔이 없으면 윈도우가
# 자식 콘솔 앱(gh.exe·git.exe)마다 **새 검은 창을 띄운다** — capture_output 을 줘도
# 막히지 않는다(파이프는 stdio 만 돌릴 뿐 콘솔 할당과 무관). 10분마다 gh·git 을
# 예닐곱 번 부르니 사장님 화면에 창이 계속 튀어나온다. CREATE_NO_WINDOW 로 막는다.
# creationflags 는 리눅스에서 넘기기만 해도 ValueError 라 CI 가 깨진다 → 윈도우에서만 붙인다.
_HIDE_WINDOW_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
)


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        args, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        **_HIDE_WINDOW_KWARGS,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _utf8_stdout() -> None:
    """예약 실행(schtasks)은 콘솔이 아니라 cp949 로 잡힐 때가 있다 — 한글이 터지면
    스크립트 자체가 죽어 감시견이 조용히 멈춘다. 그래서 시작하자마자 강제로 UTF-8."""
    # pythonw.exe(창 없이 예약 실행)로 돌면 stdout 이 아예 None 이라 print 가 터진다.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z  {msg}"
    print(line)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(patch: dict) -> None:
    """기존 값을 덮지 않고 얹는다 — 심장박동이 쿨다운 기록을 지우면 안 된다."""
    state = load_state()
    state.update(patch)
    try:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / ".git").exists():
            return p
    return here.parent


def age_min(iso: str) -> float:
    """ISO8601(Z) → 지금으로부터 몇 분 지났나."""
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(timezone.utc) - t).total_seconds() / 60.0


# ── 사실 수집 ────────────────────────────────────────────────────────────────
def remote_head(root: Path) -> str | None:
    """main 의 진짜 머리 — Actions 가 아니라 **Git** 에게 묻는다."""
    rc, out = _run(["git", "ls-remote", "origin", f"refs/heads/{BRANCH}"], cwd=root)
    if rc != 0 or not out.strip():
        log(f"❌ git ls-remote 실패: {out.strip()[:200]}")
        return None
    return out.split()[0]


def fetch(root: Path) -> None:
    _run(["git", "fetch", "origin", BRANCH, "--quiet"], cwd=root)


def head_commit_time(root: Path, sha: str) -> str | None:
    rc, out = _run(["git", "show", "-s", "--format=%cI", sha], cwd=root)
    return out.strip() if rc == 0 and out.strip() else None


def is_ancestor(root: Path, older: str, newer: str) -> bool:
    rc, _ = _run(["git", "merge-base", "--is-ancestor", older, newer], cwd=root)
    return rc == 0


def list_runs(root: Path) -> list[dict]:
    rc, out = _run([
        "gh", "run", "list", "--workflow", WORKFLOW, "--branch", BRANCH,
        "--limit", "40", "--json",
        "databaseId,headSha,status,conclusion,createdAt,event",
    ], cwd=root)
    if rc != 0:
        log(f"❌ gh run list 실패: {out.strip()[:200]}")
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def deploy_job_started(root: Path, run_id: int) -> bool:
    """`deploy` 잡이 이미 돌기 시작했나 — 시작했으면 절대 취소하지 않는다."""
    rc, out = _run(["gh", "run", "view", str(run_id), "--json", "jobs"], cwd=root)
    if rc != 0:
        return True  # 모르면 안전한 쪽(취소 안 함)
    try:
        jobs = json.loads(out).get("jobs", [])
    except ValueError:
        return True
    for j in jobs:
        if j.get("name") == DEPLOY_JOB and j.get("status") in ("in_progress", "completed"):
            return True
    return False


# ── 조치 ────────────────────────────────────────────────────────────────────
def cancel(root: Path, run_id: int) -> tuple[bool, str]:
    rc, out = _run(["gh", "run", "cancel", str(run_id)], cwd=root)
    return rc == 0, out.strip()[:200]


def dispatch(root: Path) -> tuple[bool, str]:
    rc, out = _run(["gh", "workflow", "run", WORKFLOW, "--ref", BRANCH], cwd=root)
    return rc == 0, out.strip()[:200]


# ── 본체 ────────────────────────────────────────────────────────────────────
def main() -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="무엇을 할지만 출력, 실제 조치 안 함")
    ap.add_argument("--report", action="store_true", help="상태만 보기 (조치 없음)")
    args = ap.parse_args()
    act = not (args.dry_run or args.report)

    root = repo_root()
    head = remote_head(root)
    if not head:
        return 2
    fetch(root)
    head_time = head_commit_time(root, head)
    head_age = age_min(head_time) if head_time else 0.0

    # 심장박동 — 감시견이 **살아서 돌았다**는 증거. 예약 실행이 조용히 죽어도
    #   이 시각이 안 움직이는 것으로 바로 안다(로그는 조치가 있을 때만 쌓이므로).
    if act:
        save_state({"last_check": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "last_head": head})

    runs = [r for r in list_runs(root) if r.get("event") != "pull_request"]
    mine = [r for r in runs if r.get("headSha") == head]
    ok = [r for r in mine if r.get("conclusion") == "success"]
    live = [r for r in mine if r.get("status") in ("queued", "in_progress", "waiting", "requested")]

    print(f"main 머리      : {head[:8]}  ({head_age:.0f}분 전 커밋)")
    print(f"이 커밋의 런   : 성공 {len(ok)}건 / 진행중 {len(live)}건 / 전체 {len(mine)}건")

    # ① 되돌리기 위험 — main 보다 뒤처진 런이 아직 살아 있는가
    behind = [
        r for r in runs
        if r.get("status") in ("queued", "in_progress", "waiting", "requested")
        and r.get("headSha") != head
        and is_ancestor(root, r["headSha"], head)
    ]
    for r in behind:
        rid, sha, a = r["databaseId"], r["headSha"][:8], age_min(r["createdAt"])
        if a < STALE_MIN:
            print(f"  · {rid} ({sha}) 뒤처짐 — 아직 {a:.0f}분, 지켜봄")
            continue
        if deploy_job_started(root, rid):
            log(f"⚠️  {rid} ({sha}) 이 이미 배포 단계 진입 — 취소 안 함(SSH 중단은 서버를 깨뜨림). "
                f"끝난 뒤 재배포로 덮는다.")
            continue
        if not act:
            print(f"  · [예정] {rid} ({sha}) 취소 — main 보다 뒤처진 런")
            continue
        good, msg = cancel(root, rid)
        log(f"{'✅ 취소함' if good else '⏳ 취소 거부(다음에 재시도)'} {rid} ({sha}) {msg}")

    # ② 반영 안 됨 — 푸시가 런을 못 만들었으면 내가 만든다
    if ok:
        print("✅ 최신 main 이 배포 성공으로 반영됨 — 할 일 없음")
        return 0
    if live:
        print("⏳ 최신 main 배포가 진행 중 — 기다림")
        return 0
    if head_age < GRACE_MIN:
        print(f"⏳ 아직 {head_age:.0f}분 — {GRACE_MIN}분까지 기다림")
        return 0

    state = load_state()
    last_sha, last_at = state.get("dispatched_sha"), state.get("dispatched_at", 0)
    since = (time.time() - last_at) / 60.0
    if last_sha == head and since < COOLDOWN_MIN:
        print(f"⏳ 같은 커밋을 {since:.0f}분 전에 이미 밀어 넣음 — {COOLDOWN_MIN}분까지 대기")
        return 0

    if not act:
        print(f"  · [예정] workflow_dispatch 로 {head[:8]} 배포 밀어 넣기")
        return 0

    good, msg = dispatch(root)
    if good:
        save_state({"dispatched_sha": head, "dispatched_at": time.time()})
        log(f"🚀 배포 수동 실행 밀어 넣음 — {head[:8]} (푸시가 런을 못 만듦, {head_age:.0f}분 경과)")
        return 0
    log(f"❌ workflow_dispatch 실패 — {msg}")
    return 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
