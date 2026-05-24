@echo off
REM 모음전 팀 공유 시스템 (Fly.io 배포본) — Chrome 강제 (사용자 명시 2026-05-25)
REM start "" 는 OS 기본 브라우저 (Edge 등) — Chrome 강제로 명시.

set URL=https://modeumjeon-team-share.fly.dev

REM Chrome 절대경로 후보 (우선순위)
set CHROME1="%ProgramFiles%\Google\Chrome\Application\chrome.exe"
set CHROME2="%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
set CHROME3="%LocalAppData%\Google\Chrome\Application\chrome.exe"

if exist %CHROME1% (
    start "" %CHROME1% "%URL%"
) else if exist %CHROME2% (
    start "" %CHROME2% "%URL%"
) else if exist %CHROME3% (
    start "" %CHROME3% "%URL%"
) else (
    REM Chrome 없으면 fallback - 기본 브라우저
    start "" "%URL%"
)
