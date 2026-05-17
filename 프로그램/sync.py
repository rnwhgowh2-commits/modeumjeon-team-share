"""
sync.py — 기존 → 신규 단방향 미러 동기화 스크립트

사용법:
  python sync.py                  # 대화형 (변경 보여주고 사용자 승인 후 적용)
  python sync.py --dry-run        # 변경 사항만 출력, 적용 안 함
  python sync.py --scheduled      # 자동 실행 (승인 없이 적용 + 로그 + 토스트)
  python sync.py --force          # 승인 없이 적용 (수동, 로그 없이)

룰:
  - 기존 → 신규 단방향 (신규 → 기존 절대 안 함)
  - .sync-ignore 매칭 경로/파일 제외
  - 변경 감지: 파일 mtime + size 비교 (robocopy 와 동일 방식)
  - schema 변경 (lemouton/**/models*.py, webapp/**/models*.py) 감지 시 경고
  - 결과: sync.log append + (scheduled 모드 시) 토스트 알림
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import shutil
import sys
from pathlib import Path

# Windows cp949 콘솔에서 UTF-8 / 이모지 출력 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ───────────────────────────────────────────────────────────
# 설정
# ───────────────────────────────────────────────────────────
SOURCE = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
PROJECT_ROOT = Path(r"C:\dev\모음전 프로젝트")
PROGRAM_DIR = PROJECT_ROOT / "프로그램"
TARGET = PROGRAM_DIR / "_시스템"
IGNORE_FILE = PROJECT_ROOT / ".sync-ignore"
LOG_FILE = PROGRAM_DIR / "sync.log"

SCHEMA_PATTERNS = [
    "lemouton/**/models*.py",
    "lemouton/**/*/models.py",
    "webapp/**/models*.py",
    "shared/db.py",
]


# ───────────────────────────────────────────────────────────
# .sync-ignore 파싱
# ───────────────────────────────────────────────────────────
def load_ignore_patterns() -> list[str]:
    """주석·빈 줄 제외하고 ignore 패턴 리스트 반환."""
    if not IGNORE_FILE.exists():
        return []
    patterns: list[str] = []
    for line in IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # line-level 패턴 (config.py:DATABASE_URL) 은 별도 처리 예정 — 지금은 파일 단위만
        if ":" in s and not s.endswith("/"):
            continue
        patterns.append(s)
    return patterns


def matches_ignore(rel_path: str, patterns: list[str]) -> bool:
    """rel_path 가 ignore 패턴 중 하나에라도 매칭되면 True.

    rel_path 는 POSIX 스타일 (forward slash). 디렉토리 패턴 (끝에 /) 은 prefix 매칭.
    """
    rp = rel_path.replace("\\", "/")
    for pat in patterns:
        p = pat.replace("\\", "/")
        if p.endswith("/"):
            # 디렉토리 prefix 매칭
            dir_prefix = p.rstrip("/")
            if rp == dir_prefix or rp.startswith(dir_prefix + "/"):
                return True
        else:
            # glob 매칭 (basename 또는 전체 경로)
            if fnmatch.fnmatch(rp, p):
                return True
            base = rp.rsplit("/", 1)[-1]
            if fnmatch.fnmatch(base, p):
                return True
    return False


# ───────────────────────────────────────────────────────────
# diff 계산
# ───────────────────────────────────────────────────────────
def file_signature(path: Path) -> tuple[int, int]:
    """파일 비교용 시그니처 (크기, mtime 정수부)."""
    st = path.stat()
    return (st.st_size, int(st.st_mtime))


def compute_diff(patterns: list[str]) -> dict[str, list[str]]:
    """기존 ↔ 신규 차이 계산.

    Returns:
        {
            "to_add":    [rel_path, ...],   # 기존에 있고 신규에 없음
            "to_update": [rel_path, ...],   # 양쪽 있는데 다름
            "to_delete": [rel_path, ...],   # 신규에 있고 기존에 없음 (ignore 제외)
            "schema":    [rel_path, ...],   # schema 파일 변경 감지
        }
    """
    src_files: dict[str, tuple[int, int]] = {}
    dst_files: dict[str, tuple[int, int]] = {}

    if SOURCE.exists():
        for p in SOURCE.rglob("*"):
            if p.is_file():
                rel = p.relative_to(SOURCE).as_posix()
                if matches_ignore(rel, patterns):
                    continue
                try:
                    src_files[rel] = file_signature(p)
                except (OSError, PermissionError):
                    pass

    if TARGET.exists():
        for p in TARGET.rglob("*"):
            if p.is_file():
                rel = p.relative_to(TARGET).as_posix()
                if matches_ignore(rel, patterns):
                    continue
                try:
                    dst_files[rel] = file_signature(p)
                except (OSError, PermissionError):
                    pass

    to_add: list[str] = []
    to_update: list[str] = []
    to_delete: list[str] = []
    schema_changes: list[str] = []

    for rel, sig in src_files.items():
        if rel not in dst_files:
            to_add.append(rel)
        elif sig != dst_files[rel]:
            to_update.append(rel)

    for rel in dst_files:
        if rel not in src_files:
            to_delete.append(rel)

    # schema 변경 감지
    for rel in to_add + to_update:
        for pat in SCHEMA_PATTERNS:
            if fnmatch.fnmatch(rel, pat):
                schema_changes.append(rel)
                break

    return {
        "to_add": sorted(to_add),
        "to_update": sorted(to_update),
        "to_delete": sorted(to_delete),
        "schema": sorted(set(schema_changes)),
    }


# ───────────────────────────────────────────────────────────
# 적용
# ───────────────────────────────────────────────────────────
def apply_diff(diff: dict[str, list[str]], delete_enabled: bool = False) -> dict[str, int]:
    """diff 를 신규 폴더에 적용. 적용 카운트 반환."""
    counts = {"added": 0, "updated": 0, "deleted": 0, "errors": 0}

    for rel in diff["to_add"] + diff["to_update"]:
        src = SOURCE / rel
        dst = TARGET / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if rel in diff["to_add"]:
                counts["added"] += 1
            else:
                counts["updated"] += 1
        except (OSError, PermissionError) as e:
            counts["errors"] += 1
            print(f"  [ERROR] {rel}: {e}", file=sys.stderr)

    if delete_enabled:
        for rel in diff["to_delete"]:
            dst = TARGET / rel
            try:
                dst.unlink()
                counts["deleted"] += 1
            except (OSError, PermissionError) as e:
                counts["errors"] += 1
                print(f"  [ERROR delete] {rel}: {e}", file=sys.stderr)

    return counts


# ───────────────────────────────────────────────────────────
# 알림 (Windows 토스트)
# ───────────────────────────────────────────────────────────
def show_toast(title: str, message: str) -> None:
    """Windows 토스트 알림 (BurntToast 또는 PowerShell ToastNotification 폴백)."""
    import subprocess

    # BurntToast 가 있으면 사용, 없으면 단순 PowerShell New-BurntToastNotification 시도
    # 안 되면 기본 Windows Forms 트레이 알림으로 폴백
    ps_script = f"""
$title = '{title.replace("'", "''")}'
$msg = '{message.replace("'", "''")}'

try {{
    # Method 1: BurntToast (있으면)
    if (Get-Module -ListAvailable -Name BurntToast) {{
        Import-Module BurntToast
        New-BurntToastNotification -Text $title, $msg
        exit 0
    }}
}} catch {{}}

try {{
    # Method 2: Windows Runtime ToastNotification (Win10+ 내장)
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

    $template = @"
<toast><visual><binding template="ToastGeneric"><text>$title</text><text>$msg</text></binding></visual></toast>
"@
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('모음전 프로젝트').Show($toast)
    exit 0
}} catch {{}}

# Method 3: Tray balloon 폴백
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = $title
$notify.BalloonTipText = $msg
$notify.Visible = $true
$notify.ShowBalloonTip(8000)
Start-Sleep -Seconds 9
$notify.Dispose()
"""
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except Exception as e:
        print(f"  [WARN] 토스트 알림 실패: {e}", file=sys.stderr)


# ───────────────────────────────────────────────────────────
# 로그
# ───────────────────────────────────────────────────────────
def append_log(entry: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")


# ───────────────────────────────────────────────────────────
# 출력 헬퍼
# ───────────────────────────────────────────────────────────
def print_diff_summary(diff: dict[str, list[str]], verbose: bool = False) -> None:
    n_add = len(diff["to_add"])
    n_upd = len(diff["to_update"])
    n_del = len(diff["to_delete"])
    n_sch = len(diff["schema"])

    print(f"📊 변경 사항: 추가 {n_add} · 수정 {n_upd} · 삭제 {n_del}")
    if n_sch > 0:
        print(f"⚠️  Schema 파일 변경 감지: {n_sch} 건 (Supabase 마이그레이션 필요할 수 있음)")
        for rel in diff["schema"]:
            print(f"     - {rel}")

    if verbose:
        if n_add:
            print("\n➕ 추가:")
            for rel in diff["to_add"][:30]:
                print(f"     + {rel}")
            if n_add > 30:
                print(f"     ... 외 {n_add - 30}건")
        if n_upd:
            print("\n✏️  수정:")
            for rel in diff["to_update"][:30]:
                print(f"     ~ {rel}")
            if n_upd > 30:
                print(f"     ... 외 {n_upd - 30}건")
        if n_del:
            print("\n🗑  삭제 (신규에만 있음):")
            for rel in diff["to_delete"][:30]:
                print(f"     - {rel}")
            if n_del > 30:
                print(f"     ... 외 {n_del - 30}건")


# ───────────────────────────────────────────────────────────
# 메인
# ───────────────────────────────────────────────────────────
def auto_git_push(counts: dict[str, int]) -> str | None:
    """변경 사항을 자동으로 git commit + push (GitHub Actions → Fly.io 자동 배포 트리거).

    Returns: 결과 메시지 (성공/실패), 변경 없으면 None.
    """
    import subprocess
    if counts["added"] + counts["updated"] + counts["deleted"] == 0:
        return None
    try:
        # git status 로 stage 대상 있는지 확인
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None  # 변경 없음 (.gitignore 가 모두 잡았을 수도)

        # add + commit + push
        subprocess.run(["git", "-C", str(PROJECT_ROOT), "add", "."], check=True, timeout=30)
        msg = f"Auto-sync: {counts['added']} added, {counts['updated']} updated, {counts['deleted']} deleted"
        commit = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "commit", "-m", msg],
            capture_output=True, text=True, timeout=30,
        )
        if commit.returncode != 0:
            # 변경 없거나 .gitignore 가 모두 잡음 — 정상
            return None
        push = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "push", "origin", "main"],
            capture_output=True, text=True, timeout=120,
        )
        if push.returncode != 0:
            return f"⚠️ git push 실패: {push.stderr[:100]}"
        return f"✅ GitHub push 완료 → Fly.io 자동 배포 시작"
    except Exception as e:
        return f"⚠️ git 자동화 에러: {str(e)[:100]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="기존 → 신규 단방향 미러 동기화")
    parser.add_argument("--dry-run", action="store_true", help="변경 출력만, 적용 안 함")
    parser.add_argument("--scheduled", action="store_true", help="자동 실행 (승인 없이 + 토스트)")
    parser.add_argument("--force", action="store_true", help="승인 없이 적용 (토스트 없이)")
    parser.add_argument("--verbose", "-v", action="store_true", help="변경 파일 목록 출력")
    parser.add_argument("--delete", action="store_true", help="신규에만 있는 파일 삭제 동기화")
    parser.add_argument("--no-git-push", action="store_true", help="--scheduled/--force 시 자동 git push 끄기")
    args = parser.parse_args()

    started_at = dt.datetime.now()
    print(f"🔄 동기화 시작: {started_at.isoformat(timespec='seconds')}")
    print(f"   Source: {SOURCE}")
    print(f"   Target: {TARGET}")

    if not SOURCE.exists():
        print(f"❌ Source 폴더 없음: {SOURCE}", file=sys.stderr)
        return 2
    if not TARGET.exists():
        print(f"❌ Target 폴더 없음: {TARGET}", file=sys.stderr)
        return 2

    patterns = load_ignore_patterns()
    diff = compute_diff(patterns)

    print_diff_summary(diff, verbose=args.verbose or args.dry_run)

    total_changes = len(diff["to_add"]) + len(diff["to_update"]) + (len(diff["to_delete"]) if args.delete else 0)

    if total_changes == 0:
        print("✅ 변경 없음 (이미 동기화 상태)")
        if args.scheduled:
            append_log(f"{started_at.isoformat(timespec='seconds')} | 변경 없음")
            show_toast("모음전 동기화 완료", "변경 없음 (이미 동기화 상태)")
        return 0

    if args.dry_run:
        print("\n[DRY-RUN] 실제 적용 안 함.")
        return 0

    if not (args.scheduled or args.force):
        # 대화형 승인
        ans = input(f"\n위 {total_changes}건을 신규에 적용할까요? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("취소됨.")
            return 1

    counts = apply_diff(diff, delete_enabled=args.delete)
    elapsed = (dt.datetime.now() - started_at).total_seconds()

    print(f"\n✅ 적용 완료 ({elapsed:.1f}초)")
    print(f"   추가 {counts['added']} · 수정 {counts['updated']} · 삭제 {counts['deleted']} · 에러 {counts['errors']}")

    schema_alert = ""
    if diff["schema"]:
        schema_alert = f" | ⚠️ schema {len(diff['schema'])}건"

    log_line = (
        f"{started_at.isoformat(timespec='seconds')} | "
        f"add {counts['added']} upd {counts['updated']} del {counts['deleted']} err {counts['errors']}"
        f"{schema_alert} | {elapsed:.1f}s"
    )
    append_log(log_line)

    # ─── 자동 git push (--scheduled 또는 --force 시 기본 ON) ───
    git_msg = None
    if (args.scheduled or args.force) and not args.no_git_push:
        git_msg = auto_git_push(counts)
        if git_msg:
            print(git_msg)
            append_log(f"{started_at.isoformat(timespec='seconds')} | {git_msg}")

    if args.scheduled:
        toast_title = "모음전 동기화 완료"
        toast_msg = (
            f"추가 {counts['added']}, 수정 {counts['updated']}, 삭제 {counts['deleted']}"
            + (f", Schema 변경 {len(diff['schema'])}건 ⚠️" if diff["schema"] else "")
            + (f", 에러 {counts['errors']}건" if counts["errors"] else "")
            + ("\n→ GitHub push + 자동 배포 시작" if git_msg and "✅" in git_msg else "")
        )
        show_toast(toast_title, toast_msg)

    return 0 if counts["errors"] == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
