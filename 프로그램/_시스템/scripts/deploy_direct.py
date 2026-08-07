# -*- coding: utf-8 -*-
"""직접 배포 — GitHub Actions 가 **완전히** 죽어도 개발 PC 에서 라이브로 올린다.

언제 쓰나:
    감시견(deploy_watchdog.py)은 "푸시가 런을 못 만든" 경우를 수동 실행으로 해소한다.
    그런데 수동 실행마저 막히면 배포할 길이 하나도 없다 — 그때 이 스크립트를 쓴다.
    평소엔 쓸 일이 없다. **평소 배포는 언제나 GitHub 워크플로가 정본이다.**

🔴 배포 절차를 여기에 베껴 쓰지 않는다 (중복 = 언젠가 갈라진다):
    워크플로 YAML 에서 서버 실행 블록을 **그대로 꺼내** 돌린다. 즉 CI 가 하는 일과
    글자 단위로 같다. YAML 이 바뀌면 여기도 저절로 따라간다.
    모르는 `${{ }}` 식이 하나라도 남으면 **배포를 시작조차 하지 않는다** — 조용히
    다른 설정으로 나가느니 멈추는 게 낫다.

🔴 검사를 건너뛰지 않는다:
    CSS 괄호 검사 + 전체 테스트를 **먼저 로컬에서** 돌린다. 이 관문은 죽은 CSS 가
    라이브로 나갔던 실제 사고 뒤에 생긴 것이다. CI 를 우회한다고 관문까지 우회하면
    이 스크립트가 그 사고를 다시 부른다.

🔴 지금 돌고 있는 것과 같은 설정으로 올린다:
    DATABASE_URL 은 **현재 서비스 중인 컨테이너에서 읽어** 그대로 쓴다(같은 DB 보장).
    실전송·실등록 같은 위험 스위치는 켜져 있어도 **끄고** 올린다(재배포 시 닫힘 규칙과 동일).
    안전 방향 스위치(백필 킬스위치)는 살려서 올린다.

쓰는 법:
    python scripts/deploy_direct.py --dry-run   # 무엇을 할지·어떤 설정으로 갈지만 출력
    python scripts/deploy_direct.py             # 실제 배포 (origin/main 을 그대로)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

HOST = "54.116.196.90"                       # LIGHTSAIL_HOST (비밀 아님 — 공개 IP)
KEY = Path.home() / ".ssh" / "moum_lightsail"  # 개발 PC 전용 열쇠 (짝 공개키는 저장소에)
WORKFLOW_REL = ".github/workflows/aws-lightsail-deploy.yml"
DEPLOY_STEP = "코드 압축"                     # 이 이름으로 서버 실행 블록을 찾는다
# 🔴 원단(서버)으로 직접 두드린다 — 워크플로 헬스체크와 같은 문.
#   mou-m.com 으로 가면 Cloudflare 가 파이썬 요청에 **403** 을 준다(curl 은 200).
#   실측: 배포가 완전히 성공했는데도 헬스체크만 실패해 "배포 실패"로 잘못 보고했다.
HEALTH = f"http://{HOST}/health"

SSH = ["ssh", "-i", "", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]

# 위험 방향 스위치 — GitHub 를 못 읽으면 **끈다**(켜진 채 나가느니 꺼진 채 나간다)
DANGER_VARS = {
    "LIVE_UPLOAD_ARMED": "-e MOUM_LIVE_UPLOAD=1",
    "LIVE_REGISTER_ARMED": "-e LIVE_REGISTER_ARMED=1",
    "PERIOD_PROBE_ARMED": "-e PERIOD_PROBE=1",
    "UPLOAD_RATE_PROBE_ARMED": "-e UPLOAD_RATE_PROBE=1",
}
# 안전 방향 스위치 — GitHub 를 못 읽으면 **돌고 있는 컨테이너에서 물려받는다**
SAFE_VARS = {"MOUM_BACKFILL_OFF": "-e MOUM_BACKFILL_OFF=1"}


def sh(args: list[str], cwd: Path | None = None, check: bool = False) -> tuple[int, str]:
    p = subprocess.run(args, cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        raise RuntimeError(f"실패({p.returncode}): {' '.join(args[:3])}…\n{out[-1500:]}")
    return p.returncode, out


def ssh_key_args() -> list[str]:
    a = list(SSH)
    a[2] = str(KEY)
    return a


def bash_path(p: Path) -> str:
    """C:\\Users\\x → /c/Users/x (Git Bash 가 알아듣는 꼴)."""
    s = str(p).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":
        s = "/" + s[0].lower() + s[2:]
    return s


def find_bash() -> str:
    """Git Bash 를 **콕 집는다**.

    PATH 의 `bash` 는 Windows 의 WSL 런처(System32\\bash.exe)일 수 있다. 그러면 리눅스
    VM 을 띄우려다 실패한다 — 실측: `Bash/Service/CreateInstance/CreateVm/HCS/0x800705aa`.
    터미널에서 돌릴 땐 Git 이 PATH 앞에 있어 우연히 맞았고, 예약 실행·PowerShell 에서
    돌리자 틀렸다. 우연에 기대지 않는다.
    """
    cands: list[Path] = []
    rc, out = sh(["git", "--exec-path"])
    if rc == 0 and out.strip():
        for anc in Path(out.strip().splitlines()[-1]).parents:
            for sub in (("usr", "bin", "bash.exe"), ("bin", "bash.exe")):
                if (anc.joinpath(*sub)).exists():
                    cands.append(anc.joinpath(*sub))
                    break
            if cands:
                break
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for sub in ("Git/usr/bin/bash.exe", "Git/bin/bash.exe", "Programs/Git/usr/bin/bash.exe"):
            q = Path(base) / sub
            if q.exists():
                cands.append(q)
    w = shutil.which("bash")
    if w and "system32" not in w.lower():
        cands.append(Path(w))
    if not cands:
        raise RuntimeError("Git Bash 를 못 찾았다 — Git for Windows 가 설치돼 있어야 한다")
    return str(cands[0])


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / ".git").exists():
            return p
    raise RuntimeError("git 저장소를 못 찾음")


# ── ① 지금 라이브가 무엇으로 돌고 있나 (설정을 물려받기 위해) ─────────────────
def running_container() -> str | None:
    rc, out = sh(ssh_key_args() + [
        f"ubuntu@{HOST}",
        "sudo docker ps --format '{{.Names}}' | grep -E '^modeumjeon(_[0-9]+)?$' | head -1",
    ])
    name = out.strip().splitlines()[-1].strip() if rc == 0 and out.strip() else ""
    return name or None


def container_env(name: str) -> dict[str, str]:
    rc, out = sh(ssh_key_args() + [
        f"ubuntu@{HOST}",
        f"sudo docker inspect -f '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}' {name}",
    ])
    env: dict[str, str] = {}
    if rc != 0:
        return env
    for line in out.splitlines():
        if "=" in line and not line.startswith(("sudo", "Error")):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()      # 뒤에 나온 값이 이긴다 = docker 와 같은 규칙
    return env


def ci_deploy_in_flight(root: Path) -> list[str]:
    """CI 배포가 지금 돌고 있나 — 돌고 있으면 직접배포는 하면 안 된다.

    2026-07-21 18:32 에 푸시 배포와 수동 배포가 11초 차로 겹쳐 같은 ~/app 빌드 폴더와
    같은 이미지 태그를 서로 덮어써 5분간 502 가 났다. 워크플로는 그 뒤 concurrency
    그룹(deploy-live)으로 자기들끼리는 막았지만, **저장소 밖에서 도는 이 스크립트는
    그 그룹에 안 들어간다.** 그래서 여기서 직접 확인한다.
    """
    rc, out = sh(["gh", "run", "list", "--workflow", "aws-lightsail-deploy.yml",
                  "--limit", "20", "--json", "databaseId,status,event,headSha"], cwd=root)
    if rc != 0:
        return []          # GitHub 이 아예 안 읽히는 상황 = 애초에 CI 도 못 도는 상황
    try:
        runs = json.loads(out)
    except ValueError:
        return []
    return [f"{r['databaseId']} ({r['headSha'][:8]}, {r['event']})" for r in runs
            if r.get("status") in ("queued", "in_progress", "waiting", "requested")
            and r.get("event") != "pull_request"]


def repo_vars(root: Path) -> dict[str, str] | None:
    """GitHub 저장소 변수 — 읽히면 CI 와 똑같이, 안 읽히면 None(=보수적 기본값)."""
    rc, out = sh(["gh", "api", "repos/{owner}/{repo}/actions/variables",
                  "--jq", "[.variables[]|{(.name):.value}]|add"], cwd=root)
    if rc != 0:
        return None
    try:
        return json.loads(out) or {}
    except ValueError:
        return None


# ── ② 워크플로에서 서버 실행 블록을 그대로 꺼낸다 ────────────────────────────
def extract_deploy_run(export: Path) -> str:
    import yaml
    doc = yaml.safe_load((export / WORKFLOW_REL).read_text(encoding="utf-8"))
    for step in doc["jobs"]["deploy"]["steps"]:
        if DEPLOY_STEP in (step.get("name") or ""):
            return step["run"]
    raise RuntimeError(f"워크플로에서 '{DEPLOY_STEP}' 단계를 못 찾음 — YAML 이 바뀌었나?")


def substitute(script: str, subs: dict[str, str]) -> str:
    """`${{ … }}` 를 실제 값으로. **모르는 식이 남으면 예외** — 조용한 오배포 차단."""
    unknown: list[str] = []

    def repl(m: re.Match[str]) -> str:
        inner = " ".join(m.group(1).split())
        if inner in subs:
            return subs[inner]
        unknown.append(inner)
        return m.group(0)

    out = re.sub(r"\$\{\{(.*?)\}\}", repl, script, flags=re.S)
    if unknown:
        raise RuntimeError(
            "워크플로에 모르는 식이 있어 배포를 멈춘다(설정이 달라질 수 있음):\n  - "
            + "\n  - ".join(sorted(set(unknown)))
            + "\n→ scripts/deploy_direct.py 의 치환표에 이 식을 추가하고 다시 실행할 것."
        )
    return out


def build_subs(sha: str, dburl: str, flags: dict[str, str]) -> dict[str, str]:
    return {
        "github.sha": sha,
        "secrets.LIGHTSAIL_HOST": HOST,
        "secrets.DATABASE_URL": dburl,
        "github.event.inputs.arm_live_confirm == 'true' && '-e MOUM_LIVE_CONFIRM=1' || ''": "",
        "(vars.LIVE_UPLOAD_ARMED == '1' || github.event.inputs.arm_live_upload == 'true') "
        "&& '-e MOUM_LIVE_UPLOAD=1' || ''": flags.get("LIVE_UPLOAD_ARMED", ""),
        "vars.PERIOD_PROBE_ARMED == '1' && '-e PERIOD_PROBE=1' || ''":
            flags.get("PERIOD_PROBE_ARMED", ""),
        "vars.UPLOAD_RATE_PROBE_ARMED == '1' && '-e UPLOAD_RATE_PROBE=1' || ''":
            flags.get("UPLOAD_RATE_PROBE_ARMED", ""),
        "vars.MOUM_BACKFILL_OFF == '1' && '-e MOUM_BACKFILL_OFF=1' || ''":
            flags.get("MOUM_BACKFILL_OFF", ""),
        "vars.LIVE_REGISTER_ARMED == '1' && '-e LIVE_REGISTER_ARMED=1' || ''":
            flags.get("LIVE_REGISTER_ARMED", ""),
    }


# ── ③ 관문: CI 가 돌리는 검사를 로컬에서 먼저 ────────────────────────────────
def gate(app: Path) -> None:
    print("── 배포 전 검사 (CI 와 같은 것) ──")
    rc, out = sh([sys.executable, "scripts/check_css_balanced.py"], cwd=app)
    print(out.strip()[-800:] or "(출력 없음)")
    if rc != 0:
        raise RuntimeError("CSS 괄호 짝 검사 실패 — 배포 중단")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "-ra"],
                       cwd=str(app), env=env, text=True, encoding="utf-8", errors="replace",
                       capture_output=True)
    print((p.stdout or "")[-2500:])
    if p.returncode != 0:
        raise RuntimeError("테스트 실패 — 배포 중단 (라이브는 그대로 유지)")
    print("✅ 검사 통과")


def health(timeout_s: int = 240) -> bool:
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            with urllib.request.urlopen(HEALTH, timeout=20) as r:
                if r.status == 200:
                    print("헬스체크:", r.read(200).decode("utf-8", "replace"))
                    return True
        except OSError:
            pass
        time.sleep(10)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="설정만 확인하고 배포는 안 함")
    ap.add_argument("--force", action="store_true",
                    help="⚠️ CI 배포가 돌고 있어도 강행 — 겹치면 502 가 난다")
    ap.add_argument("--skip-gate", action="store_true",
                    help="⚠️ 검사 건너뛰기 — 죽은 CSS 가 라이브로 나간 사고가 실제로 있었다")
    args = ap.parse_args()

    if not KEY.exists():
        print(f"❌ 열쇠가 없다: {KEY}\n   먼저 GitHub 워크플로로 한 번 배포해 공개키를 서버에 심어야 한다.")
        return 2

    root = repo_root()
    sh(["git", "fetch", "origin", "main", "--quiet"], cwd=root)
    _, sha = sh(["git", "rev-parse", "origin/main"], cwd=root, check=True)
    sha = sha.strip()
    print(f"배포 대상 : origin/main {sha[:8]}  (작업본이 아니라 **main 그대로**)")

    busy = ci_deploy_in_flight(root)
    if busy and not args.force:
        print("❌ CI 배포가 돌고 있다 — 겹치면 서로 덮어써 502 가 난다(2026-07-21 실사고). 중단.\n"
              "   도는 런: " + ", ".join(busy) + "\n"
              "   그게 끝나길 기다리거나, 정말 겹쳐도 된다면 --force.")
        return 2

    # 지금 라이브 설정을 물려받는다
    cur = running_container()
    if not cur:
        print("❌ 서버에 SSH 로 붙지 못했거나 도는 컨테이너가 없다 — 중단")
        return 2
    cenv = container_env(cur)
    dburl = cenv.get("DATABASE_URL", "")
    print(f"현재 컨테이너 : {cur}")
    print("DATABASE_URL  : " + ("현재 것 그대로 물려받음(서울)" if "ap-northeast-2" in dburl
                                else "미설정/형식불일치 → app.env 유지"))

    rvars = repo_vars(root)
    flags: dict[str, str] = {}
    if rvars is None:
        print("⚠️ GitHub 저장소 변수를 못 읽음 — 위험 스위치는 끄고, 안전 스위치만 물려받는다")
        for name, flag in SAFE_VARS.items():
            if cenv.get(name.replace("_ARMED", "")) == "1" or cenv.get("MOUM_BACKFILL_OFF") == "1":
                flags[name] = flag
    else:
        for name, flag in {**DANGER_VARS, **SAFE_VARS}.items():
            if rvars.get(name) == "1":
                flags[name] = flag
    on = [k for k in flags] or ["(없음 — 전부 기본 OFF)"]
    print("켜서 나갈 스위치 :", ", ".join(on))

    # main 을 그대로 꺼낸다 (지저분한 작업본이 라이브로 새지 않게)
    tmp = Path(tempfile.mkdtemp(prefix="moum_deploy_"))
    try:
        tar = tmp / "src.tar"
        sh(["git", "archive", "--format=tar", "-o", str(tar), sha], cwd=root, check=True)
        export = tmp / "src"
        export.mkdir()
        # 풀기는 파이썬으로 — Windows 의 tar.exe 에 `/c/...` 꼴 경로를 넘기면
        #   "Failed to open" 으로 죽는다(실측). 표준 라이브러리엔 그 함정이 없다.
        with tarfile.open(tar) as tf:
            tf.extractall(export, filter="data")

        script = substitute(extract_deploy_run(export), build_subs(sha, dburl, flags))
        script = script.replace("~/.ssh/ls_key", bash_path(KEY))
        # 🔴 CR 제거 — Windows 체크아웃(autocrlf)이라 YAML 이 CRLF 로 나온다. 그대로 bash 에
        #   넣으면 첫 줄부터 `set: -: invalid option` 으로 죽는다(실측). 서버에 닿기도 전에
        #   멈추니 안전하긴 하나, 정작 필요할 때 못 쓰면 이 스크립트는 없는 것과 같다.
        script = script.replace("\r\n", "\n").replace("\r", "\n")

        if args.dry_run:
            print("\n── [예정] 서버에서 돌 스크립트 앞 40줄 ──")
            print("\n".join(script.splitlines()[:40]))
            print("…(이하 워크플로와 동일)")
            return 0

        if not args.skip_gate:
            gate(export / "프로그램" / "_시스템")
        else:
            print("⚠️⚠️ 검사를 건너뛴다 — 죽은 CSS 가 라이브로 나갔던 그 관문이다")

        print("── 서버로 전송·무중단 교체 (워크플로와 같은 절차) ──")
        bash = find_bash()
        print(f"(bash: {bash})")
        p = subprocess.run([bash, "-e"], input=script, cwd=str(export),
                           text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            print("❌ 배포 실패 — 새 컨테이너는 폐기되고 라이브는 이전 것이 그대로 유지된다")
            return 1

        print("── 배포 후 헬스체크 ──")
        if not health():
            print("❌ 헬스체크 실패 — 서버 상태를 확인할 것")
            return 1
        print(f"✅ 직접 배포 완료 — origin/main {sha[:8]} 가 라이브")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    try:
        # line_buffering: 로그로 리다이렉트해도 진행 상황이 **그때그때** 보이게.
        #   (없으면 끝날 때까지 빈 파일이라, 도는 중인지 굳은 건지 알 수 없다)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        pass
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as e:
        print(f"❌ {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
